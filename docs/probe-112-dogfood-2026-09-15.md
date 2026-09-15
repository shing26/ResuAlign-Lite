# 探针周 2：truetailor 自我狗食轮记录（#112 前置）

> 日期：2026-09-15 ｜ 执行者：作者本人充当 host agent，按
> `skill/SKILL.md` 四步闭环逐步执行 ｜ 现场：`.scratch/truetailor-dogfood/`
> （`resume.md` + `jd.txt` + `gap.json` + `diffs_r{1,2}.json` +
> `tailoring.jsonl`）｜ 取证：验证器 JSONL 运行日志（ADR-0041 决定 4）

## 1. 这一轮在判据里算什么

ADR-0041 决定 4：作者用 skill 跑出的因果链狗食数据**按需求线 (a) 计入
合格例**，取证靠 JSONL。本轮给出的是 **1 例两跳合格链**：

```
{"ts":"2026-09-15T12:48:38+00:00","round":1,"trigger":"manual","diffs":6,"usable":5,
 "blocked":{"missing":0,"fabricated":1,"noop":0},"resume_sha256":"d9a4e197…",
 "chain":{"prev_round":null,"cites_prev":true}}
{"ts":"2026-09-15T12:48:39+00:00","round":2,"trigger":"eval:round1","diffs":3,"usable":3,
 "blocked":{"missing":0,"fabricated":0,"noop":0},"resume_sha256":"88f04b27…",
 "chain":{"prev_round":1,"cites_prev":true}}
```
（`chain` 是本轮修订 R5 新增字段：日志尾部由当前发布版验证器重跑生成，
不是旧版 gate.py 的产物。）

两行 `resume_sha256` 不同 = 第二轮的门禁确实跑在「应用首轮采纳项之后」的
候选稿上，不是同一段文本重放。轮次链字段（`round` + `trigger` 引用上一轮）
就是「我们迭代改进过这份简历」的可核对版本。

## 2. 输入与产出

- 输入：作者真实主简历（Python/AI 应用方向）+ 阿里 2027 届 AI 应用研发
  工程师 JD。零外部信息，未联网。
- Step 1 `gap.json`：5 条 missing_keywords（全部满足「简历已实证才准点名」
  硬线）、2 条 misaligned_emphasis、5 条 strength_matches。
- Step 2 首轮 6 条 diffs，其中 **r1d5 是作者故意投手喂给门禁的假建议**
  （「搭建向量检索链路…日解析简历 10 万份」——简历里既无向量检索也无 10 万）。
- Step 3 门禁裁决：`GATE: 6 diffs / 1 blocked (missing=0, fabricated=1,
  noop=0)`，r1d5 的理由行是「数字 10 在简历原文中无依据」。
- Step 4 复评 → 采纳 5 条 → `resume.r1.md` → 二轮 3 条全过。

### EVAL round 1（复评原文，二轮 trigger 引用的就是这一段）

缺口①标题未点出 AI 应用/Agent 方向（JD 首屏扫描路径）；缺口②JD 职责 6
「降级策略保障稳定性」——简历只有「恢复机制」，降级叙事未点出；缺口③JD
职责 5「沉淀方法论与可复用组件」在简历里被「注重工程积累」一句自我低估。
三条都在二轮转成 diffs。仍未闭合的真缺口：JD 要求的 RAG/知识库与
Java 生产级工程经验，简历无实证 → **按硬线记为「不能诚实 tailor」，
不进改写目标**。

## 3. 摩擦日志 → 提示词/验证器修订（R1–R7）

| # | 现场摩擦 | 归因来源 | 修订 |
|---|---|---|---|
| F1 | SKILL.md 写 `python gate.py`，但 host agent 的 cwd 是用户工作目录，gate.py 在 skill 目录里 → 首跑必踩路径坑 | 狗食 | **R1** 命令改为「本 SKILL.md 同目录的 gate.py」绝对路径写法，Claude Code / Codex 各给一种变量 |
| F2 | 铁律 1 声称「新数字、雇主、工具、项目、结果都会被门禁拦下」——代码只保证数字与非 CJK 专名，中文假词（「向量检索」）实测未被内容校验拦下，靠的是 add 型缺支持句/引文定位 | 狗食（本轮 r1d5 只被「10」抓住） | **R2** 铁律改成可核对的分层表述：门禁能证明什么、不能证明什么；README 出「gate 强制 vs skill 约定」两栏 |
| F3 | #110 静默降级 20%：qwen2.5:7b 批量 8 连跑各出 1 diff，状态机全绿、价值贴地板 | #110 §2 | **R3** 输出地板规则：二轮候选必须**逐条挂在 gap.json 的缺口项上**，缺口≥3 而 usable<3 时按同一 gap 清单重跑 Step 2 一次（上限 1 次），且明文禁止为凑数编造——「薄报薄」是合格，「灌水」是失败 |
| F4 | #110 假成功 20%：succeeded 但 usable=0；「7B 摆烂」与「真无缺口」数据同形 | #110 §2 + 决定 5 | **R4** Step 3 收尾话术按决定 5 分型：有缺口而 usable=0 → 明说这是本轮质量失败（可重跑/换模型）；无缺口且 usable=0 → 「无缺口 · 无需改写」，**绝不等同「已对齐」** |
| F5 | #110 远程 30B 在「JD 画像与差距分析」阶段超时 2 例（60–72s） | #110 派单 B | **R6** 上下文节约：简历只通读一次、`gap.json` 控制在 ~15 行内、回复里不整段转贴简历，长简历分段只引相关段 |
| F6 | 轮次链靠自觉：`--round/--trigger` 有默认值（1/manual），漏传就把第二轮写成第一轮 | 狗食 | **R5** 验证器 JSONL 增 `chain` 块（`prev_round` / `cites_prev`），SKILL.md 要求显式传参并在回复里引用上一轮 EVAL 结论；摘要行格式不变（契约锁） |
| F7 | SKILL.md 声明 `proposed <= 250 chars`，验证器不校验——文案许了代码不兑的诺 | 狗食 | **R7** 保留为「skill 侧写作纪律」，但措辞明确它不是门禁项；门禁只报它真正执行的四类裁决 |
| F8 | **英文专名编造不拦**：合成例里 `Built Kafka-backed ETL jobs…` 直接 `usable/verified`；`_noun_candidate` 只认全大写与内部大写（QPS/FastAPI），句中 Title-case 的 Kafka/公司名一律放过 | 狗食（合成例）+ 自家测试套件实锤 | **R8** 门禁补「句中大写词即专名」判定（句首大写与常见英文词豁免），`Kafka-backed` 这类复合词拆词回溯；`gate.py` 与 `tailor.py` 同源改，新增英文黄金剧本 e2/e3（拦）与 e4/e5（不误杀）双向锁死 |

### 3.1 F8 的分量

这不是边角优化：探针的一句话卖点就是「门禁是代码不是承诺」，而英文生态的
第一个攻击动作必然是「往英文简历里塞一个没用过的工具名」。实测两处实锤：

- 合成例 `demo-d5-fabricated-stack`（Kafka）修订前 `usable/verified`；
- 主仓 `tests/test_jd_preanalyze_rewrite.py` 里躺着一模一样的剧本：
  简历只有 `Python dev built services.`，改写建议 `Built services using Java`
  被断言为 `provenance_state == "verified"`——**测试本身在保护这个漏口**。

修订后两侧行为一致，该断言改为 `fabricated`，并新增
`test_tailor_blocks_unsourced_english_proper_noun` 把它钉成回归例。
豁免表（月份/星期/职级等常见大写词）与「句首大写不算专名」写进
`docs/gate-contract.md` 的已知边界，README 也照实说明，避免下一次有人
为了少几个误拦把规则再放宽回去。

## 4. 已知门禁边界（写给 README，不藏）

1. 内容级校验看**数字**与**拉丁专名/术语**（缩写、混合大小写、以及 R8 后
   的句中 Title-case 词）；中文普通短语（如新造的
   「向量检索」）不在词表校验内——它靠「provenance 必须逐字定位」这一条
   间接约束。CJK 无分词，字符级比对会把正常改写全拦掉，故意不做。
2. 门禁证明的是「这句话有出处」，不是「这句话重要/有效」。匹配度评估仍是
   agent 的活（Step 4），不进硬门。
3. `--allowlist` 是唯一合法的「新词」入口，来源必须是 JD/gap 侧文本；
   把整份简历塞进 allowlist 等于自拆门禁——README 明确禁止并说明为何
   机器读不出这个作弊（只要求文件存在）。

## 5. 结论与下一步

- 形态假设在作者身上成立：一个 host agent + 两个文件就能跑完整闭环，
  无需 app、无需 key、无需服务；且**故意投毒的假建议确实被当场拦下**，
  这条就是 #113 视频的镜头脚本。
- 本轮不产生任何需求线 (b)/(c) 结论（判据只看非作者首跑）。
- 下一步：R1–R7 落到 SKILL.md/验证器 → 合成例（零个人信息）录视频 →
  建 `truetailor` 公开仓（fixtures 迁为唯一事实源，主仓 vendor 副本 +
  漂移锁）→ outreach，时钟自发布日起算。
