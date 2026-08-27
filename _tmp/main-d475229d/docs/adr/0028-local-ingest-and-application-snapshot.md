# ADR-0028: Client-side JD ingestion and applied-draft snapshots

Status: accepted (2026-08-16)

## Context

V4 迭代聚焦两个 P0 闭环：JD 录入（国内招聘平台反爬严苛，后端强攻成本高、
维护碎）和投递后回溯（记录投递时只 PATCH status/applied_at，之后重跑对齐
或另存定稿会覆盖当时实际投出的版本，HR 来电时无法一秒找到投递版简历）。

## Decision

- JD 录入采用客户端降维：Tampermonkey 油猴脚本，双模摄入。
  - Specific 模式先适配实习僧（shixiseng.com）：岗位详情页高精度提取
    title/company/location/salary/jd_text，右下角一键入库。
  - Universal 模式覆盖全网官网校招/实习页：划词选中 JD 文本后，浮层
    「摄入选区 JD」发送 document.title + 当前 URL + 选中文本，由后端
    已有规则/LLM 结构化。
  - 剪贴板文本粘贴沿用现有 Ctrl+K 快速导入；截图 OCR 推迟到后续迭代。
- 新增专用本地端点 `POST /api/jobs/local-ingest`，不复用 `/api/jobs` 或
  批量导入。
- 鉴权使用 Local Ingest Token（`X-ResuAlign-Token`）：服务端首次启动自动
  生成并持久化，系统设置页支持复制/重置；油猴首次运行弹输入框粘贴，
  401 时清空并重新引导。API 地址可配置，默认 `http://127.0.0.1:8011`。
- local-ingest 请求路径只做确定性解析（title/company/location/salary 从
  页面字段或正则推导），新岗位以 `classification_pending=1` 秒级入库；
  分类通过既有重新分类/工作台预分析按需补全，不阻塞摄入。
- 查重语义：Specific 模式按岗位 URL 归一化查重，Universal 模式按 JD 文本
  哈希查重；重复时返回 `{status: "duplicate", job_id, job}`，绝不覆盖
  已有 Job 的 status/notes/final_draft。
- 记录投递进入已投递时，后端同一事务冻结「投递定稿快照」到独立的
  `application_snapshots` 表：final_draft、match_score、主简历引用、
  applied_at 等不可变；岗位抽屉/卡片按时间列出快照，支持查看 Markdown
  与下载 PDF。
- 快照采用 Append-Only 策略：`application_snapshots` 主键为自增 ID，并
  记录 `version_index`（同一 Job 内 1,2,3… 递增），抽屉按 created_at
  DESC 列出历史投递镜像。已投递岗位再次「记录投递」不再被幂等拦截，
  而是追加新一轮快照且不降级/不覆盖原 status；前端原“无需重复记录投递”
  守卫同步调整为可确认的追加动作。
- 存量降级：已投递/面试中但迁移前无快照的岗位，抽屉查询快照为空时自动
  降级读取当前 final_draft，并标注「⚠️ 早期投递版本（未生成不可篡改
  快照）」，缺失 match_score 时显示占位，不抛前端异常。
- 油猴摄入反馈为原地轻量状态（已入库/已在岗位库/失败原因），提供可选的
  「去工作台」链接，不自动弹出新标签页。
- 油猴首次配置框同时提供「服务地址」与 Token 两个字段：服务地址默认
  预填 `http://127.0.0.1:8011`，两者都存入 `GM_setValue`；本地端口被
  占用改用 8012 等端口时无需改脚本源码。

## Considered Options

- WXT/Plasmo 浏览器扩展：功能更强但需要签名/构建链，且用户当前主要场景
  是官网校招划词，Tampermonkey 脚本零构建、安装最快，故先采用脚本。
- 后端 DrissionPage/Playwright-stealth/代理池/HITL 强攻：仍会触发验证码
  和封 IP，P0 收益低于客户端方案，本轮不做。
- 同步 LLM 分类后再返回：每次摄入多等 2-5 秒，批量刷岗位体验差，且失败
  时仍落回 pending，故改为先入库后补全。
- 不加快照、约定「投递后不改 final_draft」：不可靠，无法满足一秒回溯；
  手动「锁定版本」按钮则多一步操作，故采用自动冻结 + 独立表。

## Consequences

- 后端新增 `user_settings.local_ingest_token`（或等价持久化）与
  `application_snapshots` 表，通过既有 migration 机制演进。
- `/api/jobs/local-ingest` 需要同时兼容个人模式匿名租户与 token 校验；
  多租户模式下 token 按租户存储。
- 油猴脚本、README/安装说明与前端设置页需要同步更新；Playwright/e2e
  覆盖 token 配置、双模摄入和快照展示。
- 后续迭代可无破坏地增加图片 OCR、更多 Specific 站点与 HITL 兜底。
