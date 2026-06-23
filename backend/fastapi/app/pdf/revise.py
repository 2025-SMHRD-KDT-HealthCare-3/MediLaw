"""멀티에이전트 F — 치환 before/after (블록 단위 정밀 치환).

위험판정된 세그먼트(Segment.risk 채워짐)와 원본 Document(blocks)를 받아,
위험 블록의 텍스트만 risk.after 로 교체한 **수정 블록 집합**을 만든다.
구조(type/table_ref/bbox/row_index/page 등)는 그대로 보존하고 text 만 교체한다.

원칙:
- 평문 전체 문자열 replace 금지. Segment.block_ids 로 정확히 타겟팅.
- 표(table_row)도 셀 단위 텍스트 교체로 구조 유지(동일 메커니즘: text 만 교체).
- 같은 block_id 가 여러 세그먼트에 걸리면 위험도가 더 높은 것 우선,
  동률이면 나중(뒤) 세그먼트 우선.
"""
from typing import Optional

from app.pdf.schema import Document, Segment

# 위험도 정렬용 — 높을수록 우선
_LEVEL_RANK = {"none": 0, "low": 1, "med": 2, "high": 3}
# 실제 치환 대상이 되는 위험 수준
_RISKY_LEVELS = {"low", "med", "high"}


def _is_applicable(seg: Segment) -> bool:
    """치환을 적용할 세그먼트인지 — risk 존재 + 위험수준 + after 비어있지 않음."""
    risk = seg.risk
    if risk is None:
        return False
    if risk.level not in _RISKY_LEVELS:
        return False
    if not (risk.after or "").strip():
        return False
    return True


def _select_segment_per_block(segments: list[Segment]) -> dict:
    """block_id → 적용할 Segment 매핑.

    같은 block_id 가 여러 세그먼트에 걸리면 위험도 높은 것 우선,
    동률이면 나중에 나온(인덱스가 큰) 것 우선.
    """
    chosen: dict = {}  # block_id -> (rank, order_index, segment)
    for idx, seg in enumerate(segments):
        if not _is_applicable(seg):
            continue
        rank = _LEVEL_RANK.get(seg.risk.level, 0)
        for bid in seg.block_ids:
            prev = chosen.get(bid)
            # 더 높은 위험도이거나, 동률이면 더 나중 세그먼트가 이긴다.
            if prev is None or (rank, idx) >= (prev[0], prev[1]):
                chosen[bid] = (rank, idx, seg)
    return {bid: val[2] for bid, val in chosen.items()}


def apply_revisions(document: Document, segments: list[Segment]) -> dict:
    """위험 블록만 after 로 치환한 before/after 표현을 만든다.

    반환 dict:
      - blocks_before: 원본 Block dump 리스트
      - blocks_after:  text 만 교체된 Block dump 리스트(구조 보존)
      - changes:       변경 목록 [{block_id, page, before, after, level, law, reason}]
    """
    block_to_seg = _select_segment_per_block(segments)

    blocks_before: list[dict] = []
    blocks_after: list[dict] = []
    changes: list[dict] = []

    for block in document.blocks:
        before_dump = block.model_dump()
        blocks_before.append(before_dump)

        seg = block_to_seg.get(block.id)
        if seg is None:
            # 위험 없는 블록 — 원문 그대로 유지.
            blocks_after.append(block.model_dump())
            continue

        # 구조 보존: text 만 교체한 복사본 생성.
        risk = seg.risk
        after_text = risk.after
        after_dump = block.model_dump()
        before_text = after_dump.get("text", "")
        after_dump["text"] = after_text
        blocks_after.append(after_dump)

        changes.append({
            "block_id": block.id,
            "page": block.page,
            "before": before_text,
            "after": after_text,
            "level": risk.level,
            "law": list(risk.law),
            "reason": risk.reason,
        })

    return {
        "blocks_before": blocks_before,
        "blocks_after": blocks_after,
        "changes": changes,
    }


# --------------------------------------------------------------------------
# 자체 검증 — 상류(A~E) 없이 목 Document/Segment 로 계약 대상 검증.
# --------------------------------------------------------------------------
def _mock_document() -> Document:
    from app.pdf.schema import Block
    return Document(
        doc_id="d1", doc_type="ad", page_count=1,
        blocks=[
            Block(id="b1", type="para",
                  text="부작용이 전혀 없는 100% 안전한 시술", page=1, source="digital"),
            Block(id="b2", type="para",
                  text="국내 최초 무통증 치료", page=1, source="digital"),
            Block(id="b3", type="para",
                  text="진료시간 09-18시", page=1, source="digital"),
        ],
    )


def _mock_table_document() -> Document:
    from app.pdf.schema import Block
    return Document(
        doc_id="d2", doc_type="ad", page_count=1,
        blocks=[
            Block(id="t1", type="table", text="", page=1, source="digital"),
            Block(id="t1r0", type="table_row", text="항목 | 효과",
                  page=1, source="digital", table_ref="t1", row_index=0),
            Block(id="t1r1", type="table_row", text="시술 | 100% 완치 보장",
                  page=1, source="digital", table_ref="t1", row_index=1),
        ],
    )


def test_basic_revision():
    from app.pdf.schema import RiskResult
    doc = _mock_document()
    segs = [
        Segment(seg_id="s1", block_ids=["b1"],
                text="부작용이 전혀 없는 100% 안전한 시술",
                risk=RiskResult(level="high", law=["의료광고 가이드라인"],
                                reason="절대안전 단정",
                                before="부작용이 전혀 없는 100% 안전한 시술",
                                after="시술 전 부작용 가능성을 안내합니다")),
        Segment(seg_id="s3", block_ids=["b3"], text="진료시간 09-18시", risk=None),
    ]
    out = apply_revisions(doc, segs)
    after_map = {b["id"]: b["text"] for b in out["blocks_after"]}
    assert after_map["b1"] == "시술 전 부작용 가능성을 안내합니다"
    assert after_map["b3"] == "진료시간 09-18시"  # 비위험 원문 유지
    assert after_map["b2"] == "국내 최초 무통증 치료"  # risk 없는 블록 유지
    assert len(out["blocks_after"]) == len(doc.blocks)  # 구조 보존
    assert len(out["changes"]) == 1
    assert out["changes"][0]["block_id"] == "b1"
    assert out["changes"][0]["level"] == "high"


def test_structure_preserved():
    """치환 후에도 type/bbox/source 등 구조 필드가 보존되는지."""
    from app.pdf.schema import RiskResult
    doc = _mock_table_document()
    segs = [
        Segment(seg_id="s1", block_ids=["t1r1"], text="시술 | 100% 완치 보장",
                risk=RiskResult(level="high", law=["의료광고법"], reason="완치 보장 과장",
                                before="시술 | 100% 완치 보장",
                                after="시술 | 치료 효과는 개인차가 있습니다")),
    ]
    out = apply_revisions(doc, segs)
    after = {b["id"]: b for b in out["blocks_after"]}
    # text 교체 확인
    assert after["t1r1"]["text"] == "시술 | 치료 효과는 개인차가 있습니다"
    # 구조 보존 확인
    assert after["t1r1"]["type"] == "table_row"
    assert after["t1r1"]["table_ref"] == "t1"
    assert after["t1r1"]["row_index"] == 1
    # 헤더 행/테이블 컨테이너 유지
    assert after["t1r0"]["text"] == "항목 | 효과"
    assert after["t1"]["type"] == "table"


def test_empty_after_not_applied():
    """after 가 비어있으면 위험이어도 치환하지 않는다."""
    from app.pdf.schema import RiskResult
    doc = _mock_document()
    segs = [
        Segment(seg_id="s1", block_ids=["b1"], text="x",
                risk=RiskResult(level="high", law=["g"], reason="r", before="x", after="")),
    ]
    out = apply_revisions(doc, segs)
    after_map = {b["id"]: b["text"] for b in out["blocks_after"]}
    assert after_map["b1"] == "부작용이 전혀 없는 100% 안전한 시술"  # 원문 유지
    assert len(out["changes"]) == 0


def test_none_level_not_applied():
    """level=none 은 치환하지 않는다."""
    from app.pdf.schema import RiskResult
    doc = _mock_document()
    segs = [
        Segment(seg_id="s1", block_ids=["b1"], text="x",
                risk=RiskResult(level="none", after="바뀌면안됨")),
    ]
    out = apply_revisions(doc, segs)
    after_map = {b["id"]: b["text"] for b in out["blocks_after"]}
    assert after_map["b1"] == "부작용이 전혀 없는 100% 안전한 시술"
    assert len(out["changes"]) == 0


def test_conflict_highest_risk_wins():
    """같은 block_id 가 여러 세그먼트에 걸리면 위험도 높은 것 우선."""
    from app.pdf.schema import RiskResult
    doc = _mock_document()
    segs = [
        Segment(seg_id="s1", block_ids=["b1"], text="x",
                risk=RiskResult(level="low", after="낮은위험치환")),
        Segment(seg_id="s2", block_ids=["b1"], text="x",
                risk=RiskResult(level="high", after="높은위험치환")),
    ]
    out = apply_revisions(doc, segs)
    after_map = {b["id"]: b["text"] for b in out["blocks_after"]}
    assert after_map["b1"] == "높은위험치환"
    assert len(out["changes"]) == 1
    assert out["changes"][0]["level"] == "high"


def test_conflict_same_level_later_wins():
    """동률 위험도면 나중 세그먼트 우선."""
    from app.pdf.schema import RiskResult
    doc = _mock_document()
    segs = [
        Segment(seg_id="s1", block_ids=["b1"], text="x",
                risk=RiskResult(level="med", after="먼저")),
        Segment(seg_id="s2", block_ids=["b1"], text="x",
                risk=RiskResult(level="med", after="나중")),
    ]
    out = apply_revisions(doc, segs)
    after_map = {b["id"]: b["text"] for b in out["blocks_after"]}
    assert after_map["b1"] == "나중"


def test_multi_block_segment():
    """한 세그먼트가 여러 block_ids 를 가지면 모두 치환된다."""
    from app.pdf.schema import RiskResult
    doc = _mock_document()
    segs = [
        Segment(seg_id="s1", block_ids=["b1", "b2"], text="x",
                risk=RiskResult(level="high", after="합쳐서치환")),
    ]
    out = apply_revisions(doc, segs)
    after_map = {b["id"]: b["text"] for b in out["blocks_after"]}
    assert after_map["b1"] == "합쳐서치환"
    assert after_map["b2"] == "합쳐서치환"
    assert len(out["changes"]) == 2


if __name__ == "__main__":
    test_basic_revision()
    test_structure_preserved()
    test_empty_after_not_applied()
    test_none_level_not_applied()
    test_conflict_highest_risk_wins()
    test_conflict_same_level_later_wins()
    test_multi_block_segment()
    print("all tests OK")
