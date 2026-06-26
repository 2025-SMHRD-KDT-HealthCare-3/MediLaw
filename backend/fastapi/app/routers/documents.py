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
from app.pdf import geometry, routing
from app.pdf.extract_ocr import OCR_SCALE
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
        if not pdf_bytes:
            raise HTTPException(400, "업로드한 PDF 파일이 비어 있습니다.")
        text = None  # file 우선 — text는 무시(둘 다 줘도 PDF 사용, 묵음 처리 방지)
    elif not (text and text.strip()):
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


def _page_findings(segments, block_by_id=None, page_sizes=None) -> list[dict]:
    """그 페이지 세그먼트 중 위험한 것 → ReviewFinding 형태 dict 목록.

    block_by_id/page_sizes 가 주어지면 각 finding 에 page/bbox(정규화 좌표)를 채운다.
    안 주어지면 finding_geometry 가 (None, None) 반환(graceful).
    """
    block_by_id = block_by_id or {}
    page_sizes = page_sizes or {}
    out = []
    # segment_index 는 enumerate(segments) 의 페이지-로컬 0-based 인덱스.
    # page 이벤트가 같은 페이지의 segments 원문 배열을 함께 내보내므로(self-contained),
    # 프론트는 event.segments[finding.segment_index] 로 원문을 역참조할 수 있다.
    for i, s in enumerate(segments):
        r = s.risk
        if r and r.level in ("low", "med", "high"):
            pg, bbox = geometry.finding_geometry(s, block_by_id, page_sizes, OCR_SCALE)
            out.append({
                "segment_index": i,
                "segment_text": s.text,
                "risk_level": _LEVEL.get(r.level, "medium"),
                "issue": r.reason,
                "suggestion": r.after,
                "law": list(r.law),
                "page": pg,
                "bbox": bbox,
            })
    return out


def _stream_gen(pdf_bytes: bytes, as_of, top_k: int, pages: "list[int] | None" = None):
    """SSE 이벤트 제너레이터: pages → page(별 before/after) → done.

    페이지 단위로 추출→세그먼트→위험판정→치환을 돌려 완료되는 대로 흘려보낸다.
    제너레이터 전체를 try/except 로 감싸 루프 이전(route_pages/첫 yield) 단계에서
    예외가 나도 마지막에 반드시 error(+가능하면 done) 이벤트를 보장한다.
    """
    risky_total = change_total = 0
    done_summary = None  # 정상 완료 시 done 이벤트 payload
    try:
        # PDF 전체 라우팅은 여기서 1회만. 이후 페이지별 호출엔 route_hint 로 재파싱 제거.
        routes = routing.route_pages(pdf_bytes)
        if pages is not None:
            routes = [r for r in routes if r.page in pages]
        total = len(routes)
        # 페이지 크기(포인트)는 PDF 전체에서 1회만 계산해 페이지 루프에서 재사용.
        page_sizes = geometry.page_sizes(pdf_bytes)
        yield _sse({"type": "pages", "page_count": total,
                    "routes": [{"page": r.page, "route": r.route} for r in routes]})
        for n, r in enumerate(routes, 1):
            try:
                # route_hint 로 미리 구한 라우팅을 넘겨 페이지마다 PDF 전체 재파싱 방지.
                res = process_pdf(pdf_bytes, as_of=as_of, top_k=top_k,
                                  pages=[r.page], route_hint=routes)
                segs = res["segments"]
                rev = res["revisions"]
                block_by_id = {b.id: b for b in res["document"].blocks}
                findings = _page_findings(segs, block_by_id, page_sizes)
                before = "\n".join(b["text"] for b in rev["blocks_before"])
                after = "\n".join(b["text"] for b in rev["blocks_after"])
                risky_total += len(findings)
                change_total += len(rev["changes"])
                event = {
                    "type": "page", "page": r.page, "route": r.route,
                    "progress": f"{n}/{total}", "doc_type": res["document"].doc_type,
                    "original_text": before, "revised_text": after, "findings": findings,
                    # 이 페이지의 세그먼트 원문 배열. findings[].segment_index(페이지-로컬)가
                    # 이 배열 인덱스와 일치 → 프론트가 segment_index 로 원문 역참조 가능.
                    "segments": [s.text for s in segs],
                }
                # scan 페이지인데 추출 텍스트가 비면 OCR 실패 — "위험 없음"과 구별되게 경고.
                if r.route == "scan" and not before.strip():
                    event["warning"] = "ocr_failed"
                yield _sse(event)
            except Exception as e:  # noqa: BLE001 — 한 페이지 실패가 전체 스트림을 끊지 않게
                yield _sse({"type": "error", "page": r.page, "message": str(e)})
        done_summary = {"page_count": total, "risky": risky_total, "changes": change_total}
    except Exception as e:  # noqa: BLE001 — 루프 이전 등 어떤 단계 예외도 스트림을 끊지 않게
        yield _sse({"type": "error", "message": str(e)})
    yield _sse({"type": "done", "status": "reviewed",
                "summary": done_summary
                if done_summary is not None
                else {"risky": risky_total, "changes": change_total}})


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
        media_type="text/event-stream",
        # 프록시(nginx 등) 버퍼링 방지 → 페이지별 점진 노출 보장.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
