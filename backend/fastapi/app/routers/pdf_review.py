"""멀티에이전트 G — 새 PDF 파이프라인 HTTP 엔드포인트 + 페이지별 SSE 스트리밍.

신버전 PDF 파이프라인(app/pdf/pipeline.py)을 HTTP로 노출한다. 구버전
/documents/review(app/routers/documents.py)와 공존한다(건드리지 않음).

POST /pdf/review        : PDF 업로드 → 위험검토 결과 JSON 한 번에.
POST /pdf/review/stream : 페이지별 점진 노출 SSE
    routes → page(페이지별 segments/changes) … → done(요약).

라우팅(route_pages)은 한 번만 수행하고, 이후 페이지별로 process_pdf(pages=[n]) 를
호출해 페이지 결과를 흘려보낸다(구현 단순화 + 점진 노출).

LLM(위험판정)은 OPENAI_API_KEY 필요 — 없으면 추출/세그먼트까지는 동작하고 판정은
graceful 하게 비어 나온다(파이프라인이 흡수). 디지털 PDF 는 OCR 없이 동작.
"""
import json
import os
import sys
from typing import Optional

# 단독 러너(__main__)에서도 `from app...` import 가 되도록 프로젝트 루트를 path 에 추가.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import StreamingResponse

from app.auth import require_api_key
from app.pdf import routing
from app.pdf.pipeline import process_pdf

router = APIRouter(prefix="/pdf", tags=["능동형 PDF 에디터(신 파이프라인)"])

# 위험으로 집계할 수준(none 제외).
_RISKY_LEVELS = {"low", "med", "high"}


def _parse_pages(pages: Optional[str]) -> Optional[list[int]]:
    """쉼표구분 페이지 문자열("2,3") → [2,3]. 빈 값/None → None(전체)."""
    if not pages or not pages.strip():
        return None
    out: list[int] = []
    for tok in pages.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            n = int(tok)
        except ValueError as e:
            raise HTTPException(400, f"pages 는 쉼표구분 정수여야 합니다: {tok!r}") from e
        if n >= 1:
            out.append(n)
    return out or None


def _seg_dump(seg) -> dict:
    """Segment → 응답 dict. risk(판정) 포함, 없으면 risk=None."""
    return {
        "seg_id": seg.seg_id,
        "block_ids": list(seg.block_ids),
        "text": seg.text,
        "doc_type": seg.doc_type,
        "risk": seg.risk.model_dump() if seg.risk is not None else None,
    }


def _is_risky(seg) -> bool:
    return seg.risk is not None and seg.risk.level in _RISKY_LEVELS


def _result_json(result: dict) -> dict:
    """process_pdf 결과(dict) → 직렬화 가능한 응답 dict."""
    doc = result["document"]
    segs = result["segments"]
    revisions = result["revisions"]
    routes = result["routes"]
    risky = [s for s in segs if _is_risky(s)]
    return {
        "document": {
            "doc_id": doc.doc_id,
            "doc_type": doc.doc_type,
            "page_count": doc.page_count,
            "status": doc.status,
            "blocks": [b.model_dump() for b in doc.blocks],
        },
        "routes": [{"page": r.page, "route": r.route} for r in routes],
        "segments": [_seg_dump(s) for s in segs],
        "revisions": revisions,
        "summary": {
            "risky": len(risky),
            "changes": len(revisions.get("changes", [])),
            "page_count": doc.page_count,
        },
    }


def _review_bytes(
    pdf_bytes: bytes,
    doc_id: str = "doc",
    doc_type: Optional[str] = None,
    as_of: Optional[str] = None,
    top_k: int = 4,
    pages: Optional[list[int]] = None,
    ocr: bool = True,
) -> dict:
    """UploadFile 없이 bytes 로 한 번에 검토(엔드포인트·테스트 공용 헬퍼)."""
    if not pdf_bytes:
        raise HTTPException(400, "빈 파일입니다(PDF 바이트 없음).")
    result = process_pdf(
        pdf_bytes, doc_id=doc_id, doc_type=doc_type, as_of=as_of,
        top_k=top_k, pages=pages, ocr=ocr,
    )
    return _result_json(result)


@router.post("/review", dependencies=[Depends(require_api_key)])
async def review(
    file: UploadFile = File(..., description="검토할 PDF 파일"),
    doc_type: Optional[str] = Form(default=None, description="ad|consent|privacy_policy|terms"),
    as_of: Optional[str] = Form(default=None),
    top_k: int = Form(default=4),
    pages: Optional[str] = Form(default=None, description="쉼표구분 1-based 페이지(예: '2,3'). 비우면 전체"),
    ocr: bool = Form(default=True),
):
    """PDF 업로드 → 신 파이프라인으로 위험검토 결과를 JSON 한 번에 반환."""
    pdf_bytes = await file.read()
    page_list = _parse_pages(pages)
    top_k = max(1, min(8, top_k))
    doc_id = (file.filename or "doc").rsplit("/", 1)[-1]
    return _review_bytes(
        pdf_bytes, doc_id=doc_id, doc_type=doc_type, as_of=as_of,
        top_k=top_k, pages=page_list, ocr=ocr,
    )


def _sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def _stream_gen(
    pdf_bytes: bytes,
    doc_id: str = "doc",
    doc_type: Optional[str] = None,
    as_of: Optional[str] = None,
    top_k: int = 4,
    pages: Optional[list[int]] = None,
    ocr: bool = True,
):
    """페이지별 점진 노출 SSE 제너레이터(엔드포인트·테스트 공용).

    이벤트 순서:
      routes → page(페이지마다) … → done
    """
    if not pdf_bytes:
        yield _sse({"type": "error", "message": "빈 파일입니다(PDF 바이트 없음)."})
        return

    # 1) 페이지 라우팅은 한 번만.
    all_routes = routing.route_pages(pdf_bytes)
    if pages is not None:
        all_routes = [r for r in all_routes if r.page in pages]

    if not all_routes:
        yield _sse({"type": "routes", "pages": []})
        yield _sse({"type": "done", "status": "reviewed",
                    "summary": {"risky": 0, "changes": 0, "page_count": 0}})
        return

    yield _sse({
        "type": "routes",
        "pages": [{"page": r.page, "route": r.route} for r in all_routes],
    })

    page_nums = [r.page for r in all_routes]
    total = len(page_nums)
    total_risky = 0
    total_changes = 0

    # 2) 페이지별로 process_pdf(pages=[n]) — 추출→세그먼트→판정→치환을 페이지 단위로.
    for i, page in enumerate(page_nums, 1):
        try:
            result = process_pdf(
                pdf_bytes, doc_id=doc_id, doc_type=doc_type, as_of=as_of,
                top_k=top_k, pages=[page], ocr=ocr,
            )
        except Exception as e:  # noqa: BLE001 — 한 페이지 실패가 전체를 끊지 않게.
            yield _sse({"type": "error", "page": page, "message": str(e),
                        "progress": f"{i}/{total}"})
            continue

        segs = result["segments"]
        changes = result["revisions"].get("changes", [])
        risky = [s for s in segs if _is_risky(s)]
        total_risky += len(risky)
        total_changes += len(changes)

        yield _sse({
            "type": "page",
            "page": page,
            "progress": f"{i}/{total}",
            "status": "processing",
            "segments": [_seg_dump(s) for s in segs],
            "changes": changes,
        })

    # 3) 완료.
    yield _sse({
        "type": "done",
        "status": "reviewed",
        "summary": {"risky": total_risky, "changes": total_changes, "page_count": total},
    })


@router.post("/review/stream", dependencies=[Depends(require_api_key)])
async def review_stream(
    file: UploadFile = File(..., description="검토할 PDF 파일"),
    doc_type: Optional[str] = Form(default=None, description="ad|consent|privacy_policy|terms"),
    as_of: Optional[str] = Form(default=None),
    top_k: int = Form(default=4),
    pages: Optional[str] = Form(default=None, description="쉼표구분 1-based 페이지(예: '2,3'). 비우면 전체"),
    ocr: bool = Form(default=True),
):
    """PDF 업로드 → 페이지별 점진 노출 SSE(routes → page… → done)."""
    pdf_bytes = await file.read()
    page_list = _parse_pages(pages)
    top_k = max(1, min(8, top_k))
    doc_id = (file.filename or "doc").rsplit("/", 1)[-1]
    return StreamingResponse(
        _stream_gen(pdf_bytes, doc_id=doc_id, doc_type=doc_type, as_of=as_of,
                    top_k=top_k, pages=page_list, ocr=ocr),
        media_type="text/event-stream",
    )


# ─────────────────────────── 자체 검증(pytest + __main__) ───────────────────────────
_SAMPLE_PDF = "기획서(최종 수정 중 ).pdf"


def _sample_pdf_bytes():
    """프로젝트 루트의 샘플 기획서 PDF(디지털)를 읽어 반환. 없으면 None."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(root, _SAMPLE_PDF)
    if not os.path.exists(path):
        if os.path.exists(_SAMPLE_PDF):
            path = _SAMPLE_PDF
        else:
            return None
    with open(path, "rb") as f:
        return f.read()


def _parse_sse(raw: str) -> list[dict]:
    """raw SSE 문자열 → 이벤트 dict 리스트."""
    events = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        assert block.startswith("data: "), f"SSE 라인이 'data: '로 시작하지 않음: {block!r}"
        events.append(json.loads(block[len("data: "):]))
    return events


def _collect_stream(**kw) -> tuple[str, list[dict]]:
    """_stream_gen 을 끝까지 모아 (raw, events) 반환(동기 제너레이터)."""
    raw = "".join(_stream_gen(**kw))
    return raw, _parse_sse(raw)


def test_parse_pages():
    assert _parse_pages(None) is None
    assert _parse_pages("") is None
    assert _parse_pages("2") == [2]
    assert _parse_pages("2, 3 ,4") == [2, 3, 4]


def test_router_routes_present():
    paths = [r.path for r in router.routes]
    assert "/pdf/review" in paths
    assert "/pdf/review/stream" in paths


def test_empty_bytes_stream_errors():
    raw, events = _collect_stream(pdf_bytes=b"")
    assert events and events[0]["type"] == "error"


def test_stream_event_order_digital_p2():
    """디지털 샘플 PDF p2 — routes → page → done 순서, 블록/세그먼트 잡힘."""
    sample = _sample_pdf_bytes()
    if sample is None:
        return  # 샘플 없으면 스킵
    raw, events = _collect_stream(pdf_bytes=sample, pages=[2])
    assert events, "이벤트가 하나도 없음"
    assert events[0]["type"] == "routes", f"첫 이벤트 type={events[0]['type']!r}"
    assert events[-1]["type"] == "done", f"마지막 이벤트 type={events[-1]['type']!r}"
    # 중간엔 page 이벤트가 최소 1개(에러 제외).
    page_events = [e for e in events if e["type"] == "page"]
    assert page_events, "page 이벤트가 없음"
    # done 요약 키 존재.
    summary = events[-1]["summary"]
    for k in ("risky", "changes", "page_count"):
        assert k in summary, f"done.summary 에 {k!r} 키 없음"


def test_review_bytes_json_shape():
    """한 번에 JSON — 디지털 p2 에서 document.blocks/segments 잡힘(LLM 없어도 추출까지)."""
    sample = _sample_pdf_bytes()
    if sample is None:
        return
    out = _review_bytes(sample, pages=[2])
    assert "document" in out and "segments" in out and "revisions" in out
    assert "summary" in out
    assert out["document"]["page_count"] >= 1
    # 디지털 p2 면 블록이 잡혀야(추출은 LLM 불필요).
    assert out["document"]["blocks"], "디지털 p2 에서 블록이 잡혀야"


def _run():
    passed = total = 0

    def _check(label, fn):
        nonlocal passed, total
        total += 1
        try:
            fn()
            passed += 1
            print(f"  [OK ] {label}")
        except AssertionError as e:
            print(f"  [FAIL] {label} :: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  [ERR ] {label} :: {type(e).__name__}: {e}")

    print("── 결정론(LLM 불필요) ──")
    _check("_parse_pages", test_parse_pages)
    _check("router 라우트 등록", test_router_routes_present)
    _check("빈 바이트 스트림 error", test_empty_bytes_stream_errors)

    print("\n── 샘플 PDF(디지털 p2) ──")
    if _sample_pdf_bytes() is None:
        print(f"  (샘플 PDF '{_SAMPLE_PDF}' 없음 — 스킵)")
    else:
        _check("스트림 routes→page→done 순서", test_stream_event_order_digital_p2)
        _check("JSON 응답 shape(blocks/segments)", test_review_bytes_json_shape)

    print(f"\n  {passed}/{total} passed")


if __name__ == "__main__":
    _run()
