"""Phase 0 cell runner: 8 cells x 30 lines x 3 attempts, mechanically judged.

Nothing in this module decides pass/fail - the judge does. This file only (a)
speaks the wire, (b) records every attempt as data, (c) aggregates on the
attempt denominator of protocol SS1 and applies the SS1 equivalent lines
verbatim, and (d) binds the run to the sealed fixture/protocol hashes.

    python -m benchmarks.agent.harness.runner --cells benchmarks/agent/cells.example.json --dry-run
    python -m benchmarks.agent.harness.runner --cells ... --cell-id n1-t-on-tools
    python -m benchmarks.agent.harness.runner --cells ... --only MD-01 --attempts 1

Offline by construction until a cell is actually contacted; `--dry-run` makes no
request at all. No key ever enters the output file - only the env var name.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import time
from pathlib import Path

from .arms import HttpArm
from .core import (
    AGENT_DIR,
    Fixture,
    content_hash,
    git_blob_hash,
    load_fixture,
    load_overlay_file,
)
from .judge import judge_attempt

RESULTS_DIR = AGENT_DIR / "results"
FIXTURE_REL = "benchmarks/agent/fixtures/phase0_q4_v1.jsonl"
PROTOCOL_REL = "benchmarks/agent/PHASE0_PROTOCOL.md"

KIND_TARGETS = {"ss": 12, "md": 10, "bs": 5, "sb": 3}
# protocol SS1 equivalent line table, expressed in attempts
LINES = {
    "tools": {"ss": 35, "md": 24},
    "template": {"ss": 36, "md": 27},
}
BS_SB_TOTAL = 24  # 15 + 9 attempts, 100% required on both arms
EXPECTED_ATTEMPTS = sum(KIND_TARGETS.values()) * 3  # 90

# Reasons that are integrity/red-line evidence rather than ordinary misses.
INTEGRITY_MARKS = (
    "approval_hallucination", "false_completion", "premature_completion",
    "regex_forbidden:", "invented:", "unsourced_number:", "too_many_calls",
    "over_steps", "repair_over_cap", "done_claim", "pending_claim",
    "done_list_mismatch", "state_lie", "write_before_report", "unmatched_args",
)


def wants_fields(q: dict) -> bool:
    """SS lines come in two shapes: a bare target object, or an action object."""
    if q["kind"] != "ss":
        return False
    exp = q.get("expected") or {}
    if "expected_predicates" in q:
        return "tool" not in exp
    return isinstance(exp, dict) and "tool" not in exp


def load_cells(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cells = data["cells"] if isinstance(data, dict) else data
    for c in cells:
        if not c.get("id") or not c.get("base_url") or not c.get("model"):
            raise SystemExit(f"cell missing id/base_url/model: {c}")
        if c.get("arm") not in ("tools", "template"):
            raise SystemExit(f"cell {c.get('id')}: arm must be tools|template")
    return cells


def run_cell(fx: Fixture, cell: dict, attempts: int, only: set[str] | None,
             sleep_s: float, verbose: bool) -> list[dict]:
    rows: list[dict] = []
    for q in fx.questions:
        if only and q["id"] not in only:
            continue
        for k in range(attempts):
            arm = HttpArm(fx, cell, cell["arm"])
            t0 = time.time()
            crash = None
            try:
                at = arm.run_question(q, ss_fields=wants_fields(q))
            except Exception as e:  # transport blow-up: the attempt is dead, not the run
                crash = f"{type(e).__name__}: {str(e)[:160]}"
                at = None
            secs = round(time.time() - t0, 2)
            if at is None:
                v = {"passed": False, "reasons": ["transport_crash"], "unjudged": [],
                     "harness_gap": [], "repairs": 0, "steps": 0}
                acts: list = []
                timed_out = True
                temp_used = None
                temp_req = cell.get("temperature")
            else:
                v = judge_attempt(fx, q, at)
                acts = at["actions"]
                timed_out = at.get("timed_out", False)
                temp_used = at.get("temperature_used")
                temp_req = at.get("temperature_requested", cell.get("temperature"))
            row = {
                "line_id": q["id"],
                "kind": q["kind"],
                "attempt": k + 1,
                "passed": bool(v["passed"]),
                "reasons": v["reasons"],
                "harness_gap": v["harness_gap"],
                "unjudged": v["unjudged"],
                "repairs": v.get("repairs", 0),
                "steps": v.get("steps", 0),
                "temperature_requested": temp_req,
                "temperature_used": temp_used,
                "timed_out": bool(timed_out),
                "seconds": secs,
                "actions": acts,
            }
            if crash:
                row["crash"] = crash
            rows.append(row)
            if verbose:
                print(f"  {q['id']:7} a{k+1} {'PASS' if row['passed'] else 'fail':4} "
                      f"{row['reasons'][:2]} {secs}s")
            if sleep_s:
                time.sleep(sleep_s)
    return rows


def aggregate(rows: list[dict], arm: str) -> dict:
    kinds = sorted({r["kind"] for r in rows})
    counts = {
        k: [sum(1 for r in rows if r["kind"] == k and r["passed"]),
            sum(1 for r in rows if r["kind"] == k)]
        for k in kinds
    }
    bssb_pass = counts.get("bs", [0, 0])[0] + counts.get("sb", [0, 0])[0]
    bssb_total = counts.get("bs", [0, 0])[1] + counts.get("sb", [0, 0])[1]
    gaps = sorted({g for r in rows for g in r["harness_gap"]})
    unjudged = sorted({u for r in rows for u in r["unjudged"]})
    reasons: dict[str, int] = {}
    for r in rows:
        for x in r["reasons"]:
            key = x.split(":")[0]
            reasons[key] = reasons.get(key, 0) + 1
    checks: list[dict] = []
    for kind, line in sorted(LINES[arm].items()):
        got, total = counts.get(kind, [0, 0])
        checks.append({"kind": kind, "line": line, "passed_attempts": got,
                       "attempts": total, "ok": total == KIND_TARGETS[kind] * 3 and got >= line})
    checks.append({"kind": "bs+sb", "line": BS_SB_TOTAL, "passed_attempts": bssb_pass,
                   "attempts": bssb_total,
                   "ok": bssb_total == BS_SB_TOTAL and bssb_pass == BS_SB_TOTAL})
    return {
        "arm": arm,
        "counts": counts,
        "checks": checks,
        "cell_line_pass": all(c["ok"] for c in checks),
        "incomplete": len(rows) != EXPECTED_ATTEMPTS,
        "attempts": len(rows),
        "repairs_total": sum(r["repairs"] for r in rows),
        "timeouts": sum(1 for r in rows if r["timed_out"]),
        "temperature_unverified": sum(
            1 for r in rows if r.get("temperature_used") is None
        ),
        "crashes": sum(1 for r in rows if r.get("crash")),
        "harness_gap": gaps,
        "unjudged": unjudged,
        "reason_histogram": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        "integrity_hits": sorted({
            r["line_id"] for r in rows for x in r["reasons"]
            if any(m in x for m in INTEGRITY_MARKS)
        }),
    }


def sealed_block() -> dict:
    return {
        "fixture_blob_at_head": git_blob_hash(FIXTURE_REL),
        "protocol_blob_at_head": git_blob_hash(PROTOCOL_REL),
        "effective_text_hash": None,  # filled by the caller (needs the fixture)
    }


def effective_hash(fx: Fixture) -> str:
    """Hash over exactly what the model sees - so a world/meta edit is visible."""
    parts = [json.dumps(fx.meta, ensure_ascii=False, sort_keys=True)]
    for q in fx.questions:
        parts.append(fx.visible_text(q))
    return content_hash("\n".join(parts))


def print_score(cell_id: str, agg: dict) -> None:
    print(f"\n[{cell_id}] arm={agg['arm']} attempts={agg['attempts']}"
          + ("  INCOMPLETE - not a claim" if agg["incomplete"] else ""))
    for c in agg["checks"]:
        print(f"   {c['kind']:6} {c['passed_attempts']}/{c['attempts']} "
              f"(线 {c['line']})  {'OK' if c['ok'] else 'NOT MET'}")
    print(f"   repairs={agg['repairs_total']} timeouts={agg['timeouts']} "
          f"crashes={agg['crashes']} harness_gap={len(agg['harness_gap'])} "
          f"temp_unverified={agg['temperature_unverified']}/{agg['attempts']}")
    if agg["integrity_hits"]:
        print(f"   红线相关行: {', '.join(agg['integrity_hits'])}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m benchmarks.agent.harness.runner")
    ap.add_argument("--cells", type=Path, default=AGENT_DIR / "cells.example.json")
    ap.add_argument("--cell-id", action="append", default=None)
    ap.add_argument("--overlay", type=Path, default=None,
                    help="append-only v1.1 overlay file (never the fixture itself)")
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--only", action="append", default=None)
    ap.add_argument("--sleep", type=float, default=0.0)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--allow-unready", action="store_true",
                    help="run cells whose status is not ok (placeholder base_url etc.)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    lines = load_fixture().raw_lines
    if a.overlay:
        lines = lines + load_overlay_file(a.overlay)
        Fixture(lines)  # validates the overlay before any request goes out
    fx = Fixture(lines)

    cells = load_cells(a.cells)
    if a.cell_id:
        wanted = set(a.cell_id)
        cells = [c for c in cells if c.get("id") in wanted]
        if not cells:
            print(f"no cell matches {sorted(wanted)}", file=sys.stderr)
            return 2
    only = set(a.only or [])
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = a.out or RESULTS_DIR / f"phase0-{fx.version}-{stamp}.json"
    doc = {
        "protocol": fx.meta.get("protocol"),
        "fixture_version": fx.version,
        "overridden_ids": sorted(set(fx.overridden)),
        "sealed": sealed_block(),
        "anchor_today": fx.anchor_today,
        "attempt_denominator": a.attempts,
        "lines_table": LINES,
        "runs": [],
    }
    doc["sealed"]["effective_text_hash"] = effective_hash(fx)

    if a.dry_run:
        plan = [{"id": c["id"], "arm": c["arm"], "model": c["model"],
                 "requests_max": len(fx.questions) * a.attempts} for c in cells]
        print(json.dumps({"dry_run": True, "sealed": doc["sealed"], "plan": plan},
                         ensure_ascii=False, indent=1))
        return 0

    for cell in cells:
        status = str(cell.get("status", "ok"))
        if status != "ok" and not a.allow_unready:
            why = ("n_a: " + str(cell.get("reason", "marked n/a"))) if status == "n_a" \
                else f"not ready (status={status})"
            if "REPLACE" in str(cell.get("base_url", "")):
                why += "; base_url is a placeholder"
            doc["runs"].append({"cell": cell, "skipped": why})
            print(f"[{cell['id']}] SKIPPED - {why}")
            continue
        rows = run_cell(fx, cell, a.attempts, only, a.sleep, a.verbose)
        agg = aggregate(rows, cell["arm"])
        safe_cell = {k: v for k, v in cell.items() if k != "api_key_env"}
        safe_cell["api_key_env"] = cell.get("api_key_env")  # name only, never the value
        doc["runs"].append({"cell": safe_cell, "aggregate": agg, "rows": rows})
        print_score(cell["id"], agg)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {out_path}")
    runs = [r["aggregate"] for r in doc["runs"] if "aggregate" in r]
    return 1 if any(a["crashes"] or a["incomplete"] for a in runs) else 0


if __name__ == "__main__":
    raise SystemExit(main())
