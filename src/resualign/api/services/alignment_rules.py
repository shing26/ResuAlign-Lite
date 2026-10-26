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

from ...alignment_lifecycle import gap_report_has_gap

logger = logging.getLogger(__name__)


def humanize_alignment_error(message: str | None) -> str | None:
    """Strip the ADR-0041 machine prefix for user-facing projections."""
    text = str(message or "").strip()
    if text.startswith("no_output:"):
        text = text.split(":", 1)[1].strip()
    return text or None


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
    """#111 / ADR-0041 决定 5 分型谓词：缺口证据 = 可行动方向非空。

    None/空报告一律视为「无缺口」——7B 摆烂与真无缺口数据同形，宁可保守
    （零产出但无证据时保 succeeded + 「无缺口 · 无需改写」徽章，由换模型
    引导兜底），也不凭猜把一轮 run 判成质量失败。
    """
    return gap_report_has_gap(gap_report)


def strip_placeholders_in_diffs(
    diffs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Strip legacy metric placeholders from ``proposed`` before projecting.

    2026-10-26（P0 成效审计）：占位串「[待人工确认：…]」历史上被注入
    `proposed`，会成为简历正文。投影层统一剥离，让旧建议立刻可采纳，
    不改写库内原始数据。
    """
    from ...engine.tailor import strip_metric_placeholders

    cleaned: list[dict[str, Any]] = []
    for diff in diffs:
        if not isinstance(diff, dict):
            cleaned.append(diff)
            continue
        proposed = diff.get("proposed")
        if isinstance(proposed, str) and proposed:
            stripped = strip_metric_placeholders(proposed)
            if stripped != proposed:
                diff = {**diff, "proposed": stripped}
        cleaned.append(diff)
    return cleaned


def split_verified_diffs(
    raw_diffs: list[dict[str, Any]],
    invalid_diffs: list[dict[str, Any]],
    *,
    eval_hallucinated: bool,
    eval_hallucinated_diff_ids: list[str] | None = None,
    job_label: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(kept, invalid)`` after the zero-hallucination gate.

    P0（2026-09-06 安全审查 #74）：evaluator 自评判定幻觉时不得冒充已验证
    建议。2026-10-19 起若 evaluator 给出 `hallucinated_diff_ids`，只隔离被
    指认的 diff；没有 id 映射时回退整轮硬阻断（ADR-0019 零幻觉硬门）。
    Phase A2：剔除 no-op diffs 并把它们折进 invalid_diffs。
    """
    if eval_hallucinated and raw_diffs:
        flagged_ids = {
            str(diff_id)
            for diff_id in (eval_hallucinated_diff_ids or [])
            if str(diff_id)
        }
        if flagged_ids:
            blocked_source = [
                diff
                for diff in raw_diffs
                if str(diff.get("diff_id") or "") in flagged_ids
            ]
            kept_source = [
                diff
                for diff in raw_diffs
                if str(diff.get("diff_id") or "") not in flagged_ids
            ]
            if not blocked_source:
                blocked_source = list(raw_diffs)
                kept_source = []
        else:
            blocked_source = list(raw_diffs)
            kept_source = []
        blocked = []
        for diff in blocked_source:
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
            "blocked %d of %d diff(s) from verified advice",
            job_label,
            len(blocked_source),
            len(raw_diffs),
        )
        noop_diffs = [diff for diff in kept_source if is_noop_diff(diff)]
        kept = [diff for diff in kept_source if not is_noop_diff(diff)]
        return kept, list(invalid_diffs) + noop_diffs + blocked
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
    no_safe_rewrite: bool = False,
    no_safe_rewrite_reason: str = "",
) -> tuple[str, str | None, str | None]:
    """Return ``(status, error, reason)`` for a finished alignment run.

    ``alignment_error`` keeps the ADR-0041 ``no_output:`` machine prefix for
    zero-output quality failures. ``reason`` adds the user-facing terminal
    classification without changing that contract.
    """
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
    elif no_safe_rewrite:
        alignment_error = (
            no_safe_rewrite_reason.strip()
            or "岗位存在缺口，但简历原文没有足够依据，因此没有安全改写。"
        )
    else:
        alignment_error = None
    # ADR-0041 决定 5 分型甲（#111）：有缺口 ∧ usable=0 = 质量失败——就该红、
    # 可重跑（旧语义「全 noop/全拦截仍 succeeded」废除）。「no_output: 」
    # 前缀是机读契约，投影据此派生 alignment_reason。无缺口 ∧ usable=0
    # 且没有真实性拦截时维持 succeeded；但 evaluator 已判幻觉并拦空全部
    # 建议时，必须失败，不能靠“缺口列表为空”留下假绿灯。
    blocked_hallucination = eval_hallucinated and not kept_diffs
    alignment_status = "succeeded"
    if not kept_diffs and (
        report_has_gap(gap_report)
        or blocked_hallucination
        or no_safe_rewrite
        or tailor_degraded
    ):
        alignment_status = "failed"
        alignment_error = (
            "no_output: "
            + (
                alignment_error
                or "该岗位存在能力/经验缺口，但本轮未产出任何可用改写建议"
            )
        )
    if not kept_diffs:
        if no_safe_rewrite:
            alignment_reason: str | None = "no_safe_rewrite"
        elif alignment_status == "failed":
            alignment_reason = "model_failed"
        else:
            alignment_reason = "no_gap"
    else:
        alignment_reason = None
    return alignment_status, alignment_error, alignment_reason
