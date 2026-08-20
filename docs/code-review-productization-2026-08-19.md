# Code Review - 产品化五项优化（2026-08-19）

## 审查范围

- 固定点：`HEAD` = `28ba20f`
- 审查对象：未提交工作树变更 `git diff HEAD`
- 文件：`parser.py`、`tailor.py`、`engine.py`、`format.js`、`split-canvas.js`、`styles.css` 及对应测试
- 生成方式：Standards / Spec 双轴审查

## Standards

### 已记录的仓库标准

- `pyproject.toml`：ruff `select = ["E", "F", "I"]`，`line-length = 88`，`ignore = ["E501"]`
- 结论：本次 diff 未新增 ruff 违规。`engine.py` 命中的 import 排序/未使用告警位于本次 diff 未触碰的行，属于改动前已存在，不计入本次审查。

### Smell baseline（均为 judgement call，仓库标准或工具已强制时跳过）

1. **Duplicated Code（parser.py）** — `_SECTION_HEADING_LINE_RE`（L23）与既有 `_SECTION_HEADING_RE`（L117）语义重叠，都是“识别简历章节标题”，只是匹配范围略有差异。建议收敛成一个共享标题识别区间，或至少在两者旁加注释说明各自职责，避免后续改标题词表时只改一处导致清洗与分段行为漂移。

2. **Duplicated Code（format.js `workbenchProgressPipelineHtml`）** — `Array.isArray(profile.must_have_skills) ? ... : []` 与 `nice_to_have_skills`、`business_scenarios` 的判空取值重复三次。当前规模下可接受，但若后续再加 JD 字段会继续复制同一形状，可抽一个小的 `asList` 助手。

3. **Duplicated Code（engine.py）** — `_profile_progress_message` / `_gap_progress_message` 的计数逻辑与前端 `workbenchProgressPipelineHtml` 重复一次。前后端各维护一份同语义计数，属于跨语言重复，短期可接受；建议后续把“进度文案的最终事实源”明确为其中一端并在注释里指出，避免两边文案漂移。

## Spec

### 来源 spec

用户本轮 5 条优化点：脏数据清洗与段落保真、Editor 的 STAR + 量化占位、步进式反馈、面试防深挖清单、ATS 打印分页。

### 实现覆盖

5 条均已实现：`clean_resume_markdown`、`METRIC_PLACEHOLDER` + STAR Prompt、四步进度流水线 + SSE 消息、`interviewCheatSheetHtml`、`@page` + `break-inside/break-after`。

### Findings

#### [P1] 简历清洗会损坏合法内容（parser.py）

- 位置：`src/resualign/parser.py:19`
- 现象：`_BULLET_RE` 的字符集包含 ASCII `o`、`O`、`0`，且尾随 `\s*` 可为空。`clean_resume_markdown` 会把普通行首字符误当 bullet，例如：
  - `Objective: backend engineer` → `- bjective: backend engineer`
  - `Overview of the project` → `- verview of the project`
  - `0 years experience` → `- years experience`
- 根因：只匹配“行首单个字符 + 可空空白”，没有要求 bullet 与正文之间有分隔，也没有排除英文字母/数字。
- 影响：英文简历/英文标题被静默删字，违背“第一眼就是工整优雅标准排版”的 spec 目标。这是数据丢失，不是排版瑕疵。
- 建议修法：从 bullet 字符集移除 `o/O/0`（只保留真实 bullet 字形与 `-`），或至少要求 `o|O|0` 后必须是空白且剩余文本不以字母继续。并补一条回归测试断言 `Objective`、`Overview`、`0 years experience` 原样保留。

#### [P2] 量化检测正则误报英文单词（tailor.py）

- 位置：`src/resualign/tailor.py:12`
- 现象：`_METRIC_HINT_RE` 第二分支的短 ASCII token `rt` / `pv` / `uv` 未加词边界，会命中英文单词内部。`_has_quantified_metric("supports")` 返回 `True`（命中 “su***pp***o**rt**s”）。也因此 `"art"` 返回 `True`。
- 影响：英文改写结果只要包含 “supports/art/port/smart” 之类词，就当作“已有量化”，导致本应追加 `[待人工确认：耗时降低 X% / 支撑 QPS 达 Y]` 的英文 bullet 不再追加占位，削弱这条 spec。
- 建议修法：ASCII token（`qps/tps/rt/pv/uv/roi`）改用 `\b...\b` 词边界；中文短语（`成本降低/耗时降低/性能提升`）保持无边界即可。补测试覆盖 `supports`、`art` 应为 `False`。

#### [P3] 面试清单的 `topic` 与占位剥离是死代码（format.js）

- 位置：`src/resualign/static/app/format.js:2290`
- 现象：`topic` 在 `strongDiffs.forEach` 里计算（含 `[待人工确认...]` 剥离），写进 `questions[i].topic`，但最终渲染只输出 `type` / `question` / `sop`，没有把 `topic` 展示出来。因此该变量及占位剥离没有产生任何 UI 效果。
- 影响：没有功能 bug，但混入了“看似在清洗、实际未使用”的意图，增加后续维护成本；同时高置信 diff 生成的问题是通用话术，未引用具体经历文本，离“每条采纳经历下的防深挖卡片”还有一点距离。
- 建议：要么在 `strong` 追问里拼上具体 `topic` 文本，要么删掉 `topic` 计算；二选一，别留死数据。

## 结论

- Standards：0 个硬违规，3 个 judgement-call smell（Duplicated Code）。
- Spec：5 条需求均已实现，但含 1 个 P1 数据损坏、1 个 P2 功能削弱、1 个 P3 死代码。最严重为 `clean_resume_markdown` 对英文行首 `O/o/0` 的静默删字。
