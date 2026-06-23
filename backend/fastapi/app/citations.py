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


def _grade(exists: bool, clause_accurate, valid_as_of, trust_grade=None) -> tuple[int, str]:
    """검증 신호 → (신뢰 점수 0~100, 상태 확인|주의|오류).

    오류 = 존재하지 않거나 조문 불일치(환각). 주의 = 존재하나 그 시점엔 미발효/이후 선고.
    확인 = 핵심 검증 통과(미검증 항목만큼 소폭 감점).
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


def _compact(date_str: str) -> str:
    return re.sub(r"\D", "", date_str or "")


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
    score, status = _grade(True, clause_accurate, valid_as_of, s["trust_grade"])

    # 모호(저신뢰) 매칭 보정: 정확 매칭이 아니면서 짧은 법령명이 긴 인용 문자열에
    # 헐겁게 박힌 경우만 엄격하게 '주의'로 낮춘다(정확 매칭/4대 법령은 회귀 0).
    cited = law_name.strip()
    db_name = s["name"].strip()
    exact_match = db_name == cited
    if not exact_match:
        coverage = len(db_name) / len(cited) if cited else 1.0
        ambiguous = len(db_name) <= 4 and coverage < 0.6
        if ambiguous and status == "확인":
            status = "주의"
            score = min(score, 70)
            notes.append(f"법령명 매칭이 모호함(매칭: {s['name']})")

    # 구법 인용 리스크 교차검증(기획서 ⑤) — law_revisions 데이터가 있을 때만.
    # 데이터 없으면(테이블 부재/빈 테이블/해당 law_id 행 없음) 완전히 스킵 → 기존 동작 유지.
    score, status = _cross_check_revisions(s, as_of, score, status, notes)

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
