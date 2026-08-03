# ADR-0015: Single-Job Workspace as the core page

**Status**: Accepted
**Date**: 2026-08-02

## Context

After Phase 12, the workbench has a Job Library but no per-job working page.
The user's design review identified three concrete problems: the Resume
Center mixes multiple mainlines (resume CRUD, applications, quick analysis)
without a clear focus; the interaction reads like a debug tool (plain
textarea, no diff view, no progress affordance); and the navigation lacks a
clear high-frequency workspace. A proposed three-column immersive layout was
reviewed and adjusted to two panels plus a collapsible diff drawer.

## Decision

- The Single-Job Workspace becomes the core page: select a job from the
  library, pick a Master Resume, choose granularity and prompt focus, run the
  pipeline with progress, review diffs, accept/replace per diff, update
  status, and read the appraisal.
- Rewrite granularity is a prompt-level backend control: `fine` (微调),
  `medium` (重构, default), `coarse` (重塑). The control is wired through
  `engine.run()` and the API before any UI control is shown.
- Worth appraisal is deterministic and transparent: match 40%, salary 30%,
  hard conditions 20%, quality 10%, verdict 投递 / 考虑 / 放弃, with a reason
  list. Salary benchmark uses the library median for the same function until
  the editable reference table exists.
- The UI layout is two panels (job + controls, results/diff) with a
  collapsible diff drawer; mobile stacks vertically. No fixed three-column
  grid for Chinese text.
- Resume Center is reduced to master resume library management; quick
  analysis and application creation leave the Resume Center.

## Considered Options

- Three-column immersive layout: proposed by the design review, but too
  narrow for Chinese resume diff text at the current container width.
- Appraisal inside the LLM result: less transparent and harder to test than
  a deterministic local module.
- Applying all diffs automatically: faster but removes user control; the
  workspace instead offers per-diff accept/replace.
- Full React/Monaco migration now: heavier than the product needs while the
  pipeline contract is still evolving; the workspace stays on the current
  no-build frontend.

## Consequences

- Phase 13 replaces Phase 12's application-focused quick-analysis flow in the
  UI while keeping the underlying `/api/analyze` and application APIs intact
  for backward compatibility.
- The tailored diff list becomes a first-class UI object: each `DiffItem`
  maps to a card with accept/replace/regenerate actions.
- Settings (weights, reference table) and Pipeline Kanban are explicitly
  deferred to Phase 14 so the workspace can be completed end to end first.
