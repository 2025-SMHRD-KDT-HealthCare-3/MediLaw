"""세그먼트 단계(멀티에이전트 D) — 정규화된 Block[] → Segment[].

규칙 요약:
  - table 컨테이너 블록은 세그먼트로 만들지 않는다(요약일 뿐).
  - table_row 는 각각 1세그먼트(표는 행 단위).
  - figure 는 제외.
  - heading / para / list_item 은 각각 1세그먼트.
  - 무의미 블록 제외: 공백 제거 텍스트 길이 < MIN_SEG_LEN, 또는 페이지번호 패턴.
  - 보통 1블록 = 1세그먼트(block_ids=[block.id]), text=block.text, doc_type 전달.

B(디지털)·C(OCR) 출력은 동일한 Block 형식이므로 source 구분 없이 처리한다.
표준 라이브러리만 사용(외부 의존 없음).
"""
from __future__ import annotations

import re

from app.pdf.schema import Block, Segment

# 공백 제거 후 이 길이 미만이면 무의미 블록으로 간주하고 스킵.
MIN_SEG_LEN = 6

# 세그먼트 대상 타입(table 컨테이너 / figure 는 의도적으로 제외).
_SEGMENTABLE = {"heading", "para", "list_item", "table_row"}

# 페이지번호 패턴: 순수 숫자, "- 1 -", "1 / 10", "p. 3", "Page 4", "3쪽/페이지" 등.
_PAGE_NUMBER_RE = re.compile(
    r"""^\s*(?:
        -+\s*\d+\s*-+            # - 1 -
        | [\(\[]?\s*\d+\s*[\)\]]?  # 1, (1), [1]
        | \d+\s*[/／]\s*\d+        # 1 / 10
        | (?:p\.?|page)\s*\d+      # p.3, page 4
        | \d+\s*(?:쪽|페이지)       # 3쪽, 4페이지
    )\s*$""",
    re.IGNORECASE | re.VERBOSE,
)


def _is_page_number(text: str) -> bool:
    """페이지번호/머리말 류의 무의미 텍스트인지 판정."""
    return bool(_PAGE_NUMBER_RE.match(text.strip()))


def _is_meaningless(text: str) -> bool:
    """공백 제거 길이 미달 또는 페이지번호 패턴이면 무의미."""
    stripped = re.sub(r"\s+", "", text)
    if len(stripped) < MIN_SEG_LEN:
        return True
    if _is_page_number(text):
        return True
    return False


def to_segments(blocks: list[Block], doc_type: str | None = None) -> list[Segment]:
    """정규화된 Block[] 을 Segment[] 로 변환한다.

    위험 소지가 있는 블록을 누락하지 않도록, 의미 있는 텍스트는 모두 세그먼트로 보존한다.
    """
    segments: list[Segment] = []
    n = 0
    for block in blocks:
        # table 컨테이너 / figure 는 세그먼트 대상 아님.
        if block.type not in _SEGMENTABLE:
            continue
        # 무의미 블록(짧은 텍스트, 페이지번호) 스킵.
        if _is_meaningless(block.text):
            continue
        n += 1
        segments.append(
            Segment(
                seg_id=f"seg-{n}",
                block_ids=[block.id],
                text=block.text,
                doc_type=doc_type,
                risk=None,
            )
        )
    return segments


# --------------------------------------------------------------------------- #
# 테스트 (상류 구현 없이 목 Block 으로 검증 — 계약 대상 개발)
# --------------------------------------------------------------------------- #
def _mock_blocks() -> list[Block]:
    return [
        Block(id="b1", type="heading", text="개인정보 수집 동의", page=1, source="digital"),
        Block(id="b2", type="para", text="회사는 아래 항목을 수집합니다.", page=1, source="digital"),
        Block(id="t1", type="table", text="", page=1, source="digital"),
        Block(id="t1-r1", type="table_row", text="수집항목 | 이름, 연락처", page=1,
              source="digital", table_ref="t1", row_index=0),
        Block(id="t1-r2", type="table_row", text="보유기간 | 5년", page=1,
              source="digital", table_ref="t1", row_index=1),
        Block(id="f1", type="figure", text="", page=1, source="digital"),
        Block(id="pn", type="para", text="- 1 -", page=1, source="digital"),
    ]


def test_table_container_and_figure_excluded():
    segs = to_segments(_mock_blocks(), doc_type="consent")
    ids = [s.block_ids[0] for s in segs]
    assert "t1" not in ids, "table 컨테이너 제외"
    assert "f1" not in ids, "figure 제외"


def test_table_rows_kept_individually():
    segs = to_segments(_mock_blocks(), doc_type="consent")
    ids = [s.block_ids[0] for s in segs]
    assert "t1-r1" in ids and "t1-r2" in ids, "표는 행 단위"


def test_page_number_excluded():
    segs = to_segments(_mock_blocks(), doc_type="consent")
    ids = [s.block_ids[0] for s in segs]
    assert "pn" not in ids, "페이지번호 제외"


def test_doc_type_propagated():
    segs = to_segments(_mock_blocks(), doc_type="consent")
    assert all(s.doc_type == "consent" for s in segs)
    assert segs, "세그먼트가 비어있지 않아야 함"


def test_short_text_skipped():
    blocks = [
        Block(id="s1", type="para", text="짧음", page=1, source="digital"),       # < MIN_SEG_LEN
        Block(id="s2", type="para", text="충분히 긴 문장입니다.", page=1, source="digital"),
    ]
    ids = [s.block_ids[0] for s in to_segments(blocks)]
    assert "s1" not in ids and "s2" in ids


def test_seg_ids_stable_and_sequential():
    segs = to_segments(_mock_blocks(), doc_type="consent")
    assert [s.seg_id for s in segs] == [f"seg-{i + 1}" for i in range(len(segs))]


def test_ocr_and_digital_treated_same():
    blocks = [
        Block(id="d1", type="para", text="디지털 소스 문장입니다.", page=1, source="digital"),
        Block(id="o1", type="para", text="OCR 소스 문장입니다.", page=1, source="ocr",
              confidence=0.9),
    ]
    ids = [s.block_ids[0] for s in to_segments(blocks)]
    assert "d1" in ids and "o1" in ids


def test_various_page_number_patterns():
    patterns = ["- 12 -", "1 / 10", "p. 3", "Page 4", "3쪽", "(7)", "42"]
    blocks = [
        Block(id=f"p{i}", type="para", text=t, page=1, source="digital")
        for i, t in enumerate(patterns)
    ]
    assert to_segments(blocks) == [], f"모든 페이지번호 패턴 제외돼야 함: {patterns}"


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"PASS  {t.__name__}")
    print(f"\nAll {len(tests)} tests passed.")


if __name__ == "__main__":
    _run()
