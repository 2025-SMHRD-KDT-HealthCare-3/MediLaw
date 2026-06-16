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
Lang = Literal["auto", "ko", "en"]


class ChatRequest(BaseModel):
    question: str
    top_k: int = Field(8, ge=1, le=20)
    source_types: Optional[list[SourceType]] = None
    as_of: Optional[str] = None
    lang: Lang = Field("auto", description="응답 언어. auto=질문 언어 자동감지")


class ChatSource(BaseModel):
    n: int = Field(description="인용 번호 [n]")
    label: str
    source_type: SourceType
    source_id: int
    snippet: str = ""
    source_url: str = ""
    trust_grade: str = ""
    # 영어 응답용 — 법령은 공식 영문(elaw), 그 외는 비어있음(LLM 비공식 번역)
    label_en: str = Field("", description="공식 영문 라벨(법령만)")
    snippet_en: str = Field("", description="공식 영문 조문(법령만)")
    is_official_en: bool = Field(False, description="공식 영문 출처 여부(법령 True)")


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource]
    citation_check: VerifyResponse = Field(description="답변 인용의 Citation Firewall 검증")
    method: str = "hybrid"
    lang: str = Field("ko", description="실제 응답 언어")
    as_of: Optional[str] = None


# ---------- /documents/review (능동형 PDF 에디터) ----------
class ReviewRequest(BaseModel):
    """텍스트 직접 검토(파일 업로드는 multipart form 으로 처리)."""
    text: str = Field(description="검토할 문서 본문(광고문구·동의서·약관 등)")
    as_of: Optional[str] = None
    top_k_per_segment: int = Field(4, ge=1, le=8, description="세그먼트별 근거 검색 개수")


class ReviewFinding(BaseModel):
    segment_index: int = Field(description="위험 세그먼트 번호(segments 배열 인덱스)")
    segment_text: str = Field(description="원문 세그먼트")
    risk_level: Literal["high", "medium", "low"]
    issue: str = Field(description="위험 사유")
    suggestion: str = Field(description="대안 문구(수정 권고)")
    citations: list[ChatSource] = Field(default_factory=list, description="판단 근거")


class ReviewResponse(BaseModel):
    original_text: str = Field(description="before — 추출된 원문 전체")
    revised_text: str = Field(description="after — 위험 세그먼트를 대안 문구로 치환한 수정본")
    segments: list[str] = Field(description="문서를 분할한 세그먼트(원문)")
    findings: list[ReviewFinding] = Field(description="위험 세그먼트별 검토 결과(segment_text=before, suggestion=after)")
    extracted_by: Literal["text", "ocr"] = Field("text", description="원문 추출 방식")
    citation_check: VerifyResponse = Field(description="findings 인용의 Citation Firewall 검증")
    method: str = "hybrid"
    lang: str = Field("ko", description="실제 응답 언어")
    as_of: Optional[str] = None
