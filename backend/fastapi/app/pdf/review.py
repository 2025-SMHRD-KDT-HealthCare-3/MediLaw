"""멀티에이전트 E — 세그먼트별 위험판정(RAG 근거 + LLM 판단).

흐름: 각 Segment.text 로 hybrid_search → 근거 확보(코드가 근거 결정)
     → 세그먼트들 + 각자 근거를 한 프롬프트에 묶어 LLM 1회 호출
     → {level, reason, after} 만 LLM 이 판단 → RiskResult 채움.

핵심 원칙(다른 에이전트 계약과 동일):
  - **근거(law) 연결은 코드가 담당한다.** LLM 은 근거 번호/인용을 만들지 않는다.
    law 는 그 세그먼트에 대해 검색해 둔 hits 의 label 에서 코드가 채운다.
  - before = 세그먼트 원문(seg.text).
  - LLM 호출은 세그먼트당 1회가 아니라 **전체 묶어 1회**(지연·비용 방어).
  - LLM 사용 불가(LLMUnavailable) 시 risk 미채움(graceful).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from app import llm
from app.db import db, has_embeddings
from app.pdf.schema import RiskResult, Segment
from app.rag import embed_queries, fmt_article_label, hybrid_search
from app.schemas import Hit

_VALID_LEVELS = {"none", "low", "med", "high"}

# 의료광고 핵심 금지조문 — 광고검토는 입력이 '광고'임이 전제이므로, 검색 결과가 이 조문을
# 못 끌어와도(흔함) 미감지가 나지 않게, ad 세그먼트 근거에 항상 주입한다.
#   제56조(의료광고의 금지 등) · 제27조(무면허+환자 유인·알선 제3항) · 제57조(사전심의)
_AD_CORE_ARTICLES = [("의료법", "56"), ("의료법", "27"), ("의료법", "57")]
_AD_CORE_SNIPPET = 600  # 제56조 경험담(≈340)·제27조 유인(≈537)이 보이도록.


@lru_cache(maxsize=1)
def _ad_core_hits() -> tuple:
    """의료광고 핵심 금지조문 Hit(프로세스 1회 캐시). DB 문제 시 빈 튜플(graceful)."""
    out: list[Hit] = []
    try:
        for law, art in _AD_CORE_ARTICLES:
            row = db().execute(
                """SELECT a.id, a.article_no, a.article_title, a.content,
                          s.name AS law_name, s.trust_grade, s.effective_from, s.source_url
                   FROM articles a JOIN statutes s ON s.id = a.statute_id
                   WHERE s.name = ? AND a.article_no = ?
                   ORDER BY a.id LIMIT 1""",
                (law, art),
            ).fetchone()
            if not row:
                continue
            out.append(Hit(
                source_type="statute", source_id=row["id"],
                label=fmt_article_label(row["law_name"], row["article_no"], row["article_title"] or ""),
                title=row["article_title"] or "",
                snippet=(row["content"] or "")[:_AD_CORE_SNIPPET],
                score=0.0, trust_grade=row["trust_grade"] or "법령",
                effective_from=row["effective_from"], source_url=row["source_url"] or "",
            ))
    except Exception:  # noqa: BLE001 — DB 문제 시 주입 생략(검색만으로 graceful)
        return tuple()
    return tuple(out)


def _inject_ad_core(segments: list[Segment], per_segment: list[list]) -> None:
    """ad 세그먼트의 근거 앞에 의료광고 핵심 금지조문을 주입(중복 제외, in-place)."""
    core = _ad_core_hits()
    if not core:
        return
    for i, seg in enumerate(segments):
        if seg.doc_type != "ad":
            continue
        existing = {h.source_id for h in per_segment[i]}
        prepend = [h for h in core if h.source_id not in existing]
        if prepend:
            per_segment[i] = prepend + per_segment[i]

# doc_type 별 점검 관점(시스템 프롬프트에 끼워 넣는 분기). 없으면 일반 프롬프트.
_DOCTYPE_GUIDE = {
    "ad": (
        "이 문서는 [의료광고]입니다. 과장·허위 표현, 비교광고(최고/최상 등 우월성 주장), "
        "'국내 최초·유일' 등 객관적 근거 없는 배타적 표현, 치료경험담·환자 후기, "
        "부작용을 부정하거나 안전성을 단정하는 문구(예: '부작용 전혀 없음', '100% 안전'), "
        "그리고 비급여 진료의 할인·이벤트·금품 제공 등으로 환자를 유인·알선하는 표현"
        "(의료법 제27조 제3항)을 중점 점검하세요."
    ),
    "consent": (
        "이 문서는 [개인정보 수집·이용 동의서]입니다. 민감정보(건강·진료정보 등)의 별도 동의 누락, "
        "수집·이용 목적/항목/보유기간의 불명확·누락, 포괄·강제 동의, 동의 거부권 및 거부 시 "
        "불이익 고지 누락을 중점 점검하세요."
    ),
    "privacy_policy": (
        "이 문서는 [개인정보 처리방침]입니다. 처리방침 필수 기재사항(처리 목적·항목·보유기간, "
        "제3자 제공, 처리위탁, 정보주체의 권리·행사방법, 개인정보 보호책임자, 파기 절차 등)의 "
        "누락·미흡을 중점 점검하세요."
    ),
    "terms": (
        "이 문서는 [약관]입니다. 고객에게 부당하게 불리한 조항, 사업자 책임의 부당한 면제·제한, "
        "고객의 해지·취소권의 부당한 제한, 중요사항 고지·설명 의무 누락을 중점 점검하세요."
    ),
}

_SYSTEM_BASE = (
    "당신은 한국 의료·헬스케어 사업자의 문서를 의료법·개인정보보호법·생명윤리법·정보통신망법 및 "
    "관련 판례·해석례·가이드라인에 비추어 위반 소지를 점검하는 컴플라이언스 검토자입니다.\n"
    "[세그먼트]는 번호가 매겨진 문서 조각이며, 각 세그먼트 아래에 그 세그먼트에 대해 미리 검색해 둔 "
    "[근거](법령·판례·가이드라인)가 함께 붙어 있습니다.\n"
    "규칙:\n"
    "1. 각 세그먼트를 그 아래 [근거]에만 비추어 판단하세요. 근거 없는 추측은 금지합니다.\n"
    "2. level 은 none/low/med/high 중 하나. 위반·과장·오해소지가 없으면 none.\n"
    "3. 근거(법령 번호·인용)는 시스템이 자동으로 연결합니다. 당신은 근거 번호나 법령명을 만들지 말고, "
    "reason 본문에 근거 내용을 자연어로 녹여 설명만 하세요.\n"
    "4. after 는 그 세그먼트를 '그대로 대체할' 실제 수정 문구만 한국어로 쓰세요(지시·설명·따옴표 없이 "
    "문서에 바로 넣을 문장 자체). level 이 none 이면 after 는 빈 문자열로 두세요.\n"
    '5. 반드시 다음 JSON 형식으로만 응답: {"results":[{"index":0,"level":"high",'
    '"reason":"...","after":"..."}]}. results 에는 모든 세그먼트(index 0..N-1)를 포함하세요.'
)


def _system_prompt(segments: list[Segment]) -> str:
    """세그먼트들의 doc_type 에 맞춰 점검 관점을 시스템 프롬프트에 분기 추가."""
    guides: list[str] = []
    seen: set[str] = set()
    for seg in segments:
        dt = seg.doc_type
        if dt in _DOCTYPE_GUIDE and dt not in seen:
            seen.add(dt)
            guides.append(_DOCTYPE_GUIDE[dt])
    if not guides:
        return _SYSTEM_BASE
    return _SYSTEM_BASE + "\n\n[문서 유형별 점검 관점]\n" + "\n".join(guides)


# doc_type별 검색 질의 보강 — 캐주얼한 문구만으로는 관련 조문이 잘 안 걸려서,
# 해당 문서유형의 법률 용어를 질의에 덧붙여 임베딩 검색의 적중률을 높인다.
_QUERY_HINT = {
    "ad": "의료광고 과장·허위광고 치료경험담 환자 유인·알선 비교광고 최상급 표현 사전심의 금지",
    "consent": "개인정보 수집·이용 동의 민감정보 별도 동의 보유기간 거부권",
    "privacy_policy": "개인정보 처리방침 필수 기재사항 보유기간 제3자 제공 보호책임자",
    "terms": "약관 불공정조항 사업자 책임 제한·면제 해지·취소권 제한",
}


def _gather(segments: list[Segment], as_of: str | None, top_k: int) -> list[list]:
    """세그먼트별 hybrid_search → per-segment hits 리스트. (근거를 코드가 결정)

    질의는 원문 + doc_type별 법률용어 힌트로 보강해 관련 조문 적중률을 높인다.
    속도: 세그먼트별 단건 임베딩(N회 순차) 대신, 전 세그먼트 질의를 모아 **1회 배치 임베딩**
    한 뒤 미리 구한 벡터로 검색한다(임베딩 API 왕복 N→1, rate-limit 회피). FTS는 로컬이라 per-seg.
    검색(hybrid_search) 호출은 thread-local SQLite 커넥션이라 스레드 안전 → 병렬 실행한다
    (측정상 N>=2에서 1.5~2.6배 단축). 결과는 원본 세그먼트 인덱스 순서로 정확히 매핑한다.
    """
    per_segment: list[list] = [[] for _ in segments]

    # 1) 비어있지 않은 세그먼트의 보강 질의를 모은다(원본 인덱스 보존).
    idxs: list[int] = []
    queries: list[str] = []
    for i, seg in enumerate(segments):
        text = (seg.text or "").strip()
        if not text:
            continue
        hint = _QUERY_HINT.get(seg.doc_type or "", "")
        idxs.append(i)
        queries.append(f"{text} {hint}".strip() if hint else text)

    # 2) 배치 임베딩 1회(임베딩 인덱스 있을 때만; 키 없음/실패 시 None → FTS 전용).
    vecs = embed_queries(queries) if (queries and has_embeddings()) else [None] * len(queries)

    # 3) 세그먼트별 검색 — 미리 구한 qvec 사용(재임베딩 없음). FTS는 로컬이라 per-seg OK.
    #    thread-local 커넥션이라 스레드 안전 → 검색을 병렬로(워커 상한 min(8, N)).
    def _search(args: tuple[int, str, object]) -> tuple[int, list]:
        i, query, qvec = args
        try:
            hits, _ = hybrid_search(query, None, top_k=top_k, as_of=as_of, qvec=qvec)
        except Exception:  # noqa: BLE001 — 검색 실패해도 그 세그먼트만 빈 hits(나머지는 계속)
            hits = []
        return i, hits

    work = list(zip(idxs, queries, vecs))
    if len(work) <= 1:
        # 단건은 스레드풀 오버헤드만 늘어남 → 직접 실행.
        for args in work:
            i, hits = _search(args)
            per_segment[i] = hits
    else:
        with ThreadPoolExecutor(max_workers=min(8, len(work))) as ex:
            # ex.map 은 입력 순서대로 결과를 주지만, 안전하게 i 로 직접 매핑한다.
            for i, hits in ex.map(_search, work):
                per_segment[i] = hits
    return per_segment


def review_segments(
    segments: list[Segment],
    as_of: str | None = None,
    top_k: int = 4,
) -> list[Segment]:
    """세그먼트별 RAG 근거 확보 + LLM 위험판정으로 Segment.risk 를 채운다.

    - 근거(RiskResult.law)는 코드가 hits.label 에서 채움(LLM 이 인용 생성 안 함).
    - before = 세그먼트 원문, after/reason/level 은 LLM 판단.
    - LLMUnavailable 시 risk 미채움(graceful).
    반환: 입력과 동일한 Segment 리스트(in-place 로 risk 채움).
    """
    if not segments:
        return segments

    per_segment = _gather(segments, as_of, top_k)
    # 광고검토: 검색이 의료광고 금지조문을 못 끌어와도 잡도록 핵심 조문을 근거에 항상 주입.
    _inject_ad_core(segments, per_segment)

    # 세그먼트 + 각자 근거를 한 프롬프트에 묶어 1회 호출.
    blocks: list[str] = []
    for i, seg in enumerate(segments):
        hits = per_segment[i]
        if hits:
            ev = "\n".join(f"  - {h.label}: {h.snippet}" for h in hits)
        else:
            ev = "  - (근거 없음)"
        blocks.append(f"[{i}] {seg.text}\n  이 세그먼트의 근거:\n{ev}")
    body = "\n\n".join(blocks)

    messages = [
        {"role": "system", "content": _system_prompt(segments)},
        {"role": "user", "content": f"[세그먼트와 근거]\n{body}"},
    ]

    try:
        data = llm.chat_json(messages)
    except llm.LLMUnavailable:
        return segments  # graceful — risk 미채움

    by_index: dict[int, dict] = {}
    for r in data.get("results", []) if isinstance(data, dict) else []:
        if not isinstance(r, dict):
            continue
        try:
            idx = int(r["index"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= idx < len(segments):
            by_index[idx] = r

    for i, seg in enumerate(segments):
        r = by_index.get(i)
        if not r:
            continue
        level = r.get("level")
        if level not in _VALID_LEVELS:
            level = "none"
        if level == "none":
            # 위험 아님 — level="none" 으로 명시(의미 있는 것만 위험).
            seg.risk = RiskResult(level="none", before=seg.text)
            continue
        # 근거(law)는 코드가 hits 의 label 에서 채운다 — LLM 이 만들지 않음.
        laws = [h.label for h in per_segment[i] if h.label]
        seg.risk = RiskResult(
            level=level,
            law=laws,
            reason=str(r.get("reason", "")),
            before=seg.text,
            after=str(r.get("after", "")),
        )
    return segments


# ----------------------------- pytest -----------------------------
def test_doctype_prompt_branches():
    """doc_type 별 점검 관점이 시스템 프롬프트에 분기되어 들어가는지."""
    ad = [Segment(seg_id="s", block_ids=[], text="x", doc_type="ad")]
    assert "의료광고" in _system_prompt(ad)
    consent = [Segment(seg_id="s", block_ids=[], text="x", doc_type="consent")]
    assert "동의서" in _system_prompt(consent)
    plain = [Segment(seg_id="s", block_ids=[], text="x", doc_type=None)]
    assert _system_prompt(plain) == _SYSTEM_BASE


def test_empty_segments():
    assert review_segments([]) == []


def test_graceful_without_llm():
    """OPENAI_API_KEY 없으면 검색은 동작하되 LLM 판정은 skip(risk 미채움)."""
    import os

    if os.environ.get("OPENAI_API_KEY"):
        return  # 키 있으면 이 케이스는 의미 없음
    segs = [Segment(seg_id="s1", block_ids=["b1"], text="국내 최초 무통증 치료", doc_type="ad")]
    out = review_segments(segs)
    assert out is segs
    assert out[0].risk is None  # LLM 미사용 → 판정 안 됨


if __name__ == "__main__":
    import os

    print("=== app.pdf.review 셀프체크 ===")
    test_doctype_prompt_branches()
    test_empty_segments()
    print("프롬프트 분기/빈입력 OK")

    segs = [
        Segment(seg_id="s1", block_ids=["b1"], text="부작용이 전혀 없는 100% 안전한 시술", doc_type="ad"),
        Segment(seg_id="s2", block_ids=["b2"], text="국내 최초 무통증 치료", doc_type="ad"),
    ]
    if os.environ.get("OPENAI_API_KEY"):
        out = review_segments(segs)
        risky = [s for s in out if s.risk and s.risk.level in ("low", "med", "high")]
        print("risky:", len(risky))
        for s in risky:
            print("  ", s.risk.level, "| law:", s.risk.law[:2], "| after:", s.risk.after[:30])
        assert risky, "광고 과장 문구가 위험으로 잡혀야"
    else:
        test_graceful_without_llm()
        print("OPENAI_API_KEY 없음 — 판정 skip(검색·graceful 경로만 검증)")
    print("OK")
