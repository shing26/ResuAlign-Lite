# ADR-0029: Agent orchestration pilot

Status: proposed (2026-08-16)

## Context

用户希望用 agent 提高效率：JD 岗位抓取一个 agent，简历处理一个 agent，
大多数模块都由 agent 替代。当前痛点是持续加功能/优化导致调试成本高，
容易打击信心。

现状是 `src/resualign/agent/` 已经提供 MCP 工具
（`fetch_and_evaluate_job`、`auto_align_resume`、`get_pending_blockers`、
`resolve_blocker`）、headless daemon 与 HITL webhook；
`engine.py` 是确定性流水线 + LLM 阶段（diagnose / profile / gap /
tailor / evaluate），仓库已有 840+ pytest、benchmark 与前端测试作为质量门禁。

若直接把 crawler / parser / classifier / store 等确定性模块换成自由 LLM
agent，会引入不可复现输出、更高 token 与延迟成本、幻觉风险，并让调试
更难定位，与降低调试成本的初衷相悖。

## Decision

Agent 不替换模块，而是编排现有模块：确定性模块保持为 agent 的工具，
LLM 阶段保持为 agent 的能力，agent 层只负责决策。

### 编排边界

- Agent 只能通过现有 MCP 工具层 / API 调用系统，禁止直接改 store、
  写文件或调用 `engine.run()` 之外的内部函数。
- 每个 agent 使用固定 prompt + 结构化 JSON 输出 schema + 最大工具调用轮数；
  agent 不自由组合未授权的工具。
- 铁律不变：不捏造事实；低置信度 diff 必须转人工确认；agent 不得自动
  修改 final_draft 或跳过 blocker。
- Agent 失败、超时或预算耗尽时，降级到现有确定性路径：headless daemon、
  Web UI、人工 blocker 处理。agent 是加速器，不是唯一入口。

### 试点范围

1. JD intake agent：决策抓取重试、blocker 处理、重复岗位与分类待定。
   工具：`fetch_and_evaluate_job`、`get_pending_blockers`、
   `resolve_blocker`。
2. Resume alignment agent：决策何时排队对齐、结果质量检查与低置信度转交。
   工具：`auto_align_resume`、分析任务查询、HITL webhook。
3. Supervisor（后续可选）：批量扫描岗位库、按优先级对齐、输出每日汇总。

### 预算

- 单 URL 抓取：最多 2 次确定性重试 + 1 次 agent 决策轮，仍失败则落 blocker。
- 单对齐任务：最多 3 次 agent 工具轮；LLM 超时沿用现有配置。
- 每日批量上限、token/费用上限通过 `RESUALIGN_AGENT_*` 环境变量配置，
  默认保守。
- 所有 agent 决策写入 observability 事件：
  `agent.decision` / `agent.failure` / `agent.budget_exceeded`，
  便于复现与定位，而不是让失败静默。

### 落地顺序

- Phase A：JD intake agent 最小闭环（复用现有 MCP 工具，只加编排与契约测试）。
- Phase B：Resume alignment agent 最小闭环。
- Phase C：supervisor 批量编排（可选）。

每个 Phase 的验收标准：现有 pytest、benchmark、node 测试、Playwright
smoke 全绿；新增 agent 契约测试覆盖成功路径与降级路径。

## Considered Options

- 用 agent 替换 crawler/parser/classifier/store：拒绝。确定性逻辑的可复现性、
  安全边界与测试契约会被自由 LLM 决策削弱。
- 无 agent，只保留 headless daemon：保留为降级路径，但没有自主决策、
  批量编排与质量检查。
- 引入第三方 agent framework（如 LangGraph）：推迟到有真实多步编排需求后
  再评估，避免为试点引入新框架成本。
- 本轮采用：薄 orchestrator + 现有 MCP 工具，先收敛一个垂直闭环。

## Consequences

- 新增 orchestrator prompt 模板、agent 配置与 agent 契约测试；核心引擎
  `engine.py` 与数据层保持不变。
- MCP 工具成为硬契约，后续工具变更需走与 OpenAPI 同等的契约测试门禁。
- 新增 `RESUALIGN_AGENT_*` 配置与 observability 事件，文档同步更新。
- 试点不会立即减少功能开发，但会先把调试噪音收敛到一个可控闭环，
  后续 agent 能力的扩展都基于同一套边界与预算。
