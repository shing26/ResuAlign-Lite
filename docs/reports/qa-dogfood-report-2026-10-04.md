# 🧪 产品体验与缺陷报告 - ResuAlign-Lite（2026-10-04）

## 0. 修复状态（本报告的收尾，2026-10-04）

分支 `codex/jobtable-qa-fixes-2026-10-04`。下表是本文各条的最终去向，
细节见对应 PR 与 issue。

| 报告条目 | issue | 状态 |
|---|---|---|
| Bug-01 门户页 URL 吃掉真实岗位 | #145 | 已修（`_demote_shared_portal_urls`，去重碰撞 6 → 0） |
| Bug-02 errors 从不渲染 | #146 | 已修（新建 `static/app/skip-detail.js`） |
| Bug-03 `_normalize_url` 透传中文 | #147 | 已修（含中文的坏 `jd_url` 36 → 0） |
| Bug-04 README 配置位置写错 | #148 | 已修（实际在岗位库「批量导入」对话框） |
| Bug-05 harness 崩溃丢 findings | #149 | 已修（用例级 try/except + `finally` 落盘 + 非零退出码） |
| Bug-06 批量预分析无取消 | #150 | 未修（留待新功能排期） |
| Bug-07 缺 JD 行与真重复同形 | #151 | 已修（缺 JD 行逐条列入明细） |

修复过程中另外挖出三件事，都不在原报告里：

1. **表单挂载竞态（已修）** —— 新建/导入表单排在 canvas boot hook 里
   `await api("/api/master-resumes")` 之后才挂载。进入岗位库后立刻点
   「批量导入」，`$('[data-form="job-import"]')` 还是 null，`form.hidden = false`
   抛 TypeError；表单随后才挂载且保持 hidden —— 按钮点了没反应。
   表单不依赖任何请求，已改为在该 await 之前同步挂载。

2. **本批引入的回归（已修）** —— 上一条修复里的 `restoreImportForm` 一律
   恢复 `snapshot.open`，导致粘贴 CSV 导入完成后那个填满视口的大表单继续
   留在屏幕上，看板被顶到折叠线以下。`tests/e2e/test_batch_import_flow.py`
   从 4/4 通过掉到 3/3 失败（`board-column` 拦截指针事件）。改为 CSV 导入
   完成后收起表单，岗位表同步仍保持展开（它的产物就在表单里）。

3. **三条 harness 误报（已修）** —— 「移动端导航不可点击」「工作台缺少主简历
   选择器」「同步明细未列出未入库岗位」经实测全是检查自身的问题，不是产品缺陷。
   详见 `c6098a2`。修正后 harness finding 从 5 条降到 3 条。

修复后仍存在的缺陷已另开 issue：

- **#152（P2）** `#/today` 是死路由，落到驾驶舱，URL 与页面不一致
- **#153（P3）** 移动端导航后两项在首屏外且无滚动提示

## 1. 体验总览
## 1. 体验总览

* 体验角色：新用户（空库首屏）+ 核心用户（每日岗位表同步 → 一键预分析 → 岗位库）
* 健康指数：🟡 严重交互受阻
* 核心体感：主路径的响应式与控制台层面很干净（6 条路由 × 2 视口，0 console error、
  0 pageerror、0 横向溢出）；真正的风险集中在最近新增的**岗位表同步**上——用真实
  165 行岗位表实测，**126 行可导入中有 6 行（4.8%）被静默丢弃**，而 UI 只显示
  「跳过 6」，用户无从知道丢的是哪 6 个岗位、也无法找回。
* 取证方式：隔离实例（`scripts/qa_dogfooder.py` 的 `FakeLLMServer` + `AppServer`，
  临时 SQLite、随机端口、fake LLM），真实数据源为
  `C:\Users\Shing\.workbuddy\Claw\job-radar\岗位总表.csv`（165 行，2026-10-03）。
  用户真实 DB（`data/jobs.db`）未被触碰。

## 2. 缺陷与体验问题清单

### 🔴 [Bug-01] 岗位库 多岗位共用门户页 URL 时被静默去重丢弃（真实数据 6/126）

* 严重级别：**P1**
* 问题类别：功能缺陷（数据丢失）
* 复现环境：Chromium headless / 1440x900 / 隔离实例 + fake LLM

#### 🐾 严格复现步骤

1. 把真实岗位表（165 行）复制到临时目录，配置 `job_table.path` / `job_table.jd_dir`。
2. `POST /api/jobs/job-table/sync`，轮询 `GET /api/jobs/import/{id}` 至完成。
3. 观察结果：`total=126, created=120, skipped=6`。
4. 读取 `errors` 字段，6 条被丢弃的岗位是：腾讯「AI 应用工程师（技术类｜2027 校园
   招聘）」、金蝶「软件开发-FDE（Delta 方向）」与「Java 开发工程师（AI 应用方向）」、
   大疆「AI DevOps 工程师」「AI 实习生 - 全栈开发」「AI 实习生 - 前端开发（AI Coding）」。

#### ⚖️ 现象比对

* 实际现象：6 个**真实且不同**的岗位（同公司不同岗位名）因 `投递入口` 列填的是公司
  门户页而非单岗位页（`join.qq.com`、`app.mokahr.com/campus-recruitment/kingdeehr/166565`、
  `apply.careers.dji.com/campus-recruitment/dji/143359`、`we.dji.com/zh-cn/campus/position?project=intern`），
  URL 归一化后相同 → 被判为重复 → 丢弃。
* 预期行为：门户页 URL 不具备岗位唯一性，不应作为岗位身份；这类行应回落到
  `公司|岗位|地点` 身份键（ADR-0055 已有的 paste 分支逻辑），或至少**不静默丢弃**。

#### 🔍 疑似根因与线索

* `src/resualign/api/services/job_table.py:normalize_job_table_row` —
  `jd_url` 非空即设 `source_type="url"`，去重键走 URL 分支；
  而 `_COLUMN_ALIASES` 把 `投递入口` 映射为 `jd_url`，该列在 WorkBuddy 里是
  「人工填的入口描述」，语义上不等于单岗位 URL。
* ADR-0057 保留 query/fragment 的修复**对本类数据无效**：这些 URL 本身就不含
  单岗位标识符，query 相同是事实，不是归一化过度。

#### 🤖 编码 Agent 专用修复 Prompt

> 在 `normalize_job_table_row` 中区分「单岗位页 URL」与「门户/入口描述 URL」。
> 建议做法：当同一批 CSV 内有 ≥2 行归一化后 URL 相同，或该 URL 的 path 是
> `/campus`、`/campus-recruitment/...`、`/jobs`、`/` 等**无岗位 id 的列表/门户形态**
> （可结合已有 path 含 jobId/postId/detail/id 数字的判定），则不采用 URL 分支，
> 改用 `_job_table_dedupe_key(company, title, location)` 并置 `source_type="paste"`。
> 同时在 `errors` 里区分「重复跳过」与「身份键冲突丢弃」，供 UI 展示（见 Bug-02）。
> 补测试：门户 URL 多岗位 → 全部入库；单岗位 URL 重复 → 仍然去重。

---

### 🔴 [Bug-02] 导入/同步的 `errors` 从不渲染，被丢弃的岗位对用户不可见

* 严重级别：**P1**
* 问题类别：交互反馈（放大 Bug-01 的危害）
* 复现环境：Chromium headless / 1440x900 / 隔离实例

#### 🐾 严格复现步骤

1. 配置含门户 URL 冲突行的岗位表，点「数据 → 批量导入」里的「同步岗位表」。
2. 等待状态文案从「同步中：新建 N，跳过 M」变为「同步完成：新建 114，跳过 6」。
3. 通读状态区与 toast：**没有任何一处显示被跳过的岗位名**。

#### ⚖️ 现象比对

* 实际现象：`GET /api/jobs/import/{id}` 与 `POST /api/jobs/job-table/sync` 都返回了
  逐条 `errors`（含岗位标题与原因），但前端两处轮询回调
  （`submitImport`、`sync-job-table`）只渲染 `created` / `skipped` 计数，
  `errors` 被丢弃。「跳过 6」与「重复跳过 6」在 UI 上完全同形。
* 预期行为：跳过数 > 0 时给出可展开的明细（标题 + 原因），并区分「已存在（正常）」
  与「身份冲突丢弃（异常）」。

#### 🔍 疑似根因与线索

* `src/resualign/static/app/main.js` 的 `submitImport`（约 3644-3670）与
  `"sync-job-table"`（约 1341-1400）：两处都只读 `status.created/skipped/analyzed`，
  从未读 `status.errors`。

#### 🤖 编码 Agent 专用修复 Prompt

> 在 `submitImport` 与 `sync-job-table` 的轮询回调里，当 `status.errors.length > 0`
> 时在状态节点下方渲染一个可折叠明细列表（每行 `标题: 原因`），并在 toast 里
> 追加「详情见下方」提示。把「Duplicate job already exists」这类正常去重与
> 其它错误分开展示（后端可在 errors 项上带一个 `kind` 字段，或前端按前缀归类）。

---

### 🟡 [Bug-03] `_normalize_url` 透传中文说明，36/126 行的 `jd_url` 是坏值

* 严重级别：**P2**
* 问题类别：功能缺陷

#### 🐾 严格复现步骤

1. 对真实 CSV 调用 `_normalize_url`，输入为真实单元格值：

```text
RAW : https://app.mokahr.com/su/aiaJb （官方 Moka，已由第三方聚合页更正）
NORM: 'https://app.mokahr.com/su/aiaJb （官方 Moka，已由第三方聚合页更正）'

RAW : campus.sf-express.com；公众号「顺丰校园招聘」
NORM: 'https://campus.sf-express.com；公众号「顺丰校园招聘」'
```

#### ⚖️ 现象比对

* 实际现象：36/126 行（28.6%）的 `jd_url` 含中文、空格、分号；点击必然 404。
  顺丰那行还会被拼成 `https://campus.sf-express.com；公众号...` 这种非法 URL。
  字节那行单元格内含**两个**真实 URL（官网 + BOSS 同岗），但整段被当成一个 URL 存下，
  第二个入口丢失。
* 预期行为：要么抽取第一个合法 http(s) URL，要么整格判为非 URL 走 paste 分支。

#### 🔍 疑似根因与线索

* `src/resualign/api/services/job_table.py:_normalize_url` — 只做
  `startswith` / `"." in value and " " not in value` 两种判断，没有校验 URL 主体
  是否只含合法字符。

#### 🤖 编码 Agent 专用修复 Prompt

> 重写 `_normalize_url`：先用正则从整格文本中抽取全部 `https?://[^\s；;，,）)】」]+`
> 候选；若存在候选则取**第一个**并对其做 `urlsplit` 合法性校验（netloc 必须含点、
> 不含中日文字符），返回该 URL；若整格本身不含中文且本身就是裸域名，保留现有
> 补 scheme 逻辑；否则返回 `""`。补单测覆盖上述三例 + 多 URL 单元格。

---

### 🟡 [Bug-04] README 把岗位表配置位置写错了（本轮 PR #144 新引入）

* 严重级别：**P2**
* 问题类别：文档与实现不符

#### 🐾 严格复现步骤

1. 读 `README.md:33`：「把 WorkBuddy 每日追加的那张 CSV 路径填进**设置页**」。
2. 打开 `http://127.0.0.1:8000/#/settings`，查询 `[name="job_table_path"]` → 不存在；
   该页只有 `simple-llm-form` 与 `command-panel` 两个 form。
3. 打开 `#/jobs`，`[name="job_table_path"]` 存在，但藏在
   `<details class="toolbar-more">`（summary 文案「数据」）→ 「批量导入」对话框内。

#### ⚖️ 现象比对

* 实际现象：真实入口是 **岗位库 → 「数据」溢出菜单 → 批量导入 → 岗位表 CSV 路径**，
  比 README 描述多两级且不在设置页。
* 预期行为：文档与 UI 一致。

#### 🔍 疑似根因与线索

* 该文案是 PR #144（`a9ac128`）新写的，写作时未在 UI 上核对位置。
* `README.md:53` 的「设置」小节把「岗位表自动同步」列在设置项里，同样需要修正。

#### 🤖 编码 Agent 专用修复 Prompt

> 修正 `README.md`：第 33 行与第 53 行把岗位表配置位置从「设置页」改为
> 「岗位库 →『数据』→『批量导入』对话框」，并说明该对话框同时承载手动粘贴
> / 选择文件导入、导入后自动预分析开关与岗位表同步按钮。

---

### 🟡 [Bug-05] QA harness 选择器漂移导致整轮 findings 丢失，且不覆盖新功能

* 严重级别：**P2**（QA 基础设施，非产品）
* 问题类别：测试与工具链

#### 🐾 严格复现步骤

1. `PYTHONPATH=src python scripts/qa_dogfooder.py`。
2. 跑到第 16 个用例 `check_invalid_url_blocker` 时
   `Page.fill: Timeout 30000ms exceeded. waiting for locator("[data-fetch-url]")`，
   进程以 traceback 退出。
3. 检查 `.scratch/qa/findings.json` → 仍是 2026-08-19 的空数组，本轮证据全部丢失。

#### ⚖️ 现象比对

* 实际现象：
  * harness 在测一个**已被删除的功能**：URL 抓取栏与 blocker 徽标在 `8f7bfed
    feat(debloat)` 中移除，`src/resualign` 全树已搜不到 `data-fetch-url` /
    `fetch-job-url` / `data-blocker-badge`（后端 `blocker_queue` 表还在）。
  * `main()` 把 `findings.json` 写在 `runner.run()` **之后**，任何一个用例抛异常就
    带走全部结果；CI 里跑它只能得到「退出码非 0」。
  * 20 个用例中**没有任何一个**覆盖岗位表同步、一键预分析、CSV 导入去重——即最近
    三个月新增的全部功能。Bug-01 因此在 CI 与 harness 中都无人发现。
* 预期行为：用例随产品演进更新；每个用例独立捕获异常并写产物；新功能有对应覆盖。

#### 🔍 疑似根因与线索

* `scripts/qa_dogfooder.py:1533`（`page.fill('[data-fetch-url]', ...)`）。
* `scripts/qa_dogfooder.py:1689-1726`（产物写入在 `run` 之后、且不在 `finally` 内）。

#### 🤖 编码 Agent 专用修复 Prompt

> 三步：① 删除或重写 `check_invalid_url_blocker`（抓取入口已移除；如要保留
> 「无效输入」这一维度，改测岗位表路径为空 / 非绝对路径 / 非 CSV 的分支）。
> ② 把 `main()` 的产物写入放进 `finally`，并给每个 `check_*` 套一层
> 「记录异常 → 继续下一个用例」的包装，异常计入 findings 而非终止整轮。
> ③ 新增三个用例覆盖新功能：岗位表同步（用临时 CSV，断言 created/skipped 与
> errors 明细）、一键预分析（断言二次点击 `queued=false` 且不重复消耗）、
> 同门户 URL 多岗位不被丢弃（Bug-01 的回归防线）。

---

### 🔵 [Bug-06] 批量预分析无取消，长批次只能干等

* 严重级别：**P3**
* 问题类别：交互反馈

#### 🐾 严格复现步骤

1. 库中有 N 个未分析岗位，点看板「一键预分析」。
2. 按钮置灰并变为 `预分析中 0/N`，只能看计数。
3. 期间无任何中止入口。

#### ⚖️ 现象比对

* 实际现象：实测 **3.5s/岗位**（每个岗位 2 次串行 LLM：jd_profiler + gap_analyzer，
  fake LLM 环境下 20 岗位耗时 70.3s）。按真实 120 个待分析岗位外推 ≈ 7 分钟，
  期间按钮禁用、无取消、无「还剩多久」提示。
* 预期行为：长批次提供「停止」按钮（或允许用户直接关闭页面并说明后台仍会继续）。

#### 🔍 疑似根因与线索

* `src/resualign/api/services/jobs.py:_run_preanalyze_batch` — 无 `stop` 事件，
  唯一的 `break` 分支是 `PreanalyzeUnavailable`（鉴权/欠费）。
* `POST /api/jobs/preanalyze-pending` 没有对应的 cancel 路由
  （单岗位分析有 `POST /api/jobs/{id}/cancel`，批量没有）。
* ✅ 已核实**不是**缺陷的部分：每日额度护栏在 `preanalyze_job` 内部每岗位
  `enforce_daily_llm_cap`，超限会抛 `PreanalyzeUnavailable` → 整批 `stopped=true`
  早停并把可执行原因透给 UI。这段设计是对的。

#### 🤖 编码 Agent 专用修复 Prompt

> 给 `_preanalyze_batches[batch_id]` 增加 `stop: threading.Event`，循环顶部
> `if batch['stop'].is_set(): break`；新增 `POST /api/jobs/preanalyze-pending/{batch_id}/cancel`
> 置位该事件；前端在 `预分析中 N/M` 状态下把按钮切成「停止」并调用该路由。
> 补测试：取消后 `queued=false` 且 `analyzed` 停在取消时刻，已分析结果保留。

---

### 🔵 [Bug-07] 39/165 行无 JD 正文被跳过，但与「重复跳过」同形

* 严重级别：**P3**
* 问题类别：交互反馈

#### 🐾 严格复现步骤

1. `read_job_table_rows(..., stats=...)` 对真实 CSV 返回
   `{'total_rows': 165, 'importable_rows': 126, 'missing_jd': 39}`。
2. 同步文案把这些行计入 `missing_jd` 后缀，但「跳过」计数里与重复行混在一起。

#### ⚖️ 现象比对

* 实际现象：39 行（23.6%）无 `JD文件`，每次同步都会被重新检查并再次跳过，
  文案只说「另有 39 行缺少 JD 正文，未导入」。若 WorkBuddy 后续补上 md 文件，
  这些行会自动入库（这是对的）；但若永远不会补，用户无法从 UI 区分
  「待补 JD」与「真重复」。
* 预期行为：三类结果（新建 / 已存在 / 缺 JD 正文 / 身份冲突丢弃）分别可见。

#### 🔍 疑似根因与线索

* `sync_job_table` 已算出 `missing_jd`，但只拼进 `detail` 字符串；
  `queue_job_rows` 不接收 `missing_jd`，`errors` 里也没有对应条目。
* 与 Bug-02 同源：修 Bug-02 的明细渲染时一并暴露。

#### 🤖 编码 Agent 专用修复 Prompt

> 把 `missing_jd` 从字符串后缀升级为结构化结果：在 sync 响应的 `errors` 里为
> 缺 JD 的行各追加一条 `{title}: 缺少 JD 正文（待 WorkBuddy 补充后自动导入）}`，
> 并在导入状态响应里加 `missing_jd` 计数字段供 UI 单独展示。

## 3. 体验优化与 Vibe 建议

1. **「跳过」这个词承担了太多语义。** 新建 / 已存在 / 缺 JD / 身份冲突是四种完全
   不同的结局，却都被压成一个整数。建议同步完成后的状态区固定四行小计，
   而不是一句话。
2. **岗位表配置入口太深。** 它是整个每日工作流的起点，却藏在「数据 → 批量导入」
   两层之下，和「导出 CSV」这种低频操作挤在同一个溢出菜单里。考虑到用户每天都要用，
   值得一个独立入口（例如岗位库工具栏常驻「同步岗位表」按钮）。
3. **预分析的进度模型可以更诚实。** `预分析中 37/120` 里的 120 是「待分析总数」，
   不是「本次会真正分析的数量」——每日额度可能让它在 50 就早停。分母改成
   「本次实际排入数」并附一句额度提示，用户预期会更准。
4. **真实数据的价值已被验证。** 这轮所有 P1 都是用真实 165 行 CSV 发现的，
   fake/合成 fixture 无法复现（门户 URL 复用这种脏数据只有真实运营才会长出来）。
   建议把真实 CSV 的**结构特征**（而非内容）固化成测试 fixture。

## 4. 本轮**没有**发现问题的部分（已实测）

* 6 条路由（含无效路由 `#/nope`）× 2 视口（1440x900 / 390x844）：
  0 console error、0 pageerror、0 failed request、0 横向溢出。
* 岗位表同步幂等性：126 行二次同步 → `queued=0, already_present=126`，0 新增、
  0 次 LLM 调用。去重设计本身有效，失效的只是「无单岗位标识的门户 URL」这一类。
* 一键预分析的跳过逻辑：首次 20/20 分析完成，第二次点击
  `{'queued': false, 'total': 0}`，不重复消耗。
* 每日 LLM 额度护栏在批量预分析中正确早停（见 Bug-06 的 ✅ 说明）。
* 导入吞吐：1.12s/岗位（fake LLM，20 岗位 22.5s，created=20 skipped=0）。

## 5. 复现方式

```powershell
$env:PYTHONPATH = "D:\ResuAlign-Lite\src"
$env:PYTHONIOENCODING = "utf-8"
# harness（本轮崩溃，见 Bug-05）
python scripts\qa_dogfooder.py
# 本轮真实数据走查脚本（gitignored，位于 .scratch/qa2/）
python .scratch\qa2\live_sync2.py    # 岗位表同步 + 丢失行定位
python .scratch\qa2\live_timing.py   # 导入/预分析吞吐与幂等
python .scratch\qa2\a11y2.py         # 图标按钮可访问名称复核
```
