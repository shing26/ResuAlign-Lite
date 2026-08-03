# ADR-0009: Asynchronous analysis jobs with stage progress

**Status**: Accepted
**Date**: 2026-08-01

## Context

Long pipeline runs take minutes, and the current synchronous `POST /api/analyze`
endpoint blocks until the whole Report is ready. The web UI can only show a
spinner, so users cannot tell which stage is running or how much longer to wait.
Streaming (SSE) would be more real-time but heavier to build and test;
synchronous execution cannot report progress at all.

## Decision

Expose progress and run long analyses as asynchronous jobs:

- `engine.run()` gains an optional stage callback (stage name + human-readable
  message) invoked before each pipeline stage. The engine stays
  frontend-agnostic and I/O-free; callers that do not pass a callback keep
  today's behavior.
- The API creates an in-memory job, starts a daemon thread, returns `202` with
  a `job_id` immediately, and exposes `GET /api/jobs/{job_id}` for polling.
- Job status transitions are `queued -> running -> succeeded | failed`;
  completed jobs carry the full Report and failed jobs carry an error message.
- The job registry is process-local with a size cap and TTL; no persistence. A
  restart loses in-flight and completed jobs, which is acceptable for a
  single-user local tool.

## Considered Options

- SSE push instead of polling: more real-time, but adds streaming infrastructure
  and makes tests and proxies more complex.
- FastAPI BackgroundTasks: awkward failure reporting and TestClient semantics
  for long-running jobs.
- Persistent job store: unnecessary until the product grows a real multi-user
  backend.

## Consequences

- Frontends can render live stage progress with a small polling loop.
- Tests can drive the job store deterministically without real HTTP
  concurrency.
- A future SaaS backend can replace the in-memory registry with a persistent
  store without changing the API contract.
