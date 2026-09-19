"""Contract layer: stable LLM failure codes (hardening 2026-09-19).

The point of the enum is that the nine codes live in one place while four
modules keep consuming them positionally. These tests pin the value set, the
``str`` compatibility that keeps existing comparisons working, and the
consumer sets that must hold plain values (an Enum mixin overrides
``__hash__``, so a set of members would silently stop matching).
"""

from __future__ import annotations

from resualign.contracts.errors import KNOWN_LLM_FAILURE_CODES, LlmFailureCode
from resualign.llm import LLMResponseError

EXPECTED = {
    "timeout": LlmFailureCode.TIMEOUT,
    "empty": LlmFailureCode.EMPTY,
    "parse": LlmFailureCode.PARSE,
    "schema": LlmFailureCode.SCHEMA,
    "quota": LlmFailureCode.QUOTA,
    "rate_limit": LlmFailureCode.RATE_LIMIT,
    "auth": LlmFailureCode.AUTH,
    "http": LlmFailureCode.HTTP,
    "other": LlmFailureCode.OTHER,
}


def test_contract_covers_exactly_the_nine_known_codes():
    assert {code.value for code in LlmFailureCode} == set(EXPECTED)
    assert KNOWN_LLM_FAILURE_CODES == set(EXPECTED)
    assert len(KNOWN_LLM_FAILURE_CODES) == 9


def test_members_stay_str_compatible():
    assert LlmFailureCode.PARSE == "parse"
    assert LlmFailureCode.OTHER == "other"
    assert isinstance(LlmFailureCode.HTTP, str)


def test_error_normalises_enum_member_to_bare_str():
    exc = LLMResponseError("boom", LlmFailureCode.SCHEMA)
    assert exc.code == "schema"
    assert type(exc.code) is str
    assert exc.code in KNOWN_LLM_FAILURE_CODES


def test_error_still_accepts_plain_string_codes():
    assert LLMResponseError("boom", "timeout").code == "timeout"


def test_error_falls_back_to_other_for_unknown_codes():
    assert LLMResponseError("boom", "not-a-code").code == "other"
    assert LLMResponseError("boom", "").code == "other"
    assert LLMResponseError("boom").code == "other"


def test_consumer_sets_hold_plain_string_values():
    from resualign.engine import _DEGRADED_EDITOR_CODES, _GAP_DEGRADED_CODES
    from resualign.llm_nodes import LLMNodeStore

    assert "schema" in _DEGRADED_EDITOR_CODES
    assert "timeout" in _DEGRADED_EDITOR_CODES
    assert _GAP_DEGRADED_CODES == {"schema", "parse", "empty"}
    assert LLMNodeStore.BREAKER_COUNTED_CODES == {
        "timeout",
        "http",
        "auth",
        "quota",
        "other",
    }


def test_breaker_does_not_count_output_quality_codes():
    """parse/schema/empty/rate_limit are not node-availability failures."""
    from resualign.llm_nodes import LLMNodeStore

    for code in (
        LlmFailureCode.PARSE,
        LlmFailureCode.SCHEMA,
        LlmFailureCode.EMPTY,
        LlmFailureCode.RATE_LIMIT,
    ):
        assert code.value not in LLMNodeStore.BREAKER_COUNTED_CODES


def test_job_failure_detail_maps_codes_to_user_copy():
    from resualign.api import _job_failure_detail

    assert "欠费" in _job_failure_detail(
        "align", LLMResponseError("boom", LlmFailureCode.QUOTA), 1.0
    )
    assert "限流" in _job_failure_detail(
        "align", LLMResponseError("boom", LlmFailureCode.RATE_LIMIT), 1.0
    )
    assert "API Key" in _job_failure_detail(
        "align", LLMResponseError("boom", LlmFailureCode.AUTH), 1.0
    )
