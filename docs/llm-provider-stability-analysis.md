# LLM Provider 稳定性：成因剖析与落地方案

_日期: 2026-08-20 · 状态: 已审阅并已实施 · 相关: ADR-0030, ADR-0032_

## 一、结论先行

ResuAlign 已经具备角色化 LLM 拆分（ADR-0030）、分级超时、角色节点绑定与
一键预设等大部分"架构底座"。真正导致"切 Provider 不稳定"的剩余根因集中在
三点：

1. **editor 角色仍是"整篇重写"的单体大 Prompt / 大输出**（`engine.py` +
   `tailor.py`），单次生成 20-40s，是超时与队列断连的最主要来源。
2. **LLM 客户端是同步阻塞、非流式**（`llm.py`），前端只能干等，且断连后
   无局部自愈。
3. **JSON 清洗器只覆盖了"代码围栏 + 取首尾括号"的浅层场景**，对"前置杂质文本 +
   截断未闭合括号"没有兜底，小模型格式坍塌时直接重试到失败。

对照成熟开源求职 Copilot 的做法，缺口清单见文末，其中部分项（节点连通性测试、
模型分级路由）**当前代码已实现**，无需重复建设。

## 二、成因剖析（锚定具体代码）

### 根因 1：单体大 Prompt / 大输出导致 HTTP 阻塞与队列断连

- `engine.py` 在 editor 节点调用 `tailor_resume(...)` 时，传入 `resume_text`
  全文 + `gap_report_text`（含 `jd_context`，上限 `MAX_JD_CONTEXT_CHARS=6000`）。
- `tailor.py` 的 `TAILOR_PROMPT` 要求模型同时输出 `sections`（整份重写正文）与
  最多 15 条 `diffs`。即便增量改写，输出包仍可能很长。
- `llm.py` 的 `OpenAIClient` 使用同步 `httpx.Client`（`stream=False`）一次性
  `POST /chat/completions`，在前端看来就是一段 20-40s 的"转圈"。
- DeepSeek 晚间高峰或本地 Ollama 排队时，长连接内若首字节迟迟不来，网关层
  TCP 静默断开 / Read Timeout，整次请求直接丢弃。

### 根因 2：小模型指令遵循上限（Cognitive Overload）

- 当 editor 换成 NVIDIA 免费 8B 或本地小模型时，`TAILOR_PROMPT` 的 14 条规则 +
  Gap Report + 长 `jd_context` 叠加，远超 8B 模型的稳定遵循区间。
- 结果表现为三种格式坍塌：输出闲散文案、Markdown 未闭合、JSON 字段缺失。
  `tailor.py` 内 14 条规则大多是在"如何改写"的业务规则，不是行为约束，进一步
  加重小模型负担。

### 根因 3：清洗器只覆盖浅层

`llm.py::_parse_json_object` 目前只做三件事：

1. 剥掉 ```` ``` ```` 代码围栏；
2. `json.loads` 失败后用 `text[start:end+1]` 取首尾 `{...}`，其中 `end` 用
   `rfind("}")`，**没有括号配平**，遇到截断/字符串内含 `}` 会切错；
3. 没有前置杂质文本剥离，也没有"未闭合括号补齐"。

小模型输出 `Here is the revised resume: {…` 被截断时，无法恢复，只能重试。

### 根因 4：无中心化零 Token 熔断

角色级超时（`role_router.py` 的 15/20/40/30s）确实存在，但它是"整包超时"，
不是"首 Token 空转熔断"；建立连接后若 25s 内一个 Token 都不吐，前端仍然只能
等到超时或报错，没有"换备用节点重试"的局部自愈。

## 三、现状 vs. 缺口清单

| 改造项 | 现状 | 结论 |
| --- | --- | --- |
| 经历点级并发改写（Bullet Map-Reduce） | `tailor.py` 有 `rewrite_bullet` 助手，但主链路仍是整篇 `tailor_resume` | **缺口** |
| 全链路 SSE 流式 + 15s 零 Token 熔断 | 客户端同步阻塞，非流式 | **缺口** |
| 模型分级路由（Free vs Pro） | `llm_role_assignments` + 预设 + `is_parallel_safe` 已实现 | **已具备**（可补文档化默认） |
| 健壮输出清洗器 | `_parse_json_object` 只覆盖浅层 | **缺口**（本轮落地） |
| 一键连通性测试 | `POST /api/llm/nodes/{id}/test` + 设置页按钮已实现 | **已具备** |
| 局部单条重试 | 只有整工作台重跑 | **缺口** |
| 面试防深挖 CheatSheet | `interviewCheatSheetHtml` 已渲染，但 `topic` 为死代码（评审 P3） | **部分** |
| 零配置本地兜底 | 未配置 Key 时 pipeline 走空客户端直接失败 | **缺口** |

## 四、分阶段落地方案

每个阶段保持可运行、可测试、可交付，且都有独立验收标准。

### Phase 1 — 输出清洗器加固（本轮落地）

- 重写 `llm.py::_parse_json_object`：
  - 剥离 BOM / 代码围栏 / 前置杂质文本；
  - 括号配平扫描提取真正的 JSON 对象（跳过字符串内的 `{}`）；
  - 截断时最佳努力补齐未闭合括号 + 清除尾随逗号；
  - 全失败才抛错（保持原重试语义）。
- 新增 `tests/test_llm_sanitizer.py` 覆盖：前置杂质、`json`/`markdown` 围栏、
  尾随文本、字符串内 `}`、截断补齐、尾随逗号、纯垃圾抛错。

### Phase 2 — Bullet 级并发改写（Map-Reduce Editor）

- **状态：本轮已落地**。`tailor.py::tailor_resume_map_reduce` 把简历切分为
  原子经历点 → 按缺口挑选目标 → 并发 `rewrite_bullet` → 确定性重组
  `sections` + `diffs`。并发上限 `min(4, n)`，本地 Ollama 经
  `is_parallel_safe("editor")` 关闭并发串行执行。
- 失败单条降级进 `invalid_diffs`（Phase 4 "重试此条" 的钩子），不会拖垮其余
  建议；全部目标失败则回退整篇 `tailor_resume`，保留角色级 Fallback。
- 引擎角色路径对 `fine`/`medium` 默认走 map-reduce，`coarse` 保留整篇；
  可用 `RESUALIGN_BULLET_EDITOR=0` 关闭。
- 验收：pytest（1013 passed）、前端 node（460）、7 条 E2E 全绿。

### Phase 3 — 流式生成 + 零 Token 熔断

- `OpenAIClient` 增加 `stream=True` 路径，首个 chunk 经现有 progress/SSE sink
  推送前端批注气泡；15s 内零 Token 触发节点 Fallback（复用
  `call_with_role` 的默认节点回退）。
- 验收：前端 500ms 内看到首字符，断连时换备用节点，不再无限等待。
- **本轮落地**：`llm.py::OpenAIClient.stream_chat_json(...)`（SSE 增量聚合 +
  `idle_timeout=15.0` 零 Token 熔断）+ `role_router.py::call_with_role_streaming`
  （角色节点失败自动切默认节点）。测试 `tests/test_llm_streaming.py` 全绿；
  editor 全链路 SSE 化保留为后续可选增强。

### Phase 4 — 局部单条重试（Granular Retry）

- 在 diff 建议气泡内为失败条目增加 `⚠️ 生成超时 [↻ 重试此条]`，仅重试该
  `rewrite_bullet`，其余建议与正文不受影响。
- 验收：前端 node 测试 + E2E 覆盖重试后仅替换该条。
- **本轮落地**：复用 `POST /api/jobs/{job_id}/workbench/rewrite` 为单条重试；
  修复重试成功后 invalid diff 残留重复卡片缺陷；失败 diff 渲染 `↻ 重试此条`。
  测试 `tests/test_jd_preanalyze_rewrite.py` 与前端 `split-canvas.test.mjs` 全绿。

### Phase 5 — 零配置本地兜底

- 未配置任何云端 Key / 本地节点时，pipeline 自动切入确定性规则引擎 + 内置正则
  （基础打分、缺口清单、关键词归属），保证开箱即用不白屏。
- 验收：无 API Key 状态下工作台仍返回可用结果并在 UI 标注 `fallback=local`。
- **本轮落地**：新增 `local_fallback.py`；API job worker 在无 LLM 且无活动节点
  时产出 `Report(fallback="local")`；analyze / diagnose 路由放开 503 硬门禁。
  测试 `tests/test_local_fallback.py` 全绿。

## 五、验收总标准

1. 同一份 fixture 下 DeepSeek / OpenRouter / Ollama / NVIDIA 四档 Provider 输出
   均可被清洗器稳定解析（sanitizer 单测覆盖每档的典型坍塌形态）。
2. editor 单次输出包显著减小，整条对齐链路对慢节点有独立兜底路径。
3. 后端 pytest、前端 node 测试、7 条 E2E 全程绿。
4. 未配置 Key 时产品仍可用（零配置本地兜底）。
