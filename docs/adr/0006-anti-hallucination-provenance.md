# ADR-0006: Anti-hallucination provenance tracking

**Status**: Proposed
**Date**: 2026-07-31

## Context

The core value proposition is tailoring a resume to a JD. The greatest risk is LLM hallucination — inventing skills, projects, or metrics that do not exist in the candidate actual experience. Once false content enters a resume, it damages credibility irreparably.

The user explicitly defined this as an iron rule: AI cannot fabricate facts.

## Decision

Every diff and every tailored sentence must carry a provenance field that links back to the exact source sentence in the Master Resume.

Enforcement strategy:
- The tailor.py prompt explicitly receives the source sentence and is instructed to keep all factual claims unchanged.
- A post-processing step in evaluator.py checks each sentence against the Master Resume using fuzzy matching. Any claim not traceable is flagged.
- The evaluation phase (ADR-0007) includes hallucination detection as a mandatory check.

## Consequences

- Users can verify every change against the original resume.
- Hallucination rate approaches zero for factual claims (rephrase is still allowed).
- Adds overhead to the tailoring prompt (include source context).
- Provenance information makes the diff output more informative for human review.
- The evaluation phase becomes more expensive but catches the critical failure mode.
