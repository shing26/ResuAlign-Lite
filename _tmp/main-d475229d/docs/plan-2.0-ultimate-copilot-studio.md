# ResuAlign 2.0 终极形态：AI 求职 Copilot + 交互式分屏工作室

**日期**: 2026-08-04
**状态**: 评审完成，待确认口径后进入 ticket 化
**参会部门**: 产品与用户体验部（PM: Mill）、前端与交互设计部（UI: Averroes）、
AI 策略与引擎部（AI: Hypatia）、后端与系统架构部（Architect: Descartes）、
质量与工程效能部（QA: Lagrange）

## 一、总原则：双标杆融合

本方案吸收两个标杆，不做「后台管理面板」：

- **求职方舟（Autofill）**：万能输入框、粘贴即解析、确认卡片、侧边浮窗、
  无感沉浸，废除复杂表单。
- **TalentCat（JD Optimizer）**：左右双栏分屏、JD 结构化画像卡片、履历
  Bullet Point 逐条对比、一键 AI 替换与导出。

用户提供的参考方案只作为设计方向；其中的代码片段仅供参考，不直接照搬，
最终实现以本仓库现有 ESM/API 契约与 ADR 为准。

## 二、核心结论

1. 主视图确定为 **Optimizer 双栏 Split-Canvas**，Copilot 是覆盖在画布上的
   抽屉/快搜层；不再默认常驻第三栏（修订 ADR-0020 第 12 条）。
2. 主工作流压缩为「粘贴 -> 确认 -> 分屏」：顶栏万能输入框接收 URL/文本，
   后台解析出确认卡片，确认后自动入库并预热 JD 画像与 Gap Report。
3. 删除「添加岗位表单」和「创建投递记录表单」；投递记录由看板状态迁移
   派生，岗位库仍是唯一状态源。
4. API 从实体 CRUD 转向会话编排器：新增
   `POST /api/workbench/session/init`（粘贴即建会话）与
   `GET /api/workspace/session/{job_id}`（打开既有岗位），共享同一份
   `WorkstationState` 契约和 SSE 事件通道。
5. AI 粒度下沉到 Bullet：稳定 `diff_id` 贯穿 SSE、重写、采纳与前端状态；
   `provenance_state` 逐条可点、无来源拒收或 `pending_review`。
6. 持久化边界修正为：运行中会话/进度/tentative diff 走内存，终态
   alignment 产物（gap/diffs/score/draft）与任务信封、看板状态落 SQLite。
7. 质量护栏先行：契约增量、`#print-root` 导出契约、Playwright 新主线、
   benchmark SLO，全部在视觉重构前修复。

## 三、现状诊断汇总

### 产品与 UX

- 顶栏没有 Copilot 入口，仍是后台导航；添加岗位是 8 字段 CRUD，URL 解析
  只回填表单（`main.js:405/1149`）。
- 看板是「伪看板」：卡片无 `draggable`、无 `match_score`，状态靠 select。
- 工作台是「先选岗位 -> 填参数 -> 一键生成 -> 轮询等待」的任务提交页，
  AI 能力默认不可见（`main.js:776`）。
- 「创建投递记录」仍独立存在，与「投递记录是派生状态」冲突。
- AI 结果依赖内存 registry，gap/diffs/draft 不落库。

### 前端与交互

- 仍是固定 rail + topbar + 单页 `#app` 的 Dashboard 壳层，不是工作画布。
- 工作台是 `300px 1fr 320px` 三栏任务表单，不是 TalentCat 双栏。
- Diff 是 set-based `lineDiff()`，没有逐条卡片、拒绝、AI 润色；provenance
  是卡片底部 blockquote，不可点击定位原文。
- 没有 Cmd/Ctrl+K、万能输入、粘贴即解析、Copilot 抽屉或 SSE 消费代码。
- `#print-root` 缺失、`printTarget` 未定义，PDF 导出实际不可用。

### AI 策略与引擎

- 全量成功才返回结果，`gap_ready` 无法作为中间结果先落地。
- JD 画像必须同时传简历，JD-only `profile_jd()` 已有但未接线。
- 没有 bullet-level 重写入口；「重新生成」仍是全量重跑。
- Diff 无稳定 `diff_id`，采纳按数组下标；provenance 只做引文存在检查，
  `add + original=""` 可绕过。
- 无 bullet 缓存；单模型 + 16k max_tokens + schema retry sleep 1s 无法满足
  单条 1s 目标；字段名 `must_have_skills / business_scenarios` 与目标
  `required_skills / business_scene` 不一致。

### 后端与架构

- `routers/jobs.py` 单文件承载 ingest/CRUD/workbench/appraisal/bulk status；
  没有 workspace/kanban/session 编排层。
- 前端打开工作台 4+ RTT；全仓无 SSE 路由；crawl 同步阻塞，无
  `crawl_tasks` 持久化。
- `JobRegistry` 1 小时 TTL/100 条上限；`BatchAlignStore` 与 import 均内存态；
  alignment 结果只存 `final_draft`。
- `_WORKER_SEMAPHORE=1` 会成为会话编排瓶颈；bulk-status 隐藏且逐条循环。

### 质量与工程效能

- 契约 golden 未入库，测试是「全等比较」而非增量；OpenAPI 大量空 schema、
  无错误契约。
- `test_e2e.py` 不是浏览器 E2E；Phase-20 smoke 的 selector 已漂移，
  `#print-root`/`printTarget` 硬伤会导致 PDF 步骤失败。
- latency 阈值未收紧（cold 5.5s 而非 3.3s）；无 session/bullet/rewrite/SSE
  benchmark；缺真实多 worker、SSE 时序、重启恢复、invalid provenance 测试。

## 四、目标形态

```text
+-------------------------------------------------------------------------------------------+
| [RA] ResuAlign 2.0   [Copilot] [Optimizer]  [🔍 万能输入/粘贴 URL·文本 · Cmd/Ctrl+K]      |
+-------------------------------------------------------------------------------------------+
|  Copilot 抽屉（可折叠）      |  Optimizer Split-Canvas                                     |
|  - 岗位快搜 / 五列看板        |  左栏 JD 智能剖析区（35%）      右栏履历对比编辑器（65%）    |
|  - 投递状态时间线            |  - 岗位基本信息 + 匹配度雷达    - Bullet 逐条 Diff 卡片       |
|  - match_score 标签          |  - 硬性技能 Gap + 场景关键词    - [采纳][拒绝][AI 润色]      |
|  - 拖拽/键盘改状态           |  - Proactive Parsing 即时渲染  - Provenance 逐条高亮        |
|                              |                                  - 复制 Markdown / 导出 PDF   |
+-------------------------------------------------------------------------------------------+
```

### 关键组件与 data 契约

- 全局命令栏：`[data-command-input]`、`[data-surface-mode="copilot|optimizer"]`、
  `[data-export-dock]`。
- Copilot 抽屉：`[data-copilot-drawer]`、`[data-job-list]`、
  `[data-job-status-filter]`、`[data-application-timeline]`。
- Optimizer：`[data-jd-canvas]`、`[data-jd-summary]`、`[data-hard-gap]`、
  `[data-match-radar]`、`[data-scenario-tags]`、`[data-resume-canvas]`。
- Diff 卡片：`<article class="diff-card" data-diff-id>`，内含
  `[data-diff-original] / [data-diff-proposed] / [data-diff-reason] /
  [data-provenance] / [data-diff-actions]`。
- 保留冻结契约：`#app`、`#toast-region`、`#print-root`（本轮补齐）、hash
  路由、`data-*`、`aria-*`；新增动作全部登记到现有 `data-action` 委托。

## 五、跨部门冲突与决议

| # | 冲突点 | 决议 |
| --- | --- | --- |
| 1 | ADR-0020 三栏 vs TalentCat 双栏 | 默认双栏 Split-Canvas，决策/评估面板收进 Copilot 抽屉；三栏只作为 >=1280px 用户主动展开的可选视图。 |
| 2 | 双模式路由 | 双模式是 shell 级布局切换：Copilot 复用 `#/jobs`，Optimizer 复用 `#/workspace/:jobId`，不新开唯一入口路由。 |
| 3 | `POST /api/workbench/session/init` vs `GET /api/workspace/session/{job_id}` | 两者并存：init 负责粘贴 raw JD 建会话，GET 负责打开已有岗位；共享同一 `WorkstationState` 与 SSE 事件契约。 |
| 4 | SQLite 只存最终定稿 vs alignment 持久化 | 运行中会话/进度/tentative diff 内存化（TTL 30 分钟）；终态 gap/diffs/score/draft 与任务信封、看板状态必须落库。 |
| 5 | Bullet 重写 1s vs 单模型延迟 | 硬门为 cache hit <=500ms / 首事件 <=2s；cold 走 SSE pending；`fast_model` 或 bullet 低延迟路径提前到 P0。 |
| 6 | 字段命名 | 公开契约采用 `required_skills / nice_to_have / business_scene`，Pydantic 对旧字段提供 alias 兼容。 |
| 7 | 拖拽 vs 自动化 | 拖拽是 P0 体验目标；状态迁移以 API 契约为准，Playwright 硬门走 select/键盘，拖拽只做非硬门 smoke。 |
| 8 | SSE tentative vs JSON | SSE 只推事件；`job.result` 必须与 GET snapshot 一致；前端不得采纳 tentative diff。 |
| 9 | 打印契约 | `#print-root` 与 `printTarget()` 必须在视觉重构前修复并进入 Playwright 硬门。 |
| 10 | 参考方案代码 | 仅作为设计参考，不直接复制；组件与 API 以本仓库契约和既有 ESM 结构实现。 |

## 六、P0 / P1 范围

### P0

- 万能输入：URL/文本/文件 -> `preview` -> 确认卡片 -> 入库 -> 自动预分析。
- 五列拖拽看板 + match 标签 + 批量单事务状态。
- Optimizer 双栏 Split-Canvas + Copilot 抽屉双模式。
- 零点击预分析：`profile_jd()` 拆 JD-only 链路，`gap_ready` 中间结果。
- SSE 事件通道 + 统一前端事件状态机，轮询兜底。
- Bullet 行内重写：稳定 `diff_id`、instruction 白名单、provenance 高亮。
- `#print-root`/导出契约、一键复制 Markdown / PDF。
- 契约增量、response model、Playwright 新主线、benchmark SLO 护栏。

### P1

- `fast_model / reasoning_model` 模型分层与 bullet 低延迟专用参数。
- 在线 P95 nightly、60fps 采样。
- ContentStore 大文本外置与备份迁移。

## 七、分阶段实施路线

1. **Phase 0 护栏修复**：契约基线入库与增量 manifest、OpenAPI response
   model、`#print-root`/`printTarget`、Playwright selector 对齐、latency
   SLO、基线 pytest artifact。
2. **Phase 1 数据与 API**：`aligned` 状态、crawl_tasks、kanban 单事务、
   session/init 与 session GET、preanalyze、alignment 持久化。
3. **Phase 2 前端主流程**：万能输入、确认卡片、五列看板、Copilot 抽屉、
   Optimizer 双栏、统一事件状态机、骨架屏。
4. **Phase 3 AI 流式**：JD-only 预分析、SSE、gap_ready、单 diff 重写、
   provenance_state、invalid_diffs 可见。
5. **Phase 4 视觉重构**：Phase 20 token、Bento、glass 白名单、命令面板。
6. **Phase 5 质量收口**：E2E 全流程、并发/SSE/重启/负向测试、nightly。

每个 Phase 先出 spec + tickets，按 contract-first + TDD + code-review 执行，
保持 `resualign.api:app` 入口、`engine.run()` 与 `tailor_resume()` 签名不变，
现有 pytest 全绿。

## 八、API / 契约草案

### WorkstationState

```json
{
  "session_id": "",
  "status": "initializing|ready|failed",
  "job": {},
  "jd": {"profile": null, "status": "queued|ready|failed", "error": null},
  "resume": {"selected_resume_id": null, "available_resumes": [], "content_ref": null},
  "gap": {"status": "queued|running|ready|failed|blocked", "score": null,
          "gap_report": null, "cache_hit": false, "error": null},
  "alignment": {"status": "idle|queued|running|succeeded|failed",
                "stage": "", "diffs": [], "invalid_diffs": [],
                "draft": null, "eval_score": null},
  "appraisal": {},
  "crawl": {"crawl_id": null, "status": "idle", "stage": "", "error": null},
  "meta": {"etag": "", "updated_at": "", "event_url": ""}
}
```

### 新增/演进接口

- `POST /api/workbench/session/init`：`{raw_jd | jd_url, master_resume_id |
  resume_text, granularity, prompt_focus, idempotency_key}` -> 202 +
  WorkstationState。
- `GET /api/workspace/session/{job_id}`：打开既有岗位，读取不触发 LLM。
- `GET /api/workbench/session/{session_id}/events`：SSE 事件通道。
- `POST /api/jobs/preview`、`GET /api/jobs/preview/{preview_id}`。
- `POST /api/jobs/{job_id}/preanalyze`。
- `POST /api/jobs/{job_id}/workbench/rewrite`：`{diff_id, instruction:
  quantified|high_concurrency|concise}`，原文由后端从持久化 alignment 取。
- `POST /api/kanban/bulk-status`：单事务、幂等、乐观锁。
- `GET /api/jobs?board=1`：返回 `status_canonical + final_draft +
  match_score + analysis_ready`。

### SSE 事件

`job.stage / job.gap_ready / tailor.diff(tentative) / job.result / job.error /
heartbeat / crawl.status`。`job.result` 与 GET snapshot 完全一致；轮询兜底
走 `GET session?if-none-match=<etag>` 返回 304。

## 九、验收标准

1. 粘贴 URL/文本后 1 步出确认卡片；确认后 2 个动作内进入 Optimizer，全程
   无必填字段；全站不再出现「添加岗位表单」和「创建投递记录表单」。
2. Optimizer 首屏即见 JD 画像与 Bullet/Gap 骨架；cache hit Gap Report
   <=1s，冷启动显示阶段进度而非空白。
3. 每条 Bullet 可单独采纳/拒绝/AI 润色；`diff_id` 稳定；provenance 可点击
   定位原文；invalid diff 显示硬闸门 Warning 且不可采纳。
4. 复制 Markdown 与 PDF 导出闭环可用；`#print-root` 静态、无按钮、文件
   非空；desktop 1440x900 与 mobile 390x844 均覆盖。
5. 工作台初始请求收敛为 1 个 session；session 读取 P95 <300ms；session/init
   快速返回 P95 <150ms；SSE 首事件 <=2s；bulk 200 行 P95 <500ms。
6. `pytest` 全绿且与 CI artifact 一致，不依赖真实 LLM/.env/网络；coverage
   >=85；offline 15/15、avg goal coverage >=0.8；cold <=3.3s、cached <=2.2s、
   schema retry <=4.4s；Playwright desktop+mobile 全流程通过并上传产物。

## 十、待用户拍板

- 看板五列口径：`draft/aligned/applied/interview/(offer+withdrawn)`（推荐），
  还是六列拆开。
- `POST /api/workbench/session/init` 与
  `GET /api/workspace/session/{job_id}` 并存（推荐），还是只保留其一。
- Bullet 1s 硬门：cache-first + SSE pending（推荐），还是强制 cold <=1s
  （需 fast_model 提前到 P0）。
- `add` 无来源 diff：直接拒收（推荐），还是允许 `pending_review` 人工放行。
- 拖拽是否作为验收硬门：否（推荐），E2E 走 select/键盘。
- PDF 导出：前端 `#print-root` + `window.print()`（推荐），还是后端生成。
