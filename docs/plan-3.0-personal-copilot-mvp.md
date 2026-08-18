# ResuAlign 3.0 个人自托管求职 Copilot MVP 计划

Status: Agreed via grilling (2026-08-17)
Scope: 个人自托管求职工作台，本地一键启动优先
Related: `docs/roadmap-saas-workbench.md`（SaaS 作为远期终点）、
`docs/plan-2.0-ultimate-copilot-studio.md`（Split-Canvas 作为 UI 方向）、
`docs/adr/0029-agent-orchestration-pilot.md`（agent 接入试点）

## 1. 产品定义

一句话：**个人自托管的求职工作台，把「筛岗 → 定制 → 投递 → 跟进」跑成一条
可长期使用的闭环。**

铁律：每个改写仍可溯源到 Master Resume；所有用户数据留在本机 SQLite；AI 调用
有每日预算护栏，失败可见、可重试。

## 2. Grilling 决策记录

| # | 决策点 | 结论 |
| --- | --- | --- |
| 1 | 交付对象 | 个人求职者自托管/单机工具，不做 SaaS 产品化 |
| 2 | v1 闭环 | Match + Tailor + Apply/Progress 三件套 |
| 3 | 岗位数据源 | 个人导入（粘贴/CSV/collector）+ 收藏链接定时刷新 |
| 4 | 匹配分模型 | 确定性规则四维分 + LLM 解释，不逐岗纯 LLM 打分 |
| 5 | 定制交付 | 草稿 → 人工采纳 → 定稿 → 导出 PDF/Markdown/JSON |
| 6 | 提醒通道 | 产品内今日待办/日程 + scheduler + 可选 Webhook/邮件 |
| 7 | Message 文书 | 完全移出 v1，不预留模板与自动发送 |
| 8 | 分发形态 | 本地一键启动为主，Docker 为第二通道 |
| 9 | 成本护栏 | 每日调用上限 + 成本/调用可见 + 缓存优先 |
| 10 | 验收标准 | 真实跑通一次完整求职闭环，备份/升级不丢历史，契约回归全绿 |

## 3. 模块清单（现状 vs v1 目标）

### Match（岗位匹配与投递优先级）

现状：岗位库有 JD 分类、JD 画像、gap_report、派生 `match_score`，但没有
“投递前四维匹配分”和可解释排序。

v1 目标：
- `library_jobs` 持久化 `match_score` 明细（硬技能/场景/表达/经验）与
  `match_reason`、`match_updated_at`。
- 确定性规则先打分，LLM 只补一句“推荐投/不投”的理由。
- 岗位列表/工作台展示匹配分与维度条，支持按分数排序。
- 收藏岗位定时刷新：复用 crawler，检测 closed/updated，刷新后重算或标记
  stale。

### Tailor（简历定制）

现状：JD 画像 + 差距分析 + AI 改写 + 草稿落库 + diff 采纳均有；真实运行中
出现过 provenance 带“章节标题: ”前缀导致整批 diff 进 `invalid_diffs`。

v1 目标：
- provenance 匹配放宽到“章节标题 + 行首”，bad diff 降级展示但不再误杀。
- 完成「草稿 → 采纳/拒绝 → 定稿 → 导出 PDF/Markdown/JSON」四态闭环。
- 导出结果带本次采用的 `diff_id`、prompt 版本和模型名，保证可复查。
- 历史版本对比：同一岗位/简历可重跑并对比旧草稿。

### Apply / Progress（投递与跟进）

现状：职业状态、`next_step_due_at`、`interview_stage`、dashboard
`active_followups` 已存在；没有 scheduler 和提醒出口。

v1 目标：
- 轻量 scheduler 扫描到期 `next_step_due_at`，生成“今日待办”。
- 产品内待办/日程视图（红点 + 列表），到期自动推进提醒状态。
- 可选 Webhook（飞书/企业微信/Telegram）或 SMTP 邮件出口，配置不落日志。
- 投递状态迁移与提醒联动：已投递/面试中才进入提醒漏斗。

### Ops（交付底座）

现状：`start.ps1`/`start.sh`、Dockerfile、备份恢复文档已有；metrics 已统计
LLM 调用；缓存已启用。

v1 目标：
- 设置页展示今日 LLM 调用数、估算成本、失败数。
- 每日调用上限：达到后阻止新 LLM 任务并明确提示，缓存命中的分析不占额度。
- 一键备份/恢复覆盖 jobs.db、content-cache.db 与上传文件目录。
- 升级路径：SQLite 迁移向后兼容，历史对齐产物不丢。

## 4. P0 范围

1. Match：匹配分 schema + 确定性打分 + LLM 解释 + 持久化 + 列表排序。
2. Tailor：provenance 放宽 + 采纳/拒绝回归 + 导出 API/UI。
3. Progress：scheduler + 今日待办 + Webhook/邮件配置。
4. 收藏岗位定时刷新（复用 crawler，防重复与更新合并）。
5. 成本护栏：每日上限 + 成本估算 + 设置页 + metrics 联动。
6. MVP 验收：真实主路径 Playwright/E2E + 备份/恢复 + 升级不丢历史。

## 5. P1 范围

- 日历视图与批量跟进。
- Match 分自动重算策略（JD 更新、简历改版后标 stale）。
- agent 接入：现有 `agent/` 编排作为导入/刷新通道之一，正式接线。
- 多岗位批量对齐与并发预算调度。

## 6. v1 明确不做

- Message：求职信、Cover Letter、内推话术、OQ、跟进文案生成与自动发送
  （用户 2026-08-17 确认直接排除，不做入口、模板或自动发送）。
- 自动网申/跨 ATS Autofill。
- 24/7 面试 Copilot、模拟面试、复盘对话。
- SaaS 多租户、支付、配额计费产品化。
- PWA/移动端推送，不引入 service worker 常驻。

## 7. 数据契约草案

- `library_jobs`：新增 `match_score_detail_json`、`match_reason`、
  `match_updated_at`；`match_score` 保留为总分子。
- 提醒：不新建实体，优先由 `next_step_due_at + status` 派生；新增
  `reminder_sent_at` 时间戳做幂等，避免 scheduler 重复推送。
- 刷新任务：复用 `crawl_tasks`，新增 last_refresh_at；closed/update 差异
  记录在 `job_events` 或 notes。
- 设置：新增 `daily_llm_cap`、`llm_cost_per_1k_in/out`、webhook/SMTP 配置；
  密钥只存环境变量，不进 SQLite 明文。

## 8. 验收主路径

1. 导入/刷新岗位：粘贴 JD 或 collector 入库；收藏 URL 定时刷新后状态正确。
2. Match：岗位出现四维分和推荐理由，按分数排序，理由能解释为什么投/不投。
3. Tailor：打开工作台 → 对齐 → 逐条采纳/拒绝 → 定稿 → 导出
   PDF/Markdown/JSON，provenance 可定位原文。
4. Progress：标记投递并设置下次跟进时间 → 今日待办出现 → 到期触发
   Webhook/邮件一次且不重复。
5. Ops：设置页可见预算与调用；达到每日上限后 LLM 任务被阻止并提示；
   备份/恢复后数据完整；升级后历史岗位与对齐产物仍在。

## 9. 依赖与风险

- PDF 导出：优先复用打印契约与浏览器 print-to-PDF，不引入独立渲染服务。
- scheduler：进程内轻量线程 + SQLite 幂等标记；重启不重复推送。
- Webhook/邮件：配置即环境变量；发送失败有重试与日志，但不阻塞主流程。
- LLM 成本估算：先按 model + token 估算，提供配置项，不承诺精确账单。
- 工作区当前有未提交的 agent 编排改动；实施时先锁定基线，不覆盖这些文件。

## 10. 建议 Ticket 切分（待开工）

- Phase 1 数据与 API：match schema/评分/解释、导出 API、reminder 幂等字段。
- Phase 2 运行面：scheduler、收藏刷新、Webhook/邮件。
- Phase 3 前端：职位置顶/分数排序、今日待办、导出菜单、设置页成本卡。
- Phase 4 质量：provenance 回归、预算上限、备份/恢复、升级迁移、Playwright
  主路径验收。
