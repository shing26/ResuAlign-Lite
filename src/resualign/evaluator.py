from .llm import _structured_or_json
from .models import EvalScore
from .schema_registry import EvalScoreSchema
from .tailor import parse_diff_with_provenance

# PROMPT_VERSION bump: evaluator/v1 -> v2（2026-08-25，对照 04b-PE §2.6）
# 本次升级说明：
# - 变更点 1：评分锚点（80+/60-79/<60）与不确定兜底值（50/0/0.0），不鼓励极端 0
# - 变更点 2：hallucination 判定边界收紧（措辞调整/同义改写不视为幻觉），details 0-5 条
# - 变更点 3：删除假指令 Max tokens/Temperature
# - 缓存影响：版本常量随文本变更 bump，缓存键自动失效。
EVALUATOR_PROMPT_VERSION = "v2"


EVAL_PROMPT = """PROMPT_VERSION: evaluator/v2

你是简历质量裁判。输入：原始主简历（Original）、改写后简历（Tailored）、岗位描述（JD），可选差距报告（Gap Report）。评估改写质量并做真实性检查。

## Output Contract（只能输出一个 JSON 对象，5 个字段）
键名固定为：jd_match_score / improvement / hallucination_detected / hallucination_details / gap_coverage

- jd_match_score：改写后简历与 JD 要求的匹配度，0-100 整数。锚点：80+ = 高度匹配；60-79 = 基本匹配；<60 = 明显不足。
- improvement：相对原始简历的提升度，0-100 整数；无实质提升给 0-10；改动引入新问题可给负向说明（仍输出 ≥0 的整数）。
- gap_coverage：改写覆盖的差距比例，0.0-1.0 小数；按差距报告条目数估算（无差距报告时按 JD 关键要求估算）。
- hallucination_detected：仅当 proposed/改写内容中的事实（技能、数字、公司、项目名）在原始简历中无任何依据时为 true。措辞调整、同义词改写、换序不视为幻觉。
- hallucination_details：0-5 条，每条 ≤ 80 字；逐条写「可疑事实 + 为什么无依据」；无幻觉给 []。

## 规则
- 不确定时：jd_match_score 给 50、improvement 给 0、gap_coverage 给 0.0；不要给极端值（0 会让"0 分匹配"与确定性兜底信息混淆）。
- 只输出 JSON，无 markdown fence，无解释文字。"""

def evaluate(client, original_resume, tailored_text, jd_text, diffs=None):
    user = (
        f"Original:\n{original_resume}\n\n"
        f"Tailored:\n{tailored_text}\n\n"
        f"JD:\n{jd_text}"
    )
    result = _structured_or_json(client, EVAL_PROMPT, user, EvalScoreSchema)
    hallucination_detected = bool(result.get("hallucination_detected", False))
    try:
        gap_coverage = float(result.get("gap_coverage", 0.0))
    except (TypeError, ValueError):
        gap_coverage = 0.0
    gap_coverage = max(0.0, min(1.0, gap_coverage))
    hallucination_details = list(result.get("hallucination_details") or [])
    if diffs:
        for diff in diffs:
            if isinstance(diff, dict):
                _, valid = parse_diff_with_provenance(diff, original_resume)
                quote = str(
                    diff.get("provenance_quote")
                    or diff.get("provenance")
                    or ""
                ).strip()
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
            if not valid:
                hallucination_detected = True
                hallucination_details.append(
                    "Diff provenance not found in original resume: "
                    + (quote or "<empty>")
                )
    return EvalScore(
        jd_match_score=result.get("jd_match_score", 0),
        improvement=result.get("improvement", 0),
        hallucination_detected=hallucination_detected,
        hallucination_details=hallucination_details,
        gap_coverage=gap_coverage,
    )
