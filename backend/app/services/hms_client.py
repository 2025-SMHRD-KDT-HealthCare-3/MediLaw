from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 120
DOCUMENT_TIMEOUT = 180


def _url(path: str) -> str:
    return f"{settings.HMS_URL.rstrip('/')}/{path.lstrip('/')}"


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if settings.HMS_API_KEY:
        headers["x-api-key"] = settings.HMS_API_KEY
    if extra:
        headers.update(extra)
    return headers


def _hms_error(exc: httpx.HTTPError) -> HTTPException:
    if isinstance(exc, httpx.TimeoutException):
        return HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="HMS server response timed out",
        )
    if isinstance(exc, httpx.ConnectError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="HMS server is unavailable",
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="HMS request failed",
    )


def post_json(path: str, payload: dict[str, Any], *, timeout: int = DEFAULT_TIMEOUT) -> dict:
    try:
        response = httpx.post(_url(path), json=payload, timeout=timeout, headers=_headers())
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        logger.exception("HMS JSON request failed path=%s", path)
        raise _hms_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="HMS response was not valid JSON",
        ) from exc

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="HMS response was not an object",
        )
    return data


def post_multipart(
    path: str,
    *,
    data: dict[str, Any] | None = None,
    files: dict[str, tuple[str, bytes, str]] | None = None,
    timeout: int = DOCUMENT_TIMEOUT,
) -> dict:
    try:
        response = httpx.post(_url(path), data=data, files=files, timeout=timeout, headers=_headers())
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        logger.exception("HMS multipart request failed path=%s", path)
        raise _hms_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="HMS response was not valid JSON",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="HMS response was not an object",
        )
    return payload
