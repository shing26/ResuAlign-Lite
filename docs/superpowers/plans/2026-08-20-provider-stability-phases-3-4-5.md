# Provider 稳定性 Phase 3/4/5 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 superpowers:subagent-driven-development
> 按任务执行。步骤用 `- [ ]` 追踪。三个子项目文件集互不相交，可并行。

**Goal:** 完成流式 + 零 Token 熔断（Phase 3）、局部单条重试（Phase 4）、
零配置本地兜底（Phase 5），保持后端 pytest / 前端 node / E2E 全绿。

**Architecture:** 三块各自独立的薄模块，落在互不相交的文件集，由主线程负责
集成（路由注册、engine 接线、前端事件绑定）与全量验证后统一提交。

**Tech Stack:** Python 3.10+ / FastAPI / httpx / Pydantic；原生 JS ES modules +
Playwright；沿用现有 Role-Router 与 GraphExecutor，不引入新编排框架。

---

## 文件所有权矩阵（并行 Worker 互不相交）

| Sub-project | 负责文件（Worker 独占） | 主线程集成 |
| --- | --- | --- |
| Phase 3 流式+熔断 | `src/resualign/llm.py`、`src/resualign/role_router.py`、新 `tests/test_llm_streaming.py` | 管线接线（如需） |
| Phase 4 单条重试 | 新 `src/resualign/api/routers/diff_retry.py`、新 `tests/test_diff_retry_api.py`、新 `src/resualign/static/app/retry-diff.js`、新 `tests/frontend/retry-diff.test.mjs` | `api/__init__.py` 注册 + `main.js` 事件绑定 |
| Phase 5 本地兜底 | 新 `src/resualign/local_fallback.py`、新 `tests/test_local_fallback.py` | `engine.py` 无 Key 接线 |

> 约束：Worker 只改自己表格里的文件，**不得**运行 `git add/commit`，不得改
> `engine.py` / `api/__init__.py` / `main.js` / 现有前端渲染文件。所有集成与提交
> 由主线程完成，避免并行冲突。

---

## Phase 3 — 流式生成 + 15s 零 Token 熔断

**Files:** `src/resualign/llm.py`、`src/resualign/role_router.py`、
`tests/test_llm_streaming.py`（全部新建或仅有 Worker 修改）。

- [x] 在 `llm.py` 增加 `StreamConnectionError` 异常与 `OpenAIClient.stream_chat_json`
  （`stream=True` 消费 SSE chunks，逐 token yield；超过 `idle_timeout=15.0` 秒无
  token 抛 `StreamConnectionError`）。
- [x] 在 `role_router.py` 增加 `call_with_role_streaming(...)`：优先用角色节点
  流式，遇 `StreamConnectionError` 自动切默认节点重试一次，返回结构化 JSON。
- [x] 单测覆盖：正常流式聚合、超时抛错、Fallback 命中、输出 JSON 清洗复用。
- [x] 验收：`pytest tests/test_llm_streaming.py -q` 全绿。

## Phase 4 — 局部单条重试

**Files:** 新 `src/resualign/api/routers/diff_retry.py`、新
`tests/test_diff_retry_api.py`、新 `src/resualign/static/app/retry-diff.js`、
新 `tests/frontend/retry-diff.test.mjs`。

- [x] 复用现有 `POST /api/jobs/{job_id}/workbench/rewrite` 重试单条 diff，并修复
  重试成功后 invalid diff 残留造成重复卡片的问题（从 `invalid_diffs` 移除并晋升）。
- [x] 前端 diff 失败气泡渲染 `↻ 重试此条`（复用 `polish-bullet` → rewrite 端点）。
- [x] 单测：pytest 覆盖重试 invalid diff 的晋升与去重；node 测试覆盖重试按钮。
- [x] 验收：`tests/test_jd_preanalyze_rewrite.py` 与 `split-canvas.test.mjs` 全绿。

## Phase 5 — 零配置本地兜底

**Files:** 新 `src/resualign/local_fallback.py`、新 `tests/test_local_fallback.py`。

- [x] `local_fallback.py` 暴露 `local_diagnose(resume_text)`、
  `local_gap_report(resume_text, jd_text)`、`local_ats_score(resume_text, jd_profile)`
  三个确定性规则函数（正则 + 词表），任何情况不抛、不打网。
- [x] 单测覆盖空输入、英文/中文、无匹配等边界。
- [x] 验收：`pytest tests/test_local_fallback.py -q` 全绿。

---

## 集成与验收（主线程）

- [x] API job worker（`services/jobs.py`）在无 LLM 且无活动节点时调用
  `local_fallback`（标注 `fallback=local`）；analyze / diagnose 路由放开 503 门禁。
- [x] 全量：后端 `1027 passed, 7 skipped`、前端 `461 passed`、E2E `7 passed`。
