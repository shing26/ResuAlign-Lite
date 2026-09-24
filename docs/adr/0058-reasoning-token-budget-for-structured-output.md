# ADR-0058: 结构化输出预算必须容纳推理 token；截断输出同样触发预算翻倍

- **状态**: 已采纳
- **日期**: 2026-09-24
- **依据**: ADR-0042 决定 6e（逐项例外）；用户主动派单（「预分析一直失败，
  排查问题」）
- **关系**: 只解冻 `engine/llm.py` 的结构化 JSON 重试与 `services/jobs.py`
  的 classifier 预算两处；不动 AIE 决策域的角色超时数值，不改探针判据

## 背景：分类在推理模型上被自己的 token 预算掐死

活服务实测（2026-09-24，节点 nvidia `meta/muse-glimmer-30b`）：

```
attempt 1  max_tokens=128  finish_reason=length  content=None
           reasoning_content 长度 365        → 整个预算烧在推理上
attempt 2  max_tokens=256  finish_reason=stop    content=完整 JSON
           usage.completion_tokens=183
```

两条独立缺陷叠加：

1. **预算不含推理 token**。`OpenAIClient._provider_extras()` 在
   `request_direct_output` 为真时发 `{"thinking": {"type": "disabled"}}`，
   但 NVIDIA NIM 对该模型**忽略**这个字段——响应里照旧带
   `reasoning_content`，而它**计入 `max_tokens`**。classifier 的直连预算被
   钳在 128（03-AIE §③「纯 JSON 输出」的假设），于是长 JD 上推理吃光预算，
   `content` 为空或被截断。

2. **截断的非空输出不会翻倍预算**。`_chat_structured_json_mode` 只在
   `not content and finish_reason == "length"` 时翻倍；而截断成
   `{"job_function":` 这种**非空**内容是同一种症状，却直接进解析失败分支，
   用同样大小的预算重试一次就报
   `Structured response failed schema validation after 2 attempts`。

实测证据（修复前，app.log）：`20955504…`（3754 prompt tokens）连续两次
`attempts=2 / tokens_out=256 / status=failed`，报
`Unable to parse LLM JSON response: '{"job_function":'`。

## 决定

**决定 1（截断即翻倍）**：`_chat_structured_json_mode` 中，只要
`finish_reason == "length"` 且未触顶 `_token_cap` 就翻倍预算——
`content` 为空时按原逻辑立即重试；`content` 非空（截断）时让它落进解析失败
分支，由该分支用**已翻倍**的预算重试。与 `_chat_structured_provider`
既有的 `finish_reason == "length"` 翻倍行为对齐（两条路径此前不一致）。

**决定 2（classifier 直连预算 128 → 512）**：`services/jobs._classify_job`
的 `max_tokens` 由 128 提到 512，让「推理 + JSON」都放得下。模型仍会在
`stop` 处停下，正常路径不增加生成量；反而因为不再浪费一次被截断的尝试，
长 JD 的总耗时下降（实测 6222 字 JD 单次 17.6s 成功，输出 509 tokens）。

**决定 3（不做）**：

- 不动 `_ROLE_TIMEOUT_DEFAULTS`（profiler 75s 等）——那是 ADR-0018/#116 的
  AIE 决策域数值，需要用户裁决，不由本 ADR 顺手改；
- 不改 `{"thinking": ...}` 的 provider 字段形态（不确定各 provider 的正确
  写法，猜测会把「被忽略」变成「400」）；
- 不改默认回退节点的选择逻辑。

## 后果

- 分类不再因推理 token 挤占预算而间歇失败。
- 结构化 JSON 在「空输出」与「截断输出」两种截断形态下都会自动扩容重试。
- **残留（未解决，需要用户决策）**：预分析仍会受节点能力影响——
  `meta/muse-glimmer-30b` 实测单次 17–130s，超过 profiler 的 75s 墙钟即
  回退到默认节点；而默认节点 DeepSeek 当前 **HTTP 402 欠费**，于是回退即硬
  失败。要么给 DeepSeek 充值让回退可用，要么改用更快的节点（本地
  `qwen2.5:7b` 实测 7.6s），或另行裁决调整角色超时。

## 验证

- `tests/test_llm.py::test_structured_json_mode_expands_budget_on_truncated_content`
  （新增）：截断的非空输出 → 第二次请求预算翻倍并成功。
- 既有 `test_structured_json_mode_expands_budget_on_reasoning_length`
  （空输出）保持通过。
- 活服务实测：真实 6222 字待分类 JD，修复后**单次**成功（509 output
  tokens）；修复前同一量级输入在 128/256 预算下两次失败。

## 与既有 ADR 的关系

- **ADR-0042 决定 6e**：本 ADR 即该条的逐项例外记录（用户主动派单、修复
  功能性失败），冻结令其余部分继续有效。
- **ADR-0057**：同批采集/预分析修复；本 ADR 补的是它未覆盖的 LLM 预算层。
