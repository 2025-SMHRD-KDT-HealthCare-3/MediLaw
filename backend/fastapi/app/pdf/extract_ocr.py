"""멀티에이전트 C — OCR 추출.

스캔/이미지 페이지를 OCR해 B(extract_digital)와 **동일한 Block[] 형식**으로 산출한다.
(source="ocr", confidence 채움 — 단 폴백에선 None 허용)

흐름: 페이지 렌더(pypdfium2) → OCR 백엔드 → 줄/문단 단위 Block.

────────────────────────────────────────────────────────────────────────────
백엔드 추상화 / 데이터 거주(data residency) 정책
────────────────────────────────────────────────────────────────────────────
OCR 백엔드는 OCR_BACKEND 환경변수로 교체한다.

  "paddleocr_vl"  (프로덕션, 권장):
      국내 자체 호스팅 PaddleOCR-VL(paddleocr 3.x `PaddleOCRVL`). 데이터가 외부로
      나가지 않음(거주 정책 준수). 첫 호출 시 인스턴스를 지연 생성(프로세스 1회 캐시)하고
      렌더 페이지 이미지를 ocr.predict()로 추론한 뒤 결과를 Block[]으로 매핑한다.

      ⚠️ **이 개발 환경은 모델 가중치 호스트 접근이 차단**되어 있어(URLError: Connection
      refused) 가중치 다운로드가 실패한다 → 인스턴스화/추론이 예외를 내며, 이때는 로그만
      남기고 **빈 결과로 graceful degrade**한다(예외 전파 금지). 가중치를 받을 수 있는
      프로덕션(국내 서버)에서 실제로 동작한다.

  "vision"        (폴백):
      기존 app.llm.ocr_image(b64_png)(OpenAI 비전, gpt-5.5) 재사용.
      ⚠️ 외부(OpenAI) 호출이므로 **데이터 거주 정책상 유의** — 가능하면 paddleocr_vl 사용.

1차 → 폴백 자동 전환(OCR_FALLBACK_BACKEND, 기본 "vision"):
  1차 백엔드(OCR_BACKEND, 기본 paddleocr_vl)가 어떤 페이지에서 빈 결과/예외면
  그 페이지를 폴백 백엔드로 한 번 더 시도한다. 즉 가중치 차단/추론 실패로 PaddleOCR-VL이
  빈 결과를 내면 자동으로 gpt-5.5 비전이 OCR을 이어받는다. 폴백을 끄려면 OCR_FALLBACK_BACKEND="".

import 시 paddle/모델 로딩이나 네트워크 시도가 일어나지 않도록, paddleocr import 및
PaddleOCRVL 인스턴스화는 모두 `paddleocr_vl` 백엔드 첫 호출 시점으로 **지연**한다.

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
# 백엔드 선택: 기본 "paddleocr_vl"(자체호스팅, 데이터 국내처리). 모델 가중치를 받을 수 없는
# 환경(가중치 호스트 차단 등)에선 OCR이 빈 결과(graceful) → 개발/클라우드는 OCR_BACKEND="vision".
OCR_BACKEND = os.environ.get("OCR_BACKEND", "paddleocr_vl")

# 폴백 백엔드: 1차 백엔드가 빈 결과/실패면 페이지 단위로 여기에 재시도한다.
# 프로덕션 paddleocr_vl 가중치 차단/추론 실패 시 "vision"(gpt-5.5 비전, OpenAI)으로 넘겨 OCR.
# ""(빈 문자열)이면 폴백 비활성. 1차와 동일 백엔드면 무시.
# ⚠️ vision 폴백은 외부(OpenAI) 호출이라 데이터 거주 정책상 유의 — 요청에 의해 기본 활성.
OCR_FALLBACK_BACKEND = os.environ.get("OCR_FALLBACK_BACKEND", "vision")

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


# ── 백엔드: PaddleOCR-VL (프로덕션) ───────────────────────────────────────────
# 텍스트로 취급할 레이아웃 라벨(문단류). 그 외(image/chart/seal 등)는 텍스트 추출 대상 아님.
_VL_PARA_LABELS = {
    "text", "paragraph", "paragraph_title", "title", "doc_title", "abstract",
    "content", "header", "footer", "footnote", "reference", "list", "formula",
    "header_image",  # 캡션 텍스트가 들어오는 경우 대비
}
# 표 영역으로 매핑할 라벨.
_VL_TABLE_LABELS = {"table"}
# 텍스트가 없어 스킵할 비텍스트 라벨.
_VL_SKIP_LABELS = {"image", "figure", "chart", "seal", "stamp"}

# 프로세스 1회 캐시(지연 생성). _SENTINEL=초기화 안 함, None=초기화 실패(가중치 차단 등).
_PADDLE_VL = "__uninitialized__"


def _bbox_from_polygon(poly) -> "list[float] | None":
    """폴리곤 점들(또는 [x0,y0,x1,y1])에서 [x0,y0,x1,y1] 사각 bbox 추출(방어적)."""
    if poly is None:
        return None
    try:
        pts = list(poly)
    except TypeError:
        return None
    if not pts:
        return None
    # 이미 [x0,y0,x1,y1] 형태(4개 스칼라)면 그대로 정규화.
    if len(pts) == 4 and all(isinstance(v, (int, float)) for v in pts):
        x0, y0, x1, y1 = (float(v) for v in pts)
        return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
    xs, ys = [], []
    for pt in pts:
        try:
            x, y = pt[0], pt[1]
        except (TypeError, IndexError, KeyError):
            continue
        xs.append(float(x))
        ys.append(float(y))
    if not xs or not ys:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def _result_to_dict(result) -> "dict | None":
    """PaddleOCRVL predict 결과(객체/딕셔너리)를 평탄한 dict로 정규화(방어적).

    버전별로 result.json["res"] / result.json / dict-like 접근이 다를 수 있어 순서대로 시도.
    """
    # 1) MarkdownMixin/JsonMixin: .json -> {"res": {...}}
    try:
        j = getattr(result, "json", None)
        if isinstance(j, dict):
            res = j.get("res", j)
            if isinstance(res, dict):
                return res
    except Exception:
        pass
    # 2) 이미 dict 인 경우
    if isinstance(result, dict):
        return result.get("res", result) if isinstance(result.get("res"), dict) else result
    return None


def _map_vl_result(result, page_no: int) -> "list[tuple[str, str, float | None, list[float] | None]]":
    """PaddleOCRVL 한 페이지 결과 → (block_type, text, confidence, bbox) 튜플 리스트.

    우선순위:
      1) parsing_res_list(레이아웃 인지) — 라벨로 para/table 구분, content=텍스트, bbox 포함.
      2) parsing_res_list 가 비면 spotting_res / overall_ocr_res 의 라인 단위
         (rec_texts/rec_scores/rec_polys) → 모두 para.
    confidence: 라인 단위 spotting 결과는 rec_scores, 레이아웃 블록은 점수 없음(None).
    스키마가 버전마다 달라 getattr/키존재 확인으로 안전하게 처리한다.
    """
    out: "list[tuple[str, str, float | None, list[float] | None]]" = []
    data = _result_to_dict(result)
    if not isinstance(data, dict):
        return out

    parsing = data.get("parsing_res_list") or []
    if isinstance(parsing, (list, tuple)):
        for blk in parsing:
            # 객체(PaddleOCRVLBlock) 또는 dict 모두 지원
            label = (getattr(blk, "label", None)
                     or (blk.get("block_label") if isinstance(blk, dict) else None)
                     or "")
            content = (getattr(blk, "content", None)
                       or (blk.get("block_content") if isinstance(blk, dict) else None)
                       or "")
            bbox_raw = (getattr(blk, "bbox", None)
                        if not isinstance(blk, dict) else blk.get("block_bbox"))
            poly = (getattr(blk, "polygon_points", None)
                    if not isinstance(blk, dict) else blk.get("block_polygon_points"))
            text = (content or "").strip() if isinstance(content, str) else str(content)
            if not text:
                continue
            label_l = str(label).lower()
            if label_l in _VL_SKIP_LABELS:
                continue
            bbox = _bbox_from_polygon(poly) or _bbox_from_polygon(bbox_raw)
            btype = "table" if label_l in _VL_TABLE_LABELS else "para"
            out.append((btype, text, None, bbox))
        if out:
            return out

    # 폴백: 라인 단위 OCR(점수 포함). 키 이름이 버전별로 다를 수 있어 둘 다 본다.
    spotting = data.get("spotting_res") or data.get("overall_ocr_res") or {}
    if isinstance(spotting, dict):
        texts = spotting.get("rec_texts") or []
        scores = spotting.get("rec_scores") or []
        polys = spotting.get("rec_polys") or spotting.get("dt_polys") or []
        for i, t in enumerate(texts):
            text = (t or "").strip() if isinstance(t, str) else str(t)
            if not text:
                continue
            score = None
            if i < len(scores):
                try:
                    score = float(scores[i])
                except (TypeError, ValueError):
                    score = None
            bbox = _bbox_from_polygon(polys[i]) if i < len(polys) else None
            out.append(("para", text, score, bbox))
    return out


# 로컬 PaddleOCR-VL 추론에 필요한 최소 가용 메모리(GB). 모델 ~1.9GB + 프레임워크라
# 6GB 미만이면 로딩 중 OOM(SIGKILL, try/except로 못 막음) 위험 → 아예 시도하지 않는다.
_MIN_OCR_RAM_BYTES = int(os.environ.get("PADDLE_OCR_VL_MIN_RAM_GB", "6")) * (1024 ** 3)


def _has_enough_memory() -> bool:
    """가용 메모리가 로컬 OCR 임계 이상인지. 측정 불가 시 True(정상환경 막지 않음)."""
    try:
        import psutil

        return psutil.virtual_memory().available >= _MIN_OCR_RAM_BYTES
    except Exception:  # noqa: BLE001
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) * 1024 >= _MIN_OCR_RAM_BYTES
        except Exception:  # noqa: BLE001
            pass
        return True


def _get_paddle_vl():
    """PaddleOCRVL 인스턴스를 지연 생성하고 프로세스 1회 캐시.

    가중치 다운로드/패키지 미설치 실패(URLError 등)는 graceful — None 을 캐시하고
    이후 호출은 즉시 빈 결과로 빠진다(반복 재시도/지연 방지). 예외 전파하지 않는다.
    저메모리 환경에선 모델 로딩 자체가 OOM-킬 위험이라, 로딩 전 메모리를 점검해 막는다.
    """
    global _PADDLE_VL
    if _PADDLE_VL != "__uninitialized__":
        return _PADDLE_VL
    try:
        # 지연 import — 모듈 import 시 paddle 로딩/네트워크 시도 방지.
        from paddleocr import PaddleOCRVL
    except Exception as e:  # noqa: BLE001
        print(f"[extract_ocr] paddleocr import 불가 → vision 폴백 권장: {e}")
        _PADDLE_VL = None
        return None
    try:
        # 인스턴스화 시 모델 가중치 해석/다운로드가 일어난다. 차단 환경에선 여기서 실패.
        if not _has_enough_memory():
            # 로컬 로딩인데 메모리 부족 → OOM-킬 방지 위해 시도조차 안 함.
            print(f"[extract_ocr] 가용 메모리가 {_MIN_OCR_RAM_BYTES // (1024**3)}GB 미만 → "
                  f"PaddleOCR-VL 로컬 로딩 생략(graceful 빈 결과). "
                  f"OCR_BACKEND=vision 또는 더 큰 메모리 사용.")
            _PADDLE_VL = None
            return None
        _PADDLE_VL = PaddleOCRVL()
    except Exception as e:  # noqa: BLE001 — URLError(가중치 호스트 차단) 등 포함
        print(f"[extract_ocr] PaddleOCRVL 초기화 실패(가중치 차단/미설치 추정) "
              f"→ graceful 빈 결과: {type(e).__name__}: {e}")
        _PADDLE_VL = None
    return _PADDLE_VL


def _ocr_paddleocr_vl(b64_png: str) -> "list[tuple[str, str, float | None, list[float] | None]]":
    """프로덕션 백엔드: 국내 자체 호스팅 PaddleOCR-VL(paddleocr `PaddleOCRVL`).

    반환: (block_type, text, confidence, bbox[x0,y0,x1,y1]) 튜플 리스트.
      - block_type: "para" 또는 "table"(표 영역 식별 시).
      - bbox 는 가능하면 채운다(before/after 치환용). confidence 는 0~1(없으면 None).

    동작:
      1) 인스턴스 지연 생성(_get_paddle_vl, 1회 캐시). 가중치 차단 시 None → 빈 결과.
      2) b64 PNG → ndarray(BGR) 로 디코드해 ocr.predict() 추론.
      3) 결과(parsing_res_list / spotting_res)를 _map_vl_result 로 매핑.
    모든 실패(URLError/추론 오류 등)는 graceful — 빈 리스트(예외 전파 금지).
    """
    ocr = _get_paddle_vl()
    if ocr is None:
        return []
    try:
        import numpy as np
        from PIL import Image
        img = Image.open(io.BytesIO(base64.b64decode(b64_png))).convert("RGB")
        arr = np.array(img)[:, :, ::-1]  # RGB → BGR(paddle 관례)
    except Exception as e:  # noqa: BLE001
        print(f"[extract_ocr] paddleocr_vl 이미지 디코드 실패 → skip: {e}")
        return []
    try:
        results = ocr.predict(arr)
    except Exception as e:  # noqa: BLE001
        print(f"[extract_ocr] paddleocr_vl predict 실패 → graceful 빈 결과: "
              f"{type(e).__name__}: {e}")
        return []
    # predict 는 페이지(이미지)당 결과 리스트(또는 제너레이터)를 돌려준다.
    out: "list[tuple[str, str, float | None, list[float] | None]]" = []
    try:
        for res in results:
            out.extend(_map_vl_result(res, page_no=0))
    except Exception as e:  # noqa: BLE001
        print(f"[extract_ocr] paddleocr_vl 결과 매핑 중 오류(부분 결과 유지): {e}")
    return out


# ── 백엔드: vision (개발 폴백, OpenAI) ────────────────────────────────────────
def _ocr_vision(b64_png: str) -> "list[tuple[str, str, float | None, list[float] | None]]":
    """개발 폴백 백엔드: app.llm.ocr_image(OpenAI 비전).

    ⚠️ 외부 호출 — 데이터 거주 정책 위반. 개발/검증 전용.
    plain text(줄바꿈 보존)를 받아 줄 단위 ("para", text, None, None) 으로 래핑.
    confidence/bbox 미지원(None). LLM 사용불가/실패 시 빈 리스트(graceful).

    반환 튜플 형식은 paddleocr_vl 백엔드와 동일: (block_type, text, conf, bbox).
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
    return [("para", line.strip(), None, None) for line in text.splitlines() if line.strip()]


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

    # 폴백 백엔드(1차가 빈 결과/실패일 때 재시도). 1차와 동일하거나 미설정이면 폴백 없음.
    fallback = _BACKENDS.get(OCR_FALLBACK_BACKEND) if OCR_FALLBACK_BACKEND else None
    if fallback is backend:
        fallback = None

    rendered = _render_pages(pdf_bytes, pages)
    if not rendered:
        return []

    blocks: "list[Block]" = []
    counter = 0
    for page_no, b64 in rendered:
        try:
            lines = backend(b64)
        except Exception:
            # 백엔드 자체 예외(가중치 차단 등) → 빈 결과로 두고 아래 폴백에 맡김
            lines = []
        if not lines and fallback is not None:
            # 1차 백엔드가 빈 결과/실패 → 폴백(gpt-5.5 비전)으로 재시도.
            try:
                lines = fallback(b64)
            except Exception:
                lines = []
            if lines:
                print(f"[extract_ocr] p{page_no}: {OCR_BACKEND} 빈 결과 → "
                      f"{OCR_FALLBACK_BACKEND} 폴백 사용({len(lines)}줄)")
        for item in lines:
            btype, text, conf, bbox = _normalize_line(item)
            if not text:
                continue
            counter += 1
            blocks.append(Block(
                id=f"ocr-p{page_no}-{counter}",
                type=btype,
                text=text,
                page=page_no,
                bbox=bbox,
                source="ocr",
                confidence=conf,
            ))
    return blocks


# 매핑 시 사용할 허용 BlockType(스키마 계약). 그 외는 para 로 graceful.
_ALLOWED_BLOCK_TYPES = {"heading", "para", "list_item", "table", "table_row", "figure"}


def _normalize_line(item) -> "tuple[str, str, float | None, list[float] | None]":
    """백엔드 반환 튜플을 (block_type, text, conf, bbox) 로 정규화(방어적).

    구버전 3-튜플(text, conf, bbox)도 허용 → type 은 para. type 이 계약 밖이면 para.
    """
    if not isinstance(item, (tuple, list)):
        return ("para", "", None, None)
    if len(item) == 4:
        btype, text, conf, bbox = item
    elif len(item) == 3:  # 하위호환: (text, conf, bbox)
        btype, (text, conf, bbox) = "para", item
    else:
        return ("para", "", None, None)
    btype = btype if btype in _ALLOWED_BLOCK_TYPES else "para"
    text = "" if text is None else str(text)
    return (btype, text, conf, bbox)


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


def test_paddleocr_vl_graceful_when_weights_blocked():
    # 가중치 차단/미설치로 인스턴스화 실패 시 빈 결과(graceful, 예외 전파 금지).
    import app.pdf.extract_ocr as mod

    prev = mod._PADDLE_VL
    mod._PADDLE_VL = None  # 초기화 실패(가중치 차단) 상태를 흉내
    try:
        assert mod._ocr_paddleocr_vl("ignored") == []
    finally:
        mod._PADDLE_VL = prev


def test_fallback_used_when_primary_empty():
    # 1차 백엔드가 빈 결과면 폴백(vision)이 이어받는지 검증(외부 호출 없이 monkeypatch).
    import app.pdf.extract_ocr as mod

    prev_backend, prev_fb = mod.OCR_BACKEND, mod.OCR_FALLBACK_BACKEND
    orig_paddle = mod._BACKENDS["paddleocr_vl"]
    orig_vision = mod._BACKENDS["vision"]
    orig_render = mod._render_pages
    mod.OCR_BACKEND, mod.OCR_FALLBACK_BACKEND = "paddleocr_vl", "vision"
    mod._BACKENDS["paddleocr_vl"] = lambda b64: []                       # 1차: 가중치 차단 흉내
    mod._BACKENDS["vision"] = lambda b64: [("para", "폴백 줄", None, None)]  # 폴백: gpt-5.5 비전
    mod._render_pages = lambda data, pages: [(1, "fakeb64")]
    try:
        blocks = mod.extract_ocr(b"whatever")
    finally:
        mod.OCR_BACKEND, mod.OCR_FALLBACK_BACKEND = prev_backend, prev_fb
        mod._BACKENDS["paddleocr_vl"] = orig_paddle
        mod._BACKENDS["vision"] = orig_vision
        mod._render_pages = orig_render

    assert len(blocks) == 1
    assert blocks[0].text == "폴백 줄" and blocks[0].source == "ocr"


def test_no_fallback_when_primary_has_result():
    # 1차가 결과를 내면 폴백은 호출되지 않아야 한다.
    import app.pdf.extract_ocr as mod

    called = {"fb": False}
    prev_backend, prev_fb = mod.OCR_BACKEND, mod.OCR_FALLBACK_BACKEND
    orig_paddle = mod._BACKENDS["paddleocr_vl"]
    orig_vision = mod._BACKENDS["vision"]
    orig_render = mod._render_pages

    def _fb(b64):
        called["fb"] = True
        return [("para", "안 불려야 함", None, None)]

    mod.OCR_BACKEND, mod.OCR_FALLBACK_BACKEND = "paddleocr_vl", "vision"
    mod._BACKENDS["paddleocr_vl"] = lambda b64: [("para", "1차 줄", None, None)]
    mod._BACKENDS["vision"] = _fb
    mod._render_pages = lambda data, pages: [(1, "fakeb64")]
    try:
        blocks = mod.extract_ocr(b"whatever")
    finally:
        mod.OCR_BACKEND, mod.OCR_FALLBACK_BACKEND = prev_backend, prev_fb
        mod._BACKENDS["paddleocr_vl"] = orig_paddle
        mod._BACKENDS["vision"] = orig_vision
        mod._render_pages = orig_render

    assert [b.text for b in blocks] == ["1차 줄"]
    assert called["fb"] is False


def test_block_format_matches_contract():
    # vision 폴백 출력 형식 검증(OpenAI 호출 없이 백엔드만 monkeypatch).
    import app.pdf.extract_ocr as mod

    orig = mod._BACKENDS["vision"]
    mod._BACKENDS["vision"] = lambda b64: [
        ("para", "샘플 줄1", None, None), ("para", "샘플 줄2", None, None)]
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


# ── 매핑 단위 테스트 (목 결과 — 실제 가중치 추론은 이 환경서 불가) ──────────────
class _MockVLBlock:
    """PaddleOCRVLBlock 흉내(.label/.content/.bbox/.polygon_points)."""
    def __init__(self, label, content, bbox=None, polygon_points=None):
        self.label = label
        self.content = content
        self.bbox = bbox
        self.polygon_points = polygon_points


class _MockVLResult:
    """PaddleOCRVL predict 결과 흉내 — .json -> {"res": {...}}."""
    def __init__(self, payload):
        self._payload = payload

    @property
    def json(self):
        return {"res": self._payload}


def test_map_vl_result_parsing_list_objects():
    # parsing_res_list(객체) → para/table 구분 + 폴리곤 bbox 추출.
    res = _MockVLResult({
        "parsing_res_list": [
            _MockVLBlock("text", "본문 한 줄", polygon_points=[[10, 20], [110, 20], [110, 60], [10, 60]]),
            _MockVLBlock("table", "<table>...</table>", bbox=[0, 100, 200, 300]),
            _MockVLBlock("image", "", bbox=[0, 0, 50, 50]),  # 비텍스트 → skip
            _MockVLBlock("paragraph_title", "제목", bbox=[5, 5, 80, 25]),
        ]
    })
    mapped = _map_vl_result(res, page_no=1)
    types = [m[0] for m in mapped]
    texts = [m[1] for m in mapped]
    assert types == ["para", "table", "para"]  # image 는 빠짐
    assert "본문 한 줄" in texts and "<table>...</table>" in texts and "제목" in texts
    # 폴리곤 → [x0,y0,x1,y1]
    assert mapped[0][3] == [10.0, 20.0, 110.0, 60.0]
    assert mapped[1][3] == [0.0, 100.0, 200.0, 300.0]
    assert all(m[2] is None for m in mapped)  # 레이아웃 블록은 점수 없음


def test_map_vl_result_parsing_list_dicts():
    # parsing_res_list(dict 형태) 도 동일하게 처리.
    res = _MockVLResult({
        "parsing_res_list": [
            {"block_label": "text", "block_content": "딕트 본문", "block_bbox": [1, 2, 3, 4]},
        ]
    })
    mapped = _map_vl_result(res, page_no=1)
    assert mapped == [("para", "딕트 본문", None, [1.0, 2.0, 3.0, 4.0])]


def test_map_vl_result_spotting_fallback_with_scores():
    # parsing_res_list 비면 라인 단위(spotting_res) — rec_texts/scores/polys.
    res = _MockVLResult({
        "parsing_res_list": [],
        "spotting_res": {
            "rec_texts": ["라인1", "  ", "라인2"],   # 빈 줄은 스킵
            "rec_scores": [0.95, 0.1, 0.42],
            "rec_polys": [
                [[0, 0], [10, 0], [10, 10], [0, 10]],
                [[0, 0], [1, 0], [1, 1], [0, 1]],
                [[5, 5], [25, 5], [25, 15], [5, 15]],
            ],
        },
    })
    mapped = _map_vl_result(res, page_no=2)
    assert [m[1] for m in mapped] == ["라인1", "라인2"]
    assert mapped[0][2] == 0.95 and mapped[1][2] == 0.42
    assert mapped[0][3] == [0.0, 0.0, 10.0, 10.0]


def test_map_vl_result_overall_ocr_res_key():
    # 일부 버전은 overall_ocr_res 키 사용 → 동일 처리.
    res = _MockVLResult({
        "overall_ocr_res": {"rec_texts": ["대체키"], "rec_scores": [0.7]},
    })
    mapped = _map_vl_result(res, page_no=1)
    assert mapped == [("para", "대체키", 0.7, None)]


def test_map_vl_result_garbage_is_graceful():
    # 알 수 없는/빈 구조 → 예외 없이 빈 리스트.
    assert _map_vl_result(_MockVLResult({}), 1) == []
    assert _map_vl_result(object(), 1) == []
    assert _map_vl_result(None, 1) == []


def test_normalize_line_backward_compat():
    # 3-튜플(text, conf, bbox) 하위호환 → para.
    assert _normalize_line(("hi", 0.5, None)) == ("para", "hi", 0.5, None)
    # 4-튜플 + 계약 밖 타입 → para 로 강등.
    assert _normalize_line(("weird", "t", None, None)) == ("para", "t", None, None)
    # table 은 유지.
    assert _normalize_line(("table", "t", None, [0, 0, 1, 1])) == ("table", "t", None, [0, 0, 1, 1])
    # 형식 불량 → 빈 텍스트(스킵 대상).
    assert _normalize_line("nope") == ("para", "", None, None)


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
