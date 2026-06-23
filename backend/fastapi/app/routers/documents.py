"""기획서 핵심기능 ② — 능동형 PDF 에디터 (문서 위험 검토).

신 PDF 파이프라인(app/pdf/*)을 엔진으로, 기존 `/documents/review` 응답 계약(ReviewResponse)을 유지.
흐름: PDF → 페이지 라우팅 → pdfplumber(텍스트+표) ∥ OCR(스캔본) → doc_type 자동분류
     → 세그먼트 → 위험판정(RAG) → 블록단위 before/after → Citation Firewall.

엔드포인트:
  POST /documents/review         단발 JSON(전체 한 번에). multipart(file=PDF) 또는 form(text).
  POST /documents/review/stream  SSE 페이지별 점진 노출(앞 페이지부터 화면에 채움). file=PDF.
"""
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.auth import require_api_key
from app.pdf import routing
from app.pdf.pipeline import process_pdf
from app.pdf.review_adapter import review_to_response
from app.schemas import ReviewResponse

router = APIRouter(prefix="/documents", tags=["능동형 PDF 에디터"])

# RiskResult.level("med") → ReviewFinding.risk_level("medium") 매핑.
_LEVEL = {"high": "high", "med": "medium", "medium": "medium", "low": "low"}


@router.post("/review", response_model=ReviewResponse, dependencies=[Depends(require_api_key)])
async def review(
    file: UploadFile | None = File(default=None, description="검토할 PDF 파일(그림·표·스캔본 포함)"),
    text: str | None = Form(default=None, description="PDF 대신 직접 입력하는 본문"),
    as_of: str | None = Form(default=None),
    top_k_per_segment: int = Form(default=4, description="세그먼트별 근거 검색 수(1~8)"),
    lang: str = Form(default="auto", description="응답 언어 auto|ko|en"),
):
    """PDF 업로드(file) 또는 텍스트(text)로 위험검토 → findings + before/after(전체 한 번에)."""
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


# ───────────── 페이지별 점진 스트리밍 (SSE) ─────────────
def _sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def _page_findings(segments) -> list[dict]:
    """그 페이지 세그먼트 중 위험한 것 → ReviewFinding 형태 dict 목록."""
    out = []
    for i, s in enumerate(segments):
        r = s.risk
        if r and r.level in ("low", "med", "high"):
            out.append({
                "segment_index": i,
                "segment_text": s.text,
                "risk_level": _LEVEL.get(r.level, "medium"),
                "issue": r.reason,
                "suggestion": r.after,
                "law": list(r.law),
            })
    return out


def _stream_gen(pdf_bytes: bytes, as_of, top_k: int, pages: "list[int] | None" = None):
    """SSE 이벤트 제너레이터: pages → page(별 before/after) → done.

    페이지 단위로 추출→세그먼트→위험판정→치환을 돌려 완료되는 대로 흘려보낸다.
    """
    routes = routing.route_pages(pdf_bytes)
    if pages is not None:
        routes = [r for r in routes if r.page in pages]
    total = len(routes)
    yield _sse({"type": "pages", "page_count": total,
                "routes": [{"page": r.page, "route": r.route} for r in routes]})
    risky_total = change_total = 0
    for n, r in enumerate(routes, 1):
        try:
            res = process_pdf(pdf_bytes, as_of=as_of, top_k=top_k, pages=[r.page])
            segs = res["segments"]
            rev = res["revisions"]
            findings = _page_findings(segs)
            before = "\n".join(b["text"] for b in rev["blocks_before"])
            after = "\n".join(b["text"] for b in rev["blocks_after"])
            risky_total += len(findings)
            change_total += len(rev["changes"])
            yield _sse({
                "type": "page", "page": r.page, "route": r.route,
                "progress": f"{n}/{total}", "doc_type": res["document"].doc_type,
                "original_text": before, "revised_text": after, "findings": findings,
            })
        except Exception as e:  # noqa: BLE001 — 한 페이지 실패가 전체 스트림을 끊지 않게
            yield _sse({"type": "error", "page": r.page, "message": str(e)})
    yield _sse({"type": "done",
                "status": "reviewed",
                "summary": {"page_count": total, "risky": risky_total, "changes": change_total}})


def _parse_pages(pages: str) -> "list[int] | None":
    if not pages.strip():
        return None
    try:
        return [int(p) for p in pages.split(",") if p.strip()]
    except ValueError:
        return None


@router.post("/review/stream", dependencies=[Depends(require_api_key)])
async def review_stream(
    file: UploadFile = File(..., description="검토할 PDF 파일"),
    as_of: str | None = Form(default=None),
    top_k_per_segment: int = Form(default=4),
    pages: str = Form(default="", description="특정 페이지만(쉼표구분, 1-based). 비우면 전체"),
):
    """페이지별 점진 스트리밍(SSE) — pages → page(별 before/after) → done.

    프론트는 `page` 이벤트를 받는 즉시 그 페이지 카드를 before/after로 렌더(앞 페이지부터),
    뒤 페이지는 백엔드가 처리 완료하는 대로 이어서 채운다.
    이벤트(data: JSON):
      {"type":"pages","page_count":N,"routes":[{"page":1,"route":"digital"}...]}
      {"type":"page","page":1,"progress":"1/N","doc_type":"ad","original_text":...,
       "revised_text":...,"findings":[{segment_index,segment_text,risk_level,issue,suggestion,law}]}
      {"type":"done","summary":{"page_count":N,"risky":k,"changes":m}}
    """
    pdf_bytes = await file.read()
    top_k = max(1, min(8, top_k_per_segment))
    return StreamingResponse(
        _stream_gen(pdf_bytes, as_of, top_k, _parse_pages(pages)),
        media_type="text/event-stream")
