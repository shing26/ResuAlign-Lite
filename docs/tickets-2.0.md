# ResuAlign 2.0 Implementation Tickets

Status: active (2026-08-04). Source of truth for sequencing is
`docs/plan-2.0-optimization.md`; this file is the executable breakdown.

## Definition of done for every ticket

- `python -m pytest tests/ -q` keeps the full suite green after integration.
- New behavior is covered by tests; no real LLM calls or `.env` credentials in
  tests.
- No personal data, API keys, or `data/` content is committed.
- Each ticket lists the files it owns. Workers must not edit files owned by
  another open ticket. New tests are preferred over editing existing test
  files unless the fixture contract itself changes.

## T1 - Contract freeze (baseline guard)

Owner: orchestrator. Dependency: none. Write scope: `contracts/`,
`tests/test_contract.py`, `docs/`.

- Commit an OpenAPI golden snapshot of the current `resualign.api:app` and a
  contract test that fails when critical routes disappear or response shapes
  break.
- Critical routes: `/health`, `/api/analyze`, `/api/jobs`,
  `/api/jobs/{job_id}`, `/api/jobs/{job_id}/workbench`,
  `/api/jobs/{job_id}/appraisal`, `/api/master-resumes`,
  `/api/applications`, `/api/settings`.
- The golden snapshot is the authoritative contract and is regenerated
  deliberately when a ticket adds routes or request/response models; response
  shape assertions in `tests/test_contract.py` are additive beyond the golden
  so unrelated field additions do not require editing the test body.

## T2 - Backend package split + SQLite WAL + durable jobs

Owner: backend architect / orchestrator. Dependency: T1. Write scope:
`src/resualign/api/` package, `src/resualign/store_base.py`,
`src/resualign/jobs.py`, `tests/` additions.

- Split `api.py` into `api/__init__.py` (re-export `app`), `api/routers/`,
  `api/services/`, `api/schemas.py`, `api/deps.py` without route or response
  drift; keep `resualign.api:app` importable.
- Unify SQLite pragmas: WAL, `busy_timeout=5000`, `foreign_keys=ON`,
  `synchronous=NORMAL`, thread-local connections.
- Job status transitions must be durable-claim style: only a queued job can be
  marked running; restart recovery requeues interrupted jobs.

## T3 - AI schema registry + provenance hard gate + content cache

Owner: AI engineer. Dependency: T1. Write scope: `src/resualign/llm.py`,
`src/resualign/models.py`, `src/resualign/tailor.py`,
`src/resualign/evaluator.py`, `src/resualign/jd_profiler.py`,
`src/resualign/classifier.py`, new `src/resualign/cache.py`,
`src/resualign/schema_registry.py`, `tests/conftest.py` additions,
new tests.

- Add `chat_structured` (Pydantic JSON Schema via `model_json_schema`; use
  provider Structured Outputs when supported, otherwise JSON mode + schema
  validation retry; never `raw_decode` fallback).
- `DiffItem` gains `provenance_quote` and `source_span`; tailor/evaluator
  outputs are hard-validated: diff provenance must trace back to the source
  resume, and `EvalScore` must return `hallucination` + `gap_coverage`.
- Add a small SQLite-backed content hash cache keyed by
  tenant/model/prompt-version/content-sha256 for diagnosis, JD profile+gaps,
  and classifier results. Tailor is not cached by default.

## T4 - Unified pipeline board + three-level workbench result

Owner: full-stack worker. Dependency: T1. Write scope: `src/resualign/api.py`,
`src/resualign/job_library.py`, `src/resualign/workspace.py`,
`src/resualign/static/app.js`, `src/resualign/static/styles.css`, new tests.

- Make the job library status the single source of truth for the pipeline
  board. Migrate old application statuses into the unified five-state model
  (draft/applied/interview/offer/withdrawn style) and add
  `applied_at`, `next_step`, `notes`, `offer_at`, `rejected_at`.
- Board API + UI support bulk status changes.
- Workbench result renders three levels: total score -> diff-by-bullet accept
  (with provenance) -> JD profile / gap / eval details.

## T5 - Frontend theme + three-column workbench + ESM split

Owner: frontend developer. Dependency: T4. Write scope:
`src/resualign/static/` (index.html, styles.css, new `static/app/` modules),
Playwright smoke updates in `.scratch/phase-16` / `.scratch/phase-18`.

- Token-based theme with `[data-theme]` and dark mode, 4/6/8px radius family,
  reduced-motion support.
- Three-column workbench on wide screens (`300px / 1fr / 320px`), drawer below
  `1100px`, tab collapse below `800px`; `data-*`, `aria-*`, `#app`,
  `#toast-region`, `#print-root` contracts stay intact.
- Split `app.js` into `static/app/{main,diff-editor,appraisal-panel,theme,events}.js`;
  `node --check` must pass on every module.

## T6 - Batch alignment + appraisal upgrade

Owner: backend/full-stack worker. Dependency: T4. Write scope:
`src/resualign/appraisal.py`, `src/resualign/engine.py`,
`src/resualign/api.py`, new `src/resualign/batch.py`, frontend batch views,
new tests.

- Batch align one master resume against 2-5 JD URLs/rows: queue, per-row
  progress, cancel, results matrix, default granularity `fine`.
- Appraisal upgrade: commute cost, living-cost adjustment, manual weights,
  four-dimension score + conclusion, lightweight SVG radar.

## T7 - Crawler hardening + observability

Owner: backend/data engineer. Dependency: T1. Write scope:
`src/resualign/crawler.py`, `src/resualign/config.py`,
`src/resualign/api.py` (crawl paths only), `src/resualign/observability.py`,
new tests.

- Per-host rate limiting, exponential backoff, user-agent pool, optional
  proxy config, opt-in Playwright headless fallback, URL sanitization, graceful
  degradation on 404/redirect/private-address failures.
- Request ids, structured logs, slow query logging, cache hit-rate counters.

## T8 - Phase-20 Playwright + benchmark expansion

Owner: QA/performance worker. Dependency: T4, T5. Write scope:
`.scratch/phase-20/`, `benchmarks/`, `.github/workflows/ci.yml`.

- Playwright key-path smoke: import resume -> crawl JD -> tailor -> export;
  desktop + mobile viewports; fake LLM server only.
- Benchmark grows from 9 to 15 cases: adversarial anti-hallucination, cache
  hit, batch 5 JD, schema retry.
- CI runs three stages: unit+contract, benchmark gate (cold/cached call and
  wallclock thresholds), Playwright smoke.

## T9 - P2 spikes (post-MVP)

Owner: rapid prototyper / orchestrator. Dependency: T8. Write scope:
`.scratch/spikes/`, docs ADRs.

- Evaluate Web Components (`ra-*`, Light DOM), Tauri shell, full-result cache
  (0 LLM calls, p95 <= 500ms), data export/backup/analytics.
- Record findings as ADRs; no production code changes unless approved.
