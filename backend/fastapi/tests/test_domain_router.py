"""도메인 라우터 회귀 테스트 — 프롬프트/키워드 바꿀 때마다 행동이 안 깨졌는지 확인.

세 계층:
  1) RULE_CASES        : 단발 질문, 규칙으로 tier 확정(LLM 불필요, 항상 실행)
  2) RULE_FOLLOWUP     : 멀티턴 후속질문의 규칙 동작(키워드 없으면 LLM 위임, 결정론)
  3) ROUTE_AMBIGUOUS / ROUTE_MULTITURN : 모호·후속 케이스 실제 분류(OPENAI_API_KEY 있을 때만)

운영 중 오분류가 나오면 (질문[, history], 기대tier)를 해당 세트에 계속 추가한다.

실행:
  pytest tests/test_domain_router.py
  python tests/test_domain_router.py          # 단독 러너(요약 출력)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import domain_router as dr  # noqa: E402

# ── 1) 단발 질문 — 규칙으로 tier 확정 (LLM 불필요) ─────────────────────────────
RULE_CASES = [
    # Tier 2 = 의료/헬스케어 (핵심)
    ("무면허로 시술하면 처벌받나요?", 2),
    ("병원 진료기록 보관기간은 얼마예요?", 2),
    ("직원 건강검진 결과를 인사팀이 보관해도 되나요?", 2),
    ("수술실 CCTV 설치가 의무인가요?", 2),
    ("환자 전후사진을 블로그 광고에 써도 되나요?", 2),
    ("비대면진료 시 처방전 발급이 가능한가요?", 2),
    ("임상시험 동의서에 무엇이 들어가야 하나요?", 2),
    ("의료광고 사전심의 대상인지 알려줘", 2),
    ("생명윤리법상 인간대상연구 IRB 심의가 필요한가요?", 2),
    ("유전자검사 결과를 보관해도 되나요?", 2),
    # Tier 1 = 일반 개인정보/정보통신망 (의료 맥락 없음, 번질 여지 키워드 없음)
    ("쇼핑몰 회원 개인정보 보관기간 얼마예요?", 1),
    ("개인정보 처리방침에 꼭 넣어야 할 항목은?", 1),
    ("정보통신망법상 개인정보 파기 시점은?", 1),
    ("가명처리하면 동의 없이 활용해도 되나요?", 1),
    ("개인정보 유출 시 신고 의무가 있나요?", 1),
    # Tier 3 = 무관 (거절)
    ("야근수당 어떻게 계산해요?", 3),
    ("부동산 임대차 계약서 작성법 알려줘", 3),
    ("오늘 서울 날씨 알려줘", 3),
    ("파이썬 퀵소트 코드 짜줘", 3),
    ("주식 종목 추천해줘", 3),
    ("근처 맛집 추천해줘", 3),
]

# ── 2) 멀티턴 후속질문 — 규칙 동작(결정론) ────────────────────────────────────
#  키워드 없는 후속("그럼 처벌은?")은 하드 거절하지 않고 None(→ LLM 위임)이어야 함.
#  키워드 있는 후속은 단발과 동일하게 tier 확정.
RULE_FOLLOWUP_CASES = [
    ("그럼 처벌은 어떻게 되나요?", None),     # 키워드 없음 + 대화중 → LLM 위임
    ("그건 어떻게 신청하나요?", None),
    ("그러면요?", None),
    ("의료광고는 어떤가요?", 2),              # 키워드 있으면 후속도 확정
    ("개인정보 파기는요?", 1),
]


def test_rule_based_singleshot():
    for q, expected in RULE_CASES:
        got = dr.rule_based_route(q)            # 단발(history 없음)
        assert got == expected, f"rule_based_route({q!r}) = {got}, expected {expected}"


def test_rule_followup_with_history():
    for q, expected in RULE_FOLLOWUP_CASES:
        got = dr.rule_based_route(q, has_history=True)
        assert got == expected, f"rule_based_route({q!r}, has_history=True) = {got}, expected {expected}"


def test_keywordless_singleshot_vs_followup():
    # 같은 키워드 없는 질문: 단발이면 Tier3(거절), 대화중이면 None(LLM 위임)
    q = "그럼 그건 어떻게 되나요?"
    assert dr.rule_based_route(q, has_history=False) == 3
    assert dr.rule_based_route(q, has_history=True) is None


def test_non_korean_defers_to_llm():
    # 키워드 사전은 한국어 → 영어 등 비한국어 질문은 규칙으로 단정 않고 LLM 위임(None).
    # (한국어 의료 키워드가 없어도 Tier3로 하드 거절하면 안 됨 — 영어 입력 기능 보호)
    for q in [
        "What is the penalty for unlicensed medical practice?",
        "Do I need consent to use patient photos in ads?",
        "Write me a python quicksort function",
    ]:
        assert dr.rule_based_route(q) is None, f"비한국어 질문은 None(LLM 위임)이어야: {q!r}"


def test_in_scope_policy():
    assert dr.is_in_scope({"tier": 1})
    assert dr.is_in_scope({"tier": 2})
    assert not dr.is_in_scope({"tier": 3})


# ── 3) 실제 분류(LLM 필요) — 모호 단발 + 멀티턴 후속 ──────────────────────────
ROUTE_AMBIGUOUS_CASES = [
    ("사무실 CCTV 안내문 꼭 붙여야 하나요?", {1, 2}),
    ("광고 문자 보낼 때 수신동의 받아야 하나요?", {1, 2}),
    ("직원 개인정보 수집 동의서 양식 알려줘", {1, 2}),
    ("회원정보를 마케팅에 활용해도 되나요?", {1, 2}),
    # 영어 입력(lang=en) — 규칙은 None, LLM이 분류
    ("What is the penalty for unlicensed medical practice?", {2}),  # 영어 의료 → 핵심
    ("Write me a python quicksort function", {3}),                  # 영어 잡담 → 거절
]

_H_MED = [
    {"role": "user", "content": "무면허 의료행위가 뭔가요?"},
    {"role": "assistant", "content": "의료인이 아닌 자가 의료행위를 하는 것입니다."},
]
_H_AD = [
    {"role": "user", "content": "병원 블로그에 환자 전후사진을 올려 광고하려는데요"},
    {"role": "assistant", "content": "의료광고 심의·과장표현 규제와 환자 동의가 문제될 수 있습니다."},
]
_H_PRIV = [
    {"role": "user", "content": "개인정보 수집 동의는 어떻게 받나요?"},
    {"role": "assistant", "content": "수집·이용 목적, 항목, 보유기간을 알리고 동의를 받아야 합니다."},
]

# (history, 후속질문, 기대 tier 집합)
ROUTE_MULTITURN_CASES = [
    (_H_MED,  "그럼 처벌 수위는 어떻게 되나요?", {2}),     # 의료 맥락 후속 → 핵심
    (_H_MED,  "그럼 파이썬 코딩은 어떻게 배워요?", {3}),    # 화제 이탈 → 거절
    (_H_AD,   "그건 사전심의 대상인가요?", {2}),
    (_H_PRIV, "위탁을 주는 경우엔 어떻게 해야 하나요?", {1, 2}),
]


def _run():
    passed = total = 0
    print("── 1) 단발 규칙(결정론) ──")
    for q, expected in RULE_CASES:
        got = dr.rule_based_route(q)
        ok = got == expected; passed += ok; total += 1
        print(f"  [{'OK ' if ok else 'FAIL'}] expect {expected} got {got} :: {q}")

    print("\n── 2) 멀티턴 후속 규칙(결정론) ──")
    for q, expected in RULE_FOLLOWUP_CASES:
        got = dr.rule_based_route(q, has_history=True)
        ok = got == expected; passed += ok; total += 1
        print(f"  [{'OK ' if ok else 'FAIL'}] expect {expected} got {got} :: (후속) {q}")
    print(f"\n  결정론 {passed}/{total} passed")

    if not os.environ.get("OPENAI_API_KEY"):
        print("\n(OPENAI_API_KEY 없음 — 모호·멀티턴 LLM 검증 생략)")
        return

    print("\n── 3) 모호 단발(실제 route, LLM) ──")
    for q, expected in ROUTE_AMBIGUOUS_CASES:
        d = dr.route(q)
        ok = d["tier"] in expected
        print(f"  [{'OK ' if ok else 'FAIL'}] expect {expected} got tier={d['tier']} clar={d['needs_clarification']} :: {q}")

    print("\n── 4) 멀티턴 후속(실제 route, history+LLM) ──")
    for hist, q, expected in ROUTE_MULTITURN_CASES:
        d = dr.route(q, hist)
        ok = d["tier"] in expected
        ctx = hist[0]["content"][:18]
        print(f"  [{'OK ' if ok else 'FAIL'}] expect {expected} got tier={d['tier']} :: [{ctx}…] → {q}")


if __name__ == "__main__":
    _run()
