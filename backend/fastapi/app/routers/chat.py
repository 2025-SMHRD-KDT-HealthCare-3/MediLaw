"""기획서 핵심기능 ① — AI 질의응답 챗봇.

흐름: 질문 → hybrid_search(근거) → gpt-5.5 답변생성(근거 강제인용)
     → Citation Firewall로 답변 인용 자동검증 → {answer, sources, citation_check}
POST /chat          : 단발 JSON
POST /chat/stream   : SSE 토큰 스트리밍 (sources → token... → done)
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app import llm
from app.auth import require_api_key
from app.citations import extract_and_verify, summarize
from app.english import detect_lang, english_article
from app.rag import hybrid_search
from app.schemas import (
    ChatRequest,
    ChatResponse,
    ChatSource,
    ChecklistItem,
    ChecklistRequest,
    ChecklistResponse,
    ChecklistSummary,
    VerifyResponse,
)

router = APIRouter(prefix="", tags=["AI 챗봇"])

MAX_HISTORY = 10  # 토큰 방어 — 최근 N턴만 LLM에 전달

SYSTEM_PROMPT = (
    "당신은 한국 의료·헬스케어 사업자를 위한 의료법 컴플라이언스 도우미입니다. "
    "의료법·개인정보보호법·생명윤리법·정보통신망법 및 관련 판례·해석례·가이드라인을 근거로 답합니다.\n"
    "규칙:\n"
    "1. 아래 [근거]에 있는 내용만 사용해 한국어로 답하세요.\n"
    "2. 근거에 없으면 추측하지 말고 '제공된 자료로는 확인되지 않습니다'라고 답하세요.\n"
    "3. 답변에 사용한 근거는 문장 끝에 [1], [2]처럼 번호로 인용하세요.\n"
    "4. 법령명과 조문번호는 근거에 적힌 그대로 정확히 쓰세요(없는 조문을 만들지 마세요).\n"
    "5. 마지막에 '※ 본 답변은 법률 자문이 아니라 정보 제공입니다.'를 한 줄 덧붙이세요."
)

SYSTEM_PROMPT_EN = (
    "You are a medical-law compliance assistant for healthcare businesses operating under Korean law "
    "(Medical Service Act, Personal Information Protection Act, Bioethics and Safety Act, "
    "Network Act) and related precedents, interpretations, and guidelines.\n"
    "Rules:\n"
    "1. Answer in English using ONLY the [Sources] below.\n"
    "2. If the sources do not cover it, say 'This cannot be confirmed from the provided materials.'\n"
    "3. Cite sources inline with [1], [2].\n"
    "4. Sources marked '(official English)' are the official English translation of a statute — "
    "quote the law and article names exactly as given. Sources marked '(Korean source)' have no "
    "official English version; translate them yourself and mark such text as '(unofficial translation)'.\n"
    "5. End with: '* This response is informational, not legal advice.'"
)

_NO_EVIDENCE = "제공된 자료로는 확인되지 않습니다. 질문을 더 구체화해 주세요.\n※ 본 답변은 법률 자문이 아니라 정보 제공입니다."
_NO_EVIDENCE_EN = ("This cannot be confirmed from the provided materials. Please make your question more specific.\n"
                   "* This response is informational, not legal advice.")

# 도메인 밖(잡담·코딩·날씨 등) 질문 거절 메시지 — RAG/생성 없이 즉시 반환.
_OUT_OF_DOMAIN = (
    "저는 의료법·개인정보보호법·생명윤리법·정보통신망법 등 의료·헬스케어 컴플라이언스 "
    "관련 질문만 도와드립니다. 관련 질문을 해주세요.\n"
    "※ 본 답변은 법률 자문이 아니라 정보 제공입니다."
)
_OUT_OF_DOMAIN_EN = (
    "I can only help with medical/healthcare compliance questions under Korean law "
    "(Medical Service Act, Personal Information Protection Act, Bioethics and Safety Act, "
    "Network Act, etc.). Please ask a related question.\n"
    "* This response is informational, not legal advice."
)


def _out_of_domain(req: ChatRequest, lang: str) -> bool:
    """도메인 가드 — 의료·헬스케어 컴플라이언스 밖이면 True. 애매하면 통과(False)."""
    history = [{"role": t.role, "content": t.content} for t in req.history[-MAX_HISTORY:]]
    return not llm.in_domain(req.question, history)


def _build(req: ChatRequest):
    """(messages, sources, method, lang, search_q). 근거 없으면 messages=None."""
    lang = req.lang if req.lang in ("ko", "en") else detect_lang(req.question)

    # 멀티턴이면 후속질문을 독립 한국어 질의로 재작성(검색 정확도↑, EN도 함께 해결).
    if req.history:
        search_q = llm.rewrite_query(
            [{"role": t.role, "content": t.content} for t in req.history[-MAX_HISTORY:]],
            req.question,
        )
    else:
        search_q = llm.translate(req.question, "ko") if lang == "en" else req.question

    hits, method = hybrid_search(
        search_q, req.source_types, top_k=req.top_k, as_of=req.as_of
    )
    sources: list[ChatSource] = []
    for i, h in enumerate(hits, 1):
        s = ChatSource(
            n=i, label=h.label, source_type=h.source_type, source_id=h.source_id,
            snippet=h.snippet, source_url=h.source_url, trust_grade=h.trust_grade,
        )
        if lang == "en" and h.source_type == "statute":
            en = english_article(h.source_id)
            if en:
                s.label_en = f"{en['law_name_en']} Article {en['article_no']}"
                s.snippet_en = en["body_en"]
                s.is_official_en = True
        sources.append(s)

    if not hits:
        return None, sources, method, lang, search_q

    if lang == "en":
        parts = []
        for s in sources:
            if s.is_official_en:
                parts.append(f"[{s.n}] {s.label_en} (official English)\n{s.snippet_en}")
            else:
                parts.append(f"[{s.n}] {s.label} (Korean source)\n{s.snippet}")
        system, user = SYSTEM_PROMPT_EN, f"Question: {req.question}\n\n[Sources]\n" + "\n\n".join(parts)
    else:
        context = "\n\n".join(f"[{s.n}] {s.label}\n{s.snippet}" for s in sources)
        system, user = SYSTEM_PROMPT, f"질문: {req.question}\n\n[근거]\n{context}"

    # 멀티턴: system → 이전 대화(최근 MAX_HISTORY턴) → 현재 질문+근거
    messages = [{"role": "system", "content": system}]
    messages += [{"role": t.role, "content": t.content} for t in req.history[-MAX_HISTORY:]]
    messages.append({"role": "user", "content": user})
    return messages, sources, method, lang, search_q


def _citation_check(answer: str, as_of) -> VerifyResponse:
    results = extract_and_verify(answer, as_of)
    return VerifyResponse(output=results, summary=summarize(results), as_of=as_of)


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_api_key)])
def chat(req: ChatRequest):
    lang = req.lang if req.lang in ("ko", "en") else detect_lang(req.question)
    if _out_of_domain(req, lang):
        refusal = _OUT_OF_DOMAIN_EN if lang == "en" else _OUT_OF_DOMAIN
        return ChatResponse(answer=refusal, sources=[], method="none", lang=lang,
                            search_query=req.question,
                            citation_check=_citation_check("", req.as_of), as_of=req.as_of)
    messages, sources, method, lang, search_q = _build(req)
    no_ev = _NO_EVIDENCE_EN if lang == "en" else _NO_EVIDENCE
    if messages is None:
        return ChatResponse(answer=no_ev, sources=[], method=method, lang=lang,
                            search_query=search_q,
                            citation_check=_citation_check("", req.as_of), as_of=req.as_of)
    try:
        answer = llm.chat(messages)
    except llm.LLMUnavailable as e:
        raise HTTPException(503, str(e))
    return ChatResponse(
        answer=answer, sources=sources, method=method, lang=lang, search_query=search_q,
        citation_check=_citation_check(answer, req.as_of), as_of=req.as_of,
    )


def _sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


@router.post("/chat/stream", dependencies=[Depends(require_api_key)])
def chat_stream(req: ChatRequest):
    lang = req.lang if req.lang in ("ko", "en") else detect_lang(req.question)
    if _out_of_domain(req, lang):
        refusal = _OUT_OF_DOMAIN_EN if lang == "en" else _OUT_OF_DOMAIN

        def gen_refuse():
            yield _sse({"type": "sources", "method": "none", "lang": lang,
                        "search_query": req.question, "sources": []})
            yield _sse({"type": "token", "text": refusal})
            yield _sse({"type": "done", "citation_check": _citation_check("", req.as_of).model_dump()})

        return StreamingResponse(gen_refuse(), media_type="text/event-stream")

    messages, sources, method, lang, search_q = _build(req)

    def gen():
        yield _sse({"type": "sources", "method": method, "lang": lang, "search_query": search_q,
                    "sources": [s.model_dump() for s in sources]})
        if messages is None:
            yield _sse({"type": "token", "text": _NO_EVIDENCE_EN if lang == "en" else _NO_EVIDENCE})
            yield _sse({"type": "done", "citation_check": _citation_check("", req.as_of).model_dump()})
            return
        parts = []
        try:
            for tok in llm.chat_stream(messages):
                parts.append(tok)
                yield _sse({"type": "token", "text": tok})
        except llm.LLMUnavailable as e:
            yield _sse({"type": "error", "message": str(e)})
            return
        answer = "".join(parts)
        yield _sse({"type": "done", "citation_check": _citation_check(answer, req.as_of).model_dump()})

    return StreamingResponse(gen(), media_type="text/event-stream")


# ───────────── 대화 종료 후 능동형 체크리스트 (POST /chat/checklist) ─────────────
# '체크리스트 생성' 버튼 → 그동안의 전체 대화 → 쟁점 추출 → RAG 근거검색 → LLM이
# '법적으로 대응·준비하기 위해 추가로 확인할 항목'을 근거 기반으로 생성.

CHECKLIST_SYSTEM = (
    "당신은 한국 의료·헬스케어 사업자의 법률 컴플라이언스 조력자입니다.\n"
    "[대화]는 사용자와 의료법 챗봇의 전체 대화(있을 때), [문서 검토 결과]는 사용자가 올린 "
    "문서(광고문구·동의서·약관 등)에서 발견된 위험 세그먼트·위험사유·위험도(있을 때), "
    "[근거]는 그와 관련해 검색된 법령·판례·해석례·가이드라인(번호 매김)입니다.\n"
    "대화와 문서 검토에서 드러난 상황 '전체를 종합'해, 사용자가 '법적으로 대응·준비하기 위해' "
    "추가로 확인·검토·조치해야 할 항목을 하나의 통합 능동형 체크리스트로 만드세요.\n"
    "규칙:\n"
    "1. 각 항목은 사용자가 실제로 수행/확인할 행동이어야 합니다"
    "(예: '환자 동의서에 민감정보 별도 동의 문구가 있는지 확인', "
    "'광고문구의 절대적 안전성 단정 표현을 수정').\n"
    "2. 판단과 reason 은 반드시 [근거]에 있는 내용에만 기반하세요. 근거 없는 추측 금지.\n"
    "3. 각 항목: id(짧은 영문 슬러그), title(확인/대응할 것), reason(왜 필요한지+근거), "
    "status(기본 todo), citations(사용한 [근거] 번호 정수배열).\n"
    "4. [이전체크리스트]가 주어지면 대조해 change(kept/added/updated/removed)를 표시하고 "
    "이전 id 를 유지하세요. 사용자가 ok/na 로 둔 항목은 그대로 유지(todo 로 되돌리지 마세요).\n"
    "5. 일반론·중복은 빼고 이 대화·문서에 특화된 항목만. 최대 8개.\n"
    '6. 반드시 JSON: {"checklist":[{"id":"sensitive-consent","title":"...","reason":"...",'
    '"status":"todo","change":"added","citations":[1]}]}'
)

CHECKLIST_SYSTEM_EN = (
    "You assist a Korean healthcare business with legal compliance.\n"
    "[Conversation] is the full chat between the user and a medical-law bot (when present); "
    "[Document Review] lists risky segments, risk reasons, and risk levels found in documents the "
    "user uploaded (ads/consent forms/terms, when present); [Sources] are the related "
    "statutes/precedents/interpretations/guidelines (numbered).\n"
    "Synthesizing the WHOLE situation from both the conversation and the document review, build a "
    "single unified actionable checklist of things the user should additionally verify/prepare to "
    "respond legally.\n"
    "Rules:\n"
    "1. Each item is a concrete action/check the user performs (e.g. 'Verify the consent form has a "
    "separate sensitive-data consent clause', 'Fix the ad copy's absolute-safety claim').\n"
    "2. Base every judgment and reason ONLY on [Sources]. No speculation.\n"
    "3. Each item: id (short english slug), title (what to check/do), reason (why + grounds), "
    "status (default todo), citations ([source] number int array).\n"
    "4. If [PreviousChecklist] is given, reconcile and set change (kept/added/updated/removed), reuse "
    "previous ids, and keep user-set ok/na items as-is (do not reset to todo).\n"
    "5. No generic/duplicate items — only items specific to this conversation/document. Max 8.\n"
    '6. Respond ONLY as JSON: {"checklist":[{"id":"sensitive-consent","title":"...","reason":"...",'
    '"status":"todo","change":"added","citations":[1]}]}'
)


def _extract_findings(reviews) -> list[dict]:
    """reviews(느슨한 dict 목록)에서 위험 finding 을 방어적으로 평탄화. 누락 필드 무시."""
    out: list[dict] = []
    if not reviews:
        return out
    for rv in reviews:
        if not isinstance(rv, dict):
            continue
        for f in rv.get("findings") or []:
            if not isinstance(f, dict):
                continue
            seg = str(f.get("segment_text") or "").strip()
            issue = str(f.get("issue") or "").strip()
            if not seg and not issue:
                continue
            out.append({
                "segment_text": seg,
                "issue": issue,
                "risk_level": str(f.get("risk_level") or "").strip(),
                "suggestion": str(f.get("suggestion") or "").strip(),
            })
    return out


def _findings_block(findings: list[dict], lang: str) -> str:
    """LLM 프롬프트용 [문서 검토 결과] 블록. findings 없으면 빈 문자열."""
    if not findings:
        return ""
    lines = []
    for f in findings:
        lvl = f"[{f['risk_level']}] " if f["risk_level"] else ""
        seg = f["segment_text"]
        issue = f["issue"]
        if lang == "en":
            lines.append(f"- {lvl}\"{seg}\" → {issue}" if seg else f"- {lvl}{issue}")
        else:
            lines.append(f"- {lvl}\"{seg}\" → {issue}" if seg else f"- {lvl}{issue}")
    body = "\n".join(lines)
    label = "[Document Review]" if lang == "en" else "[문서 검토 결과]"
    return f"\n\n{label}\n{body}"


def _derive_queries(convo: str, max_n: int) -> list[str]:
    """대화 전체에서 법적 쟁점을 한국어 검색질의로 추출(검색 코퍼스가 한국어). 실패 시 []."""
    try:
        data = llm.chat_json([
            {"role": "system", "content":
                "다음은 사용자와 의료법 챗봇의 대화 전체다. 사용자가 처한 상황에서 법적으로 "
                f"점검·대응해야 할 핵심 쟁점을 한국어 검색 질의 최대 {max_n}개로 뽑아라. "
                "의료법·개인정보보호법·생명윤리법·정보통신망법·의료광고 관점에서 서로 다른 쟁점으로 "
                '나누고, 검색용 명사구로 작성하라. 반드시 JSON: {"queries":["...","..."]}'},
            {"role": "user", "content": convo},
        ])
    except llm.LLMUnavailable:
        return []
    qs = [q.strip() for q in data.get("queries", []) if isinstance(q, str) and q.strip()]
    return qs[:max_n]


def _gather_for_queries(queries: list[str], top_k: int, as_of, lang: str):
    """쟁점 질의들로 검색 → (전역번호 ChatSource 목록, n→source 맵, method). 출처 dedup."""
    by_key: dict[tuple[str, int], ChatSource] = {}
    method = "fts"
    for q in queries:
        hits, m = hybrid_search(q, None, top_k=top_k, as_of=as_of)
        if m == "hybrid":
            method = "hybrid"
        for h in hits:
            key = (h.source_type, h.source_id)
            if key not in by_key:
                s = ChatSource(
                    n=len(by_key) + 1, label=h.label, source_type=h.source_type,
                    source_id=h.source_id, snippet=h.snippet,
                    source_url=h.source_url, trust_grade=h.trust_grade,
                )
                if lang == "en" and h.source_type == "statute":
                    en = english_article(h.source_id)
                    if en:
                        s.label_en = f"{en['law_name_en']} Article {en['article_no']}"
                        s.snippet_en = en["body_en"]
                        s.is_official_en = True
                by_key[key] = s
    sources = list(by_key.values())
    return sources, {s.n: s for s in sources}, method


@router.post("/chat/checklist", response_model=ChecklistResponse, dependencies=[Depends(require_api_key)])
def chat_checklist(req: ChecklistRequest):
    findings = _extract_findings(req.reviews)
    if not req.history and not findings:
        raise HTTPException(400, "대화나 문서 검토 결과 중 하나는 필요합니다.")

    user_text = " ".join(t.content for t in req.history if t.role == "user").strip()
    # 언어 감지 — 대화가 있으면 대화, 없으면 문서 위험요약 기준
    lang_basis = user_text or " ".join(f["issue"] or f["segment_text"] for f in findings).strip()
    lang = req.lang if req.lang in ("ko", "en") else detect_lang(lang_basis)
    convo = "\n".join(f"{t.role}: {t.content}" for t in req.history)

    # 문서 위험요약(쟁점 추출 입력용 + LLM 프롬프트용)
    risk_summary = "\n".join(
        f"- {f['segment_text']} → {f['issue']}" if f["segment_text"] else f"- {f['issue']}"
        for f in findings)

    # 1) 대화 + 문서 위험 → 법적 쟁점 질의 추출 (실패 시 발화/위험요약을 단일 질의로 폴백)
    derive_input = convo
    if risk_summary:
        derive_input = (derive_input + "\n\n[문서 위험요약]\n" + risk_summary).strip()
    queries = _derive_queries(derive_input, req.max_topics)
    if not queries:
        fallback = (user_text or risk_summary).strip()
        queries = [fallback[:300]] if fallback else []
    if not queries:
        raise HTTPException(400, "대화·문서에서 검색할 쟁점을 찾지 못했습니다.")

    # 2) 쟁점별 RAG 근거 검색
    sources, by_n, method = _gather_for_queries(queries, req.top_k, req.as_of, lang)
    if not sources:
        return ChecklistResponse(
            checklist=[], sources=[], search_queries=queries,
            citation_check=_citation_check("", req.as_of),
            method=method, lang=lang, as_of=req.as_of)

    # 이전 체크리스트(재생성) — 사용자 status/note 보존
    prev_block = ""
    prev_notes: dict[str, str] = {}
    if req.prev_checklist:
        slim = []
        for p in req.prev_checklist:
            if isinstance(p, dict) and p.get("id"):
                slim.append({"id": p.get("id"), "title": p.get("title"),
                             "status": p.get("status"), "note": p.get("note", "")})
                if p.get("note"):
                    prev_notes[str(p["id"])] = p["note"]
        if slim:
            label = "[PreviousChecklist]" if lang == "en" else "[이전체크리스트]"
            prev_block = f"\n\n{label}\n{json.dumps(slim, ensure_ascii=False)}"

    # 3) LLM이 대화+문서 근거 기반 통합 체크리스트 생성
    doc_block = _findings_block(findings, lang)
    if lang == "en":
        ev = "\n\n".join(
            f"[{s.n}] {s.label_en} (official English)\n{s.snippet_en}" if s.is_official_en
            else f"[{s.n}] {s.label} (Korean source)\n{s.snippet}" for s in sources)
        convo_block = f"[Conversation]\n{convo}\n\n" if convo else ""
        messages = [{"role": "system", "content": CHECKLIST_SYSTEM_EN},
                    {"role": "user", "content": f"{convo_block}[Sources]\n{ev}{doc_block}{prev_block}".lstrip()}]
    else:
        ev = "\n\n".join(f"[{s.n}] {s.label}\n{s.snippet}" for s in sources)
        convo_block = f"[대화]\n{convo}\n\n" if convo else ""
        messages = [{"role": "system", "content": CHECKLIST_SYSTEM},
                    {"role": "user", "content": f"{convo_block}[근거]\n{ev}{doc_block}{prev_block}".lstrip()}]
    try:
        data = llm.chat_json(messages)
    except llm.LLMUnavailable as e:
        raise HTTPException(503, str(e)) from e

    checklist: list[ChecklistItem] = []
    summary = ChecklistSummary()
    for c in data.get("checklist", []):
        if not isinstance(c, dict) or not c.get("title"):
            continue
        cid = str(c.get("id") or f"item-{len(checklist) + 1}")
        status = c.get("status") if c.get("status") in ("todo", "ok", "risk", "na") else "todo"
        checklist.append(ChecklistItem(
            id=cid, title=c.get("title", ""), reason=c.get("reason", ""), status=status,
            change=c.get("change") if c.get("change") in ("added", "kept", "updated", "removed") else "added",
            segment_index=None,
            citations=[by_n[n] for n in c.get("citations", []) if n in by_n],
            note=c.get("note") or prev_notes.get(cid, ""),
        ))
        setattr(summary, status, getattr(summary, status) + 1)
    summary.total = len(checklist)

    audit = "\n".join(f"{c.title} {c.reason}" for c in checklist)
    return ChecklistResponse(
        checklist=checklist, checklist_summary=summary,
        sources=sources, search_queries=queries,
        citation_check=_citation_check(audit, req.as_of),
        method=method, lang=lang, as_of=req.as_of)
