# ResuAlign — Domain Glossary

> 本地优先的求职工作台：简历诊断 / 岗位库 / 单岗对齐精修 / 投递闭环。
> 核心引擎前端无关（CLI 与 Web 共用同一套流水线），铁律：**不捏造事实**。

## 问题 / 目标 / 非目标

**问题**：求职者逐岗手工改简历耗时，且容易夸大；LLM 能改写，但会编造事实，
而编造的简历在面试里会穿。

**目标**：把「岗位 → 对齐后的简历 → 投递 → 复盘」做成一条可追溯的本地闭环；
每条改写都能指回主简历原文（provenance）。

**非目标**（明确不做）

- 自动海投、简历代写、信息聚合运营（issue #62，`wontfix`）。
- 后端爬虫与 `--jd-url`（2026-08 退役，改由油猴插件/粘贴录入）。
- 生产规模多实例部署、托管 demo / 落地页（ADR-0041 冻结令）。
- 为评分把「钳制配置」改成「启动期拒绝」（ADR-0054 决定 6）。

## 关键裁决索引

| 主题 | ADR |
| --- | --- |
| 防编造 provenance | [0006](docs/adr/0006-anti-hallucination-provenance.md) |
| 前端无关引擎 | [0005](docs/adr/0005-frontend-agnostic-engine.md) |
| 多格式输入 / 两阶段抽取 | [0001](docs/adr/0001-multi-format-input.md) · [0008](docs/adr/0008-two-stage-extraction.md) |
| 异步任务 / 租户与工作台 | [0009](docs/adr/0009-async-analysis-jobs.md) · [0013](docs/adr/0013-auth-tenancy-and-workspace-storage.md) |
| 投递闭环单事实源 | [0027](docs/adr/0027-delivery-loop-job-single-source.md) · [0028](docs/adr/0028-local-ingest-and-application-snapshot.md) |
| 角色化 LLM 节点 / 稳定性 | [0030](docs/adr/0030-role-based-llm-split.md) · [0032](docs/adr/0032-llm-provider-stability-and-streaming.md) · [0034](docs/adr/0034-llm-preflight-policy.md) |
| 密钥加密 / 推理预算 | [0035](docs/adr/0035-api-key-encryption-at-rest.md) · [0058](docs/adr/0058-reasoning-token-budget-for-structured-output.md) |
| agent 形态与三线门槛 | [0036](docs/adr/0036-agent-shape-a-only-mcp-deferred.md) · [0040](docs/adr/0040-three-gate-and-macro-vs-loop.md) |
| 探针主线与双线判据 | [0041](docs/adr/0041-pivot-skill-probe-mainline.md) · [0042](docs/adr/0042-pre-registered-reanchor-probe-clock-and-dual-line.md) |
| CSS 架构与主题 | [0043](docs/adr/0043-at-layer-single-file-css-architecture.md) · [0044](docs/adr/0044-token-single-namespace-convergence.md) · [0047](docs/adr/0047-supersede-adr0033-decision1-dark-default-teal-accent.md) |
| 加固 / 评分实证 | [0052](docs/adr/0052-freeze-window-hardening-and-layering-ratchet.md) · [0054](docs/adr/0054-score-evidence-hardening.md) |
| 岗位表同步 / 护栏面板 | [0055](docs/adr/0055-job-table-auto-sync-and-dedupe-precheck.md) · [0056](docs/adr/0056-drop-decorative-guardrails-panel.md) |

> 全量决策见 `docs/adr/`（编号 0001–0058；**0029 有意缺号**，见 ADR-0036）。
> 历史轨迹见 [`CHANGELOG.md`](CHANGELOG.md)，交付状态见 [`docs/STATUS.md`](docs/STATUS.md)。

---

## 核心实体

**Job Description (JD)**
一段岗位描述文本。来源是粘贴、文件或油猴摄入，从不服务端抓取。

**JD Profile**
JD 的结构化萃取：必会/加分技能、软技能、业务场景、年限、学历要求。

**Master Resume**
候选人的完整未裁剪简历，一切对齐版本的唯一事实源。
_Avoid_: 模板简历、多份主简历并行

**Resume**
以 PDF / DOCX / 纯文本提交的简历文件，系统抽取纯文本供 LLM 分析。

**Gap Report**
主简历 vs JD Profile 的结构化对比：缺失关键词、错位强调、可保留的强匹配项。

**Tailored Resume**
针对某个 JD 改写的主简历版本；每处改动都指回主简历原文，不新增事实。

**Diff**
一条原子改写建议：type（add/modify/remove）+ original + proposed + reason +
confidence + **provenance**（指向主简历原文）。

**无效建议 / noop Diff**
modify/remove 中 `original` 与 `proposed` 逐字相同者，移入 `invalid_diffs`，
不计入有效建议。

**Alignment**
「简历 vs JD → 建议改动」的过程。UI 中「已对齐」= 该岗位 final draft 的
`alignment_status` 为 succeeded，**不是**第六种投递状态。

**Diagnosis**（最小版）
不接 JD 的简历评估：0–100 分 + 技能 + 问题/建议。UI 中称「诊断分」。

**Match Score**
岗位与工作台展示的简历-岗位匹配度。主源是 Gap Report 的匹配分；跑过对齐
评估时用 Eval 的 `jd_match_score` 并标注「来自对齐评估」。
_Avoid_: 匹配率、fit score（与投递评估混淆）

**Eval Score**
LLM-as-Judge 的对齐质量：匹配度、有无编造、缺口覆盖比例。UI 称「对齐评估」，
默认关闭，可在设置页设全局默认、工作台按次勾选。
_Avoid_: 投递评估

**Report**
引擎输出：诊断 + 对齐 diffs + 元数据；完整版含 JD Profile + Gap Report +
Tailored Resume + Eval Score。

## 流水线阶段

1. **JD Ingestion**：客户端采集（油猴 Specific/Universal）或粘贴 JD 文本 →
   `POST /api/jobs/local-ingest` / `POST /api/jobs`。后端抓取已退役（2026-08-27），
   JD 链接由油猴捕获、从不服务端拉取。
2. **JD Profiling**：结构化萃取必会/加分技能、软技能、业务场景 → JD Profile。
3. **Gap Analysis**：主简历 vs JD Profile → 缺口/错位/强匹配。
4. **Dynamic Tailoring**：改写章节闭合缺口。**铁律：绝不编造**，只改写/重排/
   强调已有事实，逐 diff 追踪 provenance。
5. **Evaluation**（可选）：LLM-as-Judge 对比原稿与对齐稿，打分并标记编造。

## 设计原则

**Token Optimization Principle**
所有长文本走两阶段抽取：① 轻量 pass（正则/启发式）缩小范围；② LLM pass 在缩小
后的上下文上精修。适用于 JD 摄入、简历解析、差距分析，长文档省 60–80% token。

**Key Quality Attributes**
provenance（每个词可回溯）、可测试性（LLM 调用在 httpx 传输层可 mock）、
前端无关引擎（`engine.run()` 收 config + 输入、返回 Report、无 I/O）、
token 效率、极简依赖、可观测（stderr 警告 + 长操作进度标记）。

## 工作台

**Job Library**
租户隔离的岗位持久库：原始 JD、来源、地点、薪资、分类标签、投递状态。
其他工作台模块都从这里读。

**Job Classification**
岗位的多维标签：职能（backend/frontend/algorithm/data/client/ops/testing/
product/design/operations）、资历（intern/campus/junior/mid/senior/expert）、
自由技术/领域标签。LLM 产出，用户可编辑。

**Classification Pending**
分类 LLM 失败时落库的持久标志。岗位仍保存、显示琥珀徽章、可稍后重分类，
不阻塞摄入或批量导入。
_Avoid_: 失败行跳过、静默 unknown 分类

**Vocabulary Sync**
岗位库筛选器与编辑弹窗的职能/资历/状态选项来自 `/api/settings`；前端按页缓存，
设置 API 不可用时回落内置值。
_Avoid_: 硬编码下拉、每筛选一次请求一次设置

**Single-Job Workspace**
单岗位工作页：JD 分析 + 状态 + 从主简历版本生成对齐草稿。

**Final Draft**
某个岗位已采纳对齐稿的持久副本；刷新与重开不丢，另存为主简历不改原稿。
_Avoid_: 自动覆盖主简历、一次性草稿

**Rewrite Granularity**
改写强度：`fine`（微调，保结构措辞）、`medium`（重构，默认，保结构内改）、
`coarse`（重塑，允许整体重组）。

**Master Resume Diagnosis**
针对一份主简历的异步无 JD 流水线：0–100 分 + 技能 + 问题 + 建议；结果被
单岗位工作台复用（诊断缓存复用，rerun 跳过 diagnose 的 LLM 调用）。

**Application Status**
逐岗位的轻量生命周期标记：未投递 / 已投递 / 面试中 / Offer / 放弃。
_Avoid_: 流水线阶段、漏斗状态

**Interview Stage**
岗位的面试轮次标记（一面/二面/HR/offer 沟通）。与 Application Status 正交：
状态是漏斗桶，面试轮次是「面试中」内部的跟进锚点。

**Follow-up**
岗位的结构化跟进信息：自由文本下一步 + 可选到期时间 + 面试轮次；驱动到期提醒。
_Avoid_: 下一步（与 Batch Decision 混淆）、提醒条目

**Batch Decision**
批量对比矩阵里的逐岗结论（投/考虑/跳过）。UI 里与 Follow-up 共用「下一步」标签，
但是两件事。

**采纳率 (Adoption Ratio)**
近 7 天窗口内，保存定稿时被标 accepted 的 diff 数 / 定稿时 diff 总数
（`alignment_metrics` 按 tenant+日聚合）。零分母如实显示「—」，不伪装成 100%。
2026-09-10 起不再作驾驶舱 KPI 主数字（低服从率在核心位构成负向引导），
降级为卡内明细「采纳 Y/Z 条建议」。
_Avoid_: 拿 runs 当分母；把单岗历史状态当窗口采纳率

**已优化条目 (Optimized Entries)**
窗口内被采纳并进入定稿的 diff 总数，驾驶舱 KPI 主数字口径：单调只增，
强调「工具帮你改了多少」。与 Aha 指标同源但口径更宽。
_Avoid_: 与采纳率混用（一个量、一个率）

**无建议（badge）**
零可用产出对齐的终端语义，按证据分型（ADR-0041 决定 5 / #111）：新增
`usable_diffs` 计数（noop 过滤与拦截后的有效 diff 数）。**有缺口 ∧ usable=0 →
`failed` + reason `no_output`**（可重跑）；**无缺口 ∧ usable=0 → 保 `succeeded`**，
徽章「无缺口 · 无需改写」，不得渲染为「已对齐」。驾驶舱「完成对齐」分子只数
`usable_diffs≥1`，「100% 完成率」从制度上不可能出现。
_Avoid_: 拿「跑完没报错」当「产出了价值」；把「无缺口」当可信结论
（小模型摆烂与真无缺口同形，文案必须带换模型重跑引导）

**节点预检 (LLM pre-flight probe)**
对齐排队前对实际服务节点做的 5s 最小连通 + 鉴权探测。确定性 HTTP 失败
（401/402/403）对所有节点硬拦截为 422 + 引导；本地节点（Ollama / localhost）
的网络错误/超时同样硬拦截；远程节点的网络错误/超时保持非阻塞，由
`last_alignment_error` 延迟透出。

**单岗对齐 / 批量对齐 / 批量对比矩阵**
单岗 = 看板卡片按 `alignment_status` 显示的按钮，直接 POST
`/api/jobs/{id}/workbench`（默认 medium + 最近主简历）。批量 = 看板
「批量对齐」，走 `/api/batch-align`（`selector="pending"` 覆盖 idle/failed/卡死
queued），结果进「批量对比矩阵」。两者共用同一排队与并发上限（每租户同时最多 1 个）。

**简单模式 / 专家模式**
设置页双视角。简单模式只保留连接 AI 所需最小配置（服务商/模型/API Key/测试连接）；
专家模式暴露节点管理、成本护栏、自动化规则与词表。无节点时默认简单模式。
_Avoid_: 用「高级设置」折叠代替真双模式

**投递结果归因 (Application Result)**
对已投递定稿的结局标注：过筛通过 / 简历挂筛 / 暂无回音 / 其他。可选字段，
不改变投递状态机；是验证「对齐是否有效」的原始数据。
_Avoid_: 当作第六种投递状态

## 摄入

**JD Source**
一切把岗位引用变成 JD 文本的来源：粘贴、文件、油猴摄入。前端一律产出同一份
纯文本进流水线。

**Site Handler**
已知招聘站点的站点级抽取策略；未知站点走通用抽取而非失败。

**双模摄入 (Dual-Mode Ingestion)**
客户端 JD 采集策略：实习僧高精度 Specific 模式 + 任意职业站点划词的 Universal
模式（带 document.title 与页面 URL）。两模式都 POST 到 local-ingest。
_Avoid_: 反爬对抗、后端常驻无头浏览器

**本地摄入端点 (Local Ingest Endpoint)**
`POST /api/jobs/local-ingest`，本地专用建岗端点。请求路径只做确定性解析，
新岗位标 `classification_pending=1`，重复岗位绝不覆盖已有 Job。

**Local Ingest Token**
local-ingest 的 `X-ResuAlign-Token` 头密钥。服务首次启动生成，设置页可复制/重置，
油猴插件提示一次、401 时再提示。
_Avoid_: 免鉴权信任 localhost、用户自填双端 token

**岗位表同步 (Job Table Sync)**
用户维护的岗位表 CSV 的服务端拉取路径：`job_table` 设置存文件路径（+ 可选 JD
目录），后台循环按间隔重读，只加库中从未见过的行。重读未变表对库与 LLM 账单
都是 no-op（去重检查先于分类）。无投递链接的行用稳定 `jobtable:` 身份
（公司/标题/地点），改写 JD 正文不会造重复。
_Avoid_: 网络爬取岗位表、按文件名判重

## 投递闭环

**投递闭环 (Delivery Loop)**
求职主线：岗位库 → 工作台对齐 → 记录投递 → 安排跟进 → 终态收口。Job 是全链
唯一事实源。
_Avoid_: Application 双轨记录、投递记录面板

**状态生命周期 (Status Lifecycle)**
半约束状态策略：前进自动填时间戳并清后续字段；回退需显式确认并清陈旧字段；
终态保留历史时间戳。
_Avoid_: 自由改状态

**记录投递 (Record Application)**
一键动作：盖当天 applied_at 并把 Job 移到「已投递」；幂等，绝不回退到更早阶段。

**投递定稿快照 (Applied Draft Snapshot)**
记录投递时原子捕获的不可变副本（final_draft + match_score + 主简历引用 +
applied_at）。append-only：重录追加新 `version_index` 行而非覆盖。面试回溯看快照，
不看可变定稿；旧记录无快照时回落当前 final_draft 并给「早期投递版本」警示。
UI canonical 叫法：**投递快照**。
_Avoid_: 对齐快照、当前定稿冒充投递版、快照可被覆盖

**安排跟进 (Schedule Follow-up)**
一次捕获面试轮次 + 下一步 + 到期时间，同步更新 Job 与其活动提醒。

**历史峰值漏斗 (Historical Peak Funnel)**
按最强历史证据（offer_at > applied_at > status）推导的漏斗，撤回的岗位保留
过去的阶段计入。

**待跟进提醒 (Follow-up Reminder)**
只对活动阶段（已投递/面试中）显示的到期提醒；终态自动停提醒。

**直达投递 (Direct Application)**
打开 Job 的 source_url 让用户提交对齐稿；缺链接走补链接流程。

## 平台与数据

**Analysis Job**
Web/API 层拥有的异步对齐运行：queued → running → succeeded/failed，最终持 Report。
持久在 SQLite、按租户隔离；重启中断的 queued/running 任务落到明确 failed 态。
_Avoid_: request、task

**User**
持邮箱与哈希密码、拥有一个租户工作区的账号；鉴权用不透明 bearer token +
哈希会话记录。

**Tenant**
岗位、主简历、投递的作用域边界。MVP 里每个 user 是一个 tenant；跨租户读
表现为资源不存在。

**Master Resume Version**
主简历的不可变快照。更新追加新版本；回滚把当前版本指回去但不改写历史。

**Application** *(legacy)*
已休眠的逐租户记录，曾钉住主简历版本与分析任务。投递闭环不再经它追踪，
Job 是唯一事实源（ADR-0027）。

**Stage Progress**
每个流水线阶段前发出的通知（阶段名 + 人类可读消息）。引擎保持 I/O-free，
把进度交给回调而非打印。

## 基准与配置

**Benchmark Case**
合成简历 + JD 对，带具体期望改写方向与 provenance 注记；无 PII、可离线回归。

**Expected Direction**
挂在 Benchmark Case 上的具体改写目标，供回归 harness 量关键词覆盖。

**Case Tag**
Benchmark Case 上的可选元数据（角色/领域/语言），留给未来的子集选择，不改 case schema。

**ResuAlignConfig**
持全部运行时配置的 dataclass（provider/api_key/model/base_url 等）。来源：
① 显式 kwargs（编程 API / Web 层）；② `.env` + 环境变量回落（CLI 便利）。
CLI 专属 flag（如 `--output-dir`）留在 CLI 层，调用引擎前翻译进 config。

## Agent 化与探针

**指挥台 (Command Deck)**
产品内的 agent 操作员入口：一句自然语言驱动既有流程，与工作台并列、同数据同队列。
定义特征只有「单入口 + 自然语言路由」；**执行期是否由模型逐步决定下一步不属于
它的定义**（ADR-0040）。
_Avoid_: 聊天机器人；把「要不要上指挥台」偷换成「要不要上循环」

**预设流 (Macro)**
服务端预先定好参数与顺序、一次调用跑完的编排；执行期不需判断中间结果。
四个招牌场景（挑高分/归因/批量对齐/周复盘）都属这一型。与**决策循环**相对。

**决策点 (Decision Point)**
下一步动作取决于运行时观察、且该观察无法预先枚举成调用参数的位置。审计判据：
某步若在 30 次重放里能被一条确定性规则复现同一选择，它就不是决策点。

**决策循环 (Explicit Loop)**
执行期由模型逐步决定下一个工具调用的编排形态。实现顺序是先做厚预设流 + 单入口
路由，循环按实测决策点再决定。
_Avoid_: 把「agent 项目」默认等于「有循环」

**三线门槛 (Three Gates)**
Phase A 开工前三道灯（ADR-0040）：能力线 = Phase 0 过线；地基线 = 对齐成功率
回到可接受线 + 零 diff 假成功被 CI 锁死；需求线 = 合格例 ≥3。三线全亮才开工。

**合格例 (Qualifying Case)**
需求线计数单位，三条全满足才算：同一简历 ≥3 轮「改→评→改」 ∧ ≥1 轮有 diff
采纳 ∧ ≥2 轮的触发原因是上一轮评测结论。第三条是因果链条款。狗食数据计入。
_Avoid_: 拿「同一简历跑三次」凑数（缺采纳与因果链）

**授权档位 (Approval Tier)**
agent 可用工具三档：读档自由；写档只能经既有入口排队；审批档（采纳 diff、
定稿、覆盖主简历、导出、删除）只能提议，人确认后生效。

**轨迹评测 (Trajectory Eval)**
评 agent 一次会话的完整步骤序列而非只看终态：任务成功率、工具调用正确率、
步数与成本上限。放 `benchmarks/agent/`，接 CI。核心指标是**无编造率**
（会话中不含无出处内容的比例，对抗用例下必须 100%）。

**轨迹报价 / agent 预算卡 (Trajectory Quote / Budget Card)**
含写档步骤的 agent 指令执行前出示两行预演卡：决策调用行（agent 桶余量）+
引擎调用行（与按钮路径共享的每日池）；数字算术派生，不许模型口算。agent 桶是
循环决策调用的专属账本（起点预留、步界结算、退还），agent 派生的引擎调用不在
账上。报价是事前知情，审批档是事后生效，两道门互不替代。

**门禁摘要 (Gate Report)**
skill 验证器每次运行输出的一行机器可读汇总：`N diffs / K blocked
(missing/fabricated/noop) / sha256`。探针判据的唯一取证形式——非作者首跑报告
必须附此行才算数。
_Avoid_: 口头「我用过了」当首跑；agent 转述或重打摘要（必须原样粘贴脚本输出）

**合格例取证 (Qualifying Evidence)**
验证器落盘的 append-only JSONL 运行日志，证明因果链：第 n+1 轮 trigger 必须指向
第 n 轮复评结论。轮次连续性由验证器自己判定并写入
`chain{prev_round,cites_prev}`；`resume_sha256` 跨轮不变即「同一文本重放」，
不算迭代证据。

**skill 探针 (Skill Probe)**
掉头期主线：独立公开仓库（`truetailor`）= prompt skill + 单文件确定性验证器
（stdlib 零依赖），在 app 之外验证「逐条可溯源改写」的需求。仓库已公开（MIT），
故 `gate.py` 与黄金 fixtures 的**唯一事实源在上游**；主仓持 vendor 副本，由
`tests/fixtures/gate/VENDOR.json` 哈希清单 + `tests/platform/test_skill_vendor_lock.py`
锁定，改规则须先改上游再同步。

**冻结令 (Freeze Order)**
探针期内 app 一切新功能冻结（agent 化 Phase A/B、商业化 PRD、扩展期二、托管
demo），只留地基修复 #110/#111 与探针包两类工作。解冻条件唯一：探针判据「过」。
ADR-0042 决定 6e 明确自用线推进期间冻结令继续有效。

**探针线 / 自用线 (Probe Line / Dogfood Line)**
掉头期判据的两条**独立**线（ADR-0042 决定 3），各自取证、各自判定，不许互相
顶替。探针线 = 非作者首跑 ≥5 例附门禁摘要行，或 1 例外部完整合格链 = 过；
≥100★ 或社区二创 = 强信号；4 周后 <2 例 = 证伪。自用线 = 合格例 ≥3，取证走
JSONL，输入必须是真实投递过的岗位 JD。

**分发未执行 (dist_not_executed)**
ADR-0042 决定 2 的判据状态：四渠道 outreach 未在 2026-09-23 24:00 前全部发出时
登记为此态——时钟不启动、判据保持 PENDING、观察窗不开启。它把「没发出去」与
「发了没人要」在制度上分开，**不是证伪**；处置 = 先执行分发。
_Avoid_: 把分发未执行读成探针证伪；以「反正要重锚」为由拖延分发而不登记
