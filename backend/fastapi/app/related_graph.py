"""연관 판례 그래프 — '더보기' 클릭 시 입력 문구를 위반 쟁점별 판례·제재 그래프로 구조화.

기존 연관 판례 표시는 평평한 텍스트 리스트지만, 프론트 마인드맵은 3층 구조가 필요하다:

    입력 문구(root)
      └─ 위반 쟁점(issue)            ← 검색 히트를 '분류'
            └─ 판례 + 제재수위(case)  ← 판례 묶기 + 제재 '추출'

흐름:
  1) hybrid_search(text) — 실재하는 조문·판례 히트만 확보(사건번호·출처URL 포함).
  2) gpt-5.5(chat_json)로 히트들을 쟁점 클러스터로 묶고, 각 판례의 제재수위를 추출.
     LLM은 후보를 **idx로만** 참조 → 목록 밖 판례/조문을 새로 만들 수 없음.
  3) Citation Firewall — LLM이 돌려준 idx가 실제 후보(그리고 올바른 type)인지 검증해
     환각/오참조를 버리고, 남은 것만 실제 Hit 데이터로 그래프를 만든다.
  LLM 불가/실패/빈 결과면 규칙 기반 폴백(판례를 단일 쟁점으로 묶음)으로 graceful degrade.

챗봇 답변·PDF 검토 finding 어디서든 '보고 있던 텍스트' 한 줄만 주면 재사용된다(공용).
"""
from app import llm, rag
from app.llm import LLMUnavailable
from app.schemas import (
    GraphCase,
    GraphIssue,
    GraphRoot,
    GraphSeed,
    RelatedGraphResponse,
)

# 쟁점/제재 과다 방지 상한.
_MAX_ISSUES = 5
_MAX_SANCTIONS = 4
_SNIPPET_MAX = 280


def _case_node(hit) -> GraphCase:
    return GraphCase(
        source_id=hit.source_id,
        label=hit.label,
        title=hit.title,
        summary=(hit.snippet or "")[:_SNIPPET_MAX],
        source_url=hit.source_url,
    )


def _seed_hit(seed: GraphSeed):
    """seed(클릭한 인용) → 실제 Hit 복원. rag의 기존 Hit 빌더 재사용. 없으면 None(graceful)."""
    if seed.source_type == "statute":
        return rag._statute_hit(seed.source_id, 0.0)
    if seed.source_type == "case":
        return rag._case_hit(seed.source_id, 0.0)
    # interpretation / decision / guideline
    return rag._doc_hit(seed.source_id, 0.0)


def _merge_seeds(hits: list, seeds: list[GraphSeed] | None) -> list:
    """seed의 Hit을 복원해 hits 풀에 없는 것만 병합. dedup 키=(source_type, source_id).

    LLM 후보와 폴백 모두 seed를 볼 수 있게 한다. seed가 있으면 hits가 비어도 seed만으로 그래프를 만든다.
    """
    merged = list(hits)
    if not seeds:
        return merged
    present = {(h.source_type, h.source_id) for h in merged}
    for seed in seeds:
        key = (seed.source_type, seed.source_id)
        if key in present:
            continue
        hit = _seed_hit(seed)
        if hit is None:
            continue  # 복원 실패 → 무시
        present.add(key)
        merged.append(hit)
    return merged


def _seed_targets(seeds: list[GraphSeed] | None) -> tuple[set[int], list[str]]:
    """seed를 보정 패스용으로 분해 — (seed case source_id 집합, seed statute 라벨 목록)."""
    seed_case_keys: set[int] = set()
    seed_statute_labels: list[str] = []
    if not seeds:
        return seed_case_keys, seed_statute_labels
    seen_labels: set[str] = set()
    for seed in seeds:
        if seed.source_type == "case":
            seed_case_keys.add(seed.source_id)
        elif seed.source_type == "statute":
            hit = _seed_hit(seed)
            if hit and hit.label and hit.label not in seen_labels:
                seen_labels.add(hit.label)
                seed_statute_labels.append(hit.label)
    return seed_case_keys, seed_statute_labels


def _ensure_seeds(
    issues: list[GraphIssue],
    hits: list,
    seeds: list[GraphSeed] | None,
    lang: str,
) -> list[GraphIssue]:
    """최종 보정 패스(LLM/폴백 공통) — seed 보장 + 강조.

    - seed case가 어떤 issue.cases에 있으면 highlighted=True.
    - seed statute 라벨이 어떤 issue.statute면 그 issue.statute_highlighted=True.
    - 어디에도 안 들어간 seed case가 있으면 맨 앞에 '클릭한 인용' issue 추가.
    - seed statute가 어떤 issue.statute로도 안 나타났고 위 issue도 안 만들어졌다면,
      그 seed statute를 가진 '클릭한 인용' issue를 앞에 추가(cases=[]).
    """
    seed_case_keys, seed_statute_labels = _seed_targets(seeds)
    if not seed_case_keys and not seed_statute_labels:
        return issues  # seed 없음 → 기존 동작과 동일

    statute_label_set = set(seed_statute_labels)
    statute_shown = False  # seed statute가 기존 issue.statute로 한 번이라도 나타났는가
    found_case_keys: set[int] = set()

    # 기존 issues 강조
    for issue in issues:
        if issue.statute and issue.statute in statute_label_set:
            issue.statute_highlighted = True
            statute_shown = True
        for case in issue.cases:
            if case.source_id in seed_case_keys:
                case.highlighted = True
                found_case_keys.add(case.source_id)

    # 누락된 seed case 복원(highlighted=True)
    missing_keys = seed_case_keys - found_case_keys
    missing_cases: list[GraphCase] = []
    if missing_keys:
        hit_by_case = {h.source_id: h for h in hits if h.source_type == "case"}
        for key in missing_keys:
            hit = hit_by_case.get(key)
            if hit is None:
                continue
            node = _case_node(hit)
            node.highlighted = True
            missing_cases.append(node)

    first_statute = seed_statute_labels[0] if seed_statute_labels else ""

    if missing_cases:
        # 누락 seed case가 있으면 '클릭한 인용' issue를 맨 앞에 추가.
        label = "클릭한 인용" if lang != "en" else "Clicked citation"
        issues.insert(0, GraphIssue(
            label=label,
            statute=first_statute,
            statute_highlighted=bool(first_statute),
            cases=missing_cases,
            sanctions=[],
        ))
    elif seed_statute_labels and not statute_shown:
        # seed statute가 어떤 issue.statute로도 안 나타났고 위 issue도 없었다면 추가(cases=[]).
        label = "클릭한 인용" if lang != "en" else "Clicked citation"
        issues.insert(0, GraphIssue(
            label=label,
            statute=first_statute,
            statute_highlighted=True,
            cases=[],
            sanctions=[],
        ))
    return issues


def _candidates(hits) -> list[dict]:
    """LLM에 넘길 후보 근거 목록 — idx로만 참조시켜 환각을 원천 차단."""
    return [
        {
            "idx": i,
            "type": h.source_type,
            "label": h.label,
            "title": h.title,
            "snippet": (h.snippet or "")[:_SNIPPET_MAX],
        }
        for i, h in enumerate(hits)
    ]


_SYS_KO = (
    "당신은 의료·헬스케어 법률 컴플라이언스 분석가입니다. 사용자가 보고 있던 '입력 문구'와, "
    "검색으로 찾은 '후보 근거' 목록(조문·판례)이 주어집니다. 후보를 위반 '쟁점(issue)'별로 묶어 "
    "JSON으로 정리하세요.\n"
    "규칙:\n"
    "- 반드시 제공된 후보의 idx만 사용하세요. 목록에 없는 판례·조문을 새로 만들지 마세요(환각 금지).\n"
    "- 각 issue 형식: {label(쟁점명, 짧게), statute_ref(관련 조문 후보 idx 또는 null), "
    "case_refs(판례 후보 idx 배열), sanctions(제재 문자열 배열)}.\n"
    "- sanctions 는 해당 판례 snippet에 '명시적으로' 나타난 처분/제재(업무정지·벌금·자격정지·"
    "시정명령·과징금 등)만 적으세요. 근거가 없으면 빈 배열.\n"
    "- 쟁점은 1~5개. 입력 문구와 무관한 후보는 빼도 됩니다.\n"
    '출력은 {"issues": [...]} JSON 객체만.'
)
_SYS_EN = (
    "You are a medical-law compliance analyst. You get an 'input text' the user was viewing and a list "
    "of 'candidate sources' (statutes/precedents) found by search. Group candidates into violation "
    "'issues' as JSON.\n"
    "Rules:\n"
    "- Use ONLY the provided candidate idx values. Never invent precedents/statutes not in the list.\n"
    "- Each issue: {label, statute_ref(candidate idx or null), case_refs(array of idx), "
    "sanctions(array of strings)}.\n"
    "- sanctions: only penalties explicitly present in that precedent's snippet; else empty.\n"
    "- 1~5 issues. Drop irrelevant candidates.\n"
    'Output only a JSON object {"issues": [...]}.'
)


def _clean_sanctions(raw) -> list[str]:
    out: list[str] = []
    if not isinstance(raw, list):
        return out
    for s in raw:
        if isinstance(s, str) and s.strip():
            out.append(s.strip()[:60])
        if len(out) >= _MAX_SANCTIONS:
            break
    return out


def _firewall_issue(raw: dict, hits) -> GraphIssue | None:
    """LLM이 만든 issue 한 개를 검증 — 유효 idx만 실제 Hit으로 복원. 환각 idx는 버림."""
    if not isinstance(raw, dict):
        return None
    label = str(raw.get("label") or "").strip()
    if not label:
        return None

    # statute_ref: 유효하고 실제로 statute 인 후보만 인정.
    statute = ""
    sref = raw.get("statute_ref")
    if isinstance(sref, int) and 0 <= sref < len(hits) and hits[sref].source_type == "statute":
        statute = hits[sref].label

    # case_refs: 유효하고 실제로 case 인 후보만. 중복 제거.
    cases: list[GraphCase] = []
    seen: set[int] = set()
    refs = raw.get("case_refs")
    if isinstance(refs, list):
        for r in refs:
            if not isinstance(r, int) or r in seen or not (0 <= r < len(hits)):
                continue
            if hits[r].source_type != "case":
                continue
            seen.add(r)
            cases.append(_case_node(hits[r]))

    if not cases and not statute:
        return None  # 근거가 하나도 안 남으면 노드 자체를 만들지 않음
    return GraphIssue(
        label=label,
        statute=statute,
        cases=cases,
        sanctions=_clean_sanctions(raw.get("sanctions")),
    )


def _structure_with_llm(text: str, hits, lang: str) -> list[GraphIssue]:
    """gpt-5.5로 쟁점 클러스터링 + 제재 추출. 실패 시 LLMUnavailable 전파."""
    sys = _SYS_EN if lang == "en" else _SYS_KO
    payload = {"input_text": text[:1000], "candidates": _candidates(hits)}
    import json

    data = llm.chat_json([
        {"role": "system", "content": sys},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ])
    issues_raw = data.get("issues") if isinstance(data, dict) else None
    if not isinstance(issues_raw, list):
        return []
    issues: list[GraphIssue] = []
    for raw in issues_raw[:_MAX_ISSUES]:
        issue = _firewall_issue(raw, hits)
        if issue:
            issues.append(issue)
    return issues


def _structure_fallback(hits) -> list[GraphIssue]:
    """LLM 불가 시 규칙 폴백 — 판례를 단일 쟁점으로 묶고 대표 조문을 붙임."""
    cases = [_case_node(h) for h in hits if h.source_type == "case"]
    statute = next((h.label for h in hits if h.source_type == "statute"), "")
    if not cases and not statute:
        return []
    return [GraphIssue(label="관련 판례·근거", statute=statute, cases=cases, sanctions=[])]


def build_related_graph(
    text: str,
    lang: str = "ko",
    as_of: str | None = None,
    top_k: int = 12,
    seeds: list[GraphSeed] | None = None,
) -> RelatedGraphResponse:
    """입력 문구 → 연관 판례 그래프(root/issues). 챗봇·PDF 검토 공용.

    seeds(클릭한 인용)가 있으면 검색 결과에 병합해 그래프에 반드시 포함·강조한다.
    seeds 없으면 기존 동작과 100% 동일(하위호환).
    """
    text = (text or "").strip()
    root = GraphRoot(
        label="입력 문구" if lang != "en" else "Input text",
        text=text[:200],
    )
    if not text and not seeds:
        return RelatedGraphResponse(root=root, issues=[], method="fts", llm=False)

    if text:
        hits, method = rag.hybrid_search(text, top_k=top_k, as_of=as_of)
    else:
        # text 없이 seed만 있는 경우: 검색 없이 seed만으로 그래프 구성.
        hits, method = [], "fts"

    # seed의 Hit을 풀에 병합 → LLM 후보·폴백·보정 모두 seed를 본다.
    hits = _merge_seeds(hits, seeds)
    if not hits:
        return RelatedGraphResponse(root=root, issues=[], method=method, llm=False)

    used_llm = True
    try:
        issues = _structure_with_llm(text, hits, lang)
    except LLMUnavailable:
        issues, used_llm = [], False

    if not issues:
        # LLM이 비었거나 불가 → 규칙 폴백으로라도 그래프를 채운다.
        issues = _structure_fallback(hits)
        used_llm = False

    # 최종 보정 패스(LLM/폴백 공통) — seed 보장 + 강조.
    issues = _ensure_seeds(issues, hits, seeds, lang)

    return RelatedGraphResponse(root=root, issues=issues, method=method, llm=used_llm)
