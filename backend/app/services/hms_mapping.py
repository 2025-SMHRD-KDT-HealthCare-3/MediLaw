from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any


STATUS_MAP = {
    "CONFIRMED": "CONFIRMED",
    "OK": "CONFIRMED",
    "SUCCESS": "CONFIRMED",
    "VERIFIED": "CONFIRMED",
    "\ud655\uc778": "CONFIRMED",
    "WARNING": "WARNING",
    "WARN": "WARNING",
    "\uc8fc\uc758": "WARNING",
    "ERROR": "ERROR",
    "FAILED": "ERROR",
    "FAIL": "ERROR",
    "INVALID": "ERROR",
    "\uc624\ub958": "ERROR",
}


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_law_label(label: str | None) -> tuple[str | None, str | None]:
    """Parse labels like '의료법 제27조' into law name and article number."""
    if not label:
        return None, None

    value = " ".join(str(label).strip().split())
    if not value:
        return None, None

    match = re.search(r"(\uc81c?\s*\d+(?:-\d+)?\s*\uc870(?:\uc758\s*\d+)?)", value)
    if not match:
        return value, None

    article_no = re.sub(r"\s+", "", match.group(1))
    if article_no[0].isdigit():
        article_no = f"\uc81c{article_no}"
    law_name = value[: match.start()].strip() or None
    return law_name, article_no


def clamp_score(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        score = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if score < 0:
        return Decimal("0")
    if score > 100:
        return Decimal("100")
    return score.quantize(Decimal("0.01"))


def map_verification_status(item: dict[str, Any]) -> str:
    raw_status = str(item.get("status") or "").strip().upper()
    mapped = STATUS_MAP.get(raw_status)
    if mapped:
        return mapped

    if item.get("verified") is True:
        return "CONFIRMED"
    if item.get("exists") is False or item.get("clause_accurate") is False:
        return "ERROR"
    return "WARNING"


def verification_reason(item: dict[str, Any]) -> str | None:
    for key in ("reason", "rationale", "message", "note", "raw"):
        value = clean_text(item.get(key))
        if value:
            return value
    return None


def hms_bool(value: Any) -> bool:
    return bool(value) if value is not None else False
