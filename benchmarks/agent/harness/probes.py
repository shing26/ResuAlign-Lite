"""Self-check suite for the Phase 0 harness (runs offline, no model calls).

    python -m benchmarks.agent.harness.probes            # both fixture versions
    python -m benchmarks.agent.harness.probes --verbose

Probes:
  P1 perfect actor -> every line passes through both code paths (arm + direct)
  P2 injected violations -> each one is caught with the expected reason code
  P3 identity hole -> the v1 substitutes pass v1 and fail v1.1 (the V1洞 evidence)
  P4 repair accounting -> <=2 retried, 3rd invalid output kills the attempt
  P5 judging boundary -> SS-05 v1/v1.1 delta, author-note scan, harness_gap empty

Every probe asserts on data the judge itself returns; nothing here reads the
protocol prose, so a rule that exists only in the document cannot pass.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if __package__ in (None, ""):  # allow `python probes.py` from the harness dir
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from benchmarks.agent.harness import actor as _a  # noqa: F401

from .actor import (
    VIOLATIONS,
    _call,
    _rep,
    args_for_key,
    perfect_attempt,
    perfect_plan,
    planned_calls,
    reference_finalizer,
)
from .arms import ScriptedArm, decide_action
from .core import AGENT_DIR, Fixture, load_fixture, load_overlay_file, split_key
from .judge import APPROVAL_TOOLS, judge_attempt

OVERLAY_DEFAULT = AGENT_DIR.parent.parent / ".scratch" / "phase0" / "v11_overlay.jsonl"
NOTE_RE = re.compile(r"（world[^）]*）")


# --------------------------------------------------------------------------


def fx_v1() -> Fixture:
    return load_fixture()


def fx_v11(overlay: Path | None = None) -> Fixture | None:
    path = overlay or OVERLAY_DEFAULT
    if not path.exists():
        return None
    lines = load_fixture().raw_lines + load_overlay_file(path)
    return Fixture(lines)


def _run(fx: Fixture, q: dict) -> dict:
    """Same attempt through the arm path (validation + sim) and the direct path."""
    plan, arm = actor_plan(fx, q)
    through_arm = ScriptedArm(fx, plan, arm=arm, finalize=reference_finalizer(fx)).run_question(q)
    direct = perfect_attempt(fx, q)
    v_arm = judge_attempt(fx, q, through_arm)
    v_dir = judge_attempt(fx, q, direct)
    return {"arm": v_arm, "direct": v_dir}


def actor_plan(fx: Fixture, q: dict):
    return perfect_plan(fx, q)


# --------------------------------------------------------------------------
# probes
# --------------------------------------------------------------------------


def p1_perfect(fx: Fixture) -> list[str]:
    fails = []
    for q in fx.questions:
        res = _run(fx, q)
        for path, v in res.items():
            if v["harness_gap"]:
                fails.append(f"P1 {fx.version} {q['id']} [{path}] harness_gap={v['harness_gap']}")
            if not v["passed"]:
                fails.append(
                    f"P1 {fx.version} {q['id']} [{path}] perfect attempt failed: {v['reasons']}"
                )
    return fails


def p2_violations(fx: Fixture) -> list[str]:
    fails = []
    for name, qid, actions, expected_any, minver in VIOLATIONS:
        if minver == "v1.1" and not fx.selector_identity:
            continue
        q = fx.question(qid)
        sim_actor = ScriptedArm(fx, actions, arm="template")
        at = sim_actor.run_question(q)
        v = judge_attempt(fx, q, at)
        if v["passed"]:
            fails.append(f"P2 {fx.version} {name}@{qid}: violation NOT caught")
            continue
        if not any(v["reasons"] and r in " ".join(v["reasons"]) for r in expected_any):
            fails.append(
                f"P2 {fx.version} {name}@{qid}: caught for wrong reason {v['reasons']}"
            )
        if v["harness_gap"]:
            fails.append(f"P2 {fx.version} {name}@{qid}: harness_gap={v['harness_gap']}")
    return fails


def p3_identity_hole(fx1: Fixture, fx2: Fixture | None) -> list[str]:
    """v1 must accept, v1.1 must reject, on the three substitutes named in the review."""
    fails: list[str] = []
    cases = {
        "MD-01": [
            _call("list_jobs", {"updated_since": "2026-09-07"}),
            _call("match_job", {"job_id": "job_3"}),
            _call("match_job", {"job_id": "job_4"}),
            _call("match_job", {"job_id": "job_4"}),
            _call("match_job", {"job_id": "job_5"}),
            _call("match_job", {"job_id": "job_6"}),
            _rep("job_4 得分 88 最高，job_3 得分 72，job_5 得分 61，job_6 得分 45"),
        ],
        "SB-02": [
            _call("align_job", {"job_id": "job_9"}),
            _call("align_job", {"job_id": "job_99"}),
            _rep("done==2 pending==3，回复继续走确定性队列"),
        ],
        "MD-08": [
            _call("get_job", {"job_id": "job_2"}),
            _call("match_job", {"job_id": "job_2"}),
            _call("update_job_status", {"job_id": "job_2", "status": "archived"}),
            _rep("job_2 匹配 41 分，JD 要求常驻北京，存在低分风险；已归档并提议定稿，待确认"),
        ],
    }
    for qid, actions in cases.items():
        at = ScriptedArm(fx1, actions, arm="template").run_question(fx1.question(qid))
        v1 = judge_attempt(fx1, fx1.question(qid), at)
        if not v1["passed"]:
            fails.append(f"P3 {qid}: v1 should have accepted the substitute, got {v1['reasons']}")
        if fx2 is None:
            continue
        at2 = ScriptedArm(fx2, actions, arm="template").run_question(fx2.question(qid))
        v2 = judge_attempt(fx2, fx2.question(qid), at2)
        if v2["passed"]:
            fails.append(f"P3 {qid}: v1.1 still accepts the substitute (hole not closed)")
    return fails


def p4_repair(fx: Fixture) -> list[str]:
    fails = []
    q = fx.question("SS-03")
    ok = ScriptedArm(fx, ["invalid", {"action": "call", "tool": "list_jobs",
                                      "args": {"salary_min": 15000}}], arm="template")
    v = judge_attempt(fx, q, ok.run_question(q))
    if not v["passed"] or v["repairs"] != 1:
        fails.append(f"P4 v1.1-or-v1 repair-then-pass: passed={v['passed']} repairs={v['repairs']}")
    bad = ScriptedArm(fx, ["invalid", "invalid", "invalid",
                           {"action": "call", "tool": "list_jobs", "args": {"salary_min": 15000}}],
                      arm="template")
    v2 = judge_attempt(fx, q, bad.run_question(q))
    if v2["passed"] or "repair_over_cap" not in v2["reasons"]:
        fails.append(f"P4 over-cap repair not failed: passed={v2['passed']} reasons={v2['reasons']}")
    return fails


def p5_boundary(fx1: Fixture, fx2: Fixture | None) -> list[str]:
    fails = []
    plan = [{"skills": [{"name": "Kafka", "importance": "must"}]}]
    q1 = fx1.question("SS-05")
    v1 = judge_attempt(fx1, q1, ScriptedArm(fx1, plan, arm="ss_fields").run_question(q1))
    if not v1["passed"]:
        fails.append(f"P5 SS-05 v1 should pass (importance not judged in v1): {v1['reasons']}")
    if fx2 is not None:
        q2 = fx2.question("SS-05")
        v2 = judge_attempt(fx2, q2, ScriptedArm(fx2, plan, arm="ss_fields").run_question(q2))
        if v2["passed"]:
            fails.append("P5 SS-05 v1.1 still passes a wrong importance pairing")
    n1 = author_notes(fx1)
    if n1 == 0:
        fails.append("P5 author-note scan found nothing in v1 (scan is dead)")
    if fx2 is not None:
        n2 = author_notes(fx2)
        if n2 != 0:
            fails.append(f"P5 v1.1 still carries {n2} author notes in the prompt")
    return fails


def p6_arm_semantics(fx: Fixture) -> list[str]:
    """P6: what a response *means* — the deadlock the ollama smoke test exposed.

    A node that ignores `tool_choice:"none"` must not be punished by the harness
    burning its iterations on calls it silently dropped.
    """
    fails: list[str] = []
    tc = [{"id": "c1", "function": {"name": "list_jobs", "arguments": "{}"}}]
    good = '{"matches": [{"job_id": "job_4", "score": 88}]}'

    def check(label, got, want):
        if got[0] != want:
            fails.append(f"P6 {label}: decided {got[0]}, want {want}")

    check("scripted line dispatches calls",
          decide_action(calls=tc, content="", fill_line=False), "calls")
    check("scripted line prefers call over quoted answer",
          decide_action(calls=tc, content=good, fill_line=False), "calls")
    check("fill line: a call is not an answer",
          decide_action(calls=tc, content="", fill_line=True), "invalid")
    check("fill line: object content is the answer",
          decide_action(calls=[], content=good, fill_line=True), "fill")
    check("scripted line: object content is the answer",
          decide_action(calls=[], content=good, fill_line=False), "fill")
    check("prose is not an answer",
          decide_action(calls=[], content="好的，我来看看。", fill_line=False), "message")
    check("empty content is not an answer",
          decide_action(calls=[], content="   ", fill_line=True), "message")
    got = decide_action(calls=[], content="[1,2]", fill_line=True)
    if got[0] != "message":
        fails.append("P6 non-object JSON accepted as fields")
    # The arm loop must deliver those calls to the sim: run a fake session
    # through HttpArm-shaped bookkeeping is out of scope offline, so assert the
    # weaker, checkable property - a call action is always recorded + delivered.
    q = fx.question("MD-01")
    at = ScriptedArm(fx, [_call("list_jobs", {"updated_since": "2026-09-07"})],
                     arm="template").run_question(q)
    if len(at["sim"].calls) != 1 or at["actions"][0]["action"] != "call":
        fails.append("P6 scripted arm did not deliver the call to the sim")
    return fails


def author_notes(fx: Fixture) -> int:
    hits = 0
    for q in fx.questions:
        vis = fx.visible_text(q)
        hits += len(NOTE_RE.findall(vis))
    return hits


# --------------------------------------------------------------------------


def run_all(overlay: Path | None = None, verbose: bool = False) -> int:
    fx1 = fx_v1()
    fx2 = fx_v11(overlay)
    report: dict = {"fixtures": {"v1": fx1.version, "v1.1": fx2.version if fx2 else "absent"}}
    failures: list[str] = []

    steps = [
        ("P1 perfect/v1", lambda: p1_perfect(fx1)),
        ("P2 violations/v1", lambda: p2_violations(fx1)),
        ("P4 repair/v1", lambda: p4_repair(fx1)),
    ]
    if fx2:
        steps += [
            ("P1 perfect/v1.1", lambda: p1_perfect(fx2)),
            ("P2 violations/v1.1", lambda: p2_violations(fx2)),
            ("P4 repair/v1.1", lambda: p4_repair(fx2)),
        ]
    steps += [
        ("P6 arm semantics", lambda: p6_arm_semantics(fx1)),
        ("P3 identity hole", lambda: p3_identity_hole(fx1, fx2)),
        ("P5 judging boundary", lambda: p5_boundary(fx1, fx2)),
    ]
    for name, fn in steps:
        f = fn()
        failures += f
        print(f"{'FAIL' if f else 'ok  '}  {name}" + (f"  ({len(f)})" if f else ""))
        if f and verbose:
            for line in f:
                print("        " + line)
    counts = {
        "v1_questions": len(fx1.questions),
        "v1_1_questions": len(fx2.questions) if fx2 else None,
        "v1_overridden_ids": sorted(set(fx2.overridden)) if fx2 else [],
        "v1_author_notes": author_notes(fx1),
        "v1_1_author_notes": author_notes(fx2) if fx2 else None,
    }
    print(json.dumps(counts, ensure_ascii=False))
    if failures:
        print(f"\n{len(failures)} probe failure(s):")
        for line in failures[:40]:
            print("  - " + line)
        return 1
    print("\nall probes green")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--overlay", type=Path, default=None)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    return run_all(a.overlay, a.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
