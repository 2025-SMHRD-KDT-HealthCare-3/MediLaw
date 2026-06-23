"""멀티에이전트 B — 디지털 추출.

텍스트 레이어가 있는 PDF 페이지를 pdfplumber로 읽어 공유 계약의 `Block[]`으로 변환한다.
읽기 순서를 유지하고 표는 `table` + `table_row` 블록으로 보존한다.

C(OCR) 에이전트와 동일한 Block 형식을 내야 하므로(하류 D가 둘을 구분 없이 처리),
`source`는 항상 "digital", `confidence`는 항상 None 으로 둔다.

사용:
    from app.pdf.extract_digital import extract_digital
    blocks = extract_digital(pdf_bytes, pages=[2, 8])  # 1-based, None이면 전체
"""
from __future__ import annotations

import io

import pdfplumber

# `python3 app/pdf/extract_digital.py` 로 직접 실행할 때도 `app` 패키지를
# 찾을 수 있도록 프로젝트 루트(.../fastapi)를 path에 추가(직접 실행 시에만).
if __package__ in (None, ""):
    import os
    import sys

    _root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    if _root not in sys.path:
        sys.path.insert(0, _root)

from app.pdf.schema import Block

# 표 영역과 일반 텍스트가 겹쳐 중복 추출되는 것을 막기 위한 표 경계 여유(pt).
_TABLE_PAD = 2.0
# heading 휴리스틱: 페이지 평균 글자 높이 대비 이 배수 이상이면 heading 후보.
_HEADING_SIZE_RATIO = 1.35
# heading 후보로 보는 최대 글자 수(제목은 보통 짧다).
_HEADING_MAX_CHARS = 60


def _rects_overlap(a: tuple[float, float, float, float],
                   b: tuple[float, float, float, float]) -> bool:
    """두 사각형(x0, top, x1, bottom)이 겹치면 True."""
    ax0, atop, ax1, abot = a
    bx0, btop, bx1, bbot = b
    return not (ax1 <= bx0 or bx1 <= ax0 or abot <= btop or bbot <= atop)


def _line_bbox(words: list[dict]) -> list[float]:
    """한 줄을 이루는 word dict 들에서 [x0, top, x1, bottom] bbox 계산."""
    x0 = min(w["x0"] for w in words)
    top = min(w["top"] for w in words)
    x1 = max(w["x1"] for w in words)
    bottom = max(w["bottom"] for w in words)
    return [x0, top, x1, bottom]


def _group_words_into_lines(words: list[dict]) -> list[list[dict]]:
    """extract_words 결과를 (top 기준) 읽기 순서대로 줄 단위로 묶는다."""
    if not words:
        return []
    # pdfplumber는 보통 top -> x0 순으로 주지만 안전하게 정렬.
    ordered = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))
    lines: list[list[dict]] = []
    current: list[dict] = []
    current_top: float | None = None
    for w in ordered:
        # 같은 줄 판단 기준: 글자 높이의 절반 이내면 같은 줄로 본다.
        h = max(w["bottom"] - w["top"], 1.0)
        if current_top is None or abs(w["top"] - current_top) <= h * 0.6:
            current.append(w)
            current_top = w["top"] if current_top is None else current_top
        else:
            lines.append(current)
            current = [w]
            current_top = w["top"]
    if current:
        lines.append(current)
    return lines


def _classify_line(words: list[dict], avg_height: float) -> str:
    """단순 휴리스틱으로 heading/para 분류. 기본은 para."""
    text = " ".join(w["text"] for w in words).strip()
    if not text or len(text) > _HEADING_MAX_CHARS:
        return "para"
    line_h = max((w["bottom"] - w["top"]) for w in words)
    if avg_height > 0 and line_h >= avg_height * _HEADING_SIZE_RATIO:
        return "heading"
    return "para"


def _extract_page_blocks(page, page_no: int) -> list[Block]:
    """단일 pdfplumber 페이지 → Block 리스트. 실패 시 빈 리스트."""
    blocks: list[Block] = []
    n = 0  # 텍스트 블록 카운터
    k = 0  # 표 카운터

    # --- 1) 표 추출 (영역 기록 후 표 밖 텍스트만 para로) ---
    table_rects: list[tuple[float, float, float, float]] = []
    try:
        tables = page.find_tables()
    except Exception:
        tables = []

    for tbl in tables:
        try:
            rows = tbl.extract()
        except Exception:
            rows = None
        if not rows:
            continue

        tx0, ttop, tx1, tbot = tbl.bbox  # (x0, top, x1, bottom)
        table_rects.append((tx0 - _TABLE_PAD, ttop - _TABLE_PAD,
                            tx1 + _TABLE_PAD, tbot + _TABLE_PAD))
        table_id = f"p{page_no}-t{k}"
        ncols = max((len(r) for r in rows), default=0)
        blocks.append(Block(
            id=table_id,
            type="table",
            text="",
            page=page_no,
            bbox=[float(tx0), float(ttop), float(tx1), float(tbot)],
            source="digital",
            confidence=None,
        ))

        # 행별 bbox는 tbl.rows 에서 가능하면 채운다.
        row_bboxes: list[list[float] | None] = []
        try:
            for r in tbl.rows:
                rb = getattr(r, "bbox", None)
                row_bboxes.append([float(v) for v in rb] if rb else None)
        except Exception:
            row_bboxes = []

        for i, row in enumerate(rows):
            cells = [(c if c is not None else "").replace("\n", " ").strip()
                     for c in row]
            row_text = " | ".join(cells)
            rb = row_bboxes[i] if i < len(row_bboxes) else None
            blocks.append(Block(
                id=f"{table_id}-r{i}",
                type="table_row",
                text=row_text,
                page=page_no,
                bbox=rb,
                source="digital",
                confidence=None,
                table_ref=table_id,
                row_index=i,
            ))
        k += 1

    # --- 2) 일반 텍스트 (표 영역과 겹치는 줄은 제외) ---
    try:
        words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    except Exception:
        words = []

    if words:
        heights = [w["bottom"] - w["top"] for w in words
                   if w["bottom"] > w["top"]]
        avg_height = sum(heights) / len(heights) if heights else 0.0

        for line_words in _group_words_into_lines(words):
            bbox = _line_bbox(line_words)
            line_rect = (bbox[0], bbox[1], bbox[2], bbox[3])
            # 표 영역과 겹치면 중복이므로 건너뛴다.
            if any(_rects_overlap(line_rect, tr) for tr in table_rects):
                continue
            text = " ".join(w["text"] for w in line_words).strip()
            if not text:
                continue
            btype = _classify_line(line_words, avg_height)
            blocks.append(Block(
                id=f"p{page_no}-b{n}",
                type=btype,
                text=text,
                page=page_no,
                bbox=bbox,
                source="digital",
                confidence=None,
            ))
            n += 1

    # words가 비었으나 표도 없으면 extract_text로 최후 시도(bbox 없음).
    if not blocks:
        try:
            raw = page.extract_text() or ""
        except Exception:
            raw = ""
        for line in (ln.strip() for ln in raw.splitlines()):
            if not line:
                continue
            blocks.append(Block(
                id=f"p{page_no}-b{n}",
                type="para",
                text=line,
                page=page_no,
                bbox=None,
                source="digital",
                confidence=None,
            ))
            n += 1

    return blocks


def extract_digital(pdf_bytes: bytes,
                    pages: list[int] | None = None) -> list[Block]:
    """디지털 PDF 바이트에서 Block 리스트를 추출한다.

    Args:
        pdf_bytes: PDF 원본 바이트.
        pages: 1-based 페이지 번호 리스트. None이면 전체 페이지.

    Returns:
        읽기 순서를 유지한 Block 리스트. 빈/실패 페이지는 graceful 스킵.
    """
    if not pdf_bytes:
        return []

    wanted: set[int] | None = set(pages) if pages else None
    blocks: list[Block] = []

    try:
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
    except Exception:
        return []

    with pdf:
        for idx, page in enumerate(pdf.pages):
            page_no = idx + 1  # 1-based
            if wanted is not None and page_no not in wanted:
                continue
            try:
                blocks.extend(_extract_page_blocks(page, page_no))
            except Exception:
                # 한 페이지 실패가 전체를 막지 않도록.
                continue

    return blocks


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "기획서(최종 수정 중 ).pdf"
    pg = [int(x) for x in sys.argv[2:]] or None
    with open(path, "rb") as f:
        data = f.read()
    result = extract_digital(data, pages=pg)
    print(f"blocks: {len(result)} | types: {sorted(set(b.type for b in result))}")
    for b in result[:15]:
        snippet = (b.text[:70] + "...") if len(b.text) > 70 else b.text
        print(f"  [{b.page}] {b.type:10s} {b.id:14s} {snippet!r}")
