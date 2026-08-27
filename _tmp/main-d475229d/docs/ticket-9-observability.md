# Ticket #9 — Observability: events + readiness + metrics

Scope: job lifecycle events, LLM call metrics, `/health` readiness, and
`/api/ops/metrics`. Implements GitHub issue #9.

## Structured log events (via `resualign.observability.log_event`)

- `job.queued` — `JobRegistry.create` (extra: `job_id`, `tenant_id`)
- `job.claimed` — `JobRegistry.claim_running` on a successful claim (extra: `job_id`)
- `job.stage` — `JobRegistry.update_progress` while running (extra: `job_id`, `stage`, `message`)
- `job.finished` — `JobRegistry.succeed` / `fail` / `cancel` (extra: `job_id`, `outcome`; `error` on failure)
- `job.requeued` — `JobRegistry.requeue_interrupted` at startup recovery
- `llm.call` — every OpenAI-compatible transport attempt, emitted once per logical
  call with `provider`, `model`, `stage` (`chat_json` / `chat_structured`), `mode`
  (`json_object` / `json_schema`), `duration_ms`, `attempts` (HTTP attempts made),
  `status` (`ok` / `failed`). Retry logic is untouched; instrumentation is a
  try/finally wrapper around the existing loops.

Events are emitted inside the registry / client methods, so the services layer
does not need changes.

## Endpoints

### GET /health (unchanged route, extended body)

```json
{
  "status": "ok",
  "checks": {
    "db":    {"ok": true, "detail": "database readable"},
    "cache": {"ok": true, "detail": "cache read/write ok"}
  }
}
```

- `db` — `JobRegistry.ping()` executes `SELECT 1`.
- `cache` — write-read roundtrip through the public `ContentCache` API with a
  fixed probe key (tiny, INSERT OR REPLACE, expires with TTL).
- `status` is `ok` when every check passes, `degraded` otherwise. The response
  keeps the `status` field (string), so the OpenAPI `{}` body contract is
  unchanged.

### GET /api/ops/metrics (new, ops-only)

```json
{
  "queue": {"depth": 2, "oldest_waiting_seconds": 12.0},
  "jobs":  {"by_status": {"succeeded": 1, "failed": 1}, "failure_rate": 0.5},
  "llm":   {"total": 3, "successes": 2, "failures": 1,
            "success_rate": 0.6667,
            "duration": {"count": 3, "min_ms": 5.0, "p50_ms": 15.0,
                         "p95_ms": 25.0, "max_ms": 25.0}},
  "uptime_seconds": 123.4
}
```

- Queue depth = queued + running jobs; oldest waiting = age of the oldest queued job.
- Job failure rate is derived from the SQLite store (`outcome_stats`), so it
  survives restarts.
- LLM stats come from a module-level `CallStats` (200-sample ring buffer for
  durations), fed by `llm.call` observation.
- **Contract note:** the route is registered with `include_in_schema=False`.
  Ops endpoints are intentionally not part of the public v1 OpenAPI contract,
  so `contracts/openapi-current.json` and the incremental manifest stay
  unchanged. If this policy changes, regenerate the snapshots deliberately.

## Files touched

- `src/resualign/observability.py` — added `MetricWindow` (ring buffer + p50/p95)
  and `CallStats` (counters + duration window).
- `src/resualign/llm.py` — `_observe_llm_call`, `llm_metrics_snapshot()`, provider
  attribute on `OpenAIClient`, try/finally instrumentation of `chat_json`,
  `_chat_structured_provider`, `_chat_structured_json_mode`.
- `src/resualign/jobs.py` — lifecycle `log_event`s; new `queue_depth()`,
  `oldest_waiting_seconds()`, `outcome_stats()`, `ping()`.
- `src/resualign/api/routers/health.py` — readiness checks behind `/health`.
- `src/resualign/api/routers/ops.py` — new `/api/ops/metrics` router.
- `src/resualign/api/__init__.py` — registered the ops router after `app = FastAPI(...)`.
- Tests: `tests/test_health.py`, `tests/test_ops_metrics.py`,
  `tests/test_job_events.py`, `tests/test_llm_metrics.py`; extended
  `tests/test_observability.py`; updated `/health` assertions in
  `tests/test_api.py` and `tests/test_contract.py`.

## Handoff to #13 (log governance)

This ticket adds event emission but deliberately does **not** configure logging
(output formatting, JSON serialization to file, rotation, sampling, or field
redaction). #13 should own:

- a single logging configuration (format/handlers/levels) applied at app startup;
- retention/rotation policy for the structured JSON lines;
- redaction rules for sensitive fields (`llm.call` extras contain model names,
  `job.finished` failure extras contain error text) and truncation for long
  `error` values.
