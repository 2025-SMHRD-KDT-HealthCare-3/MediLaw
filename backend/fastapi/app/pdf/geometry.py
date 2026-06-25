"""PDF 위험 세그먼트의 위치를 페이지 상대 정규화 좌표로 변환.

digital 블록 bbox = PDF 포인트(좌상단 원점), OCR 블록 bbox = 렌더 픽셀(=포인트×OCR_SCALE).
둘을 페이지 폭/높이로 나눠 [0..1] 상대좌표로 통일 → 프론트는 캔버스 크기만 곱하면 됨.

흐름:
  page_sizes(pdf_bytes) 로 1-based 페이지 → (width_pt, height_pt) 사전을 한 번 만들고,
  세그먼트마다 finding_geometry(seg, block_by_id, page_sizes) 로 (page, bbox[0..1]) 산출.
  digital(source != "ocr")은 분모 (W, H), OCR(source == "ocr")은 분모 (W*scale, H*scale).
  (픽셀/(pt*scale)=상대, 포인트/pt=상대 → 둘 다 [0..1] 동일 좌표계로 통일됨)

모든 함수는 graceful — 미설치/손상/누락/분모0 등 어떤 예외도 전파하지 않는다.
"""
from __future__ import annotations

import os
import sys

# `python3 app/pdf/geometry.py` 로 직접 실행할 때도 `app` 패키지를 찾도록 루트를 path에.
if __package__ in (None, ""):
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _root not in sys.path:
        sys.path.insert(0, _root)

# OCR 블록 bbox는 페이지를 OCR_SCALE배로 렌더한 픽셀 좌표 → 정규화 시 분모에 곱한다.
from app.pdf.extract_ocr import OCR_SCALE  # noqa: E402


def page_sizes(pdf_bytes: bytes) -> "dict[int, tuple[float, float]]":
    """PDF 바이트 → {1-based 페이지: (width_pt, height_pt)} 사전.

    pypdfium2 로 각 페이지의 PDF 포인트 크기를 읽는다.
    미설치/손상/빈 입력 등 모든 예외는 graceful → 빈 사전({}) 반환(예외 전파 금지).
    """
    if not pdf_bytes:
        return {}
    try:
        import pypdfium2 as pdfium
    except Exception:  # noqa: BLE001 — 미설치 등
        return {}

    out: "dict[int, tuple[float, float]]" = {}
    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
        n = len(pdf)
        for i in range(n):
            try:
                w, h = pdf[i].get_size()  # (width_pt, height_pt)
                out[i + 1] = (float(w), float(h))
            except Exception:  # noqa: BLE001 — 개별 페이지 실패는 건너뜀
                continue
    except Exception:  # noqa: BLE001 — 문서 파싱 실패 → 처리된 부분까지
        return out
    return out


def _clamp01(v: float) -> float:
    """[0, 1] 범위로 자른다."""
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def finding_geometry(
    seg,
    block_by_id: dict,
    page_sizes: "dict[int, tuple[float, float]]",
    ocr_scale: float = OCR_SCALE,
) -> "tuple[int | None, list[float] | None]":
    """위험 세그먼트의 (1-based page, 페이지 상대 정규화 bbox[x0,y0,x1,y1]) 산출.

    Args:
        seg: block_ids 속성을 가진 세그먼트(Segment).
        block_by_id: {block_id: Block} 사전. Block 은 page/bbox/source 속성을 가짐.
        page_sizes: page_sizes() 결과 — {1-based page: (W_pt, H_pt)}.
        ocr_scale: OCR 렌더 배율(기본 OCR_SCALE). OCR 블록 bbox 분모에 곱한다.

    Returns:
        (page, bbox): bbox 는 [x0,y0,x1,y1] 0~1 정규화(좌상단 원점), 좌표 산출 불가 시 None.
        graceful 규칙(아래)에 걸리면 bbox=None 을 반환하되 page 는 가능하면 채운다.

    graceful 규칙(예외 전파 금지):
        - block_ids 가 없거나 매칭 블록이 전혀 없음 → (None, None)
        - 매칭 블록은 있으나 bbox 가진 블록이 없음 → (page, None)  ※ page 는 첫 블록 것
        - page_sizes 에 해당 page 가 없음 / 분모(W 또는 H, OCR이면 ×scale)가 0 → (page, None)
    """
    try:
        block_ids = list(getattr(seg, "block_ids", None) or [])
    except Exception:  # noqa: BLE001
        return (None, None)

    # block_ids 순서대로 매칭 블록 수집.
    blocks = []
    for bid in block_ids:
        blk = block_by_id.get(bid)
        if blk is not None:
            blocks.append(blk)
    if not blocks:
        return (None, None)

    # page = 첫 블록의 page(매칭 블록 중 가장 앞).
    page = getattr(blocks[0], "page", None)
    try:
        page = int(page) if page is not None else None
    except (TypeError, ValueError):
        page = None

    # 같은 page + bbox 있는 블록만 모아 union.
    same_page = [b for b in blocks if getattr(b, "page", None) == page]
    boxed = [b for b in same_page if getattr(b, "bbox", None)]
    if not boxed:
        return (page, None)

    # union(min x0, min y0, max x1, max y1). bbox 형식 불량은 건너뜀.
    x0s, y0s, x1s, y1s = [], [], [], []
    for b in boxed:
        try:
            bx0, by0, bx1, by1 = (float(v) for v in b.bbox[:4])
        except (TypeError, ValueError, IndexError):
            continue
        # 좌표가 뒤집혀 들어와도 안전하게 정규화.
        x0s.append(min(bx0, bx1))
        y0s.append(min(by0, by1))
        x1s.append(max(bx0, bx1))
        y1s.append(max(by0, by1))
    if not x0s:
        return (page, None)
    ux0, uy0, ux1, uy1 = min(x0s), min(y0s), max(x1s), max(y1s)

    # 페이지 크기(포인트). 없으면 정규화 불가 → bbox None.
    size = page_sizes.get(page) if page is not None else None
    if not size:
        return (page, None)
    w_pt, h_pt = float(size[0]), float(size[1])

    # OCR 블록이면 픽셀 좌표 → 분모에 scale 을 곱한다(픽셀/(pt*scale)=상대).
    # union 에 쓰인 블록 중 하나라도 OCR source 면 OCR 분모로 본다(OCR/digital 혼합은 비정상이라
    # 보수적으로 OCR 기준; 보통 한 세그먼트는 한 source).
    is_ocr = any(getattr(b, "source", None) == "ocr" for b in boxed)
    denom_w = w_pt * ocr_scale if is_ocr else w_pt
    denom_h = h_pt * ocr_scale if is_ocr else h_pt
    if denom_w <= 0 or denom_h <= 0:
        return (page, None)

    bbox = [
        _clamp01(ux0 / denom_w),
        _clamp01(uy0 / denom_h),
        _clamp01(ux1 / denom_w),
        _clamp01(uy1 / denom_h),
    ]
    return (page, bbox)


# ── pytest 함수 ──────────────────────────────────────────────────────────────
# 실제 Block/Segment 대신 가벼운 가짜 객체로 좌표 변환 로직만 검증한다.
class _FakeBlock:
    def __init__(self, id, page, bbox, source="digital"):
        self.id = id
        self.page = page
        self.bbox = bbox
        self.source = source


class _FakeSeg:
    def __init__(self, block_ids):
        self.block_ids = block_ids


def _by_id(blocks):
    return {b.id: b for b in blocks}


def _approx(a, b, eps=1e-9):
    return abs(a - b) <= eps


def test_digital_normalization():
    # digital 블록: 분모 = (W, H). bbox=[100,200,300,400], page=(1000,2000).
    blk = _FakeBlock("b1", 1, [100.0, 200.0, 300.0, 400.0], source="digital")
    seg = _FakeSeg(["b1"])
    page, bbox = finding_geometry(seg, _by_id([blk]), {1: (1000.0, 2000.0)})
    assert page == 1
    assert _approx(bbox[0], 0.1) and _approx(bbox[1], 0.1)
    assert _approx(bbox[2], 0.3) and _approx(bbox[3], 0.2)


def test_ocr_same_position_as_digital():
    # OCR 블록은 픽셀(포인트×scale)이므로, digital 의 scale배 bbox 를 넣으면 동일 정규좌표.
    scale = 2.0
    page_sz = {1: (1000.0, 2000.0)}
    dig = _FakeBlock("d", 1, [100.0, 200.0, 300.0, 400.0], source="digital")
    ocr = _FakeBlock("o", 1,
                     [100.0 * scale, 200.0 * scale, 300.0 * scale, 400.0 * scale],
                     source="ocr")
    _, bbox_d = finding_geometry(_FakeSeg(["d"]), _by_id([dig]), page_sz, ocr_scale=scale)
    _, bbox_o = finding_geometry(_FakeSeg(["o"]), _by_id([ocr]), page_sz, ocr_scale=scale)
    assert all(_approx(a, b) for a, b in zip(bbox_d, bbox_o))


def test_no_blocks_graceful():
    # 매칭되는 블록이 전혀 없음 → (None, None).
    seg = _FakeSeg(["missing"])
    assert finding_geometry(seg, {}, {1: (1000.0, 2000.0)}) == (None, None)
    # block_ids 비어있음 → (None, None).
    assert finding_geometry(_FakeSeg([]), {}, {}) == (None, None)


def test_blocks_without_bbox_graceful():
    # 블록은 있으나 bbox 없음 → (page, None).
    blk = _FakeBlock("b1", 3, None)
    page, bbox = finding_geometry(_FakeSeg(["b1"]), _by_id([blk]), {3: (500.0, 700.0)})
    assert page == 3 and bbox is None


def test_page_missing_in_sizes_graceful():
    # page_sizes 에 해당 page 없음 → (page, None).
    blk = _FakeBlock("b1", 5, [10.0, 10.0, 20.0, 20.0])
    page, bbox = finding_geometry(_FakeSeg(["b1"]), _by_id([blk]), {1: (100.0, 100.0)})
    assert page == 5 and bbox is None


def test_multiblock_union():
    # 같은 page 의 여러 블록 → union(min,min,max,max) 후 정규화.
    b1 = _FakeBlock("b1", 1, [100.0, 100.0, 200.0, 200.0])
    b2 = _FakeBlock("b2", 1, [150.0, 50.0, 400.0, 300.0])
    seg = _FakeSeg(["b1", "b2"])
    page, bbox = finding_geometry(seg, _by_id([b1, b2]), {1: (1000.0, 1000.0)})
    # union = [100, 50, 400, 300] / 1000
    assert page == 1
    assert _approx(bbox[0], 0.10) and _approx(bbox[1], 0.05)
    assert _approx(bbox[2], 0.40) and _approx(bbox[3], 0.30)


def test_clamp_to_unit():
    # bbox 가 페이지를 벗어나도 [0,1] 로 clamp.
    blk = _FakeBlock("b1", 1, [-50.0, -10.0, 2000.0, 3000.0])
    _, bbox = finding_geometry(_FakeSeg(["b1"]), _by_id([blk]), {1: (1000.0, 1000.0)})
    assert bbox == [0.0, 0.0, 1.0, 1.0]


def test_page_sizes_graceful_empty():
    # 빈/쓰레기 입력 → 예외 없이 {} (pypdfium2 미설치 환경도 graceful).
    assert page_sizes(b"") == {}


# ── 단독 러너 ────────────────────────────────────────────────────────────────
_SAMPLE_PDF = "기획서(최종 수정 중 ).pdf"


def _sample_pdf_bytes():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(root, _SAMPLE_PDF)
    if not os.path.exists(path):
        if os.path.exists(_SAMPLE_PDF):
            path = _SAMPLE_PDF
        else:
            return None
    with open(path, "rb") as f:
        return f.read()


def _run():
    # 셀프테스트 — 모든 test_* 함수 실행.
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
        passed += 1
    print(f"셀프테스트 {passed}/{len(tests)} 통과")

    # 샘플 PDF page_sizes 가벼운 확인(설치돼 있으면).
    sample = _sample_pdf_bytes()
    if sample is None:
        print(f"(샘플 PDF '{_SAMPLE_PDF}' 없음 — page_sizes 실측 skip)")
        return
    sizes = page_sizes(sample)
    if sizes:
        first = sorted(sizes)[0]
        print(f"page_sizes: {len(sizes)} page(s), p{first}={sizes[first]} "
              f"(OCR_SCALE={OCR_SCALE})")
    else:
        print("page_sizes 빈 결과 — pypdfium2 미설치/손상(graceful)")


if __name__ == "__main__":
    _run()
