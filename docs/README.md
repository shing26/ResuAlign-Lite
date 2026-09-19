# docs/ 目录导航

一句话规则：**平铺层 = 活文档，子目录 = 归档。** 新增文档前先看这里，别往平铺层堆历史报告。

（本仓库长期由多个 agent 交替开发，曾经 40+ 份带日期的报告平铺在 `docs/` 根下。
2026-09-16 做了一次归档，此页是给下一位 agent 的导航，避免再次堆积。）

## 平铺层：仍在被引用或维护的活文档

| 文件 | 说明 |
| --- | --- |
| `adr/` | 决策记录。**只增不改**；编号不复用（0029 已删除，见 ADR-0036 编号说明） |
| `agents/` | agent 工作方法：issue tracker / triage labels / domain docs / QA agent |
| `user-guide.md` | 用户手册 |
| `operations.md`、`runbook-incidents.md`、`backup-restore.md`、`deployment-security.md` | 运维与安全 |
| `resualign-collector-install.md` | 油猴摄入器安装说明（指向仓库根目录的 `resualign-collector.user.js`） |
| `ticket-9-observability.md` | 被 `src/resualign/api/routers/ops.py` 注释引用 |
| `prd-commercialization-20260905.md` | 商业化 PRD（2026-09-14 主叙事已拍板） |
| `probe-window-plan-2026-09-16.md` | 探针窗执行计划（活文档；判据截止后归档到 `plans/`） |
| `architecture-hardening-plan-2026-09-19.md` | 架构加固计划（活文档；现在批已完成，挂起批等探针时钟出结论后评审） |
| `probe-112-outreach-2026-09-15.md`、`probe-112-dogfood-2026-09-15.md`、`probe-112-send-checklist-2026-09-16.md` | ADR-0042 探针在途（时钟起点登记在此），**未收口前不许移动** |
| `foundation-110-attribution-2026-09-15.md`、`market-research-competitors-2026-09-15.md`、`llm-provider-stability-analysis.md`、`tickets-2.0.md` | 被 ADR-0032/0040/0041/0019 正文按路径引用；ADR 只增不改，故**原位冻结**，整理时不要"顺手"搬走 |

## 子目录：归档

| 目录 | 装什么 |
| --- | --- |
| `plans/` | 历史计划、规格、票据（plan-\*、spec-\*、tickets-\*、roadmap、设计/重构方案） |
| `reports/` | 带日期的一次性报告：QA 走查、评审、调研、交接（handoff）、方向裁决、模块验证 |
| `superpowers/plans/` | superpowers 工作流的执行计划 |
| `agents/`、`adr/` | 见上 |

默认：**归档文档不再更新**；若某份归档件重新变成活文档，把它移回平铺层再改。

## 新文档放哪

| 产出 | 位置 |
| --- | --- |
| ADR | `docs/adr/NNNN-slug.md`（下一个号 = 现有最大号 + 1；跳过空缺号不复用） |
| QA / 走查报告 | `docs/reports/qa-dogfood-report-YYYY-MM-DD.md`（约定见 `docs/agents/qa-dogfooder.md`） |
| 一次性评审、调研、裁决报告 | `docs/reports/<slug>-YYYY-MM-DD.md` |
| 计划 / 规格 / 票据 | `docs/plans/<slug>-YYYY-MM-DD.md` |
| 长期维护的操作文档 | `docs/` 平铺层 |

命名统一用**英文 kebab-case + 日期后缀**，中文标题留在文档 H1。

## 归档操作备忘

移动文档后必须做一次引用自检（`docs/` 内外都查），因为本仓大量引用写成反引号
repo-root 路径而非可点击链接：

```bash
# 对每个被移动的文件名，查全仓残留引用
git grep -n -I "docs/<旧文件名>.md" -- '*.md' '*.py' '*.mjs' '*.js' '*.yml'
```
