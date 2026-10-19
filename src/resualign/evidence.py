"""Deterministic helpers for resume-backed rewrite evidence."""

from __future__ import annotations

import re
from typing import Any

_ASCII_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#./-]*")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_ASCII_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


def _normalized_whitespace(text: str) -> str:
    return " ".join((text or "").split())


def _ascii_token_in_text(token: str, text: str) -> bool:
    pattern = rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _anchor_supports_keyword(keyword: str, quote: str) -> bool:
    """Return True when the quote contains a meaningful keyword token."""
    quote_text = _normalized_whitespace(quote).casefold()
    keyword_text = _normalized_whitespace(keyword).casefold()
    if not quote_text or not keyword_text:
        return False

    ascii_tokens = [
        token
        for token in _ASCII_TOKEN_RE.findall(keyword_text)
        if len(token) >= 2 and token not in _ASCII_STOPWORDS
    ]
    numeric_tokens = {
        token for token in ascii_tokens if any(char.isdigit() for char in token)
    }
    if any(
        not _ascii_token_in_text(token, quote_text)
        for token in numeric_tokens
    ):
        return False
    if any(_ascii_token_in_text(token, quote_text) for token in ascii_tokens):
        return True

    for run in _CJK_RUN_RE.findall(keyword_text):
        if len(run) == 2:
            probes = {run}
        elif len(run) > 2:
            probes = {run[index : index + 3] for index in range(len(run) - 2)}
        else:
            continue
        if any(probe in quote_text for probe in probes):
            return True
    return False


def evidence_quote_in_text(quote: str, text: str) -> bool:
    """Return True when a quote occurs in text, ignoring whitespace runs."""
    normalized_quote = _normalized_whitespace(quote)
    return bool(normalized_quote) and normalized_quote in _normalized_whitespace(
        text
    )


def anchored_supported_keywords(
    supported_keywords: Any,
    evidence: Any,
    resume_text: str,
) -> tuple[list[str], dict[str, str]]:
    """Return supported keywords whose evidence quote exists in the resume."""
    if not isinstance(supported_keywords, list):
        return [], {}
    evidence_map = evidence if isinstance(evidence, dict) else {}
    keywords: list[str] = []
    kept_evidence: dict[str, str] = {}
    seen: set[str] = set()
    for item in supported_keywords:
        keyword = str(item or "").strip()
        if not keyword or keyword in seen:
            continue
        quote = str(evidence_map.get(keyword) or "").strip()
        if not evidence_quote_in_text(
            quote, resume_text
        ) or not _anchor_supports_keyword(keyword, quote):
            continue
        seen.add(keyword)
        keywords.append(keyword)
        kept_evidence[keyword] = quote
    return keywords, kept_evidence
