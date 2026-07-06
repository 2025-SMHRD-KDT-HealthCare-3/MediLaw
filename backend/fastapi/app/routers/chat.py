"""기획서 핵심기능 ① — AI 질의응답 챗봇.

흐름: 질문 → hybrid_search(근거) → gpt-5.5 답변생성(근거 강제인용)
     → Citation Firewall로 답변 인용 자동검증 → {answer, sources, citation_check}
POST /chat          : 단발 JSON
POST /chat/stream   : SSE 토큰 스트리밍 (sources → token... → done)
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app import domain_router, llm
from app.auth import require_api_key
from app.citations import clean_law_label, extract_and_verify, summarize
from app.english import detect_lang, english_article
from app.rag import hybrid_search
from app.schemas import (
    AnswerSegment,
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

_CITE_RE = re.compile(r"\[(\d+)\]")


def segment_answer(answer: str, sources: list[ChatSource]) -> list[AnswerSegment]:
    """answer 문자열의 [n]을 sources(n 기준)와 매칭해 text/cite 토큰 배열로 쪼갠다.
    sources에 없는 [n]은 텍스트로 강등(환각/오번호 방어)."""
    by_n = {s.n: s for s in sources}
    segs: list[AnswerSegment] = []
    last = 0
    for m in _CITE_RE.finditer(answer or ""):
        if m.start() > last:
            segs.append(AnswerSegment(type="text", text=answer[last:m.start()]))
        src = by_n.get(int(m.group(1)))
        if src:
            segs.append(AnswerSegment(type="cite", text=m.group(0), n=src.n,
                source_type=src.source_type, source_id=src.source_id, label=src.label))
        else:
            segs.append(AnswerSegment(type="text", text=m.group(0)))
        last = m.end()
    if answer and last < len(answer):
        segs.append(AnswerSegment(type="text", text=answer[last:]))
    return segs

MAX_HISTORY = 10  # 토큰 방어 — 최근 N턴만 LLM에 전달

SYSTEM_PROMPT = (
    "당신은 한국 의료·헬스케어 사업자를 위한 의료법 컴플라이언스 도우미입니다. "
    "의료법·개인정보보호법·생명윤리법·정보통신망법 및 관련 판례·해석례·가이드라인을 근거로 답합니다.\n"
    "규칙:\n"
    "1. 아래 [근거]에 있는 내용만 사용해 한국어로 답하세요.\n"
    "2. 근거에 없으면 추측하지 말고 '제공된 자료로는 확인되지 않습니다'라고 답하세요.\n"
    "3. 답변에 사용한 근거는 문장 끝에 [1], [2]처럼 번호로 인용하세요.\n"
    "4. 법령명과 조문번호는 근거에 적힌 그대로 정확히 쓰세요(없는 조문을 만들지 마세요).\n"
    "5. [근거]에 없는 다른 법령·판례는 이름조차 언급하지 마세요(예: 약사법·형법 등 4개 법 밖의 법). "
    "범위를 벗어나면 지어내지 말고 2번처럼 '제공된 자료로는 확인되지 않습니다'라고 답하세요.\n"
    "6. '※ 본 답변은 법률 자문이 아니라 정보 제공입니다.'는 답변 맨 마지막 줄에, 본문과 빈 줄 하나로 "
    "구분해 한 줄로 덧붙이세요.\n"
    "7. 가독성을 위해 아래 형식으로 작성하세요.\n"
    "   - 먼저 핵심 결론을 1~2문장으로 제시합니다.\n"
    "   - 한 줄(빈 줄)을 띄운 뒤, '**근거**' 라는 굵은 소제목을 쓰고 그 아래에 관련 조문·판례를 "
    "'- '(하이픈+공백)로 시작하는 불릿으로 한 줄에 하나씩 정리합니다. 각 항목은 짧게 요약하고 끝에 "
    "인용번호[1]를 붙입니다.\n"
    "   - 문단과 문단 사이에는 반드시 빈 줄을 넣고, 절대 한 문단으로 길게 이어 쓰지 마세요.\n"
    "   - 굵게 강조는 '**...**' 로만, 목록은 '- ' 로만 표기하고, 그 외 마크다운(제목#, 표, 번호목록)은 "
    "사용하지 마세요."
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
    "5. Do NOT mention any law or precedent that is not in the [Sources] (e.g. the Pharmaceutical "
    "Affairs Act, the Criminal Act, or any statute outside the four covered laws). If it is out of "
    "scope, do not invent it — answer as in rule 2.\n"
    "6. End with: '* This response is informational, not legal advice.' on the very last line, "
    "separated from the body by one blank line.\n"
    "7. Format for readability:\n"
    "   - Start with a 1-2 sentence conclusion.\n"
    "   - Then add a blank line and a bold subheading '**Grounds**', followed by relevant "
    "statutes/precedents as bullet points, one per line starting with '- ', each ending with its "
    "citation number [1].\n"
    "   - Separate paragraphs with a blank line. Never write one long paragraph.\n"
    "   - Use only '**...**' for bold and '- ' for lists. Do not use other markdown "
    "(headings #, tables, numbered lists)."
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


# needs_clarification(Tier 2 모호)일 때 답변 끝에 붙이는 되묻기 한 줄.
_CLARIFY = "\n\n※ 의료기관·환자·건강정보와 관련된 상황이라면 구체적으로 알려주시면 더 정확히 답변드립니다."
_CLARIFY_EN = ("\n\n* If this concerns a medical institution, patients, or health data, "
               "please specify for a more precise answer.")

# 분류 불가(LLM 장애 등)로 답변을 강행하지 않고 '한 번 더 묻는' 단독 응답.
_CLARIFY_ONLY = (
    "질문 의도를 정확히 파악하지 못했습니다. 의료기관·환자·건강정보, 또는 개인정보·의료광고 등 "
    "어떤 상황에 대한 질문인지 조금만 더 구체적으로 알려주시면 정확히 답변드리겠습니다.\n"
    "※ 본 답변은 법률 자문이 아니라 정보 제공입니다."
)
_CLARIFY_ONLY_EN = (
    "I couldn't quite determine the intent of your question. Could you specify the situation "
    "(e.g., a medical institution, patient/health data, privacy, or medical advertising)? "
    "I'll then answer precisely.\n"
    "* This response is informational, not legal advice."
)


def _domain_route(req: ChatRequest) -> dict:
    """3-tier 도메인 라우팅. {tier, needs_clarification, source}."""
    history = [{"role": t.role, "content": t.content} for t in req.history[-MAX_HISTORY:]]
    return domain_router.route(req.question, history)


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


def _offcorpus_note(cc: VerifyResponse, lang: str) -> str:
    """확인된 코퍼스(4개 법) 밖 인용에 대한 비파괴 경고 한 줄(겹2-A).

    LLM이 근거 밖 법령·판례를 흘려 쓰면 Citation Firewall이 exists=False로 잡는다.
    본문은 그대로 두고, 검증 안 된 인용을 끝에 명시해 사용자가 오인하지 않게 한다.
    라벨은 citations.clean_law_label 로 앞 문장조각을 떼어 '법령명 제N조'만 보인다.
    """
    seen: set[str] = set()
    labels: list[str] = []
    for r in cc.output:
        if not r.exists and (r.raw or "").strip():
            label = clean_law_label(r.raw)
            if label and label not in seen:
                seen.add(label)
                labels.append(label)
    if not labels:
        return ""
    joined = ", ".join(labels)
    if lang == "en":
        return ("\n\n⚠️ The following citations are outside the verified corpus "
                "(Medical Service Act, PIPA, Bioethics Act, Network Act) and could not be "
                f"confirmed — treat as reference only: {joined}")
    return ("\n\n⚠️ 다음 인용은 확인된 코퍼스(의료법·개인정보보호법·생명윤리법·정보통신망법) 밖이라 "
            f"검증되지 않았습니다 — 참고용으로만 보세요: {joined}")


def _chat_impl(req: ChatRequest):
    """/chat 의 실제 구현. lang 은 호출 측에서 req.lang 으로 고정해 넘긴다
    (한국어판='ko', 영어판='en'). 내부 _build·detect_lang 가 req.lang 을 그대로
    존중하므로, req.lang 만 고정하면 전체 경로가 해당 언어로 일관되게 동작한다."""
    if not req.question.strip():
        raise HTTPException(400, "질문을 입력해주세요.")
    lang = req.lang if req.lang in ("ko", "en") else detect_lang(req.question)
    decision = _domain_route(req)
    if not domain_router.is_in_scope(decision):  # Tier 3 → 거절
        refusal = _OUT_OF_DOMAIN_EN if lang == "en" else _OUT_OF_DOMAIN
        return ChatResponse(answer=refusal, answer_segments=segment_answer(refusal, []),
                            sources=[], method="none", lang=lang,
                            search_query=req.question,
                            citation_check=_citation_check("", req.as_of), as_of=req.as_of)
    if decision.get("clarify_only"):  # 분류 불가 → 답변 강행 대신 한 번 더 묻기
        msg = _CLARIFY_ONLY_EN if lang == "en" else _CLARIFY_ONLY
        return ChatResponse(answer=msg, answer_segments=segment_answer(msg, []),
                            sources=[], method="none", lang=lang,
                            search_query=req.question,
                            citation_check=_citation_check("", req.as_of), as_of=req.as_of)
    messages, sources, method, lang, search_q = _build(req)
    no_ev = _NO_EVIDENCE_EN if lang == "en" else _NO_EVIDENCE
    if messages is None:
        return ChatResponse(answer=no_ev, answer_segments=segment_answer(no_ev, []),
                            sources=[], method=method, lang=lang,
                            search_query=search_q,
                            citation_check=_citation_check("", req.as_of), as_of=req.as_of)
    try:
        answer = llm.chat(messages)
    except llm.LLMUnavailable as e:
        raise HTTPException(503, str(e))
    if decision["needs_clarification"]:  # Tier 2 모호 → 답변 끝에 되묻기 한 줄
        answer += _CLARIFY_EN if lang == "en" else _CLARIFY
    cc = _citation_check(answer, req.as_of)  # 경고 덧붙이기 전 원문 기준으로 검증
    answer += _offcorpus_note(cc, lang)      # 겹2-A: 코퍼스 밖 인용 비파괴 경고
    return ChatResponse(
        answer=answer, answer_segments=segment_answer(answer, sources),
        sources=sources, method=method, lang=lang, search_query=search_q,
        citation_check=cc, as_of=req.as_of,
    )


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_api_key)])
def chat(req: ChatRequest):
    # 한국어 전용 — req.lang 의 영어 분기를 막고 'ko'로 고정.
    # (구 동작: lang = req.lang if req.lang in ("ko","en") else detect_lang(...) — 영어판은 /chat/en 사용)
    return _chat_impl(req.model_copy(update={"lang": "ko"}))


@router.post("/chat/en", response_model=ChatResponse, dependencies=[Depends(require_api_key)])
def chat_en(req: ChatRequest):
    # 영어 전용 — lang="en" 고정(번역 검색·영문 프롬프트·공식 영문조문 포함).
    return _chat_impl(req.model_copy(update={"lang": "en"}))


def _sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def _chat_stream_impl(req: ChatRequest):
    """/chat/stream 의 실제 구현(SSE). lang 은 호출 측에서 req.lang 으로 고정."""
    if not req.question.strip():
        raise HTTPException(400, "질문을 입력해주세요.")
    lang = req.lang if req.lang in ("ko", "en") else detect_lang(req.question)
    decision = _domain_route(req)
    if not domain_router.is_in_scope(decision):  # Tier 3 → 거절
        refusal = _OUT_OF_DOMAIN_EN if lang == "en" else _OUT_OF_DOMAIN

        def gen_refuse():
            yield _sse({"type": "sources", "method": "none", "lang": lang,
                        "search_query": req.question, "sources": []})
            yield _sse({"type": "token", "text": refusal})
            yield _sse({"type": "done", "citation_check": _citation_check("", req.as_of).model_dump(),
                        "answer_segments": [s.model_dump() for s in segment_answer(refusal, [])]})

        return StreamingResponse(gen_refuse(), media_type="text/event-stream")

    if decision.get("clarify_only"):  # 분류 불가 → 답변 강행 대신 한 번 더 묻기
        msg = _CLARIFY_ONLY_EN if lang == "en" else _CLARIFY_ONLY

        def gen_clarify():
            yield _sse({"type": "sources", "method": "none", "lang": lang,
                        "search_query": req.question, "sources": []})
            yield _sse({"type": "token", "text": msg})
            yield _sse({"type": "done", "citation_check": _citation_check("", req.as_of).model_dump(),
                        "answer_segments": [s.model_dump() for s in segment_answer(msg, [])]})

        return StreamingResponse(gen_clarify(), media_type="text/event-stream")

    def gen():
        # _build(검색·질의재작성·DB)도 제너레이터 안에서 감싸, 여기서 터져도 스트림이
        # error+done 없이 끊기지 않게 한다(프론트 로딩 hang 방지).
        try:
            messages, sources, method, lang, search_q = _build(req)
        except Exception as e:  # noqa: BLE001
            yield _sse({"type": "error", "message": f"근거 준비 중 오류: {e}"})
            yield _sse({"type": "done", "citation_check": _citation_check("", req.as_of).model_dump(),
                        "answer_segments": []})
            return
        yield _sse({"type": "sources", "method": method, "lang": lang, "search_query": search_q,
                    "sources": [s.model_dump() for s in sources]})
        if messages is None:
            no_ev = _NO_EVIDENCE_EN if lang == "en" else _NO_EVIDENCE
            yield _sse({"type": "token", "text": no_ev})
            yield _sse({"type": "done", "citation_check": _citation_check("", req.as_of).model_dump(),
                        "answer_segments": [s.model_dump() for s in segment_answer(no_ev, [])]})
            return
        parts = []
        try:
            for tok in llm.chat_stream(messages):
                parts.append(tok)
                yield _sse({"type": "token", "text": tok})
        except llm.LLMUnavailable as e:
            yield _sse({"type": "error", "message": str(e)})
            return
        if decision["needs_clarification"]:  # Tier 2 모호 → 되묻기 한 줄 추가 토큰
            clarify = _CLARIFY_EN if lang == "en" else _CLARIFY
            yield _sse({"type": "token", "text": clarify})
            parts.append(clarify)  # done의 answer_segments/citation_check에도 포함
        answer = "".join(parts)
        yield _sse({"type": "done", "citation_check": _citation_check(answer, req.as_of).model_dump(),
                    "answer_segments": [s.model_dump() for s in segment_answer(answer, sources)]})

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/chat/stream", dependencies=[Depends(require_api_key)])
def chat_stream(req: ChatRequest):
    # 한국어 전용 — 'ko'로 고정(영어판은 /chat/en/stream 사용).
    return _chat_stream_impl(req.model_copy(update={"lang": "ko"}))


@router.post("/chat/en/stream", dependencies=[Depends(require_api_key)])
def chat_en_stream(req: ChatRequest):
    # 영어 전용 SSE — lang="en" 고정.
    return _chat_stream_impl(req.model_copy(update={"lang": "en"}))


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
    """쟁점 질의들로 검색 → (전역번호 ChatSource 목록, n→source 맵, method). 출처 dedup.

    쟁점별 검색을 **병렬**로 돌린다(thread-local DB라 스레드 안전). 순차로 하면
    검색 1회가 느린 환경에서 N배로 누적돼 체크리스트가 타임아웃나기 때문.
    결과는 입력 질의 순서대로 병합(ex.map 순서 보존)해 dedup·번호 부여는 결정론 유지.
    """
    def _search(q):
        try:
            return hybrid_search(q, None, top_k=top_k, as_of=as_of)
        except Exception:  # noqa: BLE001 — 한 질의 실패가 전체를 막지 않게
            return [], "fts"

    if len(queries) <= 1:
        results = [_search(q) for q in queries]
    else:
        with ThreadPoolExecutor(max_workers=min(8, len(queries))) as ex:
            results = list(ex.map(_search, queries))  # 입력 순서 보존

    by_key: dict[tuple[str, int], ChatSource] = {}
    method = "fts"
    for hits, m in results:
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


def _chat_checklist_impl(req: ChecklistRequest):
    """/chat/checklist 의 실제 구현. lang 은 호출 측에서 req.lang 으로 고정."""
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


@router.post("/chat/checklist", response_model=ChecklistResponse, dependencies=[Depends(require_api_key)])
def chat_checklist(req: ChecklistRequest):
    # 한국어 전용 — 'ko'로 고정(영어판은 /chat/en/checklist 사용).
    return _chat_checklist_impl(req.model_copy(update={"lang": "ko"}))


@router.post("/chat/en/checklist", response_model=ChecklistResponse, dependencies=[Depends(require_api_key)])
def chat_en_checklist(req: ChecklistRequest):
    # 영어 전용 — lang="en" 고정(공식 영문조문·영문 프롬프트 포함).
    return _chat_checklist_impl(req.model_copy(update={"lang": "en"}))
