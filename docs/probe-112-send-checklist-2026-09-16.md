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

---

## 1. 发送清单（每发一条：`[ ]` 改 `[x]`，填日期与 URL）

### 1.1 置顶 first-run feedback discussion

- [ ] 已发出 ｜ 日期：`____` ｜ URL：`____`
- **预填链接**（点开即标题 + 正文 + Announcements 分类，直接 Submit）：

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

- [x] **`PENDING`** — 分发未完成，判据未启动 ← **当前状态（2026-09-16）**
- [ ] 时钟已启动 ｜ 起点 = `____` ｜ 截止 = 起点 + 28 天 = `____`
- [ ] **`dist_not_executed`** — 09-23 24:00 前未发完 ｜ 登记日期 `____`
