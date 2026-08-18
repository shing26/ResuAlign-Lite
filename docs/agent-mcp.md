# Agent-Native Backend (MCP + Headless + HITL)

Sprint 6 adds three agent-facing surfaces on top of the existing FastAPI
application. Everything lives in `src/resualign/agent/` and defaults to the
personal-mode tenant `"local"`.

## MCP server (`agent/mcp_server.py`)

A FastMCP server exposing the job-library pipeline as four tools. Run it
over stdio with:

```bash
python -m resualign.agent.mcp_server
```

To serve over SSE, call `resualign.agent.mcp_server.run("sse")` or embed
`get_mcp_app()` in your own process.

| Tool | Signature | Returns |
| --- | --- | --- |
| `fetch_and_evaluate_job` | `(url: str, tenant_id: str = "local")` | `{status, job_id?, blocker_id?, category?, reason?}` — `status` is `created` / `duplicate` / `blocked` / `rule_rejected` (Sprint 3 state machine) |
| `auto_align_resume` | `(job_id: str, master_resume_id: str \| None = None, tenant_id: str = "local")` | `{analysis_job_id, status: "queued"}` or `{status: "error", error}` |
| `get_pending_blockers` | `(tenant_id: str = "local")` | `[{blocker_id, url, title, reason, category, created_at}]` |
| `resolve_blocker` | `(blocker_id: str, text: str, tenant_id: str = "local")` | `{status: "resolved", blocker_id, job_id}` or `{status: "error", error, blocker_id}` |

`auto_align_resume` queues through the same `_queue_job(user, payload,
workbench=True)` path as the web API (granularity defaults to `medium`) and
pins the job's `workbench_job_id`/`workbench_resume_id`. The resume is taken
from `master_resume_id` or the tenant's most recently updated master resume.

Tools are plain functions (the `@mcp.tool()` decorator returns the original
callable), so they can be imported and called directly without a transport:

```python
from resualign.agent.mcp_server import fetch_and_evaluate_job
result = fetch_and_evaluate_job(url="https://example.com/jobs/1")
```

## JD intake orchestrator (`agent/orchestrator.py`)

Phase A of ADR-0029 adds a minimal agent loop on top of the MCP tools. It
never touches stores/API internals directly; every side effect goes through
`JdIntakeTools.default()` (the three MCP functions).

```python
from resualign.agent.orchestrator import (
    JdIntakePolicy,
    run_jd_intake,
    process_pending_blockers,
)

result = run_jd_intake(
    url="https://example.com/jobs/1",
    resolve_text="",  # paste JD text here to auto-resolve a transient fetch
    policy=JdIntakePolicy(),
)
```

Per URL the orchestrator performs one fetch plus at most one agent decision
round. The default policy keeps login/CAPTCHA/rule blockers pending and only
resolves transient network failures when pasted JD text is supplied. Tool
failures and budget exhaustion degrade to the existing blocker path; decisions
are logged as `agent.decision`, failures as `agent.failure`, and budget skips
as `agent.budget_exceeded`. Queue-driven mode:

```python
stats = process_pending_blockers(
    tenant_id="local",
    resolve_texts={"<blocker_id>": "JD text"},
)
```

The default `JdIntakePolicy` is deterministic and conservative.
`LLMJdIntakePolicy` (`agent/policy_llm.py`) asks the configured LLM for the
same decision with a fixed prompt and `JdIntakeDecisionSchema`; when the LLM
is unavailable or returns an invalid action, the orchestrator keeps the
blocker pending.

The headless daemon runs `process_pending_blockers` on every poll round.
`RESUALIGN_AGENT_POLICY` selects the policy: `auto` (default) uses the LLM
when an API key is configured, `llm` forces it, and `deterministic` keeps
the conservative local policy.

## HITL webhook (`agent/hitl.py`)

`emit_hitl_event(event, payload)` fans events out to
`RESUALIGN_WEBHOOK_URL` (JSON POST, 5s timeout, failures logged and
swallowed). Without a URL it writes a structured `log_event` instead.

- `blocker.created` — emitted by the fetcher pipeline whenever a blocker is
  created: `{blocker_id, url, reason, category}`
- `alignment.low_confidence` — emitted by `auto_align_resume` when the job
  already carries low-confidence diffs: `{job_id, diff_index, confidence}`

## Headless daemon (`agent/headless.py`)

```bash
resualign --headless [--interval 30]
resualign --agent-mode [--interval 30]    # synonym
```

`run_headless(interval, tenant_id, start_server=True, once=False,
max_rounds=None)` starts the FastAPI app on a background uvicorn thread
(optional — skipped when the port is already bound) and polls every
`interval` seconds:

1. Classify pending blockers and log the disposition (rule-rejected /
   login/CAPTCHA are kept pending; no auto-resolution without human text).
2. Queue `auto_align_resume` for library jobs whose `alignment_status` is
   `idle`/`failed` (never double-queues in-flight runs).

The daemon never starts the web frontend. `once=True` / `max_rounds=1`
bounds the loop for tests/one-shot runs; the function returns the last
round's stats dict (or `{}` when no round ran).

## Concurrency note

`store_base.py:51` already enables `PRAGMA journal_mode=WAL`, so the daemon
and the FastAPI app can share the same SQLite database. Concurrency-guard
tests are owned by the parallel agent (B).
