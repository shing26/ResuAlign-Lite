#!/usr/bin/env python3
"""Wall-clock benchmark for workbench LLM round trips.

Every fake chat completion sleeps ``--latency`` seconds so the numbers are
easy to reason about: the pre-optimization pipeline was 4 calls, the current
cold pipeline is 3, and a cached diagnosis run is 2.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from resualign.engine import run
from resualign.gap_analyzer import GAP_ANALYSIS_PROMPT, analyze_gaps
from resualign.jd_profiler import JD_PROFILER_PROMPT, profile_jd
from resualign.llm import DIAG_PROMPT
from resualign.models import ResuAlignConfig
from resualign.tailor import tailor_resume


RESUME = (
    "# Python Backend Engineer\n"
    "5 years of experience\n"
    "- FastAPI services\n"
    "- Redis cache storage\n"
    "- Docker\n"
    "- PostgreSQL and SQL tuning\n"
)

JD = (
    "Hiring Python backend engineer with FastAPI and Redis for a "
    "high-concurrency platform. Requirements: FastAPI async endpoints, "
    "Redis caching for hot data and rate limiting, low latency performance "
    "metrics, Docker and Kubernetes deployment workflows. Salary 25-35K."
)

DIAGNOSIS = {
    "score": 82,
    "skills": ["Python", "FastAPI", "Redis", "Docker", "SQL"],
    "issues": ["Add concrete performance metrics.", "Show deployment evidence."],
}

FAKE_PROFILE = {
    "must_have_skills": ["Python", "FastAPI", "Redis", "SQL"],
    "nice_to_have_skills": ["Docker", "Kubernetes"],
    "soft_skills": ["Communication", "Teamwork"],
    "business_scenarios": [
        "high concurrency",
        "low latency",
        "production deployment",
        "observability",
    ],
    "min_years_experience": 3,
    "education_requirements": ["Bachelor's degree in Computer Science"],
}

FAKE_GAP = {
    "missing_keywords": [
        "Redis caching for high concurrency",
        "FastAPI async endpoints",
        "production Kubernetes deployment evidence",
        "low latency performance metrics",
    ],
    "misaligned_emphasis": [
        "Add explicit high-concurrency metrics",
        "Show production observability",
    ],
    "strength_matches": ["Python and SQL align with the JD"],
}

FAKE_TAILOR = {
    "sections": {
        "experience": (
            "Built Python FastAPI services with Redis caching for high "
            "concurrency and async endpoints; deployed to production "
            "Kubernetes with Docker and added low latency performance "
            "metrics."
        ),
    },
    "diffs": [
        {
            "type": "modify",
            "original": "Redis cache storage",
            "proposed": "Redis caching for high concurrency",
            "reason": "JD emphasizes Redis caching and high concurrency",
            "confidence": "high",
            "provenance": "Redis cache storage",
        },
    ],
}


class FakeLatencyClient:
    """Deterministic client that sleeps once per simulated LLM round trip."""

    def __init__(self, latency: float = 1.0):
        self.latency = latency
        self.calls: list[tuple[str, str]] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def chat_json(
        self, system: str, user: str, model: Optional[str] = None
    ) -> dict:
        self.calls.append((system, user))
        time.sleep(self.latency)
        stage = self._stage(system)
        if stage == "diag":
            return copy.deepcopy(DIAGNOSIS)
        if stage == "jd_analysis":
            return {
                "jd_profile": copy.deepcopy(FAKE_PROFILE),
                "gap_report": copy.deepcopy(FAKE_GAP),
            }
        if stage == "profile":
            return copy.deepcopy(FAKE_PROFILE)
        if stage == "gap":
            return copy.deepcopy(FAKE_GAP)
        return copy.deepcopy(FAKE_TAILOR)

    @staticmethod
    def _stage(system: str) -> str:
        text = system.lower()
        if "resume auditor" in text:
            return "diag"
        if "job description analyst" in text and "gap analyst" in text:
            return "jd_analysis"
        if "job description analyst" in text:
            return "profile"
        if "gap analyst" in text:
            return "gap"
        return "tailor"


def _profile_to_text(profile) -> str:
    return json.dumps(
        {
            "must_have_skills": list(profile.must_have_skills or []),
            "nice_to_have_skills": list(profile.nice_to_have_skills or []),
            "soft_skills": list(profile.soft_skills or []),
            "business_scenarios": list(profile.business_scenarios or []),
            "min_years_experience": profile.min_years_experience,
            "education_requirements": list(
                profile.education_requirements or []
            ),
        },
        ensure_ascii=False,
    )


def _gap_to_text(gap) -> str:
    return json.dumps(
        {
            "missing_keywords": list(gap.missing_keywords or []),
            "misaligned_emphasis": list(gap.misaligned_emphasis or []),
            "strength_matches": list(gap.strength_matches or []),
        },
        ensure_ascii=False,
    )


def legacy_flow(client: FakeLatencyClient) -> dict:
    """Replay the pre-optimization 4-call sequence from the same modules."""
    client.chat_json(DIAG_PROMPT, RESUME)
    profile = profile_jd(client, JD)
    gap = analyze_gaps(client, RESUME, _profile_to_text(profile))
    tailor_resume(client, RESUME, _gap_to_text(gap))
    return {"call_count": client.call_count}


def new_cold_flow(client: FakeLatencyClient) -> dict:
    report = run(
        ResuAlignConfig(model="fake-latency"),
        RESUME,
        JD,
        llm_client=client,
    )
    return {
        "call_count": client.call_count,
        "report_score": report.score,
        "diffs": len(report.diffs or []),
    }


def new_cached_flow(client: FakeLatencyClient) -> dict:
    report = run(
        ResuAlignConfig(model="fake-latency"),
        RESUME,
        JD,
        llm_client=client,
        diagnosis=DIAGNOSIS,
    )
    return {
        "call_count": client.call_count,
        "report_score": report.score,
        "diffs": len(report.diffs or []),
    }


def _timed(runner):
    client = FakeLatencyClient()
    start = time.monotonic()
    detail = runner(client)
    elapsed = round(time.monotonic() - start, 3)
    return {**detail, "elapsed_seconds": elapsed}


def _print_row(label: str, row: dict, out: TextIO) -> None:
    expected = row["call_count"]
    print(
        f"{label:<24} calls={row['call_count']} "
        f"wall={row['elapsed_seconds']:.2f}s "
        f"(expected {expected}s at 1s/call)",
        file=out,
    )


def main(argv=None, out: Optional[TextIO] = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--latency",
        type=float,
        default=1.0,
        help="simulated seconds per LLM call (default: 1.0)",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=REPO_ROOT / "benchmarks" / "results",
        help="directory for the JSON result file",
    )
    args = parser.parse_args(argv)

    if args.latency <= 0:
        raise ValueError("--latency must be positive")

    output = out or sys.stdout
    legacy = _timed(legacy_flow)
    cold = _timed(new_cold_flow)
    cached = _timed(new_cached_flow)

    if (legacy["call_count"], cold["call_count"], cached["call_count"]) != (
        4,
        3,
        2,
    ):
        raise AssertionError(
            "unexpected call counts: "
            f"legacy={legacy['call_count']}, "
            f"cold={cold['call_count']}, cached={cached['call_count']}"
        )

    payload = {
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "latency_per_call_seconds": args.latency,
        "scenarios": {
            "legacy_4_calls": legacy,
            "current_cold_3_calls": cold,
            "current_cached_2_calls": cached,
        },
        "summary": {
            "cold_speedup_pct": round(
                (legacy["elapsed_seconds"] - cold["elapsed_seconds"])
                / legacy["elapsed_seconds"] * 100,
                1,
            ),
            "cached_speedup_pct": round(
                (legacy["elapsed_seconds"] - cached["elapsed_seconds"])
                / legacy["elapsed_seconds"] * 100,
                1,
            ),
            "seconds_saved_cold": round(
                legacy["elapsed_seconds"] - cold["elapsed_seconds"], 3
            ),
            "seconds_saved_cached": round(
                legacy["elapsed_seconds"] - cached["elapsed_seconds"], 3
            ),
        },
    }

    print(f"Latency benchmark (simulated {args.latency}s per LLM call):", file=output)
    _print_row("legacy (4 calls)", legacy, output)
    _print_row("current cold (3 calls)", cold, output)
    _print_row("current cached (2 calls)", cached, output)
    summary = payload["summary"]
    print("", file=output)
    print(
        f"cold pipeline saves {summary['seconds_saved_cold']}s "
        f"({summary['cold_speedup_pct']}%)",
        file=output,
    )
    print(
        f"cached run saves {summary['seconds_saved_cached']}s "
        f"({summary['cached_speedup_pct']}%)",
        file=output,
    )

    args.results_dir.mkdir(parents=True, exist_ok=True)
    result_path = (
        args.results_dir / f"latency-{payload['timestamp']}.json"
    )
    result_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Results written: {result_path}", file=output)
    return payload


if __name__ == "__main__":
    main()
