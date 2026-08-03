# ADR-0008: Two-stage extraction for token optimization

**Status**: Proposed
**Date**: 2026-07-31

## Context

JD texts from crawled pages can be 5000+ tokens. Full resumes are similar. Sending all of this directly to an LLM for every operation is expensive (token cost + latency) and unnecessary.

The user design explicitly calls for a two-stage approach: cheap pass first, LLM pass second.

## Decision

Introduce a two-stage extraction pipeline for all long-text operations:

Stage 1 - Lightweight (regex / NLP heuristics)
- JD: extract sections by heading markers, filter out boilerplate.
- Resume: detect section boundaries, filter headers and footers.
- Cost: ~0 tokens, pure string ops.

Stage 2 - LLM refinement
- Only the narrowed context from Stage 1 is sent to the LLM.
- The LLM prompt includes the structured schema and asks the model to fill in missing fields.

## Consequences

- Typical token savings: 60-80% on JD texts, 40-60% on resumes.
- Adds a new module (extractor.py) and a dependency on a regex/NLP library.
- Stage 2 fallback ensures no loss of accuracy for complex cases.
- The heuristic rules need maintenance as new JD formats appear.
