"""OpenAI 생성 LLM 래퍼 (gpt-5.5). 챗봇·향후 PDF 에디터 공용."""
from collections.abc import Iterator

from app.config import CHAT_MODEL, OPENAI_API_KEY


class LLMUnavailable(RuntimeError):
    """OPENAI_API_KEY 미설정 등 LLM 사용 불가."""


def _client():
    if not OPENAI_API_KEY:
        raise LLMUnavailable("OPENAI_API_KEY 가 설정되지 않았습니다")
    from openai import OpenAI

    return OpenAI(api_key=OPENAI_API_KEY)


def chat(messages: list[dict]) -> str:
    """단발 생성. 답변 텍스트 반환."""
    resp = _client().chat.completions.create(model=CHAT_MODEL, messages=messages)
    return resp.choices[0].message.content or ""


def chat_stream(messages: list[dict]) -> Iterator[str]:
    """토큰 스트리밍 (delta 텍스트만 yield)."""
    stream = _client().chat.completions.create(
        model=CHAT_MODEL, messages=messages, stream=True
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
