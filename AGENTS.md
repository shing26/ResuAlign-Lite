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
  `tests/platform/test_skill_vendor_lock.py`). A rule change goes upstream first, then a
  re-sync commit here updates the manifest and `synced_from`.
- `tailor.py` keeps its own copy of the content check for historical reasons;
  `tests/engine/test_gate.py::TestDriftLockParity` runs **every** fixture scenario in
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
  两线的数值与取证口径仍不得中途重谈。

### 双主线与 app 自用验证 (2026-10-19, ADR-0059)

ADR-0059 已取代 ADR-0041 的 app 冻结总闸。执行 app 相关动作前先读
`docs/adr/0059-dual-mainline-app-self-use-first.md`：

- app 与 skill 探针是双主线；探针阈值/取证不变，冲突时 app 的真实自用
  验证优先。探针不能再冻结 app，app 使用量也不能冒充探针首跑。
- app 顺序：P0 真实 JD 可靠性验证 → P1 ADR/票/feature flag → P2 三步工作台
  与文案 → P3 演示/BYOK/指标 → P4 展示型优化。首页样例与导航爆改不得插队。
- app 通过线 = 3 份作者真实投递过的不同 JD，每份至少采纳 1 条并保存定稿，
  至少 2 份导出或记录投递。不过线则新工作台默认关闭，回旧版。
- `frozen` 只保留 ADR-0041 历史语义；具体票必须重新分诊，不能继续当
  自动拒绝。旧票 #72/#26 等按 ADR-0059 的 P2/P3 顺序重排。

### 编辑器产出约束：技能清单禁止增长 (2026-10-19, #163 P0)

`tailor/v3` 起有两道防线，别拆：

- `TAILOR_PROMPT` 规则 5/8：缺口只覆盖原文有事实支撑的部分；技能清单类
  章节（`技能|skill`）只能改写已有条目。
- `_apply_editor_output_contract`（`engine/tailor.py`）：`modify`/`add` 命中
  技能章节且 `proposed` 条目数多于 `original` → 降级 `fabricated` 进
  `invalid_diffs`。整卷编辑器与逐条编辑器都过它。

为什么在 app 侧而不在 `gate_diff_items`：gap report 的 `missing_keywords`
是上游 gate 的放行术语来源（`tests/fixtures/gate` 的 d8/e6 锁着），所以
「把 JD 缺口词写进技能清单」会**假通过**内容级校验（2026-10-19 腾讯用例
实证 usable=2）。改语料语义属上游 truetailor 规则变更，须先上游后同步；
本约束按**条目数**判定，与 allowlist 语义解耦，且不触碰 parity 锁。
背景与重跑证据见 `docs/reports/app-self-use-reliability-2026-10-19.md`。

### 缺口术语兜底与逐条 evaluator 隔离 (2026-10-19, P0)

两条后续防线，改编辑器/评测前先读：

- **缺口术语兜底**：`_missing_keyword_violation`（`engine/tailor.py`）在
  `modify`/`add` 的 `proposed` 中发现 gap report 的 `missing_keywords` 词，
  但简历原文没有任何依据时，降级 `fabricated`。整卷编辑器与 map-reduce
  都在写回 `sections` 前过这条，避免中文术语绕过 `_unsupported_content`。
  这是 app 侧临时 guard；根因是 app 的 `missing_keywords` 语义与上游
  truetailor 不一致（见下一条）。
- **evaluator 逐条隔离**：`evaluator/v3` 输出 `hallucinated_diff_ids`；
  `split_verified_diffs` 只隔离被指认的 diff，其余保留。若 evaluator 报幻觉
  但没有可映射的 diff id，或确定性 provenance 校验发现无 id 的坏 diff，
  回退整轮硬阻断（ADR-0019 零幻觉硬门不变）。`EvalScore` 与
  `EvalScoreSchema` 都带该字段。

**allowlist 语义拆分（已决，ADR-0060 / #164）**：allowlist 只认
`supported_keywords`（JD 要、简历**有依据但没写明**）；`missing_keywords`
固定为「JD 要、简历**没有依据**」的真缺口，**永不进 allowlist**。上游
`gate.py::allowlist_corpus` 与 app `tailor.py::_gap_support_text` 键列表
一致（`supported_keywords / misaligned_emphasis / strength_matches /
business_scenarios`）。`jd_context` 仅作提示词上下文，永不进入 allowlist
（ADR-0061 / #165）。改动顺序固定：**先上游 truetailor
（gate + fixtures + SKILL/README/contract）→ 再同步 vendor
（`src/resualign/gate.py` + `tests/fixtures/gate/` + `VENDOR.json`）→ 再重跑
parity**（`tests/engine/test_gate.py::TestDriftLockParity` 与
`tests/platform/test_skill_vendor_lock.py`）。ADR-0041 决定 11 漂移锁不变。
黄金场景现为 **21** 个（`d11-` / `e8-missing-keyword-not-a-rewrite-source`
锁住 #164，`d12-` / `e9-jd-context-is-not-a-license` 锁住 #165）。app 侧
`gap_analyzer/v3`、`jd-analysis-v4`、`tailor/v4`。

**guard 后实测（2026-10-19，别把它当「已解决」）**：3 份真实 JD × 3
（`nvidia/nemotron-3-super-120b-a12b`）= **0/9 可用**，前一轮是 3/9。前一轮
那 3 个「可用」正是被 allowlist 放行的编造项，guard 已把它们改判
`fabricated`——**guard 修的是假通过，不是「编辑器产不出真建议」**。同一轮
Reolink 编辑器调用 90s 超时 2/3。字段拆分（ADR-0060）落地后复测
**2/9 可用、0 次基础设施错误**（腾讯 1/3、Dida 1/3、Reolink 0/3）。原始
数据见 `.scratch/p0-159-samples/results{,-post-guard,-pre-guard}.json`。

**#165 处置（已拍，ADR-0061 / 0062）**：

1. **`jd_context` 已从内容许可链移除**。上游 `allowlist_corpus` 不再接收
   该键，而且 context-only JSON 不再回退返回原文；app 主流程和工作台
   单条重试统一传 `jd_context_summary()` 生成的结构化摘要（≤300 字），
   不传 JD 原文，不传 `missing_keywords`。`rewrite_bullet` 的事实校验只认
   原 bullet。
2. **编辑器墙钟已放宽到 150s，但仍是每次 POST 的硬截止**。
   `_WallClockDeadlineExceeded` 在 TransportError 分支不重试，首发 >150s
   仍会硬失败。150s 的依据是 Reolink 上一轮 2/3 撞 90s、腾讯单发 81.9s；
   最坏单发估算 `45+75+150=270s`，远低于 watchdog 1800s。该值由
   `tests/api/test_r4_aie_guardrails.py` 锁定，改值先拍新 ADR。

**#165 后实测（2026-10-20，`48e2eb3`）**：同节点 3×3，隔离目录
`nvidia/nemotron-3-super-120b-a12b` = **3/9 succeeded、1/9 usable、
0 次基础设施错误、0 次 deadline**。Reolink #3 整轮 193.9s，编辑器
调用 170.4s / 2 次 POST，单次均未过 150s。结论：暂不继续放宽墙钟；
剩余瓶颈是编辑器证据化与产出质量，app 自用线仍为 0/3。详见
`docs/reports/app-self-use-post-165-2026-10-20.md`。

### 模块布局是刻意的：平铺 + 层表，别顺手分包 (2026-09-28)

`src/resualign/` 一级的平铺模块**不是失序**。层归属由
`src/resualign/tools/modgraph.py` 的 `LAYERS` 声明（接入 / API / 服务 / 引擎 /
领域 / 存储 / 可观测 / 模型 / 契约），CI Stage 1 的 `modgraph --check` 用集合差
棘轮**只允许减少**。R7「领域目录分包」施工单
（`docs/architecture-hardening-plan-2026-09-19.md` §3.3）**只落地了引擎批**
（`a9515be`：`engine.py` 转包 + 5 个模块移入 `engine/`）；`domain/` 与 `storage/`
两批于 **2026-09-21 明确暂停**——约 23 个模块、上百处导入，属纯组织性改动，
收益与风险不匹配。恢复条件 =「出现真实导航痛点」，**目前未触发**。
**看到「顶层模块偏多」不要直接开工搬目录**；`gate.py` 另受 ADR-0041 决定 11
漂移锁约束（`VENDOR.json` 按路径记哈希），路径不可动。

`tests/` 同理：子目录 = 不同 runner（`e2e/` `frontend/` `extension/`）加
`fixtures/`，根层 = 主 pytest 套件。这是既定约定，不是堆积。

### `archive/` 是归档层，不是死代码 (2026-09-28)

`src/resualign/archive/` 存的是**原始 LLM 报文归档**（ADR-0052「归档层」：
`RESUALIGN_LLM_TRACE` 默认 `0`，开启后落 `<RESUALIGN_LOG_DIR>/llm-traces.jsonl`），
是在用的模块（`engine/llm.py` 导入），名字与 ADR 用词一致。**别因为名字像
「已归档」就删。**

### Production-readiness invariants (2026-09-13, spec #97)

- **#100 error shape**: every HTTP error body is JSON; existing `detail` is
  byte-preserved and a top-level `request_id` is appended; uncaught
  exceptions → 500 `{code,message,request_id}` (never Starlette text, never
  `str(exc)` passthrough — auth login/signup now return fixed 话术). Runtime
  lock = `tests/api/test_error_contract.py`; OpenAPI snapshot is intentionally
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
