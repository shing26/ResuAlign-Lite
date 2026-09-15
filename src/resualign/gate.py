"""Deterministic fabrication gate for resume tailoring — stdlib only.

This is the portable core of the `true-tailor` skill: one file, no
dependencies, no network. It mirrors the ResuAlign app's fail-closed gate
chain (provenance parse + content check + noop filter) over plain dicts so
that "we only suggest rewrites the resume can already support" is enforced
by code instead of promised in prose.

The app and the skill repo carry a byte-identical copy of this file. Drift
is locked two ways: the shared golden fixtures (canonical in the skill
repo's fixtures/, vendored here under tests/fixtures/gate/ with a hash
manifest) and a parity test that runs the app's real gate chain over the
same fixtures and demands the same verdicts.

CLI contract:
    python gate.py --resume resume.md --diffs diffs.json \
        [--allowlist gap.json|text] [--log run.jsonl] [--round N] \
        [--trigger eval:roundN-1]
stdout: one verdict line per diff + one machine-readable summary line:
    GATE: N diffs / K blocked (missing=x, fabricated=y, noop=z) / resume-sha256=H
exit: 0 ran (even with blocks), 2 usage/IO error.

Append-only JSONL: one line per run with counts, the hashed resume, and a
chain block saying whether the run really follows the previously logged
round and cites it — the difference between "we iterated on this resume"
as evidence and as a claim.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import re
import sys
from datetime import datetime, timezone

# Placeholders the ResuAlign app writes into unfinished drafts
# ("[待人工确认]" = needs human confirmation). Stripped before the content
# check so a placeholder is never reported as a fabricated number; a no-op
# for resumes that never contain that marker.
_METRIC_PLACEHOLDER_RE = re.compile(r"\[[^\]\[]*待人工确认[^\]\[]*\]")
_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9.+#/-]*")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_PROPER_NOUN_MIN_CHARS = 3
_TOKEN_PART_RE = re.compile(r"[-/]")
_SENTENCE_BREAK_RE = re.compile(r"[.!?:;\n]$")

# Words that are legitimately capitalized mid-sentence in English resume
# prose without naming a product, employer or tool. Everything else that is
# capitalized mid-sentence must be findable in the source text: that is
# where "Kafka" and "Acme" hide. The bias is deliberate — a visible false
# block is recoverable, an invisible false pass is the whole claim failing.
_ENTITY_STOP_WORDS = frozenset(
    """
    january february march april may june july august september october
    november december monday tuesday wednesday thursday friday saturday
    sunday senior junior lead staff principal engineer engineering
    developer manager director team company client customer business
    product project projects software services solutions experience
    education skills summary highlights awards honors year month week
    full part remote onsite hybrid north south east west university
    college bachelor master doctor first second third current recent
    global regional internal external public private open cross
    """.split()
)

_FUZZY_MIN_QUOTE_CHARS = 12
_FUZZY_COVERAGE_THRESHOLD = 0.85
_FUZZY_LONG_QUOTE_CHARS = 60
_FUZZY_LONG_COVERAGE_THRESHOLD = 0.75


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _normalized_char_map(text: str) -> tuple[str, list[int]]:
    norm_chars: list[str] = []
    map_to_original: list[int] = []
    index = 0
    length = len(text)
    while index < length:
        if text[index].isspace():
            start = index
            while index < length and text[index].isspace():
                index += 1
            norm_chars.append(" ")
            map_to_original.append(start)
        else:
            norm_chars.append(text[index])
            map_to_original.append(index)
            index += 1
    return "".join(norm_chars), map_to_original


def _resolve_span(
    quote: str, resume_text: str, start_index: int = 0
) -> tuple[int, int] | None:
    if not quote:
        return None
    exact = resume_text.find(quote, start_index)
    if exact >= 0:
        return (exact, exact + len(quote))
    normalized_text, char_map = _normalized_char_map(resume_text)
    normalized_quote = _normalize_whitespace(quote)
    normalized_start = bisect.bisect_left(char_map, start_index) if start_index else 0
    position = normalized_text.find(normalized_quote, normalized_start)
    if position < 0 or position >= len(char_map):
        return None
    start = char_map[position]
    end_index = position + len(normalized_quote)
    end = char_map[end_index] if end_index < len(char_map) else len(resume_text)
    return (start, end)


def _fuzzy_locate_quote(
    quote: str, resume_text: str
) -> tuple[tuple[int, int] | None, str]:
    """Port of tailor._fuzzy_locate_quote (salvage misquoted provenance)."""
    import difflib

    norm_text, char_map = _normalized_char_map(resume_text)
    norm_quote = _normalize_whitespace(quote)
    qlen = len(norm_quote)
    min_chars = max(_FUZZY_MIN_QUOTE_CHARS, int(qlen * 0.25))
    coverage_bar = (
        _FUZZY_LONG_COVERAGE_THRESHOLD
        if qlen >= _FUZZY_LONG_QUOTE_CHARS
        else _FUZZY_COVERAGE_THRESHOLD
    )
    if qlen < min_chars or not norm_text:
        return None, ""
    text_len = len(norm_text)

    def span_for(norm_start: int, norm_end: int) -> tuple[int, int]:
        norm_start = max(0, min(norm_start, text_len - 1))
        norm_end = max(norm_start + 1, min(norm_end, text_len))
        return (char_map[norm_start], char_map[norm_end - 1] + 1)

    candidates: list[tuple[float, tuple[int, int]]] = []

    head = norm_quote[:16]
    anchors: list[int] = []
    pos = norm_text.find(head)
    while pos >= 0 and len(anchors) < 20:
        anchors.append(pos)
        pos = norm_text.find(head, pos + 1)
    if not anchors:
        mid = norm_quote[max(0, qlen // 2 - 8) : max(0, qlen // 2 - 8) + 16]
        if len(mid) >= 8:
            pos = norm_text.find(mid)
            while pos >= 0 and len(anchors) < 20:
                anchors.append(max(0, pos - qlen // 2))
                pos = norm_text.find(mid, pos + 1)
    pad = qlen // 5
    for anchor in anchors:
        window_start = max(0, anchor - pad)
        window_end = min(text_len, anchor + qlen + pad)
        candidate = norm_text[window_start:window_end]
        if not candidate:
            continue
        matcher = difflib.SequenceMatcher(None, norm_quote, candidate)
        blocks = [b for b in matcher.get_matching_blocks() if b.size]
        matched = sum(b.size for b in blocks)
        coverage = matched / qlen
        if coverage >= coverage_bar and blocks:
            first, last = blocks[0], blocks[-1]
            span = span_for(
                window_start + first.b, window_start + last.b + last.size
            )
            candidates.append((coverage, span))

    if not candidates:
        for fraction in (0.9, 0.8, 0.7, 0.6):
            cut = int(qlen * fraction)
            if cut < _FUZZY_MIN_QUOTE_CHARS:
                break
            prefix = norm_quote[:cut]
            pos = norm_text.find(prefix)
            if pos >= 0:
                candidates.append((fraction, span_for(pos, pos + cut)))
                break
            suffix = norm_quote[qlen - cut :]
            pos = norm_text.find(suffix)
            if pos >= 0:
                candidates.append((fraction, span_for(pos, pos + cut)))
                break

    if not candidates:
        return None, ""
    coverage, span = max(candidates, key=lambda item: item[0])

    line_start = resume_text.rfind("\n", 0, span[0]) + 1
    expanded_start = line_start
    marker = re.match(
        r"\s*(?:[-•▪●○◦·∙‣]|\d+(?:[.、)]))\s+", resume_text[line_start:]
    )
    if marker:
        expanded_start = line_start + marker.end()
    line_end = resume_text.find("\n", span[1])
    if line_end < 0:
        line_end = len(resume_text)
    expanded = (expanded_start, line_end)
    return expanded, resume_text[expanded[0] : expanded[1]]


def _unsupported_content(proposed: str, *supported_texts: str) -> list[str]:
    """Port of tailor._unsupported_content (#74 content-level gate)."""
    text = _METRIC_PLACEHOLDER_RE.sub(" ", proposed or "")
    corpus = "\n".join(t for t in supported_texts if t)
    corpus_numbers = set(_NUMBER_RE.findall(corpus.replace(",", "")))
    corpus_lower = corpus.lower()
    cjk_context = bool(_CJK_RE.search(text))

    def _at_sentence_start(index: int) -> bool:
        before = text[:index].rstrip()
        return not before or bool(_SENTENCE_BREAK_RE.search(before[-1:]))

    def _noun_candidate(token: str, at_sentence_start: bool) -> bool:
        if token.upper() == token or any(c.isupper() for c in token[1:]):
            return True  # acronym or mixed case: QPS, FastAPI, PyTorch
        if cjk_context:
            return True  # inside Chinese prose, a Latin word is a term
        if not token[:1].isupper():
            return False
        # English prose capitalizes freely at the head of a sentence, so a
        # leading "Built"/"Led" carries no signal; mid-sentence it names something.
        if at_sentence_start or token.lower() in _ENTITY_STOP_WORDS:
            return False
        return True

    unsupported: list[str] = []
    for number in _NUMBER_RE.findall(text.replace(",", "")):
        if number not in corpus_numbers:
            unsupported.append(f"number {number}")
    seen_tokens: set[str] = set()
    for match in _LATIN_TOKEN_RE.finditer(text):
        token = match.group(0)
        key = token.lower()
        if key in seen_tokens:
            continue
        seen_tokens.add(key)
        if len(token) < _PROPER_NOUN_MIN_CHARS or token.islower():
            continue
        if key in corpus_lower:
            continue
        # "Kafka-backed" is one regex token; the name inside it is what needs
        # a source, and a resume that says Kafka should not block the compound.
        parts = [
            part
            for part in _TOKEN_PART_RE.split(token)
            if len(part) >= _PROPER_NOUN_MIN_CHARS and not part.islower()
        ]
        token_starts_sentence = _at_sentence_start(match.start())
        for position, part in enumerate(parts or [token]):
            part_at_start = token_starts_sentence and position == 0
            if _noun_candidate(part, part_at_start) and (
                part.lower() not in corpus_lower
            ):
                unsupported.append(f"term {part}")
                break
    return unsupported


def allowlist_corpus(payload: str) -> str:
    """Gap-report JSON allowlist extraction (port of tailor._gap_support_text);
    plain text passes through unchanged."""
    try:
        data = json.loads(payload or "{}")
    except (ValueError, TypeError):
        return payload or ""
    if not isinstance(data, dict):
        return payload or ""
    parts: list[str] = []
    for key in (
        "missing_keywords",
        "misaligned_emphasis",
        "strength_matches",
        "business_scenarios",
        "jd_context",
    ):
        value = data.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(item) for item in value)
    return "\n".join(parts) if parts else (payload or "")


def _is_noop(diff_type: str, original: str, proposed: str) -> bool:
    """Port of api/services/jobs._is_noop_diff (A2): modify/remove only,
    whitespace-stripped comparison on both sides."""
    if diff_type not in ("modify", "remove"):
        return False
    o = (original or "").strip()
    p = (proposed or "").strip()
    return bool(o) and o == p


def resolve_provenance(
    item: dict, resume_text: str
) -> tuple[bool, str, str, bool]:
    """Mirror tailor.parse_diff_with_provenance on plain dicts.

    Returns (valid, provenance, corrected_original, salvaged).
    """
    diff_type = item.get("type", "modify")
    if diff_type not in {"modify", "add", "remove"}:
        diff_type = "modify"
    original = item.get("original", "")
    quote = str(item.get("provenance_quote") or item.get("provenance") or "").strip()
    if not quote and diff_type in ("modify", "remove") and str(original).strip():
        quote = str(original).strip()
    salvaged = False
    valid = False
    span = _resolve_span(quote, resume_text)
    if span is None and quote and (":" in quote or "：" in quote):
        prefix, stripped = (
            part.strip() for part in re.split(r"[:：]", quote, maxsplit=1)
        )
        if stripped:
            heading = str(item.get("section") or "").strip() or prefix
            heading_index = resume_text.find(heading) if heading else -1
            candidates = [(stripped, 0)]
            if heading_index >= 0:
                candidates.insert(0, (stripped, heading_index))
            for candidate, start_index in candidates:
                span = _resolve_span(candidate, resume_text, start_index)
                if span is not None:
                    break
    if quote and span is not None:
        valid = True
    elif quote:
        fuzzy_span, actual_text = _fuzzy_locate_quote(quote, resume_text)
        if fuzzy_span is not None:
            quote = actual_text
            if diff_type in ("modify", "remove") and actual_text:
                original = actual_text
            valid = True
            salvaged = True
    return valid, quote if valid else "", str(original or ""), salvaged


def verdict(item: dict, resume_text: str, jd_allowlist: str = "") -> dict:
    """One diff -> one gate verdict, mirroring the app's fail-closed chain
    (parse -> add-empty -> #74 content -> strict provenance -> A2 noop)."""
    diff_type = item.get("type", "modify")
    if diff_type not in {"modify", "add", "remove"}:
        diff_type = "modify"
    proposed = str(item.get("proposed", "") or "")
    valid, provenance, original, salvaged = resolve_provenance(item, resume_text)
    result = {
        "diff_id": str(item.get("diff_id") or ""),
        "type": diff_type,
        "original": original,
        "provenance": provenance,
        "salvaged": salvaged,
        "verdict": "usable",
        "detail": "",
    }
    if diff_type == "add" and not original.strip():
        result["verdict"] = "blocked"
        result["reason"] = "missing"
        result["detail"] = "add without a supporting sentence: original must be verbatim resume text"
        return result
    # #119 parity: add-type diffs are content-checked too (anchor truth does
    # not certify the numbers/entities inside proposed).
    if proposed and diff_type in {"modify", "remove", "add"}:
        unsupported = _unsupported_content(proposed, resume_text, original, jd_allowlist)
        if unsupported:
            result["verdict"] = "blocked"
            result["reason"] = "fabricated"
            result["detail"] = "; ".join(unsupported) + " has no source in the resume"
            return result
    if not valid:
        result["verdict"] = "blocked"
        result["reason"] = "missing"
        result["detail"] = "provenance quote cannot be located in the resume"
        return result
    if _is_noop(diff_type, original, proposed):
        result["verdict"] = "blocked"
        result["reason"] = "noop"
        result["detail"] = "proposed is character-for-character the original"
        return result
    result["reason"] = "verified"
    return result


def run_gate(
    diffs: list[dict], resume_text: str, jd_allowlist: str = ""
) -> dict:
    results = [verdict(item, resume_text, jd_allowlist) for item in diffs]
    counts = {"missing": 0, "fabricated": 0, "noop": 0}
    usable = 0
    for r in results:
        if r["verdict"] == "usable":
            usable += 1
        else:
            counts[r["reason"]] += 1
    blocked = sum(counts.values())
    resume_hash = hashlib.sha256(resume_text.encode("utf-8")).hexdigest()
    summary = (
        f"GATE: {len(results)} diffs / {blocked} blocked "
        f"(missing={counts['missing']}, fabricated={counts['fabricated']}, "
        f"noop={counts['noop']}) / resume-sha256={resume_hash[:12]}"
    )
    return {
        "results": results,
        "usable": usable,
        "blocked": counts,
        "resume_sha256": resume_hash,
        "summary": summary,
    }


def append_log(
    log_path: str, report: dict, round_no: int, trigger: str
) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "resume_sha256": report["resume_sha256"],
        "round": round_no,
        "trigger": trigger,
        "diffs": len(report["results"]),
        "usable": report["usable"],
        "blocked": report["blocked"],
        "chain": chain_state(log_path, round_no, trigger),
    }
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def last_logged_round(log_path: str) -> int | None:
    """Round number of the last readable JSONL line, None if no log yet."""
    try:
        with open(log_path, encoding="utf-8") as fh:
            previous = None
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    value = json.loads(line).get("round")
                except ValueError:
                    continue
                if isinstance(value, int):
                    previous = value
            return previous
    except OSError:
        return None


def chain_state(log_path: str, round_no: int, trigger: str) -> dict:
    """Round-chain check against the log's tail (dogfood revision R5).

    Round 1 with an empty log is trivially sound; any later round must be
    the successor of the last logged round and name that round in its
    trigger, which is what stops "round 7" from being pasted over a run
    that never happened.
    """
    previous = last_logged_round(log_path)
    if previous is None:
        return {"prev_round": None, "cites_prev": True}
    contiguous = round_no == previous + 1
    cites = f"round{previous}" in (trigger or "")
    return {"prev_round": previous, "cites_prev": contiguous and cites}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # Verdict details carry CJK text; when stdout is a pipe under a GBK
    # locale (typical Windows + agent capture) print() would crash.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    parser.add_argument("--resume", required=True, help="master resume markdown/text")
    parser.add_argument("--diffs", required=True, help="diffs JSON (list or {diffs:[…]})")
    parser.add_argument("--allowlist", default="", help="gap-report JSON or JD text")
    parser.add_argument("--log", default="", help="append JSONL run log to this path")
    parser.add_argument("--round", type=int, default=1)
    parser.add_argument("--trigger", default="manual")
    args = parser.parse_args(argv)
    try:
        resume_text = open(args.resume, encoding="utf-8").read()
        raw = json.load(open(args.diffs, encoding="utf-8"))
        allow = (
            allowlist_corpus(open(args.allowlist, encoding="utf-8").read())
            if args.allowlist
            else ""
        )
    except (OSError, ValueError) as exc:
        print(f"gate error: {exc}", file=sys.stderr)
        return 2
    diffs = raw.get("diffs") if isinstance(raw, dict) else raw
    if not isinstance(diffs, list):
        print("gate error: diffs.json must be a list or {\"diffs\": […]}", file=sys.stderr)
        return 2
    report = run_gate(diffs, resume_text, allow)
    for r in report["results"]:
        mark = "OK " if r["verdict"] == "usable" else "BLOCK"
        line = f"{mark} {r['diff_id']} [{r['type']}/{r.get('reason','')}] {r['detail']}"
        if r["salvaged"]:
            line += " (quote corrected to the source line)"
        print(line)
    print(report["summary"])
    if args.log:
        append_log(args.log, report, args.round, args.trigger)
    return 0


if __name__ == "__main__":
    sys.exit(main())
