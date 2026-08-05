"""Deterministic salary range extraction for Chinese job descriptions."""

from __future__ import annotations

import re
from typing import Optional

_NEGOTIABLE = re.compile(r"薪资\s*面议|面议|negotiable", re.IGNORECASE)
_RANGE = re.compile(
    r"(?P<low>\d+(?:\.\d+)?)\s*[kK]?\s*[-—~到]\s*"
    r"(?P<high>\d+(?:\.\d+)?)\s*(?P<unit>[kK万])"
)
_WAN_RANGE = re.compile(
    r"(?P<low>\d+(?:\.\d+)?)\s*万\s*[-—~到]\s*"
    r"(?P<high>\d+(?:\.\d+)?)\s*万"
)
_RAW_RANGE = re.compile(
    r"(?P<low>\d{4,})\s*[-—~到]\s*(?P<high>\d{4,})\s*元(?:\s*/\s*月)?"
)
_FLOOR_K = re.compile(r"(?P<amount>\d+(?:\.\d+)?)\s*[kK]\s*以上")
_WAN_ANNUAL = re.compile(r"(?P<amount>\d+(?:\.\d+)?)\s*万\s*/\s*年")

_SALARY_CONTEXT = re.compile(r"月薪|每月|薪资|薪酬|工资|年薪")


def _round2(value: float) -> float:
    return round(value, 2)


def extract_salary_range(text: str) -> tuple[Optional[float], Optional[float]]:
    """Extract a monthly salary range in yuan from JD text.

    Supported formats include ``15-25K``, ``20k-30k``, ``30-50万/年``,
    ``15K以上``, and ``薪资面议``. Returns ``(None, None)`` when no
    recognizable salary appears.
    """
    if not text:
        return (None, None)
    if _NEGOTIABLE.search(text):
        return (None, None)

    match = _RANGE.search(text)
    if match:
        low = float(match.group("low"))
        high = float(match.group("high"))
        if match.group("unit") == "万":
            tail = text[match.end() : match.end() + 8]
            monthly = ("/月" in tail) or ("月薪" in tail) or ("每月" in tail)
            multiplier = 10000 if monthly else 10000 / 12
            low = low * multiplier
            high = high * multiplier
            return (_round2(low), _round2(high))
        return (
            low * 1000,
            high * 1000,
        )

    match = _WAN_RANGE.search(text)
    if match:
        low = float(match.group("low")) * 10000
        high = float(match.group("high")) * 10000
        monthly = "/年" not in text and "年薪" not in text
        return (low, high) if monthly else (_round2(low / 12), _round2(high / 12))

    match = _RAW_RANGE.search(text)
    if match and _SALARY_CONTEXT.search(text):
        return (
            float(match.group("low")),
            float(match.group("high")),
        )

    match = _FLOOR_K.search(text)
    if match:
        return (float(match.group("amount")) * 1000, None)

    match = _WAN_ANNUAL.search(text)
    if match:
        monthly = float(match.group("amount")) * 10000 / 12
        return (_round2(monthly), None)

    return (None, None)
