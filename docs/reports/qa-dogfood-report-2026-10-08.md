# 🧪 产品体验与缺陷报告 - ResuAlign-Lite（2026-10-08）

## 0. 结论摘要

本轮聚焦**交互逻辑**（不是回归）：用隔离实例（`scripts/qa_dogfooder.py` 的
fake LLM + 临时 SQLite + 随机端口）驱动真实浏览器，走新用户与核心用户的
真实路径。既有 harness 的 21 项检查**全部通过（0 findings）**，但那是回归网
而不是探索器 —— 本轮新增探索发现的四条缺陷全部落在 harness 未覆盖的面。

| # | 级别 | 一句话 | 状态 |
|---|---|---|---|
| F1 | **P1** | 「批量对齐 / 分析全部待处理」点下去必崩：批次已排队，但前端抛异常、轮询不启动、进度永远空白 | **已修** |
| F2 | **P1** | 岗位卡 hover 展开导致列表位移 187px，多选复选框点不中（点击落到卡片本体） | **已修** |
| F3 | **P2** | 看板勾选框与面板勾选框是两套互不相通的选择模型，「已选 2」后提交仍报「请选择 2-5 个岗位」 | **已修** |
| F4 | **P3** | 多选复选框是原生 13×13px，无扩大热区（低于 WCAG 2.2 的 24px 最小目标） | **已修** |

另有 1 条在本轮**已修**：批量面板没有关闭入口（详见 §6）。

### 修复落点（2026-10-08）

| # | 改动 | 回归测试 |
|---|---|---|
| F1 | `api/services/batch.py` 创建响应改为 GET 同形超集（保留 `total`/`queued`） | `tests/api/test_batch_align.py::test_create_response_is_superset_of_status_response` |
| F2 | `styles.css` 详情展开只认 `[data-revealed]`；`format.js` 卡头加 chevron；`main.js` 加 `toggle-card-reveal` | `tests/frontend/board-card-reveal.test.mjs`（3 条） |
| F3 | `main.js` 新增 `openBatchPanel`/`syncBatchPanelFromBoard`，三个展开入口统一走它 | `tests/frontend/batch-panel-selection.test.mjs`（3 条） |
| F4 | `styles.css` `.board-check` 热区 24px（触摸 32px），视觉尺寸不变 | `tests/frontend/board-check-target.test.mjs`（2 条） |

修复后实测（隔离实例 + 真实浏览器）：

```
F1  POST keys: [..., 'queued', 'rows', 'summary', 'total']   toast: 已排队 2 个待处理岗位
    GET polls: 4   status: '已完成 0/2'   （修前：0 / '' / TypeError toast）
F2  卡片高度 hover 前后均为 181px；点击目标 ['INPUT','INPUT','INPUT']（修前第 2 次为 ARTICLE）
F3  看板勾 2 → 面板自动勾 2 → 提交 '已排队 2 个岗位'（修前：'请选择 2-5 个岗位'）
F4  .board-check 盒 13×13 → 24×24（input 仍 13×13，视觉不变）
```

回归：前端 553 passed、后端 1196 passed / 7 skipped（覆盖率 89.36%）、
E2E 7 passed、ruff 与 modgraph --check 全绿。

## 1. 取证方式

- 隔离实例：`scripts/qa_dogfooder.py` 的 `FakeLLMServer` + `AppServer`，
  临时 SQLite、随机端口、fake LLM；**真实用户 DB 未被触碰**。
- 浏览器：Playwright headless Chromium，1440×900。
- 数据：经 API 造 1 份主简历 + 3~6 个岗位，非真实数据。
- 复现脚本留在 `.scratch/`（gitignored）：`explore_interaction.py`（10 项探索）、
  `verify_batch_align_flow.py`、`verify_selection_models.py`、
  `diagnose_click_order.py`、`diagnose_events.py`、`diagnose_shift.py`。

---

## 2. 🔴 [F1] 批量对齐的两个入口必然崩溃，且用户无从察觉

* 严重级别：**P1**（功能缺陷 + 静默失败）
* 引入点：`f38b0a8`（2026-08-29，feat(batch): 一键分析全部待处理岗位）
* 影响入口：工具栏「批量对齐」、面板内「分析全部待处理」
  （第三个入口「开始批量对齐」表单提交正常）

### 严格复现步骤

1. 进入 `#/jobs`（库里有主简历与待处理岗位）。
2. 点工具栏「批量对齐」。
3. 观察：面板展开，取消按钮出现；但 `[data-batch-status]` 为空、
   结果矩阵为空、轮询请求数为 **0**。
4. Toast 显示：`Cannot read properties of undefined (reading 'completed')`。

### 实测证据

```
POST /api/batch-align keys: ['batch_id', 'queued', 'total']
  has 'summary': False   has 'rows': False
GET  /api/batch-align/{id} keys: ['batch_id', 'created_at', 'custom_prompt',
                                  'granularity', 'master_resume_id',
                                  'prompt_focus', 'rows', 'summary']
toast after click: Cannot read properties of undefined (reading 'completed')
GET polls started by UI: 0          ← 轮询从未启动
[data-batch-status] text: ''
results innerHTML length: 0
```

### 根因

`api/services/batch.py::queue_batch_align` 的**创建响应**只返回
`{'batch_id', 'total', 'queued'}`（`batch.py:217`），而前端
`static/app/events.js::renderBatchResults` 直接读
`batch.summary.completed`（`events.js:954`）——
**该字段只有 GET 状态接口才有**。

`main.js` 的 `batch-align-pending` 把 POST 响应直接喂给 `renderBatchResults`：

```js
state.batchAlign = result;
if (panel) panel.hidden = false;
if (cancel) cancel.hidden = false;
renderBatchResults(result);        // ← 抛 TypeError
startBatchPolling(result.batch_id); // ← 永不执行
toast(`已排队 ${result.queued} 个待处理岗位`, "success"); // ← 永不执行
```

对比：第三个入口（表单 `batch-align` 提交）**不**渲染 POST 响应，只调
`startBatchPolling`，所以它是好的 —— 这解释了为什么问题只在两个入口出现。

### 为什么危险

后端**已经真实排队了任务**（LLM 调用会真的发生、会消耗额度），但前端：

- 不启动轮询 → 进度与结果永远不出现
- 不显示成功提示 → 用户以为没点上
- 唯一反馈是一句 JS 异常文本 → 不可行动

用户很可能重复点击，造成重复排队。

### 为什么 harness 没抓到

`scripts/qa_dogfooder.py::check_preanalyze_pending` 测的是**另一个端点**
（`/api/jobs/preanalyze-pending`）且**只走 API**，从不驱动 UI；
`batch-align-pending` 没有任何 UI 层测试覆盖。

### 修复方向（二选一，建议甲）

- **甲**：后端创建响应补齐 `summary`/`rows`（与 GET 同形），前端无需分支。
- **乙**：前端不在创建时渲染结果，改为先 `startBatchPolling`，
  由首次轮询回填（与表单提交路径一致）。

### 验收标准

- 点工具栏「批量对齐」与面板「分析全部待处理」后：
  toast 显示「已排队 N 个待处理岗位」；`GET /api/batch-align/{id}` 轮询启动；
  `[data-batch-status]` 从「已完成 0/N」开始推进。
- 新增 UI 层测试（Playwright 或前端单测）覆盖这两个入口，
  断言「无 TypeError + 轮询已启动」。
- 控制台/pageerror 无输出。

---

## 3. 🔴 [F2] 岗位卡 hover 展开导致布局位移，多选复选框点不中

* 严重级别：**P1**（交互阻断，影响批量选择这一整条路径）

### 严格复现步骤

1. 进入 `#/jobs`，鼠标移到第 1 张卡的复选框并点击（选中成功）。
2. 移向第 2 张卡的复选框并点击。
3. 观察：第 2 张卡**没有被选中**；事件日志显示这次点击的目标是
   `ARTICLE.board-card`，不是 `INPUT`。

### 实测证据

```
before click#0: box#0=[270, 367, 13, 13] box#1=[270, 546, 13, 13]
after  click#0: box#0=[270, 365, 13, 13] box#1=[270, 733, 13, 13]   ← 位移 187px

after click #0: ['click INPUT 选择 岗位 6', 'change INPUT 选择 岗位 6 checked=true']
after click #1: ['click ARTICLE board-card copilot-card ']            ← 没点到 input
checked now: ['选择 岗位 6']

命中测试（静止态）：elementFromPoint(复选框中心) -> <INPUT>，insideLabel=True
FAB box=[628, 822, 185, 54] 与复选框 [270,733,13,13] 不重叠 → 不是 FAB 遮挡
```

### 根因

`static/styles.css:7833` 起：

```css
.board-card__reveal { display: none; }
.board-card:hover .board-card__reveal,
.board-card:focus-within .board-card__reveal,
.board-card[data-revealed="true"] .board-card__reveal { display: flex; }
@media (hover: none) { .board-card__reveal { display: flex; } }
```

鼠标一旦进入某张卡，`__reveal`（技术栈 + 匹配块 + 标签 + 时间线 + 操作区）
展开约 **187px**，把该列**下方所有卡片整体下推**。鼠标离开时又收回。

于是「从第 1 张卡移到第 2 张卡」的瞬间：第 1 张收回 → 第 2 张上跳 187px →
落点已经不在复选框上。真人用户表现为「列表在鼠标下抖动、复选框点不中」，
自动化表现为点击命中卡片本体。

注：`e5f2641`（岗位卡操作面移出 hover 折叠层）已经处理过同类问题，
但复选框在 `board-card__top`（折叠层之上），位移来自**其他卡片**的展开，
所以那次修复没有覆盖本路径。

### 修复方向（建议甲）

- **甲**：`__reveal` 不参与文档流位移 —— 改为绝对定位浮层 / 覆盖在卡片上，
  或把折叠区做成固定高度的可滚动区，使展开不改变卡片高度。
- **乙**：卡片不因 hover 改变高度；展开改由显式交互触发
  （点击「详情」或 `data-revealed` 切换），hover 只做视觉强调。

### 验收标准

- 鼠标沿列上下移动时，卡片高度不变（`getBoundingClientRect().height` 恒定）。
- 连续点击同一列任意三张卡的复选框，三次全部命中 `INPUT`
  （事件日志不得出现 `ARTICLE`）。
- 新增回归测试：断言 `.board-card__reveal` 展开前后
  `.board-card` 的高度不变。

---

## 4. 🟡 [F3] 两套互不相通的选择模型

* 严重级别：**P2**（认知负荷 + 误导性反馈）

### 严格复现步骤

1. `#/jobs` 勾选 2 个岗位 → FAB 显示「已选 2」。
2. 点「批量对比」打开面板，选好主简历。
3. 点「开始批量对齐」。
4. 观察：toast 报「请选择 2-5 个岗位」，尽管 FAB 明明写着「已选 2」。

### 实测证据

```
FAB visible: True  count label: '已选 1\n批量对比'
board checkboxes checked: 1
PANEL checkboxes checked: 0   (0 = 两套选择互不相通)
submit with only board selection -> toast: 请选择 2-5 个岗位
submit with panel selection     -> toast: 已排队 2 个岗位
  GET polls: 4  status text: '已完成 1/2'
```

### 根因

两个属性各自独立、互不同步：

- 看板卡复选框 `data-board-check`（`format.js:1048`）→ 只喂
  `updateBatchSelection`（FAB 计数与显隐）。
- 面板岗位列表复选框 `data-batch-check`（`format.js:1103`）→
  表单提交只读它：
  `$$("[data-batch-check]:checked")`（`main.js:3447`）。

看板勾选看起来是「选择要批量对齐的岗位」，实际只是「显示 FAB」的开关。

### 修复方向

- 甲：面板打开时用看板已选集合预勾选面板列表（单向同步即可）。
- 乙：面板列表直接复用看板选择，去掉 `data-batch-check` 这套并行状态。
- 丙：若确属有意设计，则 FAB 文案必须区分（如「已选 N（仅用于批量对比）」），
  且面板内明示「请在下方列表选择岗位」。

### 验收标准

- 看板勾选 2 个岗位 → 打开面板 → 「开始批量对齐」直接成功（不再要求二次勾选）。
- 或者：FAB 计数与面板选择语义在文案上明确区分，且面板内给出显式指引。

---

## 5. 🔵 [F4] 多选复选框热区仅 13×13px

* 严重级别：**P3**（可用性 / 无障碍）

### 实测证据

```
岗位 6: label=[13, 13] input=[13, 13] opacity=1
    elementFromPoint -> <INPUT> insideLabel=True
```

`.board-check` 只有 `display:inline-flex`（`styles.css:3464`），
未给 `input`/`span` 任何样式或内边距 —— 复选框保持浏览器默认的
约 13×13px，热区等于视觉尺寸。

### 为什么算问题

WCAG 2.2 SC 2.5.8 要求指针目标至少 24×24px；移动端触摸目标常规建议
44px。此复选框是「批量对比 / 批量对齐」的唯一入口，却比周围任何控件都小，
叠加 F2 的位移问题后尤其难命中。

### 修复方向

给 `.board-check` 一个不小于 24×24（触摸 ≥44）的可点击区域 ——
用 `--space-*` 刻度补 padding，让 `<span>` 承担视觉，
或直接把 label 的最小尺寸写进 `--radius`/`--space` 体系内的样式。

### 验收标准

- `.board-check` 的 `getBoundingClientRect()` 宽高均 ≥ 24（桌面）。
- 既有 CSS 结构守卫（`tests/frontend/css-structure.test.mjs`）继续通过；
  新增样式只用 `--space-*` 与 `--radius-*` 令牌（ADR-0043 护栏）。

---

## 6. 本轮已修：批量面板没有关闭入口

工具栏「批量对齐」点开后，面板没有任何关闭/返回入口 —— 唯一能收起它的
toggle 按钮挂在 FAB 上，而 FAB 只在「已选 >0」时显示。取消勾选后
FAB 消失、面板仍可见，用户被困住。

同一处还暴露一个放大器：`styles.css` 用 `.batch-panel .batch-job-list`
给岗位列表加 `max-height/overflow`，但元素真实类名是 `batch-panel-wrap`
—— 死选择器，155 个岗位把面板撑到首屏之外，连「开始批量对齐」都在折叠线以下。

已修：面板加 `panel-head` + 「返回岗位库」按钮（`close-batch-panel`），
并把 `.batch-panel` 改为 `.batch-panel-wrap`；新增
`tests/frontend/batch-panel-close.test.mjs`（3 条，含死选择器守卫）。

实测：关闭按钮可见且生效；岗位列表高度 220px 可滚动；
提交按钮 y=787.5 回到首屏内；前端 545 passed、后端 1195 passed / 7 skipped。

---

## 7. 覆盖缺口（建议补进 harness）

本轮四条缺陷全部落在现有 harness 之外，说明**回归网存在结构性盲区**：

| 缺口 | 说明 |
|---|---|
| 批量对齐入口无 UI 测试 | `check_preanalyze_pending` 只走 API 且是另一个端点 |
| 无「创建响应形状」契约测试 | POST 与 GET 响应不同形，前端假设了同形 |
| 无布局稳定性检查 | 现有 `overflow_scan` 查横向溢出，不查 hover 引起的纵向位移 |
| 无选择模型一致性检查 | 两套 checkbox 属性无人断言其关系 |

建议在 `scripts/qa_dogfooder.py` 增加一个 `check_batch_align_ui`：
驱动两个入口、断言轮询启动与 toast 文案；并加一个
`check_board_card_stability`：断言 hover 前后卡片高度不变。
