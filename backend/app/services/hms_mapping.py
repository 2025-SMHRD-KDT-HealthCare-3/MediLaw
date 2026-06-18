from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any


def parse_law_label(label: str | None) -> tuple[str | None, str | None]:
    """Parse labels like '의료법 제27조' into law name and article number."""
    if not label:
        return None, None

    value = " ".join(str(label).strip().split())
    if not value:
        return None, None

    match = re.search(r"(제?\s*\d+(?:-\d+)?\s*조(?:의\s*\d+)?)", value)
    if not match:
        return value, None

    article_no = re.sub(r"\s+", "", match.group(1))
    if article_no[0].isdigit():
        article_no = f"제{article_no}"
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
    if raw_status in {"CONFIRMED", "확인", "OK", "SUCCESS", "VERIFIED"}:
        return "CONFIRMED"
    if raw_status in {"ERROR", "오류", "FAILED", "FAIL", "INVALID"}:
        return "ERROR"
    if raw_status in {"WARNING", "주의", "WARN"}:
        return "WARNING"

    if item.get("verified") is True:
        return "CONFIRMED"
    if item.get("exists") is False or item.get("clause_accurate") is False:
        return "ERROR"
    return "WARNING"


def verification_reason(item: dict[str, Any]) -> str | None:
    for key in ("reason", "rationale", "message", "raw"):
        value = item.get(key)
        if value:
            return str(value)
    return None
