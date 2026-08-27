# ADR-0018: Fewer LLM Round Trips for Workbench Runs

**Status**: Accepted
**Date**: 2026-08-03

## Context

A workbench run (diagnose + align) made four serial LLM calls: diagnosis, JD
profile, gap analysis, and tailoring. Every call adds wall-clock latency, and
the API re-ran diagnosis on every workbench run even when the master resume
had not changed. Users reported the AI rewrite / alignment flow feeling slow.

## Decision

- Merge JD profile and gap analysis into one completion: `profile_and_gaps()`
  in `src/resualign/jd_analysis.py` returns `{"jd_profile": ..., "gap_report":
  ...}` from a single response.
- Add an optional `diagnosis` argument to `engine.run()`; when supplied, the
  diagnosis LLM call is skipped.
- Persist `diagnosis_source_hash = sha256(resume_text)` on successful diagnosis
  jobs and reuse the latest diagnosis for workbench runs when the resume hash
  and model match (`_cached_diagnosis()` in `src/resualign/api.py`).
- Bound long inputs with `truncate_text()`: JD input at 8000 chars, JD context
  for tailoring/evaluation at 6000 chars, cutting on a line boundary.
- Keep frontend compatibility: `app.js` adds the `jd_analysis` stage label and
  weight while old stage keys still resolve.

## Consequences

- First workbench run: 4 LLM calls -> 3 (25% fewer).
- Repeated run on the same resume: 2 LLM calls (50% fewer) via the diagnosis
  cache.
- `benchmarks/latency_benchmark.py` reproduces the improvement with simulated
  1s calls: 4.0s -> 3.0s cold, 2.0s cached.
- Tests cover new call counts, stage order, diagnosis reuse, cache
  invalidation, and truncation.
