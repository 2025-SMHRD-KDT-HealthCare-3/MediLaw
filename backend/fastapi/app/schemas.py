"""요청/응답 스키마 — lawbot.org v1 API 계약."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

SourceType = Literal["statute", "case", "interpretation", "decision", "guideline"]


# ---------- 공통 ----------
class Hit(BaseModel):
    source_type: SourceType
    source_id: int
    label: str = Field(description="인용 라벨, 예: '의료법 제27조' / '대법원 2010도1234'")
    title: str = ""
    snippet: str = ""
    score: float = 0.0
    trust_grade: str = ""
    effective_from: Optional[str] = None
    source_url: str = ""


# ---------- /v1/retrieve (RAG API) ----------
class RetrieveRequest(BaseModel):
    query: str
    top_k: int = Field(8, ge=1, le=50)
    source_types: Optional[list[SourceType]] = None
    as_of: Optional[str] = Field(None, description="시점 조회 YYYY-MM-DD (이 날짜에 유효한 자료만)")


class RetrieveResponse(BaseModel):
    output: list[Hit]
    as_of: Optional[str] = None
    source: str = "medilaw.db"
    method: str = "hybrid"


# ---------- /v1/source-pack (Source Pack) ----------
class SourcePackRequest(BaseModel):
    query: str
    max_items: int = Field(8, ge=1, le=30)
    source_types: Optional[list[SourceType]] = None
    as_of: Optional[str] = None


class Citation(BaseModel):
    label: str
    source_type: SourceType
    source_id: int
    source_url: str = ""
    trust_grade: str = ""


class SourcePackResponse(BaseModel):
    output: str = Field(description="LLM 인용용 마크다운")
    citations: list[Citation]
    as_of: Optional[str] = None
    source: str = "medilaw.db"


# ---------- /v1/verify (Citation Firewall) ----------
class CitationInput(BaseModel):
    """직접 검증할 인용. text 대신 구조화 입력도 가능."""
    law_name: Optional[str] = None
    article_no: Optional[str] = None
    case_no: Optional[str] = None
    raw: Optional[str] = None


class VerifyRequest(BaseModel):
    text: Optional[str] = Field(None, description="LLM 답변 원문 — 인용 자동 추출")
    citations: Optional[list[CitationInput]] = None
    as_of: Optional[str] = None


class VerifyResult(BaseModel):
    raw: str
    type: Literal["statute", "case", "unknown"]
    exists: bool
    clause_accurate: Optional[bool] = None
    valid_as_of: Optional[bool] = None
    verified: bool
    matched_label: str = ""
    matched_source_url: str = ""
    note: str = ""


class VerifySummary(BaseModel):
    total: int
    verified: int
    failed: int


class VerifyResponse(BaseModel):
    output: list[VerifyResult]
    summary: VerifySummary
    as_of: Optional[str] = None


# ---------- /chat (AI 질의응답 챗봇) ----------
class ChatRequest(BaseModel):
    question: str
    top_k: int = Field(8, ge=1, le=20)
    source_types: Optional[list[SourceType]] = None
    as_of: Optional[str] = None


class ChatSource(BaseModel):
    n: int = Field(description="인용 번호 [n]")
    label: str
    source_type: SourceType
    source_id: int
    snippet: str = ""
    source_url: str = ""
    trust_grade: str = ""


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource]
    citation_check: VerifyResponse = Field(description="답변 인용의 Citation Firewall 검증")
    method: str = "hybrid"
    as_of: Optional[str] = None
