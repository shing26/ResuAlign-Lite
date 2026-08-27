# ADR-0021: Copilot + Split-Canvas workstation

Status: accepted (2026-08-04)

## Context

2.0.1 已经确认五列看板、SSE 事件通道、稳定 diff_id、持久化 alignment 等
原则。本次联席会议引入两个新标杆：求职方舟（万能输入、侧边浮窗、无感沉浸）
与 TalentCat（双栏分屏、JD 画像卡片、Bullet 逐条对比与一键 AI 替换），
目标是把 ResuAlign 收敛为「AI 求职 Copilot + 交互式分屏工作室」的结合体，
而不是后台管理面板。

## Decisions

1. 主视图改为 Optimizer 双栏 Split-Canvas：左栏 JD 智能剖析区（岗位信息、
   硬技能 Gap、匹配度雷达、业务场景），右栏履历 Bullet 逐条对比卡片。
   决策/评估/快搜收进 Copilot 抽屉。本决议修订 ADR-0020 第 12 条的常驻
   三栏默认值；三栏仅保留为 >=1280px 的用户可选视图。
2. 双模式是 shell 级布局切换，不新增唯一入口路由：Copilot 复用
   `#/jobs`，Optimizer 复用 `#/workspace/:jobId`。
3. 万能输入框常驻顶栏，支持 `Cmd/Ctrl+K`；URL/文本/文件走
   `POST /api/jobs/preview` -> 确认卡片 -> 入库 -> 自动预分析。
4. 新增 `POST /api/workbench/session/init` 作为「粘贴即建会话」入口，
   `GET /api/workspace/session/{job_id}` 作为打开既有岗位入口；两者共享
   `WorkstationState` 与 SSE 事件契约，读取绝不触发 LLM。
5. 持久化边界：运行中 session、stage/progress、partial gap、tentative
   diff 与事件 fanout 走内存（TTL 30 分钟）；终态 alignment 产物
   （gap/diffs/score/draft）、任务信封（crawl/alignment tasks）与看板
   /final draft 必须落 SQLite。此决议明确并收紧 ADR-0020 第 9 条。
6. 预分析只自动执行 classifier + JD profile + gap，tailor/eval 仍由用户
   显式触发；并行对象是 classifier 与 profile_and_gaps，不再为并行拆分
   已有合并调用。
7. Bullet 行内重写使用 `POST /api/jobs/{job_id}/workbench/rewrite`，
   instruction 白名单为 `quantified / high_concurrency / concise`；原文由
   后端从持久化 alignment 按 `diff_id` 读取，前端不得提交原文。
8. `diff_id` 是前后端与 SSE/采纳/落库的稳定主键，替代数组下标；采纳接口
   与前端 DOM key 同步迁移。
9. Provenance 升级为 `provenance_state`：`verified / ambiguous / missing /
   pending_review`；校验做空白/换行归一化与全部候选 span；`add` 无来源
   进入 `invalid_diffs` 或被标记 `pending_review`，不得静默进入 draft。
10. JD 画像公开契约字段统一为 `required_skills / nice_to_have /
    business_scene`，Pydantic 对旧字段保留 alias 兼容。
11. Bullet 1s 目标采用 cache-first：cache hit <=500ms 为硬门，cold 走 SSE
    pending；`fast_model` 或 bullet 专用低延迟参数提前到 P0，上线前用离线
    benchmark 验证防幻觉与 gap coverage 不退化。
12. 契约采用增量模型：v1 golden 不可变，新增路径/字段进增量 manifest；
    公开响应补 Pydantic `response_model`；`#print-root` 与 `printTarget()`
    作为前端导出契约在视觉重构前修复。
13. 前端继续无构建 Vanilla ESM；新增 `split-canvas.js`、`command-panel.js`、
    `export.js` 等模块时统一走 `data-action` 事件委托，保留 `#app /
    #toast-region / #print-root / data-* / aria-*` 契约。
14. 质量护栏：pytest 总数与 coverage 作为 CI artifact；latency cold <=3.3s、
    cached <=2.2s、schema retry <=4.4s；offline 15/15、avg goal coverage
    >=0.8；Playwright 新主线「万能输入 -> 分屏 -> Bullet 采纳/拒绝 -> 复制
    Markdown/PDF」desktop+mobile 全通过。

## Consequences

- 前端初始 RTT 从 4+ 收敛为 1 个 session 请求；增量由 SSE/轻量轮询 + etag
  承担。
- 现有 `applications` 表降为派生记录；用户侧创建/编辑表单删除，旧数据保留
  并做迁移映射。
- 零点击预分析必须受缓存、幂等、队列边界约束，避免 LLM 成本放大。
- SSE 认证继续禁止裸 query token：前端用 fetch + ReadableStream 或短时
  cookie。
- Playwright 断言最终 DOM/JSON，不依赖 SSE 到达顺序；拖拽只做非硬门 smoke。

## Deferred

- `fast_model / reasoning_model` 完整分层、在线 P95 nightly、60fps 采样、
  ContentStore 大文本外置与备份迁移，列为本阶段 P1 或后续版本。
