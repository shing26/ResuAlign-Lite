# ResuAlign-Lite 优化审查报告

_审查日期：2026-08-18 · 基于静态分析（结构、复杂度、重复、测试覆盖、依赖、并发）_

## 总体评价

项目质量基线**明显高于平均水平**：

- 19,245 行源码 / 25,298 行测试，测试量 > 代码量，80+ 测试文件几乎覆盖所有模块（仅 `api/deps` 无独立测试）。
- 依赖零冗余（9 个运行时依赖全部被实际使用）。
- SQLite 并发设计有意识：`WAL` + `busy_timeout=5000` + 按请求创建连接。
- 无 `TODO/FIXME/HACK` 残留，代码整洁。
- 已有契约测试（`test_contract.py`、`test_migrations_convergence.py`）、崩溃恢复测试、并发测试，工程成熟度很高。

**结论**：这不是"代码写得很烂要返工"的项目，而是"已经很好、但有几个规模性痛点会在继续增长时拖慢你"的项目。下面按 **影响 × 改动成本** 排序。

---

## P0 — 高影响、值得优先处理

### 1. `job_library.py` 是 2956 行的"上帝模块"
- 71 个函数/方法混在一个文件：状态生命周期工具函数（模块级）+ `JobLibraryStore` + `CrawlTaskStore` 三个类，职责边界模糊。
- 单个 `update_job` 方法 **449 行**，承担字段归一化、状态生命周期、快照、提醒、缓存失效等至少 6 类职责。
- 平均 42 LOC/函数（是 crawler/workspace 的近 2 倍）。

**建议**：
- 拆为 `job_library/`（包）：`status_lifecycle.py`（现有模块级函数）、`store.py`（`JobLibraryStore`）、`crawl_store.py`（`CrawlTaskStore`）、`models.py`（行映射）。
- `update_job` 拆成：`_normalize_fields` → `_apply_status_lifecycle` → `_maybe_snapshot` → `_invalidate_match_cache`，每个 60–80 行。
- 收益：可测试性↑、合并冲突↓、新人上手成本↓。

### 2. 巨型闭包回调：`on_crawl_stage` (263 行) / `on_stage` (231 行)
- 这两个进度回调是嵌在 `workbench.py` / `jobs.py` 方法体内的闭包，包含状态机推进、DB 写入、SSE 格式化、错误分支。
- 问题：无法独立单测、难以复用（刷新流程 `job_refresh.py` 里有几乎一样的 `complete_crawl` 129 行）、重构风险高。

**建议**：
- 抽成顶层 `ProgressSink` 类（或独立模块 `progress_sink.py`），注入到 crawl/align 服务。
- `job_refresh.py` 的 `complete_crawl` 与 `workbench.py` 的 `on_crawl_stage` 实质是同一状态机的两个入口 → 合并为统一 `CrawlStateMachine`。

---

## P1 — 中影响、建议规划处理

### 3. LLM 抽象有两套实现路径
- `llm.py` 中 `LLMClient`(ABC) 的 `chat_json`/`chat_structured` 在 `OpenAIClient` 被**各自重写**（行 203、282），且 `_chat_structured_provider` 与 `_chat_structured_json_mode` 又各 100+ 行。
- 重试逻辑是手写 `for attempt in range(...)` 循环（行 222–269）。

**建议**：
- 重试统一为装饰器或 `tenacity`；provider 差异收敛到 `_provider_extras` + 一个 `postprocess` 钩子，消除 2 套 chat 实现。
- 收益：新增 provider（如 qwen/glm）时只改一处，而非复制 80 行。

### 4. 命名撞车：`_row_to_job` 语义不同却同名
- `jobs.py:483` 映射 **AnalysisJob**（异步分析任务）。
- `job_library.py:2301` 映射 **Job Library 岗位记录**（dict）。
- 两者同名但返回类型/表完全不同，易误导。

**建议**：重命名为 `_row_to_analysis_job` 与 `_row_to_library_job`。低风险但消除歧义。

### 5. settings 校验手写，与 pydantic 能力重叠
- `settings_store.py:_validate_settings`（113 行）手写了一整套 provider/类型/互校验。
- 项目已依赖 `pydantic-settings`，但 settings 持久化走的是裸 dict + 手写校验。

**建议**：将 settings 收敛到一个 Pydantic `SettingsModel`，`_validate_settings` 退化为 `model_validate` 的薄封装。长期收益是校验逻辑与 OpenAPI schema 自动同步。

---

## P2 — 低影响、可顺手做

### 6. 端点/schema 规模大但无 API 版本前缀
- 79 个端点、53 个 Pydantic model，全部挂在 `/api/*` 下无版本（`/api/v1/...`）。
- 当前个人模式为主无碍，但 MCP server 已暴露工具，未来多客户端时破坏性变更风险高。

**建议**：在路由层加 `/api/v1` 前缀（FastAPI `APIRouter(prefix=...)`），属一次性机械改动。

### 7. `crawler.py` 1483 行可拆站点处理器
- 目前 `SiteHandler` 概念在 CONTEXT 里有定义，但实现集中在单文件，新增站点要改大文件。
- 建议：站点处理器按 `crawler/handlers/<site>.py` 插件化（已有 `shixiseng` 特定逻辑可先行抽出）。

### 8. 测试运行时间可能偏长
- 25k 行测试含 E2E/Playwright/真实 LLM 基准分支。CI 用 `pytest-xdist`，但 SQLite 文件锁可能在并行下成为瓶颈。
- 建议：确认 `pytest-xdist` worker 是否各自用独立 `tmp_path` 数据库（避免 WAL 争用导致偶发失败）。

---

## 不必动的地方（已做得好，别过度优化）

- **依赖管理**：`requirements.txt` 与 `pyproject.toml` 双源同步、零未用依赖，保持。
- **并发模型**：WAL + busy_timeout + 连接隔离已规范，不要盲目上 async SQLite 驱动（引入新复杂度）。
- **契约测试**：`test_contract.py` / migration convergence 是护城河，重构时务必保留并扩展。
- **测试覆盖率 85% 门槛**：高价值，重构大模块时靠它兜底。

---

## 推荐行动顺序

| 步骤 | 动作 | 成本 | 风险 |
|------|------|------|------|
| 1 | 拆 `job_library.py` 为包 + 拆 `update_job` | 中 | 中（靠契约测试兜底） |
| 2 | 抽 `ProgressSink` + 合并 crawl 状态机 | 中 | 中 |
| 3 | LLM 重试收敛 + 消除双 chat 实现 | 中 | 低 |
| 4 | 重命名 `_row_to_job` 双义 | 低 | 低 |
| 5 | settings 收敛 Pydantic Model | 中 | 低 |
| 6 | `/api/v1` 前缀 | 低 | 低 |

> 每一步都应在保留现有契约测试的前提下进行；建议每步后跑 `python -m pytest tests/ -q` 确认绿灯。
