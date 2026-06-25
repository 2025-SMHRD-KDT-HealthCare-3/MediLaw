"""의료광고 검토 회귀 테스트 — '광고 미감지' 수정의 재발 방지.

배경: 캐주얼한 후기형 의료광고 문구가 (1) doc_type 분류에서 'ad'로 안 잡히거나
(2) 검색이 의료광고 금지조문을 못 끌어와 위험으로 미감지되던 문제를 수정했다.
이 테스트는 그 수정(후기 키워드 추가 / ad 핵심조문 주입 / 질의 보강 / 가이드)의
회귀를 막는다.

구성:
  A. 결정론 테스트(키 불필요, 항상 실행) — 분류·핵심조문·주입·질의·가이드.
     DB(data/medilaw.db) 의존 케이스 있으나 DB 존재 → 동작.
  B. LLM 통합 테스트(OPENAI_API_KEY 있을 때만, 없으면 skip) — 실제 위반 감지.

실행:
  pytest tests/test_ad_review.py
  python3 tests/test_ad_review.py        # 단독 러너(PASS/FAIL/SKIP 요약, 실패 시 exit 1)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.pdf import review  # noqa: E402
from app.pdf.review import _ad_core_hits, _inject_ad_core  # noqa: E402
from app.pdf.classify import rule_based_classify  # noqa: E402
from app.pdf.schema import Segment  # noqa: E402


# pytest 미설치 환경(단독 러너)에서도 skip 을 표현하기 위한 신호.
class _Skip(Exception):
    """단독 러너가 해석하는 skip 신호."""


def _skip(msg):
    """pytest 가 있으면 pytest.skip, 없으면 _Skip 예외(단독 러너가 해석)."""
    try:
        import pytest
    except ImportError:
        raise _Skip(msg)
    pytest.skip(msg)


def _skip_if_no_key():
    if not os.environ.get("OPENAI_API_KEY"):
        _skip("OPENAI_API_KEY 없음 — LLM 통합 검토 생략")


# ─────────────────────────────────────────────────────────────────────────────
# A. 결정론 테스트 (키 불필요)
# ─────────────────────────────────────────────────────────────────────────────
def test_review_keyword_classifies_as_ad():
    """후기형 문장이 doc_type 분류에서 'ad'로 잡혀야 한다(후기 키워드 반영)."""
    text = "실제 환자 후기입니다. 여기서 시술받고 다 나았어요"
    assert rule_based_classify(text) == "ad", (
        f"후기형 문장이 ad 로 분류되지 않음: {rule_based_classify(text)!r}"
    )


def test_ad_core_statutes_present():
    """_ad_core_hits 가 의료법 제56·27·57조 3건을 반환해야 한다(DB 의존)."""
    hits = _ad_core_hits()
    assert len(hits) == 3, f"핵심 조문 3건이어야 함: {len(hits)}건"
    labels = " ".join(h.label for h in hits)
    for art in ("제56조", "제27조", "제57조"):
        assert art in labels, f"핵심 조문에 {art} 누락: {labels!r}"


def test_inject_ad_core_only_for_ad():
    """ad 세그먼트엔 핵심조문이 주입되고, 비-ad(terms) 세그먼트엔 주입 안 됨."""
    ad_seg = Segment(seg_id="s0", block_ids=["b0"], text="후기 광고 문구", doc_type="ad")
    terms_seg = Segment(seg_id="s1", block_ids=["b1"], text="약관 조항", doc_type="terms")
    segments = [ad_seg, terms_seg]
    per_segment = [[], []]  # 검색 결과가 비어도(미감지 상황) 주입돼야 함.

    _inject_ad_core(segments, per_segment)

    # ad: 핵심조문 주입(>=3건, 제56조 포함).
    ad_labels = " ".join(h.label for h in per_segment[0])
    assert len(per_segment[0]) >= 3, f"ad 세그먼트 근거 >=3 이어야 함: {len(per_segment[0])}"
    assert "제56조" in ad_labels, f"ad 근거에 제56조 없음: {ad_labels!r}"
    # terms: 주입 없음(0건).
    assert len(per_segment[1]) == 0, (
        f"비-ad(terms) 세그먼트엔 주입되면 안 됨: {len(per_segment[1])}건"
    )


def test_ad_query_hint_exists():
    """_QUERY_HINT['ad'] 에 의료광고 검색 보강 용어가 들어 있어야 한다."""
    hint = review._QUERY_HINT.get("ad", "")
    assert "치료경험담" in hint, f"질의 보강에 '치료경험담' 없음: {hint!r}"
    assert "유인" in hint, f"질의 보강에 '유인' 없음: {hint!r}"


def test_ad_guide_has_patient_inducement():
    """_DOCTYPE_GUIDE['ad'] 에 비급여 유인/제27조 제3항 점검 문구가 있어야 한다."""
    guide = review._DOCTYPE_GUIDE.get("ad", "")
    assert "비급여" in guide, f"가이드에 '비급여' 없음: {guide!r}"
    assert ("유인" in guide) and ("제27조" in guide), (
        f"가이드에 환자 유인/제27조 점검 문구 없음: {guide!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# B. LLM 통합 테스트 (OPENAI_API_KEY 있을 때만)
# ─────────────────────────────────────────────────────────────────────────────
def test_ad_review_detects_violations():
    """실제 위반 문구는 findings 로 잡고, 단순 안내 문구는 안 잡혀야 한다.

    LLM 판정이라 약간의 비결정성이 있을 수 있으나, 현재 아래 5문장은 5/5 통과한다.
    위반 4문장은 len(findings)>0, 안내 1문장은 len(findings)==0 을 단언한다.
    """
    _skip_if_no_key()
    from app.pdf.review_adapter import review_to_response

    must_flag = [
        "실제 환자 후기입니다. 여기서 시술받고 허리디스크가 완전히 나았어요!",
        "비급여 임플란트 지금 신청하면 50% 할인 이벤트 진행중",
        "부작용 전혀 없는 100% 안전한 시술입니다",
        "국내 최초이자 유일한 줄기세포 치료, 최고의 의료진",
    ]
    must_pass = "저희 병원 진료시간은 평일 오전 9시부터 오후 6시까지입니다"

    for text in must_flag:
        r = review_to_response(text=text)
        assert len(r.findings) > 0, f"위반으로 잡혀야 하나 미감지: {text!r}"

    r = review_to_response(text=must_pass)
    assert len(r.findings) == 0, (
        f"안내 문구인데 위험으로 잡힘(findings={len(r.findings)}): {must_pass!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 단독 러너 (PASS/FAIL/SKIP 요약, 실패 시 exit 1)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _tests = [
        ("후기형 → ad 분류", test_review_keyword_classifies_as_ad),
        ("핵심조문 제56·27·57조", test_ad_core_statutes_present),
        ("ad 만 핵심조문 주입", test_inject_ad_core_only_for_ad),
        ("ad 질의 보강 용어", test_ad_query_hint_exists),
        ("ad 가이드 유인/제27조", test_ad_guide_has_patient_inducement),
        ("[LLM] 위반 감지", test_ad_review_detects_violations),
    ]
    passed = failed = skipped = 0
    print("=== 의료광고 검토 회귀 테스트 ===")
    for label, fn in _tests:
        try:
            fn()
            passed += 1
            print(f"  [PASS] {label}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {label} :: {e}")
        except _Skip as e:
            skipped += 1
            print(f"  [SKIP] {label} :: {e}")
        except BaseException as e:  # pytest Skipped 도 skip 으로 처리
            if type(e).__name__ == "Skipped":
                skipped += 1
                print(f"  [SKIP] {label} :: {e}")
            else:
                failed += 1
                print(f"  [FAIL] {label} :: {type(e).__name__}: {e}")
    print(f"\n  PASS {passed} / FAIL {failed} / SKIP {skipped} (총 {len(_tests)})")
    sys.exit(1 if failed else 0)
