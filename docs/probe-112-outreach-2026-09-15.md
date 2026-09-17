# 探针发布包 #112：发布记录与 outreach 文案

## 发布事实（时钟锚点）

| 项 | 值 |
|---|---|
| 仓库 | https://github.com/shing26/truetailor （MIT，公开） |
| 转公开时刻 | 2026-09-15 14:24 UTC（`gh repo edit --visibility public`） |
| 首个 tag | `v0.1.0`，含 `docs/gate-demo.mp4`（59.8s，2026-09-15 14:27 UTC） |
| CI | GitHub Actions `gate contract` 首推即绿（py3.9 + py3.12，selftest + demoflow 复算） |
| Discussions 功能 | 已开（Announcements 分类可用）；first-run feedback 讨论**未发**，见下节 |
| 主仓引流 | `README.md` 顶部一行 + 漂移锁告示（commit 2b01b93 / c5a7aa9） |

**判据时钟**：ADR-0041 决定 4 的 4 周自 **2026-09-15** 起算，到
**2026-10-13**。口径取「转公开时刻」而不是「outreach 全部发完」，
因为把时钟往后挪对作者有利、对判据不利——宁可早停表。

> ⚠️ **本段时钟口径已被 ADR-0042（2026-09-16）重锚，仅作为 09-15 发布事实存档**：
> 判据时钟起点 = **四渠道 outreach 全部发出当日**（未发→`dist_not_executed`，
> 非证伪）。执行口径以 `docs/probe-112-send-checklist-2026-09-16.md` 为准。

## 机器能做的都做了，剩两件要人点一下

| 事项 | 状态 |
|---|---|
| first-run feedback discussion | **未发**：gh 的 OAuth token 无 Discussions 写权限（GraphQL `addDiscussion` 字段不可见，REST 建讨论 404）。正文已入库 `docs/first-run-feedback.md`，预填链接见下，点开即发 |
| 四渠道 outreach | **待发**：HN / Reddit / 即刻 / V2EX 的登录态不在这台机器的工具链里，文案已按各社区语感备好 |

预填讨论链接（点开就是标题+正文+Announcements 分类）：

```
https://github.com/shing26/truetailor/discussions/new?category=announcements&title=First+run%3F+Tell+me+what+broke+%28I+expected+X%2C+I+saw+Y%29&body=I+am+the+author%2C+so+my+own+runs+prove+very+little.+Run+true-tailor+once+on+your+resume+%2B+one+real+JD%2C+then+reply+in+this+shape%3A%0A%0A++++I+expected%3A+%3Cwhat+you+thought+would+happen%3E%0A++++I+saw%3A++++++%3Cwhat+actually+happened%3E%0A++++Host%3A+++++++Claude+Code+%2F+Codex%2C+which+model%2C+which+OS%0A++++GATE%3A+++++++%3Cpaste+the+summary+line+verbatim%3E%0A%0AThe+GATE+line+matters+more+than+the+prose+because+it+cannot+be+embellished.+Full+protocol+and+what+happens+to+each+report%3A+docs%2Ffirst-run-feedback.md
```

## 发布状态：outreach 四渠道待发（需本人账号）

HN / r/ClaudeAI / 即刻 / V2EX 的登录态不在这台机器的工具链里，
文案已按各社区语感写好可直接粘。**发完请在本 issue 追加日期**，
但不改判据截止日。

---

## 1. Hacker News — Show HN

> **提交方式（先看这段，不然会发错）**
> 1. HN 的提交框只能 **「Title + URL」或「Title + Text」二选一**，不能同时填——所以
>    Title 用下面那行，URL 填 `https://github.com/shing26/truetailor`。
> 2. **提交成功后立刻把 Body 作为第一条评论贴出去**：这是 Show HN 的惯例，
>    而且 Body 最后一句 "the discussion I pinned" 要求讨论区**先存在**——
>    所以顺序必须是「置顶讨论 → HN」。
> 3. 标题上限 **80 字符**；原稿 81 字符会被 HN 直接拒（`Title too long`），
>    已改为下面这版（66 字符）。

Title:

```
Show HN: A resume-tailoring skill with a 500-line fabrication gate
```

Body:

```
Most "tailor my resume to this JD" tools are prompts with a promise inside
them: "do not invent anything". Then the model writes "migrated the pipeline
to Kafka" because Kafka is a word that fits the sentence, and the resume is
wrong in a way nobody notices until an interview.

This is a skill file for Claude Code / Codex plus one verifier: gate.py,
500 lines of Python standard library, no install, no network, no API key.
The model must emit every suggestion as a diff carrying a verbatim quote of
the resume line it rests on. The gate then rejects any suggestion whose
quote cannot be located, whose digits do not already appear in the source,
or whose named tools/employers (acronyms, mixed case, and mid-sentence
capitalized words) come from nowhere. It also refuses to let a blocked diff
be applied to a draft, and appends an audit trail where "round 2" has to
cite round 1 and the resume hash has to change.

You can check the claim without trusting me or running a model:

    git clone https://github.com/shing26/truetailor && cd truetailor
    python selftest.py

That replays 17 golden scenarios (Chinese and English resumes) through the
same file your agent calls, and prints each ruling. Four of them are bugs
this project's parent app actually shipped. One of them was found this week
in our own test suite: an English resume that said only "Python dev" was
being rewritten to "Built services using Java" and marked verified, because
the name check only looked at acronyms and camelCase. That is the kind of
hole I expect the first comments to find, so: the README has a section
called "What the gate does not do", and it is as long as the one above it.

It cannot catch an invented claim written in Chinese prose or in lowercase
English, it has no idea whether a rewrite is worth making, and a zero-output
round is a legitimate answer. MIT. If you run it once on your own resume,
the discussion I pinned is asking for "I expected X and saw Y" plus the
GATE line - first-run friction is the whole point of the project.
```

## 2. r/ClaudeAI

Title:

```
I shipped a resume-tailoring skill where the "don't fabricate" rule is a stdlib script, not a line in the prompt
```

Body:

```
Four steps: paste resume + JD -> gap.json (only skills your resume already
evidences may become rewrite targets) -> diffs.json where every suggestion
carries a verbatim quote of the line it rests on -> gate.py rules on each
one. The gate line gets pasted into the reply verbatim; the model is not
allowed to restate its numbers. Blocked diffs stay visible in a "needs
review" list instead of being quietly dropped, and apply.py refuses to write
one into a draft even if you ask it to.

What it catches: quotes that aren't in your resume, digits nobody measured,
tool and employer names that came from nowhere, and "suggestions" that change
nothing. What it doesn't: coined Chinese phrases, lowercase English
invention, or a rewrite that is technically sourced but pointless.

Install (Claude Code):
    git clone https://github.com/shing26/truetailor ~/.claude/skills/true-tailor

No model needed to inspect the gate:
    python selftest.py

MIT, 60s clip of it blocking a fabricated metric in the README. Weak local
models produce thin rounds and the gate will say so out loud - that's
feature, not bug, but it does mean "run it on the smallest model you have"
is not a great first experience. Feedback format I care about most: I
expected X / I saw Y + the GATE line, pinned in the repo's Discussions.
```

## 3. 即刻（#AI 编程# / #独立开发#）

```
把「不许编简历」这件事从提示词里拿出来，写成 500 行纯标准库的 Python。

上周我把 ResuAlign 整个掉头：app 冻结，只留一个 skill 文件 + 一个门禁脚本。
理由很实在——市面上所有 tailoring 工具都靠模型承诺「不要编」，而它照样会写
「用 Kafka 重构了管道」，因为 Kafka 是个放得进去的词。

现在每条改写建议必须带上主简历原文的逐字引文，门禁脚本逐条判：引文找不到、
数字原文没有、工具/公司名凭空出现、改了等于没改——四类当场 blocked，
而且 apply 脚本会拒绝把没过门的建议写进稿子。

不用模型也能验：git clone 后跑 python selftest.py，17 个剧本（中英各一套）
直接打印裁决行。四个剧本对应我们真发布过的 bug。

MIT，Claude Code / Codex 双入口，60 秒视频在 README。求首跑摩擦报告。
https://github.com/shing26/truetailor
```

## 4. V2EX（分享创造 / Claude 节点）

```
标题：做了个防编造的技能：改简历的每条建议都要能逐字回溯到原文，否则脚本当场拦下

背景：我在做一个本地优先的简历对齐工具，做了半年发现真瓶颈不是功能，
是「陌生人 30 秒能不能跑通第一次」。所以把核心能力剥成一个 SKILL.md
加一个 500 行纯标准库的验证器，丢进 agent 里就能用，零安装零 key 零联网。

规则很硬：模型只能输出「带原文逐字引文的 diff」，验证器逐条裁决
（引文定位 / 数字出处 / 工具与公司名出处 / 改了等于没改），
block 的不许静默丢弃，也不许被 apply 写进稿子；每轮跑完往 JSONL 追加一行，
第二轮必须引用第一轮的复评结论，简历哈希必须变化，
这样「我们迭代优化过」是可核对的而不是一句描述。

不用模型也能自己验：clone 下来 python selftest.py，17 个剧本打印裁决。
MIT。README 里专门写了一节「门禁拦不住什么」，和「能拦住什么」那节一样长。
https://github.com/shing26/truetailor
```

## 不做什么（避免自毁判据）

- 不投「AI 帮你改简历」的营销口吻：转化来的首跑不会留下 GATE 行，
  只会污染判据分子。
- 不在四个渠道同分钟群发同一份文案；HN 先发，隔日再看中文渠道。
- 不为「首跑数」去拉熟人跑一遍贴个摘要：ADR 决定 10 的归档条款就是为了让
  这个数字说真话。
