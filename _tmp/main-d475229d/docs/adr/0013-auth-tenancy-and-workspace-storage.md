# ADR-0013: Auth, tenancy, and workspace storage

**Status**: Accepted
**Date**: 2026-08-01

## Context

ResuAlign is moving from a local single-user CLI to a SaaS-style workbench.
Phase 10 needs a minimal identity boundary so that analysis jobs stop being
globally readable, and Phase 11 needs durable, per-user applications and a
versioned Master Resume. The roadmap previously listed eight open decisions;
the user asked for the recommended option on each remaining question.

## Decision

- Storage: SQLite single-node for the MVP. Workspace tables (users, sessions,
  master resumes, applications) live in the same SQLite database as jobs, so
  `RESUALIGN_JOB_DB` becomes the single local storage override. A Postgres
  store can replace this later behind the same method surface.
- Auth: email/password signup and login with opaque bearer tokens. Passwords
  are hashed with a per-user salt (stdlib `hashlib.scrypt`); tokens are stored
  as hashes, never as plaintext. OAuth is documented but not implemented.
- Tenancy: user-only workspaces. Each user id is also the tenant id. All job,
  application, and master-resume queries are scoped by tenant; a cross-tenant
  read returns the same 404 as an unknown id.
- Document storage: SQLite for MVP text (JD text, resume versions). Reports
  remain inside job results. Payloads, credentials, and API keys are never
  written to the database.
- LLM economics: a per-user daily quota counter with a configurable cap and
  configurable model routing. Failed jobs remain readable so the user can
  resubmit. Caching is deferred.
- Deployment: single VM with embedded SQLite for the MVP. Containers and a
  managed database are deferred to Phase 14.
- JD acquisition: keep the ADR-0010 handlers (LinkedIn, BOSS直聘, generic
  fallback). Crawl rate limits and the user-authorized agent seam are Phase 12
  work, not implemented now.

## Considered Options

- OAuth/SSO first: too much external dependency for a self-hosted MVP.
- Organizations up front: adds a second tenant axis before any application
  workspace exists; user-only keeps the data model small and org-compatible.
- Postgres from the start: strong for multi-tenant scale, but premature while
  the MVP is a single VM and SQLite already persists Phase 9 jobs.
- Object storage for documents: unnecessary while document counts are small;
  report export remains available through the API.

## Consequences

- Analysis jobs become tenant-owned: `POST /api/analyze` requires a bearer
  token, and polling only returns the caller's own jobs.
- The API gains signup/login/logout endpoints and a small auth dependency
  injected at the FastAPI boundary; `engine.run()` stays I/O-free.
- Phase 11 application and master-resume stores can be built directly on the
  same SQLite database with tenant scoping already in place.
- Moving to Postgres later means implementing the same store surface for the
  workspace tables, not changing the API contract.
