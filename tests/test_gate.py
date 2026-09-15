"""Tests for the stdlib-only provenance gate (ADR-0041 spike).

Includes the drift lock: every golden fixture must produce the SAME
usable/blocked partition through gate.verdict() and through the app's
real gate chain in tailor.py (parse_diff_with_provenance + #74 content
check + A2 noop). If either side changes its gate semantics, this test
goes red — that is the parity contract promised to the skill repo.
"""

import ast
import json
import re
from pathlib import Path

import pytest

from resualign import gate

FIXTURES = Path(__file__).parent / "fixtures" / "gate"


@pytest.fixture()
def resume_text() -> str:
    return (FIXTURES / "resume.md").read_text(encoding="utf-8")


@pytest.fixture()
def diffs() -> list[dict]:
    return json.loads((FIXTURES / "diffs.json").read_text(encoding="utf-8"))


@pytest.fixture()
def allowlist() -> str:
    return gate.allowlist_corpus((FIXTURES / "allowlist.json").read_text(encoding="utf-8"))


def _app_flow_verdict(item: dict, resume_text: str, jd_support: str):
    """Drive the REAL shared chain (tailor.gate_diff_items, strict) plus the
    A2 noop filter exactly as the job layer applies it — the parity lock now
    runs against live app code, not a duplicated flow (#119 review followup)."""
    from resualign.api.services.jobs import _is_noop_diff
    from resualign.tailor import gate_diff_items

    diffs, invalid = gate_diff_items([item], resume_text, jd_support)
    if invalid:
        state = invalid[0].provenance_state
        return "blocked", "fabricated" if state == "fabricated" else "missing"
    if _is_noop_diff(
        {
            "type": diffs[0].type,
            "original": diffs[0].original,
            "proposed": diffs[0].proposed,
        }
    ):
        return "blocked", "noop"
    return "usable", "verified"


class TestFixtureVerdicts:
    def test_every_scenario_matches_expected(self, resume_text, diffs, allowlist):
        expected = json.loads(
            (FIXTURES / "expected.json").read_text(encoding="utf-8")
        )["expectations"]
        results = {
            r["diff_id"]: r for r in gate.run_gate(diffs, resume_text, allowlist)["results"]
        }
        for exp in expected:
            got = results[exp["diff_id"]]
            assert got["verdict"] == exp["verdict"], exp["diff_id"]
            assert got["reason"] == exp["reason"], exp["diff_id"]
            assert bool(got["salvaged"]) == exp["salvaged"], exp["diff_id"]

    def test_summary_counts(self, resume_text, diffs, allowlist):
        report = gate.run_gate(diffs, resume_text, allowlist)
        exp = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))["summary"]
        assert len(report["results"]) == exp["diffs"]
        assert report["usable"] == exp["usable"]
        assert report["blocked"] == exp["blocked"]

    def test_salvaged_quote_is_real_resume_text(self, resume_text, diffs, allowlist):
        """Iron rule: the fuzzy salvage must correct provenance to an ACTUAL
        resume substring, never keep the model's misquote."""
        d3 = next(d for d in diffs if d["diff_id"] == "d3-truncated-quote")
        got = gate.verdict(d3, resume_text, allowlist)
        assert got["salvaged"] and got["verdict"] == "usable"
        assert got["provenance"] in resume_text
        assert got["original"] == "参与大促值班，保障系统峰值 QPS 12000 的稳定运行"


class TestDriftLockParity:
    @pytest.mark.parametrize(
        "diff_id",
        [
            "d1-clean-modify",
            "d2-fabricated-metric",
            "d3-truncated-quote",
            "d4-noop",
            "d5-invented-experience",
            "d6-add-empty-original",
            "d7-add-with-support",
            "d8-allowlist-term",
            "d9-add-fabricated-number",
            "d10-add-fabricated-entity",
        ],
    )
    def test_gate_matches_tailor_chain(self, diff_id, resume_text, diffs, allowlist):
        item = next(d for d in diffs if d["diff_id"] == diff_id)
        got = gate.verdict(item, resume_text, allowlist)
        want_verdict, want_reason = _app_flow_verdict(item, resume_text, allowlist)
        assert got["verdict"] == want_verdict, diff_id
        assert got["reason"] == want_reason, diff_id

    def test_allowlist_is_load_bearing(self, resume_text, diffs):
        """d8 passes only with the JD allowlist corpus and is blocked as
        fabricated without it — proves the corpus is actually consulted."""
        d8 = next(d for d in diffs if d["diff_id"] == "d8-allowlist-term")
        without = gate.verdict(d8, resume_text, "")
        assert (without["verdict"], without["reason"]) == ("blocked", "fabricated")
        allow = gate.allowlist_corpus(
            (FIXTURES / "allowlist.json").read_text(encoding="utf-8")
        )
        with_list = gate.verdict(d8, resume_text, allow)
        assert with_list["verdict"] == "usable"


class TestCliContract:
    def test_summary_line_format(self, tmp_path, capsys):
        log = tmp_path / "run.jsonl"
        rc = gate.main(
            [
                "--resume", str(FIXTURES / "resume.md"),
                "--diffs", str(FIXTURES / "diffs.json"),
                "--allowlist", str(FIXTURES / "allowlist.json"),
                "--log", str(log),
                "--round", "2",
                "--trigger", "eval:round1",
            ]
        )
        out = capsys.readouterr().out
        assert rc == 0
        summary = [line for line in out.splitlines() if line.startswith("GATE:")]
        assert len(summary) == 1
        assert re.fullmatch(
            r"GATE: 10 diffs / 6 blocked \(missing=2, fabricated=3, noop=1\) "
            r"/ resume-sha256=[0-9a-f]{12}",
            summary[0],
        ), summary[0]
        entry = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
        assert entry["round"] == 2
        assert entry["trigger"] == "eval:round1"
        assert entry["usable"] == 4
        assert entry["blocked"] == {"missing": 2, "fabricated": 3, "noop": 1}
        assert len(entry["resume_sha256"]) == 64

    def test_missing_file_exits_2(self, tmp_path, capsys):
        rc = gate.main(["--resume", str(tmp_path / "nope.md"), "--diffs", str(FIXTURES / "diffs.json")])
        assert rc == 2
        assert "gate error" in capsys.readouterr().err

    def test_jsonl_is_append_only(self, tmp_path):
        log = tmp_path / "run.jsonl"
        report = gate.run_gate([], (FIXTURES / "resume.md").read_text(encoding="utf-8"))
        gate.append_log(str(log), report, 1, "manual")
        gate.append_log(str(log), report, 2, "eval:round1")
        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert json.loads(lines[1])["round"] == 2


class TestStdlibPurity:
    """The skill repo ships this file standalone: no third-party imports."""

    STDLIB_OK = {
        "__future__", "argparse", "bisect", "difflib", "hashlib", "json",
        "re", "sys", "datetime",
    }

    def test_imports_are_stdlib_only(self):
        tree = ast.parse((Path(gate.__file__)).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert imported <= self.STDLIB_OK, imported - self.STDLIB_OK
