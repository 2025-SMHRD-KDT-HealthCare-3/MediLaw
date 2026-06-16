"""OpenAI 생성 LLM 래퍼 (gpt-5.5). 챗봇·PDF 에디터 공용."""
import json
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


def chat_json(messages: list[dict]) -> dict:
    """JSON 모드 단발 생성. 파싱된 dict 반환 (structured output).

    PDF 에디터처럼 구조화된 분석 결과가 필요할 때 사용.
    프롬프트에 'JSON' 단어가 포함돼야 함(OpenAI json_object 요구사항).
    """
    resp = _client().chat.completions.create(
        model=CHAT_MODEL, messages=messages,
        response_format={"type": "json_object"},
    )
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
        )
        return (resp.choices[0].message.content or "").strip() or text
    except LLMUnavailable:
        return text


def ocr_image(b64_png: str) -> str:
    """비전 모델로 이미지(base64 PNG)에서 한국어 텍스트 추출.

    스캔본/이미지 PDF의 OCR fallback 용. 본문만 반환(설명 금지).
    """
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
    )
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
