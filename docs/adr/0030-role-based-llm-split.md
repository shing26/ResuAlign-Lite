# ADR-0030: Role-based LLM Split

**Status**: Accepted
**Date**: 2026-08-18

## Context

The original single-prompt LLM approach suffered from three problems when
switching to smaller or local models:

1. **Context overload**: one prompt asking for JD parsing + gap calculation +
   resume rewriting + JSON formatting was too complex for <10B models.
2. **Serial latency**: 3000-5000 input tokens meant high TTFT for every call.
3. **Model brittleness**: different providers handled complex system prompts
   differently, causing JSON truncation and format drift.

## Decision

Split the single heavy LLM call into five independent **LLM roles**:

- `diagnose` — resume diagnosis (no-JD skill/issue extraction)
- `profiler` — JD profile extraction (structured fields from a job description)
- `gap_analyzer` — resume-to-JD gap comparison
- `editor` — incremental resume rewriting (only gap-hit sections)
- `evaluator` — LLM-as-Judge quality evaluation

Each role has:
- A focused, small prompt (<500 tokens)
- Its own output schema
- A configurable timeout (15-40s depending on role)
- Optional node binding (which provider/model to use)

### Role binding

Roles map to LLM nodes via `llm_role_assignments` table. Unbound roles fall
back to the active default node. On failure, the system attempts one automatic
fallback to the default node before reporting an error.

### Parallel execution

`diagnose` and `profiler` are independent and run concurrently when both
resolve to non-local (cloud API) nodes. Local Ollama nodes force serial
execution to avoid VRAM contention.

### Incremental editor

The editor only receives resume sections that match gap terms (missing
keywords, misaligned emphasis), capped at 3 sections or 2000 input chars.
Unchanged sections pass through verbatim, eliminating token waste.

### Presets

Settings page offers three presets:
- **Unified**: all roles use the default node
- **Hybrid** (recommended): extractive roles via Ollama, generative roles
  via cloud API
- **Local**: all roles via Ollama

## Consequences

- The `profile_and_gaps()` merged call is replaced by sequential `profile_jd`
  + `analyze_gaps` calls (ADR-0018 superseded).
- ADR-0029 agent orchestrator remains distinct: orchestrator agents handle
  fetch/blocker decisions; LLM roles handle text generation.
- Contract tests, benchmark, and 945+ pytest regressions pass.
- Settings API exposes `role-bindings` endpoints and presets.
- Frontend settings page is updated with role dropdowns and preset buttons.
