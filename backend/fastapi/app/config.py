"""중앙 설정 — 환경변수 + 상수. lawbot.org 4대 기능 공통 설정."""
import os

# .env 자동 로드 (있으면). python-dotenv 미설치 시에도 환경변수로 동작.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

def _int_env(name: str, default: int) -> int:
    """정수 환경변수 안전 파싱 — 비숫자 값이면 기본값(앱 import 크래시 방지)."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        print(f"[config] {name}={raw!r} 이(가) 정수가 아님 → 기본값 {default} 사용")
        return default


# DB
DB_PATH = os.environ.get("DB_PATH", "data/medilaw.db")

# 임베딩 / 생성 모델
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-3-small")
EMBED_DIM = _int_env("EMBED_DIM", 512)
# 생성 LLM (챗봇·PDF). OpenAI gpt-5.5 (2026-04). 스냅샷 고정 원하면 gpt-5.5-2026-04-23.
CHAT_MODEL = os.environ.get("CHAT_MODEL", "gpt-5.5")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
# 추론 강도(gpt-5계열). "low"면 완답 시간 약 절반(품질은 근거기반이라 충분).
# 빈 문자열이면 미전달(모델 기본). 값: minimal(미지원)|low|medium|high.
REASONING_EFFORT = os.environ.get("REASONING_EFFORT", "low")

# 하이브리드 검색 RRF 상수
RRF_K = 60
DEFAULT_TOP_K = 8
# 재랭킹: 핵심 법령(trust_grade='법령')의 RRF 점수에 곱하는 가중.
# 제목이 비슷한 행정규칙이 핵심 4대 법령을 상위에서 밀어내는 문제를 보정한다(배제 아닌 가중).
# 1.0이면 가중 없음. 과하면 가이드라인·행정규칙이 필요할 때 안 나오므로 보수적으로.
STATUTE_BOOST = float(os.environ.get("STATUTE_BOOST", "1.4"))
# 후보 풀 크기(RRF 융합 전 FTS·벡터에서 모으는 후보 수). 클수록 핵심 법령이 후보에
# 진입할 확률↑(제목 동일 행정규칙이 후보를 포화시키는 문제 보정), 단 검색 지연↑.
RAG_POOL = int(os.environ.get("RAG_POOL", "100"))
# 조문명 다양성 캡: 같은 조문명 statute 히트를 결과에 최대 N개까지만(0=비활성).
# 동일 제목 행정규칙 다수가 핵심 법령을 밀어내지 않게 슬롯을 제한한다.
STATUTE_TITLE_CAP = int(os.environ.get("STATUTE_TITLE_CAP", "2"))

# 내용 일치(content faithfulness) 검증 — 인용 주변 '주장 문장' ↔ 실제 조문/판례 본문을
# 임베딩 코사인 유사도로 비교해 의미가 다른 인용을 탐지하는 별도 레이어.
# 기본 ON. 구조상 '확인'인데 유사도가 임계값 미만이면 '주의'로 다운그레이드(오류 단정 X — 임베딩은 확률적).
# 실질적 '주장'에만 작동(단순 인용·나열은 skip). CONTENT_CHECK=0 으로 끄면 구조 검증만 수행.
CONTENT_CHECK = os.environ.get("CONTENT_CHECK", "1") == "1"
# 내용검사 전용 임베딩(검색 인덱스 모델과 독립). 본문을 조항 청크로 쪼개 claim과의 최대
# 코사인을 쓰므로, 짧은 주장↔긴 본문 비교의 분리력을 높이려 large/3072 차원을 쓴다.
# (검색 인덱스는 small/512 — 캐시·차원 충돌을 피하려 별도 모델/캐시로 분리.)
CONTENT_EMBED_MODEL = os.environ.get("CONTENT_EMBED_MODEL", "text-embedding-3-large")
CONTENT_EMBED_DIM = int(os.environ.get("CONTENT_EMBED_DIM", "3072"))
# 의미 일치로 볼 코사인 유사도 하한(청크-최대 기준). large+청크최대로 4대 법령 조문 본문 vs
# 올바른/틀린 주장(9쌍) 재보정: 올바른 주장 min 0.642·mean 0.752, 틀린 주장 max 0.685·mean 0.540.
# 0.60 = 올바른 주장 통과율 100%(오경보 0, 최저 0.642 아래 여유) 유지하며 틀린 주장 대부분(<0.60)을 거름.
CONTENT_SIM_THRESHOLD = float(os.environ.get("CONTENT_SIM_THRESHOLD", "0.60"))

# 인증 — x-api-key. 쉼표구분 다중키. 비어있으면 인증 비활성(로컬 개발)
API_KEYS = {k.strip() for k in os.environ.get("API_KEYS", "").split(",") if k.strip()}

# 레이트리밋 (lawbot 무료 데모: IP당 분당 30회)
RATE_LIMIT_PER_MIN = _int_env("RATE_LIMIT_PER_MIN", 30)

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
