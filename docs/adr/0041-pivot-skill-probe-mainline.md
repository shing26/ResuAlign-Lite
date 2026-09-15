# 0041 — 掉头：skill 探针升主线，app 冻结新功能；判据、终态剧本与归档条款

Status: accepted (2026-09-15 grilling 访谈 11 项裁决全部落定，用户逐题确认)

> 2026-09-16 注记（ADR-0042，预注册式重锚）：本 ADR 决定 4 的**时钟起点**与
> 决定 9/10 的**终态剧本**经限定修正——时钟起点改为「四渠道 outreach 全部
> 发出当日」，09-23 前未发出则登记 `dist_not_executed`（时钟不启动、判据
> PENDING、**非证伪**）；判据拆为「**探针线 ∥ 自用线**」两条独立线；项目级
> 归档条件改为「**探针线证伪 ∧ 自用线 = 0**」。**决定 4 的三档数值一字未改**，
> 本 ADR 其余 8 项决定（冻结令、探针形态、发布策略、#111 语义、四步闭环、
> demo 押后、排期、漂移锁）原样有效。修正理由：转公开 17 小时后实测零曝光
> （stars/forks/watchers/discussions 全 0），原「转公开即开始暴露」的隐含
> 前提被证伪，属测量错误而非方向错误。

## 背景（证据链，非估计）

- 自身基线（`data/jobs.db` 实测 2026-09-15，ADR-0040 复核一致）：59 租户
  中 58 个为自动化测试流量；唯一真人租户 `local` 11 条 job 且中断于
  08-17；`alignment_metrics` 全表 runs 55 / saves 1 / diffs 9 / **accepted 1**；
  ≥3 版简历 0 份。核心假设（真人反复对齐并采纳）从未发生。
- 市场调研（`docs/market-research-competitors-2026-09-15.md`）：问题域被
  两侧独立验证——JobCtrl（87★，本地优先 + evidence ledger + fabrication
  gates fail closed，与本项目定位重合 ~90%）证明命题真实，也证明瓶颈在
  分发不在功能；resume-tailoring skill（739★/377★/119★/中文 63★）证明
  核心能力可被 markdown 文件吸收大半。AIHawk（31.5k★）已从投递产品
  转型 agent 基建。
- 判定：方向不是牛角尖，形态押注是；真瓶颈 = 「陌生人 30 秒跑通首次
  对齐」。在探针出结论前，app 侧一切新功能（agent 化 Phase A/B、商业化、
  扩展期二）边际价值≈0。

## 决定（11 项，逐题裁决记录）

1. **全量主线**：app 冻结一切新功能；只保留地基修复 #110/#111 + 探针与
   视频两类工作。（甲，否决 70/30 并行与纯支线）
2. **探针形态 = prompt skill + 单文件确定性验证器**：SKILL.md 承载方法论，
   每条 diff 必须过 stdlib 零依赖验证器才算数——**fabrication gate 是代码
   不是承诺**，这是对纯 prompt skill 生态（甲案）与挂引擎 CLI（乙案）的
   双双否决。
3. **发布策略**：英文为主（README + SKILL.md 正文），一份正文
   Claude Code / Codex 双入口；独立公开仓库（默认命名 `truetailor`，
   改名零成本）+ MIT；发布即开 first-run feedback discussion
   （"I expected X and saw Y" 格式，抄 JobCtrl #797）。渠道：GitHub +
   HN Show + r/ClaudeAI + 即刻/V2EX。
4. **判据（行为判据，4 周时钟自发布日起算）**：
   - 过 = ≥5 例非作者首跑报告（附门禁摘要行，贴得出即真跑过）
     或任意 1 例外部完整合格链；
   - 强信号（提前结束观察）= ≥100★ 或出现非本项目发布的社区二创；
   - 证伪 = 4 周后非作者首跑 <2 例。
   - ADR-0040 需求线 (a) **原样保留**，探针不替代它；作者用 skill 跑出的
     因果链狗食数据按 (a) 裁决计入合格例，取证靠验证器 JSONL 运行日志。
5. **#111 终端语义 = 按证据分型（甲乙各取其半，否决丙自动重跑）**：
   新增 `usable_diffs` 计数（无新状态）；**有缺口但 usable=0 → failed +
   reason `no_output`**（质量失败就该红，可重跑）；**无缺口且 usable=0 →
   保 succeeded**，徽章「无缺口 · 无需改写」（≠已对齐）+ 换模型重跑引导
   （7B 摆烂与真无缺口数据同形，文案必须留口）；驾驶舱「完成对齐」分子
   只数 `usable_diffs≥1`，100% 从制度上不可能出现；CI 锁 FakeLLM 全 noop
   剧本徽章 ≠「已对齐」。实测注记：现库 51 条零 diff succeeded **全部**
   是 gap 空型，「有缺口零产出」型目前只在 CI 剧本中存在。
6. **skill v1 = 四步闭环**：录入（简历+JD 粘贴）→ 差距 → 带溯源改写 →
   验证器门禁；随后一步 agent 复评（before/after 匹配度 + 剩余缺口），
   JSONL 落 `round + trigger=eval` 字段以支撑 (a) 合格例取证。诊断段
   （ATS 分数）整段不进 skill，留在 app。
7. **托管 demo 押后**：探针期 app 零分发投入，README 顶部一行
   "the 30-second version lives in <skill repo>" 引流；探针通过后 demo 以
   「skill 用户 → app 的转化器」身份重新立项。探针包含 90 秒屏幕视频：
   真实跑一次 skill，特写验证器当场拦下一条编造 diff。
8. **排期**：周 1 验证器剥离（>1 天不通即切换为按门禁语义 ~300 行独立
   重写，fixtures 裁决不变）+ 黄金 fixtures + SKILL.md 初稿 + JSONL
   schema，同时 #110 派后台 agent（只读）；周 2 自我狗食（兼视频素材）→
   按 #110 归因修订提示词 → 建仓发布 outreach，时钟启动；周 3-6 观察窗
   只做回反馈/修首跑摩擦/#111 实现。工时 ≈70% 探针 / 30% 地基。
9. **过 → (乙)**：skill 升主线（v1.1 加 DOCX/PDF 导出、批量岗），app 降为
   可选持久层（只保留看板/复盘/档案回填这些 skill 没有的）；否决
   「解冻回原 roadmap」（甲）与双主线（丙）。
10. **死 → 归档条款（合同，不复议）**：证伪 → skill 线冻结、回 app-only、
    不开第三条线；**证伪 ∧ (a) 合格例 = 0 → 项目 README 挂 maintenance
    声明、全 Phase 冻结**。触发条件白纸黑字，事后不许凭感觉谈判。
11. **漂移锁三道**：fixtures（编造/救回/noop 三类剧本）为唯一事实源——
    skill 仓建立前暂居主仓 `tests/fixtures/gate/`，建立后迁移并以 vendor
    副本 + 主仓 pytest 断言两侧裁决一致；验证器 I/O 契约定死为
    `resume.md + diffs.json (+ jd allowlist)` → 逐条裁决 + 一行机器可读
    门禁摘要（`N diffs / K blocked / sha256`）+ append JSONL。

## 与既有 ADR 的关系（不推翻，注记）

- **0036**：不冲突。探针是需求探针与分发渠道，不是「MCP 外部消费面」；
  MCP 后置与其 B 复活判据原样有效。
- **0038**：agent 作为 Pro 旗舰的叙事位不变，但 Phase A/B 排期被本 ADR
  冻结（需求线 (a) 仍为 0，三线门槛未亮）。
- **0040**：三线门槛制保留；本 ADR 只改「先做什么」——地基线两票继续，
  能力线 Phase 0 结论悬置到探针出结果。
- **商业化 PRD（draft）**：随 app 冻结一并冻结，不推进不修订。

## 后果

- 本 ADR 是掉头期的唯一 roadmap；任何 app 新功能请求默认引用冻结令
  拒绝，解冻条件 = 判据「过」且按决定 9 的形态重立项。
- 验证器剥离产出的 `gate.py` 同时是主仓门禁的 stdlib 化解耦件，
  反哺后续引擎独立性问题（模块报告 api/__init__ 枢纽债不在此列）。
- 已知盲区照旧：Jobscan/LoopCV/超级简历定价与留存、BOSS 站内 AI 覆盖面
  未核实；不改变本判定。
