# ADR-0067：投递主线（job application as the spine）

- 状态：已采纳（2026-10-28）
- 关联：ADR-0059（P0）、ADR-0066（定稿版本化）、#168

## 背景

「投递」目前散在三处：

1. `library_jobs.applied_at / status`（看板与筛选在用）；
2. 旧 `applications` 表（有 `latest_job_id / resume_version / jd_text`，但 `tenant=local` 下 0 行）；
3. `application_snapshots`（1 行，存过定稿快照，无 sha、无渠道、无结果）。

结果是：**没人能回答「这一版投给了谁、什么渠道、结果如何」**——而这正是 P0 证据链
与 C（采纳→面试）的死结。

## 决策

1. **新增 `job_applications` 表（迁移 49）**，每个岗位一条：

   | 列 | 说明 |
   | --- | --- |
   | `application_id` | 主键（uuid4 hex） |
   | `tenant_id` / `job_id` | 归属，`UNIQUE(tenant_id, job_id)` |
   | `version_id` / `final_draft_version` / `draft_sha256` | 投递时绑定的定稿版本（ADR-0066）；旧数据为空 |
   | `channel` | 官网 / 平台 / 邮箱 / 内推，自由文本 |
   | `applied_at` | 投递日期（字符串，沿用现有 YYYY-MM-DD） |
   | `status` | `applied / interview / offer / rejected / withdrawn` |
   | `outcome_at` | 结果发生日期 |
   | `notes` | 备注 |

2. **`library_jobs.applied_at / status` 是投影**：写入与新表同事务；状态取
   `interview → 面试中`、`offer → 已拿Offer`、`rejected/withdrawn → 放弃`。
3. **投递时自动绑定当前定稿**：`version_id + sha256 + final_draft_version` 一并落库；
   没有定稿则拒绝（422）——投递必须对应一版可导出的定稿。
4. **旧 `applications` / `application_snapshots` 冻结**：不再写新数据，读路径保留到
   前端切换完成；迁移 49 只从 `library_jobs.applied_at` 回填 `job_applications`。
5. **时间线由服务端拼装**（岗位 → 对齐 → 定稿版本 → 投递 → 结果），前端只渲染，
   避免各页面自己拼字段。

## 后果

- 投递成为一等对象：P0 证据链 = `job_id → version_id/sha → channel → applied_at → outcome`；
- 看板/筛选继续读投影，暂不改 UI 契约；
- 每岗位一条投递（重复投递同一岗位用 notes 体现），不引入"多轮投递"复杂度。

## 备选与不选

- **继续用旧 `applications`**：列语义是另一套（jd_text 快照、resume_version），
  与新岗位库/版本化对不上，且已有"de-bloat 冻结"历史；
- **只加 `applied_channel` 到 library_jobs**：无法表达结果与时间线，C 仍然做不了。

## 验证

- 迁移 49 收敛测试；store：绑定版本/sha、投影状态、结果映射、时间线；
- API：创建/读取/回填结果/时间线 4 个端点；
- 前端切换后：岗位页「记录投递」走新端点，时间线一屏可见（A/2）。
