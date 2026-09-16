# ResuAlign SaaS Workbench Roadmap

Status: Planning
Date: 2026-08-01

## 1. Product Vision

ResuAlign evolves from a local single-user resume-tailoring CLI into a
SaaS-style job-seeking workbench. A job seeker keeps one Master Resume and
manages many applications; each application stores its JD, runs the pipeline
(profile, gap analysis, tailor, evaluate), and keeps the tailored resume,
report, and history reusable.

The workbench captures JDs from URLs today and from agent-based fetchers later.
Quality is measured per application by EvalScore (LLM-as-Judge) and across
releases by the synthetic benchmark. The iron rule stays: every tailored word
traces to the Master Resume.

## 2. Capability Pillars Mapped to Existing Work

1. Async jobs and progress (Phase 9, ADR-0009): stage callback plus polling
   API that survives the move to persistent jobs.
2. Crawler plus agent JD ingestion (ADR-0010): `crawl_jd()` and site handlers,
   with `JDSourceFetcher` as the documented future seam.
3. Benchmark quality gate (ADR-0011): nine synthetic, PII-free cases with
   `expected_direction`, runnable offline in CI.
4. Frontend-agnostic engine (ADR-0005): `engine.run()` stays I/O-free; SaaS
   persistence lives in API/worker layers.
5. Provenance iron rule (ADR-0006): diffs and tailored sentences link to
   source sentences; evaluator flags untraceable claims.
6. Two-stage extraction (ADR-0008): regex/NLP pass narrows text before the
   LLM, bounding per-user token cost.

## 3. Phased Roadmap (Phase 10+)

### Phase 10 - Persistent multi-tenant data and auth
Goal: database-backed, authenticated multi-user foundation.
Outcome: users sign in; resumes, JDs, applications, and jobs survive restarts.
Tickets:
- Persistent job store behind the existing polling API (in progress,
  ADR-0012).
- Storage stack and tenant/user model.
- Signup/signin with session or token auth.
- Persistent job registry behind the existing polling API.
- Tenant-scoped routes, migrations, isolation tests, CI gates.

### Phase 11 - Application workspace
Goal: one Master Resume drives multiple applications with per-JD tailoring.
Outcome: users manage an application board and rerun any application.
Tickets:
- Application model (master resume version, JD, status, timestamps).
- Application CRUD API plus list/detail UI.
- Per-application `engine.run()` with progress updates.
- Duplicate/reset workflows and cross-tenant isolation tests.

### Phase 12 - JD library and agent ingestion
Goal: reusable JD library with paste, URL, and agent ingestion.
Outcome: users build and reapply a JD library with ingestion status per source.
Tickets:
- `JDSourceFetcher` protocol extracted from `crawl_jd()`; adapt CLI/API.
- JD entity, dedupe, and refresh/update semantics.
- Agent fetcher adapter plus ingestion queue and categorized errors.
- Two-stage extraction reuse and ingestion tests.

### Phase 13 - Web result persistence and history
Goal: durable reports and analysis history instead of in-memory TTL.
Outcome: users reopen, export, and compare past analyses.
Tickets:
- Report store keyed by tenant and application.
- History API/UI (status, elapsed, stage, EvalScore).
- PDF/JSON/Markdown export plus retention policy.
- Migrate Phase 9 registry tests to the persisted store.

### Phase 14 - SaaS deployment hardening
Goal: config, env, observability, and rate limits for a multi-user server.
Outcome: the service runs safely behind a proxy with no local-file assumptions.
Tickets:
- Server config schema separate from CLI `.env` layering.
- Secrets management; no credentials in repo or logs.
- Structured logs, request metrics, job telemetry.
- Per-tenant rate limits, quotas, backpressure, deployment docs.

### Phase 15 - Monetization and onboarding (placeholder only)
Goal: define, but do not commit to, the first hosted offering.
Outcome: to be decided.
Tickets (open, non-binding):
- Free tier/quota design and onboarding flow.
- Billing/payment provider evaluation.
- Pricing, legal, and support scope.

## 3b. Re-scoped Workbench Roadmap (2026-08-02, ADR-0014)

Product re-converged by grilling: a personal job-seeking workbench with four
modules, keeping SaaS as the long-term end state. Personal mode stays default
for now.

### Phase 12 - Job Library and classification (done 2026-08-02)
Goal: collect and classify jobs as the shared data base.
Tickets: `.scratch/phase-12/issues/01-07`.
- Job library data model and store.
- Ingestion: URL crawl, pasted JD, JSON/CSV import.
- Multi-dimensional classification (function, seniority, tech tags).
- Job library API and web UI (four-page navigation).
- Single-Job Workspace: JD analysis, worth appraisal, tailored resume draft,
  application status.
- Settings: salary reference table, appraisal weights, vocabulary.

### Phase 13 - Single-Job Workspace (current, ADR-0015)
Goal: build the core working page where one job is compared with the Master
Resume, rewritten at a chosen granularity, and appraised.
Tickets: `.scratch/phase-13/issues/01-04`.
- Rewrite granularity control (fine/medium/coarse) through engine + API.
- Deterministic worth appraisal (match 40%, salary 30%, hard 20%, quality
  10%) with verdict and reasons.
- Workbench API: run, appraisal, accept diffs, status update.
- Workbench UI: two-panel job workspace with progress and per-diff actions.

### Phase 14 - Settings, Pipeline, and acquisition (planned)
Goal: operational polish around the workspace.
Tickets (open, non-binding):
- Settings: salary reference table, editable appraisal weights, vocabulary.
- Pipeline Kanban from library statuses; report/export history.
- Markdown editor, version tree diff view, streaming affordances.
- Search/list-page ingestion and agent-based JD acquisition (ADR-0010 seam).

### Phase 14+ - SaaS hardening (eventual)
Goal: multi-user deployment when the workbench is ready.
Tickets (deferred, unchanged from the earlier roadmap):
- Storage stack and tenant/user model completion.
- Session/token auth enforced by default.
- Reports history, export, quotas, observability.
- Deployment and onboarding.

## 4. Dependencies and Risks

- Phase 9 in-memory `JobRegistry` must become persistent before multi-user;
  ADR-0009 permits replacement without changing the API contract.
- Daemon-thread execution must become a durable worker queue with per-tenant
  concurrency; transition tests move from injected clock to store.
- `crawl_jd()` must become the `JDSourceFetcher` protocol (ADR-0010); CLI and
  API currently import `crawl_jd()` directly.
- Benchmark fixtures (ADR-0011) need tenant-safe selection and namespaced
  result storage so benchmark output never leaks user data.
- ADR-0002 config layering is CLI-oriented; SaaS hardening must split server
  config from user-local `.env` behavior.
- Engine stays I/O-free (ADR-0005): persistence belongs in API/worker layers.
- LLM cost/latency scale with users; two-stage extraction (ADR-0008)
  mitigates, but quotas and caching are still required.

## 5. Resolved Decisions (2026-08-01, ADR-0013)

1. Storage: SQLite single-node for the MVP, with a documented Postgres
   migration path behind the same store surface. `RESUALIGN_JOB_DB` remains
   the storage override for jobs; workspace data shares the same SQLite file.
2. Auth: email/password with opaque bearer tokens, self-hosted-first. OAuth
   is a documented future option, not an MVP dependency.
3. Tenancy: user-only workspaces; each user is a tenant. Organizations are
   deferred; tenant_id columns are designed to later accept an org id.
4. Document storage: SQLite for MVP documents (JD text, resume snapshots,
   reports are kept in job results). Object storage and encryption at rest
   are deferred; credentials and payload secrets are never written to disk.
5. LLM economics: per-user daily quota with configurable model routing;
   failed jobs stay visible and are retried by the user. Caching is deferred.
6. Deployment: single VM with embedded SQLite for the MVP; containers and a
   managed database are deferred until Phase 14.
7. JD acquisition: LinkedIn and BOSS直聘 handlers plus generic fallback
   (ADR-0010); crawl rate limits and a user-authorized agent seam are
   documented for Phase 12, not implemented yet.
8. Phase 15 scope: placeholder only; no commitment to free tier, pricing, or
   onboarding depth.

These decisions unblock Phase 10 ticket 02 (auth/tenancy) and Phase 11
(application workspace and master resume management).
