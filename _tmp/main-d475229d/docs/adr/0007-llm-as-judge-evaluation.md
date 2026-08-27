# ADR-0007: LLM-as-Judge for quality evaluation

**Status**: Proposed
**Date**: 2026-07-31

## Context

Without an evaluation mechanism, there is no way to objectively measure whether the tailored resume is better than the original. User feedback is slow and subjective. Manual review does not scale. The project needs a way to:
1. Detect hallucinations (provenance check)
2. Measure JD alignment improvement
3. Track quality over time as prompts and models change

## Decision

Use a separate LLM call (LLM-as-Judge) after tailoring to produce an EvalScore.

The judge LLM receives:
1. The original Master Resume
2. The JD Profile
3. The tailored resume
4. The list of diffs with provenance

It scores each dimension and flags any content that cannot be traced to the original.

## Consequences

- Adds one extra LLM call per run (cost + latency).
- Provides an objective quality signal for iteration.
- Hallucination detection acts as a safety net for the iron rule (ADR-0006).
- The --eval flag makes evaluation opt-in.
- In the future, EvalScore can feed into a regression test suite for prompt changes.
