# 市场调研：ResuAlign vs 商业/开源同类——差距、差异与方向检验

> 日期：2026-09-15 ｜ 方法：GitHub API 实测（stars/pushed_at/README 原文）+
> 竞品官网直连抓取。每条 claim 标注来源；未能核实的数字显式标
> 「未核实」，不引用二手博客转述。

## 0. 结论（一句话）

**问题空间是真的、方向被多方独立验证；错的是形态与打法**——
"本地全栈应用 + 自带 key" 这个形态正在被两类玩家从两侧夹击：
云 SaaS（分发碾压）和通用 Agent 的 skill 文件（工程吸收）。
在核心漏斗只有 1 条真实采纳记录（见 §4）的情况下继续加
agent 化/商业化工程，是钻牛角尖。

## 1. 开源格局（GitHub API 实测，2026-09-15）

| 项目 | Stars | 最近推送 | 定位 | 与 ResuAlign 的关系 |
|---|---|---|---|---|
| reactive-resume/reactive-resume | 42,856 | 2026-09-12 | 隐私向简历构建器（表单+排版，无 JD 对齐） | 不同象限：它做"写出来"，不做"对齐" |
| feder-cr/AIHawk | 31,573 | 2026-09-14 | **已从自动投递转型为反检测浏览器/MCP server**（官方 description 原文） | 自动海投赛道头部已弃守产品形态、转做 agent 基建 |
| speedyapply/JobSpy | 4,283 | 2026-02-18 | 多平台岗位爬虫库 | 印证「岗位获取」才是开源最大流量口；ResuAlign 退役爬虫（ADR-0028）= 放弃了这个入口 |
| **ebarti/JobCtrl** | 87 | 2026-09-13 | **本地优先求职应用：evidence-backed fit scoring、truthful tailoring、approval-gated apply**（官方 description 原文） | **定位孪生**，见 §2 |
| varunr89/resume-tailoring-skill | 739 | 2026-03-01 | Claude Code skill：JD 定制简历、事实完整、置信度选料、3-5 岗批量 | **同一核心价值 = 一个 markdown 文件**，star 是 ResuAlign 外部用户数的无穷倍 |
| proficientlyjobs/proficiently-claude-skills | 377 | 2026-03-12 | 求职全家桶 skills（简历/求职信/tailoring） | 同上，skill 生态挤满该问题 |
| amanattar/resume-tailoring-skill | 119 | 2026-03-18 | Claude skill：用既有 markdown 简历按 JD 定制 | 同上 |
| smile-xyy/resume-tailor | 63 | 2026-08-13 | **中文 skill：本地优先、证据可追溯、不自动投递、不编造项目/公司/学历/时间**（README 原文） | ResuAlign 的立场声明被中文 skill 逐句复刻 |
| 23aaaa/jobfill | 28 | 2026-03-17（静默半年） | Chrome 扩展网申一键填表（牛客/智联/BOSS/官网），本地简历数据 | PRD §2.2 引用的竞品，已停更 |
| YIKUAIBANZI/job-hunter | 28 | 2026-07-12 | Claude skill 形态的投递自动化 | skill 化的又一例 |
| Jackychen-12/Career-Search | 8 | 2026-09-14 | 中文 AI 全链路求职助手（匹配/面试/投递追踪） | 中文同类 app 化尝试，量级很小 |
| 333kjp/ai-job-search | 2 | 2026-07-14 | 自托管 AI 求职：智联/猎聘采集+六维评分+**有出处核查**的简历 | 「出处核查」在中文开源已是共识词 |

**读法**：star 是开发者注意力代理，不是消费者需求证明；但
「同一问题在 skill 形态下的 star 数量级 > app 形态」这个对比，
对"值不值得自建全栈"是有效信号。

## 2. 重点样本：JobCtrl（与 ResuAlign 定位重合度 ~90%）

来源：README 原文 + repo API（created 2026-04-30，AGPL，pushed 2026-09-13）。

- 主张逐条对照：`~/.jobctrl/` 单 SQLite、无账号、默认不出本机
  （= 本地优先）；「每个分数有逐要求证据台账、每条简历 bullet 溯源到
  profile、**fabrication gates fail closed**」（= provenance 硬门禁）；
  「dry-run 不提交、live 提交需绑定已审材料的显式批准、绝不重复提交」
  （= 审批档；差别：它做投递执行，ResuAlign 红线不做）；
  「discover → enrich → score → tailor → review → apply 全流程、
  每日花费上限、可断点续跑」（= 流水线 + 成本护栏）。
- **它比 ResuAlign 多做的**：岗位发现管线、受审批的自动投递、
  合成数据在线 demo、签名 macOS 安装包 + Homebrew tap、
  公开测试召集（discussion #797）。
- **它比 ResuAlign 少做的**：A4 预览/逐条 diff 卡/看板/复盘/回填扩展
  （ResuAlign 产品完整度更高）。
- **但它创建至今 5 个月、star 87、仍在 early access 找测试者**。
  结论：孪生定位验证了问题真实，也验证了**这条路的瓶颈从来不是
  产品完整度，而是分发与首批用户**。

## 3. 商业格局（官网直连，2026-09-15）

| 产品 | 定价（核实状态） | 打法 | 来源 |
|---|---|---|---|
| Teal (tealhq.com) | 定价页出现 $13/$29/$79 三档（tier 名称未核实） | 求职全家桶 web freemium：简历构建+岗位跟踪+AI | 官网 /pricing 抓取 |
| Jobscan | 未核实（页面 JS 渲染） | 简历 vs JD 的 ATS 匹配分老牌玩家 | 官网 |
| Resume Worded | 未核实 | 简历评分/改写建议 | 官网 |
| LoopCV | 未核实 | 首页标语「Auto-Apply to 1,000+ Jobs」+ 企业/API 多客群 | 官网 |
| 超级简历 WonderCV | 会员制（价目未核实） | **自报 30,000,000+ 用户**；AI 解析 JD、关键词密度检测、ATS 兼容校准、5000+ 模板、微信扫码即用 | 官网首页文案（自报数字，营销口径） |
| Offerbiu | 免费同步（未见付费墙） | 大学生秋招投递 CRM：岗位/简历版本/JD 分析/AI 匹配/面试跟进 | 官网首页 |

**空位检验**：PRD §2.2「逐条可溯源改写无直接竞品」在海外**已不成立**
（JobCtrl 的 evidence ledger + fail-closed gates 是同一主张，英文市场）；
在国内仍成立，但国内头部（超级简历）用「免费+模板+AI 生成」拿到了
数量级更大的用户，说明大众市场当前为「省事」付费，不为「可溯源」付费
——可溯源是信任门槛，不是获客钩子，这个次序 PRD 押反了。

## 4. ResuAlign 自身基线（对照组，`data/jobs.db` 实测 2026-09-15）

- 59 租户中 58 个为单 job 零 diff 的自动化测试流量；唯一真人租户
  `local` 11 条 job，集中于 2026-08-03→08-17。
- `alignment_metrics` 全表：runs 55 / saves 1 / diffs_total 9 / **accepted 1**。
- 62 条 `succeeded` 中 51 条零 diff（假成功）。
- ≥3 版简历：0 份。
（与 ADR-0040 记录一致，本次复核无变化。）

## 5. 差距/差异总表

| 维度 | ResuAlign | 领先者水位 | 差距性质 |
|---|---|---|---|
| 引擎深度（provenance/降级/熔断/状态机） | 强 | JobCtrl 同理念；skill 系无引擎 | **超配**：无用户为深度付费 |
| 产品完整度（看板/复盘/A4/导出/扩展） | 强 | 各家 web 版相当或更强 | 持平 |
| 分发（demo/安装包/零门槛首跑） | 近 0 | JobCtrl 有 demo+brew；SaaS 有扫码即用 | **最大差距** |
| 需求证据（非作者真人） | 0 | 超级简历自报 3000 万；JobCtrl 公开招募测试者 | 数量级 |
| 岗位获取 | 已退役爬虫，靠用户录入 | JobSpy 4.2k★、LoopCV/Teal 内置聚合 | 主动放弃的入口 |
| 形态适配 | 独立全栈 app | 同价值能力已可免费装在用户已有 agent 里 | **结构性风险** |

## 6. 方向判定

1. **问题域正确**：本地优先 + 证据化对齐被 JobCtrl（app 形态）与
   739★/377★/63★ 三个 skill（agent 形态）从两侧独立验证。不是牛角尖。
2. **形态押注错误**：skill 生态证明「对齐+防编造」的核心价值可以被
   一个 markdown 文件承载大半；自建 app 的剩余价值只有「结构化持久 +
   看板/复盘 + 回填」，而这三者恰好是实测中**使用证据最少**的部分。
3. **当前阶段的真瓶颈**：不是任何未写的代码，而是「一个非作者的
   陌生人 30 秒内跑通首次对齐」。ADR-0040 需求线 (a) 的合格例
   至今为 0，所有 Phase A/B 讨论都悬空。
4. 建议见对话结论（skill/MCP 作为需求探针 + demo 分发优先 +
   冻结内部工程）。

## 附：本次调研的已知盲区

- 未核实 Jobscan/Resume Worded/LoopCV/超级简历的具体价格与用户留存数据
  （JS 渲染/需登录）；未核实 BOSS 直聘站内免费 AI 功能的实际覆盖面。
- star 数与官网自报用户数均有各自的偏差方向（前者测开发者，后者是营销），
  不能直接互比。
- 中国 C 端付费意愿仅由「超级简历免费打法 + Offerbiu 未见付费墙」间接推断。
