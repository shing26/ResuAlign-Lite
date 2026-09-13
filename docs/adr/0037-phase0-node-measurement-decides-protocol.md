# 0037 — Agent 决策协议不在设计期定，由 Phase 0 节点实测定

Status: accepted (2026-09-14)

当前活跃 LLM 节点是 `meta/muse-glimmer-30b`（NVIDIA 网关；`llm_nodes.py:131` 有实测注释「推理内容烧光 max_tokens 后 content 为空」，需 `disable_thinking` 治）与本地 Ollama qwen2.5:7b。2026-09-13 prod-readiness 实跑：真实 LLM 对齐 3 次只成 1 次（profiler 23.2s vs 预算 30s；editor 90s 仍失败 → 梯度降级产出 succeeded + 0 建议）。此类节点的原生 function-calling 可靠性未知。方案红线自己写了「不许按云端大模型的能力做设计假设」——那就执行它：协议选择不得预设。

**决定：新增 Phase 0，排在一切功能代码之前**——两节点各跑 30 条结构化输出用例（含多步决策模拟，`disable_thinking` 开/关作变体），测 schema 合规率与 JSON 转义错误率；过线 → OpenAI `tools`/`tool_choice` 原生 function-calling；不过 → 收缩为「模板化编排」（确定性场景模板 + LLM 只填参数）。**通过线在测量前写死，不得事后解释。** `benchmarks/cases/schema_retry_tailor_structured.json` 是测试集现成素材。

## Consequences

- 循环协议是 `agent/policy.py` 后面的可插拔 seam，两套协议都是一等公民，不是「主路径 + 补丁」。
- 若落在模板化编排，Phase B「计划」部分复杂度减半，但「自由 agent」叙事随之降温——与 PRD 拍板联动。
- Phase 0 的产出是一份 ADR 补记（哪套协议、依据数字），不是代码。
