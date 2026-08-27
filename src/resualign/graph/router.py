"""Node router configuration for the alignment Graph."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class NodeDef(BaseModel):
    next: str = ""
    type: str = "pass_through"
    role: str = ""
    timeout: float = 15.0
    max_retries: int = 1
    gate: str = ""
    fail_action: str = "mark_failed"
    block_action: str = "mark_blocked"
    scorer: str = ""
    decision: str = ""
    output: str = ""
    description: str = ""

NODE_ROUTER: dict[str, dict[str, Any]] = {
    "start": {
        "next": "jd_profiling", "type": "pass_through",
        "description": "Entry point -- route to JD profiling.",
    },
    "jd_profiling": {
        "next": "hard_gate_1", "type": "llm", "role": "profiler",
        "timeout": 15.0, "max_retries": 1,
        "description": "LLM-based JD profiling: extract structured profile from JD text.",
    },
    "hard_gate_1": {
        "next": "gap_analysis", "type": "deterministic",
        "gate": "minimum_requirements", "block_action": "mark_blocked",
        "description": "Hard gate: check min years, education, sensitivity keywords.",
    },
    "gap_analysis": {
        "next": "style_router", "type": "llm", "role": "gap_analyzer",
        "timeout": 15.0,
        "description": "LLM-based gap analysis: compare resume against JD profile.",
    },
    "style_router": {
        "next": "star_tailoring", "type": "llm_decision",
        "role": "editor", "decision": "route_style", "output": "rewrite_style",
        "description": "LLM decision: route rewrite style (deep/architecture/general).",
    },
    "star_tailoring": {
        "next": "provenance_gate", "type": "llm", "role": "editor",
        "timeout": 40.0, "max_retries": 1,
        "description": "LLM-based STAR tailoring: rewrite resume sections to close gaps.",
    },
    "provenance_gate": {
        "next": "anti_hallucination_gate", "type": "deterministic",
        "gate": "provenance_check", "fail_action": "request_retry",
        "description": "Deterministic gate: >=80% of diff entities must belong to Master Resume.",
    },
    "anti_hallucination_gate": {
        "next": "ats_scoring", "type": "deterministic",
        "gate": "hallucination_check", "fail_action": "mark_degraded",
        "description": "Deterministic gate: cross-check numbers and entities against original.",
    },
    "ats_scoring": {
        "next": "end", "type": "deterministic",
        "scorer": "keyword_density_ats",
        "description": "Deterministic ATS scoring: keyword density + structure + experience match.",
    },
    "end": {
        "type": "terminal",
        "description": "Terminal node -- triggers outer FSM transition.",
    },
}

def get_node(name: str) -> Optional[dict[str, Any]]:
    return NODE_ROUTER.get(name)

def next_node(current: str) -> str:
    node = NODE_ROUTER.get(current)
    if node is None:
        return "end"
    return node.get("next", "end")
