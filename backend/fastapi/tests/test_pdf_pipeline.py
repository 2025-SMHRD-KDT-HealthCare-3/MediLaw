"""PDF 파이프라인(app/pdf/*) 회귀 테스트.

두 계층:
  (A) 결정론(LLM 불필요)   : routing / extract / segment / revise / pipeline 비-LLM 경로.
                            항상 실행. OPENAI_API_KEY 없어도 전부 PASS.
  (B) LLM·엔드포인트 스모크 : review_segments 위험판정 + SSE 엔드포인트.
                            OPENAI_API_KEY 없으면 skip(메시지 출력).

데이터 변동에 견고하도록 특정 블록 수를 하드코딩하지 않고 구조/관계로 단언한다.

실행:
  pytest tests/test_pdf_pipeline.py
  python tests/test_pdf_pipeline.py          # 단독 러너(요약 출력)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.pdf import extract_digital, pipeline, revise, routing, segment  # noqa: E402,F401
from app.pdf.schema import (  # noqa: E402
    Block,
    Document,
    RiskResult,
    Segment,
)

# ── 샘플 PDF(디지털, 21p, 표 있음) ─────────────────────────────────────────────
_SAMPLE_PDF = "기획서(최종 수정 중 ).pdf"
_BLOCK_TYPES = {"heading", "para", "list_item", "table", "table_row", "figure"}
_HAS_KEY = bool(os.environ.get("OPENAI_API_KEY"))


def _sample_pdf_bytes():
    """프로젝트 루트의 샘플 기획서 PDF(디지털)를 읽어 반환. 없으면 None."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, _SAMPLE_PDF)
    if not os.path.exists(path):
        if os.path.exists(_SAMPLE_PDF):
            path = _SAMPLE_PDF
        else:
            return None
    with open(path, "rb") as f:
        return f.read()


# ─────────────────────────────────────────────────────────────────────────────
# (A) 결정론 — 항상 실행
# ─────────────────────────────────────────────────────────────────────────────
def test_routing_digital_pdf():
    """1. routing: 페이지>0, 모든 route in {digital,scan}, 최소 1개 digital."""
    sample = _sample_pdf_bytes()
    if sample is None:
        return  # 샘플 없으면 스킵(graceful)
    routes = routing.route_pages(sample)
    assert routes, "샘플 PDF 라우팅 결과가 비어있음"
    assert all(r.route in ("digital", "scan") for r in routes), \
        "route 는 digital/scan 중 하나여야"
    assert any(r.route == "digital" for r in routes), \
        "디지털 PDF 면 최소 1개 digital 페이지가 잡혀야"
    # 1-based 연속 페이지 번호 보존.
    assert [r.page for r in routes] == list(range(1, len(routes) + 1))


def test_extract_digital_specific_pages():
    """2. extract_digital(pages=[2,8]): blocks>0, 전부 digital, page in {2,8}, type 유효."""
    sample = _sample_pdf_bytes()
    if sample is None:
        return
    blocks = extract_digital.extract_digital(sample, pages=[2, 8])
    assert blocks, "p2,p8 에서 블록이 잡혀야(디지털 추출은 LLM 불필요)"
    assert all(b.source == "digital" for b in blocks), "디지털 추출은 source=digital"
    assert all(b.page in (2, 8) for b in blocks), "지정 페이지(2,8) 외 블록이 섞이면 안 됨"
    assert all(b.type in _BLOCK_TYPES for b in blocks), "type 은 계약 집합 내여야"
    # 표가 있는 문서이므로 table/table_row 가 보이면 table_ref 연결을 느슨히 확인.
    rows = [b for b in blocks if b.type == "table_row"]
    for r in rows:
        assert r.table_ref, "table_row 는 소속 table id(table_ref)를 가져야"


def test_segment_excludes_and_keeps():
    """3. segment(목 Block): table/figure 제외, table_row 각각 세그먼트,
    페이지번호/짧은 블록 제외, doc_type 전달."""
    blocks = [
        Block(id="b1", type="heading", text="개인정보 수집 동의", page=1, source="digital"),
        Block(id="b2", type="para", text="회사는 아래 항목을 수집합니다.", page=1, source="digital"),
        Block(id="t1", type="table", text="", page=1, source="digital"),
        Block(id="t1-r0", type="table_row", text="수집항목 | 이름, 연락처", page=1,
              source="digital", table_ref="t1", row_index=0),
        Block(id="t1-r1", type="table_row", text="보유기간 | 5년 보관", page=1,
              source="digital", table_ref="t1", row_index=1),
        Block(id="f1", type="figure", text="", page=1, source="digital"),
        Block(id="pn", type="para", text="- 1 -", page=1, source="digital"),
        Block(id="sh", type="para", text="짧음", page=1, source="digital"),  # < MIN_SEG_LEN
    ]
    segs = segment.to_segments(blocks, doc_type="consent")
    ids = {bid for s in segs for bid in s.block_ids}
    # 제외돼야 하는 것들.
    assert "t1" not in ids, "table 컨테이너 제외"
    assert "f1" not in ids, "figure 제외"
    assert "pn" not in ids, "페이지번호 제외"
    assert "sh" not in ids, "짧은 블록 제외"
    # 유지돼야 하는 것들(table_row 는 각각 세그먼트).
    assert "t1-r0" in ids and "t1-r1" in ids, "표는 행 단위로 각각 세그먼트"
    assert "b1" in ids and "b2" in ids, "heading/para 유지"
    # doc_type 전달 + 1블록=1세그먼트(block_ids 길이 1).
    assert all(s.doc_type == "consent" for s in segs)
    assert all(len(s.block_ids) == 1 for s in segs)


def test_revise_mock_document():
    """4. revise(목 Document+Segment): 위험(after有)은 치환, 비위험/None은 원문 유지,
    blocks_after 개수==원본, 구조(type/table_ref) 보존."""
    doc = Document(
        doc_id="d1", doc_type="ad", page_count=1,
        blocks=[
            Block(id="b1", type="para", text="부작용이 전혀 없는 100% 안전한 시술",
                  page=1, source="digital"),
            Block(id="b2", type="para", text="국내 최초 무통증 치료", page=1, source="digital"),
            Block(id="t1r1", type="table_row", text="시술 | 100% 완치 보장", page=1,
                  source="digital", table_ref="t1", row_index=1),
        ],
    )
    segs = [
        # 위험(after 있음) → 치환.
        Segment(seg_id="s1", block_ids=["b1"],
                text="부작용이 전혀 없는 100% 안전한 시술",
                risk=RiskResult(level="high", law=["의료광고 가이드라인"],
                                reason="절대안전 단정",
                                before="부작용이 전혀 없는 100% 안전한 시술",
                                after="시술 전 부작용 가능성을 안내합니다")),
        # 비위험(risk=None) → 원문 유지.
        Segment(seg_id="s2", block_ids=["b2"], text="국내 최초 무통증 치료", risk=None),
        # 표 행 치환(구조 보존 확인용).
        Segment(seg_id="s3", block_ids=["t1r1"], text="시술 | 100% 완치 보장",
                risk=RiskResult(level="med", law=["의료광고법"], reason="완치 보장 과장",
                                before="시술 | 100% 완치 보장",
                                after="시술 | 치료 효과는 개인차가 있습니다")),
    ]
    out = revise.apply_revisions(doc, segs)
    assert {"blocks_before", "blocks_after", "changes"} <= set(out.keys())
    assert len(out["blocks_after"]) == len(doc.blocks), "blocks_after 개수==원본"
    assert len(out["blocks_before"]) == len(doc.blocks)

    after = {b["id"]: b for b in out["blocks_after"]}
    assert after["b1"]["text"] == "시술 전 부작용 가능성을 안내합니다", "위험 세그먼트 치환"
    assert after["b2"]["text"] == "국내 최초 무통증 치료", "비위험(None) 원문 유지"
    assert after["t1r1"]["text"] == "시술 | 치료 효과는 개인차가 있습니다", "표 행 치환"
    # 구조(type/table_ref/row_index) 보존.
    assert after["t1r1"]["type"] == "table_row"
    assert after["t1r1"]["table_ref"] == "t1"
    assert after["t1r1"]["row_index"] == 1
    # changes 는 치환된 2건(b1, t1r1)만.
    changed_ids = {c["block_id"] for c in out["changes"]}
    assert changed_ids == {"b1", "t1r1"}


def test_pipeline_non_llm_path():
    """5. pipeline 비-LLM 경로: process_pdf(pages=[2], ocr=False) →
    document.blocks>0, segments>0, revisions 키 존재. (위험판정 0 허용.)"""
    sample = _sample_pdf_bytes()
    if sample is None:
        return
    result = pipeline.process_pdf(sample, pages=[2], ocr=False)
    assert {"document", "routes", "segments", "revisions"} <= set(result.keys())
    doc = result["document"]
    assert doc.blocks, "디지털 p2 에서 document.blocks 가 잡혀야"
    assert result["segments"], "세그먼트가 잡혀야"
    revisions = result["revisions"]
    assert {"blocks_before", "blocks_after", "changes"} <= set(revisions.keys())
    # 위험판정은 LLM 없으면 graceful — changes 0 허용.
    assert isinstance(revisions["changes"], list)
    # before/after 블록 개수는 일치(구조 보존).
    assert len(revisions["blocks_before"]) == len(revisions["blocks_after"])


# ─────────────────────────────────────────────────────────────────────────────
# (B) LLM·엔드포인트 스모크 — OPENAI_API_KEY 가드(없으면 skip)
# ─────────────────────────────────────────────────────────────────────────────
def test_review_segments_smoke():
    """6. review: 광고 과장 목 세그먼트 → risk.level in {low,med,high} 하나 이상."""
    if not _HAS_KEY:
        return  # 키 없으면 skip
    from app.pdf.review import review_segments

    segs = [
        Segment(seg_id="s1", block_ids=["b1"],
                text="부작용이 전혀 없는 100% 안전한 시술", doc_type="ad"),
    ]
    out = review_segments(segs)
    risky = [s for s in out if s.risk and s.risk.level in ("low", "med", "high")]
    assert risky, "광고 과장 문구가 위험(low/med/high)으로 잡혀야"


def test_endpoint_sse_event_order():
    """7. 엔드포인트 SSE: 기획서 p2 → 이벤트 type 순서 routes → page → done."""
    if not _HAS_KEY:
        return  # 엔드포인트 스모크도 LLM 가드(없으면 skip)
    sample = _sample_pdf_bytes()
    if sample is None:
        return
    from app.routers.pdf_review import _stream_gen

    raw = "".join(_stream_gen(sample, pages=[2]))
    events = []
    for blk in raw.split("\n\n"):
        blk = blk.strip()
        if not blk:
            continue
        assert blk.startswith("data: "), f"SSE 라인이 'data: '로 시작 안 함: {blk!r}"
        import json
        events.append(json.loads(blk[len("data: "):]))
    assert events, "SSE 이벤트가 하나도 없음"
    assert events[0]["type"] == "routes", f"첫 이벤트 type={events[0]['type']!r}"
    assert events[-1]["type"] == "done", f"마지막 이벤트 type={events[-1]['type']!r}"
    assert any(e["type"] == "page" for e in events), "page 이벤트가 최소 1개여야"


def test_ocr_vision_path_smoke():
    """8. OCR 경로: 이미지전용(스캔본) PDF → 라우팅 scan → 비전 OCR(gpt-5.5) → Block[].

    PaddleOCR-VL은 가중치 차단 환경에서 미동작하므로, 기본 백엔드(vision)로 OCR 분기를
    실측한다(거주 정책은 추후 — 챗봇과 동일하게 외부 LLM 사용).
    """
    if not _HAS_KEY:
        return  # OCR(vision)는 LLM 필요
    sample = _sample_pdf_bytes()
    if sample is None:
        return
    try:
        import io

        import pypdfium2 as pdfium
    except ImportError:
        return
    # 기획서 p1을 렌더해 텍스트 레이어 없는 이미지전용 PDF(스캔본) 생성
    img = pdfium.PdfDocument(sample)[0].render(scale=2.0).to_pil().convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "PDF")
    scanned = buf.getvalue()

    from app.pdf.routing import route_pages

    routes = route_pages(scanned)
    assert routes and routes[0].route == "scan", "이미지전용 PDF는 scan으로 라우팅돼야"

    from app.pdf.pipeline import process_pdf

    r = process_pdf(scanned, doc_id="scanned", top_k=4)
    ocr_blocks = [b for b in r["document"].blocks if b.source == "ocr"]
    assert ocr_blocks, "비전 OCR이 블록을 추출해야"
    assert any(b.text.strip() for b in ocr_blocks), "추출 텍스트가 비어있지 않아야"


# ─────────────────────────────────────────────────────────────────────────────
# 단독 러너 — python tests/test_pdf_pipeline.py
# ─────────────────────────────────────────────────────────────────────────────
_DETERMINISTIC = [
    ("routing (digital PDF)", test_routing_digital_pdf),
    ("extract_digital (p2,p8)", test_extract_digital_specific_pages),
    ("segment (목 Block 제외/유지)", test_segment_excludes_and_keeps),
    ("revise (목 Document 치환/보존)", test_revise_mock_document),
    ("pipeline (비-LLM p2)", test_pipeline_non_llm_path),
]
_LLM = [
    ("review_segments (광고 위험판정)", test_review_segments_smoke),
    ("endpoint SSE (routes→page→done)", test_endpoint_sse_event_order),
    ("OCR 비전 경로 (스캔본→Block)", test_ocr_vision_path_smoke),
]


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

    if _sample_pdf_bytes() is None:
        print(f"(주의: 샘플 PDF '{_SAMPLE_PDF}' 없음 — PDF 의존 케이스는 graceful 스킵)")

    print("── (A) 결정론(LLM 불필요) ──")
    for label, fn in _DETERMINISTIC:
        _check(label, fn)
    print(f"\n  결정론 {passed}/{total} passed")

    print("\n── (B) LLM·엔드포인트 스모크 ──")
    if not _HAS_KEY:
        print("  (OPENAI_API_KEY 없음 — LLM/엔드포인트 스모크 skip)")
    else:
        for label, fn in _LLM:
            _check(label, fn)


if __name__ == "__main__":
    _run()
