# ADR-0016: Deliverable Upgrade for the Personal Workbench

**Status**: Accepted
**Date**: 2026-08-02

## Context

Four specialist agent evaluations converged on the same conclusion: the
workbench is functionally coherent but not shippable. Product gaps (Settings
stub, no history/export, disconnected Job Library and Workspace), frontend
state bugs and single-file maintainability, backend process-local job
execution and crawler SSRF risk, and the absence of deployment/onboarding all
stand between the current app and a deliverable product.

## Decision

- Phase 14 is a delivery-focused upgrade, not a new feature wave: close the
  four modules, harden the backend, rebuild the frontend without a build
  step, and ship scripts/docs/CI.
- Personal-first remains the product default (ADR-0014); SaaS auth stays
  dormant and the frontend is explicitly personal-mode-only this phase.
- The persistent worker is the core backend change: SQLite-backed payloads,
  single-writer, restart recovery, no eviction of active jobs, unchanged
  polling contract.
- The crawler treats every URL as untrusted: scheme allowlist, DNS/private-IP
  checks, redirect cap, streamed byte cap.
- The frontend splits into `styles.css` + `app.js` with hash routing; this is
  cheaper and more robust than adding a bundler now, and it enables a real
  CSP later.
- Settings becomes an editable, persisted API surface instead of a stub.

## Considered Options

- Adopt React/Vite now: heavier than the current app needs; the no-build
  split covers routing, state fixes, and maintainability for the current
  scale.
- Keep in-memory threads and add a queue library: still loses jobs on
  restart; a bounded SQLite-backed worker solves persistence and restart
  safety together.
- Treat the crawler as trusted: false for any user-supplied URL; SSRF and
  byte-cap protection are mandatory before real use.

## Consequences

- API gains pagination, export, cancel, and settings endpoints while keeping
  the existing polling contract backward-compatible.
- SQLite needs a versioned migration layer; existing databases are migrated
  additively, not reset.
- The frontend file split changes how static assets are served, so the API
  server must mount `static/` and stop serving inline scripts/styles.
- Phase 14 is a prerequisite for any future SaaS exposure: rate limits,
  stable errors, and the hardened crawler must exist before multi-user mode.
