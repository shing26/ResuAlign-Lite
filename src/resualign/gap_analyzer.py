from .engine.llm import LLMClient, _structured_or_json
from .models import GapReport
from .prompt_versions import GAP_ANALYZER as _GAP_ANALYZER_STAGE
from .prompt_versions import get_prompt_version
from .schema_registry import GapReportSchema

# PROMPT_VERSION bump: gap_analyzer/v1 -> v2（2026-08-25，对照 04b-PE §2.3）
# 本次升级说明：
# - 变更点 1：missing_keywords 由无上限改为 5-12 项、每项 ≤ 30 字符，语义重复合并
# - 变更点 2：misaligned_emphasis / strength_matches 数量封顶（0-4 / 2-8）
# - 变更点 3：删除「evidence-oriented 长配对短语」强推与假指令 Max tokens
# - 缓存影响：版本常量随文本变更 bump，缓存键自动失效（cache.py 以 prompt_version 为键）；
#   若只改文本不 bump，新旧提示词结果互串缓存（B3 类事故）。
# PROMPT_VERSION bump: gap_analyzer/v2 -> v3（2026-10-19，#164）
# 本次升级说明：
# - 变更点 1：拆出 supported_keywords——JD 要求、简历原文已有依据但没写明
#   的词，是唯一可进 gate allowlist 的新术语来源；
# - 变更点 2：missing_keywords 收窄为「简历原文完全没有依据」的真缺口，
#   只用于诊断/评分/UI，永不进 allowlist（原先它同时承担两个语义，导致
#   「JD 要什么」被当成「我会什么」假通过内容级校验）。
GAP_ANALYZER_PROMPT_VERSION = get_prompt_version(_GAP_ANALYZER_STAGE)


GAP_ANALYSIS_PROMPT = """PROMPT_VERSION: gap_analyzer/v3

你是简历-岗位差距分析师。对照岗位画像与主简历，找出简历与 JD 的差距。

## Output Contract（只能输出一个 JSON 对象，4 个字段，不得增减字段）
键名固定为：supported_keywords / missing_keywords / misaligned_emphasis / strength_matches

- supported_keywords：JD 要求、而简历原文**已有事实依据**（同一技能或场景在简历里出现过）但简历没有明确写出来的关键词或紧凑配对短语，0-8 项，每项 ≤ 30 字符。例如简历写了「基于 Redis 的缓存」，JD 要 "Redis caching for high concurrency"，则该项属于 supported_keywords。这是唯一允许作为「新说法」写进简历的来源。
- missing_keywords：JD 要求、而简历原文**完全没有依据**的真缺口，0-12 项，每项 ≤ 30 字符。只用于诊断与差距说明，**禁止**写进简历。语义重复的缺口合并为一项，不要堆砌同义表述。
- misaligned_emphasis：简历有但强调方向与 JD 不符的点，0-4 项，每项 ≤ 30 字符；没有给 []。
- strength_matches：简历已满足的 JD 要求（成功对接的证据），2-8 项，每项 ≤ 30 字符。

## 规则
1. supported_keywords 与 missing_keywords 互斥：能在简历里找到事实依据的进 supported_keywords，找不到任何依据的才进 missing_keywords；
2. 所有项必须能追溯到 JD 原文，不得脑补；同一技能的多个场景变体合并为一项；
3. 技术名词保留原文英文拼写。

## 提交前自查
- 4 个字段齐全、类型正确；数量与单项长度在上限内；无重复项；
- supported_keywords 里的每一项都能在简历原文里指出依据；
- 只输出一个 JSON 对象，无 markdown fence，无解释文字。"""


def analyze_gaps(
    client: LLMClient,
    resume_text: str,
    jd_profile_text: str,
    cache=None,
    tenant: str = "default",
    model=None,
) -> GapReport:
    resolved_model = model or getattr(client, "model", "default")
    # 缓存键同时覆盖两个输入（简历 + JD 画像）；分隔符用原文不可能出现的
    # 控制字符，避免不同配对方式拼出同一键。画像本身已被 profiler 缓存、
    # 内容稳定，因此「同简历同岗位重跑」整段 gap 调用可复用。
    cache_content = f"{resume_text}\x1e{jd_profile_text}"
    if cache is not None:
        cached = cache.get(
            tenant,
            resolved_model,
            GAP_ANALYZER_PROMPT_VERSION,
            cache_content,
        )
        if cached is not None:
            return GapReport(
                supported_keywords=cached.get("supported_keywords", []),
                missing_keywords=cached.get("missing_keywords", []),
                misaligned_emphasis=cached.get("misaligned_emphasis", []),
                strength_matches=cached.get("strength_matches", []),
            )
    user = f"Resume:\n{resume_text}\n\nJD Profile:\n{jd_profile_text}"
    # R4 §2.3-附（04b-PE）：chat_json → _structured_or_json —— gap 获得 schema 校验
    # + 纠错重试（max_retries=1，最多 2 次往返）。配套义务（AIE P0-5）：
    # engine.py:212-227 在结构失败（code ∈ schema/parse/empty）时降级为空 gap +
    # gap_degraded，不整体 fail；本行与降级 patch 同时合入（合入顺序：降级先于/同时）。
    result = _structured_or_json(client, GAP_ANALYSIS_PROMPT, user, GapReportSchema)
    gap = GapReport(
        supported_keywords=result.get("supported_keywords", []),
        missing_keywords=result.get("missing_keywords", []),
        misaligned_emphasis=result.get("misaligned_emphasis", []),
        strength_matches=result.get("strength_matches", []),
    )
    if cache is not None:
        cache.put(
            tenant,
            resolved_model,
            GAP_ANALYZER_PROMPT_VERSION,
            cache_content,
            gap.__dict__,
        )
    return gap
