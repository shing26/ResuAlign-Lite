# ResuAlign Phase 13 - Single-Job Workspace

## Problem Statement

Phase 12 gives the workbench a Job Library, but the library is a static list:
there is no per-job working page where a JD is compared with the Master
Resume, a tailored draft is generated, and the "is this job worth applying
to" question is answered. The current Resume Center also overloads one screen
with resume versioning, application creation, and quick analysis, so the
product reads like a debug tool instead of a workbench.

## Solution

Build the Single-Job Workspace as the core high-frequency page. A job is
selected from the Job Library, the user picks a Master Resume version, sets a
rewrite granularity and prompt focus, and runs the pipeline with visible
progress. The result page shows the JD profile, gap report, appraisal card,
and a per-diff comparison with accept/replace actions. The Resume Center is
then simplified to resume library management only; application tracking moves
into the job library status and a later Pipeline page.

## User Stories

1. As a job seeker, I want to open one job and see its JD profile, gap report,
   and a transparent 0-100 appraisal, so that I can decide whether it is
   worth applying to.
2. As a job seeker, I want to pick a Master Resume and a rewrite granularity
   (微调 / 重构 / 重塑), so that I control how aggressive the AI rewrite is.
3. As a job seeker, I want to see progress while the workbench runs, so that a
   multi-stage LLM run does not feel like a hanging operation.
4. As a job seeker, I want green/red diffs with per-diff accept or replace
   actions, so that I keep control of the final draft.
5. As a job seeker, I want to update the application status from the
   workspace, so that the library doubles as a lightweight pipeline.

## Implementation Decisions

- The workbench reuses the async analysis job registry and `engine.run()`
  with an additional `granularity` parameter (`fine`, `medium`, `coarse`).
  Default stays `medium`, so existing CLI/API callers keep their behavior.
- Granularity is a prompt-level control in `tailor.py`; FINE means preserve
  structure and wording, COARSE means full restructure. No new ML engine is
  introduced.
- The appraisal is a deterministic local module (`appraisal.py`): resume
  match 40%, salary competitiveness 30%, hard conditions 20%, job quality
  signals 10%, with a three-level verdict (投递 / 考虑 / 放弃) and a reason
  list. Weights default per ADR-0014; editable weights arrive with Settings.
- Salary benchmarking compares the job's extracted salary with the library
  median for the same function; the editable reference table is Phase 14.
- `POST /api/jobs/{job_id}/workbench` queues a pipeline run pinned to a
  Master Resume version; `GET /api/jobs/{job_id}/appraisal` computes the
  score synchronously; `POST /api/jobs/{job_id}/workbench/accept` applies
  accepted diffs deterministically and returns the draft text.
- Workbench results are returned through the existing job polling contract
  with a `workbench` marker in the payload, so the frontend can reuse the
  progress UI.
- The UI uses a two-panel layout plus a collapsible diff drawer, not a fixed
  three-column grid, so Chinese resume text remains readable on desktop and
  stacks vertically on mobile.
- Resume Center keeps master resume CRUD/versioning only; quick analysis
  moves into the workbench page. Application status is edited from the job
  library list and workbench, not from a separate application form.

## Testing Decisions

- Granularity prompt mapping and default behavior are unit-tested with the
  existing fake LLM client.
- Appraisal math, verdict thresholds, salary benchmarking, and reason
  generation are deterministic and unit-tested.
- Workbench API tests use TestClient with temp stores: run, poll, appraisal,
  accept diffs, tenant isolation, and status update.
- UI verification uses Playwright at desktop and mobile widths, asserting no
  overflow, no page errors, and the add -> run -> diff -> accept flow.

## Out of Scope (Phase 14+)

- Settings page (salary reference table, editable appraisal weights,
  classification vocabulary management).
- Pipeline Kanban page and report/export history.
- Markdown editor, version tree with diff view, and streaming tokens.
- Agent-based JD acquisition and list-page crawling.

## Further Notes

This repository is not under git; reviews compare against this spec and the
pre-change file state. `.env` credentials must never be printed or committed.
