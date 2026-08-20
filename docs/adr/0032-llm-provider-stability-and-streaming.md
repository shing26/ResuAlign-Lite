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
| 3 | 流式生成 + 15s 零 Token 熔断 + 备用节点回退 | 后续 |
| 4 | 局部单条重试（diff 气泡内 `↻ 重试此条`） | 后续 |
| 5 | 零配置本地兜底（未配 Key 时走确定性规则） | 后续 |

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
