"""Citation Firewall 핵심 — 한국 법률 인용 파싱 + DB 대조 검증.

검증 4축 (lawbot.org):
1. 법령 존재 (statute existence)
2. 조문 정확성 (clause accuracy)
3. 판례 유효성 (case law validity)
4. 시점 적합성 (temporal relevance, as_of)
"""
import re

from app.db import db
from app.schemas import CitationInput, VerifyResult

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


def verify_statute(law_name: str, article_no: str | None, raw: str, as_of: str | None) -> VerifyResult:
    s = _match_statute(law_name)
    if not s:
        return VerifyResult(
            raw=raw, type="statute", exists=False, verified=False,
            note=f"'{law_name.strip()}' 법령을 DB에서 찾을 수 없음",
        )

    clause_accurate = None
    article_url = s["source_url"] or ""
    matched_label = s["name"]
    if article_no:
        # 'N' 또는 'N의M' 형태 모두 시도
        variants = [article_no, article_no.replace("-", "의")]
        art = db().execute(
            f"""SELECT id, article_title FROM articles
                WHERE statute_id = ? AND article_no IN ({','.join('?' * len(variants))})
                LIMIT 1""",
            (s["id"], *variants),
        ).fetchone()
        clause_accurate = art is not None
        matched_label = f"{s['name']} 제{article_no}조"
        if art and art["article_title"]:
            matched_label += f"({art['article_title']})"

    valid_as_of = None
    if as_of:
        eff = s["effective_from"]
        valid_as_of = bool(eff) and _compact(eff) <= _compact(as_of)

    verified = (
        clause_accurate is not False and valid_as_of is not False
    )  # exists는 위에서 True 보장
    notes = []
    if clause_accurate is False:
        notes.append(f"제{article_no}조가 해당 법령에 존재하지 않음")
    if valid_as_of is False:
        notes.append(f"{as_of} 시점에 미발효(발효일 {s['effective_from']})")
    return VerifyResult(
        raw=raw, type="statute", exists=True,
        clause_accurate=clause_accurate, valid_as_of=valid_as_of,
        verified=verified, matched_label=matched_label,
        matched_source_url=article_url, note="; ".join(notes),
    )


def verify_case(case_no: str, raw: str, as_of: str | None) -> VerifyResult:
    cn = re.sub(r"\s", "", case_no)
    row = db().execute(
        "SELECT id, case_name, court, date, source_url FROM cases WHERE case_no = ? LIMIT 1",
        (cn,),
    ).fetchone()
    if not row:
        return VerifyResult(
            raw=raw, type="case", exists=False, verified=False,
            note=f"사건번호 '{cn}' 판례를 DB에서 찾을 수 없음",
        )
    valid_as_of = None
    if as_of:
        valid_as_of = bool(row["date"]) and _compact(row["date"]) <= _compact(as_of)
    label = " ".join(filter(None, [row["court"], cn]))
    notes = []
    if valid_as_of is False:
        notes.append(f"{as_of} 이후 선고된 판례(선고일 {row['date']})")
    return VerifyResult(
        raw=raw, type="case", exists=True, valid_as_of=valid_as_of,
        verified=valid_as_of is not False, matched_label=label,
        matched_source_url=row["source_url"] or "", note="; ".join(notes),
    )


def extract_and_verify(text: str, as_of: str | None) -> list[VerifyResult]:
    """LLM 답변 원문에서 인용을 추출해 전부 검증."""
    results: list[VerifyResult] = []
    seen: set[str] = set()

    for m in _STATUTE_RE.finditer(text):
        law_name, art, art_ui, _hang = m.group(1), m.group(2), m.group(3), m.group(4)
        article_no = f"{art}의{art_ui}" if art_ui else art
        key = f"s:{law_name.strip()}:{article_no}"
        if key in seen:
            continue
        seen.add(key)
        results.append(verify_statute(law_name, article_no, m.group(0).strip(), as_of))

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
            results.append(VerifyResult(raw=c.raw or "", type="unknown", exists=False, verified=False, note="인용 정보 부족"))
    return results
