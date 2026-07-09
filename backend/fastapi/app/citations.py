"""Citation Firewall 핵심 — 한국 법률 인용 파싱 + DB 대조 검증.

검증 4축 (lawbot.org):
1. 법령 존재 (statute existence)
2. 조문 정확성 (clause accuracy)
3. 판례 유효성 (case law validity)
4. 시점 적합성 (temporal relevance, as_of)

주의: 위 4축은 모두 구조·시점 검증이다. 인용한 내용(의미)이 실제 조문/판례의
취지와 일치하는지는 검증 범위가 아니다 — 번호가 실재해도 설명이 틀릴 수 있다.
"""
import re

from app import config
from app.db import db
from app.schemas import CitationInput, VerifyResult, VerifySummary


def _grade(exists: bool, clause_accurate, valid_as_of, trust_grade=None) -> tuple[int, str]:
    """검증 신호 → (신뢰 점수 0~100, 상태 확인|주의|오류).

    오류 = 존재하지 않거나 조문 불일치(환각). 주의 = 존재하나 그 시점엔 미발효/이후 선고.
    확인 = 구조 검증 통과(법령·조문·항 실재 + 시점 유효, 미검증 항목만큼 소폭 감점).
           내용(의미) 일치는 검증하지 않으므로 '확인'이 내용 정확성을 보증하진 않는다.
    trust_grade = 출처 등급('A' 권위 높음 / 'B' 행정규칙 등 낮음). 권위 차이는 환각이
    아니므로 status는 바꾸지 않고 점수만 소폭 보정한다.
    """
    if not exists:
        return 0, "오류"
    if clause_accurate is False:            # 조문 환각(법령은 있으나 그 조문 없음)
        return 25, "오류"
    if valid_as_of is False:                # 존재하나 as_of 시점엔 미발효/이후 선고
        score, status = 60, "주의"
    else:
        score = 100
        if clause_accurate is None:         # 조문 단위 대조 못함(법령명만 인용/판례)
            score -= 10
        if valid_as_of is None:             # 시점 미검증(as_of 미지정)
            score -= 5
        status = "확인"
    # 출처 등급 보정: status는 유지, 낮은 권위(B)만 소폭 감점(최저 60).
    if status != "오류" and trust_grade == "B":
        score = max(60, score - 5)
    return score, status


def summarize(results: list[VerifyResult]) -> VerifySummary:
    """검증 결과 목록 → 요약(개수 + 평균/최저 점수 + 최악 상태)."""
    verified = sum(1 for r in results if r.verified)
    avg = round(sum(r.trust_score for r in results) / len(results)) if results else 0
    order = {"확인": 0, "주의": 1, "오류": 2}
    worst = max(results, key=lambda r: order[r.status]).status if results else "확인"
    min_score = min((r.trust_score for r in results), default=100)
    return VerifySummary(
        total=len(results), verified=verified, failed=len(results) - verified, avg_score=avg,
        worst_status=worst, min_score=min_score)


# 법령 인용: (법령명) 제N조(의M)?(제K항)?
_STATUTE_RE = re.compile(
    r"([가-힣][가-힣\s·]{1,40}?(?:법|법률|령|규칙|고시|예규|훈령|지침))\s*"
    r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?(?:\s*제\s*(\d+)\s*항)?"
)
# 판례 사건번호: 2010도1234, 84도723, 2015두5184, 2018헌마123 ...
_CASE_RE = re.compile(r"\b(\d{2,4}\s*[가-힣]{1,3}\s*\d+)\b")

# 이름 없이 '법/시행규칙/조례…' 같은 일반 접미어 토큰만으로 이뤄진 지칭.
# 앞 문장에서 언급된 법을 "법 제N조"처럼 익명으로 가리키거나, _STATUTE_RE 가 답변
# 본문에서 법령명 경계를 못 잡아 앞 문장조각까지 캡처하면(예: "외국인환자를 유치할
# 목적으로 법", "조 및 같은 법 시행규칙") 마지막 토큰이 이런 일반 접미어가 된다.
# 실제 법령명은 마지막 토큰에 이름부가 남는다(약사법·보호법·의료법…).
_GENERIC_LAW_TOKENS = frozenset(
    ["법", "법률", "령", "규칙", "시행령", "시행규칙", "고시", "예규", "훈령", "지침", "조례"]
)


def _is_generic_law_ref(law_name: str) -> bool:
    """법령명 없이 일반 접미어 토큰만 지칭됐는지(마지막 토큰이 일반 접미어)."""
    tokens = re.sub(r"·", " ", law_name or "").split()
    return bool(tokens) and tokens[-1] in _GENERIC_LAW_TOKENS


def _compact(date_str: str) -> str:
    return re.sub(r"\D", "", date_str or "")


def _fmt_article_no(no: str) -> str:
    """article_no('56' / '56의2' / '56-2') → 표기 '제56조' / '제56조의2'."""
    n = (no or "").replace("-", "의")
    if "의" in n:
        base, branch = n.split("의", 1)
        return f"제{base}조의{branch}"
    return f"제{n}조"


# 표시용 법령 라벨 정리: 답변 본문 파싱 시 앞 문장조각이 법령명에 붙어 잡히므로
# ("사건에서는 구 약사법 제23조") 표시에는 '법령명 제N조'만 남긴다.
_LAW_LABEL_RE = re.compile(
    r"([가-힣]{1,20}(?:법률|법|령|규칙|고시|예규|훈령|지침|조례))\s*"
    r"(제\s*\d+\s*조(?:\s*의\s*\d+)?(?:\s*제\s*\d+\s*항)?)"
)

# 라벨 접두 복원: "보건범죄 단속에 관한 특별조치법"처럼 띄어쓴 긴 법령명은 위 라벨
# 정규식(공백 불허)이 마지막 토큰("특별조치법")만 잡아 조각 라벨이 된다. 매치 직전이
# "…에/의 관한(대한·위한) " 패턴이면 그 앞 명사 몇 단어까지 법령명으로 되살린다.
# 조사(은/는/이/가…)로 끝나는 단어는 문장조각으로 보고 접두에 넣지 않는다(과캡처 방지).
_LAW_LABEL_PREFIX_RE = re.compile(
    r"((?:[가-힣]{2,20}(?<![은는이가을를의도])\s+){0,3}"
    r"[가-힣]{1,20}[에의]\s*(?:관한|대한|위한)\s*)$"
)


def clean_law_label(raw: str) -> str:
    m = _LAW_LABEL_RE.search(raw or "")
    if not m:
        return (raw or "").strip()
    article = re.sub(r"\s+", "", m.group(2))
    name = m.group(1)
    pre = _LAW_LABEL_PREFIX_RE.search(raw[: m.start(1)])
    if pre:
        name = re.sub(r"\s+", " ", (pre.group(1) + name).strip())
    return f"{name} {article}"


# ── 내용 일치(content faithfulness) 검증 — 별도 레이어 ──────────────────────
# 인용 주변 '주장 문장' ↔ 실제 조문/판례 본문을 임베딩 코사인 유사도로 비교.
# 검색 인덱스(app.rag, small/512·캐시)와 독립적으로 내용검사 전용 임베딩
# (CONTENT_EMBED_MODEL=large/3072)을 직접 호출한다 — 모델/차원·캐시키 충돌 방지.
# 짧은 주장↔긴 본문 비교의 분리력을 높이려 본문을 조항 단위 청크로 쪼개 claim과의
# '최대 코사인'을 쓴다. 키 없음/빈입력/예외 시 None(graceful skip → content_match=None).

# 본문 청크 경계: 줄바꿈/마침표/。/원숫자 항 경계(앞쪽 lookahead). 길이>=6, 최대 30개.
_CHUNK_SPLIT_RE = re.compile(r"(?:[.。\n\r]+|(?=[①-⑮]))")
_CHUNK_MIN_LEN = 6
_CHUNK_MAX = 30

# 내용검사 전용 임베딩 캐시(rag 캐시와 분리). 키=(model,dim,text) → 벡터(list[float]).
# 동일 본문 청크/주장을 인용마다 재임베딩하는 비용을 줄인다. 단순 bounded dict.
_CONTENT_EMBED_CACHE: dict[tuple, list[float]] = {}
_CONTENT_EMBED_CACHE_MAX = 2048


def _content_chunks(content: str) -> list[str]:
    """본문을 조항 단위 청크로 분리(길이>=6, 최대 30개). 없으면 본문 통째 1개."""
    parts = [p.strip() for p in _CHUNK_SPLIT_RE.split(content or "")]
    parts = [p for p in parts if len(p) >= _CHUNK_MIN_LEN]
    if not parts:
        c = (content or "").strip()
        return [c] if c else []
    return parts[:_CHUNK_MAX]


def _content_embed(texts: list[str]) -> list[list[float]] | None:
    """내용검사 전용 임베딩(large/3072). 캐시 적중분 제외하고 1회 배치 호출.

    키 없음/실패 시 None(graceful). 반환은 입력과 같은 순서·길이.
    """
    if not texts:
        return []
    if not config.OPENAI_API_KEY:
        return None
    model, dim = config.CONTENT_EMBED_MODEL, config.CONTENT_EMBED_DIM
    out: list[list[float] | None] = [None] * len(texts)
    miss: dict[str, list[int]] = {}
    for i, t in enumerate(texts):
        cached = _CONTENT_EMBED_CACHE.get((model, dim, t))
        if cached is not None:
            out[i] = cached
        else:
            miss.setdefault(t, []).append(i)
    if miss:
        uniq = list(miss.keys())
        try:
            from app.llm import openai_client  # 공유 클라이언트 재사용(매 호출 재생성 방지)

            resp = openai_client().embeddings.create(model=model, input=uniq, dimensions=dim)
            by_idx = {d.index: d.embedding for d in resp.data}
        except Exception:
            return None
        for j, t in enumerate(uniq):
            vec = by_idx.get(j)
            if vec is None:
                return None  # 부분 실패 → 전체 graceful skip
            if len(_CONTENT_EMBED_CACHE) < _CONTENT_EMBED_CACHE_MAX:
                _CONTENT_EMBED_CACHE[(model, dim, t)] = vec
            for pos in miss[t]:
                out[pos] = vec
    return out  # 이 시점엔 전부 채워짐


def _content_similarity(claim: str, content: str) -> float | None:
    """주장 ↔ 본문 청크-최대 코사인 유사도(0~1). 키 없음·실패·빈입력이면 None."""
    if not claim or not content:
        return None
    chunks = _content_chunks(content)
    if not chunks:
        return None
    try:
        import numpy as np

        embs = _content_embed([claim] + chunks)
        if not embs or embs[0] is None:  # 키 없음/실패 → graceful skip
            return None
        cvec = np.asarray(embs[0], dtype=np.float32)
        cnorm = np.linalg.norm(cvec) or 1.0
        best = None
        for e in embs[1:]:
            v = np.asarray(e, dtype=np.float32)
            sim = float(cvec @ v / (cnorm * (np.linalg.norm(v) or 1.0)))
            if best is None or sim > best:
                best = sim
        return best
    except Exception:
        return None


# 내용검증은 '실질적 주장'에만 작동시킨다. 주장에서 인용 토큰(법령·판례)을 제거한 뒤
# 남는 의미 텍스트(한글·영숫자)가 이 글자수 미만이면 단순 인용·나열로 보고 skip한다
# — "의료법 제27조와 제56조" 같은 인용 나열에 오탐 다운그레이드가 나지 않게.
_CLAIM_MIN_SUBSTANTIVE = 10


def _content_check_target(result: VerifyResult, claim: str | None, content: str | None) -> bool:
    """내용 일치 검증 대상인지(플래그·statute 한정·claim 실질성) — 단건/배치 공용 가드."""
    if not config.CONTENT_CHECK:
        return False
    if result.type != "statute":
        return False  # 내용 일치 검증은 법령(조문)에만 — 판례 등은 본문 길이차로 보정 불가
    if not claim or not content:
        return False  # claim 모름/본문 없음 → 미검증(None 유지)
    # 실질적 '주장'에만 작동: 인용 토큰(법령·판례)을 제거한 뒤 남는 의미 텍스트가 짧으면
    # (단순 인용·나열) 내용검증 skip — 인용 나열에 오탐 다운그레이드 방지.
    bare = _CASE_RE.sub(" ", _STATUTE_RE.sub(" ", claim))
    substance = re.sub(r"[^가-힣A-Za-z0-9]", "", bare)
    return len(substance) >= _CLAIM_MIN_SUBSTANTIVE


def _apply_content_score(result: VerifyResult, sim: float) -> VerifyResult:
    """계산된 유사도를 result 에 반영(단건/배치 공용 후처리).

    - sim < THRESHOLD && status=='확인' → '주의'로 다운그레이드(오류 단정 X),
      content_match=False, content_score=sim, note에 사유 추가.
    - sim >= THRESHOLD → content_match=True, content_score=sim (status 유지).
    구조상 이미 '오류'/'주의'면 status·점수는 건드리지 않는다(content_match/score만 기록).
    """
    result.content_score = round(sim, 4)
    threshold = config.CONTENT_SIM_THRESHOLD
    if sim < threshold:
        result.content_match = False
        if result.status == "확인":  # 구조상 통과인데 내용이 다름 → 주의로 다운그레이드
            result.status = "주의"
            extra = f"인용 내용이 조문 본문과 의미가 다를 수 있음(유사도 {sim:.2f})"
            result.note = f"{result.note}; {extra}" if result.note else extra
    else:
        result.content_match = True
    return result


def _apply_content_check(result: VerifyResult, claim: str | None, content: str | None) -> VerifyResult:
    """구조 검증 결과에 내용 일치 검증을 후처리(플래그 ON일 때만).

    유사도 None(미검증/키없음) → content_match=None (불변).
    여러 인용을 한 번에 검증할 땐 _apply_content_checks(배치판)를 쓴다.
    """
    if not _content_check_target(result, claim, content):
        return result
    sim = _content_similarity(claim, content)
    if sim is None:
        return result  # 키없음/실패 → content_match=None 유지
    return _apply_content_score(result, sim)


def _apply_content_checks(items: list[tuple[VerifyResult, str | None, str | None]]) -> None:
    """여러 인용의 내용 일치 검증 — _apply_content_check 의 배치판(결과는 in-place 반영).

    가드·판정 로직은 단건과 동일하되, 전 인용의 claim/본문 청크를 모아 임베딩 API 를
    **1회 배치 호출**로 줄인다(인용 N건 → 왕복 N→1). 캐시 의미는 _content_embed 가
    그대로 처리한다(적중분 제외·미적중 유니크만 호출). 실패 시 전체 graceful skip.
    """
    todo: list[tuple[VerifyResult, str, list[str]]] = []
    for result, claim, content in items:
        if not _content_check_target(result, claim, content):
            continue
        chunks = _content_chunks(content)
        if chunks:
            todo.append((result, claim, chunks))
    if not todo:
        return
    texts: list[str] = []
    for _, claim, chunks in todo:
        texts.append(claim)
        texts.extend(chunks)
    try:
        import numpy as np

        embs = _content_embed(texts)
        if not embs:
            return  # 키없음/실패 → 전부 content_match=None 유지(단건과 동일)
        pos = 0
        for result, claim, chunks in todo:
            span = embs[pos:pos + 1 + len(chunks)]
            pos += 1 + len(chunks)
            cvec = np.asarray(span[0], dtype=np.float32)
            cnorm = np.linalg.norm(cvec) or 1.0
            best = None
            for e in span[1:]:
                v = np.asarray(e, dtype=np.float32)
                sim = float(cvec @ v / (cnorm * (np.linalg.norm(v) or 1.0)))
                if best is None or sim > best:
                    best = sim
            if best is not None:
                _apply_content_score(result, best)
    except Exception:
        return  # numpy 부재 등 — 단건(_content_similarity)과 동일하게 graceful skip


# ── 코퍼스 밖 인용의 2차 대조(sources 원문 대조) ────────────────────────────
# 코퍼스(4개 법) 밖 법령이라도 이 답변에 검색된 판례 스니펫 원문에 그 법령명이
# 그대로 등장하면 '근거 없는 서술'이 아니다 — 경고를 완화할 수 있게 플래그를 단다.
# 매칭은 공백·가운뎃점을 지운 뒤 부분문자열 비교(띄어쓰기 변형 흡수). 답변이 앞
# 문장조각을 달고 캡처되는 것을 감안해 후보명을 단어 접미 단위로 줄여가며 시도하고,
# "…에 관한 특별조치법/법률" ↔ "…법" 약칭 변형도 양방향으로 흡수한다.

# 익명 지칭("동법 제25조") 또는 이름 없는 조각("특별조치법"만 단독) — 매칭 후보에서
# 제외하고, 경고줄 라벨에서도 별도 항목으로 잡히지 않게 걸러낸다(표시단 노이즈 제거).
ANAPHORIC_OR_FRAGMENT_LAW_NAMES = frozenset(
    ["동법", "같은법", "해당법", "그법", "이법", "본법", "위법", "동법률", "같은법률",
     "특별조치법", "특례법"]
) | _GENERIC_LAW_TOKENS

_LAW_ABBREV_SUBS = (("에관한특별조치법", "법"), ("에관한법률", "법"))


def _norm_law(s: str) -> str:
    """법령명 비교용 정규화 — 공백·가운뎃점 제거(띄어쓰기 변형 흡수)."""
    return re.sub(r"[\s·]", "", s or "")


def _law_name_candidates(law_name: str) -> list[str]:
    """캡처된 법령명(앞 문장조각 포함 가능)에서 대조 후보들을 만든다.

    뒤에서부터 k개 단어를 합친 접미들("위반은 보건범죄 단속에 관한 특별조치법" →
    전체, "보건범죄단속에관한특별조치법", …) + 각 후보의 약칭 변형. 접미어 조각
    ("특별조치법"·"법")·익명 지칭만 남은 후보는 제외한다.
    """
    words = (law_name or "").split()
    out: list[str] = []
    for k in range(len(words), 0, -1):
        cand = _norm_law("".join(words[-k:]))
        if len(cand) < 2 or cand in ANAPHORIC_OR_FRAGMENT_LAW_NAMES:
            continue
        if cand not in out:
            out.append(cand)
        for pat, rep in _LAW_ABBREV_SUBS:
            abbr = cand.replace(pat, rep)
            if abbr != cand and len(abbr) >= 3 and abbr not in out:
                out.append(abbr)
    return out


def _statute_in_sources(law_name: str, source_texts: list[str]) -> bool:
    """해당 법령명이 이 답변의 근거(sources) 원문에 실제 등장하는지 대조."""
    cands = _law_name_candidates(law_name)
    if not cands:
        return False
    for text in source_texts:
        hay = _norm_law(text)
        if not hay:
            continue
        hay_abbr = hay
        for pat, rep in _LAW_ABBREV_SUBS:  # 원문이 정식 명칭이어도 약칭 인용과 맞도록
            hay_abbr = hay_abbr.replace(pat, rep)
        for cand in cands:
            if cand in hay or cand in hay_abbr:
                return True
    return False


def _match_statute(law_name: str):
    """후보 법령명에 포함된 실제 법령 중 가장 긴 것을 반환."""
    return db().execute(
        """SELECT id, law_id, name, source_url, effective_from, trust_grade
           FROM statutes
           WHERE ? LIKE '%' || name || '%'
           ORDER BY LENGTH(name) DESC LIMIT 1""",
        (law_name.strip(),),
    ).fetchone()


_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"  # 원숫자 1~15 (한국 법령 항 표기)


def _fmt_ymd(ymd: str) -> str:
    """YYYYMMDD → YYYY-MM-DD (포맷 불일치 시 원본 반환, graceful)."""
    d = _compact(ymd)
    if len(d) == 8:
        return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
    return ymd


def _cross_check_revisions(s, as_of, score, status, notes) -> tuple[int, str]:
    """statutes 매칭 성공 후 law_revisions와 교차검증해 구법 인용 리스크를 경고.

    law_revisions 데이터(4대 법령 등)가 있을 때만 동작. 테이블 부재/빈 테이블/
    해당 law_id 행 없음이면 점수·상태·note를 전혀 건드리지 않고 그대로 반환한다.
    - (a) 시행예정: 정보성 note만(점수/상태 불변).
    - (b) 구법 가능성(as_of 지정 시만): as_of 시점 시행본이 현행(검증에 쓴 버전)보다
          이전이면 '확인'→'주의'로 낮추고 score=min(score,70), note 추가.
    """
    try:
        law_id = s["law_id"]
    except (KeyError, IndexError):
        return score, status
    if not law_id:
        return score, status
    try:
        conn = db()
        from app import lawapi
        if not lawapi.has_revisions(conn):
            return score, status
        rows = conn.execute(
            "SELECT effective_on, status, revision_type FROM law_revisions "
            "WHERE law_id = ? ORDER BY effective_on",
            (law_id,),
        ).fetchall()
    except Exception:
        return score, status
    if not rows:
        return score, status

    # (a) 시행예정(개정 예정) — 정보성 note만, 점수/상태 불변.
    upcoming = [r["effective_on"] for r in rows if r["status"] == "시행예정" and r["effective_on"]]
    if upcoming:
        notes.append(f"개정 시행예정 있음(시행일 {_fmt_ymd(min(upcoming))})")

    # (b) 구법 가능성 — as_of 지정 시에만.
    if as_of:
        as_of_c = _compact(as_of)
        eff_from = _compact(s["effective_from"] or "")
        # as_of 시점에 시행 중이던 실제 버전(effective_on <= as_of 중 가장 늦은 것).
        in_force = [_compact(r["effective_on"]) for r in rows
                    if r["effective_on"] and _compact(r["effective_on"]) <= as_of_c]
        if in_force and eff_from:
            as_of_version = max(in_force)
            if as_of_version < eff_from:  # 당시 시행본이 현행보다 이전 = 구법 상황
                if status == "확인":
                    status = "주의"
                    score = min(score, 70)
                notes.append(
                    f"{as_of} 시점에는 다른 버전이 시행 중이었을 수 있음"
                    f"(당시 시행본 {_fmt_ymd(as_of_version)}, 현행과 비교 권장)")

    return score, status


def verify_statute(law_name: str, article_no: str | None, raw: str, as_of: str | None,
                   paragraph_no: int | None = None, claim: str | None = None,
                   content_batch: list | None = None,
                   source_texts: list[str] | None = None) -> VerifyResult:
    s = _match_statute(law_name)
    if not s:
        # DB에 없는 법령: '환각'으로 단정(오류/0점)하지 않는다 — 실재하나 코퍼스(4개 법)
        # 밖일 수 있어 구조적으로 검증이 불가능하다. '주의'로 표시해, 코퍼스 밖 인용 한 건이
        # 전체 답변 신뢰도를 0으로 끌어내리는 것을 막는다(코퍼스 밖 인용은 경고줄로 별도 고지).
        # 2차 대조: 이 답변의 근거(sources) 원문에 그 법령명이 실제 등장하면 근거 있는
        # 서술이므로 seen_in_sources=True 로 구분한다(경고 완화용). status/점수는 그대로
        # '주의'/50 — 법령 원문 검증이 된 것은 아니므로 '확인' 등급으로 올리지 않는다.
        clean = clean_law_label(raw)
        seen_src = _statute_in_sources(law_name, source_texts) if source_texts else None
        if seen_src:
            note = (f"'{clean}'은(는) 코퍼스(4개 법) 밖이지만 인용된 판례 원문에서 언급이 "
                    "확인됨(법령 원문 검증은 되지 않음)")
        else:
            note = f"'{clean}'은(는) 확인된 코퍼스(4개 법) 밖이라 검증 불가"
        return VerifyResult(
            raw=raw, type="statute", exists=False, verified=False,
            trust_score=50, status="주의", matched_label=clean,
            seen_in_sources=seen_src, note=note,
        )

    clause_accurate = None
    paragraph_missing = False
    article_url = s["source_url"] or ""
    matched_label = s["name"]
    article_content = None  # 내용 일치 검증용 조문 본문
    if article_no:
        # 'N' 또는 'N의M' 형태 모두 시도
        variants = [article_no, article_no.replace("-", "의")]
        art = db().execute(
            f"""SELECT id, article_title, content FROM articles
                WHERE statute_id = ? AND article_no IN ({','.join('?' * len(variants))})
                LIMIT 1""",
            (s["id"], *variants),
        ).fetchone()
        clause_accurate = art is not None
        if art:
            article_content = art["content"]
        matched_label = f"{s['name']} {_fmt_article_no(article_no)}"
        if art and art["article_title"]:
            matched_label += f"({art['article_title']})"
        # 항(項) 검증: 조문 본문(content)에 해당 항이 실제로 존재하는지 확인.
        # 항은 원숫자 ①~⑮로 표기 → 본문에 실재하는 최대 항을 기준으로 범위를 본다.
        # 마커가 없으면 단일 항(제1항)으로 간주. 실재 최대 항(또는 ⑮)을 넘는 항은 환각.
        if art and paragraph_no is not None:
            content = art["content"] or ""
            present = [i + 1 for i, sym in enumerate(_CIRCLED) if sym in content]
            max_para = max(present) if present else 1
            if 1 <= paragraph_no <= max_para and (
                not present or _CIRCLED[paragraph_no - 1] in content
            ):
                matched_label += f" 제{paragraph_no}항"
            else:
                clause_accurate = False
                paragraph_missing = True

    valid_as_of = None
    if as_of:
        eff = s["effective_from"]
        if eff:
            valid_as_of = _compact(eff) <= _compact(as_of)
        # eff 없으면 None 유지(시행일 데이터 없음 = 미검증, 미발효와 구별)

    verified = (
        clause_accurate is not False and valid_as_of is not False
    )  # exists는 위에서 True 보장
    notes = []
    if paragraph_missing:
        notes.append(f"제{paragraph_no}항이 해당 조문에 존재하지 않음")
    elif clause_accurate is False:
        notes.append(f"{_fmt_article_no(article_no)}가 해당 법령에 존재하지 않음")
    if valid_as_of is False:
        notes.append(f"{as_of} 시점에 미발효(발효일 {s['effective_from']})")
    score, status = _grade(True, clause_accurate, valid_as_of, s["trust_grade"])

    # 모호(저신뢰) 매칭 보정: 정확 매칭이 아니면서 짧은 법령명이 긴 인용 문자열에
    # 헐겁게 박힌 경우만 엄격하게 '주의'로 낮춘다(정확 매칭/4대 법령은 회귀 0).
    cited = law_name.strip()
    db_name = s["name"].strip()
    exact_match = db_name == cited
    if not exact_match:
        # 앞에 조사·수식이 붙어(예: "근거 법령으로는 의료법") db명이 인용문의 '접미'로
        # 깔끔히 정렬되면 헐거운 매칭이 아니라 접두 노이즈일 뿐 — 모호 판정에서 제외.
        _squash = lambda x: re.sub(r"\s", "", x)
        clean_suffix = _squash(cited).endswith(_squash(db_name))
        coverage = len(db_name) / len(cited) if cited else 1.0
        ambiguous = not clean_suffix and len(db_name) <= 4 and coverage < 0.6
        if ambiguous and status == "확인":
            status = "주의"
            score = min(score, 70)
            notes.append(f"법령명 매칭이 모호함(매칭: {s['name']})")

    # 구법 인용 리스크 교차검증(기획서 ⑤) — law_revisions 데이터가 있을 때만.
    # 데이터 없으면(테이블 부재/빈 테이블/해당 law_id 행 없음) 완전히 스킵 → 기존 동작 유지.
    score, status = _cross_check_revisions(s, as_of, score, status, notes)

    note = "; ".join(notes)
    if status == "확인" and not note:
        # 사용자가 '확인'을 내용 검증으로 오해하지 않도록 검증 범위를 명시.
        note = "법령·조문·항 실재 및 시점 확인(내용 일치는 미검증)"
    result = VerifyResult(
        raw=raw, type="statute", exists=True,
        clause_accurate=clause_accurate, valid_as_of=valid_as_of,
        verified=verified, trust_score=score, status=status,
        matched_label=matched_label,
        matched_source_url=article_url, note=note,
    )
    # 내용 일치 검증(플래그 ON & claim·본문 있을 때만). 조문 본문을 비교 대상으로.
    # content_batch 가 주어지면(extract_and_verify) 검증을 미뤄뒀다가 여러 인용을
    # 임베딩 1회 배치로 처리한다(_apply_content_checks) — 단건 호출 동작은 불변.
    if content_batch is not None:
        content_batch.append((result, claim, article_content))
        return result
    return _apply_content_check(result, claim, article_content)


def verify_case(case_no: str, raw: str, as_of: str | None,
                claim: str | None = None) -> VerifyResult:
    cn = re.sub(r"\s", "", case_no)
    row = db().execute(
        "SELECT id, case_name, court, date, summary, body, source_url "
        "FROM cases WHERE case_no = ? LIMIT 1",
        (cn,),
    ).fetchone()
    if not row:
        score, status = _grade(False, None, None)
        return VerifyResult(
            raw=raw, type="case", exists=False, verified=False,
            trust_score=score, status=status,
            note=f"사건번호 '{cn}' 판례를 DB에서 찾을 수 없음",
        )
    valid_as_of = None
    if as_of:
        if row["date"]:
            valid_as_of = _compact(row["date"]) <= _compact(as_of)
        # 선고일 데이터 없으면 None 유지(미검증, 이후 선고와 구별)
    label = " ".join(filter(None, [row["court"], cn]))
    notes = []
    if valid_as_of is False:
        notes.append(f"{as_of} 이후 선고된 판례(선고일 {row['date']})")
    score, status = _grade(True, None, valid_as_of)
    note = "; ".join(notes)
    if status == "확인" and not note:
        # '확인'을 내용 검증으로 오해하지 않도록 검증 범위를 명시.
        note = "판례 실재 및 시점 확인(내용 일치는 미검증)"
    result = VerifyResult(
        raw=raw, type="case", exists=True, valid_as_of=valid_as_of,
        verified=valid_as_of is not False, trust_score=score, status=status,
        matched_label=label,
        matched_source_url=row["source_url"] or "", note=note,
    )
    # 내용 일치 검증은 판례에 적용하지 않는다. 임계값이 짧은 법령 조문 기준으로 보정돼 있어,
    # 긴 판결문(요지·본문)과 짧은 사유 문장의 유사도가 구조적으로 낮게 나와 정상 인용을
    # 과하게 '주의' 처리하기 때문. 판례는 구조 검증(실재·시점)만 수행한다.
    return result


# 문장 경계: 마침표·물음표·느낌표·줄바꿈 등. 인용을 포함하는 '주장 문장'을 잘라낼 때 사용.
_SENT_SPLIT_RE = re.compile(r"[.!?。\n\r]+")


def _claim_sentence(text: str, start: int, end: int) -> str:
    """text의 [start,end) 매치를 포함하는 문장을 추출(주장 문맥). 내용 일치 검증용.

    문장 경계(마침표·물음표·느낌표·줄바꿈)로 자르고, 매치를 포함하는 조각을 반환.
    """
    left = 0
    right = len(text)
    for m in _SENT_SPLIT_RE.finditer(text):
        if m.end() <= start:
            left = m.end()       # 매치 앞의 마지막 경계
        elif m.start() >= end:
            right = m.start()    # 매치 뒤의 첫 경계
            break
    return text[left:right].strip()


def extract_and_verify(text: str, as_of: str | None,
                       source_texts: list[str] | None = None) -> list[VerifyResult]:
    """LLM 답변 원문에서 인용을 추출해 전부 검증.

    각 인용 매치마다 그것을 포함하는 '주장 문장'을 함께 넘겨 내용 일치 검증에 쓴다
    (CONTENT_CHECK ON일 때만 사용; OFF면 무시되어 기존 동작 불변).
    내용 일치 검증은 인용별로 임베딩을 호출하지 않고, 전 인용을 모아 마지막에
    임베딩 1회 배치(_apply_content_checks)로 처리한다(지연 단축).
    source_texts(이 답변에 검색된 근거 스니펫 원문들)를 주면 코퍼스 밖 법령 인용을
    근거 원문과 2차 대조해 seen_in_sources 플래그를 단다(미지정 시 기존 동작 불변).
    """
    results: list[VerifyResult] = []
    seen: set[str] = set()
    pending_content: list[tuple[VerifyResult, str | None, str | None]] = []

    for m in _STATUTE_RE.finditer(text):
        law_name, art, art_ui, _hang = m.group(1), m.group(2), m.group(3), m.group(4)
        # 이름 없는 일반 지칭("그 법 제5조", "조 및 같은 법 시행규칙")이고 DB에 대응
        # 법령이 없으면 검증 불가한 익명 참조·오추출 → skip(환각 아님, ERROR 오탐 방지).
        # 실제 법령(약사법 등)이면 _match_statute 가 잡으므로 skip 안 됨(미수록은 ERROR 유지).
        if _is_generic_law_ref(law_name) and _match_statute(law_name) is None:
            continue
        article_no = f"{art}의{art_ui}" if art_ui else art
        paragraph_no = int(_hang) if _hang else None
        key = f"s:{law_name.strip()}:{article_no}:{_hang or ''}"
        if key in seen:
            continue
        seen.add(key)
        claim = _claim_sentence(text, m.start(), m.end())
        results.append(
            verify_statute(law_name, article_no, m.group(0).strip(), as_of, paragraph_no, claim,
                           content_batch=pending_content, source_texts=source_texts))

    for m in _CASE_RE.finditer(text):
        case_no = re.sub(r"\s", "", m.group(1))
        # 연도 4자리 또는 2자리 + 한글 + 숫자 형태만 (오탐 방지: 한글 1~3자 필수)
        key = f"c:{case_no}"
        if key in seen:
            continue
        seen.add(key)
        claim = _claim_sentence(text, m.start(), m.end())
        results.append(verify_case(case_no, m.group(0).strip(), as_of, claim))

    # 미뤄둔 내용 일치 검증을 임베딩 1회 배치로 일괄 처리(결과 in-place 반영).
    _apply_content_checks(pending_content)
    return results


def verify_inputs(citations: list[CitationInput], as_of: str | None) -> list[VerifyResult]:
    """구조화된 인용 입력 검증."""
    results: list[VerifyResult] = []
    for c in citations:
        if c.raw and not (c.law_name or c.case_no):
            results.extend(extract_and_verify(c.raw, as_of))
        elif c.case_no:
            results.append(verify_case(c.case_no, c.raw or c.case_no, as_of))
        elif c.law_name:
            raw = c.raw or f"{c.law_name} 제{c.article_no}조" if c.article_no else (c.raw or c.law_name)
            results.append(verify_statute(c.law_name, c.article_no, raw, as_of))
        else:
            results.append(VerifyResult(raw=c.raw or "", type="unknown", exists=False,
                                        verified=False, trust_score=0, status="오류",
                                        note="인용 정보 부족"))
    return results
