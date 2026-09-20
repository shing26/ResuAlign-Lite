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

# Two language sets, one source of truth each (vendored from the skill repo):
# the Chinese set carries the original fabrication/salvage/noop scripts, the
# English set locks the mid-sentence proper-noun rule that an English-speaking
# reviewer attacks first.
FIXTURE_SETS = {
    "zh": {
        "resume": "resume.md",
        "diffs": "diffs.json",
        "allowlist": "allowlist.json",
        "expected": "expected.json",
    },
    "en": {
        "resume": "resume.en.md",
        "diffs": "diffs.en.json",
        "allowlist": "allowlist.en.json",
        "expected": "expected.en.json",
    },
}


@pytest.fixture()
def resume_text() -> str:
    return (FIXTURES / "resume.md").read_text(encoding="utf-8")


@pytest.fixture()
def diffs() -> list[dict]:
    return json.loads((FIXTURES / "diffs.json").read_text(encoding="utf-8"))


@pytest.fixture()
def allowlist() -> str:
    return gate.allowlist_corpus((FIXTURES / "allowlist.json").read_text(encoding="utf-8"))


@pytest.fixture(params=sorted(FIXTURE_SETS), ids=sorted(FIXTURE_SETS))
def gate_set(request):
    names = FIXTURE_SETS[request.param]
    return {
        "label": request.param,
        "resume_text": (FIXTURES / names["resume"]).read_text(encoding="utf-8"),
        "diffs": json.loads((FIXTURES / names["diffs"]).read_text(encoding="utf-8")),
        "allowlist": gate.allowlist_corpus(
            (FIXTURES / names["allowlist"]).read_text(encoding="utf-8")
        ),
        "expected": json.loads(
            (FIXTURES / names["expected"]).read_text(encoding="utf-8")
        ),
    }


def _app_flow_verdict(item: dict, resume_text: str, jd_support: str):
    """Drive the REAL shared chain (tailor.gate_diff_items, strict) plus the
    A2 noop filter exactly as the job layer applies it — the parity lock now
    runs against live app code, not a duplicated flow (#119 review followup)."""
    from resualign.api.services.jobs import _is_noop_diff
    from resualign.engine.tailor import gate_diff_items

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
    def test_every_scenario_matches_expected(self, gate_set):
        resume_text, diffs, allowlist = (
            gate_set["resume_text"],
            gate_set["diffs"],
            gate_set["allowlist"],
        )
        results = {
            r["diff_id"]: r for r in gate.run_gate(diffs, resume_text, allowlist)["results"]
        }
        for exp in gate_set["expected"]["expectations"]:
            got = results[exp["diff_id"]]
            assert got["verdict"] == exp["verdict"], exp["diff_id"]
            assert got["reason"] == exp["reason"], exp["diff_id"]
            assert bool(got["salvaged"]) == exp["salvaged"], exp["diff_id"]

    def test_summary_counts(self, gate_set):
        report = gate.run_gate(
            gate_set["diffs"], gate_set["resume_text"], gate_set["allowlist"]
        )
        exp = gate_set["expected"]["summary"]
        assert len(report["results"]) == exp["diffs"]
        assert report["usable"] == exp["usable"]
        assert report["blocked"] == exp["blocked"]

    def test_blocked_detail_names_the_unsupported_item(self, gate_set):
        """A block must be actionable: the reason line carries the number or
        term that has no source, not a generic "rejected"."""
        resume_text, diffs, allowlist = (
            gate_set["resume_text"],
            gate_set["diffs"],
            gate_set["allowlist"],
        )
        for r in gate.run_gate(diffs, resume_text, allowlist)["results"]:
            if r["verdict"] != "blocked":
                continue
            if r["reason"] in ("fabricated", "missing"):
                assert r["detail"], r["diff_id"]
                assert len(r["detail"]) > 12, r["diff_id"]

    def test_salvaged_quote_is_real_resume_text(self, resume_text, diffs, allowlist):
        """Iron rule: the fuzzy salvage must correct provenance to an ACTUAL
        resume substring, never keep the model's misquote."""
        d3 = next(d for d in diffs if d["diff_id"] == "d3-truncated-quote")
        got = gate.verdict(d3, resume_text, allowlist)
        assert got["salvaged"] and got["verdict"] == "usable"
        assert got["provenance"] in resume_text
        assert got["original"] == "参与大促值班，保障系统峰值 QPS 12000 的稳定运行"


class TestDriftLockParity:
    def test_gate_matches_tailor_chain_every_scenario(self, gate_set):
        """Every golden scenario, both languages, must land the same way on
        the standalone gate and on the app's real tailor chain. This is the
        drift lock ADR-0041 决定 11 promised the skill repo."""
        resume_text, allowlist = gate_set["resume_text"], gate_set["allowlist"]
        for item in gate_set["diffs"]:
            got = gate.verdict(item, resume_text, allowlist)
            want_verdict, want_reason = _app_flow_verdict(
                item, resume_text, allowlist
            )
            assert got["verdict"] == want_verdict, (gate_set["label"], item["diff_id"])
            assert got["reason"] == want_reason, (gate_set["label"], item["diff_id"])

    def test_allowlist_is_load_bearing(self, gate_set):
        """The allowlist-dependent scenario (d8 / e6) passes only with the JD
        corpus and is blocked as fabricated without it."""
        dependent = next(
            exp["diff_id"]
            for exp in gate_set["expected"]["expectations"]
            if "allowlist" in exp["diff_id"]
        )
        item = next(
            d for d in gate_set["diffs"] if d["diff_id"] == dependent
        )
        without = gate.verdict(item, gate_set["resume_text"], "")
        assert (without["verdict"], without["reason"]) == ("blocked", "fabricated"), dependent
        with_list = gate.verdict(item, gate_set["resume_text"], gate_set["allowlist"])
        assert with_list["verdict"] == "usable", dependent

    def test_english_prose_capitalization_is_not_read_as_a_claim(self):
        """False-positive guard, kept explicit because it is the rule most
        likely to be "fixed" into a hole later: sentence-initial verbs and
        weekday names stay usable, mid-sentence names do not."""
        resume_text = (FIXTURES / "resume.en.md").read_text(encoding="utf-8")
        diffs = {
            d["diff_id"]: d
            for d in json.loads((FIXTURES / "diffs.en.json").read_text(encoding="utf-8"))
        }
        allow = gate.allowlist_corpus(
            (FIXTURES / "allowlist.en.json").read_text(encoding="utf-8")
        )
        for diff_id in ("e1-clean-modify", "e4-sentence-start-is-prose", "e5-capitalized-common-word"):
            got = gate.verdict(diffs[diff_id], resume_text, allow)
            assert got["verdict"] == "usable", (diff_id, got["detail"])
        for diff_id in ("e2-midsentence-tool-invented", "e3-midsentence-employer-invented"):
            got = gate.verdict(diffs[diff_id], resume_text, allow)
            assert (got["verdict"], got["reason"]) == ("blocked", "fabricated"), diff_id
            assert "term" in got["detail"], diff_id


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

    def test_chain_block_records_round_provenance(self, tmp_path):
        """R5 (dogfood): the JSONL must make a faked round number detectable."""
        log = tmp_path / "run.jsonl"
        report = gate.run_gate([], (FIXTURES / "resume.md").read_text(encoding="utf-8"))
        gate.append_log(str(log), report, 1, "manual")
        gate.append_log(str(log), report, 2, "eval:round1")
        gate.append_log(str(log), report, 4, "manual")
        gate.append_log(str(log), report, 3, "manual")
        chains = [
            json.loads(line)["chain"] for line in log.read_text(encoding="utf-8").splitlines()
        ]
        assert chains[0] == {"prev_round": None, "cites_prev": True}
        assert chains[1] == {"prev_round": 1, "cites_prev": True}
        # skipped a round, then went backwards without citing it
        assert chains[2] == {"prev_round": 2, "cites_prev": False}
        assert chains[3] == {"prev_round": 4, "cites_prev": False}

    def test_last_logged_round_survives_junk_lines(self, tmp_path):
        log = tmp_path / "run.jsonl"
        log.write_text('not json\n\n{"round": 3}\n{"no_round": 1}\n', encoding="utf-8")
        assert gate.last_logged_round(str(log)) == 3
        assert gate.last_logged_round(str(tmp_path / "missing.jsonl")) is None


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
