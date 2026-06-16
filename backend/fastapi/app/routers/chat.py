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
from app.citations import extract_and_verify
from app.english import detect_lang, english_article
from app.rag import hybrid_search
from app.schemas import (
    ChatRequest,
    ChatResponse,
    ChatSource,
    VerifyResponse,
    VerifySummary,
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
    verified = sum(1 for r in results if r.verified)
    return VerifyResponse(
        output=results,
        summary=VerifySummary(total=len(results), verified=verified, failed=len(results) - verified),
        as_of=as_of,
    )


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_api_key)])
def chat(req: ChatRequest):
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
