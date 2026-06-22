"""PDF 파이프라인 통합 (오케스트레이터 소유) — A→(B∥C)→D→E→F.

route_pages → 페이지별 extract_digital / extract_ocr → Document.blocks
→ to_segments → review_segments → apply_revisions.

각 단계는 서브에이전트가 계약(app/pdf/schema.py) 기준으로 구현. 여기선 조립만.
"""
from typing import Optional

from app.pdf import classify, extract_digital, extract_ocr, review, revise, routing, segment
from app.pdf.schema import Document


def process_pdf(
    pdf_bytes: bytes,
    doc_id: str = "doc",
    doc_type: Optional[str] = None,
    as_of: Optional[str] = None,
    top_k: int = 4,
    pages: Optional[list[int]] = None,   # 특정 페이지(1-based)만 — 대용량/비용 통제
    ocr: bool = True,
) -> dict:
    """PDF → 위험검토 결과. {document, routes, segments, revisions}."""
    # A. 페이지 라우팅
    routes = routing.route_pages(pdf_bytes)
    if pages is not None:
        routes = [r for r in routes if r.page in pages]
    digital_pages = [r.page for r in routes if r.route == "digital"]
    scan_pages = [r.page for r in routes if r.route == "scan"]

    # B/C. 추출 (디지털 ∥ OCR) — 동일 Block 형식
    blocks = []
    if digital_pages:
        blocks += extract_digital.extract_digital(pdf_bytes, pages=digital_pages)
    if scan_pages and ocr:
        blocks += extract_ocr.extract_ocr(pdf_bytes, pages=scan_pages)
    blocks.sort(key=lambda b: b.page)  # 페이지 순(페이지 집합이 disjoint라 안정)

    # doc_type 미지정 시 추출 텍스트로 자동 분류(주어지면 그대로 — 하위호환).
    if doc_type is None and blocks:
        doc_type = classify.classify_blocks(blocks)

    doc = Document(doc_id=doc_id, doc_type=doc_type, page_count=len(routes), blocks=blocks)

    # D. 세그먼트 → E. 위험판정 → F. 치환
    segs = segment.to_segments(blocks, doc_type=doc_type)
    segs = review.review_segments(segs, as_of=as_of, top_k=top_k)
    revisions = revise.apply_revisions(doc, segs)
    doc.status = "reviewed"

    return {"document": doc, "routes": routes, "segments": segs, "revisions": revisions}
