from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException, status

from app.core.config import settings


DEFAULT_TIMEOUT = 120
DOCUMENT_TIMEOUT = 180


def _url(path: str) -> str:
    return f"{settings.HMS_URL.rstrip('/')}/{path.lstrip('/')}"


def post_json(path: str, payload: dict[str, Any], *, timeout: int = DEFAULT_TIMEOUT) -> dict:
    try:
        response = httpx.post(_url(path), json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"HMS request failed: {exc}",
        ) from exc
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
        response = httpx.post(_url(path), data=data, files=files, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"HMS request failed: {exc}",
        ) from exc
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
