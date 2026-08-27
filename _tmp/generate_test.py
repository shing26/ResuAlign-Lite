"""Tests for the GraphExecutor, gates, and state models."""
from __future__ import annotations
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import pytest
from resualign.graph import (
    GraphExecutor, AlignmentState, AlignmentStatus, StageResult,
    NODE_ROUTER, get_node, next_node,
    ProvenanceGate, AntiHallucinationGate, GateResult,
)

def test_alignment_state_defaults():
    s = AlignmentState(job_id="test", resume_text="hello", jd_text="world")
    assert s.status == AlignmentStatus.RUNNING
    assert s.trace_id
    assert len(s.trace_id) == 12
    assert s.current_node == "start"
    assert s.max_retries == 1

def test_alignment_state_status_enum():
    assert AlignmentStatus.RUNNING.value == "RUNNING"
    assert AlignmentStatus.BLOCKED.value == "BLOCKED"
    assert AlignmentStatus.COMPLETED.value == "COMPLEEDD"
    assert AlignmentStatus.FAILED.value == "FAILED"
    assert AlignmentStatus.DEGRADED.value == "DEGRADED"

def test_node_router_keys():
    expected = ["start", "jd_profiling", "hard_gate_1", "gap_analysis",
                "style_router", "star_tailoring", "provenance_gate",
                "anti_hallucination_gate", "ats_scoring", "end"]
    assert list(NODE_ROUTER.keys()) == expected

def test_get_node():
    node = get_node("start")
    assert node["type"] == "pass_through"
    assert node["next"] == "jd_profiling"

def test_get_node_unknown():
    assert get_node("nonexistent") is None

def test_next_node():
    assert next_node("start") == "jd_profiling"
    assert next_node("end") == "end"
    assert next_node("nonexistent") == "end"