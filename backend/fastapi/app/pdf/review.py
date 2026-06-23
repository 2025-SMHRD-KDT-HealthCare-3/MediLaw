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

from app import llm
from app.pdf.schema import RiskResult, Segment
from app.rag import hybrid_search

_VALID_LEVELS = {"none", "low", "med", "high"}

# doc_type 별 점검 관점(시스템 프롬프트에 끼워 넣는 분기). 없으면 일반 프롬프트.
_DOCTYPE_GUIDE = {
    "ad": (
        "이 문서는 [의료광고]입니다. 과장·허위 표현, 비교광고(최고/최상 등 우월성 주장), "
        "'국내 최초·유일' 등 객관적 근거 없는 배타적 표현, 치료경험담·환자 후기, "
        "부작용을 부정하거나 안전성을 단정하는 문구(예: '부작용 전혀 없음', '100% 안전') "
        "를 중점 점검하세요."
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


def _gather(segments: list[Segment], as_of: str | None, top_k: int) -> list[list]:
    """세그먼트별 hybrid_search → per-segment hits 리스트. (근거를 코드가 결정)"""
    per_segment: list[list] = []
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            per_segment.append([])
            continue
        try:
            hits, _ = hybrid_search(text, None, top_k=top_k, as_of=as_of)
        except Exception:  # noqa: BLE001 — 검색 실패해도 판정은 계속(근거 없이)
            hits = []
        per_segment.append(hits)
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
