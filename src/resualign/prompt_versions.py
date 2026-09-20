"""Single registry for LLM prompt versions (extension point).

Every prompt that can be cached or persisted carries a version string. Before
this module the constants were scattered across ten prompt modules, so adding
a stage meant remembering a fourth or fifth place. Now the registry is the one
place to register a version, and an unregistered stage fails loudly instead of
silently falling back to a default.

Bump rules (unchanged, now documented once):

- A prompt text change that can alter output MUST bump its version, or cached
  old/new results interleave under the same key (the B3 incident class).
- ``prompt_version`` is used as a cache key (see ``cache.py``) and is persisted
  on library jobs for traceability.
"""

from __future__ import annotations

CLASSIFIER = "classifier"
DIAGNOSE = "diagnose"
GAP_ANALYZER = "gap_analyzer"
EVALUATOR = "evaluator"
JD_ANALYSIS = "jd_analysis"
JD_PROFILER = "jd_profiler"
RESUME_PROFILE = "resume_profile"
RESUME_POLISH = "resume_polish"
BULLET_REWRITE = "bullet_rewrite"
TAILOR = "tailor"

# Registry: stage -> prompt version. Keep this table the only place a stage
# version is declared; modules re-export their constant from here.
_PROMPT_VERSIONS: dict[str, str] = {
    # 运行时版本标记（2026-08-25 新增）。缓存键仍用 sha256(prompt+词表)，
    # 词表变化自动失效；本常量服务于指标/日志追溯。
    CLASSIFIER: "v2",
    # PROMPT_VERSION bump: diag/v2 -> v3
    DIAGNOSE: "v3",
    # PROMPT_VERSION bump: gap_analyzer/v1 -> v2（2026-08-25，对照 04b-PE §2.3）
    # 变更点：missing_keywords 5-12 项、每项 ≤ 30 字符；misaligned/strength
    # 数量封顶；删除假指令 Max tokens。
    GAP_ANALYZER: "v2",
    # PROMPT_VERSION bump: evaluator/v1 -> v2（2026-08-25，对照 04b-PE §2.6）
    # 变更点：评分锚点与不确定兜底值；hallucination 判定边界收紧。
    EVALUATOR: "v2",
    # PROMPT_VERSION bump: jd-analysis-v2 -> v3（2026-08-25，对照 04b-PE §2.4）
    # 变更点：组合契约改为纯静态文本；各字段带数量/长度上限。
    JD_ANALYSIS: "jd-analysis-v3",
    # PROMPT_VERSION bump: jd_profiler/v1 -> v2（2026-08-25，对照 04b-PE §2.2）
    # 变更点：business_scenarios 0-6 项封顶；各列表数量/长度封顶。
    JD_PROFILER: "v2",
    RESUME_PROFILE: "resume-profile:v1",
    # PROMPT_VERSION bump: polish/v1 -> v2
    RESUME_POLISH: "v2",
    # PROMPT_VERSION bump: bullet_rewrite/v2 -> v3（2026-08-27，Few-Shot 强动词库）
    BULLET_REWRITE: "v3",
    # PROMPT_VERSION bump: tailor/v1 -> v2（2026-08-25，对照 04b-PE §2.5）
    # 变更点：规则压缩为 7 条；diffs 3-10 条；provenance 必须逐字匹配。
    TAILOR: "v2",
}

STAGES: tuple[str, ...] = tuple(_PROMPT_VERSIONS)


def get_prompt_version(stage: str) -> str:
    """Return the registered prompt version for ``stage``.

    Raises ``KeyError`` for an unregistered stage: a prompt that is not in
    the registry must not silently run under an unknown/default version.
    """
    try:
        return _PROMPT_VERSIONS[stage]
    except KeyError as exc:
        raise KeyError(
            f"prompt stage {stage!r} is not registered; add it to "
            "resualign.prompt_versions._PROMPT_VERSIONS"
        ) from exc
