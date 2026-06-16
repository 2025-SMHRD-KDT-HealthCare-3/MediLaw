"""기획서 핵심기능 ② — 능동형 PDF 에디터 (문서 위험 검토).

흐름: PDF/텍스트 → 세그먼트 분할 → 세그먼트별 hybrid_search(근거)
     → gpt-5.5 1회 structured 분석(위험사유·대안문구·근거) → Citation Firewall
POST /documents/review : multipart(file=PDF) 또는 JSON({text}) 둘 다 허용
"""
import base64
import io
import logging
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app import llm
from app.auth import require_api_key
from app.citations import extract_and_verify
from app.english import detect_lang, english_article
from app.rag import hybrid_search
from app.schemas import (
    ChatSource,
    ReviewFinding,
    ReviewResponse,
    VerifyResponse,
    VerifySummary,
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
    "[세그먼트]는 번호가 매겨진 문서 조각, [근거]는 번호가 매겨진 법령·판례·가이드라인입니다.\n"
    "규칙:\n"
    "1. 위반·과장·오해소지가 있는 세그먼트만 골라 보고하세요(문제 없으면 findings 에서 제외).\n"
    "2. 판단은 반드시 [근거]에 있는 내용에만 근거하세요. 근거 없는 추측 금지.\n"
    "3. 각 항목의 citations 에는 사용한 [근거] 번호만 정수 배열로 넣으세요.\n"
    "4. issue 는 위험 사유 설명. suggestion 은 그 세그먼트를 '그대로 대체할' 실제 수정 문구만 "
    "한국어로 쓰세요(‘~하세요’ 같은 지시·설명·따옴표 없이 광고/문서에 바로 넣을 문장 자체).\n"
    "5. risk_level 은 high/medium/low 중 하나.\n"
    '6. 반드시 다음 JSON 형식으로만 응답: '
    '{"findings":[{"segment_index":0,"risk_level":"high","issue":"...","suggestion":"...","citations":[1,2]}]}'
)

SYSTEM_PROMPT_EN = (
    "You review a Korean healthcare business document (ad copy, patient consent form, terms) for "
    "compliance risk under Korean law (Medical Service Act, Personal Information Protection Act, "
    "Bioethics and Safety Act, Network Act) and related precedents/interpretations/guidelines.\n"
    "[Segments] are numbered document fragments; [Sources] are numbered statutes/precedents/guidelines.\n"
    "Rules:\n"
    "1. Report only segments that are violating, exaggerated, or misleading (omit clean ones).\n"
    "2. Base judgments ONLY on [Sources]. No speculation.\n"
    "3. In citations put only the [Source] numbers used, as an integer array.\n"
    "4. 'issue' explains the risk. 'suggestion' is the actual replacement text to drop into the "
    "document (the sentence itself, in the document's language — no instructions or quotes).\n"
    "   Sources marked '(official English)' are official statute translations; cite their names exactly.\n"
    "5. risk_level is one of high/medium/low.\n"
    '6. Respond ONLY in this JSON format: '
    '{"findings":[{"segment_index":0,"risk_level":"high","issue":"...","suggestion":"...","citations":[1,2]}]}'
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
    """세그먼트별 검색 → (전역번호 ChatSource 목록, n→source 맵, method).

    lang=='en' 이면 검색용으로 세그먼트를 한국어 번역, 법령엔 공식 영문 부착.
    """
    by_key: dict[tuple[str, int], ChatSource] = {}
    method = "fts"
    for seg in segments:
        search_seg = llm.translate(seg, "ko") if lang == "en" else seg
        hits, m = hybrid_search(search_seg, None, top_k=top_k, as_of=as_of)
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


def _citation_check(text: str, as_of) -> VerifyResponse:
    results = extract_and_verify(text, as_of)
    verified = sum(1 for r in results if r.verified)
    return VerifyResponse(
        output=results,
        summary=VerifySummary(total=len(results), verified=verified, failed=len(results) - verified),
        as_of=as_of,
    )


def _review(text: str, as_of, top_k: int, extracted_by: str = "text", lang: str = "auto") -> ReviewResponse:
    segments = _segment(text)
    if not segments:
        raise HTTPException(400, "문서에서 검토할 텍스트를 추출하지 못했습니다(이미지 OCR도 비었음).")
    if lang not in ("ko", "en"):
        lang = detect_lang(text)

    sources, by_n, method = _gather_evidence(segments, top_k, as_of, lang)
    if not sources:
        return ReviewResponse(original_text=text, revised_text=text,
                              segments=segments, findings=[], extracted_by=extracted_by,
                              citation_check=_citation_check("", as_of),
                              method=method, lang=lang, as_of=as_of)

    seg_block = "\n".join(f"[{i}] {s}" for i, s in enumerate(segments))
    if lang == "en":
        ev_block = "\n\n".join(
            f"[{s.n}] {s.label_en} (official English)\n{s.snippet_en}" if s.is_official_en
            else f"[{s.n}] {s.label} (Korean source)\n{s.snippet}"
            for s in sources
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_EN},
            {"role": "user", "content": f"[Segments]\n{seg_block}\n\n[Sources]\n{ev_block}"},
        ]
    else:
        ev_block = "\n\n".join(f"[{s.n}] {s.label}\n{s.snippet}" for s in sources)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"[세그먼트]\n{seg_block}\n\n[근거]\n{ev_block}"},
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
        cites = [by_n[n] for n in f.get("citations", []) if n in by_n]
        findings.append(ReviewFinding(
            segment_index=idx,
            segment_text=segments[idx],
            risk_level=f.get("risk_level", "medium"),
            issue=f.get("issue", ""),
            suggestion=f.get("suggestion", ""),
            citations=cites,
        ))

    # before→after: 원문에서 위험 세그먼트를 대안 문구로 치환한 수정본
    revised = text
    for f in findings:
        if f.suggestion:
            revised = revised.replace(f.segment_text, f.suggestion, 1)

    audit = "\n".join(f"{f.issue} {f.suggestion}" for f in findings)
    return ReviewResponse(original_text=text, revised_text=revised,
                          segments=segments, findings=findings, extracted_by=extracted_by,
                          citation_check=_citation_check(audit, as_of),
                          method=method, lang=lang, as_of=as_of)


@router.post("/review", response_model=ReviewResponse, dependencies=[Depends(require_api_key)])
async def review(
    file: UploadFile | None = File(default=None, description="검토할 PDF 파일"),
    text: str | None = Form(default=None, description="PDF 대신 직접 입력하는 본문"),
    as_of: str | None = Form(default=None),
    top_k_per_segment: int = Form(default=4),
    lang: str = Form(default="auto", description="응답 언어 auto|ko|en"),
):
    """PDF 업로드(file) 또는 텍스트(text) 중 하나로 문서 위험을 검토한다."""
    if file is not None:
        raw = await file.read()
        body, extracted_by = _extract_pdf(raw)
    elif text:
        body, extracted_by = text, "text"
    else:
        raise HTTPException(400, "file(PDF) 또는 text 중 하나를 제공하세요.")
    top_k = max(1, min(8, top_k_per_segment))
    return _review(body, as_of, top_k, extracted_by, lang)
