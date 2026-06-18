"""기획서 핵심기능 ② — 능동형 PDF 에디터 (문서 위험 검토).

흐름: PDF/텍스트 → 세그먼트 분할 → 세그먼트별 hybrid_search(근거)
     → gpt-5.5 1회 structured 분석(위험사유·대안문구·근거) → Citation Firewall
POST /documents/review : multipart(file=PDF) 또는 JSON({text}) 둘 다 허용
"""
import base64
import io
import json
import logging
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app import llm
from app.auth import require_api_key
from app.citations import extract_and_verify, summarize
from app.english import detect_lang, english_article
from app.rag import hybrid_search
from app.schemas import (
    ChatSource,
    ChecklistItem,
    ChecklistSummary,
    ReviewFinding,
    ReviewResponse,
    VerifyResponse,
)

router = APIRouter(prefix="/documents", tags=["능동형 PDF 에디터"])
log = logging.getLogger("uvicorn.error")

MAX_SEGMENTS = 40          # 토큰·지연 방어
MIN_SEG_LEN = 6            # 너무 짧은 조각(머리표·페이지번호)은 검토 제외
OCR_MIN_CHARS = 20         # 텍스트 레이어가 이보다 얇으면 OCR fallback
OCR_MAX_PAGES = 5          # 비전 OCR 비용 방어(앞쪽 N페이지만)
OCR_SCALE = 2.0            # 렌더 배율(≈144DPI)
_SENT_SPLIT = re.compile(r"(?<=[.!?。」』])\s+|\n+")

SYSTEM_PROMPT = (
    "당신은 한국 의료·헬스케어 사업자의 문서(광고문구·환자 동의서·약관·홍보물)를 "
    "의료법·개인정보보호법·생명윤리법·정보통신망법 및 관련 판례·해석례·가이드라인에 비추어 "
    "위반 소지를 점검하는 컴플라이언스 검토자입니다.\n"
    "[세그먼트]는 번호가 매겨진 문서 조각이며, 각 세그먼트 아래에 그 세그먼트에 대해 "
    "미리 검색해 둔 [근거](법령·판례·가이드라인)가 함께 붙어 있습니다.\n"
    "규칙:\n"
    "1. 위반·과장·오해소지가 있는 세그먼트만 골라 보고하세요(문제 없으면 findings 에서 제외).\n"
    "2. 판단은 반드시 그 세그먼트에 붙은 [근거]에 있는 내용에만 근거하세요. 근거 없는 추측 금지.\n"
    "3. 근거 연결은 시스템이 자동으로 처리하므로, 당신은 근거 번호나 citations 를 출력하지 마세요. "
    "issue/suggestion 본문에 근거 내용을 자연어로 녹여 설명하면 됩니다.\n"
    "4. issue 는 위험 사유 설명. suggestion 은 그 세그먼트를 '그대로 대체할' 실제 수정 문구만 "
    "한국어로 쓰세요(‘~하세요’ 같은 지시·설명·따옴표 없이 광고/문서에 바로 넣을 문장 자체).\n"
    "5. risk_level 은 high/medium/low 중 하나.\n"
    "6. 또한 'checklist'(능동형 확인목록)를 만드세요 — 사람이 이 문서에서 추가로 확인해야 할 항목.\n"
    "   각 항목: id(짧은 영문 슬러그), title(확인할 것), reason(왜), status(todo|ok|risk|na), "
    "segment_index(관련 세그먼트, 없으면 null). 근거 연결은 시스템이 처리하니 citations 는 출력하지 마세요.\n"
    "   [이전체크리스트]가 주어지면 대조해 change 표시: 유지=kept, 새로추가=added, 내용바뀜=updated, "
    "더이상 불필요=removed. 유지·갱신 항목은 이전 id 를 그대로 쓰세요. 이전이 없으면 모두 added.\n"
    "   이전 항목의 status 는 사용자가 직접 설정한 값일 수 있습니다 — ok/na 로 표시된 항목은 사용자가 "
    "확인·해소한 것이니 문서가 명백히 위반하지 않는 한 그 status 를 유지하고 todo 로 되돌리지 마세요.\n"
    '7. 반드시 다음 JSON 형식으로만 응답: {"findings":[{"segment_index":0,"risk_level":"high",'
    '"issue":"...","suggestion":"..."}],"checklist":[{"id":"first-claim",'
    '"title":"...","reason":"...","status":"todo","change":"added","segment_index":0}]}'
)

SYSTEM_PROMPT_EN = (
    "You review a Korean healthcare business document (ad copy, patient consent form, terms) for "
    "compliance risk under Korean law (Medical Service Act, Personal Information Protection Act, "
    "Bioethics and Safety Act, Network Act) and related precedents/interpretations/guidelines.\n"
    "[Segments] are numbered document fragments; under each segment are the [Sources] "
    "(statutes/precedents/guidelines) pre-retrieved for that specific segment.\n"
    "Rules:\n"
    "1. Report only segments that are violating, exaggerated, or misleading (omit clean ones).\n"
    "2. Base judgments ONLY on the [Sources] attached to that segment. No speculation.\n"
    "3. Source linking is handled automatically by the system — do NOT output source numbers or a "
    "citations field. Weave the source content into your issue/suggestion prose in natural language.\n"
    "4. 'issue' explains the risk. 'suggestion' is the actual replacement text to drop into the "
    "document (the sentence itself, in the document's language — no instructions or quotes).\n"
    "   Sources marked '(official English)' are official statute translations.\n"
    "5. risk_level is one of high/medium/low.\n"
    "6. Also build a 'checklist' — items a human should additionally verify for this document.\n"
    "   Each item: id (short english slug), title (what to check), reason (why), "
    "status (todo|ok|risk|na), segment_index (related segment or null). Do NOT output a citations "
    "field — source linking is handled by the system.\n"
    "   If [PreviousChecklist] is given, reconcile and set change: kept, added, updated, or removed "
    "(no longer needed). Reuse the previous id for kept/updated items. If none given, all are added.\n"
    "   A previous item's status may have been set by the user — keep ok/na items as-is (the user "
    "resolved them) unless the document clearly still violates; do not reset them to todo.\n"
    '7. Respond ONLY in this JSON format: {"findings":[{"segment_index":0,"risk_level":"high",'
    '"issue":"...","suggestion":"..."}],"checklist":[{"id":"first-claim",'
    '"title":"...","reason":"...","status":"todo","change":"added","segment_index":0}]}'
)


def _ocr_pdf(data: bytes) -> str:
    """스캔본/이미지 PDF용 비전 OCR fallback.

    페이지를 PNG로 렌더 → gpt-5.5 비전으로 텍스트 추출. 앞 OCR_MAX_PAGES 만.
    렌더·LLM 실패 시 ""(graceful degradation — 기존 흐름 유지).
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        log.warning("OCR 생략: pypdfium2 미설치")
        return ""

    out: list[str] = []
    try:
        pdf = pdfium.PdfDocument(data)
        for i in range(min(len(pdf), OCR_MAX_PAGES)):
            bitmap = pdf[i].render(scale=OCR_SCALE)
            buf = io.BytesIO()
            bitmap.to_pil().save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            try:
                out.append(llm.ocr_image(b64))
            except llm.LLMUnavailable as e:
                log.warning("OCR 생략(LLM 사용불가): %s", e)
                return ""
    except Exception as e:  # noqa: BLE001
        log.warning("OCR 렌더 실패: %s", e)
        return "\n".join(out)
    return "\n".join(out)


def _extract_pdf(data: bytes) -> tuple[str, str]:
    """(본문, 추출방식) 반환. 추출방식 = 'text' | 'ocr'."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"PDF 파싱 실패: {e}") from e
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    # 텍스트 레이어가 비거나 너무 얇으면(스캔본·이미지 PDF) → 비전 OCR
    if len(text.strip()) < OCR_MIN_CHARS:
        ocr = _ocr_pdf(data)
        if len(ocr.strip()) > len(text.strip()):
            return ocr, "ocr"
    return text, "text"


def _segment(text: str) -> list[str]:
    segs = [s.strip() for s in _SENT_SPLIT.split(text) if s and s.strip()]
    segs = [s for s in segs if len(s) >= MIN_SEG_LEN]
    return segs[:MAX_SEGMENTS]


def _gather_evidence(segments: list[str], top_k: int, as_of, lang: str = "ko"):
    """세그먼트별 검색 → (전역 ChatSource 풀, seg_idx→[ChatSource] 매핑, method).

    핵심: **세그먼트별 근거 매핑을 코드가 보유**한다. 어느 근거가 어느 세그먼트(=어느
    finding)에 붙는지는 LLM이 아니라 이 검색 결과가 결정한다. 전역 풀(stable [n])은
    프롬프트 표시·dedup 용으로만 쓰고, 동일 출처는 모든 세그먼트에서 같은 ChatSource 객체를
    공유해 번호가 일관되게 유지된다.

    lang=='en' 이면 검색용으로 세그먼트를 한국어 번역, 법령엔 공식 영문 부착.
    """
    by_key: dict[tuple[str, int], ChatSource] = {}
    per_segment: list[list[ChatSource]] = [[] for _ in segments]
    method = "fts"
    for i, seg in enumerate(segments):
        search_seg = llm.translate(seg, "ko") if lang == "en" else seg
        hits, m = hybrid_search(search_seg, None, top_k=top_k, as_of=as_of)
        if m == "hybrid":
            method = "hybrid"
        seen_here: set[tuple[str, int]] = set()
        for h in hits:
            key = (h.source_type, h.source_id)
            s = by_key.get(key)
            if s is None:
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
            if key not in seen_here:  # 세그먼트 내 dedup, 검색 순위 유지
                seen_here.add(key)
                per_segment[i].append(s)
    sources = list(by_key.values())
    return sources, per_segment, method


def _citation_check(text: str, as_of) -> VerifyResponse:
    results = extract_and_verify(text, as_of)
    return VerifyResponse(output=results, summary=summarize(results), as_of=as_of)


def _review(text: str, as_of, top_k: int, extracted_by: str = "text",
            lang: str = "auto", prev_checklist: list | None = None) -> ReviewResponse:
    segments = _segment(text)
    if not segments:
        raise HTTPException(400, "문서에서 검토할 텍스트를 추출하지 못했습니다(이미지 OCR도 비었음).")
    if lang not in ("ko", "en"):
        lang = detect_lang(text)

    sources, per_segment, method = _gather_evidence(segments, top_k, as_of, lang)
    if not sources:
        return ReviewResponse(original_text=text, revised_text=text,
                              segments=segments, findings=[], checklist=[], extracted_by=extracted_by,
                              citation_check=_citation_check("", as_of),
                              method=method, lang=lang, as_of=as_of)

    # 이전 체크리스트(있으면) — LLM이 추가/삭제/유지 재조정. 사용자 status/note 보존.
    prev_block = ""
    prev_notes: dict[str, str] = {}
    if prev_checklist:
        slim = []
        for p in prev_checklist:
            if not isinstance(p, dict) or not p.get("id"):
                continue
            slim.append({"id": p.get("id"), "title": p.get("title"),
                         "status": p.get("status"), "note": p.get("note", "")})
            if p.get("note"):
                prev_notes[str(p["id"])] = p["note"]
        label = "[PreviousChecklist]" if lang == "en" else "[이전체크리스트]"
        prev_block = f"\n\n{label}\n{json.dumps(slim, ensure_ascii=False)}"

    # 세그먼트별 근거를 그 세그먼트 바로 아래 묶어 1회 호출 — 어느 근거가 어느 세그먼트에
    # 붙는지는 코드가 정한 per_segment 매핑이 결정한다(LLM은 번호를 고르지 않음).
    if lang == "en":
        def _ev_line(s: ChatSource) -> str:
            if s.is_official_en:
                return f"  - {s.label_en} (official English): {s.snippet_en}"
            return f"  - {s.label} (Korean source): {s.snippet}"

        blocks = []
        for i, seg in enumerate(segments):
            ev = "\n".join(_ev_line(s) for s in per_segment[i]) or "  - (no source found)"
            blocks.append(f"[{i}] {seg}\n  Sources for this segment:\n{ev}")
        body_block = "\n\n".join(blocks)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_EN},
            {"role": "user", "content": f"[Segments with their Sources]\n{body_block}{prev_block}"},
        ]
    else:
        blocks = []
        for i, seg in enumerate(segments):
            ev = "\n".join(f"  - {s.label}: {s.snippet}" for s in per_segment[i]) or "  - (근거 없음)"
            blocks.append(f"[{i}] {seg}\n  이 세그먼트의 근거:\n{ev}")
        body_block = "\n\n".join(blocks)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"[세그먼트와 근거]\n{body_block}{prev_block}"},
        ]
    try:
        data = llm.chat_json(messages)
    except llm.LLMUnavailable as e:
        raise HTTPException(503, str(e)) from e

    findings: list[ReviewFinding] = []
    for f in data.get("findings", []):
        try:
            idx = int(f["segment_index"])
        except (KeyError, TypeError, ValueError):
            continue
        if not 0 <= idx < len(segments):
            continue
        # 근거 연결은 코드가 담당: 이 세그먼트에 대해 검색해 둔 근거를 그대로 붙인다.
        # (LLM이 고른 번호가 아니라 per_segment 검색 결과 — 오연결·환각 차단)
        findings.append(ReviewFinding(
            segment_index=idx,
            segment_text=segments[idx],
            risk_level=f.get("risk_level", "medium"),
            issue=f.get("issue", ""),
            suggestion=f.get("suggestion", ""),
            citations=list(per_segment[idx]),
        ))

    # 능동형 체크리스트 파싱 (사용자 note 보존 + 상태 요약)
    checklist: list[ChecklistItem] = []
    summary = ChecklistSummary()
    for c in data.get("checklist", []):
        if not isinstance(c, dict) or not c.get("title"):
            continue
        si = c.get("segment_index")
        si = si if isinstance(si, int) and 0 <= si < len(segments) else None
        cid = str(c.get("id") or f"item-{len(checklist) + 1}")
        status = c.get("status") if c.get("status") in ("todo", "ok", "risk", "na") else "todo"
        checklist.append(ChecklistItem(
            id=cid,
            title=c.get("title", ""),
            reason=c.get("reason", ""),
            status=status,
            change=c.get("change") if c.get("change") in ("added", "kept", "updated", "removed") else "added",
            segment_index=si,
            # 근거 연결은 코드가 담당: 연관 세그먼트가 있으면 그 세그먼트 근거를 붙인다.
            citations=list(per_segment[si]) if si is not None else [],
            note=c.get("note") or prev_notes.get(cid, ""),  # 사용자 메모 보존
        ))
        setattr(summary, status, getattr(summary, status) + 1)
    summary.total = len(checklist)

    # before→after: 원문에서 위험 세그먼트를 대안 문구로 치환한 수정본
    revised = text
    for f in findings:
        if f.suggestion:
            revised = revised.replace(f.segment_text, f.suggestion, 1)

    audit = "\n".join(f"{f.issue} {f.suggestion}" for f in findings)
    return ReviewResponse(original_text=text, revised_text=revised,
                          segments=segments, findings=findings,
                          checklist=checklist, checklist_summary=summary,
                          extracted_by=extracted_by,
                          citation_check=_citation_check(audit, as_of),
                          method=method, lang=lang, as_of=as_of)


@router.post("/review", response_model=ReviewResponse, dependencies=[Depends(require_api_key)])
async def review(
    file: UploadFile | None = File(default=None, description="검토할 PDF 파일"),
    text: str | None = Form(default=None, description="PDF 대신 직접 입력하는 본문"),
    as_of: str | None = Form(default=None),
    top_k_per_segment: int = Form(default=4),
    lang: str = Form(default="auto", description="응답 언어 auto|ko|en"),
    prev_checklist: str = Form(default="", description="직전 checklist JSON 배열(능동형 재조정용)"),
):
    """PDF 업로드(file) 또는 텍스트(text) 중 하나로 문서 위험을 검토한다."""
    if file is not None:
        raw = await file.read()
        body, extracted_by = _extract_pdf(raw)
    elif text:
        body, extracted_by = text, "text"
    else:
        raise HTTPException(400, "file(PDF) 또는 text 중 하나를 제공하세요.")
    prev = None
    if prev_checklist.strip():
        try:
            prev = json.loads(prev_checklist)
            if not isinstance(prev, list):
                prev = None
        except json.JSONDecodeError:
            raise HTTPException(400, "prev_checklist 는 JSON 배열이어야 합니다.")
    top_k = max(1, min(8, top_k_per_segment))
    return _review(body, as_of, top_k, extracted_by, lang, prev)
