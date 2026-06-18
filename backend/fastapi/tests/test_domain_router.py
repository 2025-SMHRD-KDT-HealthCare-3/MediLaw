"""도메인 라우터 회귀 테스트 — 프롬프트/키워드 바꿀 때마다 행동이 안 깨졌는지 확인.

규칙 계층(rule_based_route)은 LLM 없이 결정론적으로 검증(오프라인, 항상 실행).
모호 케이스(route 전체)는 OPENAI_API_KEY 가 있을 때만 실제 분류로 검증.
운영 중 오분류가 나오면 (질문, 기대tier)를 아래 세트에 계속 추가한다.

실행:
  pytest tests/test_domain_router.py          # pytest
  python tests/test_domain_router.py          # 단독 러너(요약 출력)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import domain_router  # noqa: E402

# ── 1) 결정론적 규칙으로 tier 가 확정되는 케이스 (LLM 불필요) ──────────────────
RULE_CASES = [
    # 의료/헬스케어 명시 → Tier 2 (핵심)
    ("무면허로 시술하면 처벌받나요?", 2),
    ("병원 진료기록 보관기간은 얼마예요?", 2),
    ("직원 건강검진 결과를 인사팀이 보관해도 되나요?", 2),
    ("수술실 CCTV 설치가 의무인가요?", 2),
    ("환자 전후사진을 블로그 광고에 써도 되나요?", 2),
    # 순수 일반 개인정보/정보통신(번질 여지 키워드 없음) → Tier 1
    ("쇼핑몰 회원 개인정보 보관기간 얼마예요?", 1),
    ("개인정보 처리방침에 꼭 넣어야 할 항목은?", 1),
    # 프라이버시도 의료도 아님 → Tier 3 (거절)
    ("야근수당 어떻게 계산해요?", 3),
    ("부동산 임대차 계약서 작성법 알려줘", 3),
    ("오늘 서울 날씨 알려줘", 3),
    ("파이썬 퀵소트 코드 짜줘", 3),
]

# ── 2) 모호 → LLM 위임 케이스 (기대 tier 집합으로 느슨하게 검증) ──────────────
ROUTE_CASES = [
    ("사무실 CCTV 안내문 꼭 붙여야 하나요?", {1, 2}),   # 진료공간 가능성 → 보통 2
    ("광고 문자 보낼 때 수신동의 받아야 하나요?", {1, 2}),
]


def test_rule_based_deterministic():
    for q, expected in RULE_CASES:
        got = domain_router.rule_based_route(q)
        assert got == expected, f"rule_based_route({q!r}) = {got}, expected {expected}"


def test_tier3_out_of_scope():
    for q, _ in [c for c in RULE_CASES if c[1] == 3]:
        assert not domain_router.is_in_scope({"tier": 3}), "Tier 3 는 거절(in_scope=False)"
        assert domain_router.rule_based_route(q) == 3


def test_in_scope_policy():
    assert domain_router.is_in_scope({"tier": 1})
    assert domain_router.is_in_scope({"tier": 2})
    assert not domain_router.is_in_scope({"tier": 3})


def _run():
    passed = 0
    print("── 규칙 계층(결정론적) ──")
    for q, expected in RULE_CASES:
        got = domain_router.rule_based_route(q)
        ok = got == expected
        passed += ok
        print(f"  [{'OK ' if ok else 'FAIL'}] expect {expected} got {got} :: {q}")
    print(f"  {passed}/{len(RULE_CASES)} passed")

    if os.environ.get("OPENAI_API_KEY"):
        print("\n── 모호 케이스(실제 route, LLM) ──")
        for q, expected in ROUTE_CASES:
            d = domain_router.route(q)
            ok = d["tier"] in expected
            print(f"  [{'OK ' if ok else 'FAIL'}] expect {expected} got {d} :: {q}")
    else:
        print("\n(OPENAI_API_KEY 없음 — 모호 케이스 LLM 검증 생략)")


if __name__ == "__main__":
    _run()
