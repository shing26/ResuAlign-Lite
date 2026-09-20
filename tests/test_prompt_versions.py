"""Prompt-version registry: single source of truth for cached prompt stages."""

import pytest

from resualign import (
    classifier,
    evaluator,
    gap_analyzer,
    jd_analysis,
    jd_profiler,
    prompt_versions,
    resume_optimize,
)
from resualign.api.services import resumes
from resualign.engine import llm, tailor


def test_registry_covers_every_stage():
    assert set(prompt_versions.STAGES) == {
        prompt_versions.CLASSIFIER,
        prompt_versions.DIAGNOSE,
        prompt_versions.GAP_ANALYZER,
        prompt_versions.EVALUATOR,
        prompt_versions.JD_ANALYSIS,
        prompt_versions.JD_PROFILER,
        prompt_versions.RESUME_PROFILE,
        prompt_versions.RESUME_POLISH,
        prompt_versions.BULLET_REWRITE,
        prompt_versions.TAILOR,
    }
    for stage in prompt_versions.STAGES:
        assert prompt_versions.get_prompt_version(stage)


def test_unknown_stage_fails_loudly():
    with pytest.raises(KeyError, match="not registered"):
        prompt_versions.get_prompt_version("no_such_stage")


def test_module_constants_resolve_from_registry():
    assert classifier.CLASSIFIER_PROMPT_VERSION == prompt_versions.get_prompt_version(
        prompt_versions.CLASSIFIER
    )
    assert gap_analyzer.GAP_ANALYZER_PROMPT_VERSION == (
        prompt_versions.get_prompt_version(prompt_versions.GAP_ANALYZER)
    )
    assert evaluator.EVALUATOR_PROMPT_VERSION == prompt_versions.get_prompt_version(
        prompt_versions.EVALUATOR
    )
    assert jd_analysis.JD_ANALYSIS_PROMPT_VERSION == (
        prompt_versions.get_prompt_version(prompt_versions.JD_ANALYSIS)
    )
    assert jd_profiler.JD_PROFILER_PROMPT_VERSION == (
        prompt_versions.get_prompt_version(prompt_versions.JD_PROFILER)
    )
    assert llm.DIAG_PROMPT_VERSION == prompt_versions.get_prompt_version(
        prompt_versions.DIAGNOSE
    )
    assert resumes.PROFILE_PROMPT_VERSION == prompt_versions.get_prompt_version(
        prompt_versions.RESUME_PROFILE
    )
    assert resume_optimize.POLISH_PROMPT_VERSION == (
        prompt_versions.get_prompt_version(prompt_versions.RESUME_POLISH)
    )
    assert tailor.BULLET_REWRITE_PROMPT_VERSION == (
        prompt_versions.get_prompt_version(prompt_versions.BULLET_REWRITE)
    )
    assert tailor.TAILOR_PROMPT_VERSION == prompt_versions.get_prompt_version(
        prompt_versions.TAILOR
    )
