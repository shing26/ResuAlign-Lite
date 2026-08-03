#!/usr/bin/env python3
"""Benchmark regression harness for ResuAlign.

Offline mode uses a deterministic FakeLLMClient so it works without network
access. Online mode reads D:/ResuAlign-Lite/.env and calls the configured
DeepSeek model through OpenAIClient.
"""

import argparse
import copy
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, TextIO

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from resualign.engine import run
from resualign.llm import OpenAIClient
from resualign.models import ResuAlignConfig


_STOPWORDS = {
    "a", "an", "the", "and", "or", "for", "to", "of", "with", "in", "on",
    "at", "by", "as", "is", "are", "it", "its", "our", "your", "we", "you",
    "experience", "skills", "show", "highlight", "emphasize", "use", "using",
}

FAKE_DIAG = {
    "score": 82,
    "skills": [
        "Python", "FastAPI", "Java", "Spring Cloud", "Kafka", "Spark",
        "SQL", "Airflow", "Redis", "Kubernetes",
    ],
    "issues": [
        "Add concrete performance metrics.",
        "Show production deployment evidence.",
    ],
}

FAKE_PROFILE = {
    "must_have_skills": ["Python", "Java", "SQL", "Redis"],
    "nice_to_have_skills": [
        "FastAPI", "Kubernetes", "Docker", "Spark", "Kafka",
        "Spring Cloud", "Airflow", "dbt",
    ],
    "soft_skills": ["Communication", "Teamwork"],
    "business_scenarios": [
        "high concurrency", "low latency", "microservices",
        "ETL pipelines", "event streaming",
    ],
    "min_years_experience": 3,
    "education_requirements": ["Bachelor's degree in Computer Science"],
}

FAKE_GAP = {
    "missing_keywords": [
        "Redis caching", "async endpoints", "production Kubernetes deployment",
        "Spring Cloud microservices", "Kafka event streaming",
        "observability and tracing", "Airflow scheduling",
        "data quality validation",
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
            "concurrency and async endpoints; built Java Spring Cloud "
            "microservices with Kafka event streaming and production "
            "observability through metrics, logs, and distributed tracing; "
            "deployed to production Kubernetes with Docker."
        ),
        "projects": (
            "Designed ETL pipelines in Python and Spark with Airflow "
            "scheduling and orchestration; added data quality validation "
            "workflows; tuned PostgreSQL and SQL queries for low latency."
        ),
        "frontend": (
            "Built production React and TypeScript dashboards; improved web "
            "performance optimization and reduced bundle size through code "
            "splitting and lazy loading; added Jest and Testing Library test "
            "coverage; built a design system with accessibility work."
        ),
        "mobile": (
            "Set up CI/CD pipelines for staged production release experience; "
            "performed app performance profiling and launch time reduction; "
            "improved performance profiling and memory management."
        ),
    },
    "diffs": [
        {
            "type": "modify",
            "original": "Used Redis for cache storage",
            "proposed": (
                "Used Redis caching for high concurrency and async endpoints"
            ),
            "reason": "JD emphasizes Redis caching and high concurrency",
            "confidence": "high",
            "provenance": "Used Redis for cache storage",
        },
        {
            "type": "modify",
            "original": "Worked on backend services",
            "proposed": (
                "Built Spring Cloud microservices with Kafka event streaming "
                "and observability and tracing"
            ),
            "reason": "JD asks for microservices, Kafka, and observability",
            "confidence": "high",
            "provenance": "Worked on backend services",
        },
        {
            "type": "modify",
            "original": "Built ETL pipelines",
            "proposed": (
                "Built ETL pipelines in Python and Spark with Airflow "
                "scheduling, orchestration, and data quality validation "
                "workflows"
            ),
            "reason": "JD asks for Spark, Airflow, and data quality validation",
            "confidence": "high",
            "provenance": "Built ETL pipelines",
        },
    ],
}

FAKE_ALIGN = {
    "diffs": [
        {
            "type": "modify",
            "original": "Used Redis for cache storage",
            "proposed": (
                "Use Redis caching for high concurrency and FastAPI async "
                "endpoints"
            ),
            "reason": "JD emphasizes Redis caching and high concurrency",
            "confidence": "high",
        },
        {
            "type": "modify",
            "original": "Worked on backend services",
            "proposed": (
                "Built Spring Cloud microservices with Kafka event streaming "
                "and observability and tracing"
            ),
            "reason": "JD asks for microservices, Kafka, and observability",
            "confidence": "high",
        },
    ],
}

_FAKE_RESPONSES = {
    "diag": FAKE_DIAG,
    "profile": FAKE_PROFILE,
    "gap": FAKE_GAP,
    "jd_analysis": {"jd_profile": FAKE_PROFILE, "gap_report": FAKE_GAP},
    "tailor": FAKE_TAILOR,
    "align": FAKE_ALIGN,
}


class FakeLLMClient:
    """Deterministic LLM client for offline benchmark runs."""

    def __init__(self):
        self.calls = []
        self.call_count = 0

    def chat_json(self, system: str, user: str, model: Optional[str] = None) -> dict:
        self.calls.append({"system": system, "user": user})
        self.call_count += 1
        stage = self._stage(system)
        return copy.deepcopy(_FAKE_RESPONSES[stage])

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
        if "gap report" in text:
            return "tailor"
        return "align"


def _tokens(text: str) -> List[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if token not in _STOPWORDS
    ]


def evaluate_goals(expected_direction: List[str], evidence: str) -> Dict:
    """Score keyword overlap between expected goals and pipeline evidence."""
    evidence_tokens = set(_tokens(evidence))
    goal_results = []
    for goal in expected_direction:
        goal_tokens = _tokens(goal)
        if not goal_tokens:
            continue
        matched = [token for token in goal_tokens if token in evidence_tokens]
        missing = [token for token in goal_tokens if token not in evidence_tokens]
        coverage = len(matched) / len(goal_tokens)
        goal_results.append({
            "goal": goal,
            "matched_tokens": matched,
            "missing_tokens": missing,
            "coverage": round(coverage, 3),
            "covered": coverage >= 0.6,
        })
    coverage = (
        sum(result["coverage"] for result in goal_results) / len(goal_results)
        if goal_results else 0.0
    )
    return {
        "goal_count": len(goal_results),
        "covered_goal_count": sum(
            1 for result in goal_results if result["covered"]
        ),
        "coverage": round(coverage, 3),
        "goals": goal_results,
    }


def load_cases(cases_dir: Path) -> List[Dict]:
    cases_dir = Path(cases_dir)
    if not cases_dir.is_dir():
        raise FileNotFoundError(f"Benchmark cases directory not found: {cases_dir}")
    required = {"id", "resume_text", "jd_text", "expected_direction", "source_note"}
    cases = []
    for path in sorted(cases_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = required - set(data)
        if missing:
            raise ValueError(f"{path.name}: missing fields {sorted(missing)}")
        if not isinstance(data["expected_direction"], list) or not data["expected_direction"]:
            raise ValueError(f"{path.name}: expected_direction must be a non-empty list")
        data["source_file"] = path.name
        cases.append(data)
    return cases


def _diff_to_dict(diff) -> Dict:
    return {
        "type": diff.type,
        "original": diff.original,
        "proposed": diff.proposed,
        "reason": diff.reason,
        "confidence": diff.confidence,
        "provenance": diff.provenance,
    }


def _report_to_dict(report) -> Dict:
    data = {
        "score": report.score,
        "skills": list(report.skills or []),
        "issues": list(report.issues or []),
        "model": report.model,
        "elapsed_seconds": report.elapsed_seconds,
        "diffs": [_diff_to_dict(diff) for diff in report.diffs],
    }
    if report.jd_profile is not None:
        profile = report.jd_profile
        data["jd_profile"] = {
            "must_have_skills": list(profile.must_have_skills or []),
            "nice_to_have_skills": list(profile.nice_to_have_skills or []),
            "soft_skills": list(profile.soft_skills or []),
            "business_scenarios": list(profile.business_scenarios or []),
            "min_years_experience": profile.min_years_experience,
            "education_requirements": list(profile.education_requirements or []),
        }
    if report.gap_report is not None:
        gap = report.gap_report
        data["gap_report"] = {
            "missing_keywords": list(gap.missing_keywords or []),
            "misaligned_emphasis": list(gap.misaligned_emphasis or []),
            "strength_matches": list(gap.strength_matches or []),
        }
    if report.tailored_resume is not None:
        tailored = report.tailored_resume
        data["tailored_resume"] = {
            "sections": dict(tailored.sections or {}),
            "diffs": [_diff_to_dict(diff) for diff in (tailored.diffs or [])],
        }
    return data


def _evidence_from_report(report) -> str:
    parts = list(report.skills or [])
    parts.extend(report.issues or [])
    if report.jd_profile is not None:
        profile = report.jd_profile
        parts.extend(profile.must_have_skills or [])
        parts.extend(profile.nice_to_have_skills or [])
        parts.extend(profile.soft_skills or [])
        parts.extend(profile.business_scenarios or [])
        parts.extend(profile.education_requirements or [])
    if report.gap_report is not None:
        gap = report.gap_report
        parts.extend(gap.missing_keywords or [])
        parts.extend(gap.misaligned_emphasis or [])
        parts.extend(gap.strength_matches or [])
    if report.tailored_resume is not None:
        for section in (report.tailored_resume.sections or {}).values():
            parts.append(str(section))
        for diff in report.tailored_resume.diffs or []:
            parts.extend([diff.original, diff.proposed, diff.reason, diff.provenance])
    for diff in report.diffs or []:
        parts.extend([diff.original, diff.proposed, diff.reason, diff.provenance])
    return " ".join(part for part in parts if part)


def _run_case(case: Dict, config: ResuAlignConfig, client) -> Dict:
    t0 = time.monotonic()
    report = run(
        config,
        case["resume_text"],
        case["jd_text"],
        llm_client=client,
    )
    report.elapsed_seconds = round(time.monotonic() - t0, 3)
    evidence = _evidence_from_report(report)
    return {
        "id": case["id"],
        "source_file": case.get("source_file", ""),
        "source_note": case.get("source_note", ""),
        "expected_direction": list(case["expected_direction"]),
        "report": _report_to_dict(report),
        "keyword_overlap": evaluate_goals(case["expected_direction"], evidence),
    }


def _load_env(env_path: Path) -> Dict[str, str]:
    env_path = Path(env_path)
    values = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            values[key] = value
            os.environ.setdefault(key, value)
    return values


def _build_config(mode: str) -> ResuAlignConfig:
    if mode == "offline":
        return ResuAlignConfig(provider="offline", model="fake-deterministic")
    env = _load_env(REPO_ROOT / ".env")
    api_key = os.environ.get("DEEPSEEK_API_KEY", "") or env.get("DEEPSEEK_API_KEY", "")
    model = os.environ.get("DEEPSEEK_MODEL", "") or env.get("DEEPSEEK_MODEL", "deepseek-chat")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "") or env.get("DEEPSEEK_BASE_URL", "")
    if not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY not found in D:/ResuAlign-Lite/.env; "
            "online mode requires credentials."
        )
    return ResuAlignConfig(
        provider="deepseek",
        api_key=api_key,
        model=model,
        base_url=base_url,
    )


def _summarize(results: List[Dict]) -> Dict:
    scores = [result["report"]["score"] for result in results]
    coverages = [result["keyword_overlap"]["coverage"] for result in results]
    total_goals = sum(
        result["keyword_overlap"]["goal_count"] for result in results
    )
    covered_goals = sum(
        result["keyword_overlap"]["covered_goal_count"] for result in results
    )
    return {
        "cases": len(results),
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "avg_goal_coverage": (
            round(sum(coverages) / len(coverages), 3) if coverages else 0.0
        ),
        "total_goals": total_goals,
        "covered_goals": covered_goals,
    }


def _print_summary(payload: Dict, out: TextIO) -> None:
    summary = payload["summary"]
    print(f"Benchmark mode: {payload['mode']} (model: {payload['model']})", file=out)
    print(f"Timestamp: {payload['timestamp']}", file=out)
    print(f"Cases: {summary['cases']}", file=out)
    print(f"Average score: {summary['avg_score']}/100", file=out)
    print(
        f"Average goal coverage: {summary['avg_goal_coverage']:.1%}",
        file=out,
    )
    print(
        f"Goals covered: {summary['covered_goals']}/{summary['total_goals']}",
        file=out,
    )
    print("", file=out)
    for result in payload["cases"]:
        overlap = result["keyword_overlap"]
        print(
            f"[{result['id']}] score={result['report']['score']} "
            f"coverage={overlap['coverage']:.1%} "
            f"covered={overlap['covered_goal_count']}/{overlap['goal_count']}",
            file=out,
        )
        for goal in overlap["goals"]:
            marker = "PASS" if goal["covered"] else "MISS"
            print(
                f"  {marker} {goal['goal']} ({goal['coverage']:.1%})",
                file=out,
            )


def run_benchmark(
    mode: str = "offline",
    cases_dir: Optional[Path] = None,
    results_dir: Optional[Path] = None,
    out: Optional[TextIO] = None,
) -> Dict:
    mode = (mode or "offline").lower()
    if mode not in {"offline", "online"}:
        raise ValueError(f"Unknown benchmark mode: {mode}")
    cases_dir = Path(cases_dir) if cases_dir else REPO_ROOT / "benchmarks" / "cases"
    results_dir = (
        Path(results_dir) if results_dir else REPO_ROOT / "benchmarks" / "results"
    )
    cases = load_cases(cases_dir)
    if not cases:
        raise ValueError(f"No benchmark cases found in {cases_dir}")

    config = _build_config(mode)
    client = FakeLLMClient() if mode == "offline" else OpenAIClient(config)
    output = out or sys.stdout
    results = []
    for index, case in enumerate(cases, 1):
        print(
            f"[BENCHMARK] {index}/{len(cases)} starting {case['id']}",
            file=output,
            flush=True,
        )
        result = _run_case(case, config, client)
        print(
            f"[BENCHMARK] {index}/{len(cases)} done {case['id']} "
            f"score={result['report']['score']}",
            file=output,
            flush=True,
        )
        results.append(result)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "timestamp": timestamp,
        "mode": mode,
        "model": config.model,
        "cases": results,
        "summary": _summarize(results),
    }
    results_dir.mkdir(parents=True, exist_ok=True)
    json_path = results_dir / f"benchmark-{timestamp}.json"
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    _print_summary(payload, out=out or sys.stdout)
    print(f"Results written: {json_path}", file=out or sys.stdout)
    return payload


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="Run ResuAlign benchmark cases (offline by default)."
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use deterministic fake LLM responses (default)",
    )
    parser.add_argument(
        "--online",
        action="store_true",
        help="Call DeepSeek using D:/ResuAlign-Lite/.env credentials",
    )
    parser.add_argument(
        "--cases-dir",
        type=Path,
        default=REPO_ROOT / "benchmarks" / "cases",
        help="Directory containing benchmark case JSON files",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=REPO_ROOT / "benchmarks" / "results",
        help="Directory where benchmark result JSON is written",
    )
    args = parser.parse_args(argv)
    mode = "online" if args.online else "offline"
    run_benchmark(mode=mode, cases_dir=args.cases_dir, results_dir=args.results_dir)


if __name__ == "__main__":
    main()
