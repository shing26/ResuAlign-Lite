# ADR-0012: Persistent job store with SQLite

**Status**: Accepted
**Date**: 2026-08-01

## Context

Phase 9 (ADR-0009) deliberately used a process-local in-memory job registry:
restarting the server loses in-flight and completed analyses. The SaaS
workbench roadmap requires durable analysis history and survivable jobs before
multi-user work. The final storage stack (SQLite vs Postgres) is still an open
decision, so this phase needs a reversible step that preserves the existing
polling API contract.

## Decision

Back the existing job registry API with a SQLite-backed job store:

- The public registry methods (`create`, `get`, `mark_running`,
  `update_progress`, `succeed`, `fail`, `snapshot`, `clear`, `len`) keep their
  signatures so the API layer changes minimally.
- The job store persists only public job state: id, status, stage, message,
  timestamps, result JSON, and error text. Payloads and LLM configs stay in
  memory for the lifetime of a running job and are never written to disk.
- On startup, queued and running jobs from a previous process are marked
  failed with an "interrupted by server restart" error, so polling always
  reaches a terminal state and no credentials survive restarts.
- Storage location is configurable through `RESUALIGN_JOB_DB` (default:
  a local SQLite file under the project data directory). SQLite keeps the
  dependency footprint zero; Postgres can replace the store later without
  changing the API contract.

## Considered Options

- Keep the in-memory registry: cheapest, but history disappears on restart and
  the SaaS roadmap is blocked.
- Postgres from the start: stronger for multi-tenant, but premature while the
  storage/tenancy decisions are still open and adds a service dependency.
- Persist payloads and configs: would leak API keys into the database, so it
  was rejected.

## Consequences

- Completed analyses survive server restarts and become queryable history.
- A running analysis is at most one restart away from a terminal "failed"
  state; the user can resubmit.
- Migration to Postgres is a new `JobStore` implementation behind the same
  method surface.
