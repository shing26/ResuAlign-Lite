# Spec: Batch alignment and appraisal upgrade (T6)

## Batch alignment

Goal: align one master resume against 2-5 JD URLs or library jobs in one
action, with per-row progress and a comparison matrix.

### Backend

- NEW `src/resualign/batch.py`:
  - `BatchAlignRequest`: `master_resume_id`, `job_ids: list[str]` (2-5),
    `granularity` (default `fine`), `prompt_focus`, optional `custom_prompt`.
  - `BatchAlignStore` (in-memory with TTL, thread-safe): batch_id, rows with
    per-job status (queued/running/succeeded/failed), analysis job ids, result
    summary (score, eval, key gaps, next step), created_at.
  - `queue_batch_align(...)` reuses `api._queue_job`/engine.run per row with
    the same tenant scoping as single-job workbench.
- API (additive, hidden from OpenAPI golden is NOT allowed for new routes; the
  golden is updated deliberately at the end of the ticket):
  - `POST /api/batch-align` -> `{batch_id, total, queued}`
  - `GET /api/batch-align/{batch_id}` -> rows + overall summary
  - `POST /api/batch-align/{batch_id}/cancel` -> cancel queued rows only
- Tests: 2-JD and 5-JD queueing, tenant isolation, cancel, result matrix
  shape, default `fine` granularity.

### Frontend

- Batch panel in the jobs/workbench view: select 2-5 library jobs, choose the
  master resume, run; poll batch status; render a comparison matrix
  (job / score / top missing keywords / verdict / next step) with per-row
  "open workbench" links. Use existing `#jobs` route and `data-action`
  attributes; no new build step.

## Appraisal upgrade

`compute_appraisal` gains additive inputs without changing current defaults:

- `commute_minutes: Optional[int]` and `commute_cost_per_minute: Optional[float]`
  (defaults 0) producing a `commute` component 0-100.
- `living_cost_adjustment: Optional[float]` (0.8-1.2, default 1.0) applied to
  the salary component.
- `weights` may include `commute`; the default weight set stays 100 total and
  backward compatible (missing `commute` weight => commute excluded or folded
  into quality at 0 weight).
- Return extra keys `components.commute`, `components.living_cost_adjustment`,
  `conclusion` (one short sentence derived from top/low components), and keep
  `verdict`, `reasons`, `weights`, `benchmark_source` unchanged.
- API `GET /api/jobs/{job_id}/appraisal` accepts query params for commute and
  living-cost so the radar/panel can render without a settings change.
- Frontend appraisal panel renders the four dimensions as a lightweight SVG
  radar plus conclusion line; no chart library.

## Verification

- New tests: batch queue/status/cancel/isolation, appraisal commute/living
  cost math, weight validation with commute, conclusion presence.
- `python -m pytest tests/ -q` green; Playwright smoke still passes (phase-16/
  18) because hash routes and selectors are unchanged.
