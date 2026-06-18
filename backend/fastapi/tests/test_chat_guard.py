"""챗봇 /chat 도메인 가드 회귀 테스트 — 거절 경로 + 되묻기(needs_clarification).

두 계층:
  (A) 결정론적 — Tier 3(도메인 밖)는 규칙으로 잡혀 LLM 불필요. 키 없이도 항상 실행.
      거절 메시지 정확 일치 + sources/method/citation_check 형태 검증.
  (B) LLM 필요 — 모호 질문(Tier 2)의 되묻기 한 줄. OPENAI_API_KEY 있을 때만.

설계 메모:
  - chat()을 풀호출하면 Tier 3는 도메인 라우터가 규칙으로 거절해 LLM을 부르지 않는다
    (rule_based_route 가 3 확정 → is_in_scope False → 즉시 _OUT_OF_DOMAIN 반환).
    그래서 (A)는 키 없이도 결정론적으로 통과한다.
  - 회귀 안전장치(4)는 chat() 풀호출 대신 domain_router.route 만 호출해
    도메인 안 질문의 LLM 답변 생성을 피한다.

실행:
  pytest tests/test_chat_guard.py
  python tests/test_chat_guard.py          # 단독 러너(요약 출력)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import domain_router as dr  # noqa: E402
from app.routers import chat  # noqa: E402
from app.schemas import ChatRequest  # noqa: E402


# 규칙으로 확실히 Tier 3 로 잡히는(=LLM 불필요) 도메인 밖 질문들.
OUT_OF_DOMAIN_KO = [
    "오늘 서울 날씨 알려줘",
    "부동산 계약서 써줘",
    "주식 추천해줘",
    "근처 맛집 알려줘",
]


def _assert_refused(resp, expected_answer):
    """거절 응답 공통 단언: 거절 상수 정확 일치 + 근거/메서드/인용검증 비어있음."""
    assert resp.method == "none", f"method={resp.method!r}, expected 'none'"
    assert resp.sources == [], f"sources={resp.sources!r}, expected []"
    assert resp.answer == expected_answer, "거절 메시지가 상수와 정확히 일치하지 않음"
    assert resp.citation_check.summary.total == 0, (
        f"citation_check.summary.total={resp.citation_check.summary.total}, expected 0"
    )


# ── (A) 결정론적 — 항상 실행 (LLM 불필요) ─────────────────────────────────────
def test_korean_out_of_domain_refused():
    # 사전조건: 규칙으로 Tier 3 확정(LLM 위임 아님)을 보장.
    assert dr.rule_based_route("오늘 서울 날씨 알려줘") == 3
    resp = chat.chat(ChatRequest(question="오늘 서울 날씨 알려줘"))
    _assert_refused(resp, chat._OUT_OF_DOMAIN)
    assert resp.lang == "ko"


def test_english_out_of_domain_refused():
    # 영어는 한국어 키워드 사전 밖이라 규칙이 단정 않고 LLM 에 위임(None). (항상 검증)
    assert dr.rule_based_route("Write me a python quicksort") is None
    # 실제 거절은 LLM 분류가 필요(키 없으면 LLM 폴백이 Tier 2라 거절 안 됨) → 키 있을 때만.
    if os.environ.get("OPENAI_API_KEY"):
        resp = chat.chat(ChatRequest(question="Write me a python quicksort", lang="en"))
        _assert_refused(resp, chat._OUT_OF_DOMAIN_EN)
        assert resp.lang == "en"


def test_multiple_out_of_domain_refused():
    for q in OUT_OF_DOMAIN_KO:
        # 각 질문이 규칙으로 Tier 3 로 잡혀 LLM 없이 거절되는지.
        assert dr.rule_based_route(q) == 3, f"{q!r} 가 규칙으로 Tier3 가 아님(LLM 위임)"
        resp = chat.chat(ChatRequest(question=q))
        assert resp.method == "none", f"{q!r}: method={resp.method!r}"
        assert resp.sources == [], f"{q!r}: sources 비어있지 않음"
        assert resp.answer == chat._OUT_OF_DOMAIN, f"{q!r}: 거절 상수 불일치"


def test_in_scope_question_not_refused():
    """회귀 안전장치: 도메인 안 질문이 거절로 새지 않는지 (route만, LLM 답변 생성 회피)."""
    decision = dr.route("무면허로 시술하면 처벌받나요?")
    assert decision["tier"] == 2, f"tier={decision['tier']}, expected 2"
    assert dr.is_in_scope(decision) is True


# ── (B) LLM 필요 — 되묻기(needs_clarification) ────────────────────────────────
def test_clarification_appended():
    """모호 질문이 needs_clarification 으로 분류되면 답변 끝에 _CLARIFY 한 줄이 붙는지.

    route 가 clar=False 로 나오면(LLM 비결정성) 단언을 느슨하게 skip.
    OPENAI_API_KEY 없으면 통째로 skip.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        import pytest

        pytest.skip("OPENAI_API_KEY 없음 — 되묻기 LLM 검증 생략")

    q = "사무실 CCTV 안내문 꼭 붙여야 하나요?"
    decision = dr.route(q)
    if not decision.get("needs_clarification"):
        import pytest

        pytest.skip(f"route 가 clar=False(tier={decision['tier']}) — 비결정성으로 skip")

    resp = chat.chat(ChatRequest(question=q))
    assert chat._CLARIFY.strip() in resp.answer, "되묻기 문구가 답변에 포함되지 않음"


# ── 단독 러너(요약 출력) ──────────────────────────────────────────────────────
def _run():
    passed = total = 0

    def _check(label, fn):
        nonlocal passed, total
        total += 1
        try:
            fn()
            passed += 1
            print(f"  [OK ] {label}")
        except AssertionError as e:
            print(f"  [FAIL] {label} :: {e}")

    print("── (A) 결정론적 거절(LLM 불필요) ──")
    _check("한국어 도메인밖 거절", test_korean_out_of_domain_refused)
    _check("영어 도메인밖 거절", test_english_out_of_domain_refused)
    _check("도메인밖 다건 거절", test_multiple_out_of_domain_refused)
    _check("도메인 안 질문은 거절 안 됨(route)", test_in_scope_question_not_refused)
    print(f"\n  결정론 {passed}/{total} passed")

    print("\n── (B) 되묻기(needs_clarification, LLM) ──")
    if not os.environ.get("OPENAI_API_KEY"):
        print("  (OPENAI_API_KEY 없음 — 되묻기 검증 생략)")
        return
    q = "사무실 CCTV 안내문 꼭 붙여야 하나요?"
    decision = dr.route(q)
    if not decision.get("needs_clarification"):
        print(f"  (route clar=False, tier={decision['tier']} — 비결정성으로 생략)")
        return
    resp = chat.chat(ChatRequest(question=q))
    if chat._CLARIFY.strip() in resp.answer:
        print("  [OK ] 되묻기 한 줄 부착")
    else:
        print("  [FAIL] 되묻기 한 줄 부착 :: 문구 미포함")


if __name__ == "__main__":
    _run()
