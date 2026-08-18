# ResuAlign-Lite 重构地图（2026-08-14）

> 目标：在保持现有质量门禁（pytest、node:test、benchmark、Playwright smoke）
> 与“铁律：不捏造事实”的前提下，把当前单体热点拆成可维护的边界。

## 0. 基线快照

- 分支：`codex/ux-gap-fixes`，HEAD `1a46d54`。
- 工作区：暂存区有 `.reasonix/` 临时文件、`test.html`、`designs/v2|v3`、`docs/handoff`、
  `start.ps1`（端口改 8011）；工作区另有 9 个 UX 修复文件未提交。
- 本地验证：
  - `node --test tests/frontend/*.test.mjs tests/frontend/dom/*.test.mjs`：402 pass。
  - `pytest -n 4 tests/ --ignore=tests/e2e`：838 pass / 2 fail。
  - `ruff check` 与前端 `imports-check.mjs`：通过。
- 两个失败都与未提交改动有关：
  - `tests/test_contract.py:179`：`BatchAlignRequest` 新增 `run_eval`，OpenAPI 快照未重新生成。
  - `tests/test_engine.py:58`：`engine.run()` 为 JD 分析新建 90s 客户端，旧断言只预期诊断 120s 客户端。
- 规模热点：
  - 后端 `src/resualign/` 约 15,020 行、512 个函数。
  - 前端 `static/app/` 约 8,000 行，`styles.css` 约 220KB。
  - pytest 收集 840 个用例。

## 1. 现状地图

### 核心引擎

- `engine.py` 保持 I/O-free，诊断、JD 画像 + 差距分析、改写、可选评估串成 pipeline。
- `llm.py` 统一 OpenAI/DeepSeek/Ollama，JSON schema 校验重试。
- `tailor.py` 强制 provenance，非法 diff 进 `invalid_diffs`。

### API 层

- `api/__init__.py` 569 行，同时承担日志初始化、lifespan、中间件、路由注册和
  “re-export hub”：routers/services 用 `import resualign.api as api_module` 访问依赖。
- `api/state.py` 是进程级单例集合：registry、stores、cache、rate limiter、session store。
- `api/services/workbench.py` 803 行，会话 pipeline、session store、业务聚合都在一起。

### 数据层

- `store_base.py` 提供 SQLite 基类 + per-store migration journal。
- 数据域分散在 `jobs.py`、`job_library.py`、`workspace.py`、`settings_store.py`、
  `llm_nodes.py`、`cache.py`、`content_store.py`。
- `ContentStore` 已有实现和测试，但生产路径未接线（ADR 中列为 P1）。
- `ApplicationStore` 与 `/api/applications` 仍是休眠代码，ADR-0027 已决定后续清理。

### 前端

- `main.js` 2,801 行：路由、command palette、action registry、视图挂载混在一起。
- `format.js` 2,504 行：格式化、JD 解析、看板、投递闭环、markdown、diff 混在一起。
- `split-canvas.js` 1,379 行：session 加载、SSE/轮询、三栏渲染、Live Sheet 混在一起。
- `styles.css` 220KB：v1/v2/v3 多层覆盖并存，ADR-0026 允许清理旧 selector。

### 文档与 CI

- ADR 体系完整，最近决策是 ADR-0025（移除 appraisal）与 ADR-0027（Job 唯一事实源）。
- 但 `docs/roadmap-saas-workbench.md`、`docs/spec-2.0-*`、`docs/plan-2.0-*` 仍大量引用
  appraisal / Application，文档与当前实现不一致。
- CI 三阶段：unit-contract → benchmark gate → Playwright smoke。

## 2. 重构目标

1. 文件级单体拆到职责边界：store、service、domain、view。
2. 移除 `api_module` re-export hub 与进程级单例的强耦合。
3. 按 ADR-0025 / ADR-0027 清理休眠代码和过期文档。
4. 统一 SQLite 迁移和 blob 存储策略，避免每个 store 自建一套。
5. 前端按路由/视图拆分 JS 与 CSS，保留 DOM/data-action/hash 契约。
6. 每次重构只做“纯结构搬移”或“单一行为变更”，不混在一起。

## 3. 分阶段路线

### Phase 0：稳定工作区与基线（先做）

- 把 `.reasonix/`、`test.html` 等临时产物移出提交；如 `start.ps1` 端口改动是本地习惯，
  单独说明或恢复默认。
- 为未提交 UX 修复补齐测试并提交：
  - 更新 OpenAPI 快照（`contracts/openapi-current.json`）。
  - 更新 `test_engine_tailoring_uses_extended_timeout` 以覆盖 JD 90s 客户端行为。
  - 为 `BatchAlignRequest.run_eval` 的 settings 默认值回退补后端测试。
- 验收：`pytest -n auto`、`ruff`、node 测试、benchmark、Playwright smoke 全绿。

### Phase 1：后端 store/domain 拆分

- `job_library.py`（2,071 行）拆为：
  - `domain/status_lifecycle.py`：状态机、timeline、canonical 规则。
  - `stores/library_jobs.py`：JobLibraryStore 主体。
  - `stores/crawl_tasks.py`：CrawlTaskStore。
- `crawler.py`（1,343 行）拆为：
  - `crawler/client.py`：HTTP/Playwright 抓取。
  - `crawler/site_handlers.py`：Moka、飞书、LinkedIn、BOSS 直聘、generic。
  - `crawler/security.py`：SSRF 防护、限流、UA、代理。
- `workspace.py`（932 行）拆为 `stores/users.py`、`stores/master_resumes.py`，
  并随 ADR-0027 清理 `ApplicationStore`。
- 验收：全部 pytest 保持绿，SQLite 迁移结果不变，无行为 diff。

### Phase 2：API 解耦

- 新增 `api/container.py` 或 `api/deps.py` 的工厂/依赖注入，替代 `state.py` 全局单例。
- `api/__init__.py` 只保留 app 装配；routers/services 从 container 取依赖。
- 保留 `tests/test_contract.py` 与 `tests/test_api_split.py` 的契约，OpenAPI 变化须显式更新。
- 验收：删除 `api_module._registry = ...` 这类测试替换模式后可测试性不降。

### Phase 3：前端模块拆分

- `main.js` 拆为 `router.js`、`actions.js`、`command-panel.js`、`view-mount.js`。
- `format.js` 拆为 `format/*.js`：datetime/salary/esc、job/board/delivery、diff、markdown。
- `split-canvas.js` 拆为 `session-loader.js`、`pipeline-polling.js`、`diff-canvas.js`、
  `live-sheet.js`、`workbench-render.js`。
- `styles.css` 按 tokens / base / shell / views 拆分，删除 v1/v2 死 selector。
- 验收：`node --test` 402+ 全绿；Playwright smoke 的五视图截图与 v3 preview 对齐；
  DOM/data-action/hash 路由不变。

### Phase 4：数据层统一

- 决定 `ContentStore` 去留：若大文本 blob 是 P1，则接进 job/resume 保存路径并做迁移；
  否则明确移除，避免“有实现未接线”的中间态。
- 统一 store migration：当前 `jobs.py`、`job_library.py`、`workspace.py`、`settings_store.py`、
  `llm_nodes.py` 各自持有迁移表，重构后只保留一个迁移编排入口。
- 按 ADR-0027 移除 `applications` 表、`ApplicationStore`、`/api/applications` 路由及
  相关 contract 测试，并更新文档。
- 验收：老库升级路径有迁移测试；`test_migrations_convergence.py` 绿。

### Phase 5：文档与契约收口

- 更新 `docs/roadmap-saas-workbench.md`、`docs/spec-2.0-*`、`docs/plan-2.0-*`，
  删除或标注被 ADR-0025 / ADR-0027 取代的内容。
- 新增一张“模块职责 + 唯一事实源”地图，避免 roadmap、spec、ADR 三处漂移。
- 验收：仓库内对 appraisal / application 作为活跃功能的引用为零。

## 4. 风险与控制

- OpenAPI snapshot 是硬契约：任何 schema/字段变化都要先改快照再提交。
- 前端测试依赖具体 DOM/selector：拆分时保持 `data-action`、`data-form`、hash 路由不变。
- 当前工作区有未提交改动：重构前先提交或 stash，避免把行为修复混进结构搬移。
- SQLite 是本地真实数据：所有表/迁移改动需要旧库升级测试，禁止直接重建表。
- `crawler.py` 涉及 SSRF/限流，安全逻辑与 site handler 拆分后仍需保留现有攻击面测试。

## 5. 建议的提交序列

1. PR A：临时文件清理 + 两个失败测试修复 + OpenAPI 快照更新。
2. PR B：后端 store/domain 纯搬移（无行为变化）。
3. PR C：前端 JS/CSS 纯拆分（无行为变化）。
4. PR D：移除 dormant Application/appraisal 相关代码和过期文档。
5. PR E：API container/依赖注入改造。
6. PR F：数据层迁移统一 + ContentStore 接线或移除。
