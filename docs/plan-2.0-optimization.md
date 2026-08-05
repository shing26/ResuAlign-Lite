# ResuAlign 2.0 优化改造方案（跨部门联席会议纪要）

**日期**: 2026-08-04
**状态**: 已评审，待确认 SLO 与交付范围
**参会**: 产品与用户体验部（PM、UX Research）、后端与系统架构部（Backend
Architect、Software Architect、Infrastructure）、前端与交互设计部（Frontend
Developer、UI Designer）、AI 策略与引擎部（AI Engineer、Prompt Engineer）、
质量与工程效能部（DevOps、Test Analysis、Performance Benchmark）

## 一、三大碰撞点共识

1. 前端技术栈：方案 A。维持无构建 Vanilla ESM，组件化用 CSS Variables +
   可选 Web Components（Light DOM），不引入 React/Vue/Tauri；Tauri 放 P2
   spike，3.0 再评估。
2. 流式输出：JSON 是唯一事实契约；SSE 只推 stage/result 进度事件，不做
   token 流式；轮询保留作兜底。
3. 改写幅度：零幻觉 + provenance 硬闸门；保留 fine/medium/coarse，默认
   medium，批量对齐默认 fine，coarse 后置。

## 二、2.0 目标

从「简历改写工具」升级为「求职决策控制台」：统一投递追踪、结果分层展示、
批量对齐、评估升级、架构解耦、性能与质量护栏。

## 三、P0 交付（重构地基 + 核心功能）

### 产品与 UX

- 统一投递追踪看板：岗位库五态为唯一状态源，投递记录降为详情；新增投递
  日期、备注、下一步、Offer/拒绝时间；列表支持批量改状态。
- 工作台结果三级展开：总分 → Diff 逐条采纳 → JD 画像/Gap/Eval/provenance；
  补单条替换与重生成。

### 后端与架构

- 拆分 `api.py`：`api/__init__.py` + `routers/` + `services/` + `schemas.py` +
  `deps.py`；lifespan 注入 store；保留 `resualign.api:app` 入口，路由前缀与
  响应字段零漂移。
- 契约先行：先补 route 快照、OpenAPI 指纹、golden response 契约测试，再动
  拆分。
- SQLite 统一连接层：WAL、`busy_timeout=5000`、`foreign_keys`、
  `synchronous=NORMAL`、线程本地连接；`jobs.py` 复用 `store_base`；默认
  `workers=1`，任务状态 durable claim。
- 多租户边界：复用 `tenant_id` 作为 `workspace_id`，所有查询强制 scope；
  2.0 只做数据/API 隔离，UI 仍以个人模式交付。

### AI 引擎

- Schema Registry + `chat_structured`：Pydantic `model_json_schema`；供应商支持
  Structured Outputs 时传 `response_format`，否则 JSON mode + schema 校验重试；
  禁止 `raw_decode` 兜底。
- Provenance 硬校验：diff 增加 `provenance_quote`/`source_span`，字符级锚定原
  简历；evaluator 强制返回 `hallucination` 与 `gap_coverage`。
- 内容哈希缓存：diagnosis、JD profile+gaps、classifier；key 含
  tenant/model/prompt version；tailor 不默认缓存。

### 前端

- 主题化 token + 暗亮模式（`[data-theme]`）；苹果极简视觉，圆角 4/6/8px，
  保留卡片体系与 reduced-motion。
- 三栏工作台仅宽屏（`300px / 1fr / 320px`），≤1100px 右栏抽屉，≤800px 左右
  折叠为 tab；`data-*`/`aria-*`/`#app` 契约冻结。
- 事件层：`/api/jobs/{id}/events`（SSE）或 P0 保持轮询；前端状态机支持
  重连/取消。

### 质量与 CI

- 冻结 358 测试基线；新增 contract/golden、假 LLM 保护清单、tenancy
  isolation、kanban API 测试。
- `latency_benchmark.py` 入 CI：cold=3 / cached=2 calls，wallclock 阈值
  `expected*1.5+1s`。
- benchmark 9 → 15 用例：新增反幻觉 adversarial、缓存命中、批量 5 JD、
  schema retry。
- Playwright phase-20 关键路径：导入简历 → 抓 JD → 调优 → 导出；桌面 + 移动。

## 四、P1 交付（体验与稳定性）

- 批量对齐 2-5 个 JD：队列、配额、取消、幂等；输出「评估结论/核心缺口/下一步」
  矩阵；默认 fine。
- Appraisal 升级：通勤成本、生活成本折算、手动权重、四维横条 + 结论；雷达图
  仅作轻量 SVG 增强。
- 爬虫加固：per-host 限速、指数退避、UA 池、可选代理、Playwright Headless
  opt-in、URL 脱敏、失败降级。
- 可观测：请求 ID、结构化日志、慢查询、缓存命中率。
- 大文本外置：`data/blobs` sha256 去重、0700、TTL 清理、备份兼容迁移。
- ESM 拆分：`static/app/{main,diff-editor,appraisal-panel,theme,events}.js`；
  `node --check` 覆盖全量。
- 模型分层：`fast_model`/`reasoning_model`；诊断/分类/JD 分析走快模型，
  tailor/evaluator 走强模型。

## 五、P2 交付（后置/探索）

- Web Components 化（Light DOM `ra-*`）。
- Tauri shell spike（3.0 再评估）。
- 完整结果缓存命中：0 次 LLM 调用，P95 ≤ 500ms。
- 数据导出/备份、analytics 周报机会分。
- 三档 granularity 专用 benchmark；SSE nightly 回归。

## 六、性能 SLO（草案）

| 指标 | 目标 |
| --- | --- |
| 离线模拟 cold | ≤ 3.3s（1s/call） |
| 离线模拟 cached diagnosis | ≤ 2.2s |
| 在线 P95 cold | ≤ 12s |
| 在线 P95 cached | ≤ 8s |
| 完整结果缓存命中 | ≤ 500ms |
| SSE 首事件 | ≤ 2s |
| 批量 5 JD | 独立队列，受并发/配额限制 |

## 七、实施顺序（Ticket 化建议）

1. 契约冻结：contract/golden 测试 + CI 三段式。
2. 后端拆包 + SQLite WAL + durable job。
3. AI schema/provenance/cache。
4. 投递看板 + 结果三级展开。
5. 前端主题化/三栏/事件层。
6. 批量对齐 + appraisal 升级。
7. 爬虫加固 + 可观测。
8. Phase-20 Playwright + benchmark 扩展。
9. P2 spikes（Tauri/Web Components/analytics）。

## 八、待用户确认

- 投递状态：五态 vs 六态统一口径与旧数据映射。
- 看板：首版拖拽还是状态选择。
- SSE：P0 上还是 P1。
- 强模型选型与 evaluator 是否常开。
- 在线基准频率（建议每周 1 次 + 发布前全量）。
- 多租户：2.0 仅数据层隔离。
- 爬虫代理/白名单与合规边界。

## 九、主要风险

- api.py 拆分导致单例注入与测试 seam 变化。
- UI 重设计导致 selector 漂移。
- Structured Outputs 供应商兼容不一致。
- WAL 在 Windows/Docker bind mount 下仍可能锁。
- 批量对齐放大 LLM 成本。
- 爬虫站点 DOM 变化与反爬。
