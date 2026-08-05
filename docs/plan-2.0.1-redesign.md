# ResuAlign 2.0.1 重构与重新设计联席会议纪要

**日期**: 2026-08-04
**状态**: 评审完成，待用户确认口径后进入 ticket 化
**参会部门**: 产品与用户体验部（PM: Dewey）、前端与交互设计部（UI: Nash）、
AI 策略与引擎部（AI: Lovelace）、后端与系统架构部（Architect: Dirac）、
质量与工程效能部（QA: Planck）

## 一、会议结论摘要

1. 2.0 已有看板和三栏工作台的骨架，但产品流仍是「管理后台 + 任务提交」：
   AI 结果要等用户手动点「一键生成」才出现，投递记录还要单独建。改造重点
   不是再加样式，而是把岗位库变成决策管线、把工作台变成结果工作舱。
2. 胜负手是「一键导入 + 零点击预分析」：让用户在打开岗位之前就感受到 AI
   价值，而不是先填 8 个输入框再等待。
3. SSE 只做事件通道，最终 JSON 仍是唯一事实契约；行内微调改为单 diff
   重写并引入稳定 `diff_id`，不再「重新生成」就全量重跑。
4. API 从实体 CRUD 增加 `workspace/session` 聚合与 `kanban` 编排层，crawl
   与 alignment 结果必须持久化，不能依赖内存 registry。
5. 质量护栏先修：契约 golden 入库、OpenAPI 补真实 response model、
   Playwright selector 对齐、latency 阈值收紧，再做视觉重构。

## 二、五部门现状诊断

### 产品与 UX

- 岗位库是「伪看板」：`main.js:339-352` 已调用 `renderPipelineBoard`，
  但卡片仍用 select 改状态（`main.js:480-507`），无
  `dragstart/dragover/drop/draggable`，也不显示 match 匹配度；数据模型无
  `match_score`。
- 工作台仍要求先选岗位再进入，左栏是原始 JD + 调优表单而不是结构化画像；
  `main.js:776-783` 明确写「运行一次对齐分析后生成」，AI 能力默认不可见。
- 「创建投递记录」仍独立存在（`main.js:905-940`，`workspace.py` 独立
  `applications` 表），与 ADR-0019「岗位库状态是唯一状态源、投递记录是派生
  状态」冲突。
- 一键导入不存在：单条添加是 8 字段表单，URL 解析后只是回填表单；批量只
  接受 CSV/JSON；后端标题取 JD 首行、薪资走正则，没有 LLM 结构化提取公司、
  城市、薪资。
- 零点击预分析不存在：分析只在 `POST /api/jobs/{job_id}/workbench` 时排队，
  进度靠 1s 轮询，打开工作台基本是空白等待。

### 前端与交互设计

- 「Dev Dark Theme」同质化：所有卡片共用 `--surface/--border`，没有
  backdrop-filter、Bento 或玻璃分层。
- 排版层级不足：页面 H2 20px、panel H3 16px、card-title 15px，几乎全 800
  字重，层级靠字号而非版面结构。
- 大量单行输入框挤在 `.form-grid` 里；全库没有 `keydown` 或命令面板。
- 空状态仍是死寂文案；`.skeleton` 只在路由级出现一次，`[data-wb-result]`
  在结果前整体 `hidden`。
- Diff 是 set-based `lineDiff()`，无法保留上下文顺序；Provenance 是整张卡片
  底部 blockquote，不是逐条 Bullet 旁的溯源标签。
- 打印/导出契约已破损：`index.html` 没有 `#print-root`，`printTarget` 未定义，
  现有 PDF 导出动作实际不可用。
- 移动端有 tablist 雏形但缺 `role="tab"`、方向键和焦点管理。

### AI 策略与引擎

- 全量成功才返回结果：`engine.py` 完整链路最后才返回，`jobs.py` 只有
  `succeeded` 才给 `result`，Gap Report 无法作为中间结果先行渲染。
- 进度只有粗粒度 stage（`events.js:55`），tailor 是一次完整 LLM 调用，前端
  在改写完成前看不到任何 diff。
- 行内「重新生成」实际是重新提交整个 workbench 表单，等价于全量重跑
  （`diff-editor.js:233`）。
- Provenance 硬门有缺口：`tailor.py` 用 `quote in resume_text` 取第一次出现
  位置，未处理重复引文、空白/换行归一化、重叠 span；`add` 且 `original=""`
  可绕过；`invalid_diffs` 被过滤但前端不展示。
- 单工作台默认不开 eval，防幻觉主要靠离线 benchmark；缓存命中率和 prompt
  version 管理偏脆，`jd_analysis.py:34` 的版本号是硬编码字符串。

### 后端与系统架构

- API 偏 DB 实体 CRUD：`routers/jobs.py` 同时承载 ingest、import、CRUD、
  workbench、appraisal、bulk status；没有 workspace/kanban 编排层。
- 打开工作台需多次 RTT：先拉 jobs/resumes/applications，再轮询 analysis，
  再拉主简历和 appraisal，没有会话级聚合接口。
- 工作台结果依赖 1 小时 TTL、100 条上限的内存 `JobRegistry`；library 只
  持久化 `final_draft`，不持久化生成的对齐稿/diffs。
- URL 抓取是同步阻塞路径，没有持久化 crawl task、没有事件通道、重启不可
  恢复；`_import_batches` 与 `BatchAlignStore` 也是内存态。
- SQLite 已 WAL，但 `/api/jobs/bulk-status` 是隐藏路由，循环单条更新、无
  单事务、无幂等键、无状态机约束。

### 质量与工程效能

- 契约测试是「伪保护」：`test_contract.py` 对 OpenAPI 做全等比较而非增量
  比较；78 个响应里 36 个空 schema；无 401/404/409/502/503 与
  securitySchemes；`contracts/` 尚未入库，CI checkout 后没有基线。
- `tests/test_e2e.py` 不是浏览器 E2E，只调用 CLI + httpx mock；Playwright
  在 pytest 之外，selector 已漂移（`.card.job-card` vs `.board-card`）。
- latency 阈值与 plan SLO 不一致：`expected*1.5+1s` 给 cold 5.5s，而 plan
  要求 3.3s；无 online P95、SSE 首事件、60fps 检测。
- 并发/负面场景测试不足：缺真实多 worker WAL 批量更新、E2E invalid
  provenance、SSE 时序；CI 未显式 `--cov-fail-under=85`，Playwright 产物
  不上传。

## 三、跨部门冲突与决议

| # | 冲突点 | 决议 |
| --- | --- | --- |
| 1 | 看板状态口径 | UI 五列：心仪/待对齐、已生成对齐稿、已投递、面试中、Offer/归档。后端保留现有 canonical 状态并新增 `aligned`，`offer` 与 `withdrawn` 合并进最后一列，用 `offer_at / rejected_at / notes` 区分；旧数据迁移映射写进契约。 |
| 2 | 拖拽 vs 自动化 | 拖拽是 P0 体验目标，同时保留 select/键盘兜底；Playwright 硬门走 select/键盘路径，拖拽只做非硬门 smoke。 |
| 3 | SSE vs JSON 强契约 | SSE 只推 `job.stage / job.gap_ready / tailor.diff(tentative) / job.result / job.error / heartbeat`；`job.result` 必须与 GET snapshot 完全一致，前端不得提前采纳 tentative diff。 |
| 4 | 零点击成本 | 只预跑 classifier + profile + gap，按 `(tenant, resume_hash, jd_hash, model, prompt_version)` 幂等去重；tailor/eval 保持显式触发；任务带优先级，不阻塞 full run。 |
| 5 | 聚合接口 vs 增量更新 | 首次打开工作台用 1 个 session 请求全量，之后用 SSE/轻量轮询增量 + `etag` 条件刷新；轮询不再拉全量 session。 |
| 6 | 契约 vs 快速迭代 | `contracts/openapi-v1.json` 不可变；新增路由/字段走增量契约 manifest；破坏性变更升 v2 并跨部门确认。 |
| 7 | 三栏 vs 中文 Diff 宽度 | 三栏仅高宽屏启用：`300px minmax(560px,1fr) 320px`；`<1280px` 右栏转抽屉，`<800px` 全部转 tab。 |
| 8 | 玻璃 vs 性能 | `backdrop-filter` 只用于 app shell、topbar、命令面板、抽屉；内容卡片用半透明 surface + 1px 光边，`@supports` 提供无 blur 降级；`#print-root` 全静态。 |
| 9 | 认证 vs EventSource | 原生 EventSource 不能带 Bearer header；用 `fetch` + ReadableStream 解析 SSE，或短时 cookie，禁止裸 query token。 |

## 四、2.0.1 目标与范围

### P0（本轮交付）

- 一键导入：URL / 文本 / 文件 -> `preview` -> 确认卡片 -> 入库 -> 自动预分析。
- 五列拖拽看板：卡片 `draggable`、乐观更新 + 失败回滚、match 匹配度标签、
  批量状态单事务更新。
- 三栏沉浸工作舱：JD 画像（关键词高亮）、双栏 Diff（逐条采纳/拒绝 +
  provenance 标签）、决策仪表盘（评分/雷达/幻觉/导出）。
- 零点击预分析：进入工作台/导入后自动预热 Gap Report，缓存命中直接渲染。
- SSE 事件通道 + 统一前端事件状态机，轮询保留为兜底。
- 单 diff 行内重写：`POST .../workbench/rewrite`，稳定 `diff_id`，
  instruction 限定为量化/高并发/精简三类。
- 修复打印/导出契约：`#print-root`、`printTarget`、Markdown/PDF 导出闭环。
- 视觉重构：Phase 20 token、Bento Grid、命令面板、骨架屏、glass 白名单。
- 质量护栏：契约入库与增量校验、Playwright 全流程、latency 阈值收紧。

### P1（后续）

- `fast_model / reasoning_model` 模型分层，先跑离线 benchmark 验证防幻觉
  与 gap coverage 不退化。
- 在线 P95 nightly benchmark；60fps 采样报告（不做硬门槛）。
- ContentStore 大文本外置 + 备份迁移。

## 五、改造方案

### 产品流

- `#/jobs` 改为整页五列 Kanban；组件：`BoardColumn / JobCard / MatchBadge /
  BoardToolbar / DragLayer / ImportDropzone`。
- 看板卡片直接进入 `#/workspace/:jobId`，删除岗位选择落地页和手动
  「创建投递记录」表单；投递记录由状态迁移派生/归档。
- `POST /api/jobs/preview` 返回确认卡片，用户只核对不填表；确认后
  `POST /api/jobs` 入库并自动触发预分析队列。

### 前端与交互

- 在保留 `:root / [data-theme]` 的前提下新增 Phase 20 token：
  `--glass-surface / --glass-border / --glass-blur / --match / --warning /
  --danger / --provenance`；圆角仍按 4/6/8px。
- `Cmd/Ctrl+K` 命令面板：切换岗位、触发诊断、运行工作台、导出、切换主题；
  `role="dialog"`、焦点陷阱、Esc 关闭、方向键选择。
- Diff 按 `result.diffs` 结构化渲染，每条 Bullet 下挂 `provenance_quote /
  source_span` 标签，点击在原文高亮；`invalid_diffs` 单独展示为「硬闸门
  拦截」Warning。
- 三态系统：`ready / running / done|error`；running 用 skeleton + 阶段
  stepper；所有空列表改为引导态，不再出现「运行后生成」灰框。
- 统一事件状态机替代多组 `setInterval`，为 SSE 保留替换点。

### AI 引擎

- 新增 `POST /api/jobs/{job_id}/preanalyze`：只跑 classifier + JD profile +
  gap，幂等去重，`gap_ready` 中间结果先落 registry。
- 新增 `GET /api/jobs/{job_id}/events`：SSE 事件按上文决议推送；
  `job.result` 与 GET snapshot 一致。
- 新增 `rewrite_diff()`：按 `diff_id` 单条重写，复用 strict provenance，
  instruction 白名单；禁止造数、禁止删事实证据。
- 补 prompt version 常量、`cache_hit` 字段、重复引文/空白归一化/source_span
  边界处理；`invalid_diffs` 必须落库并可见。

### 后端与架构

- 新增 `routers/workspace.py`（只读聚合）与 `routers/kanban.py`（看板读 +
  批量状态写）；`jobs/resumes/applications` 回归实体 CRUD。
- `GET /api/workspace/session/{job_id}` 一次返回 job、JD 画像、主简历、
  alignment（status/stage/score/gap/eval/diffs/draft）、appraisal、crawl、
  `meta.etag`；读取绝不触发 LLM。
- `crawl_tasks` 持久化表 + CrawlWorker 状态机：
  `queued -> fetching -> parsing -> classifying -> succeeded`，失败落
  `failed`，动态站静态抓取失败进 `fallback`；重复 URL 幂等；写回前检查
  `jd_text_updated_at`。
- `/api/kanban/bulk-status`：单事务批量 UPDATE，逐行
  `updated/not_found/conflict`，支持 `expected_statuses /
  expected_updated_at / idempotency_key`，批次上限 200。
- alignment 结果持久化到 `library_jobs` 新列或 ContentStore，不再依赖
  registry TTL；batch/crawl 重启可恢复。

### 质量与 CI

- 契约：v1 golden 不可变，新增走增量 manifest；公开响应补
  `response_model`；hidden/internal API 进入独立契约；破坏性变更升 v2。
- Playwright：URL 粘贴 -> 看板卡片 -> 三栏 Diff 采纳 -> final draft ->
  Markdown/PDF；desktop 1440x900 + mobile 390x844；上传截图/PDF/log
  artifact；fake LLM 支持 stage delay、schema retry、invalid provenance。
- Benchmark：cold <=3.3s、cached <=2.2s、schema retry <=4.4s；call count
  保持 4/3/2/4；offline 15/15、goal coverage 平均 >=0.8；online P95 放
  nightly。
- CI：pytest + 显式 coverage>=85 + node check + contract additive；再跑
  benchmark；最后 Playwright；nightly 跑 online P95 与帧率采样。

## 六、API / 数据契约草案

```json
GET /api/workspace/session/{job_id}
{
  "job": {},
  "jd": {},
  "resume": {},
  "alignment": {
    "status": "queued|running|gap_ready|succeeded|failed|canceled",
    "stage": "",
    "generated_at": null,
    "score": null,
    "gap_report": null,
    "eval_score": null,
    "diffs": [],
    "invalid_diffs": [],
    "draft": null
  },
  "appraisal": {},
  "crawl": {"crawl_id": "", "status": "", "stage": "", "error": null},
  "meta": {"etag": "", "updated_at": ""}
}
```

新增/演进接口：

- `POST /api/jobs/preview`、`GET /api/jobs/preview/{preview_id}`
- `POST /api/jobs/{job_id}/preanalyze`
- `GET /api/jobs/{job_id}/events`（SSE）
- `POST /api/kanban/bulk-status`
- `POST /api/jobs/{job_id}/workbench/rewrite`
- `GET /api/jobs?board=1`（返回 `status_canonical + final_draft +
  match_score + analysis_ready`）

## 七、分阶段实施顺序

1. **Phase 0 护栏修复**：契约基线入库、OpenAPI response model、`#print-root`
   与 `printTarget`、Playwright selector 对齐、latency 阈值收紧。
2. **Phase 1 数据与 API**：状态模型 + `aligned`、crawl_tasks、kanban 单事务、
   session 聚合、preanalyze。
3. **Phase 2 前端主流程**：一键导入、五列看板、三栏工作舱、统一事件状态机、
   骨架屏。
4. **Phase 3 AI 流式**：SSE、gap_ready 中间结果、单 diff 重写、
   invalid_diffs 可见。
5. **Phase 4 视觉重构**：Phase 20 token、Bento、glass 白名单、命令面板。
6. **Phase 5 质量收口**：E2E 全流程、并发/负向测试、nightly benchmark。

每个 Phase 落地前先出 spec + tickets，按「contract-first / tdd / 实现后
code-review」执行，保持 `resualign.api:app` 入口和现有 432 个 pytest 全绿。

## 八、验收标准

1. 岗位库打开即见五列看板；卡片可拖拽且非法迁移 1s 内回滚；卡片显示 match
   匹配度标签。
2. 看板到三栏工作舱 <=2 次点击；缓存命中时 Gap Report 首屏 <=1s，冷启动
   显示预分析进度而非空白。
3. 一键导入：粘贴 URL/文本后 1 步出确认卡片，保存不需要填写必填字段。
4. 每条 diff 可单独采纳/拒绝，provenance 可点击定位原文；幻觉检查结果始终
   可见；导出 PDF/Markdown 闭环。
5. 打开工作台初始请求从 4+ 降为 1 个 session；session 读取 P95 <300ms；
   bulk 200 行 P95 <500ms；SSE 首事件 <=2s。
6. `pytest` 全绿且不依赖真实 LLM/.env/网络；coverage >=85；offline 15/15；
   latency 阈值通过；Playwright desktop+mobile 通过并上传 artifact。

## 九、待用户拍板

- 看板状态口径：五列合并 Offer/归档，还是拆成六列。
- SSE 是否作为 P0 硬门（建议 P0 事件通道 + 轮询兜底，首事件 <=2s）。
- 拖拽是否作为验收硬门（建议否，select/键盘为主）。
- 一键导入是否启用 LLM 结构化提取公司/城市/薪资（建议启用，失败降级为文本
  确认）。
- `fast/reasoning` 模型分层是否本轮 P1 开始。
- PDF 导出采用前端 HTML print 还是后端生成（建议前端 print + `#print-root`）。
