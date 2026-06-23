"""PDF 파이프라인 공유 계약 — 블록 스키마 (오케스트레이터 소유, 가장 먼저 잠금).

모든 서브에이전트(A~G)의 입력/출력 형식. 이 계약에만 맞추면 서로의 구현을 기다리지 않고
병렬 개발이 가능하다. 변경은 오케스트레이터를 통해서만(영향 에이전트 전체 통지·재검증).

흐름별 계약:
  A 라우팅      → list[PageRoute]
  B 디지털추출   → list[Block]  (source="digital", confidence=None)
  C OCR추출     → list[Block]  (source="ocr",     confidence 채움)   ※ B와 동일 형식
  D 세그먼트     → list[Segment] (risk=None)
  E 위험판정     → Segment.risk 채움
  F 치환        → before/after 적용(블록 단위)
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

BlockType = Literal["heading", "para", "list_item", "table", "table_row", "figure"]
DocType = Literal["ad", "consent", "privacy_policy", "terms"]
RiskLevel = Literal["none", "low", "med", "high"]
RouteKind = Literal["digital", "scan"]


class PageRoute(BaseModel):
    """A(페이지 라우팅) 출력 — 페이지별 디지털/스캔 분기."""
    page: int
    route: RouteKind


class Block(BaseModel):
    """추출 단위(B 디지털 / C OCR 공통 형식). 표는 table + table_row 들로 표현."""
    id: str
    type: BlockType
    text: str = ""
    page: int
    bbox: Optional[list[float]] = Field(
        None, description="[x0,y0,x1,y1] before/after 치환용 원문 위치(가능하면 채움)")
    source: Literal["digital", "ocr"]
    confidence: Optional[float] = Field(None, description="OCR일 때만(0~1)")
    table_ref: Optional[str] = Field(None, description="table_row가 속한 table id")
    row_index: Optional[int] = None


class RiskResult(BaseModel):
    """E(위험판정) 산출."""
    level: RiskLevel = "none"
    law: list[str] = Field(default_factory=list, description="근거 법령/가이드라인")
    reason: str = ""
    before: str = ""
    after: str = ""


class Segment(BaseModel):
    """D(세그먼트) 산출 — 보통 1블록, 표는 1행=1세그먼트. E가 risk 채움."""
    seg_id: str
    block_ids: list[str] = Field(default_factory=list)
    text: str = ""
    doc_type: Optional[str] = None
    risk: Optional[RiskResult] = None


class Document(BaseModel):
    """파이프라인을 관통하는 문서 표현."""
    doc_id: str
    doc_type: Optional[DocType] = None
    page_count: int = 0
    status: Literal["processing", "reviewed"] = "processing"
    blocks: list[Block] = Field(default_factory=list)
