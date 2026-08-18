"""Tests for GraphExecutor, gates, and state models."""
from __future__ import annotations
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import pytest
from resualign.graph import GraphExecutor, AlignmentState, AlignmentStatus, StageResult, NODE_ROUTER, get_node, next_node, ProvenanceGate, AntiHallucinationGate, GateResult

def test_alignment_state_defaults():
    s = AlignmentState(job_id="test", resume_text="hello", jd_text="world")
    assert s.status == AlignmentStatus.RUNNING
    assert s.trace_id
    assert len(s.trace_id) == 12
    assert s.current_node == "start"

def test_status_enum():
    assert AlignmentStatus.RUNNING.value == "RUNNING"
    assert AlignmentStatus.COMPLETED.value == "COMPLETED"
    assert AlignmentStatus.DEGRADED.value == "DEGRADED"

def test_router_keys():
    keys = list(NODE_ROUTER.keys())
    assert len(keys) == 10
    assert keys[0] == "start"
    assert keys[-1] == "end"

def test_get_node():
    n = get_node("start")
    assert n["type"] == "pass_through"
    assert get_node("x") is None

def test_next_node():
    assert next_node("start") == "jd_profiling"
    assert next_node("end") == "end"

class TestProvenanceGate:
    def test_exact_match(self):
        r = ProvenanceGate.check("Python Redis FastAPI", "Python Redis FastAPI")
        assert r.passed
        assert r.score >= 0.8
    def test_low_match(self):
        r = ProvenanceGate.check("Java Spring", "Python Django React")
        assert r.score < 0.8
    def test_empty_proposed(self):
        r = ProvenanceGate.check("Python", "")
        assert r.passed

class TestAntiHallucinationGate:
    def test_no_numbers(self):
        r = AntiHallucinationGate.check("Python", "Python")
        assert r.passed
    def test_novel_numbers(self):
        r = AntiHallucinationGate.check("1000 req/s", "10000 req/s 99.9 uptime")
        assert not r.passed

class TestGraphExecutor:
    def test_empty_run(self):
        s = AlignmentState(job_id="t", resume_text="h", jd_text="w")
        r = GraphExecutor().run(s)
        assert r.status == AlignmentStatus.COMPLETED
        assert len(r.completed_nodes) == 9
    def test_with_llm_runner(self):
        s = AlignmentState(job_id="t", resume_text="h", jd_text="w")
        calls = []
        def runner(st, node):
            calls.append(node.get("role", ""))
            if node.get("role") == "profiler":
                st.jd_profile = {}
            elif node.get("role") == "gap_analyzer":
                st.gap_report = {}
            elif node.get("role") == "editor":
                st.tailored_draft = {"diffs": [{"proposed": "Python"}]}
            return {"type": "mock"}
        r = GraphExecutor(llm_runner=runner).run(s)
        assert r.status == AlignmentStatus.COMPLETED
        assert len(calls) == 4
    def test_failing_llm(self):
        s = AlignmentState(job_id="t", resume_text="h", jd_text="w")
        def runner(st, node):
            if node.get("role") == "profiler":
                raise ValueError("fail")
            return {}
        r = GraphExecutor(llm_runner=runner).run(s)
        assert r.status == AlignmentStatus.FAILED
        assert len(r.errors) > 0
    def test_retry_then_succeed(self):
        s = AlignmentState(job_id="t", resume_text="Python Redis", jd_text="w", max_retries=1)
        cnt = [0]
        def runner(st, node):
            cnt[0] += 1
            if node.get("role") == "profiler":
                st.jd_profile = {}
            elif node.get("role") == "gap_analyzer":
                st.gap_report = {}
            elif node.get("role") == "editor":
                if cnt[0] <= 3:
                    st.tailored_draft = {"diffs": [{"proposed": "Django React"}]}
                else:
                    st.tailored_draft = {"diffs": [{"proposed": "Python Redis"}]}
            return {"type": "mock"}
        r = GraphExecutor(llm_runner=runner).run(s)
        assert r.status == AlignmentStatus.COMPLETED
    def test_retry_from_provenance(self):
        s = AlignmentState(job_id="t", resume_text="Python", jd_text="w", max_retries=1)
        def runner(st, node):
            if node.get("role") == "profiler":
                st.jd_profile = {}
            elif node.get("role") == "gap_analyzer":
                st.gap_report = {}
            elif node.get("role") == "editor":
                st.tailored_draft = {"diffs": [{"proposed": "Django React"}]}
            return {"type": "mock"}
        r = GraphExecutor(llm_runner=runner).run(s)
        # Provenance fails twice (retry exhausted), anti-hallucination passes
        # (no numbers), so pipeline completes normally
        assert r.status == AlignmentStatus.COMPLETED
        assert r.retry_count == 1  # retried once
