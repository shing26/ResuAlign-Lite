"""Stable failure-code contracts that cross layer boundaries.

``LLMResponseError.code`` is produced in ``llm``, branched on in ``engine``
(gap/editor degradation), mapped to user-facing copy in
``api.services.jobs`` and counted by the node breaker in ``llm_nodes``.
Before this module every site spelled the codes out as bare string literals,
so a typo or a rename would silently land in the ``other`` bucket instead of
failing loudly.

Scope is deliberately narrow: LLM call-failure codes only. The HTTP error
body contract (``{code, message, request_id}``, ticket #100) is a different
namespace and stays where it is.

Note for Python 3.10: this is ``(str, Enum)`` rather than ``enum.StrEnum``,
which is 3.11+. Enum mixins override ``__hash__``, so ``LlmFailureCode.X in
{"x"}`` is False — compare with ``==`` or build value-sets via ``.value``.
"""

from enum import Enum


class LlmFailureCode(str, Enum):
    """Stable ``LLMResponseError.code`` values (R4 P0-1)."""

    TIMEOUT = "timeout"
    EMPTY = "empty"
    PARSE = "parse"
    SCHEMA = "schema"
    QUOTA = "quota"
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    HTTP = "http"
    OTHER = "other"


# Plain-value view for membership checks, JSON payloads and anything that
# must stay a bare ``str``.
KNOWN_LLM_FAILURE_CODES: frozenset[str] = frozenset(
    code.value for code in LlmFailureCode
)
