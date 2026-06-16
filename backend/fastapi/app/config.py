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

# 하이브리드 검색 RRF 상수
RRF_K = 60
DEFAULT_TOP_K = 8

# 인증 — x-api-key. 쉼표구분 다중키. 비어있으면 인증 비활성(로컬 개발)
API_KEYS = {k.strip() for k in os.environ.get("API_KEYS", "").split(",") if k.strip()}

# 레이트리밋 (lawbot 무료 데모: IP당 분당 30회)
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "30"))

# 검색 가능한 출처 종류
SOURCE_TYPES = ("statute", "case", "interpretation")
