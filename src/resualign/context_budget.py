"""Context budget manager for LLM calls.

Controls input/output token budgets per Agent role to prevent
small models from being overwhelmed by long contexts.
"""

from __future__ import annotations

from typing import Optional

# Default budgets per role (input_tokens, output_tokens, compression_strategy)
_ROLE_BUDGETS: dict[str, tuple[int, int, str]] = {
    "diagnose": (2000, 500, "truncate"),
    "profiler": (3000, 500, "truncate"),
    "gap_analyzer": (2000, 400, "truncate"),
    "editor": (4000, 1500, "select"),
    "evaluator": (3000, 300, "truncate"),
}


class ContextBudgetExceeded(Exception):
    """Raised when input exceeds the budget and cannot be compressed."""


class ContextBudget:
    """Budget manager for Agent LLM calls.

    Each role has a configurable budget for input tokens, output tokens,
    and a compression strategy when input exceeds the budget.
    """

    def __init__(self, budgets: Optional[dict[str, tuple[int, int, str]]] = None):
        self._budgets = dict(_ROLE_BUDGETS)
        if budgets:
            self._budgets.update(budgets)

    # CJK 表意文字 + 假名 + 谚文 + 中文标点 + 全角形式：这些码位在
    # DeepSeek/GPT 系 tokenizer 下基本 1 字 = 1 token（或更贵），全部按 1.0
    # 计入，保证 estimate 是保守上界。
    _CJK_RANGES = (
        ("\u3000", "\u30ff"),  # CJK 标点与假名（含速记符号 3000-303F）
        ("\u3400", "\u4dbf"),  # CJK 扩展 A
        ("\u4e00", "\u9fff"),  # CJK 基本区
        ("\uac00", "\ud7af"),  # 谚文
        ("\uff00", "\uffef"),  # 全角形式（，。（）等）
    )

    @staticmethod
    def _is_cjk(ch: str) -> bool:
        """Whether a single char belongs to a ~1-token-per-char CJK range."""
        return any(lo <= ch <= hi for lo, hi in ContextBudget._CJK_RANGES)

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Rough token estimation: 1 token per CJK char, 4 chars per token otherwise.

        CJK scripts tokenize at roughly 1 token per character (DeepSeek/GPT
        family), so counting them at 1.0 keeps the estimate a conservative
        upper bound; the old ``len(text) // 4`` treated Chinese like ASCII
        and underestimated ~4x, so budgets never triggered compression.
        """
        if not text:
            return 0
        cjk = sum(1 for ch in text if ContextBudget._is_cjk(ch))
        other = len(text) - cjk
        return cjk + other // 4 + 1

    def get_budget(self, role: str) -> tuple[int, int, str]:
        """Return (input_budget, output_budget, compression_strategy) for a role."""
        return self._budgets.get(role, (2000, 500, "truncate"))

    def apply(self, role: str, text: str) -> str:
        """Apply the budget for a role to the input text.

        Returns the compressed text if it exceeds the budget.
        """
        input_budget, _, strategy = self.get_budget(role)
        estimated = self.estimate_tokens(text)
        if estimated <= input_budget:
            return text

        if strategy == "truncate":
            # Truncate to fit the budget, cutting on a sentence boundary
            # when one survives in the window.
            suffix = "\n[TRUNCATED: input exceeded budget]"
            target = input_budget - self.estimate_tokens(suffix)
            max_chars = self._chars_for_tokens(text, target)
            truncated = text[:max_chars]
            last_period = truncated.rfind(".")
            last_newline = truncated.rfind("\n")
            cut = max(last_period, last_newline)
            if cut > max_chars // 2:
                truncated = truncated[: cut + 1]
            # CJK 密度不均匀时按估算差额线性收缩，保证截断后真的在预算内
            while truncated and self.estimate_tokens(truncated) > target:
                over = self.estimate_tokens(truncated) - target
                truncated = truncated[: max(0, len(truncated) - over)]
            return truncated + suffix

        elif strategy == "select":
            # For editor: keep first and last 30% of the text
            max_chars = self._chars_for_tokens(text, input_budget)
            if len(text) <= max_chars:
                return text
            head_end = max_chars // 3
            tail_start = len(text) - max_chars // 3
            return text[:head_end] + "\n[...content truncated...]\n" + text[tail_start:]

        return text[: self._chars_for_tokens(text, input_budget)]

    @staticmethod
    def _chars_for_tokens(text: str, token_budget: int) -> int:
        """Convert a token budget into a char cut using the text's own density.

        ASCII-heavy text keeps the historical ~4 chars/token cut; CJK-heavy
        text cuts at ~1 char/token, consistent with estimate_tokens.
        """
        estimated = ContextBudget.estimate_tokens(text)
        density = max(estimated / max(len(text), 1), 1e-9)
        return max(1, int(token_budget / density))

    def set_budget(
        self,
        role: str,
        input_budget: int,
        output_budget: int,
        strategy: str = "truncate",
    ) -> None:
        """Override the budget for a role."""
        self._budgets[role] = (input_budget, output_budget, strategy)
