"""멀티에이전트 A — 페이지 라우팅.

PDF를 페이지별로 "디지털(텍스트 레이어 있음)" vs "스캔(이미지/사진)"으로 분기한다.
**문서 전체 단위 판정 금지 — 페이지 단위로만 판정한다.**

판정 기준:
  각 페이지에서 pypdf로 추출한 텍스트(`page.extract_text()`)의
  공백 제거 후 문자 수가 임계값 미만이면 "scan", 아니면 "digital".

출력 계약(이미 잠김): app.pdf.schema.PageRoute(page:int, route:"digital"|"scan").
page 번호는 1-based.

실행:
  pytest tests/test_pdf_routing.py   # (있다면)
  python app/pdf/routing.py          # 단독 러너(샘플 PDF 요약 출력)
"""
import io
import os
import sys

# 단독 러너(__main__)에서도 `from app.pdf...` import가 되도록 프로젝트 루트를 path에 추가.
# (tests/test_domain_router.py 의 sys.path.insert 패턴과 동일한 의도)
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from pypdf import PdfReader  # noqa: E402

from app.pdf.schema import PageRoute  # noqa: E402

# 디지털로 판정하기 위한 최소 추출 문자 수(공백 제거 기준).
# 스캔 페이지는 보통 0~몇 글자(워터마크/잡음)만 잡히고, 디지털 페이지는 훨씬 많다.
# NOTE: 실제 샘플로 튜닝 필요 — 표지/도표 위주의 디지털 페이지는 글자 수가 적을 수 있고,
#       반대로 OCR 텍스트 레이어가 박힌 스캔본은 글자 수가 많을 수 있으므로 운영 데이터로 조정한다.
MIN_DIGITAL_CHARS = 15


def _extractable_char_count(page) -> int:
    """페이지에서 추출 가능한, 공백을 제외한 문자 수. 추출 실패 시 0."""
    try:
        text = page.extract_text() or ""
    except Exception:
        # 손상 페이지/추출 예외 → 스캔으로 흘러가도록 0 반환
        return 0
    return len("".join(text.split()))


def route_pages(pdf_bytes: bytes) -> list[PageRoute]:
    """PDF 바이트를 받아 페이지별 디지털/스캔 라우팅을 반환한다(1-based).

    파싱 실패/빈 PDF는 graceful 하게 처리:
      - PDF 자체를 열 수 없으면 빈 리스트.
      - 개별 페이지 추출이 실패하면 해당 페이지를 "scan"으로 처리.
    """
    if not pdf_bytes:
        return []

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = reader.pages
    except Exception:
        # 손상되었거나 PDF가 아닌 입력 → graceful 빈 리스트
        return []

    routes: list[PageRoute] = []
    for idx, page in enumerate(pages):
        char_count = _extractable_char_count(page)
        kind = "digital" if char_count >= MIN_DIGITAL_CHARS else "scan"
        routes.append(PageRoute(page=idx + 1, route=kind))
    return routes


# ── pytest 함수 ──────────────────────────────────────────────────────────────
def test_empty_bytes_returns_empty():
    assert route_pages(b"") == []


def test_invalid_pdf_is_graceful():
    # PDF가 아닌 쓰레기 바이트 → 예외 없이 빈 리스트
    assert route_pages(b"not a pdf at all") == []


def test_routes_are_valid_kind():
    sample = _sample_pdf_bytes()
    if sample is None:
        return  # 샘플 없으면 스킵
    routes = route_pages(sample)
    assert routes, "샘플 PDF는 최소 1페이지여야"
    assert all(r.route in ("digital", "scan") for r in routes)
    # page 번호는 1-based 연속
    assert [r.page for r in routes] == list(range(1, len(routes) + 1))


def test_digital_pdf_has_digital_pages():
    sample = _sample_pdf_bytes()
    if sample is None:
        return
    routes = route_pages(sample)
    assert any(r.route == "digital" for r in routes), "디지털 페이지가 잡혀야"


# ── 단독 러너 ────────────────────────────────────────────────────────────────
_SAMPLE_PDF = "기획서(최종 수정 중 ).pdf"


def _sample_pdf_bytes():
    """프로젝트 루트의 샘플 기획서 PDF(디지털)를 읽어 반환. 없으면 None."""
    root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    path = os.path.join(root, _SAMPLE_PDF)
    if not os.path.exists(path):
        # cwd 기준으로도 한 번 시도
        if os.path.exists(_SAMPLE_PDF):
            path = _SAMPLE_PDF
        else:
            return None
    with open(path, "rb") as f:
        return f.read()


def _run():
    print(f"MIN_DIGITAL_CHARS = {MIN_DIGITAL_CHARS}")
    sample = _sample_pdf_bytes()
    if sample is None:
        print(f"(샘플 PDF '{_SAMPLE_PDF}' 없음 — graceful 케이스만 확인)")
        print("  empty :", route_pages(b""))
        print("  junk  :", route_pages(b"not a pdf"))
        return
    routes = route_pages(sample)
    print(f"pages: {len(routes)}")
    for r in routes:
        print(f"  p{r.page:>3}: {r.route}")
    n_digital = sum(r.route == "digital" for r in routes)
    n_scan = sum(r.route == "scan" for r in routes)
    print(f"\n요약: digital={n_digital}, scan={n_scan}")


if __name__ == "__main__":
    _run()
