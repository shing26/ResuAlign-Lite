# ResuAlign 2.0 终极形态 Implementation Tickets

Status: active (2026-08-04). Source of truth: `docs/plan-2.0-ultimate-copilot-studio.md`
and `docs/adr/0021-copilot-splitstudio.md`.

## Definition of done for every ticket

- `python -m pytest tests/ -q` stays green after integration.
- New behavior is covered by tests; no real LLM calls or `.env` credentials in
  tests.
- No personal data, API keys, or `data/` content is committed.
- Each ticket lists files it owns; workers must not edit files owned by another
  open ticket.
- `resualign.api:app` stays importable; `engine.run()` and
  `tailor_resume()` signatures stay unchanged.

## T0 - Contract incremental + response schema baseline

Owner: orchestrator / QA. Dependency: none.
Write scope: `contracts/`, `tests/test_contract.py`, `src/resualign/api/schemas.py`.

- `contracts/openapi-v1.json` becomes immutable golden.
- Add `contracts/incremental/` manifest for new routes/fields; contract test
  switches from exact equality to additive superset checks (no removed paths,
  no removed operationIds, no removed required fields).
- Public endpoints that currently emit empty schemas get Pydantic
  `response_model` coverage for the ones touched by this plan.
- Contract/error/security entries for new endpoints are added deliberately.

## T1 - Export/print contract + Playwright selector alignment

Owner: frontend worker. Dependency: none.
Write scope: `src/resualign/static/index.html`, `src/resualign/static/app/*.js`,
`.scratch/phase-20/playwright_smoke.py`.

- Add `#print-root` and implement `printTarget()` so PDF/print actions work.
- Replace stale `.card.job-card` selectors with current `.board-card` /
  `[data-pipeline-board]` contract.
- Keep `#app`, `#toast-region`, `data-*`, `aria-*`, hash routes intact.

## T2 - Benchmark SLO + CI artifact gate

Owner: QA worker. Dependency: none.
Write scope: `benchmarks/latency_benchmark.py`, `benchmarks/run_benchmark.py`,
`tests/test_benchmark.py`, `.github/workflows/ci.yml`.

- Tighten latency SLO: cold <=3.3s, cached <=2.2s, schema retry <=4.4s.
- Offline benchmark: 15/15 cases, avg goal coverage >=0.8.
- CI stores pytest XML, coverage, benchmark golden; adds explicit
  `--cov-fail-under=85`; uploads Playwright artifacts.

## T3 - Session orchestration API + SSE

Owner: backend worker. Dependency: T0.
Write scope: `src/resualign/api/routers/workspace.py`,
`src/resualign/api/services/workbench.py`, `src/resualign/api/schemas.py`,
`src/resualign/api/__init__.py`, new tests.

- `POST /api/workbench/session/init` accepts raw JD/URL, returns 202 +
  `WorkstationState`; never blocks on LLM cold path.
- `GET /api/workspace/session/{job_id}` returns same shape, read-only, no LLM.
- `GET /api/workbench/session/{session_id}/events` streams SSE events
  (`job.stage`, `job.gap_ready`, `tailor.diff`, `job.result`, `job.error`,
  `heartbeat`, `crawl.status`).
- Event bus is in-memory, idempotent replays supported; polling fallback via
  `?if-none-match`.

## T4 - Alignment persistence + kanban + crawl tasks

Owner: backend worker. Dependency: T0.
Write scope: `src/resualign/job_library.py`, `src/resualign/jobs.py`,
`src/resualign/api/routers/kanban.py`, `src/resualign/api/services/jobs.py`,
`src/resualign/crawler.py`, new tests.

- Persist terminal alignment products on `library_jobs`:
  `jd_profile_json / gap_report_json / match_score / alignment_status /
  diffs_json / invalid_diffs_json / draft / eval_score_json / model /
  prompt_version / generated_at`.
- `POST /api/kanban/bulk-status`: single SQLite transaction, per-row
  `updated/not_found/conflict`, optimistic lock + idempotency key, limit 200.
- `crawl_tasks` table with `queued -> fetching -> parsing -> classifying ->
  succeeded` state machine; restart recovery.

## T5 - JD-only preanalyze + bullet rewrite + provenance_state

Owner: AI worker. Dependency: T3, T4.
Write scope: `src/resualign/jd_analysis.py`, `src/resualign/tailor.py`,
`src/resualign/schema_registry.py`, `src/resualign/cache.py`,
`src/resualign/api/routers/jobs.py`, new tests.

- `proactive_jd_profile(jd_text)` reuses `profile_jd()` + cache, key includes
  tenant/model/prompt-version/jd-hash.
- `POST /api/jobs/{job_id}/preanalyze`: classifier + profile/gap only,
  idempotent; gap_ready intermediate result.
- `rewrite_bullet()` + `POST /api/jobs/{job_id}/workbench/rewrite`: input
  `diff_id + instruction`; server loads original from persisted alignment.
- `DiffItem` gains stable `diff_id` and `provenance_state`
  (`verified/ambiguous/missing/pending_review`); whitespace-normalized span
  lookup; `add` without source goes to `invalid_diffs`.
- Public JD fields become `required_skills / nice_to_have / business_scene`
  with backward-compatible aliases.

## T6 - Split-Canvas frontend + universal input + Copilot drawer

Owner: frontend worker. Dependency: T1, T3.
Write scope: `src/resualign/static/index.html`, `src/resualign/static/styles.css`,
`src/resualign/static/app/main.js`, new `static/app/split-canvas.js`,
`static/app/command-panel.js`.

- Top command bar with universal input (`Cmd/Ctrl+K`), paste -> preview card ->
  confirm -> auto preanalyze.
- `#/jobs` Copilot surface: five-column kanban, draggable cards with
  match badges and select/keyboard fallback.
- `#/workspace/:jobId` Optimizer: dual-column Split-Canvas
  (JD canvas + resume bullet canvas), decision drawer.
- Remove add-job and application-create forms from user flow.

## T7 - Frontend event state machine + bullet actions + export dock

Owner: frontend worker. Dependency: T5, T6.
Write scope: `src/resualign/static/app/events.js`,
`src/resualign/static/app/diff-editor.js`, `src/resualign/static/app/main.js`.

- Single event state machine consumes SSE with polling fallback; skeleton +
  stage stepper; no parallel polling timers.
- Bullet cards render original/proposed/provenance per `diff_id`, with
  accept/reject/polish actions; invalid diffs visible.
- Persistent export dock: copy Markdown, export PDF via `#print-root`,
  export JSON.

## T8 - Visual Phase 20 tokens + Bento/glass + command palette

Owner: UI worker. Dependency: T6.
Write scope: `src/resualign/static/styles.css`, `static/app/theme.js`,
`static/app/command-panel.js`.

- Add `--glass-surface/--glass-border/--glass-blur/--match/--warning/--danger/
  --provenance` tokens; keep 4/6/8px radius family.
- Bento Grid information grouping; glass only on shell/topbar/command
  panel/drawer; `@supports` fallback.
- Command palette with `role="dialog"`, focus trap, Esc, arrow navigation.

## T9 - QA gates: E2E + negative scenarios + CI

Owner: QA worker. Dependency: T2, T6, T7.
Write scope: `.scratch/phase-20/`, `tests/`, `.github/workflows/ci.yml`.

- Fake LLM server gains `stage_delay / schema_retry / invalid_provenance`
  switches.
- Playwright main path: universal input -> kanban/Split-Canvas -> bullet
  accept/reject -> copy Markdown -> PDF export, desktop + mobile, artifacts
  uploaded.
- New tests: SSE order/result consistency, real multi-worker WAL claim,
  restart recovery, bulk 200 transaction, invalid provenance E2E.

## T10 - Final integration + code review

Owner: orchestrator. Dependency: T0-T9.

- Full pytest + coverage >=85; node check; latency + offline benchmark;
  HTTP smoke on running server.
- Dual-axis code review (standards + spec compliance); fix findings; report.

## T10 closeout (2026-08-04)

- 465 pytest cases pass with 89.30% coverage (gate 85%); Playwright Phase 20
  smoke passes on desktop and mobile.
- Offline benchmark 15/15, average goal coverage 96.4%; latency cold 3.03s,
  cached 2.00s, schema retry 4.00s (SLO 3.3/2.2/4.4).
- Review fixes: session preanalyze now persists `jd_profile / gap_report /
  match_score` to `library_jobs`; real alignment runs emit `tailor.diff` SSE
  events before `job.result`; `contracts/incremental/manifest.json` added and
  guarded by `tests/test_contract.py`; startup requeues interrupted crawl
  tasks; `tmp-*.db` ignored.
