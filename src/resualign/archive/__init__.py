"""Archive layers: raw payload capture kept outside the pipeline core.

The archive layer records what the product actually sent to and received
from an LLM provider, so a disputed run can be replayed later. It never
mutates pipeline state and is off by default (see ``llm_trace``).
"""

from .llm_trace import record_llm_trace, trace_enabled

__all__ = ["record_llm_trace", "trace_enabled"]
