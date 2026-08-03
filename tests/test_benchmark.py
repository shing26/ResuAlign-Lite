import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_SCRIPT = REPO_ROOT / "benchmarks" / "run_benchmark.py"
CASES_DIR = REPO_ROOT / "benchmarks" / "cases"

EXPECTED_NEW_CASE_IDS = {
    "react-typescript-frontend",
    "go-backend",
    "devops-sre",
    "machine-learning-engineer",
    "mobile-engineer",
    "chinese-python-backend",
}


@pytest.fixture(scope="module")
def benchmark_module():
    spec = importlib.util.spec_from_file_location(
        "resualign_benchmark", BENCHMARK_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_benchmark_cases_are_valid(benchmark_module):
    cases = benchmark_module.load_cases(CASES_DIR)
    assert len(cases) >= 9
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))
    for case in cases:
        assert case["resume_text"].strip()
        assert case["jd_text"].strip()
        assert isinstance(case["expected_direction"], list)
        assert len(case["expected_direction"]) >= 1
        assert all(
            isinstance(goal, str) and goal.strip()
            for goal in case["expected_direction"]
        )
        assert case["source_note"].strip()
        assert "synthetic" in case["source_note"].lower()
        tags = case.get("tags")
        if tags is not None:
            assert isinstance(tags, list)
            assert len(tags) >= 1
            assert all(isinstance(tag, str) and tag.strip() for tag in tags)


def test_expanded_coverage_includes_required_roles(benchmark_module):
    cases = benchmark_module.load_cases(CASES_DIR)
    case_ids = {case["id"] for case in cases}
    assert EXPECTED_NEW_CASE_IDS <= case_ids
    for case in cases:
        if case["id"] in EXPECTED_NEW_CASE_IDS:
            assert isinstance(case.get("tags"), list)
            assert len(case["tags"]) >= 1


def test_fake_llm_client_is_deterministic(benchmark_module):
    client = benchmark_module.FakeLLMClient()
    first = client.chat_json("You are a resume auditor.", "user A")
    second = client.chat_json("You are a resume auditor.", "user B")
    assert first == second
    assert "score" in first
    assert client.call_count == 2


def test_keyword_overlap_heuristic(benchmark_module):
    result = benchmark_module.evaluate_goals(
        ["highlight Redis caching for high concurrency"],
        "Redis caching for high concurrency",
    )
    assert result["goal_count"] == 1
    assert result["coverage"] == 1.0
    assert result["goals"][0]["covered"] is True

    partial = benchmark_module.evaluate_goals(
        ["highlight Redis caching for high concurrency"],
        "Redis caching only",
    )
    assert partial["coverage"] < 1.0
    assert partial["goals"][0]["covered"] is False


def test_offline_benchmark_writes_results_without_network(
    benchmark_module, tmp_path
):
    benchmark_module.run_benchmark(
        mode="offline",
        cases_dir=CASES_DIR,
        results_dir=tmp_path,
    )
    files = list(tmp_path.glob("benchmark-*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["mode"] == "offline"
    assert data["model"] == "fake-deterministic"
    assert data["summary"]["cases"] >= 9
    assert len(data["cases"]) == len(benchmark_module.load_cases(CASES_DIR))
    assert data["summary"]["covered_goals"] == data["summary"]["total_goals"]
    for case in data["cases"]:
        report = case["report"]
        assert report["score"] >= 0
        assert report["jd_profile"] is not None
        assert report["gap_report"] is not None
        assert report["tailored_resume"] is not None
        assert "diffs" in report["tailored_resume"]
        overlap = case["keyword_overlap"]
        assert overlap["coverage"] >= 0.6
