"""P0 evidence collector (ADR-0059 app self-use run).

Read-only: opens SQLite with mode=ro, never writes the database, never calls the
network or an LLM. It only drafts the runs table from fields the app already
persisted; every manual column (adoption, export, application) stays empty for
the author to fill after the real UI session.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import time
from pathlib import Path

RUN_COLUMNS = [
    "seq", "run_id", "company", "title", "job_id", "resume_id", "resume_sha256",
    "started_at", "finished_at", "wall_seconds", "model", "prompt_version",
    "alignment_status", "alignment_reason", "usable_diffs", "diff_count",
    "invalid_diff_count", "adopted_count", "adopted_diff_ids", "saved_final",
    "final_draft_version", "exported", "export_format", "export_sha256",
    "applied_recorded", "applied_at", "env", "notes",
]
MANUAL_COLUMNS = {
    "seq", "run_id", "resume_sha256", "adopted_count", "adopted_diff_ids",
    "saved_final", "exported", "export_format", "export_sha256",
    "applied_recorded", "env", "notes",
}
SUGGESTION_COLUMNS = [
    "run_id", "suggestion_index", "diff_type", "gate_verdict", "decision",
    "reason", "original_excerpt", "proposed_excerpt",
]


def connect_ro(db_path: str) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve()
    if not path.exists():
        raise SystemExit("database not found: " + str(path))
    con = sqlite3.connect("file:" + path.as_posix() + "?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def _count(raw: str | None) -> int:
    try:
        value = json.loads(raw or "[]")
    except ValueError:
        return 0
    return len(value) if isinstance(value, list) else 0


def _stamp(value: float | None) -> str:
    if not value:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(value))


def collect(con: sqlite3.Connection, tenant: str) -> list[dict]:
    rows = con.execute(
        "SELECT job_id, title, company, job_function, workbench_resume_id, "
        "workbench_job_id, alignment_status, alignment_reason, usable_diffs, "
        "diffs_json, invalid_diffs_json, model, prompt_version, generated_at, "
        "final_draft_version, applied_at, last_alignment_error, updated_at "
        "FROM library_jobs WHERE tenant_id = ? ORDER BY updated_at ASC",
        (tenant,),
    ).fetchall()
    jobs = {}
    for row in con.execute("SELECT * FROM jobs").fetchall():
        jobs[row["job_id"]] = row
    out = []
    for index, row in enumerate(rows, 1):
        analysis = jobs.get(row["workbench_job_id"] or "")
        started = analysis["started_at"] if analysis else None
        finished = analysis["finished_at"] if analysis else None
        wall = round(finished - started, 3) if started and finished else ""
        out.append(
            {
                "seq": index,
                "run_id": "p0-" + str(index).zfill(2) + "-r1",
                "company": row["company"] or "",
                "title": row["title"] or "",
                "job_id": row["job_id"],
                "resume_id": row["workbench_resume_id"] or "",
                "resume_sha256": "",
                "started_at": _stamp(started),
                "finished_at": _stamp(finished),
                "wall_seconds": wall,
                "model": row["model"] or "",
                "prompt_version": row["prompt_version"] or "",
                "alignment_status": row["alignment_status"] or "",
                "alignment_reason": row["alignment_reason"] or "",
                "usable_diffs": row["usable_diffs"] if row["usable_diffs"] is not None else "",
                "diff_count": _count(row["diffs_json"]),
                "invalid_diff_count": _count(row["invalid_diffs_json"]),
                "adopted_count": "",
                "adopted_diff_ids": "",
                "saved_final": "",
                "final_draft_version": row["final_draft_version"] or 0,
                "exported": "",
                "export_format": "",
                "export_sha256": "",
                "applied_recorded": "",
                "applied_at": row["applied_at"] or "",
                "env": "",
                "notes": row["last_alignment_error"] or "",
            }
        )
    return out


def summarise(rows: list[dict]) -> None:
    total = len(rows)
    succeeded = sum(1 for row in rows if row["alignment_status"] == "succeeded")
    failed = sum(1 for row in rows if row["alignment_status"] == "failed")
    usable = sum(1 for row in rows if (row["usable_diffs"] or 0) >= 1)
    saved = sum(1 for row in rows if (row["final_draft_version"] or 0) > 0)
    applied = sum(1 for row in rows if row["applied_at"])
    print("jobs:", total, "| succeeded:", succeeded, "| failed:", failed)
    print("usable>=1:", usable, "| final_draft saved:", saved, "| applied:", applied)
    print("manual columns still empty: adoption / export / env / seq mapping")


def write_csv(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RUN_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in RUN_COLUMNS})
    print("wrote:", out_path)


def write_templates(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "runs.csv").write_text(
        ",".join(RUN_COLUMNS) + "\n", encoding="utf-8-sig"
    )
    (directory / "suggestions.csv").write_text(
        ",".join(SUGGESTION_COLUMNS) + "\n", encoding="utf-8-sig"
    )
    (directory / "evidence-index.md").write_text(
        "| file | kind | sha256 | note |\n| --- | --- | --- | --- |\n",
        encoding="utf-8",
    )
    print("templates:", directory)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="P0 evidence collector (read-only)")
    parser.add_argument("--db", default=str(Path("data") / "jobs.db"))
    parser.add_argument("--tenant", default="local")
    parser.add_argument("--out", default="")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--write-templates", action="store_true")
    parser.add_argument("--dir", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.write_templates:
        write_templates(Path(args.dir or (Path(".scratch") / "p0-templates")))
    if args.check_only and not args.out:
        con = connect_ro(args.db)
        try:
            summarise(collect(con, args.tenant))
        finally:
            con.close()
        return
    con = connect_ro(args.db)
    try:
        rows = collect(con, args.tenant)
    finally:
        con.close()
    summarise(rows)
    if args.out:
        write_csv(rows, Path(args.out))


if __name__ == "__main__":
    main()
