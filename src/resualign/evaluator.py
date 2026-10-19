from __future__ import annotations

import json as _json

from .engine.llm import _structured_or_json
from .engine.tailor import parse_diff_with_provenance
from .models import EvalScore
from .prompt_versions import EVALUATOR as _EVALUATOR_STAGE
from .prompt_versions import get_prompt_version
from .schema_registry import EvalScoreSchema

# PROMPT_VERSION bump: evaluator/v1 -> v2（2026-08-25，对照 04b-PE §2.6）
# 本次升级说明：
# - 变更点 1：评分锚点（80+/60-79/<60）与不确定兜底值（50/0/0.0），不鼓励极端 0
# - 变更点 2：hallucination 判定边界收紧（措辞调整/同义改写不视为幻觉），details 0-5 条
# - 变更点 3：删除假指令 Max tokens/Temperature
# - 缓存影响：版本常量随文本变更 bump，缓存键自动失效。
# v2 -> v3（2026-10-19）：逐条隔离——输出 hallucinated_diff_ids，
# 让调用方只拦被指认的 diff，而不是一次幻觉否决整轮。
EVALUATOR_PROMPT_VERSION = get_prompt_version(_EVALUATOR_STAGE)


EVAL_PROMPT = """PROMPT_VERSION: evaluator/v3

你是简历质量裁判。输入：原始主简历（Original）、改写后简历（Tailored）、岗位描述（JD），可选差距报告（Gap Report）。评估改写质量并做真实性检查。

## Output Contract（只能输出一个 JSON 对象，6 个字段）
键名固定为：jd_match_score / improvement / hallucination_detected / hallucination_details / hallucinated_diff_ids / gap_coverage

- jd_match_score：改写后简历与 JD 要求的匹配度，0-100 整数。锚点：80+ = 高度匹配；60-79 = 基本匹配；<60 = 明显不足。
- improvement：相对原始简历的提升度，0-100 整数；无实质提升给 0-10；改动引入新问题可给负向说明（仍输出 ≥0 的整数）。
- gap_coverage：改写覆盖的差距比例，0.0-1.0 小数；按差距报告条目数估算（无差距报告时按 JD 关键要求估算）。
- hallucination_detected：仅当 proposed/改写内容中的事实（技能、数字、公司、项目名）在原始简历中无任何依据时为 true。措辞调整、同义词改写、换序不视为幻觉。
- hallucination_details：0-5 条，每条 ≤ 80 字；逐条写「可疑事实 + 为什么无依据」；无幻觉给 []。
- hallucinated_diff_ids：只列实际无依据的 diff_id；每条 id 必须逐字来自输入 Diffs。无法映射到具体 diff 时给 []，系统会保守地整轮拦截。

## 规则
- 不确定时：jd_match_score 给 50、improvement 给 0、gap_coverage 给 0.0；不要给极端值（0 会让"0 分匹配"与确定性兜底信息混淆）。
- 只输出 JSON，无 markdown fence，无解释文字。"""

def evaluate(client, original_resume, tailored_text, jd_text, diffs=None):
    diff_manifest = []
    if diffs:
        for diff in diffs:
            if isinstance(diff, dict):
                diff_manifest.append(
                    {
                        "diff_id": diff.get("diff_id") or "",
                        "section": diff.get("section") or "",
                        "original": diff.get("original") or "",
                        "proposed": diff.get("proposed") or "",
                        "provenance": diff.get("provenance_quote")
                        or diff.get("provenance")
                        or "",
                    }
                )
            else:
                diff_manifest.append(
                    {
                        "diff_id": getattr(diff, "diff_id", "") or "",
                        "section": getattr(diff, "section", "") or "",
                        "original": getattr(diff, "original", "") or "",
                        "proposed": getattr(diff, "proposed", "") or "",
                        "provenance": getattr(diff, "provenance_quote", "")
                        or getattr(diff, "provenance", "")
                        or "",
                    }
                )
    user = (
        f"Original:\n{original_resume}\n\n"
        f"Tailored:\n{tailored_text}\n\n"
        f"JD:\n{jd_text}"
    )
    if diff_manifest:
        user += "\n\nDiffs:\n" + _json.dumps(
            diff_manifest, ensure_ascii=False, indent=2
        )
    result = _structured_or_json(client, EVAL_PROMPT, user, EvalScoreSchema)
    hallucination_detected = bool(result.get("hallucination_detected", False))
    known_diff_ids = {
        item["diff_id"] for item in diff_manifest if item.get("diff_id")
    }
    raw_diff_ids = result.get("hallucinated_diff_ids") or []
    if not isinstance(raw_diff_ids, list):
        raw_diff_ids = []
    hallucinated_diff_ids = [
        str(diff_id)
        for diff_id in raw_diff_ids
        if str(diff_id) in known_diff_ids
    ]
    try:
        gap_coverage = float(result.get("gap_coverage", 0.0))
    except (TypeError, ValueError):
        gap_coverage = 0.0
    gap_coverage = max(0.0, min(1.0, gap_coverage))
    hallucination_details = list(result.get("hallucination_details") or [])
    unmapped_hallucination = False
    if diffs:
        for diff in diffs:
            if isinstance(diff, dict):
                _, valid = parse_diff_with_provenance(diff, original_resume)
                quote = str(
                    diff.get("provenance_quote")
                    or diff.get("provenance")
                    or ""
                ).strip()
                diff_id = str(diff.get("diff_id") or "")
            else:
                quote = str(
                    getattr(diff, "provenance_quote", "")
                    or getattr(diff, "provenance", "")
                    or ""
                ).strip()
                original = str(getattr(diff, "original", "") or "")
                valid = bool(
                    quote and quote in original_resume
                ) or (
                    getattr(diff, "type", "") == "add"
                    and not original.strip()
                )
                diff_id = str(getattr(diff, "diff_id", "") or "")
            if not valid:
                hallucination_detected = True
                hallucination_details.append(
                    "Diff provenance not found in original resume: "
                    + (quote or "<empty>")
                )
                if diff_id:
                    if diff_id not in hallucinated_diff_ids:
                        hallucinated_diff_ids.append(diff_id)
                else:
                    unmapped_hallucination = True
    if unmapped_hallucination:
        # A flagged diff without an id cannot be quarantined safely; force
        # the caller back to the conservative whole-run block.
        hallucinated_diff_ids = []
    return EvalScore(
        jd_match_score=result.get("jd_match_score", 0),
        improvement=result.get("improvement", 0),
        hallucination_detected=hallucination_detected,
        hallucination_details=hallucination_details,
        hallucinated_diff_ids=hallucinated_diff_ids,
        gap_coverage=gap_coverage,
    )
