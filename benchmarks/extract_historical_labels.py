"""Extract historical apply/skip verdicts from jd_text (ADR-0065 A1 fallback).

The library's jd_text rows carry the author's ingest-time analysis, which usually
ends with an explicit verdict ("值得投", "建议不投", "可作为保底投", "优先级最高").
Those verdicts were written before any embedding-based ranker existed, so using
them as labels is not circular with the vector ranker.

Limitations (must be disclosed next to any number produced from them):
  - they were written for the resume profile of the time, not per-resume;
  - the analysis was LLM-assisted, so this is a WEAK label set, not human gold;
  - conflict/uncertain rows are dropped rather than guessed.

Usage:
  python benchmarks/extract_historical_labels.py --stats
  python benchmarks/extract_historical_labels.py --labels
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "jobs.db"
OUT_DIR = ROOT / ".scratch" / "ranking-a1"

# High-precision verdict only. "别投" was removed after it matched 分别投递;
# "可投" was removed after it matched 本科可投 (a qualification, not a verdict).
NEG = [
    "建议不投",
    "不建议投",
    "不投递",
    "不值得投",
    "放弃投递",
    "建议放弃",
    "不推荐投",
]
POS = [
    "值得投",
    "建议投递",
    "建议投",
    "必投",
    "优先投",
    "优先级最高",
    "优先级第一",
    "保底投",
    "强烈建议投",
]
# Phrases that mention applying but are not a verdict about this posting.
NOISE = ["建议投递时", "投递时", "投递前", "投递后", "网申时", "投递入口"]

SPLIT = re.compile(r"[。！？\n]|(?<=[；;])\s*")


def connect(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect("file:" + db.resolve().as_posix() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SPLIT.split(text or "") if s.strip()]


def classify(sentence: str) -> str | None:
    if any(noise in sentence for noise in NOISE):
        text = sentence
        for noise in NOISE:
            text = text.replace(noise, "")
    else:
        text = sentence
    has_neg = any(pattern in text for pattern in NEG)
    has_pos = any(pattern in text for pattern in POS)
    if has_neg and not has_pos:
        return "neg"
    if has_pos and not has_neg:
        return "pos"
    return None  # conflict or bare mention: dropped


def verdict_for(text: str) -> tuple[str | None, str]:
    seen: list[tuple[str, str]] = []
    for sentence in sentences(text):
        if "投" not in sentence:
            continue
        label = classify(sentence)
        if label:
            seen.append((label, sentence))
    if not seen:
        return None, ""
    labels = {label for label, _ in seen}
    if len(labels) > 1:
        # Conflicting doc: only trust a final conclusion sentence.
        tail = [item for item in seen if any(k in item[1] for k in ("结论", "最终", "综上", "建议："))]
        if len({label for label, _ in tail}) == 1:
            return tail[-1]
        return None, "conflict"
    return seen[-1]


def load_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT job_id, title, job_function, jd_text FROM library_jobs "
        "WHERE tenant_id = 'local' AND jd_text IS NOT NULL"
    ).fetchall()


def stats(rows: list[sqlite3.Row], sample_ids: set[str]) -> None:
    counts = Counter()
    examples = []
    labels = {}
    for row in rows:
        verdict, evidence = verdict_for(row["jd_text"])
        labels[row["job_id"]] = verdict
        counts[verdict or "none"] += 1
        if row["job_id"] in sample_ids and verdict and len(examples) < 12:
            examples.append(
                {
                    "job_id": row["job_id"],
                    "title": row["title"],
                    "verdict": verdict,
                    "evidence": evidence[-160:],
                }
            )
    sample_counts = Counter(labels.get(job_id) for job_id in sample_ids)
    payload = {
        "all_jobs": dict(counts),
        "sampled_50": {str(k): v for k, v in sample_counts.items()},
        "examples": examples,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "historical-verdicts.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print("all jobs:", dict(counts))
    print("sampled 50:", {str(k): v for k, v in sample_counts.items()})
    print("examples ->", OUT_DIR / "historical-verdicts.json")


def write_labels(rows: list[sqlite3.Row], sample_ids: list[str]) -> None:
    labels = json.loads((OUT_DIR / "labels-zeros.json").read_text(encoding="utf-8"))
    by_id = {row["job_id"]: row for row in rows}
    items = []
    dropped = 0
    for item in labels["items"]:
        job_id = item["job_id"]
        row = by_id.get(job_id)
        if row is None:
            dropped += 1
            continue
        verdict, evidence = verdict_for(row["jd_text"])
        if not verdict:
            dropped += 1
            continue
        items.append(
            {
                "job_id": job_id,
                "title": row["title"],
                "family": (row["job_function"] or "").strip(),
                "relevant": {
                    labels["resumes"]["A"]["id"]: "1" if verdict == "pos" else "0",
                    labels["resumes"]["B"]["id"]: "",
                },
                "label_source": "historical_verdict",
                "evidence": evidence[-160:],
            }
        )
    out = {
        "adr": "ADR-0065",
        "label_kind": "weak_historical_verdict",
        "created_at": "2026-10-27",
        "source": "jd_text ingest analysis (pipeline-written, author-curated)",
        "limitations": [
            "written for the resume profile of the time; per-resume mapping is A-only",
            "LLM-assisted analysis => weak label, not human gold",
            "conflicting or bare-mention rows dropped",
        ],
        "resumes": labels["resumes"],
        "items": items,
    }
    path = OUT_DIR / "labels-historical.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    pos = sum(1 for item in items if item["relevant"][labels["resumes"]["A"]["id"]] == "1")
    print("labels ->", path)
    print("labelled items:", len(items), "| positives:", pos, "| dropped:", dropped)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="extract historical verdict labels")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--labels", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    con = connect(Path(args.db))
    try:
        rows = load_rows(con)
    finally:
        con.close()
    zeros = json.loads((OUT_DIR / "labels-zeros.json").read_text(encoding="utf-8"))
    sample_ids = [item["job_id"] for item in zeros["items"]]
    if args.stats or not args.labels:
        stats(rows, set(sample_ids))
    if args.labels:
        write_labels(rows, sample_ids)


if __name__ == "__main__":
    main()
