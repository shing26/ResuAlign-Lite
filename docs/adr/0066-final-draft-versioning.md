# ADR-0066：定稿版本化（final draft versioning）

- 状态：已采纳（2026-10-28）
- 关联：ADR-0059（P0 自用验证）、ADR-0065（排序，B 档灰度）、#168

## 背景

定稿目前只有「当前值 + 一个计数器」：`library_jobs.final_draft` 是单值，
`final_draft_version` 只是个数字，没有历史行。由此产生四个具体问题：

1. **证据不可复核**：投出去的 PDF 无法证明对应哪一版定稿（没有 version_id / sha256），
   P0 的「保存定稿 → 导出 → 投递」链条缺最后一环；
2. **无法对比**：采纳前后、两次运行之间的差异只能人工肉眼比；
3. **无法回滚**：改坏了只能重新跑对齐；
4. **采纳不可追**：`accepted_diff_ids` 只在保存请求里传一次，落库后只剩 diff 的
   `provenance_state`，无法回答「这一版采纳了哪几条、来自哪个模型」。

## 决策

1. **新增 `final_draft_versions` 表（迁移 48）**，每次保存定稿插入一行：

   | 列 | 说明 |
   | --- | --- |
   | `version_id` | 主键（uuid4 hex） |
   | `tenant_id` / `job_id` / `version` | 归属与版本号（同一岗位唯一） |
   | `draft` | 该版全文 |
   | `accepted_diff_ids_json` | 该版采纳的 diff id 列表 |
   | `model` / `prompt_version` | 产出该版时的模型与提示版本 |
   | `sha256` | `draft` 的 UTF-8 sha256（十六进制） |
   | `source` / `source_version` | `save` / `rollback` / `backfill`，回滚时记录来源版本 |
   | `created_at` | 写入时间 |

2. **`library_jobs.final_draft*` 保留为「当前投影」**：保存与版本写入在同一事务内完成；
   不变量 = 最新版本行的 `draft` 等于 `library_jobs.final_draft`（测试锁定）。
3. **导出携带版本身份**：`meta` 增加 `final_draft_sha256` 与 `final_draft_version_id`；
   JSON / Markdown 导出承载，**PDF 打印件不打印**（投递件不放审计信息，见 ADR 记录 2026-10-27）。
4. **回滚 = 追加新版本**：把目标版本内容写成 `version = 当前 + 1` 的新行（`source=rollback`，
   `source_version=<目标>`），并更新投影；不删除任何历史行。
5. **存量回填**：迁移内把现有 `final_draft` 回填成各自的当前版本（`source=backfill`，
   `sha256` 留空——SQL 无法哈希）。导出时按当前 draft 现算 sha256，保证 P0 证据可用；
   历史行在 UI 显示「未记录 sha」。

## 后果

- 写放大：每次保存多一行 draft（约 3–5 KB），单人库可接受；
- 导出多一次按 `(job_id, version)` 的查询；
- 回滚不再丢数据，历史可 diff；
- 为 A（投递主线）提供了可直接外键化的 `version_id`。

## 备选与不选

- **只加 sha 列**：不能 diff、不能回滚，P0 之后仍要补表；
- **定稿写文件系统**：违背本地优先单库（备份/恢复只有一条路径）。

## 验证

- store：保存两次 → v1/v2 两行、sha 与 `hashlib.sha256` 一致、回滚生成 v3 且内容等于目标版；
- API：列表 / 详情 / 版本 diff / 回滚四个端点；
- 导出：`meta.final_draft_sha256` 与当前版一致；PDF 内容不含审计字段；
- 迁移收敛测试期望集合加入 48。
