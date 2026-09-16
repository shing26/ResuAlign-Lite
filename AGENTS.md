# ResuAlign

## Agent skills

### Issue tracker

Issues and PRDs live in GitHub Issues (repo `shing26/ResuAlign-Lite`) via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles use default labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` glossary + `docs/adr/` decisions. See `docs/agents/domain.md`.
`docs/README.md` maps the docs tree (flat layer = live docs, `plans/` + `reports/` = archive)
and says where each new document goes — read it before adding or moving a doc.

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

### Regression baselines (2026-09-16, post #111/#117/#118)

- Backend: `PYTHONPATH=src python -m pytest tests/ -q` → **997 passed / 7 skipped**
- Frontend: `node --test tests/frontend/*.test.mjs tests/frontend/dom/*.test.mjs`
  → **489 passed**
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

### Probe repo: truetailor owns the gate (2026-09-15, ADR-0041 week 2)

`shing26/truetailor` (sibling checkout, usually `D:\truetailor`) is the **source
of truth** for `gate.py` and the golden fixtures. This repo holds a vendor copy:

- `src/resualign/gate.py` and `tests/fixtures/gate/*` must stay byte-identical to
  upstream (LF-normalized sha256 in `tests/fixtures/gate/VENDOR.json`, asserted by
  `tests/test_skill_vendor_lock.py`). A rule change goes upstream first, then a
  re-sync commit here updates the manifest and `synced_from`.
- `tailor.py` keeps its own copy of the content check for historical reasons;
  `tests/test_gate.py::TestDriftLockParity` runs **every** fixture scenario in
  both languages through `tailor.gate_diff_items`, so the two implementations
  cannot diverge silently. Any new gate rule needs both edits plus a fixture.
- Fixtures are the spec: a new scenario arrives as a diff entry + an
  `expected*.json` line, and `python selftest.py` in the skill repo must pass.
- Probe video (issue #113): `python scripts/probe_video.py` re-runs the real
  commands against `D:\truetailor/examples/demoflow` and renders
  `docs/gate-demo.mp4` from the captured output (terminal replay, not a mock).

### 探针判据：双线与预注册时钟 (2026-09-16, ADR-0042)

ADR-0042 对 ADR-0041 决定 4/9/10 做了**限定性修正**（数值未改，只改时钟起点
与线的划分）。执行任何探针相关动作前先读这一节：

- **时钟起点 = 四渠道 outreach 全部发出当日**（原为转公开时刻 09-15）。
  实际发出日期记在 `docs/probe-112-send-checklist-2026-09-16.md`。
- 若 **09-23 24:00 前未全部发出** → 判据登记 `dist_not_executed`：
  时钟不启动、判据保持 PENDING、**这不是证伪**，处置 = 先执行分发。
- **判据两条独立线，不许互相顶替**：
  - **探针线**（口径一字未改）= 非作者首跑 ≥5 例（各附门禁摘要行原样粘贴）
    或 1 例外部完整合格链 = 过；≥100★ 或社区二创 = 强信号；4 周后 <2 例 = 证伪。
  - **自用线**（口径 = ADR-0040 需求线 a）= 合格例 ≥3，基线 **1 例**
    （09-15 狗食两跳链）。取证**只认验证器 JSONL**（`round` / `trigger` /
    `chain` / `resume_sha256`）；`examples/demoflow` 合成例、截图、口头
    复述一律不计；输入必须是作者**真实投递过**的岗位 JD。
- **项目级归档 = 探针线证伪 ∧ 自用线 = 0**。探针线单独证伪只触发
  「skill 线冻结、回 app-only」，不终结项目。
- 护栏：两线阈值均不得中途重谈（要改须新开 ADR 并回答「为什么现在改」）；
  自用线推进期间 **app 冻结令继续有效**，例外须逐项引用 ADR-0042 决定 6e。

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
- **#111 usable_diffs 分型 (ADR-0041 决定 5)**: `library_jobs` migration 45
  adds `usable_diffs` (backfilled from `diffs_json` length; first MIGRATIONS
  script with an UPDATE). Terminal typing happens at the workbench SAVE site
  (`services/jobs.py`, before `save_alignment`) — 有缺口 ∧ usable=0 →
  `failed` + `last_alignment_error` prefix `no_output: ` (machine contract;
  projection derives `alignment_reason`, never re-parse in UI); 无缺口 ∧
  usable=0 → stays `succeeded`, badge 「无缺口 · 无需改写」. `analysis_ready`
  unchanged. Dashboard 完成对齐 numerator counts `usable_diffs>=1` only;
  legacy rows (no typing fields) keep the old 无建议/诊断完成 badges via the
  fallback in `alignmentBadgeHtml`.
- **#117 test-log isolation**: `tests/conftest.py` top-level
  `setdefault(RESUALIGN_LOG_DIR, <tmp>/resualign-pytest-logs)` before any
  `resualign.api` import — real `data/logs/app.log` stays clean (verified
  delta=0 per full run); e2e subprocesses inherit. Historical test traffic
  (~71 lines) stays in the real log; filter by timestamp, do not rewrite it.
- **#118 jobs terminal retention**: `JobRegistry(terminal_retention_seconds
  =30d)` — `_purge_expired` purges non-terminal rows at `ttl_seconds` but
  keeps succeeded/failed/canceled rows for the retention window; read path
  `_get_current` lazy-deletes only NON-terminal expired rows (API expiry view
  unchanged). Weekly success-rate queries: jobs terminal rows ×
  `library_jobs.usable_diffs`. `max_jobs` cap still evicts terminal rows
  (retention is an upper bound, not a guarantee).

### Phase A-C invariants (2026-08-30)

- **A1**: `_probe_active_llm_quick` runs before queueing a workbench run;
  only HTTP 401/402/403 block (422 + message). Tests stub it via the
  `stub_workbench_llm_probe` autouse fixture in `tests/conftest.py`.
- **A2**: no-op diffs (`original == proposed` on modify/remove) are filtered
  into `invalid_diffs` in `_run_job` before `save_alignment`.
- **C**: resume list page-header and settings-head must NOT render an h2
  (the topbar already renders the page title). Guarded by
  `tests/frontend/css-structure.test.mjs`.
