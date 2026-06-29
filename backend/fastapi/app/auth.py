"""인증(x-api-key) + 간단한 IP/키 기반 레이트리밋 — lawbot.org 정책 모사."""
import time
from collections import deque

from fastapi import Header, HTTPException, Request

from app.config import API_KEYS, RATE_LIMIT_PER_MIN

# {식별자: deque[호출시각]} — 슬라이딩 윈도우(1분)
_calls: dict[str, deque] = {}


def _rate_limit(identifier: str) -> None:
    now = time.time()
    # 식별자 누적에 의한 메모리 누수 방지 — 가끔 만료된(1분 무호출) 항목 정리.
    if len(_calls) > 4096:
        for k in [k for k, d in _calls.items() if not d or now - d[-1] > 60]:
            _calls.pop(k, None)
    dq = _calls.setdefault(identifier, deque())
    while dq and now - dq[0] > 60:
        dq.popleft()
    if len(dq) >= RATE_LIMIT_PER_MIN:
        raise HTTPException(429, "분당 호출 한도를 초과했습니다 (rate limit)")
    dq.append(now)


async def require_api_key(
    request: Request,
    x_api_key: str = Header(default="", alias="x-api-key"),
    x_forwarded_for: str = Header(default="", alias="x-forwarded-for"),
) -> str:
    """모든 /v1 요청에 적용. API_KEYS 미설정 시 인증 생략(로컬 개발).

    레이트리밋 식별자: 키가 있으면 키 단위. 없으면 X-Forwarded-For 첫 IP(Node가
    실제 클라이언트 IP를 전달하는 경우) → 없으면 직접 연결 IP. ⚠️ React→Node→FastAPI
    구조에서 Node가 XFF를 안 실으면 모든 요청이 Node IP 하나로 묶인다(=전역 공유 버킷).
    실사용자 단위 레이트리밋은 Node에서 처리 권장(docs/handoff-node-rate-limit.md 참고).
    """
    if API_KEYS:
        if x_api_key not in API_KEYS:
            raise HTTPException(401, "유효한 x-api-key 헤더가 필요합니다")
        identifier = x_api_key
    else:
        fwd = x_forwarded_for.split(",")[0].strip() if x_forwarded_for else ""
        identifier = fwd or (request.client.host if request.client else "anon")
    _rate_limit(identifier)
    return identifier
