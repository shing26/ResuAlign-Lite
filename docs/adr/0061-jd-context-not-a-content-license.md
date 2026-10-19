# 0061 — `jd_context` 只是提示词上下文，不是内容许可

- **状态**: 已采纳
- **日期**: 2026-10-20
- **关联**: issue #165、#164；ADR-0060；ADR-0041 决定 11；ADR-0019
- **上游**: `truetailor@ea6b4cc77d8d0fb50db8636fbcfdab70dc7cf149`

## 背景

`jd_context` 的约定是“对雇主在买什么的一句话摘要”，但出现两种漂移：

1. app 主流程把 `truncate_text(filtered_jd or jd_text, 6000)` 的整段 JD
   塞进 `jd_context`；
2. 上游 allowlist 曾把 `jd_context` 当作可放行语料，且 JSON 中没有其他
   可识别字段时会回退返回整段 JSON，导致“JD 有、简历没有”的术语仍可能
   通过内容级校验。

这会把提示词上下文偷换成“候选人做过”的许可来源，违背 ADR-0019 的
零幻觉硬门。

## 决策

1. `jd_context` 只作为编辑器提示词上下文，**永不进入 allowlist/内容级
   校验**。allowlist 只认 `supported_keywords`，`missing_keywords` 和
   `jd_context` 都要排除。
2. 上游 `gate.py::allowlist_corpus` 解析到 JSON gap report 时，只拼接
   允许的结构化字段；没有允许字段时返回空 corpus，不再回退返回原始
   JSON 文本。该修正已在上游先提交，再按 ADR-0041 决定 11 同步 vendor。
3. app 不再把 JD 原文作为 `jd_context`。`jd_context_summary()` 从
   JDProfile 与 GapReport 的结构化字段生成不超过 300 字的一行摘要；
   摘要不包含 `jd_text`，也不包含 `missing_keywords`，避免把真缺口重新
   灌进编辑器提示。
4. `engine.run` 的整卷/逐条编辑路径、工作台单条重试都使用该摘要；
   `tailor_resume_map_reduce` 不再从 `gap_report["jd_context"]` 兜底读取。
5. `rewrite_bullet` 的内容级校验只使用原 bullet 作为事实来源；
   `jd_context` 可以影响措辞方向，但不能让新术语变成已验证事实。

## 后果

- 旧 gap report 即使携带整段 `jd_context`，也不能再扩大 allowlist。
- 编辑器可能看到岗位要求和业务场景来改善措辞，但任何原文没有的新术语仍会
  被拦成 `fabricated`。
- 上游黄金场景由 19 增至 21：`d12-jd-context-is-not-a-license` /
  `e9-jd-context-is-not-a-license`，并新增 context-only JSON 契约自检。
- 可改写素材进一步收窄；这是 fail-closed 的刻意取舍。宁可少产出，也不
  让 JD 术语冒充简历事实。
