"""챗봇 answer_segments 회귀 테스트 — segment_answer() 순수함수 검증.

answer 문자열의 [n]을 sources(n 기준)와 대조해 text/cite 토큰 배열로 쪼개는
로직만 검증한다. DB/LLM 불필요(순수 함수). 키 없이 항상 전부 실행된다.

핵심 계약:
  - type="text" : 본문 조각(매칭 안 된 [n] 강등 포함)
  - type="cite" : sources에 매칭된 인용(n/source_type/source_id/label 채움)
  - sources에 없는 [n]은 cite가 아니라 text로 강등(Citation Firewall 철학)
  - 빈 answer → []
  - cite 토큰의 {source_type, source_id}는 그대로 /v1/related-graph seed
  - 모든 토큰 text를 이으면 원본 answer 무손실 복원

실행:
  python3 tests/test_chat_segments.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.routers.chat import segment_answer  # noqa: E402
from app.schemas import AnswerSegment, ChatSource  # noqa: E402


def _src(n, source_type, source_id, label):
    return ChatSource(n=n, label=label, source_type=source_type, source_id=source_id)


# ── 1) 기본 분해 ──────────────────────────────────────────────────────────────
def test_basic_split():
    answer = "이는 위반입니다 [1] 그리고 [2] 참고."
    sources = [
        _src(1, "statute", 10, "의료법 제56조"),
        _src(2, "case", 20, "대법원 2018두12345"),
    ]
    segs = segment_answer(answer, sources)

    # 토큰 순서: text / cite / text / cite / text
    assert [s.type for s in segs] == ["text", "cite", "text", "cite", "text"], \
        [s.type for s in segs]

    # text 조각 내용 정확
    assert segs[0].text == "이는 위반입니다 "
    assert segs[2].text == " 그리고 "
    assert segs[4].text == " 참고."

    # 첫 cite 토큰: type/n/source_type/source_id/label 정확
    c1 = segs[1]
    assert c1.type == "cite"
    assert c1.text == "[1]"
    assert c1.n == 1
    assert c1.source_type == "statute"
    assert c1.source_id == 10
    assert c1.label == "의료법 제56조"

    # 둘째 cite 토큰
    c2 = segs[3]
    assert c2.type == "cite"
    assert c2.text == "[2]"
    assert c2.n == 2
    assert c2.source_type == "case"
    assert c2.source_id == 20
    assert c2.label == "대법원 2018두12345"


# ── 2) 연속 인용 [1][2] ───────────────────────────────────────────────────────
def test_adjacent_citations():
    answer = "근거는 [1][2] 입니다."
    sources = [
        _src(1, "statute", 10, "의료법 제56조"),
        _src(2, "case", 20, "대법원 2018두12345"),
    ]
    segs = segment_answer(answer, sources)

    # text / cite / cite / text — 인접 cite 2개 사이에 text 토큰이 없어야 함
    assert [s.type for s in segs] == ["text", "cite", "cite", "text"], \
        [s.type for s in segs]
    assert segs[0].text == "근거는 "
    assert segs[1].text == "[1]" and segs[1].n == 1
    assert segs[2].text == "[2]" and segs[2].n == 2
    assert segs[3].text == " 입니다."


# ── 3) 미매칭 [n] 강등 ────────────────────────────────────────────────────────
def test_unmatched_citation_demoted_to_text():
    answer = "이 부분은 [9] 근거가 없습니다."
    sources = [_src(1, "statute", 10, "의료법 제56조")]  # n=9 없음
    segs = segment_answer(answer, sources)

    # [9]는 cite로 만들지 않고 text 토큰으로 유지(Citation Firewall)
    cites = [s for s in segs if s.type == "cite"]
    assert cites == [], "매칭 안 된 [9]는 cite가 되면 안 됨"

    # "[9]" 문자열이 어떤 text 토큰에든 그대로 보존되어야 함
    nine = [s for s in segs if s.type == "text" and "[9]" in s.text]
    assert nine, f"[9]가 text로 유지되지 않음: {[s.text for s in segs]}"


# ── 4) 인용 없음 ──────────────────────────────────────────────────────────────
def test_no_citation():
    answer = "그냥 평문."
    segs = segment_answer(answer, [])
    assert len(segs) == 1
    assert segs[0].type == "text"
    assert segs[0].text == "그냥 평문."


# ── 5) 빈 문자열 ──────────────────────────────────────────────────────────────
def test_empty_answer():
    assert segment_answer("", []) == []
    # sources가 있어도 빈 answer면 토큰 없음
    assert segment_answer("", [_src(1, "statute", 10, "의료법 제56조")]) == []


# ── 6) seed 적합성 — cite 토큰 → /v1/related-graph seed ───────────────────────
def test_cite_token_is_valid_graph_seed():
    answer = "위반입니다 [1], 판례 [2]."
    sources = [
        _src(1, "statute", 10, "의료법 제56조"),
        _src(2, "case", 20, "대법원 2018두12345"),
    ]
    segs = segment_answer(answer, sources)
    cites = [s for s in segs if s.type == "cite"]
    assert len(cites) == 2

    # cite 토큰에서 {source_type, source_id}만 뽑으면 GraphSeed 형태로 그대로 사용 가능
    seeds = [{"source_type": s.source_type, "source_id": s.source_id} for s in cites]
    assert seeds == [
        {"source_type": "statute", "source_id": 10},
        {"source_type": "case", "source_id": 20},
    ]

    # 실제로 GraphSeed로 구성 가능한지(값 일치) 검증
    from app.schemas import GraphSeed
    for s, src in zip(cites, sources):
        seed = GraphSeed(source_type=s.source_type, source_id=s.source_id)
        assert seed.source_type == src.source_type
        assert seed.source_id == src.source_id


# ── 7) 재조립 무손실 — 토큰 text 이으면 원본 복원 ─────────────────────────────
def test_reassembly_lossless():
    cases = [
        ("이는 위반입니다 [1] 그리고 [2] 참고.",
         [_src(1, "statute", 10, "의료법 제56조"), _src(2, "case", 20, "대법원 2018두12345")]),
        ("근거는 [1][2] 입니다.",
         [_src(1, "statute", 10, "A"), _src(2, "case", 20, "B")]),
        ("이 부분은 [9] 근거가 없습니다.", [_src(1, "statute", 10, "A")]),
        ("그냥 평문.", []),
        ("[1] 맨 앞 인용도 보존되는지.", [_src(1, "statute", 10, "A")]),
        ("맨 끝 인용 [1]", [_src(1, "statute", 10, "A")]),
    ]
    for answer, sources in cases:
        segs = segment_answer(answer, sources)
        rebuilt = "".join(s.text for s in segs)
        assert rebuilt == answer, f"무손실 실패: {answer!r} -> {rebuilt!r}"


# ── 단독 러너 ────────────────────────────────────────────────────────────────
def _run():
    tests = [
        test_basic_split,
        test_adjacent_citations,
        test_unmatched_citation_demoted_to_text,
        test_no_citation,
        test_empty_answer,
        test_cite_token_is_valid_graph_seed,
        test_reassembly_lossless,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  [OK ] {t.__name__}")
        except Exception as e:  # noqa: BLE001
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n  answer_segments {passed}/{len(tests)} passed")
    return passed == len(tests)


if __name__ == "__main__":
    ok = _run()
    sys.exit(0 if ok else 1)
