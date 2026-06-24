"""OpenAI 생성 LLM 래퍼 (gpt-5.5). 챗봇·PDF 에디터 공용."""
import json
from collections.abc import Iterator

from app.config import CHAT_MODEL, OPENAI_API_KEY, REASONING_EFFORT


class LLMUnavailable(RuntimeError):
    """OPENAI_API_KEY 미설정 등 LLM 사용 불가."""


def _client():
    if not OPENAI_API_KEY:
        raise LLMUnavailable("OPENAI_API_KEY 가 설정되지 않았습니다")
    from openai import OpenAI

    return OpenAI(api_key=OPENAI_API_KEY)


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
