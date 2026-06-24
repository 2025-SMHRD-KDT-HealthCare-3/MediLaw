"""연관 판례 그래프 — seed 앵커링(옵션②) 회귀 테스트. DB/LLM 없이 monkeypatch 검증.

기존 tests/test_related_graph.py 와 동일한 __main__ 러너 패턴.
mod.rag.hybrid_search / mod.llm.chat_json 뿐 아니라 mod.rag._case_hit / _statute_hit /
_doc_hit 까지 가짜로 교체해, seed→Hit 복원(_seed_hit)·병합(_merge_seeds)·보정(_ensure_seeds)을
실제 DB 없이 시뮬레이션한다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.related_graph as mod  # noqa: E402
from app.llm import LLMUnavailable  # noqa: E402
from app.schemas import GraphSeed, Hit  # noqa: E402


# ---------- 공통 가짜 데이터 ----------
def _hits():
    """statute 2개 + case 2개 가짜 검색 히트(seed 와 무관한 일반 풀)."""
    return [
        Hit(source_type="statute", source_id=10, label="의료법 제56조", title="과대광고 금지",
            snippet="누구든지 거짓이나 과장된 의료광고를 하지 못한다.", trust_grade="법령"),
        Hit(source_type="case", source_id=20, label="대법원 2018두12345", title="허위광고 사건",
            snippet="과장광고로 업무정지 1개월 처분이 적법.", trust_grade="판례",
            source_url="http://law.example/20"),
        Hit(source_type="case", source_id=21, label="서울행법 2020구합6789", title="비교광고 사건",
            snippet="타 기관 비교광고에 대해 시정명령.", trust_grade="판례",
            source_url="http://law.example/21"),
        Hit(source_type="statute", source_id=11, label="의료법 제27조", title="무면허 의료행위",
            snippet="환자 유인 금지.", trust_grade="법령"),
    ]


# seed source_id → 복원될 가짜 Hit. _case_hit / _statute_hit 가 이 표를 참조.
_SEED_CASE_DB = {
    30: Hit(source_type="case", source_id=30, label="대법원 2022두9999", title="클릭 판례",
            snippet="클릭한 판례 본문.", trust_grade="판례", source_url="http://law.example/30"),
    20: Hit(source_type="case", source_id=20, label="대법원 2018두12345", title="허위광고 사건",
            snippet="과장광고로 업무정지 1개월 처분이 적법.", trust_grade="판례",
            source_url="http://law.example/20"),
}
_SEED_STATUTE_DB = {
    10: Hit(source_type="statute", source_id=10, label="의료법 제56조", title="과대광고 금지",
            snippet="누구든지 거짓이나 과장된 의료광고를 하지 못한다.", trust_grade="법령"),
    40: Hit(source_type="statute", source_id=40, label="약사법 제68조", title="의약품 광고",
            snippet="거짓·과장 광고 금지.", trust_grade="법령"),
}


def _fake_case_hit(case_id, score, snippet=""):
    return _SEED_CASE_DB.get(case_id)


def _fake_statute_hit(article_id, score, snippet=""):
    return _SEED_STATUTE_DB.get(article_id)


def _fake_doc_hit(doc_id, score, snippet=""):
    return None


class _Saved:
    """원본 함수 저장/복원 헬퍼(테스트 격리)."""

    def __init__(self):
        self.search = mod.rag.hybrid_search
        self.chat = mod.llm.chat_json
        self.case_hit = mod.rag._case_hit
        self.statute_hit = mod.rag._statute_hit
        self.doc_hit = mod.rag._doc_hit

    def restore(self):
        mod.rag.hybrid_search = self.search
        mod.llm.chat_json = self.chat
        mod.rag._case_hit = self.case_hit
        mod.rag._statute_hit = self.statute_hit
        mod.rag._doc_hit = self.doc_hit


def _patch(saved, hits, chat_json, method="hybrid"):
    mod.rag.hybrid_search = lambda text, top_k=12, as_of=None: (list(hits), method)
    mod.llm.chat_json = chat_json
    mod.rag._case_hit = _fake_case_hit
    mod.rag._statute_hit = _fake_statute_hit
    mod.rag._doc_hit = _fake_doc_hit


def _clicked_label(lang):
    return "Clicked citation" if lang == "en" else "클릭한 인용"


# ---------- 1. seed case가 LLM 결과에 이미 포함 → highlighted, 중복 issue 없음 ----------
def test_seed_case_present_is_highlighted_no_duplicate_issue():
    saved = _Saved()
    hits = _hits()
    # LLM 이 seed case(20)를 issue 안에 이미 넣어줌.
    fake = {"issues": [
        {"label": "과장·허위 광고", "statute_ref": 0, "case_refs": [1, 2],
         "sanctions": ["업무정지 1개월"]},
    ]}
    _patch(saved, hits, lambda messages: fake)
    try:
        resp = mod.build_related_graph(
            "광고 문구", lang="ko", seeds=[GraphSeed(source_type="case", source_id=20)])
    finally:
        saved.restore()

    assert resp.llm is True
    # "클릭한 인용" issue 가 새로 생기면 안 됨.
    assert all(iss.label != "클릭한 인용" for iss in resp.issues)
    assert len(resp.issues) == 1
    cases = {c.source_id: c for c in resp.issues[0].cases}
    assert cases[20].highlighted is True   # seed case 강조됨
    assert cases[21].highlighted is False  # 비-seed 는 강조 안 됨


# ---------- 2. seed case를 LLM이 누락 → 맨 앞 "클릭한 인용" issue 생성 + highlighted ----------
def test_missing_seed_case_creates_clicked_issue():
    saved = _Saved()
    hits = _hits()
    # LLM 은 seed case(30)를 모름 → 일반 case(20)만 포함.
    fake = {"issues": [
        {"label": "과장·허위 광고", "statute_ref": 0, "case_refs": [1], "sanctions": []},
    ]}
    _patch(saved, hits, lambda messages: fake)
    try:
        resp = mod.build_related_graph(
            "광고 문구", lang="ko", seeds=[GraphSeed(source_type="case", source_id=30)])
    finally:
        saved.restore()

    assert resp.llm is True
    # 맨 앞이 "클릭한 인용" issue.
    assert resp.issues[0].label == "클릭한 인용"
    clicked = resp.issues[0]
    assert [c.source_id for c in clicked.cases] == [30]
    assert clicked.cases[0].highlighted is True
    assert clicked.cases[0].label == "대법원 2022두9999"
    # 그래프 전체에 seed case 가 반드시 존재.
    all_ids = {c.source_id for iss in resp.issues for c in iss.cases}
    assert 30 in all_ids
    # 기존 LLM issue 도 보존.
    assert any(iss.label == "과장·허위 광고" for iss in resp.issues)


# ---------- 3. seed statute가 LLM issue.statute와 일치 → statute_highlighted ----------
def test_seed_statute_match_sets_statute_highlighted():
    saved = _Saved()
    hits = _hits()
    # LLM issue 가 의료법 제56조(idx 0)를 statute 로 사용.
    fake = {"issues": [
        {"label": "과장·허위 광고", "statute_ref": 0, "case_refs": [1], "sanctions": []},
    ]}
    _patch(saved, hits, lambda messages: fake)
    try:
        resp = mod.build_related_graph(
            "광고 문구", lang="ko", seeds=[GraphSeed(source_type="statute", source_id=10)])
    finally:
        saved.restore()

    assert resp.llm is True
    # 중복 "클릭한 인용" issue 안 생김(statute 가 이미 노출됨).
    assert all(iss.label != "클릭한 인용" for iss in resp.issues)
    assert len(resp.issues) == 1
    issue = resp.issues[0]
    assert issue.statute == "의료법 제56조"
    assert issue.statute_highlighted is True


# ---------- 4. seed statute가 결과에 없음 → cases=[] "클릭한 인용" issue 앞에 추가 ----------
def test_missing_seed_statute_creates_statute_only_issue():
    saved = _Saved()
    hits = _hits()
    # seed statute(40, 약사법) 은 어떤 LLM issue.statute 에도 안 나타남. 누락 seed case 도 없음.
    fake = {"issues": [
        {"label": "과장·허위 광고", "statute_ref": 0, "case_refs": [1], "sanctions": []},
    ]}
    _patch(saved, hits, lambda messages: fake)
    try:
        resp = mod.build_related_graph(
            "광고 문구", lang="ko", seeds=[GraphSeed(source_type="statute", source_id=40)])
    finally:
        saved.restore()

    assert resp.llm is True
    front = resp.issues[0]
    assert front.label == "클릭한 인용"
    assert front.cases == []
    assert front.statute == "약사법 제68조"
    assert front.statute_highlighted is True
    # 기존 issue 는 그대로 뒤에 존재.
    assert resp.issues[1].label == "과장·허위 광고"


# ---------- 5. 검색 0건 + seed만 있음 → seed만으로 그래프 생성(빈 그래프 아님) ----------
def test_seed_only_no_search_hits_builds_graph():
    saved = _Saved()
    # 검색은 0건. LLM 은 호출되더라도 seed Hit(case 30)을 후보로 보고 묶어야 함.
    # 단순화를 위해 LLM 이 빈 결과 → 폴백 경로로 graceful.
    _patch(saved, [], lambda messages: {"issues": []})
    try:
        resp = mod.build_related_graph(
            "광고 문구", lang="ko", seeds=[GraphSeed(source_type="case", source_id=30)])
    finally:
        saved.restore()

    # seed 만으로 빈 그래프가 아니어야 한다.
    assert resp.issues != []
    all_ids = {c.source_id for iss in resp.issues for c in iss.cases}
    assert 30 in all_ids
    # 그 seed case 는 highlighted.
    seed_node = next(c for iss in resp.issues for c in iss.cases if c.source_id == 30)
    assert seed_node.highlighted is True


# ---------- 6. seed 복원 실패(_case_hit None) → graceful(예외 없이 seed 무시) ----------
def test_seed_restore_failure_is_graceful():
    saved = _Saved()
    hits = _hits()
    fake = {"issues": [
        {"label": "과장·허위 광고", "statute_ref": 0, "case_refs": [1], "sanctions": []},
    ]}
    _patch(saved, hits, lambda messages: fake)
    try:
        # source_id 999 는 _SEED_CASE_DB 에 없음 → _fake_case_hit 가 None 반환.
        resp = mod.build_related_graph(
            "광고 문구", lang="ko", seeds=[GraphSeed(source_type="case", source_id=999)])
    finally:
        saved.restore()

    # 예외 없이 정상 그래프. 복원 실패 seed 는 "클릭한 인용" issue 를 만들지 않음.
    assert resp.llm is True
    assert all(iss.label != "클릭한 인용" for iss in resp.issues)
    assert len(resp.issues) == 1
    all_ids = {c.source_id for iss in resp.issues for c in iss.cases}
    assert 999 not in all_ids


# ---------- 7. 하위호환: seeds 없음 → 기존 동작과 동일(전부 False, 클릭 issue 없음) ----------
def test_no_seeds_backward_compatible():
    saved = _Saved()
    hits = _hits()
    fake = {"issues": [
        {"label": "과장·허위 광고", "statute_ref": 0, "case_refs": [1, 2], "sanctions": []},
    ]}
    _patch(saved, hits, lambda messages: fake)
    try:
        resp_none = mod.build_related_graph("광고 문구", lang="ko")  # seeds 미지정
        resp_empty = mod.build_related_graph("광고 문구", lang="ko", seeds=[])  # 빈 리스트
    finally:
        saved.restore()

    for resp in (resp_none, resp_empty):
        assert all(iss.label != "클릭한 인용" for iss in resp.issues)
        for iss in resp.issues:
            assert iss.statute_highlighted is False
            for c in iss.cases:
                assert c.highlighted is False
    # 두 경로 결과 구조 동일.
    assert len(resp_none.issues) == len(resp_empty.issues) == 1


# ---------- 8. 폴백(LLMUnavailable) 경로에서도 seed 보장·강조 작동 ----------
def test_seed_works_on_fallback_path():
    saved = _Saved()
    hits = _hits()

    def boom(messages):
        raise LLMUnavailable("no key")

    _patch(saved, hits, boom)
    try:
        # seed case 30(누락, 복원됨) + seed statute 40(폴백 statute 와 불일치).
        resp = mod.build_related_graph(
            "광고 문구", lang="ko",
            seeds=[GraphSeed(source_type="case", source_id=30),
                   GraphSeed(source_type="statute", source_id=40)])
    finally:
        saved.restore()

    assert resp.llm is False  # 폴백 경로
    # 폴백은 _merge_seeds 로 병합된 case(20,21,+seed 30)를 단일 "관련 판례·근거" issue 로 묶음.
    # 따라서 seed case 30 은 이미 폴백 issue 안에 있어 '누락'이 아니라 그 자리에서 highlighted.
    seed_node = next(c for iss in resp.issues for c in iss.cases if c.source_id == 30)
    assert seed_node.highlighted is True
    fallback_issue = next(iss for iss in resp.issues if iss.label == "관련 판례·근거")
    assert {c.source_id for c in fallback_issue.cases} == {20, 21, 30}
    # seed statute 40(약사법) 은 폴백 statute(의료법 제56조)와 달라 어떤 issue.statute 로도
    # 안 나타나고(누락 seed case 도 없으므로), 계약상 statute-only "클릭한 인용" issue 가
    # 맨 앞에 추가된다(cases=[], statute_highlighted=True).
    front = resp.issues[0]
    assert front.label == "클릭한 인용"
    assert front.cases == []
    assert front.statute == "약사법 제68조"
    assert front.statute_highlighted is True


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fails = 0
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
        except Exception as e:  # noqa: BLE001
            fails += 1
            print("FAIL", fn.__name__, "->", type(e).__name__, e)
    print(f"--- {len(fns) - fails}/{len(fns)} passed")
    sys.exit(1 if fails else 0)
