# ResuAlign

## Agent skills

### Issue tracker

Issues and PRDs live in GitHub Issues (repo `shing26/ResuAlign-Lite`) via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles use default labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` glossary + `docs/adr/` decisions. See `docs/agents/domain.md`.

### QA agent

Generic QA methodology lives in `docs/agents/qa-agent.md`; ResuAlign's concrete
instance is `docs/agents/qa-dogfooder.md`. It is registered as Codex custom
agent `qa_agent` (`.codex/agents/qa-agent.toml`) - ask Codex to spawn it for
product/UX QA runs.

## Local repo quirks

### Git branch ref silently disappears on commit

This repository has a **git branch reference bug**: after `git commit` on a
branch under `refs/heads/pr/` (e.g. `pr/2-graph-cleanup-ats`), the branch ref
file is silently deleted (the commit objects remain intact, but `git log`
reports "branch has no commits"). Note that `git rev-parse HEAD` ALSO fails
once the ref is gone. Rebuild the ref with the full 40-char hash from the
reflog or the commit output:

```bash
# 1) find the commit (use the hash printed by `git commit`, or `git reflog`)
FULL=$(git rev-parse daa76ce)   # any abbreviated hash of the new commit
mkdir -p .git/refs/heads/pr
printf '%s\n' "$FULL" > .git/refs/heads/pr/2-graph-cleanup-ats
```

Do not run `git branch -D` on the affected branch before rebuilding the ref.
Short hashes in the ref file are rejected as broken refs — always write the
full 40-char object name.

### Regression baselines (2026-09-13, post prod-readiness #97-#103)

- Backend: `PYTHONPATH=src python -m pytest tests/ -q` → **967 passed / 7 skipped**
- Frontend: `node --test tests/frontend/*.test.mjs tests/frontend/dom/*.test.mjs`
  → **485 passed**
- Page probe: 8 routes, 0 console error. Playwright browser now
  **chromium-1243** (chromium-1234 was removed). Gate variant
  `.scratch/prod-readiness/gate_probe.py` points at an isolated 8003
  instance (fresh `RESUALIGN_DATA_DIR`) so it never touches the user's 8000.
- DeepSeek .env key tests **ok** as of 2026-09-15 (was 402 unpaid in
  September early-month); the active LLM node is `meta/muse-glimmer-30b`
  via NVIDIA integrate API — 9 月真实对齐 4/5 零产出（假成功主症状，
  见 #110 归因与派单 #115）。Ollama qwen2.5:7b 是已知能力地板
  （批量对齐 8 连跑各出 1 diff）。Workbench pre-flight probe (Phase A1)
  blocks definitive auth/quota failures and local-node connectivity
  failures with an actionable message before queueing (Phase E: local
  fast-fail, remote network/timeout non-blocking).

### Production-readiness invariants (2026-09-13, spec #97)

- **#100 error shape**: every HTTP error body is JSON; existing `detail` is
  byte-preserved and a top-level `request_id` is appended; uncaught
  exceptions → 500 `{code,message,request_id}` (never Starlette text, never
  `str(exc)` passthrough — auth login/signup now return fixed 话术). Runtime
  lock = `tests/test_error_contract.py`; OpenAPI snapshot is intentionally
  **not** touched (grilling decision).
- **#101 request_id**: `jobs` table migration 3 adds `request_id`;
  `_run_job` restores the ContextVar from the row so job.* / llm logs share
  one id; startup requeue mints a fresh id marked `recovered`. Any new API
  enqueuing a job must run inside the request-id middleware (it binds state
  + ContextVar) or the row stores `''`.
- **#102 watchdog**: running jobs older than `RESUALIGN_JOB_MAX_RUNTIME_S`
  (default 1800, 0=off) flip to the existing failed terminal via
  `JobRegistry.fail` (conditional UPDATE → a late worker write cannot
  overwrite). Only DB/board state is fixed; a truly hung worker still holds
  its tenant gate (documented boundary, no gate timeout).
- **#103 node breaker**: `llm_nodes` migration 5 adds
  `consecutive_failures`/`auto_disabled`; threshold 3; counted call codes
  `timeout/http/auth/quota/other` + counted probe statuses (see
  `LLMNodeStore`), `429/parse/schema/empty` excluded. **Filtering lives only
  in the call chain** (`get_usable_node`, `resolve_node_for_role`,
  `role_router.usable_active_node`, engine `use_roles`, A1 pre-flight,
  build_config callback); admin paths (list / activate / delete-promotion /
  settings badge) keep `get_active_node`. Recovery = test ok / call success /
  explicit activate; no auto half-open.

### Phase A-C invariants (2026-08-30)

- **A1**: `_probe_active_llm_quick` runs before queueing a workbench run;
  only HTTP 401/402/403 block (422 + message). Tests stub it via the
  `stub_workbench_llm_probe` autouse fixture in `tests/conftest.py`.
- **A2**: no-op diffs (`original == proposed` on modify/remove) are filtered
  into `invalid_diffs` in `_run_job` before `save_alignment`.
- **C**: resume list page-header and settings-head must NOT render an h2
  (the topbar already renders the page title). Guarded by
  `tests/frontend/css-structure.test.mjs`.
