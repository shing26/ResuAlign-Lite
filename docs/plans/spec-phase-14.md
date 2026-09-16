# ResuAlign Phase 14 - Deliverable Upgrade

## Problem Statement

Phase 13 delivers a working Single-Job Workspace, but the product still reads
as a demo: Settings is a stub, job and resume history are thin, the frontend
is one 1000+ line inline HTML file with state bugs, the backend runs jobs in
process-memory daemon threads, the crawler is an SSRF/DoS risk, and there is
no deployment or onboarding path. Four specialist agents (product, backend,
UX, frontend) evaluated the project and produced prioritized findings; this
phase turns those findings into a deliverable personal job-seeking workbench.

## Solution

Close the four product modules end to end (Resume Center, Job Library,
Single-Job Workspace, Settings), rebuild the frontend as a no-build static
app with hash routing and robust state handling, harden the backend for real
use (persistent worker, crawler protection, limits, stable errors, versioned
migrations), and ship an onboarding/deployment story (scripts, Docker,
README, CI). Personal mode stays the default; SaaS auth stays dormant.

## User Stories

1. As a job seeker, I can open a job from the library directly into its
   workspace and see the raw JD while tailoring, so I never lose context.
2. As a job seeker, I can refresh or share a workspace URL and return to the
   same job with its result intact.
3. As a job seeker, I can export a tailored draft or report, and I can
   revisit past runs instead of losing them on restart.
4. As a job seeker, I can edit salary benchmarks, appraisal weights, and
   classification vocabulary in Settings.
5. As an operator, I can restart the server without killing in-flight jobs,
   and a malicious JD URL cannot reach internal networks or download
   unbounded content.

## Implementation Decisions

- Frontend stays no-build: `index.html` is split into `static/styles.css`
  and `static/app.js` (ES module), served through a FastAPI static mount with
  cache headers. No bundler until the app exceeds ~3k lines or needs
  TypeScript/component tests.
- Hash routing (`#/resume`, `#/jobs`, `#/workspace/:jobId`, `#/settings`)
  replaces class-only page switching; refresh/back/share preserve state.
- Job execution moves from per-request daemon threads to a bounded,
  persistent single-writer worker. Payloads persist in SQLite; queued/running
  jobs survive restarts; active jobs are never evicted by capacity limits.
  The polling contract (`queued/running/succeeded/failed` + stage/elapsed/
  result/error) stays unchanged.
- The crawler validates scheme and resolves DNS before fetching, rejects
  private/loopback/link-local targets, limits redirects, and streams with a
  byte cap instead of downloading first.
- Settings becomes a real API surface: salary reference table, appraisal
  weights, and classification vocabulary are editable and persisted.
- Appraisal match uses a JD-specific source when available
  (`eval_score.jd_match_score` or a gap-report-derived score) instead of the
  general diagnosis score.
- SQLite migrations become versioned with foreign keys enabled; the duplicate
  `GET /api/jobs/{job_id}` route is removed; list endpoints gain pagination.
- The frontend is documented as personal-mode-only for now; bearer-token
  login flow is deferred to the SaaS phase.

## Testing Decisions

- Backend changes are covered by TestClient integration tests and unit tests
  (worker restart recovery, no active-job eviction, crawler SSRF/byte cap,
  import caps, rate limits, error mapping, settings API, dedupe recompute,
  pagination).
- Frontend changes are verified with Playwright at 1440x900 and 390x844:
  hash routing, job-to-workspace journey, state preservation after status
  update, raw JD drawer, cancel/retry, export, no overflow, no page errors.
- Gates: all pytest green, coverage >= 85%, offline benchmark 9/9, Playwright
  suite green, README commands verified on a clean environment.

## Out of Scope (P2)

- Theme toggle and mobile-only navigation polish.
- Multi-user SaaS UI, login flow, and monetization.
- Streaming tokens and full Markdown editor.
- Agent-based list-page crawling (ADR-0010 seam stays).
