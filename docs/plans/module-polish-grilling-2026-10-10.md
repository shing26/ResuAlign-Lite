# 模块打磨访谈台账（grilling record）

状态：**访谈完成，转入执行**（2026-10-10 起，10-11 补全并闭环）。本文件是 `[$grill-with-docs]` 访谈的决策台账，
一次一问、每题附推荐答案；未达共同理解的条目不得进入实现。

9/9 模块广度扫描 + 每模块第一稳定性项均已锁定（Q1-Q43；Q38 按推荐默认落地）。
执行决策（Q44）：按旅程顺序逐模块交付，每模块一个可独立验收/回滚的提交；
## 目标与范围

- 打磨目标：从 demo 打磨为**可投入使用的生产系统**（用户确认）。
- 推进顺序：按用户旅程逐模块打磨——岗位库 → 单岗工作台 → 投递闭环 → 简历中心 → 驾驶舱 → 复盘 → 设置 → 指挥台 → 采集。
- 节奏：先广度后深度——广度扫描已确认 9/9 模块统一「**稳定性优先**」（用户原话：地基打稳才能进行功能深度和界面质量的优化）。
- 冻结期口径：ADR-0041 冻结令（#114）仍有效；本轮落地按 F1/F2 摩擦修复与 ADR-0042 决定 6e 例外分类，超出口径的单独立项，不静默破冻结。

## 执行进度

- [x] 批量对齐修复（`5c7a39b`）：后端 alignment_status 置 queued + 前端面板接管式浮层 + 缓存版本 v60。
- [x] 模块 1 · 去重链：多候选查重落地（见下）。
- [x] 模块 1 · 错误处理链：仅重试临时错误 + 固定 3 次退避（1s/2s/4s）+ 仅失败行，
      两条预分析链路共用同一 helper（见下）。
- [x] 模块 2 · 全部落地（stage 独立性 + gap 降级 + gap 重试解锁 + SSE 码透出 + 前端文案表，见下）。
- [ ] 模块 1 收尾后：74 行现存冗余是否合并（需用户确认，破坏性数据操作）。
- [ ] 模块 2-9：按旅程顺序推进。

### 模块 1 · 去重链执行记录（2026-10-11）

真实数据取证（379 行，`.scratch/analyze_dedupe_reality.py`）：41 个多行身份簇全部跨键泄漏
（当前键只漏不误并），成因为 URL 变体（未编码中文 / 尾巴垃圾）与跨键空间（粘贴 + URL 同岗）；
空身份簇 169 行（无公司/标题的纯粘贴）；同身份不同正文的重发误判簇 = 0。

实现：

- `_normalize_source_url` 加固：去全部空白、NFC、percent-encoding 归一、默认端口清除；
  身份 query / SPA fragment / 跟踪噪声行为不变（既有测试契约保持）。
- 新增 `_dedupe_candidates`：URL → 文本 → 身份（company+title 非空才入组）三候选。
- 新增 store `find_duplicate`：单次扫描测全部候选；文本候选对库存正文现算哈希
  （URL 键库存行也能被同正文粘贴命中）；`create_job` INSERT 前统一执行（唯一约束兜底），
  三条插入路径（服务层建单 / 本地摄入 / 无 LLM 直建）与岗位表预检共用同一判据。
- 本地摄入契约更新：同岗位异 URL 再次进入 → duplicate（原为 created，即旧泄漏行为）。

验证：`.scratch/simulate_dedupe_candidates.py` 回放真实库 40/40 泄漏簇全收敛、零误并
（30 个跨身份文本命中逐对确认为同岗元数据漂移，正文逐字节相同）；全量后端 1195 passed / 7 skipped；
ruff clean。

### 模块 2 · 单岗工作台执行记录（2026-10-11，部分落地）

先修两个把用户卡死的真实缺陷：

1. **gap 失败连坐画像**。`preanalyze_job` 与 `_run_session_pipeline` 的 gap 阶段一旦失败就
   上抛，外层直接 `status = failed` + `jd.profile = None`——已经产出并花过额度的 JD 画像
   被整份丢掉。现在 gap 阶段降级：画像照常落库，失败码记在
   `JobPreanalyzeResponse.error`（该字段原本就存在却没人写）与 `session.gap.error`。
   Phase A1 契约不变：`auth`/`quota` 仍然上抛成 `PreanalyzeUnavailable` 停掉整轮扫描。
2. **`jd_profile is not None` 早退守卫把 gap 重试入口整个堵死**。画像在、分类已定、
   gap 缺失的行会被这个守卫判成「已完成」直接返回，于是永远补不上 gap。
   现在守卫按 stage 判定：画像∧分类∧（无简历∨已有 gap）才短路；只缺 gap 时落下去，
   **不再重跑分类和画像**（省额度），只补 gap 这一跳。

实现：`_run_gap_stage`（role 调用 → 单客户端兜底 → 降级返回 `(report, code)`），
导入链 / 一键预分析链 / 工作台会话链三条路径共用；`_gap_stage_error_text` 出人话文案。
`_preanalyze_unavailable_from_llm` 重构成可按错误码复用的 `_preanalyze_unavailable_for_code`。

测试：新增 5 条（gap 降级保留画像并带码；gap-only 重试确实重跑且不短路；
auth/quota 仍然 503 停扫描；一键链记录降级错误但计入 analyzed；
会话链 gap 失败后 session 仍 ready、画像已落库）。全量后端 **1207 passed / 7 skipped**，
前端 543 passed，ruff + modgraph 干净。

SSE 结构化契约（2026-10-12 完成）：后端 `job.error` 透出 `code`（取自 `LlmFailureCode`），
`job.gap_ready` 携带 `error` + `code`；前端 `format.js` 新增 `LLM_FAILURE_COPY` 九码中文文案表
（`llmFailureNotice` / `failureActionText` / `llmFailureSummary` / `gapNoticeHtml` 纯函数），
`split-canvas.js` 的 `handleEvent` 按码查表出 toast 行动文案，inspector「技能缺口」区在
gap 报告缺失时渲染失败通知 + 重试按钮。进度管线三 stage 独立判失败，各自出「分析未完成：…」。
新增 10 条前端单测覆盖码表查表、无码回落、gap_report 存在时返回 null。
前端 553 passed，ruff + modgraph 干净。

### 模块 1 · 错误处理链执行记录（2026-10-11）

部分失败恢复原本就存在（逐行 try/except + skipped/errors），缺的是「哪些错误值得重试」。
本轮补上，并顺手消掉重复：

- 新增 `_preanalyze_row_with_retry`（`_TRANSIENT_LLM_FAILURE_CODES` = timeout/http/rate_limit，
  `_IMPORT_RETRY_DELAYS` = 1s/2s/4s）：只重试瞬时错误，确定性错误（auth/quota/parse/schema/empty）
  一次都不重试；仅失败行原地重试；`PreanalyzeUnavailable` 仍然上抛以停掉整轮扫描（Phase A1 契约不变）。
- **两条链路共用**：导入自动预分析（`_preanalyze_imported_job`）与一键预分析
  （`_run_preanalyze_batch`）。后者此前是独立逐行循环且完全没有重试——用户报的
  「一键预分析失效」在这里被真实修掉，不只是改了文案。
- 失败文案带 `（重试 N 次后仍失败）`，用户能分清「节点抖了一下」和「节点真的不行」。
- 测试：`tests/api/test_import_retry_policy.py` 8/8（原来 5 条锁导入链，新增 3 条锁一键链：
  重试后计数、耗尽后的文案与计数、不可用即停）。

验证：相关套件 66 passed；ruff clean。

## 已锁定决策

### 模块 1 · 岗位库（含重点岗位）——稳定性

- 首要问题：批量导入可靠性。
- 去重链：去重键确定性 → URL 归一化完整性 → 噪声键覆盖 → 零漏判 → 维护全面列表 → 基于真实数据统计。
- 错误处理链：部分失败恢复 → 仅重试临时错误 → 固定 3 次 + 指数退避（1s/2s/4s）→ 仅失败行 → 立即重试。

### 模块 2 · 单岗工作台——稳定性：analyze 主链路失败分级与可恢复性

- 分级判据（三层）：确定性失败（`auth`/`quota`/`schema`/`parse`/`empty`/`deadline_exceeded`）立即置 failed，文案 = 机器码 + 人话行动建议，不自动重试；临时故障（其余 `timeout`/`http`/`rate_limit`）不进终态、标记可重试、保留部分产出、引导手动重试（transport 层已有重试预算，应用层不重复）；profile 与 gap 状态独立、不连坐。
- 重试：按 stage 独立重试——profile 已在（已持久化）不重跑，只补失败/缺失的那一跳；换简历只让 gap 失效；重试按钮落在对应 stage 失败位。修复现状：`jd.profile is not None` 早退守卫会把 gap 失败的重试入口整个堵死。
- 契约：结构化机器码透出（SSE `job.error` 带 `code`，取值 `LlmFailureCode`），前端按码查文案表；对齐阶段既有「正则刮文案反推」逻辑不动（有锁行为，另案）。

### 模块 3 · 投递闭环——稳定性：状态流转合法性与时间线完整性（2026-10-12 完成）

- 流转集：单向漏斗（`draft → applied → interview → offer/withdrawn`，允许跳级，导入中途岗位常见）；任何回退 422 拒绝，文案带当前状态与合法目标；语义复刻 `transition_alignment` 的「Illegal transition + 显式恢复动作」。
- 复活：「重新打开」入口显式改回指定非终态；终态时间戳原样保留、语义变为「曾经到过」；前瞻字段清空；单次原子 `update_job` 连时间戳字段一起写；零新表。
- 已知连带收益：看板 bulk-status / PATCH / 导入三入口共用 `update_job` 收口点；ADR-0027 时间戳语义需补充「回退不清零」限定。

实现：

- `status_lifecycle.py` 新增 `DELIVERY_TRANSITIONS` 矩阵 + `validate_status_transition` / `can_transition_status` / `is_terminal_status` / `allowed_transition_targets` / `StatusTransitionError`（继承 `UserStoreError`，router 的 `except` 直接捕获成 422）。
- `update_job` 新增 `revive: bool = False` 参数；`_resolve_job_update_lifecycle` 在状态变更时调用 `validate_status_transition`，`revive=True` 时保留终态时间戳（`offer_at` / `rejected_at` 不清空）。
- `JobUpdateRequest` 新增 `revive: bool = False` 字段；PATCH 端点透传。
- 自转移（幂等重写，如 `merge_applications_into_jobs` 重复应用同一状态）始终允许。
- ADR-0027 Decision 第二条更新：回退从「显式确认 + 清理」改为「422 拒绝 + `revive=True` 显式复活」。

测试：新增 12 条（存储层 12 条覆盖矩阵/自转移/复活/非法回退；API 层 6 条覆盖 422 拒绝/复活保留时间戳/正向流转不受影响）；更新 2 条现有测试（`test_reapplying_applied_from_interview_is_rejected` 从 append-only 改为 422；`test_allowed_transition_targets` 匹配自转移）。全量后端 **1227 passed / 7 skipped**，前端 553 passed，ruff + modgraph 干净。

### 模块 4 · 简历中心——稳定性：诊断与内容变更的失效语义（2026-10-12 完成）

- 诊断改用画像那套「保留 + source-hash 判失效」：内容变更不清数据（修掉 `update_master_resume`/`rollback_master_resume` 双双 NULL 诊断字段的现状），UI 三态：有效 / 已过期附原因 / 从未诊断；回滚到匹配内容时诊断恢复显示。
- 判定口径双键：内容 hash + 诊断提示词版本（快照已内嵌 `DIAG_PROMPT_VERSION`）；`profile_model` 收敛到同一判定函数。

实现：

- `update_master_resume` / `rollback_master_resume` 不再清空诊断字段（`latest_diagnosis_job_id` / `latest_diagnosis_json` / `latest_diagnosis_source_hash` 保留）。
- 新增 `_diagnosis_for_row`：返回 `{"status": "valid" | "stale" | "missing", "data": diagnosis, "model": model, "reason": reason}`，判定口径双键（内容 hash + `DIAG_PROMPT_VERSION` + model）。
- `get_master_resume` 新增 `diagnosis_status` 字段。
- `_cached_diagnosis` 改用 `diagnosis_status` + 双键判定。
- 前端 `format.js` 新增 `diagnosisStatusHtml` / `diagnosisStatusText`；`resume-center.js` 三态展示（有效 / 已过期附原因 / 从未诊断）。

测试：新增 11 条（存储层 6 条覆盖三态/内容变更/prompt version/model 不匹配；前端 6 条覆盖 `diagnosisStatusHtml` / `diagnosisStatusText`）；更新 1 条现有测试（`test_master_resume_edit_and_rollback_preserve_diagnosis_with_staleness`）。全量后端 **1238 passed / 7 skipped**，前端 559 passed，ruff + modgraph 干净。

### 模块 5 · 驾驶舱——稳定性：统计口径（2026-10-13 完成）

- funnel peak 逻辑显式锚定新状态机不变量（时间戳只增不减）并加测试锁。
- 修两处腐烂口径：① 完成率分子取自 `limit=500` 截断列表、分母是全量 `kpi.jobs`，破 500 后必然偏低；② 当前简历只看 `latest_diagnosis` 存在、不判新鲜度。
- 完成率改服务端全量聚合（`/api/dashboard` 增加全量口径字段），`limit=500` 只喂列表 UI。
- `quick_continue` 失败感知：区分从未跑过 / 跑挂了（带码）/ 在跑，卡片带码表驱动原因徽标，点击仍单入口跳工作台（不在驾驶舱开第二个重试按钮）；顺手兑现冻结票 #48 的 `failure_detail`。

实现：

- `_job_funnel_stage` 文档锚定模块 3 不变量（时间戳只增不减，终态时间戳保留）。
- `list_dashboard_jobs` 返回 `last_alignment_error` 字段。
- `DashboardQuickContinue` 新增 `failure_detail` 字段；dashboard 路由在 `alignment_status == "failed"` 时填充。
- 前端 `dashboard-view.js`：失败时徽章显示 `failure_detail` 的机器码前缀（带码原因徽标）。

测试：新增 3 条（API 层 2 条覆盖 failed 带 failure_detail / idle 无 failure_detail；前端 1 条源码级别测试检查 dashboard-view 引用 failure_detail）。全量后端 **1234 passed / 7 skipped**，前端 560 passed，ruff + modgraph 干净。

### 模块 6 · 投递复盘——稳定性：日期归一化与比较口径（2026-10-13 完成）

- 写入端只收 `YYYY-MM-DD`（导入的非补零格式归一或拒绝），读取端 `_parse_date` 加防御性校验；现状是字典序比字符串，一个坏格式静默错分类。
- 非法日期双轨处置**（第 38 题按推荐默认落地，用户未否决，可翻案）**：导入路径字段级丢弃 + 导入报告列出；直接编辑路径 422 拒绝并提示合法格式。

实现：

- `_parse_date`（review router）：加防御性校验，只接受 `YYYY-MM-DD` 格式；非法格式返回 `None` 而不是静默截断。
- 新增共享 `normalize_import_date` / `validate_edit_date`（`job_library`）：非补零格式归一为 `YYYY-MM-DD`，非法格式返回错误。
- `_validate_job_update`：直接编辑路径（PATCH）对日期字段调用 `validate_edit_date`，非法日期 422 拒绝。
- `_run_import`：导入路径对日期字段调用 `normalize_import_date`，非法字段丢弃并记录到导入报告。

测试：新增 16 条（存储层 10 条覆盖归一化/校验/编辑路径 422；review 6 条覆盖 `_parse_date` 防御性校验；import 1 条覆盖导入路径归一化）。全量后端 **1249 passed / 7 skipped**，前端 560 passed，ruff + modgraph 干净。

### 模块 7 · 设置——稳定性：首屏加载的失败降级与空态

- 降级方式：分区降级——`/api/settings/status` 失败时主体照常渲染（节点列表兜底推导状态），坏分区显示错误条 + 重试；settings/status 两个无 catch 的关键端点补齐降级路径。
- 附带默认（实现细节，无需再问）：无节点默认简单模式 + 内联引导表单；专家模式显式选择即生效（E2E 死锁教训已有注释）；「恢复默认设置」只恢复词表与默认设置、不动节点与摄入 Token，按常规确认框处理。

### 模块 8 · 指挥台（LLM 节点管理）——稳定性：首跳失败代价

- 调用链加进程内短期冷却：节点本次 `timeout`/`http`（连接失败、5xx）失败后 60s 内同进程跳过该节点；`auth`/`quota` 不触发（配置问题，换节点才对）；`parse`/`schema`/`empty` 不触发（模型产出问题）；固定 60s 单一旋钮。
- 持久熔断机器（#103：阈值 3、计数码、恢复路径）语义不变，冷却是其上的类缓存快失败层；`auto_disabled` 徽标与「测试连通性恢复」路径已存在，不动。
- 已排除的候选：test-all 串行探测体验（次优先，后续做）；自动半打开（改 #103 语义，需 ADR-0042 6e 例外，本轮不做）。

### 模块 9 · 采集（油猴摄入器）——稳定性：失败重推、不丢载荷

- 推送失败时 payload 保留在悬浮窗内可一键重推（重取 Token / 改地址后不必重抓页面）；刷新 / SPA 跳转前有未推送成功载荷时给离开确认。
- 现有失败反馈（401 引导 / HTTP 原因 / 网络 / 超时四类 setFeedback）不动，只补恢复路径。
 - 次优先候选：脚本-服务端版本握手；三路提取命中率治理。

## 待办队列
- 执行顺序与提交粒度：待用户确认（下一步问题）。
- 每模块第二稳定性项（test-all 体验 / 版本握手 / 提取命中率等次优先候选）：访谈记录在案，排期时再定。
- 收敛执行计划后：按新决策补 ADR（下一号 0059 起）与 `CONTEXT.md` glossary（新概念：进程内冷却、单向漏斗+显式复活、分区降级等）。

## 约束备忘

- 不改 HTTP API/OpenAPI 语义为前提，除非显式决策（`quick_continue` 增字段属加性变更，落地时同步 golden 快照）。
- 验证 UI 流程用 FakeLLMServer 隔离实例，不烧用户额度；正式数字取 CI Ubuntu。
