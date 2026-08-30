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
reports "branch has no commits"). Fix after every commit:

```bash
mkdir -p .git/refs/heads/pr
printf '%s\n' "$(git rev-parse HEAD)" > .git/refs/heads/pr/2-graph-cleanup-ats
```

Do not run `git branch -D` on the affected branch before rebuilding the ref.

### Regression baselines (2026-08-30)

- Backend: `PYTHONPATH=src python -m pytest tests/ -q` → **792 passed / 7 skipped**
- Frontend: `node --test tests/frontend/*.test.mjs tests/frontend/dom/*.test.mjs`
  → **473 passed**
- Page probe: 8 pages, 0 console error (`.scratch/ra_probe_v2.py`, Playwright
  chromium-1234). DeepSeek .env key is **402 unpaid** — the active LLM node is
  Ollama qwen2.5:7b; the workbench pre-flight probe (Phase A1) blocks
  definitive auth/quota failures with an actionable message before queueing.

### Phase A-C invariants (2026-08-30)

- **A1**: `_probe_active_llm_quick` runs before queueing a workbench run;
  only HTTP 401/402/403 block (422 + message). Tests stub it via the
  `stub_workbench_llm_probe` autouse fixture in `tests/conftest.py`.
- **A2**: no-op diffs (`original == proposed` on modify/remove) are filtered
  into `invalid_diffs` in `_run_job` before `save_alignment`.
- **C**: resume list page-header and settings-head must NOT render an h2
  (the topbar already renders the page title). Guarded by
  `tests/frontend/css-structure.test.mjs`.
