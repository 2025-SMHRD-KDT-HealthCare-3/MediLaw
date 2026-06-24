"""연관 판례 그래프 테스트 — DB/LLM 없이 monkeypatch로 핵심 로직(특히 Citation Firewall) 검증.

실제 검색/LLM 호출 없이 app.related_graph.rag.hybrid_search 와 app.related_graph.llm.chat_json
를 교체해, 환각 idx 차단·폴백·빈 결과 처리를 단언한다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.related_graph as mod  # noqa: E402
from app.llm import LLMUnavailable  # noqa: E402
from app.schemas import Hit  # noqa: E402


def _hits():
    """statute 2개 + case 2개 가짜 히트."""
    return [
        Hit(source_type="statute", source_id=10, label="의료법 제56조", title="과대광고 금지",
            snippet="누구든지 거짓이나 과장된 의료광고를 하지 못한다.", trust_grade="법령"),
        Hit(source_type="case", source_id=20, label="대법원 2018두12345", title="허위광고 사건",
            snippet="과장광고로 업무정지 1개월 처분이 적법하다고 판단.", trust_grade="판례",
            source_url="http://law.example/20"),
        Hit(source_type="case", source_id=21, label="서울행법 2020구합6789", title="비교광고 사건",
            snippet="타 기관 비교광고에 대해 시정명령.", trust_grade="판례",
            source_url="http://law.example/21"),
        Hit(source_type="statute", source_id=11, label="의료법 제27조", title="무면허 의료행위",
            snippet="환자 유인 금지.", trust_grade="법령"),
    ]


def _patch(monkeypatch_hits, chat_json):
    mod.rag.hybrid_search = lambda text, top_k=12, as_of=None: (monkeypatch_hits, "hybrid")
    mod.llm.chat_json = chat_json


def _restore(orig_search, orig_chat):
    mod.rag.hybrid_search = orig_search
    mod.llm.chat_json = orig_chat


def test_firewall_drops_hallucinated_and_mistyped_refs():
    orig_s, orig_c = mod.rag.hybrid_search, mod.llm.chat_json
    hits = _hits()
    # LLM이 환각 idx(99), 잘못된 type(statute idx 0 을 case_refs에), 유효 idx(1) 섞어 반환.
    fake = {
        "issues": [
            {"label": "과장·허위 광고", "statute_ref": 0,
             "case_refs": [1, 99, 0], "sanctions": ["업무정지 1개월"]},
            #         유효^   환각^  statute를 case로 오참조^(버려야 함)
            {"label": "엉터리", "statute_ref": 7, "case_refs": [999]},  # 근거 0 → issue 제거
        ]
    }
    _patch(hits, lambda messages: fake)
    try:
        resp = mod.build_related_graph("국내 1위 100% 효과", lang="ko")
    finally:
        _restore(orig_s, orig_c)

    assert resp.llm is True
    assert len(resp.issues) == 1                       # 근거 없는 두 번째 issue는 제거됨
    issue = resp.issues[0]
    assert issue.statute == "의료법 제56조"             # 유효 statute idx
    assert [c.source_id for c in issue.cases] == [20]  # idx 1 만 살아남음(99/0 제거)
    assert issue.cases[0].source_url == "http://law.example/20"
    assert issue.sanctions == ["업무정지 1개월"]


def test_fallback_when_llm_unavailable():
    orig_s, orig_c = mod.rag.hybrid_search, mod.llm.chat_json
    hits = _hits()

    def boom(messages):
        raise LLMUnavailable("no key")

    _patch(hits, boom)
    try:
        resp = mod.build_related_graph("광고 문구", lang="ko")
    finally:
        _restore(orig_s, orig_c)

    assert resp.llm is False
    assert len(resp.issues) == 1
    issue = resp.issues[0]
    assert issue.label == "관련 판례·근거"
    assert {c.source_id for c in issue.cases} == {20, 21}   # 판례 전부 단일 쟁점에
    assert issue.statute == "의료법 제56조"                 # 첫 조문 대표로


def test_empty_issues_falls_back_to_rules():
    # LLM이 성공했지만 유효 issue 0개 → 규칙 폴백으로라도 채우고 llm=False 표기.
    orig_s, orig_c = mod.rag.hybrid_search, mod.llm.chat_json
    hits = _hits()
    _patch(hits, lambda messages: {"issues": []})
    try:
        resp = mod.build_related_graph("광고", lang="ko")
    finally:
        _restore(orig_s, orig_c)
    assert resp.llm is False
    assert len(resp.issues) == 1


def test_no_hits_returns_empty_graph():
    orig_s, orig_c = mod.rag.hybrid_search, mod.llm.chat_json
    mod.rag.hybrid_search = lambda text, top_k=12, as_of=None: ([], "fts")
    mod.llm.chat_json = lambda messages: {"issues": [{"label": "x"}]}  # 호출되면 안 됨
    try:
        resp = mod.build_related_graph("아무거나", lang="ko")
    finally:
        _restore(orig_s, orig_c)
    assert resp.issues == []
    assert resp.llm is False
    assert resp.root.text == "아무거나"


def test_blank_text_short_circuits():
    resp = mod.build_related_graph("   ", lang="en")
    assert resp.issues == []
    assert resp.root.label == "Input text"


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
