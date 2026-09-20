"""Pure alignment-result rules shared by the job runner and writer.

These predicates decide what counts as verified advice, what counts as
usable output, and what user-facing notice accompanies a saved run. They
carry no store or registry access so both the runner (``jobs.py``) and the
persistence writer (``alignment_writer.py``) can depend on them without a
cycle.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def is_noop_diff(diff: dict[str, Any]) -> bool:
    """Return True when a modify/remove diff changes nothing.

    Phase A2 (2026-08-30): whole-document editors occasionally emit a
    ``modify`` diff whose ``proposed`` equals ``original`` (model states
    "no measurable outcomes... remains unchanged" yet still returns a
    diff). Such no-op suggestions consume UI slots without adding value;
    they are moved to ``invalid_diffs`` instead of counting as advice.
    """
    if diff.get("type") not in ("modify", "remove"):
        return False
    original = (diff.get("original") or "").strip()
    proposed = (diff.get("proposed") or "").strip()
    return bool(original) and original == proposed


def report_has_gap(gap_report: Any) -> bool:
    """#111 / ADR-0041 决定 5 分型谓词：缺口证据 = missing/misaligned 非空。

    None/空报告一律视为「无缺口」——7B 摆烂与真无缺口数据同形，宁可保守
    （零产出但无证据时保 succeeded + 「无缺口 · 无需改写」徽章，由换模型
    引导兜底），也不凭猜把一轮 run 判成质量失败。
    """
    if not isinstance(gap_report, dict):
        return False
    return bool(gap_report.get("missing_keywords")) or bool(
        gap_report.get("misaligned_emphasis")
    )


def split_verified_diffs(
    raw_diffs: list[dict[str, Any]],
    invalid_diffs: list[dict[str, Any]],
    *,
    eval_hallucinated: bool,
    job_label: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(kept, invalid)`` after the zero-hallucination gate.

    P0（2026-09-06 安全审查 #74）：evaluator 自评判定幻觉时硬阻断——本轮
    diffs 不作为已验证建议保存，整体降级 invalid（ADR-0019 零幻觉硬门）。
    Phase A2：否则剔除 no-op diffs 并把它们折进 invalid_diffs。
    """
    if eval_hallucinated and raw_diffs:
        blocked = []
        for diff in raw_diffs:
            diff = dict(diff)
            diff["provenance_state"] = "fabricated"
            reason = (diff.get("reason") or "").rstrip("；;。 ")
            diff["reason"] = (
                f"{reason}；真实性评估判定本轮改写存在无依据内容，已整体拦截"
                if reason
                else "真实性评估判定本轮改写存在无依据内容，已整体拦截"
            )
            blocked.append(diff)
        logger.warning(
            "library job %s: evaluator flagged hallucination; "
            "blocked %d diff(s) from verified advice",
            job_label,
            len(raw_diffs),
        )
        return [], list(invalid_diffs) + blocked
    noop_diffs = [diff for diff in raw_diffs if is_noop_diff(diff)]
    kept = [diff for diff in raw_diffs if not is_noop_diff(diff)]
    invalid = list(invalid_diffs)
    if noop_diffs:
        logger.info(
            "library job %s: filtered %d no-op diff(s) out of %d",
            job_label,
            len(noop_diffs),
            len(raw_diffs),
        )
        invalid.extend(noop_diffs)
    return kept, invalid


def resolve_alignment_outcome(
    *,
    kept_diffs: list[dict[str, Any]],
    gap_report: Any,
    tailor_degraded: bool,
    eval_hallucinated: bool,
) -> tuple[str, str | None]:
    """Return ``(alignment_status, alignment_error)`` for a finished run."""
    if tailor_degraded:
        alignment_error: str | None = (
            "改写阶段多次失败，本轮只产出诊断与缺口分析；"
            "点击「重新运行对齐」补齐改写建议（已缓存阶段会跳过）"
        )
    elif eval_hallucinated and not kept_diffs:
        alignment_error = (
            "真实性评估判定本轮改写存在无依据内容，"
            "全部建议已拦截；请核对后重试对齐"
        )
    else:
        alignment_error = None
    # ADR-0041 决定 5 分型甲（#111）：有缺口 ∧ usable=0 = 质量失败——就该红、
    # 可重跑（旧语义「全 noop/全拦截仍 succeeded」废除）。「no_output: 」
    # 前缀是机读契约，投影据此派生 alignment_reason；无缺口 ∧ usable=0 维持
    # succeeded，由前端渲染「无缺口 · 无需改写」。
    alignment_status = "succeeded"
    if not kept_diffs and report_has_gap(gap_report):
        alignment_status = "failed"
        alignment_error = (
            "no_output: "
            + (
                alignment_error
                or "该岗位存在能力/经验缺口，但本轮未产出任何可用改写建议"
            )
        )
    return alignment_status, alignment_error
