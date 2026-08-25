from .llm import LLMClient
from .models import GapReport
# PROMPT_VERSION bump: gap_analyzer/v1 -> v2（2026-08-25，对照 04b-PE §2.3）
# 本次升级说明：
# - 变更点 1：missing_keywords 由无上限改为 5-12 项、每项 ≤ 30 字符，语义重复合并
# - 变更点 2：misaligned_emphasis / strength_matches 数量封顶（0-4 / 2-8）
# - 变更点 3：删除「evidence-oriented 长配对短语」强推与假指令 Max tokens
# - 缓存影响：版本常量随文本变更 bump，缓存键自动失效（cache.py 以 prompt_version 为键）；
#   若只改文本不 bump，新旧提示词结果互串缓存（B3 类事故）。
GAP_ANALYZER_PROMPT_VERSION = "v2"


GAP_ANALYSIS_PROMPT = """PROMPT_VERSION: gap_analyzer/v2

你是简历-岗位差距分析师。对照岗位画像与主简历，找出简历与 JD 的差距。

## Output Contract（只能输出一个 JSON 对象，3 个字段，不得增减字段）
键名固定为：missing_keywords / misaligned_emphasis / strength_matches

- missing_keywords：JD 要求但简历未体现的关键词或紧凑配对短语，5-12 项，每项 ≤ 30 字符。当 JD 把技能与场景配对时用配对短语（如 "Redis caching for high concurrency"）；简历已有技能但缺场景时，也把配对短语列为缺口。语义重复的缺口合并为一项，不要堆砌同义表述。
- misaligned_emphasis：简历有但强调方向与 JD 不符的点，0-4 项，每项 ≤ 30 字符；没有给 []。
- strength_matches：简历已满足的 JD 要求（成功对接的证据），2-8 项，每项 ≤ 30 字符。

## 规则
1. 所有项必须能追溯到 JD 与简历原文（配对短语中的每个词都必须出现于原文），不得脑补；
2. 只列对简历改写有实际价值的缺口；同一技能的多个场景变体合并为一项；
3. 技术名词保留原文英文拼写。

## 提交前自查
- 3 个字段齐全、类型正确；数量与单项长度在上限内；无重复项；
- 只输出一个 JSON 对象，无 markdown fence，无解释文字。"""


def analyze_gaps(client: LLMClient, resume_text: str, jd_profile_text: str) -> GapReport:
    user = f"Resume:\n{resume_text}\n\nJD Profile:\n{jd_profile_text}"
    result = client.chat_json(GAP_ANALYSIS_PROMPT, user)
    return GapReport(
        missing_keywords=result.get("missing_keywords", []),
        misaligned_emphasis=result.get("misaligned_emphasis", []),
        strength_matches=result.get("strength_matches", []),
    )
