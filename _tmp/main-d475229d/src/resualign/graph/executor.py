"""GraphExecutor -- lightweight Pydantic-driven DAG executor for Compound AI."""
from __future__ import annotations
import logging
import time
from typing import Any, Callable, Optional
from .state import AlignmentState, AlignmentStatus, StageResult
from .router import get_node
from .gates import ProvenanceGate, AntiHallucinationGate, GateResult

logger = logging.getLogger(__name__)


class GraphExecutor:
    """Pydantic-driven lightweight DAG executor.
    Supports 4 node types: pass_through, deterministic, llm, llm_decision, terminal.
    """

    def __init__(
        self,
        llm_runner: Optional[Callable] = None,
        scorer_runner: Optional[Callable] = None,
    ):
        self.llm_runner = llm_runner
        self.scorer_runner = scorer_runner

    def _record_stage(self, state: AlignmentState, result: StageResult) -> None:
        result.stage = state.current_node
        state.stage_results.append(result)

    def run(self, state: AlignmentState) -> AlignmentState:
        current = "start"
        while current != "end" and state.status == AlignmentStatus.RUNNING:
            node = get_node(current)
            if node is None:
                logger.error("Unknown node %s, aborting", current)
                state.status = AlignmentStatus.FAILED
                break
            state.current_node = current
            node_type = node.get("type", "pass_through")
            try:
                if node_type == "pass_through":
                    self._run_pass_through(state, node)
                elif node_type == "deterministic":
                    self._run_deterministic(state, node)
                elif node_type == "llm":
                    self._run_llm(state, node)
                elif node_type == "llm_decision":
                    self._run_llm_decision(state, node)
                elif node_type == "terminal":
                    self._run_terminal(state, node)
                else:
                    logger.warning("Unknown node type %s, skipping", node_type)
            except Exception as exc:
                logger.error("Node %s failed: %s", current, exc)
                state.errors.append({"node": current, "error": str(exc)[:300]})
                fallback = node.get("fail_action", "mark_failed")
                if fallback == "mark_degraded":
                    state.status = AlignmentStatus.DEGRADED
                elif fallback == "mark_blocked":
                    state.status = AlignmentStatus.BLOCKED
                else:
                    state.status = AlignmentStatus.FAILED
                break
            state.completed_nodes.append(current)
            current = node.get("next", "end")

        if state.status == AlignmentStatus.RUNNING:
            state.status = AlignmentStatus.COMPLETED
        return state

    def _run_pass_through(self, state: AlignmentState, node: dict) -> None:
        sr = StageResult(stage=state.current_node, status="success")
        self._record_stage(state, sr)

    def _run_deterministic(self, state: AlignmentState, node: dict) -> None:
        gate_name = node.get("gate", "")
        fail_action = node.get("fail_action", "mark_failed")
        result = GateResult(passed=True)

        if gate_name == "minimum_requirements":
            result = self._check_minimum_requirements(state)
        elif gate_name == "provenance_check":
            result = self._check_provenance(state)
        elif gate_name == "hallucination_check":
            result = self._check_hallucination(state)
        elif node.get("scorer"):
            result = self._run_scorer(state, node)

        if not result.passed:
            if fail_action == "request_retry" and state.retry_count < state.max_retries:
                state.retry_count += 1
                state.current_node = "star_tailoring"
                sr = StageResult(
                    stage=state.current_node,
                    status="degraded",
                    error=f"Gate failed ({gate_name}), retrying ({state.retry_count}/{state.max_retries})",
                )
                self._record_stage(state, sr)
                return
            elif fail_action == "mark_degraded":
                state.status = AlignmentStatus.DEGRADED
            elif fail_action == "mark_blocked":
                state.status = AlignmentStatus.BLOCKED
            else:
                state.status = AlignmentStatus.FAILED
            sr = StageResult(
                stage=state.current_node,
                status="failed",
                error=f"Gate {gate_name} failed: {result.details[:2]}",
            )
            self._record_stage(state, sr)
            return

        sr = StageResult(stage=state.current_node, status="success")
        self._record_stage(state, sr)

    def _check_minimum_requirements(self, state: AlignmentState) -> GateResult:
        return GateResult(passed=True, score=1.0, details=["No minimum requirements check implemented"])

    def _check_provenance(self, state: AlignmentState) -> GateResult:
        if not state.tailored_draft:
            return GateResult(passed=True, score=1.0, details=["No tailored draft to check"])
        diffs = state.tailored_draft.get("diffs", [])
        result = ProvenanceGate.check(state.resume_text, diffs=diffs)
        state.provenance_ratio = result.score
        state.provenance_entities = result.entities
        return result

    def _check_hallucination(self, state: AlignmentState) -> GateResult:
        if not state.tailored_draft:
            return GateResult(passed=True, score=1.0, details=["No tailored draft to check"])
        diffs = state.tailored_draft.get("diffs", [])
        result = AntiHallucinationGate.check(state.resume_text, diffs=diffs)
        state.hallucination_flags = result.flags
        return result

    def _run_scorer(self, state: AlignmentState, node: dict) -> GateResult:
        if self.scorer_runner:
            return self.scorer_runner(state)
        return GateResult(passed=True, score=0.85, details=["Default ATS score (no scorer configured)"])

    def _run_llm(self, state: AlignmentState, node: dict) -> None:
        if self.llm_runner is None:
            logger.warning("No llm_runner configured, skipping LLM node %s", state.current_node)
            return
        t0 = time.monotonic()
        result = self.llm_runner(state, node)
        elapsed = (time.monotonic() - t0) * 1000
        sr = StageResult(
            stage=state.current_node,
            status="success",
            result=result,
            duration_ms=elapsed,
        )
        self._record_stage(state, sr)

    def _run_llm_decision(self, state: AlignmentState, node: dict) -> None:
        if self.llm_runner is None:
            logger.warning("No llm_runner configured, skipping LLM decision node %s", state.current_node)
            return
        t0 = time.monotonic()
        result = self.llm_runner(state, node)
        elapsed = (time.monotonic() - t0) * 1000
        sr = StageResult(
            stage=state.current_node,
            status="success",
            result=result,
            duration_ms=elapsed,
        )
        if result and isinstance(result, dict):
            output_key = node.get("output", "")
            if output_key:
                setattr(state, output_key, result.get("value", ""))
        self._record_stage(state, sr)

    def _run_terminal(self, state: AlignmentState, node: dict) -> None:
        state.status = AlignmentStatus.COMPLETED
        sr = StageResult(stage=state.current_node, status="success")
        self._record_stage(state, sr)

    def run_with_llm(
        self,
        state: AlignmentState,
        llm_runner: Callable,
        scorer_runner: Optional[Callable] = None,
    ) -> AlignmentState:
        self.llm_runner = llm_runner
        self.scorer_runner = scorer_runner
        return self.run(state)
