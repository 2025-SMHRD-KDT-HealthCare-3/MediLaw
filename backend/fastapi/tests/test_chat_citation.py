"""Citation Firewall 회귀 테스트 — 신뢰점수/상태(trust_score/status) 결정론 검증.

이 레이어는 LLM 없이 DB 대조로만 동작하므로 **키 없이도 항상 전부 실행**된다.
세 계층:
  1) _grade 순수함수      : DB도 불필요, 절댓값 단언 OK (점수 공식 고정)
  2) extract_and_verify   : DB 사용, 진짜/가짜 인용 섞어 상대관계로 단언(데이터 변동에 견고)
  3) summarize / 챗봇 연동 : 요약 구조 + 라우터 _citation_check 통합

실행:
  pytest tests/test_chat_citation.py
  python tests/test_chat_citation.py          # 단독 러너(요약 출력)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import citations as c  # noqa: E402
from app.citations import _grade, extract_and_verify, summarize, verify_statute  # noqa: E402


# ── 1) _grade 순수함수 (DB 불필요, 절댓값 단언) ───────────────────────────────
def test_grade_pure_function():
    # 존재하지 않음 → 0점 오류
    assert _grade(False, None, None) == (0, "오류")
    # 조문 환각(법령은 있으나 그 조문 없음) → 25점 오류
    assert _grade(True, False, None) == (25, "오류")
    # 존재하나 as_of 시점 미발효 → 주의, 60점
    score, status = _grade(True, True, False)
    assert status == "주의"
    assert score == 60
    # 완전 통과 → 100점 확인
    assert _grade(True, True, True) == (100, "확인")
    # 낮은 권위(B) 출처 → status 유지(확인), 점수만 소폭 감점
    score_b, status_b = _grade(True, True, True, "B")
    assert score_b == 95
    assert status_b == "확인"


def test_grade_score_range():
    # 가능한 신호 조합 전수 → 점수는 항상 0..100, 상태는 정해진 3종 중 하나
    valid_status = {"확인", "주의", "오류"}
    for exists in (True, False):
        for clause in (True, False, None):
            for valid in (True, False, None):
                for grade in (None, "A", "B"):
                    score, status = _grade(exists, clause, valid, grade)
                    assert 0 <= score <= 100, (exists, clause, valid, grade, score)
                    assert status in valid_status


# ── 2) extract_and_verify + summarize (DB 사용, 상대관계로 단언) ──────────────
def _find(results, needle):
    """raw에 needle 문자열이 포함된 첫 결과 반환."""
    for r in results:
        if needle in r.raw:
            return r
    raise AssertionError(f"인용 {needle!r}을(를) 추출 결과에서 찾지 못함: "
                         f"{[r.raw for r in results]}")


def test_extract_real_vs_fake_statute():
    results = extract_and_verify("의료법 제27조와 가짜 의료법 제999조", None)

    real = _find(results, "제27조")
    fake = _find(results, "제999조")

    # 실재 조문: 오류가 아니고(확인), 높은 신뢰, 검증 통과
    assert real.status == "확인"
    assert real.trust_score >= 85
    assert real.verified is True

    # 가짜 조문: 오류, 낮은 신뢰, 검증 실패, 사유(note) 존재
    assert fake.status == "오류"
    assert fake.trust_score <= 25
    assert fake.verified is False
    assert fake.note  # 비어있지 않음


def test_summarize_mixed():
    results = extract_and_verify("의료법 제27조와 가짜 의료법 제999조", None)
    s = summarize(results)

    assert s.worst_status == "오류"        # 가짜가 섞였으니 최악은 오류
    assert s.min_score <= 25               # 가짜 조문 점수가 최저
    assert 0 <= s.avg_score <= 100
    assert s.failed >= 1                   # 최소 한 건은 검증 실패


def test_summarize_empty():
    s = summarize([])
    assert s.total == 0
    assert s.avg_score == 0
    assert s.worst_status == "확인"        # 결과 없으면 최악도 '확인'(중립)
    assert s.min_score == 100


# ── 3) 항(項) 검증 — 존재하는 조문이라도 없는 항이면 오류(환각) ───────────────
def test_paragraph_hallucination():
    # 의료법 제27조는 실재하나, 매우 큰 항(제14항)은 없을 가능성이 높다.
    # 데이터 의존을 줄이기 위해 먼저 직접 검증해 '없는 항'을 찾고, 그 항으로 단언한다.
    missing_para = None
    for p in (14, 13, 12, 11, 10, 9, 8, 7, 6):
        r = verify_statute("의료법", "27", "의료법 제27조", None, paragraph_no=p)
        if r.status == "오류":
            missing_para = p
            break
    assert missing_para is not None, "의료법 제27조에 존재하지 않는 항을 찾지 못함(데이터 변경?)"

    text = f"의료법 제27조 제{missing_para}항"
    results = extract_and_verify(text, None)
    item = _find(results, "제27조")
    assert item.status == "오류"           # 항 환각 → 오류
    assert "항" in item.note               # 사유에 '항' 언급


# ── 4) 챗봇 라우터 연동 — _citation_check 요약 구조 ───────────────────────────
def test_chat_citation_check():
    from app.routers.chat import _citation_check

    r = _citation_check("의료법 제27조", None)
    # 요약에 핵심 점수 필드가 존재
    assert hasattr(r.summary, "avg_score")
    assert hasattr(r.summary, "worst_status")
    assert hasattr(r.summary, "min_score")
    assert isinstance(r.output, list)


# ── 단독 러너 ────────────────────────────────────────────────────────────────
def _run():
    tests = [
        test_grade_pure_function,
        test_grade_score_range,
        test_extract_real_vs_fake_statute,
        test_summarize_mixed,
        test_summarize_empty,
        test_paragraph_hallucination,
        test_chat_citation_check,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  [OK ] {t.__name__}")
        except Exception as e:  # noqa: BLE001
            print(f"  [FAIL] {t.__name__}: {e}")
    print(f"\n  Citation Firewall {passed}/{len(tests)} passed")
    return passed == len(tests)


if __name__ == "__main__":
    ok = _run()
    sys.exit(0 if ok else 1)
