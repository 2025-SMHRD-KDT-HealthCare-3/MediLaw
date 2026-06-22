"""기획서 핵심기능 ② — 능동형 PDF 에디터 (문서 위험 검토).

신 PDF 파이프라인(app/pdf/*)을 엔진으로, 기존 `/documents/review` 응답 계약(ReviewResponse)을 유지.
흐름: PDF → 페이지 라우팅 → pdfplumber(텍스트+표) ∥ OCR(스캔본) → doc_type 자동분류
     → 세그먼트 → 위험판정(RAG) → 블록단위 before/after → Citation Firewall.
POST /documents/review : multipart(file=PDF) 또는 form(text) 중 하나.
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.auth import require_api_key
from app.pdf.review_adapter import review_to_response
from app.schemas import ReviewResponse

router = APIRouter(prefix="/documents", tags=["능동형 PDF 에디터"])


@router.post("/review", response_model=ReviewResponse, dependencies=[Depends(require_api_key)])
async def review(
    file: UploadFile | None = File(default=None, description="검토할 PDF 파일(그림·표·스캔본 포함)"),
    text: str | None = Form(default=None, description="PDF 대신 직접 입력하는 본문"),
    as_of: str | None = Form(default=None),
    top_k_per_segment: int = Form(default=4, description="세그먼트별 근거 검색 수(1~8)"),
    lang: str = Form(default="auto", description="응답 언어 auto|ko|en"),
):
    """PDF 업로드(file) 또는 텍스트(text)로 위험검토 → findings + before/after 수정안.

    PDF는 신 파이프라인이 페이지별로 디지털(pdfplumber, 표 보존)/스캔본(OCR)을 자동 분기해
    추출하고, 위험 세그먼트를 블록 단위로 before/after 치환한다.
    """
    pdf_bytes = None
    if file is not None:
        pdf_bytes = await file.read()
    elif not text:
        raise HTTPException(400, "file(PDF) 또는 text 중 하나를 제공하세요.")
    top_k = max(1, min(8, top_k_per_segment))
    try:
        return review_to_response(
            pdf_bytes=pdf_bytes, text=text, as_of=as_of, top_k=top_k, lang=lang)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
