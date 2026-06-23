"""인증(x-api-key) + 간단한 IP/키 기반 레이트리밋 — lawbot.org 정책 모사."""
import time
from collections import deque

from fastapi import Header, HTTPException, Request

from app.config import API_KEYS, RATE_LIMIT_PER_MIN

# {식별자: deque[호출시각]} — 슬라이딩 윈도우(1분)
_calls: dict[str, deque] = {}


def _rate_limit(identifier: str) -> None:
    now = time.time()
    dq = _calls.setdefault(identifier, deque())
    while dq and now - dq[0] > 60:
        dq.popleft()
    if len(dq) >= RATE_LIMIT_PER_MIN:
        raise HTTPException(429, "분당 호출 한도를 초과했습니다 (rate limit)")
    dq.append(now)


async def require_api_key(
    request: Request,
    x_api_key: str = Header(default="", alias="x-api-key"),
) -> str:
    """모든 /v1 요청에 적용. API_KEYS 미설정 시 인증 생략(로컬 개발)."""
    if API_KEYS:
        if x_api_key not in API_KEYS:
            raise HTTPException(401, "유효한 x-api-key 헤더가 필요합니다")
        identifier = x_api_key
    else:
        identifier = request.client.host if request.client else "anon"
    _rate_limit(identifier)
    return identifier
