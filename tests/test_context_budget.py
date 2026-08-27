"""Tests for ContextBudget token estimation and per-role budgets."""

from resualign.context_budget import ContextBudget


def test_estimate_tokens_cjk_counts_one_token_per_char():
    # 中文 ≈1 字 1 token：10 个汉字应估为 ~10，而不是旧口径的 len//4 ≈ 2
    text = "简历优化建议" * 2  # 12 个汉字
    estimated = ContextBudget.estimate_tokens(text)
    assert 12 <= estimated <= 13


def test_estimate_tokens_mixed_cjk_and_ascii():
    # 6 个汉字 + 8 个 ASCII 字符：CJK 计 6，ASCII 按 4 字符/token 计 2
    text = "简历优化建议abcd1234"
    estimated = ContextBudget.estimate_tokens(text)
    assert estimated == 9  # 6 + 8 // 4 + 1


def test_estimate_tokens_ascii_still_quarter():
    estimated = ContextBudget.estimate_tokens("abcdefgh")  # 8 ASCII 字符
    assert estimated == 3  # 8 // 4 + 1


def test_estimate_tokens_empty():
    assert ContextBudget.estimate_tokens("") == 0


def test_budget_triggers_compression_on_long_chinese_text():
    # 8000 字中文按旧口径只估 ~2001（刚好压线不触发），新口径必须触发压缩
    budget = ContextBudget()
    long_chinese = "简历" * 4000  # 8000 个汉字
    compressed = budget.apply("diagnose", long_chinese)
    assert len(compressed) < len(long_chinese)
    # 截断结果（去掉标记行）须真正落入预算内：约 2000 token 而非 8000
    body = compressed.rsplit("\n[TRUNCATED", 1)[0]
    assert ContextBudget.estimate_tokens(body) <= 2000


def test_budget_ascii_cut_ratio_unchanged():
    # ASCII 文本保持历史 4 字符/token 的截断比例
    budget = ContextBudget()
    long_ascii = "a" * 20000
    compressed = budget.apply("diagnose", long_ascii)
    body = compressed.rsplit("\n[TRUNCATED", 1)[0]
    assert len(body) <= 2000 * 4 + 1
