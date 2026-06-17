"""Citation Firewall 핵심 — 한국 법률 인용 파싱 + DB 대조 검증.

검증 4축 (lawbot.org):
1. 법령 존재 (statute existence)
2. 조문 정확성 (clause accuracy)
3. 판례 유효성 (case law validity)
4. 시점 적합성 (temporal relevance, as_of)
"""
import re

from app.db import db
from app.schemas import CitationInput, VerifyResult, VerifySummary


def _grade(exists: bool, clause_accurate, valid_as_of) -> tuple[int, str]:
    """검증 신호 → (신뢰 점수 0~100, 상태 확인|주의|오류).

    오류 = 존재하지 않거나 조문 불일치(환각). 주의 = 존재하나 그 시점엔 미발효/이후 선고.
    확인 = 핵심 검증 통과(미검증 항목만큼 소폭 감점).
    """
    if not exists:
        return 0, "오류"
    if clause_accurate is False:            # 조문 환각(법령은 있으나 그 조문 없음)
        return 25, "오류"
    if valid_as_of is False:                # 존재하나 as_of 시점엔 미발효/이후 선고
        return 60, "주의"
    score = 100
    if clause_accurate is None:             # 조문 단위 대조 못함(법령명만 인용/판례)
        score -= 10
    if valid_as_of is None:                 # 시점 미검증(as_of 미지정)
        score -= 5
    return score, "확인"


def summarize(results: list[VerifyResult]) -> VerifySummary:
    """검증 결과 목록 → 요약(개수 + 평균 신뢰 점수)."""
    verified = sum(1 for r in results if r.verified)
    avg = round(sum(r.trust_score for r in results) / len(results)) if results else 0
    return VerifySummary(
        total=len(results), verified=verified, failed=len(results) - verified, avg_score=avg)


# 법령 인용: (법령명) 제N조(의M)?(제K항)?
_STATUTE_RE = re.compile(
    r"([가-힣][가-힣\s·]{1,40}?(?:법|법률|령|규칙|고시|예규|훈령|지침))\s*"
    r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?(?:\s*제\s*(\d+)\s*항)?"
)
# 판례 사건번호: 2010도1234, 84도723, 2015두5184, 2018헌마123 ...
_CASE_RE = re.compile(r"\b(\d{2,4}\s*[가-힣]{1,3}\s*\d+)\b")


def _compact(date_str: str) -> str:
    return re.sub(r"\D", "", date_str or "")


def _match_statute(law_name: str):
    """후보 법령명에 포함된 실제 법령 중 가장 긴 것을 반환."""
    return db().execute(
        """SELECT id, name, source_url, effective_from, trust_grade
           FROM statutes
           WHERE ? LIKE '%' || name || '%'
           ORDER BY LENGTH(name) DESC LIMIT 1""",
        (law_name.strip(),),
    ).fetchone()


_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"  # 원숫자 1~15 (한국 법령 항 표기)


def verify_statute(law_name: str, article_no: str | None, raw: str, as_of: str | None,
                   paragraph_no: int | None = None) -> VerifyResult:
    s = _match_statute(law_name)
    if not s:
        score, status = _grade(False, None, None)
        return VerifyResult(
            raw=raw, type="statute", exists=False, verified=False,
            trust_score=score, status=status,
            note=f"'{law_name.strip()}' 법령을 DB에서 찾을 수 없음",
        )

    clause_accurate = None
    paragraph_missing = False
    article_url = s["source_url"] or ""
    matched_label = s["name"]
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
        matched_label = f"{s['name']} 제{article_no}조"
        if art and art["article_title"]:
            matched_label += f"({art['article_title']})"
        # 항(項) 검증: 조문 본문(content)에 해당 항이 실제로 존재하는지 확인
        if art and paragraph_no is not None and 1 <= paragraph_no <= len(_CIRCLED):
            content = art["content"] or ""
            symbol = _CIRCLED[paragraph_no - 1]
            if symbol in content:
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
        notes.append(f"제{article_no}조가 해당 법령에 존재하지 않음")
    if valid_as_of is False:
        notes.append(f"{as_of} 시점에 미발효(발효일 {s['effective_from']})")
    score, status = _grade(True, clause_accurate, valid_as_of)
    return VerifyResult(
        raw=raw, type="statute", exists=True,
        clause_accurate=clause_accurate, valid_as_of=valid_as_of,
        verified=verified, trust_score=score, status=status,
        matched_label=matched_label,
        matched_source_url=article_url, note="; ".join(notes),
    )


def verify_case(case_no: str, raw: str, as_of: str | None) -> VerifyResult:
    cn = re.sub(r"\s", "", case_no)
    row = db().execute(
        "SELECT id, case_name, court, date, source_url FROM cases WHERE case_no = ? LIMIT 1",
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
    return VerifyResult(
        raw=raw, type="case", exists=True, valid_as_of=valid_as_of,
        verified=valid_as_of is not False, trust_score=score, status=status,
        matched_label=label,
        matched_source_url=row["source_url"] or "", note="; ".join(notes),
    )


def extract_and_verify(text: str, as_of: str | None) -> list[VerifyResult]:
    """LLM 답변 원문에서 인용을 추출해 전부 검증."""
    results: list[VerifyResult] = []
    seen: set[str] = set()

    for m in _STATUTE_RE.finditer(text):
        law_name, art, art_ui, _hang = m.group(1), m.group(2), m.group(3), m.group(4)
        article_no = f"{art}의{art_ui}" if art_ui else art
        paragraph_no = int(_hang) if _hang else None
        key = f"s:{law_name.strip()}:{article_no}:{_hang or ''}"
        if key in seen:
            continue
        seen.add(key)
        results.append(
            verify_statute(law_name, article_no, m.group(0).strip(), as_of, paragraph_no))

    for m in _CASE_RE.finditer(text):
        case_no = re.sub(r"\s", "", m.group(1))
        # 연도 4자리 또는 2자리 + 한글 + 숫자 형태만 (오탐 방지: 한글 1~3자 필수)
        key = f"c:{case_no}"
        if key in seen:
            continue
        seen.add(key)
        results.append(verify_case(case_no, m.group(0).strip(), as_of))

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
