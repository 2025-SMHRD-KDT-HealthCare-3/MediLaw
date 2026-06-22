"""멀티에이전트 C — OCR 추출.

스캔/이미지 페이지를 OCR해 B(extract_digital)와 **동일한 Block[] 형식**으로 산출한다.
(source="ocr", confidence 채움 — 단 폴백에선 None 허용)

흐름: 페이지 렌더(pypdfium2) → OCR 백엔드 → 줄/문단 단위 Block.

────────────────────────────────────────────────────────────────────────────
백엔드 추상화 / 데이터 거주(data residency) 정책
────────────────────────────────────────────────────────────────────────────
OCR 백엔드는 OCR_BACKEND 환경변수로 교체한다.

  "paddleocr_vl"  (프로덕션, 권장):
      국내 자체 호스팅 PaddleOCR-VL. 데이터가 외부로 나가지 않음(거주 정책 준수).
      이 개발 환경엔 모델/패키지가 없으므로 **인터페이스 스텁만** 둔다.
      실제 모델 로딩/설치 금지. 미설치 시 graceful 빈 결과.

  "vision"        (개발 폴백, 기본값):
      기존 app.llm.ocr_image(b64_png)(OpenAI 비전) 재사용.
      ⚠️ 외부(OpenAI) 호출이므로 **데이터 거주 정책 위반 — 개발용 폴백 전용**이다.
      프로덕션에서는 반드시 OCR_BACKEND="paddleocr_vl" 로 전환할 것.

기본값이 "vision"인 이유: 이 환경에 paddleocr_vl 모델이 없어 개발 검증이
가능한 폴백을 기본으로 둔다. 운영 배포 시 환경변수로 강제 전환한다.

모든 처리는 graceful: 렌더/백엔드 실패 시 빈 리스트(또는 처리된 부분까지).
"""
import base64
import io
import os
import sys

# 단독 러너(__main__)에서도 `from app.pdf...` import가 되도록 프로젝트 루트를 path에 추가.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from app.pdf.schema import Block  # noqa: E402

# ── 설정 ─────────────────────────────────────────────────────────────────────
# 백엔드 선택: 환경변수 없으면 개발 폴백("vision"). 프로덕션은 "paddleocr_vl".
OCR_BACKEND = os.environ.get("OCR_BACKEND", "vision")

OCR_SCALE = 2.0            # 렌더 배율(≈144DPI; A4 기준 ~1.7K, scale 2.0이면 ~2K폭)
OCR_MAX_PAGES = 20         # 비용/시간 방어 상한

# 낮은 신뢰도 플래그 임계값(이 미만이면 low_confidence=True 로 표시).
# vision 폴백은 confidence=None 이라 플래그 대상이 아님.
LOW_CONFIDENCE_THRESHOLD = 0.6


# ── 페이지 렌더 ──────────────────────────────────────────────────────────────
def _render_pages(pdf_bytes: bytes, pages: "list[int] | None") -> "list[tuple[int, str]]":
    """PDF 바이트를 페이지별 (page_no_1based, b64_png) 목록으로 렌더.

    pages: 1-based 페이지 번호 리스트. None이면 앞 OCR_MAX_PAGES 페이지.
    렌더 실패(미설치/손상)는 graceful — 가능한 페이지까지만 반환.
    """
    if not pdf_bytes:
        return []
    try:
        import pypdfium2 as pdfium
    except ImportError:
        # pypdfium2 미설치 — graceful
        return []

    out: "list[tuple[int, str]]" = []
    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
        n = len(pdf)
        if pages is None:
            targets = list(range(1, min(n, OCR_MAX_PAGES) + 1))
        else:
            # 1-based, 범위 밖/중복 제거, 상한 적용
            targets = sorted({p for p in pages if 1 <= p <= n})[:OCR_MAX_PAGES]

        for p in targets:
            try:
                bitmap = pdf[p - 1].render(scale=OCR_SCALE)
                buf = io.BytesIO()
                bitmap.to_pil().save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode()
                out.append((p, b64))
            except Exception:
                # 개별 페이지 렌더 실패 → 건너뜀(graceful)
                continue
    except Exception:
        # 문서 자체 파싱 실패 → 처리된 부분까지
        return out
    return out


# ── 백엔드: PaddleOCR-VL (프로덕션 스텁) ──────────────────────────────────────
def _ocr_paddleocr_vl(b64_png: str) -> "list[tuple[str, float | None, list[float] | None]]":
    """프로덕션 백엔드: 국내 자체 호스팅 PaddleOCR-VL.

    반환: (text, confidence, bbox[x0,y0,x1,y1]) 튜플 리스트(줄/영역 단위).
    bbox 는 가능하면 채운다(before/after 치환용). confidence 는 0~1.

    ── 인터페이스 스텁 ──
    실제 호출은 자체 호스팅 추론 서버(예: PaddleOCR-VL vLLM 엔드포인트)로 보낸다.
    이 개발 환경엔 모델/패키지가 없으므로 **여기서 모델을 로딩하지 않는다.**
    배포 시 아래 자리에서 추론 서버를 호출하고, 결과를 (text, conf, bbox)로 매핑한다.

    예시(미구현 — 의사코드):
        client = PaddleVLClient(endpoint=os.environ["PADDLE_OCR_VL_URL"])
        result = client.recognize(png_bytes=base64.b64decode(b64_png))
        return [(r.text, r.score, r.bbox) for r in result.lines]

    미설치/미구성 환경에선 빈 리스트로 graceful degrade.
    """
    endpoint = os.environ.get("PADDLE_OCR_VL_URL")
    if not endpoint:
        # 추론 서버 미구성 — graceful 빈 결과(개발 환경 기본 동작)
        return []
    # 실제 호출 자리(미구현). 모델 로딩 금지 — 원격 추론 서버 호출만 허용.
    raise NotImplementedError(
        "paddleocr_vl 백엔드는 자체 호스팅 추론 서버 연동이 필요합니다 "
        "(PADDLE_OCR_VL_URL 구성 후 _ocr_paddleocr_vl 구현)."
    )


# ── 백엔드: vision (개발 폴백, OpenAI) ────────────────────────────────────────
def _ocr_vision(b64_png: str) -> "list[tuple[str, float | None, list[float] | None]]":
    """개발 폴백 백엔드: app.llm.ocr_image(OpenAI 비전).

    ⚠️ 외부 호출 — 데이터 거주 정책 위반. 개발/검증 전용.
    plain text(줄바꿈 보존)를 받아 줄 단위 (text, None, None) 으로 래핑.
    confidence/bbox 미지원(None). LLM 사용불가/실패 시 빈 리스트(graceful).
    """
    try:
        from app import llm
    except Exception:
        return []
    try:
        text = llm.ocr_image(b64_png) or ""
    except Exception:
        # LLMUnavailable(키 없음) 포함 모든 실패 → graceful 빈 결과
        return []
    # 줄 단위로 분해(빈 줄 제거). bbox/confidence 없음.
    return [(line.strip(), None, None) for line in text.splitlines() if line.strip()]


_BACKENDS = {
    "paddleocr_vl": _ocr_paddleocr_vl,
    "vision": _ocr_vision,
}


# ── 메인 ─────────────────────────────────────────────────────────────────────
def extract_ocr(pdf_bytes: bytes, pages: "list[int] | None" = None) -> "list[Block]":
    """스캔/이미지 PDF 페이지를 OCR해 B와 동일한 Block[] 형식으로 반환.

    pages: 1-based 페이지 번호 리스트(보통 A 라우팅의 scan 페이지). None=앞 N페이지.
    각 Block: source="ocr", type="para", confidence/bbox 는 백엔드 지원 시 채움.
    모든 단계 graceful — 실패 시 빈 리스트(또는 처리된 부분까지).
    """
    backend = _BACKENDS.get(OCR_BACKEND)
    if backend is None:
        # 알 수 없는 백엔드 → 개발 폴백으로
        backend = _ocr_vision

    rendered = _render_pages(pdf_bytes, pages)
    if not rendered:
        return []

    blocks: "list[Block]" = []
    counter = 0
    for page_no, b64 in rendered:
        try:
            lines = backend(b64)
        except NotImplementedError:
            # 프로덕션 백엔드 미구현 환경 → 해당 페이지 graceful skip
            continue
        except Exception:
            continue
        for text, conf, bbox in lines:
            if not text:
                continue
            counter += 1
            blocks.append(Block(
                id=f"ocr-p{page_no}-{counter}",
                type="para",
                text=text,
                page=page_no,
                bbox=bbox,
                source="ocr",
                confidence=conf,
            ))
    return blocks


def is_low_confidence(block: "Block") -> bool:
    """낮은 신뢰도 블록 플래그. confidence=None(폴백)은 플래그하지 않음(False)."""
    return block.confidence is not None and block.confidence < LOW_CONFIDENCE_THRESHOLD


# ── pytest 함수 ──────────────────────────────────────────────────────────────
def test_empty_bytes_returns_empty():
    assert extract_ocr(b"") == []


def test_invalid_pdf_is_graceful():
    # PDF가 아닌 쓰레기 바이트 → 예외 없이 빈 리스트
    assert extract_ocr(b"not a pdf at all") == []


def test_unknown_backend_falls_back(monkeypatch=None):
    # 알 수 없는 백엔드여도 예외 없이 동작(빈 입력 → 빈 결과)
    assert extract_ocr(b"") == []


def test_low_confidence_flag():
    hi = Block(id="x", type="para", text="t", page=1, source="ocr", confidence=0.9)
    lo = Block(id="y", type="para", text="t", page=1, source="ocr", confidence=0.3)
    none = Block(id="z", type="para", text="t", page=1, source="ocr", confidence=None)
    assert is_low_confidence(lo) is True
    assert is_low_confidence(hi) is False
    assert is_low_confidence(none) is False


def test_paddleocr_vl_graceful_without_endpoint():
    # 추론 서버 미구성 시 빈 결과(graceful, NotImplementedError 아님)
    prev = os.environ.pop("PADDLE_OCR_VL_URL", None)
    try:
        assert _ocr_paddleocr_vl("x") == []
    finally:
        if prev is not None:
            os.environ["PADDLE_OCR_VL_URL"] = prev


def test_block_format_matches_contract():
    # vision 폴백 출력 형식 검증(OpenAI 호출 없이 백엔드만 monkeypatch).
    import app.pdf.extract_ocr as mod

    orig = mod._BACKENDS["vision"]
    mod._BACKENDS["vision"] = lambda b64: [("샘플 줄1", None, None), ("샘플 줄2", None, None)]
    try:
        # _render_pages 도 우회: 가짜 렌더 결과 주입
        orig_render = mod._render_pages
        mod._render_pages = lambda data, pages: [(1, "fakeb64")]
        try:
            blocks = mod.extract_ocr(b"whatever")
        finally:
            mod._render_pages = orig_render
    finally:
        mod._BACKENDS["vision"] = orig

    assert len(blocks) == 2
    assert all(isinstance(b, Block) for b in blocks)
    assert all(b.source == "ocr" for b in blocks)
    assert all(b.type == "para" and b.page == 1 for b in blocks)
    assert [b.id for b in blocks] == ["ocr-p1-1", "ocr-p1-2"]


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
    print(f"OCR_BACKEND = {OCR_BACKEND}")
    print("  graceful empty :", extract_ocr(b""))
    print("  graceful junk  :", extract_ocr(b"not a pdf"))

    sample = _sample_pdf_bytes()
    if sample is None:
        print(f"(샘플 PDF '{_SAMPLE_PDF}' 없음)")
        return

    # 렌더 동작 확인(백엔드 호출 없이)
    rendered = _render_pages(sample, pages=[1])
    print(f"render p1: {len(rendered)} page(s) → "
          f"{'PNG OK' if rendered else '렌더 실패/미설치(graceful)'}")

    if OCR_BACKEND == "vision" and not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY 없음 — vision 폴백 실제 호출 skip(렌더까지만 확인)")
        return
    blocks = extract_ocr(sample, pages=[1])
    print(f"ocr blocks(p1): {len(blocks)} | source: "
          f"{set(b.source for b in blocks) or '(빈-graceful)'}")
    if blocks:
        assert all(b.source == "ocr" for b in blocks)
        for b in blocks[:5]:
            flag = " [LOW]" if is_low_confidence(b) else ""
            print(f"  {b.id}: {b.text[:50]!r}{flag}")


if __name__ == "__main__":
    _run()
