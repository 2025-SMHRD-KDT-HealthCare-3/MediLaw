"""요청/응답 스키마 — lawbot.org v1 API 계약."""
import re
from datetime import date
from typing import Annotated, Literal, Optional

from pydantic import AfterValidator, BaseModel, Field

SourceType = Literal["statute", "case", "interpretation", "decision", "guideline"]


def _validate_as_of(v: Optional[str]) -> Optional[str]:
    """as_of 검증 — None/빈값은 None, YYYY-MM-DD(또는 YYYYMMDD)이면서 실제 유효 날짜만 허용.

    잘못된 값(형식 오류 또는 2026-13-99 같은 불가능한 날짜)이 시점필터를 조용히
    무력화/왜곡하지 않도록 입력 단에서 422로 막는다.
    """
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if re.fullmatch(r"\d{8}", v):           # YYYYMMDD → 검증용으로 dash 형태로
        s = f"{v[:4]}-{v[4:6]}-{v[6:8]}"
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        s = v
    else:
        raise ValueError("as_of는 YYYY-MM-DD(또는 YYYYMMDD) 형식이어야 합니다")
    try:
        date.fromisoformat(s)               # 실제 유효 날짜인지(월≤12·일≤말일)
    except ValueError:
        raise ValueError(f"as_of '{v}' 는 유효한 날짜가 아닙니다")
    return v


# 시점조회 파라미터 공용 타입(검증 포함). 요청 모델의 as_of 에 사용.
AsOf = Annotated[Optional[str], AfterValidator(_validate_as_of)]


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
    as_of: AsOf = Field(None, description="시점 조회 YYYY-MM-DD (이 날짜에 유효한 자료만)")


class RetrieveResponse(BaseModel):
    output: list[Hit]
    as_of: AsOf = None
    source: str = "medilaw.db"
    method: str = "hybrid"


# ---------- /v1/source-pack (Source Pack) ----------
class SourcePackRequest(BaseModel):
    query: str
    max_items: int = Field(8, ge=1, le=30)
    source_types: Optional[list[SourceType]] = None
    as_of: AsOf = None


class Citation(BaseModel):
    label: str
    source_type: SourceType
    source_id: int
    source_url: str = ""
    trust_grade: str = ""


class SourcePackResponse(BaseModel):
    output: str = Field(description="LLM 인용용 마크다운")
    citations: list[Citation]
    as_of: AsOf = None
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
    as_of: AsOf = None


class VerifyResult(BaseModel):
    raw: str
    type: Literal["statute", "case", "unknown"]
    exists: bool
    clause_accurate: Optional[bool] = None
    valid_as_of: Optional[bool] = None
    verified: bool
    trust_score: int = Field(0, ge=0, le=100, description="신뢰 점수 0~100")
    status: Literal["확인", "주의", "오류"] = Field("오류", description="확인=신뢰 / 주의=조건부 / 오류=환각·불일치")
    matched_label: str = ""
    matched_source_url: str = ""
    note: str = ""


class VerifySummary(BaseModel):
    total: int
    verified: int
    failed: int
    avg_score: int = Field(0, ge=0, le=100, description="인용 전체 평균 신뢰 점수")
    worst_status: Literal["확인", "주의", "오류"] = Field(
        "확인", description="가장 나쁜 항목의 상태(오류>주의>확인)")
    min_score: int = Field(100, ge=0, le=100, description="최저 신뢰 점수(가장 약한 인용)")


class VerifyResponse(BaseModel):
    output: list[VerifyResult]
    summary: VerifySummary
    as_of: AsOf = None


# ---------- /chat (AI 질의응답 챗봇) ----------
Lang = Literal["auto", "ko", "en"]


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    question: str
    history: list[ChatTurn] = Field(default_factory=list, description="이전 대화(무상태 — 클라이언트가 보관·전달)")
    top_k: int = Field(8, ge=1, le=20)
    source_types: Optional[list[SourceType]] = None
    as_of: AsOf = None
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


class AnswerSegment(BaseModel):
    type: Literal["text", "cite"]
    text: str = Field("", description="text조각 본문 / cite면 표시 라벨 예 '[1]'")
    n: Optional[int] = None
    source_type: Optional[SourceType] = None
    source_id: Optional[int] = None
    label: str = ""


class ChatResponse(BaseModel):
    answer: str
    answer_segments: list[AnswerSegment] = Field(default_factory=list,
        description="answer를 [n] 기준으로 쪼갠 렌더용 배열. cite 토큰에 seed(source_type/source_id) 포함")
    sources: list[ChatSource]
    citation_check: VerifyResponse = Field(description="답변 인용의 Citation Firewall 검증")
    method: str = "hybrid"
    lang: str = Field("ko", description="실제 응답 언어")
    search_query: str = Field("", description="검색에 실제 사용된 질의(멀티턴이면 재작성된 standalone)")
    as_of: AsOf = None


# ---------- /documents/review (능동형 PDF 에디터) ----------
class ReviewRequest(BaseModel):
    """텍스트 직접 검토(파일 업로드는 multipart form 으로 처리)."""
    text: str = Field(description="검토할 문서 본문(광고문구·동의서·약관 등)")
    as_of: AsOf = None
    top_k_per_segment: int = Field(4, ge=1, le=8, description="세그먼트별 근거 검색 개수")


class ReviewFinding(BaseModel):
    segment_index: int = Field(description="위험 세그먼트 번호(segments 배열 인덱스)")
    segment_text: str = Field(description="원문 세그먼트")
    risk_level: Literal["high", "medium", "low"]
    issue: str = Field(description="위험 사유")
    suggestion: str = Field(description="대안 문구(수정 권고)")
    citations: list[ChatSource] = Field(default_factory=list, description="판단 근거")
    page: Optional[int] = Field(None, description="위험 세그먼트가 위치한 1-based 페이지(텍스트 입력 시 None)")
    bbox: Optional[list[float]] = Field(None, description="페이지 상대 정규화 좌표 [x0,y0,x1,y1] (0~1, 좌상단 원점). 프론트는 렌더 캔버스 크기를 곱해 박스를 그림. 좌표 없으면 None")


ChecklistStatus = Literal["todo", "ok", "risk", "na"]


class ChecklistItem(BaseModel):
    """능동형 확인목록 — 사람이 추가로 확인해야 할 항목(문서 내용 기반 동적 생성)."""
    id: str = Field(description="안정 식별자(재조정 시 유지)")
    title: str = Field(description="확인할 것")
    reason: str = Field(description="왜 확인해야 하는지")
    status: ChecklistStatus = "todo"
    change: Literal["added", "kept", "updated", "removed"] = Field(
        "added", description="이전 체크리스트 대비 변화")
    segment_index: Optional[int] = Field(None, description="관련 세그먼트(있으면)")
    citations: list[ChatSource] = Field(default_factory=list, description="근거")
    note: str = Field("", description="사용자 메모(요청에 담아 보내면 다음 분석까지 보존)")


class ChecklistSummary(BaseModel):
    total: int = 0
    todo: int = 0
    ok: int = 0
    risk: int = 0
    na: int = 0


class ReviewResponse(BaseModel):
    original_text: str = Field(description="before — 추출된 원문 전체")
    revised_text: str = Field(description="after — 위험 세그먼트를 대안 문구로 치환한 수정본")
    segments: list[str] = Field(description="문서를 분할한 세그먼트(원문)")
    findings: list[ReviewFinding] = Field(description="위험 세그먼트별 검토 결과(segment_text=before, suggestion=after)")
    checklist: list[ChecklistItem] = Field(default_factory=list, description="능동형 확인목록(추가/삭제/유지 동적)")
    checklist_summary: ChecklistSummary = Field(default_factory=ChecklistSummary, description="상태별 항목 수")
    extracted_by: Literal["text", "ocr"] = Field("text", description="원문 추출 방식")
    ocr_failed_pages: list[int] = Field(default_factory=list, description="스캔(OCR) 페이지인데 텍스트 추출에 실패한 페이지 번호(1-based). 비어있으면 정상")
    citation_check: VerifyResponse = Field(description="findings 인용의 Citation Firewall 검증")
    method: str = "hybrid"
    lang: str = Field("ko", description="실제 응답 언어")
    as_of: AsOf = None


# ---------- /chat/checklist (대화 종료 후 능동형 체크리스트) ----------
class ChecklistRequest(BaseModel):
    """'체크리스트 생성' 버튼 — 대화 + PDF 문서검토를 종합해 통합 법적 대응 체크리스트를 만든다."""
    history: list[ChatTurn] = Field(
        default_factory=list, description="전체 대화(무상태 — 클라이언트가 보관·전달, 없으면 문서만으로 생성)")
    reviews: Optional[list[dict]] = Field(
        None,
        description="PDF 문서검토(/documents/review) 응답들. 각 dict에서 original_text·findings"
                    "(segment_text/risk_level/issue/suggestion)를 방어적으로 파싱(누락 필드 무시)")
    top_k: int = Field(6, ge=1, le=20, description="쟁점별 근거 검색 개수")
    max_topics: int = Field(5, ge=1, le=8, description="대화·문서에서 추출할 법적 쟁점 수")
    as_of: AsOf = None
    lang: Lang = Field("auto", description="응답 언어. auto=대화 언어 자동감지")
    prev_checklist: Optional[list[dict]] = Field(
        None, description="직전 checklist(재생성 시 사용자 status/note 보존)")


class ChecklistResponse(BaseModel):
    checklist: list[ChecklistItem] = Field(default_factory=list, description="법적 대응 확인목록")
    checklist_summary: ChecklistSummary = Field(default_factory=ChecklistSummary, description="상태별 항목 수")
    sources: list[ChatSource] = Field(default_factory=list, description="체크리스트 근거로 RAG 검색된 자료")
    search_queries: list[str] = Field(default_factory=list, description="대화에서 추출해 검색에 사용한 쟁점 질의")
    citation_check: VerifyResponse = Field(description="체크리스트 인용의 Citation Firewall 검증")
    method: str = "hybrid"
    lang: str = Field("ko", description="실제 응답 언어")
    as_of: AsOf = None


# ---------- /v1/laws/* (법령 개정 현황 대시보드) ----------
class LawRevision(BaseModel):
    mst: str = Field(description="법령일련번호(버전 조회 키)")
    effective_on: Optional[str] = Field(None, description="시행일 YYYY-MM-DD")
    promulgated_on: Optional[str] = Field(None, description="공포일 YYYY-MM-DD")
    promulgation_no: str = ""
    revision_type: str = Field("", description="제개정구분(일부개정/타법개정/제정 등)")
    status: str = Field("", description="시행예정 | 현행 | 연혁")
    reason: str = Field("", description="제개정이유(주로 현행 버전)")
    detail_url: str = ""


class LawStatus(BaseModel):
    law_id: str
    name: str
    ministry: str = ""
    current: Optional[LawRevision] = Field(None, description="현행 버전")
    upcoming: list[LawRevision] = Field(default_factory=list, description="시행예정(앞으로 바뀔 조항)")
    history_count: int = Field(0, description="연혁(과거 개정) 수")
    latest_effective_on: Optional[str] = None


class LawRevisionsResponse(BaseModel):
    """대시보드 메인 — 추적 법령별 개정 현황 요약."""
    laws: list[LawStatus]
    tracked: int = 0
    synced_at: Optional[str] = Field(None, description="마지막 배치 동기화 시각(없으면 미동기화)")
    source: str = "법제처 국가법령정보 공동활용"


class LawTimelineResponse(BaseModel):
    """특정 법령 전체 개정 이력 타임라인."""
    law_id: str
    name: str
    revisions: list[LawRevision]


class ArticleDiff(BaseModel):
    article_no: str
    article_title: str = ""
    change: Literal["added", "removed", "changed"]
    before: str = Field("", description="개정 전 조문(removed/changed)")
    after: str = Field("", description="개정 후 조문(added/changed)")


class LawDiffResponse(BaseModel):
    """개정 전후 조문 비교표."""
    law_id: str
    name: str = ""
    from_effective_on: Optional[str] = Field(None, description="비교 기준(이전) 시행일")
    to_effective_on: Optional[str] = Field(None, description="비교 대상(이후) 시행일")
    added: int = 0
    removed: int = 0
    changed: int = 0
    diffs: list[ArticleDiff] = Field(default_factory=list)


# ---------- /v1/related-graph (연관 판례 그래프 — '더보기' 시각화) ----------
class GraphSeed(BaseModel):
    """사용자가 클릭한 인용 — 그래프에 반드시 포함·강조."""
    source_type: SourceType
    source_id: int


class RelatedGraphRequest(BaseModel):
    """입력 문구/질의 하나로 연관 판례 그래프를 요청 (챗봇·PDF 검토 공용)."""
    text: str = Field(description="사용자가 보고 있던 문구/질의 (광고 문구, 챗봇 질의 등)")
    lang: str = Field("ko", description="라벨 언어 ko|en")
    as_of: AsOf = Field(None, description="시점 조회 YYYY-MM-DD")
    top_k: int = Field(12, ge=1, le=30, description="검색 후보 수")
    seeds: list[GraphSeed] = Field(
        default_factory=list,
        description="클릭한 [1] 인용(조문·판례). 그래프에 반드시 포함·강조")


class GraphCase(BaseModel):
    """그래프 말단 — 실재하는 판례 노드(검색 히트에서만 생성)."""
    source_id: int
    label: str = Field("", description="인용 라벨, 예: '대법원 2018두12345'")
    title: str = ""
    summary: str = ""
    source_url: str = ""
    highlighted: bool = Field(False, description="사용자가 클릭한 인용 노드 여부")


class GraphIssue(BaseModel):
    """그래프 중간 노드 — 위반 쟁점 묶음."""
    label: str = Field(description="쟁점명, 예: '과장·허위 광고'")
    statute: str = Field("", description="관련 조문 라벨, 예: '의료법 제56조'")
    statute_highlighted: bool = Field(False, description="statute가 클릭한 인용인지")
    cases: list[GraphCase] = Field(default_factory=list)
    sanctions: list[str] = Field(default_factory=list, description="제재수위, 예: ['업무정지 1개월']")


class GraphRoot(BaseModel):
    label: str = ""
    text: str = ""


class RelatedGraphResponse(BaseModel):
    """프론트 마인드맵 렌더용: root → issues → cases/sanctions."""
    root: GraphRoot
    issues: list[GraphIssue] = Field(default_factory=list)
    method: str = Field("hybrid", description="검색 방식 hybrid|fts")
    llm: bool = Field(True, description="gpt-5.5 쟁점 가공 성공 여부(false=규칙 폴백)")
