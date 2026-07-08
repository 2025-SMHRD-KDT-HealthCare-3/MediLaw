"""OpenAI 생성 LLM 래퍼 (gpt-5.5). 챗봇·PDF 에디터 공용."""
import json
import threading
from collections.abc import Iterator

from app.config import CHAT_MODEL, OPENAI_API_KEY, REASONING_EFFORT


class LLMUnavailable(RuntimeError):
    """OPENAI_API_KEY 미설정 등 LLM 사용 불가."""


# 공유 OpenAI 클라이언트 — 매 호출마다 새로 만들면 커넥션 풀/TLS 핸드셰이크가 재생성돼
# 지연이 누적된다. OpenAI 클라이언트는 스레드 안전이므로 프로세스 1회 지연 생성해 재사용한다
# (임베딩 호출부 app.rag / app.citations 도 이 클라이언트를 공유). 키 미설정이면 기존과
# 동일하게 '호출 시점'에 LLMUnavailable — import 시점엔 아무 일도 일어나지 않는다.
_client_lock = threading.Lock()
_shared_client = None


def openai_client():
    """공유 OpenAI 클라이언트(지연 생성·프로세스 1회 캐시). 키 없으면 LLMUnavailable."""
    global _shared_client
    if not OPENAI_API_KEY:
        raise LLMUnavailable("OPENAI_API_KEY 가 설정되지 않았습니다")
    if _shared_client is None:
        with _client_lock:
            if _shared_client is None:  # double-checked — 경합 시 중복 생성 방지
                from openai import OpenAI

                _shared_client = OpenAI(api_key=OPENAI_API_KEY)
    return _shared_client


_client = openai_client  # 모듈 내부 기존 호출명 유지


# 모든 생성 호출 공통 옵션 — 추론 강도 낮춰 지연 단축(REASONING_EFFORT 빈값이면 미전달).
_GEN_OPTS = {"reasoning_effort": REASONING_EFFORT} if REASONING_EFFORT else {}


def chat(messages: list[dict]) -> str:
    """단발 생성. 답변 텍스트 반환."""
    try:
        resp = _client().chat.completions.create(model=CHAT_MODEL, messages=messages, **_GEN_OPTS)
    except LLMUnavailable:
        raise  # 키 미설정 등 의도된 예외는 그대로 전파
    except Exception as e:  # OpenAI 런타임 에러(RateLimit/Timeout/Auth 등) → 호출부가 503/폴백 처리
        raise LLMUnavailable(f"LLM 호출 실패: {e}") from e
    return resp.choices[0].message.content or ""


def chat_json(messages: list[dict]) -> dict:
    """JSON 모드 단발 생성. 파싱된 dict 반환 (structured output).

    PDF 에디터처럼 구조화된 분석 결과가 필요할 때 사용.
    프롬프트에 'JSON' 단어가 포함돼야 함(OpenAI json_object 요구사항).
    """
    try:
        resp = _client().chat.completions.create(
            model=CHAT_MODEL, messages=messages,
            response_format={"type": "json_object"}, **_GEN_OPTS,
        )
    except LLMUnavailable:
        raise  # 키 미설정 등 의도된 예외는 그대로 전파
    except Exception as e:  # OpenAI 런타임 에러 → 호출부가 503/폴백 처리
        raise LLMUnavailable(f"LLM 호출 실패: {e}") from e
    content = resp.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise LLMUnavailable(f"LLM JSON 파싱 실패: {e}") from e


def translate(text: str, target: str = "ko") -> str:
    """짧은 번역(검색어 EN→KO 등). 실패 시 원문 그대로 반환(degradation)."""
    lang = "Korean" if target == "ko" else "English"
    try:
        resp = _client().chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content":
                    f"Translate the user's text into {lang}. "
                    f"Output only the translation, no quotes or explanation."},
                {"role": "user", "content": text},
            ],
            **_GEN_OPTS,
        )
        return (resp.choices[0].message.content or "").strip() or text
    except Exception:  # LLM 실패 전반(키 미설정·런타임 에러) → 원문 반환(검색 degrade 보장)
        return text


def rewrite_query(history: list[dict], question: str) -> str:
    """멀티턴 후속질문을 '독립 검색질의(한국어)'로 재작성.

    "그럼 그건?" 같은 후속질문은 단독으론 검색이 안 되므로 대화 맥락을 합쳐
    한국어 standalone 질의로 변환(검색 코퍼스가 한국어 → 영어 입력도 함께 해결).
    이력 없음/실패 시 원문 반환(degradation).
    """
    if not history:
        return question
    convo = "\n".join(f"{t['role']}: {t['content']}" for t in history)
    try:
        resp = _client().chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content":
                    "Given the conversation and a follow-up message, rewrite the follow-up as a single "
                    "standalone search query in Korean that captures the full intent. "
                    "Output only the query, no explanation."},
                {"role": "user", "content": f"{convo}\n\nfollow-up: {question}"},
            ],
            **_GEN_OPTS,
        )
        return (resp.choices[0].message.content or "").strip() or question
    except Exception:  # LLM 실패 전반(키 미설정·런타임 에러) → 원문 반환(검색 degrade 보장)
        return question


# 단일턴 질의 재작성 프롬프트 — 일상어를 법령 용어로 '보강'(대체 아님)하는 검색질의 생성.
# 블라인드 평가에서 구어체·상황형 질문("면허 없이 문신", "해킹당했어요")이 법령 용어
# (무면허 의료행위, 침해사고)와 어휘가 달라 검색을 놓치는 문제를 해결한다.
# 원 질문 키워드를 반드시 유지시키는 이유: 골든셋(이미 법령 용어로 쓰인 질문)의
# 검색 품질이 재작성으로 오히려 떨어지지 않게 하기 위함(최소 보강 원칙).
_SINGLE_REWRITE_SYSTEM = (
    "사용자의 일상어 질문을 한국 법령(의료법·개인정보보호법·생명윤리법·정보통신망법) "
    "검색에 적합한 한국어 검색 질의 한 줄로 다듬어라.\n"
    "규칙:\n"
    "1. 원 질문의 핵심 명사·키워드는 빠짐없이 그대로 유지하고, 그 뒤에 대응하는 법령 용어를 "
    "덧붙여 '보강'만 하라. 원 단어를 다른 말로 바꾸거나 새 주제를 지어내지 마라.\n"
    "2. 일상 표현에는 대응하는 법령 용어를 덧붙여라. 예: '면허 없이 시술' → 무면허 의료행위, "
    "'폐업하는 병원의 진료기록' → 진료기록부 이관, '해킹당했다' → 침해사고, "
    "'광고 문자·스팸' → 영리목적 광고성 정보 전송, 'CCTV' → 고정형 영상정보처리기기, "
    "'환자 정보 유출' → 개인정보 유출 통지·신고.\n"
    "3. 처벌·벌금·형량·처벌 수위를 묻는 질문이면 끝에 '벌칙 처벌 벌금 형사처벌'을 덧붙여라.\n"
    "4. 이미 법령 용어로 쓰인 질문은 거의 그대로 두고 필요한 용어만 최소로 덧붙여라.\n"
    "5. 출력은 짧은 검색 질의 한 줄만. 설명·따옴표·마크다운 금지."
)


def rewrite_query_single(question: str) -> str:
    """단일턴(이력 없음) 질문을 법령 용어로 보강한 '검색 전용' 질의로 재작성.

    검색 코퍼스는 법령 용어로 쓰여 있어 구어체 질문은 어휘 불일치로 놓친다.
    답변 생성 프롬프트에는 여전히 사용자의 원 질문을 쓰고, 이 결과는 hybrid_search
    입력으로만 사용한다. 실패 시 원문 반환(degradation — rewrite_query 와 동일 패턴).
    """
    try:
        resp = _client().chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": _SINGLE_REWRITE_SYSTEM},
                {"role": "user", "content": question},
            ],
            **_GEN_OPTS,
        )
        return (resp.choices[0].message.content or "").strip() or question
    except Exception:  # LLM 실패 전반(키 미설정·런타임 에러) → 원문 반환(검색 degrade 보장)
        return question


def ocr_image(b64_png: str) -> str:
    """비전 모델로 이미지(base64 PNG)에서 한국어 텍스트 추출.

    스캔본/이미지 PDF의 OCR fallback 용. 본문만 반환(설명 금지).
    """
    try:
        resp = _client().chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": [
                {"type": "text", "text":
                    "이 이미지에 있는 모든 텍스트를 읽어 원문 그대로 출력하세요. "
                    "줄바꿈은 유지하고, 설명·요약 없이 본문 텍스트만 출력하세요. "
                    "글자가 없으면 빈 문자열을 출력하세요."},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64_png}"}},
            ]}],
            **_GEN_OPTS,
        )
    except LLMUnavailable:
        raise  # 키 미설정 등 의도된 예외는 그대로 전파
    except Exception as e:  # OpenAI 런타임 에러 → 호출부가 503/폴백 처리
        raise LLMUnavailable(f"LLM 호출 실패: {e}") from e
    return resp.choices[0].message.content or ""


def chat_stream(messages: list[dict]) -> Iterator[str]:
    """토큰 스트리밍 (delta 텍스트만 yield)."""
    try:
        stream = _client().chat.completions.create(
            model=CHAT_MODEL, messages=messages, stream=True, **_GEN_OPTS
        )
    except LLMUnavailable:
        raise  # 키 미설정 등 의도된 예외는 그대로 전파
    except Exception as e:  # OpenAI 런타임 에러 → consumer(gen())가 error 이벤트 처리
        raise LLMUnavailable(f"LLM 호출 실패: {e}") from e
    try:
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    except LLMUnavailable:
        raise
    except Exception as e:  # 순회 중 런타임 에러도 변환
        raise LLMUnavailable(f"LLM 호출 실패: {e}") from e
