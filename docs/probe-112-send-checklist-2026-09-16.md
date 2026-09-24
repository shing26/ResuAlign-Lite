# 探针发送清单与自用线推进表（ADR-0042 执行件）

> 建立：2026-09-16 07:22 ｜ 用途：**ADR-0042 决定 1 的时钟起点登记处**，
> 兼自用线（需求线 a）推进记录
> 相关：`docs/probe-112-outreach-2026-09-15.md`（四渠道文案全文）、
> `docs/adr/0042-pre-registered-reanchor-probe-clock-and-dual-line.md`（重锚裁决）、
> `docs/adr/0041-pivot-skill-probe-mainline.md`（原文）

---

## 0. 顺序（照这个来）

1. 发置顶 first-run feedback discussion（**1 步，链接已预填**）
2. 发 HN Show（英文，**先发**）
3. **隔日**发 r/ClaudeAI + 即刻 + V2EX

**时钟起点 = 上面四条全部发出当日**（ADR-0042 决定 1）。
**09-23 24:00 前没发完 → 登记 `dist_not_executed`，时钟不启动、判据保持
PENDING**（决定 2）。**这不是证伪**，处置是「先执行分发，再谈判据」。

> **当前状态（2026-09-25 登记）**：第 1 步已完成，第 2–5 步（四渠道）**0/4**，
> 判定线 09-23 24:00 已过 → 已按规则登记 **`dist_not_executed`**（见 §5）。
> 时钟未启动、判据保持 `PENDING`；**剩余动作只有分发本身**。

### 0.1 动手步骤（点哪、填哪）

**开始前**：浏览器里确认已登录 `shing26`（GitHub）；HN / Reddit / V2EX / 即刻
各自需要的账号见下——**没有账号的渠道先去注册**，不要跳到下一条（四条缺一，
时钟就不启动）。

| 步 | 去哪 | 填什么 | 做完 |
|---|---|---|---|
| 1 | 点 §1.1 的**预填链接** | 页面已带好「标题 + 正文 + Announcements 分类」，直接点 **Start discussion** | §1.1 打勾 + 填日期与 URL |
| 2 | <https://news.ycombinator.com/submit>（未登录先 <https://news.ycombinator.com/login>；无账号需先注册） | **Title** = outreach §1 的 Title 行（66 字符版）；**URL** = `https://github.com/shing26/truetailor`；**Text 留空**——HN 只允许 URL 或 Text 二选一 | 提交后进条目页，把 outreach §1 的 **Body 作为首条评论**贴出；然后 §1.2 打勾 |
| 3 | <https://www.reddit.com/r/ClaudeAI/submit> | 类型选 **Text**；标题与正文抄 outreach §2 | §1.3 打勾 |
| 4 | <https://web.okjike.com> 发动态 | 正文抄 outreach §3（含两个话题标签，无独立标题字段） | §1.4 打勾 |
| 5 | <https://www.v2ex.com/new> | 标题与正文抄 outreach §4；节点选「分享创造」（或 Claude） | §1.5 打勾 |

**第 3 步（Reddit/即刻/V2EX）放在 HN 的次日**，不要与 HN 同分钟群发（纪律见 §2）。

**四步齐了之后**：填 §1 末尾的汇总日期行 → §5 从 `PENDING` 改为「时钟已启动」，
并算出截止 = 起点 + 28 天。

**任一渠道打不开或发不出**（没账号、被限流、被杀帖）：**不要自己换渠道顶替**——
渠道属于 ADR-0041 的「发布策略与渠道」，ADR-0042 明确没有改动它；替换需新开 ADR。
把情况记在 §5 并说一声，由作者起草裁决。

---

## 1. 发送清单（每发一条：`[ ]` 改 `[x]`，填日期与 URL）

### 1.1 置顶 first-run feedback discussion

- [x] 已发出 ｜ 日期：`2026-09-17` ｜ URL：<https://github.com/shing26/truetailor/discussions/1>
- **实测登记（非自陈，2026-09-17 16:53 复验）**：
  `pinnedDiscussions.totalCount = 1` → 讨论 `#1`
  《First run? Tell me what broke (I expected X, I saw Y)》，
  `createdAt 2026-09-16T19:21:37Z`（= 北京时间 **09-17 03:21**），
  `pinnedBy shing26`，分类 **Announcements**，评论 **0**。
  即：**已发出且已置顶**，P0-1 两个动作都完成（复验命令见 §6）。
- **预填链接**（本次即用此链接发出；点开即标题 + 正文 + Announcements 分类，直接 Submit）：

```
https://github.com/shing26/truetailor/discussions/new?category=announcements&title=First+run%3F+Tell+me+what+broke+%28I+expected+X%2C+I+saw+Y%29&body=I+am+the+author%2C+so+my+own+runs+prove+very+little.+Run+true-tailor+once+on+your+resume+%2B+one+real+JD%2C+then+reply+in+this+shape%3A%0A%0A++++I+expected%3A+%3Cwhat+you+thought+would+happen%3E%0A++++I+saw%3A++++++%3Cwhat+actually+happened%3E%0A++++Host%3A+++++++Claude+Code+%2F+Codex%2C+which+model%2C+which+OS%0A++++GATE%3A+++++++%3Cpaste+the+summary+line+verbatim%3E%0A%0AThe+GATE+line+matters+more+than+the+prose+because+it+cannot+be+embellished.+Full+protocol+and+what+happens+to+each+report%3A+docs%2Ffirst-run-feedback.md
```

- 备用路径：若链接报 `category` 无效 → 进 Discussions → New discussion →
  选 **Announcements** 分类，正文从探针仓 `docs/first-run-feedback.md` 取。
- 为什么必须走浏览器：`gh` CLI 的 OAuth token 无 Discussions 写权限
  （GraphQL `addDiscussion` 字段不可见、REST 建讨论 404），这一步机器做不了。

### 1.2 HN Show

- [ ] 已发出 ｜ 日期：`____` ｜ URL：`____`
- 标题 + 正文：`docs/probe-112-outreach-2026-09-15.md` **§1**（直接复制粘贴）
- **先做前置**：置顶讨论必须已存在（HN 正文引用它）
- **提交方式**：Title + URL（`https://github.com/shing26/truetailor`），Body 作为**首条评论**发出
- 入口：<https://news.ycombinator.com/submit>

### 1.3 r/ClaudeAI

- [ ] 已发出 ｜ 日期：`____` ｜ URL：`____`
- 标题 + 正文：同文件 **§2**
- 入口：<https://www.reddit.com/r/ClaudeAI/submit>

### 1.4 即刻

- [ ] 已发出 ｜ 日期：`____` ｜ URL：`____`
- 正文：同文件 **§3**（话题 #AI 编程# / #独立开发#）

### 1.5 V2EX

- [ ] 已发出 ｜ 日期：`____` ｜ URL：`____`
- 标题 + 正文：同文件 **§4**（节点：分享创造 / Claude）

> ### 四条全部打勾的日期 = `____` ← **这就是判据时钟起点**

> ### 进度（2026-09-25 复验）：**1/5 步**
> - §1.1 置顶讨论 ✅ **已发已置顶**（这是**前置项**，不计入决定 1 的「四渠道」）
> - §1.2–§1.5 四渠道 **0/4 全空** → **时钟起点仍为空白，判据保持 `PENDING`**（决定 1/2）
> - 判定线 **2026-09-23 24:00 已过且未执行** → 已登记 `dist_not_executed`（见 §5），
>   **不是证伪**；下一步唯一动作是执行 §1.2–§1.5 的分发

---

## 2. 发送纪律（照抄 outreach 文档 §不做什么）

- **不用**「AI 帮你改简历」营销口吻——转化来的首跑不会留 GATE 行，只污染判据分子
- **不要**四渠道同分钟群发同一份文案；HN 先发，隔日再看中文渠道
- **不为凑首跑数**拉熟人跑一遍贴摘要（ADR-0041 决定 10 的归档条款就是为了让这个数字说真话）
- 收到报告时先看有没有 **GATE 摘要行**：没有的回复欢迎但**不计入探针线分子**

---

## 3. 发出后的判读（探针线口径未改，照抄 ADR-0041 决定 4）

| 触发 | 结论 |
|---|---|
| ≥5 例非作者首跑（各附门禁摘要行）或任意 1 例外部完整合格链 | **过** → 按决定 9 转形态 |
| ≥100★ 或出现非本项目发布的社区二创 | **强信号** → 提前结束观察 |
| 4 周后非作者首跑 < 2 例 | **证伪** → skill 线冻结、回 app-only（**项目不终结**，见 ADR-0042 决定 4） |

---

## 4. 自用线推进表（需求线 a：1 → 3 例）

**合格例定义**（三条全满足才算一例）：
同一份简历 ≥3 轮「改→评→改」 ∧ ≥1 轮有 diff 采纳 ∧
≥2 轮的触发原因是**上一轮评测结论**（因果链条款）。

**取证要求**：验证器 JSONL 行（`round` / `trigger` / `chain` / `resume_sha256`）。
合成例（`examples/demoflow`）、截图、口头复述**一律不计**；
输入必须是**作者真实投递过**的岗位 JD（ADR-0042 护栏 6c / 6d）。

**怎么跑**：探针仓 `SKILL.md` 四步闭环；每轮收尾落日志：

```
python gate.py ... --log tailoring.jsonl --round <N> --trigger <T>
```

第 2 轮起 `--trigger` 必须引用上一轮复评结论（形如 `eval:round1`）——
这是因果链的取证形式，漏传会被验证器判为断链。

### 记录表

| # | 日期 | 岗位（脱敏） | round | trigger | diffs | usable | blocked | resume_sha256 | cites_prev | 计入 (a) |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 2026-09-15 | 阿里 2027 届 AI 应用研发（狗食） | 1 | manual | 6 | 5 | fabricated 1 | `d9a4e197…` | true | ✅ 基线 |
| 0b | 2026-09-15 | 同上 | 2 | eval:round1 | 3 | 3 | 0 | `88f04b27…` | true | ✅ 基线 |
| 1 | | | | | | | | | | |
| 2 | | | | | | | | | | |

> **当前 1 例（基线）／目标 3 例。还需 2 例。**
> 把上表两行合成「1 例」是因为它们属于同一份简历的同一条轮次链
> （round1 → eval:round1），即一例两跳合格链。
> 再拿 2 条独立轮次链（可以是另外 2 个真实岗位，或同一简历的第 2、3 条链）。

---

## 5. 状态登记（只填一格）

- [ ] `PENDING` — 分发未完成，判据未启动（复核至 2026-09-17 16:53）
- [ ] 时钟已启动 ｜ 起点 = `____` ｜ 截止 = 起点 + 28 天 = `____`
- [x] **`dist_not_executed`** — 09-23 24:00 前未发完 ｜ 登记日期 `2026-09-25` ← **当前状态**

> **09-25 登记说明（ADR-0042 决定 1/2，非证伪）**：决定 1 的时钟挂在**四渠道**
> 上，§1.2–§1.5 至今 **0/4**，预注册判定线 `2026-09-23 24:00` 已过且未执行 →
> 按规则登记 `dist_not_executed`：**时钟不启动、探针线判据保持 `PENDING`、
> 这不是证伪**，两条线都不换判、不改阈值（决定 6f）。处置 = **先执行分发**。
>
> 09-25 现场复验（§6 命令原样跑，非文档推断）：讨论 `#1` 仍在且仍置顶，
> `discussions.totalCount = 1`、`comments = 0`；`stars = 0`、`forks = 0`、
> `watchers = 0`、`pushed = 2026-09-16T18:32:20Z`。即：**曝光侧 0 信号，
> 原因在分发未执行，不在判据未达标**。
>
> 解除条件（唯一）：§1.2–§1.5 四渠道全部打勾 → 时钟起点 = 四渠道全勾当日，
> 截止 = 起点 + 28 天；届时换格到「时钟已启动」。分发动作与文案见 §0.1 与
> `docs/probe-112-outreach-2026-09-15.md`；**这一步需要作者本人账号，机器做不了**。

---

## 6. 复验命令（本页每个数字都可复跑）

```bash
# 讨论是否已发出 + 是否已置顶（两件事分开查，不要混为一谈）
gh api graphql -f query='{repository(owner:"shing26",name:"truetailor"){discussions(first:5){totalCount nodes{number title createdAt category{name} comments{totalCount}}}}}'

gh api graphql -f query='{repository(owner:"shing26",name:"truetailor"){pinnedDiscussions(first:10){totalCount nodes{discussion{number title} createdAt pinnedBy{login}}}}}'

# 曝光度（探针线的另一侧：即使讨论发了，没分发照样 0★）
gh api repos/shing26/truetailor --jq '{stars:.stargazers_count,forks:.forks_count,watchers:.subscribers_count,created:.created_at,pushed:.pushed_at}'
```

> 注：`Discussion` 类型**没有** `isPinned` 字段，`Mutation` 里也**没有** `pinDiscussion`
> ——置顶状态只能通过 `Repository.pinnedDiscussions` 读，或在网页端手工置顶。
> 复验时别用 `isPinned`（会报 `Field 'isPinned' doesn't exist on type 'Discussion'`）。
