# ADR-0032: LLM Provider 稳定性与流式降级

**状态**: 已接受
**日期**: 2026-08-20
**前置**: ADR-0030（角色化 LLM 拆分）

## Context

在切到不同 Provider（DeepSeek / OpenRouter / 本地 Ollama / NVIDIA 免费 8B）时，
用户反馈"对齐时间过长、AI 改写缓慢、任务经常完不成"。代码审阅与成因剖析
（见 `docs/llm-provider-stability-analysis.md`）确认三个剩余根因：

1. editor 仍是整篇重写的大 Prompt / 大输出，单次 20-40s，是超时与断连主因；
2. LLM 客户端同步阻塞、非流式，前端干等、断连无局部自愈；
3. JSON 清洗器只覆盖浅层，小模型格式坍塌（前置杂质、截断、未闭合括号）无兜底。

## Decision

以"化整为零 + 流式 + 分级 + 容错兜底"四条主线推进，分五阶段落地
（详见分析文档第四节），每阶段独立可测、可交付：

| Phase | 内容 | 本轮状态 |
| --- | --- | --- |
| 1 | 输出清洗器加固（`_parse_json_object` 重写 + 单测） | 本轮落地 |
| 2 | Bullet 级并发改写（Map-Reduce Editor），失败单条可独立重试 | 本轮落地 |
| 3 | 流式生成 + 15s 零 Token 熔断 + 备用节点回退 | 本轮落地 |
| 4 | 局部单条重试（diff 气泡内 `↻ 重试此条`） | 本轮落地 |
| 5 | 零配置本地兜底（未配 Key 时走确定性规则） | 本轮落地 |

## 本轮补齐（Phase 3/4/5）

- **Phase 3**：`llm.py` 新增 `StreamConnectionError` 与
  `OpenAIClient.stream_chat_json(...)`（`stream=True` 消费 SSE，增量聚合 JSON，
  复用 `_parse_json_object` 与 `_observe_llm_call`）；`role_router.py` 新增
  `call_with_role_streaming(...)`，角色节点 `StreamConnectionError`/
  `LLMResponseError` 时自动切默认节点重试一次。测试：
  `tests/test_llm_streaming.py`（3 条）。
- **Phase 4**：`POST /api/jobs/{job_id}/workbench/rewrite` 复用为单条重试入口；
  修复"重试成功的 invalid diff 仍残留在 `invalid_diffs` 造成重复卡片"的缺陷，
  成功后从 `invalid_diffs` 移除并晋升到 `diffs`；前端 diff 卡片在失败态渲染
  `↻ 重试此条`（复用 `polish-bullet` → rewrite 端点）。测试：
  `tests/test_jd_preanalyze_rewrite.py`、前端 `split-canvas.test.mjs`。
- **Phase 5**：新增 `local_fallback.py`（`local_diagnose` / `local_gap_report` /
  `local_ats_score`，纯规则零网络）；API job worker 在 `build_config()` 未配置
  LLM 且无活动节点时改用本地规则产出 `Report(fallback="local")`；同时放开
  analyze / diagnose 路由的 503 硬门禁，让"开箱即用、绝不白屏"可达。测试：
  `tests/test_local_fallback.py`（含 worker Report 断言）。

## 明确不做 / 保留的约束

- 不引入 LangGraph / LangChain / CrewAI，Graph Runner 仍为自建 Pydantic 轻量实现。
- 确定性护栏（Provenance / 实体归属 / ATS 硬打分）继续作为防守底线，LLM 只做
  受限节点决策。
- 本地 Ollama 保持单线程串行，不因 Phase 2 并发破坏 VRAM 约束。
- 节点连通性测试（`POST /api/llm/nodes/{id}/test`）与模型分级路由已存在，不重复建设。

## Consequences

- Phase 1 是后续所有阶段的地基：清洗器越健壮，Map-Reduce 与流式阶段的重试
  命中率越高。
- 每次换 Provider 的第一道保险是"连通性测试"（已具备），第二道是 sanitizer
  （本轮），第三道是局部重试与兜底（后续）。
- 前端感知从"20-40s 转圈"逐步降为"秒级首字符 + 失败条目局部重试"。

（Phase 3 的流式原语已完成并可用，editor 管线全链路 SSE 化保留为后续可选增强；
workbench / batch 对齐仍要求配置 LLM，因为这些环节需要真实润色能力。）
