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
