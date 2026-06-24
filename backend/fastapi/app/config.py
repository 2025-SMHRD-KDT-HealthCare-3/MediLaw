"""중앙 설정 — 환경변수 + 상수. lawbot.org 4대 기능 공통 설정."""
import os

# .env 자동 로드 (있으면). python-dotenv 미설치 시에도 환경변수로 동작.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# DB
DB_PATH = os.environ.get("DB_PATH", "data/medilaw.db")

# 임베딩 / 생성 모델
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-3-small")
EMBED_DIM = int(os.environ.get("EMBED_DIM", "512"))
# 생성 LLM (챗봇·PDF). OpenAI gpt-5.5 (2026-04). 스냅샷 고정 원하면 gpt-5.5-2026-04-23.
CHAT_MODEL = os.environ.get("CHAT_MODEL", "gpt-5.5")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
# 추론 강도(gpt-5계열). "low"면 완답 시간 약 절반(품질은 근거기반이라 충분).
# 빈 문자열이면 미전달(모델 기본). 값: minimal(미지원)|low|medium|high.
REASONING_EFFORT = os.environ.get("REASONING_EFFORT", "low")

# 하이브리드 검색 RRF 상수
RRF_K = 60
DEFAULT_TOP_K = 8

# 인증 — x-api-key. 쉼표구분 다중키. 비어있으면 인증 비활성(로컬 개발)
API_KEYS = {k.strip() for k in os.environ.get("API_KEYS", "").split(",") if k.strip()}

# 레이트리밋 (lawbot 무료 데모: IP당 분당 30회)
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "30"))

# 검색 가능한 출처 종류 (법령·판례·해석례·결정문·가이드라인)
SOURCE_TYPES = ("statute", "case", "interpretation", "decision", "guideline")

# 법제처 국가법령정보 공동활용 OC 키 — 법령 개정 현황(연혁/버전) 조회용.
# 호출 IP/도메인이 등록돼 있어야 응답함(미등록 시 HTML 에러).
LAW_OC = os.environ.get("LAW_OC", "H-Lab")

# 개정 현황 대시보드가 추적하는 핵심 법령(기획서 4대 법령).
TRACKED_LAWS = [
    "의료법",
    "개인정보 보호법",
    "생명윤리 및 안전에 관한 법률",
    "정보통신망 이용촉진 및 정보보호 등에 관한 법률",
]
