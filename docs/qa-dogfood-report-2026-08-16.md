# 🧪 产品体验与缺陷报告 - ResuAlign-Lite Dogfood Round 2026-08-16

## 1. 体验总览 (Executive Summary)

* **体验角色**：新用户 / 深度创作者 / 破坏性测试者
* **健康指数**：🟢 仅体验调优（0 个 P0-P2 缺陷）
* **核心体感**：主路径完整顺滑，移动端导航、工作台深链、采纳状态持久化、
  JD 字段提取等上一轮问题均已修复；本轮未复现功能缺陷，仅有 1 个无效深链
  控制台噪音（P3）和少量可选的交互调优点。

---

## 1.5 修复记录 (Implemented This Round)

| 报告项 | 处理 | 验证 |
| --- | --- | --- |
| Bug-01 无效工作台深链双 404 | `renderOptimizerCanvas` 先确认岗位存在，不存在直接 toast + 回退驾驶舱；`loadSession` 不再探测 legacy `/api/workbench/session/` 路由 | DOM 单测 + QA harness 通过，无效深链 0 次 session 404 |
| Bug-02 路由切换后迟到的工作台渲染覆盖新视图 | `renderSplitCanvas` 增加 `state.route.name === "workspace"` 守卫；`pollSessionFallback` 在每次 await 后重新校验轮询仍存活，避免旧响应重绘岗位库 | 新 DOM 单测 + QA harness 连续两轮 0 findings |
| UX：移动端工作台自动选岗提示 | 自动打开最近岗位时 toast「已自动打开最近岗位，可在顶部切换」 | 源码契约测试 + harness 通过 |
| UX：快速继续「未知公司」文案 | 驾驶舱快速继续改为「未识别公司」 | 源码契约测试通过 |
| UX：无效深链回退提示 | 回退驾驶舱前 toast「岗位不存在，已返回驾驶舱」 | DOM 单测断言 toast 文案 |
| 加固：空 job_id 对齐提交 | `startAlignmentRun` 增加空 job_id 守卫，避免偶发 `/api/jobs//workbench` 坏请求 | harness 多轮通过 |
| 加固：QA harness 路由竞态 | `Runner.goto` 先等待 hash 落入目标路由（含 `#/workspace` 自动跳岗），岗位库断言前等待 `#job-board` 渲染 | 连续两轮 0 findings |

---

## 2. 缺陷与体验问题清单 (Defect Items)

### 🟢 [Bug-02] [工作台/路由] 切回岗位库时，迟到的 workbench 渲染覆盖新视图（已修复）

* **严重级别**：P2-严重交互受阻（间歇）
* **问题类别**：状态同步
* **复现环境**：Chromium headless / 1440×900 / 隔离实例；对齐开始后 2-3 秒内
  从 `#/workspace/<jobId>` 切到 `#/jobs`

#### 🐾 严格复现步骤 (Step-by-Step Reproduction)
1. 通过命令面板创建岗位并进入工作台。
2. 发起对齐，随后立即点击左侧「岗位库」。
3. 观察 `#app-router-view`：岗位库看板可能被迟到的 workbench 画布覆盖。

#### ⚖️ 现象比对 (Expected vs. Actual)
* **实际现象 (Actual)**：路由 hash 已是 `#/jobs`，但看板在 10-15 秒后仍可能
  显示工作台内容（`data-live-sheet` / 岗位上下文），`#job-board` 不存在；
  控制台无 JS 异常，`GET /api/jobs` 正常返回新岗位。
* **预期行为 (Expected)**：路由切走之后，任何迟到的 workbench SSE/轮询/加载
  响应都不得重绘 `#app-router-view`。

#### 🔍 疑似根因与线索 (Suspected Cause & Code Context)
* **疑似文件/位置**：`src/resualign/static/app/split-canvas.js`
  - `renderSplitCanvas` 不校验当前路由；
  - `pollSessionFallback` 在 `await fetch` 之后不校验轮询是否已被
    `stopPollingFallback()` 停止。
* **状态/网络线索**：`console-all.log` 中多次出现
  `GET /api/workbench/session/{id} -> net::ERR_ABORTED`，而失败快照
  `debug-job-board.html` 的 `#app-router-view` 仍是工作台三栏结构。

#### 🤖 编码 Agent 专用修复 Prompt (Coder Agent Instruction)
> "修复工作台迟到渲染覆盖其他路由的问题：
> 1. 在 `renderSplitCanvas` 入口校验 `state.route.name === 'workspace'`，
>    非工作台路由直接 return（DOM 单测需先设置 `state.route`）。
> 2. 在 `pollSessionFallback` 的 `await fetch` 与 `await response.json()`
>    之后重新校验 `fallbackPollTimer && activeSession`，失效则丢弃响应。
> 3. 验收标准：对齐运行中切到 `#/jobs`，看板稳定显示；快速往返
>    `#/workspace` / `#/jobs` 10 次无旧画布覆盖。"

### 🟢 [Bug-01] [工作台/路由] 无效工作台深链触发两次 404 后回退，控制台留噪音（已修复）

* **严重级别**：P3-体验优化
* **问题类别**：性能与控制台
* **复现环境**：Chromium headless / 1440×900 / 隔离实例（fake LLM + 临时 DB）

#### 🐾 严格复现步骤 (Step-by-Step Reproduction)
1. 直接访问 `#/workspace/__missing_job__`（不存在的岗位 id）。
2. 观察网络面板与浏览器控制台。
3. 等待前端回退到驾驶舱。

#### ⚖️ 现象比对 (Expected vs. Actual)
* **实际现象 (Actual)**：页面最终正确回退到 `#/dashboard`，但回退前先请求
  `GET /api/workspace/session/__missing_job__`（404），再请求
  `GET /api/workbench/session/__missing_job__`（404），控制台出现两条
  `Failed to load resource: 404`。证据见
  `.scratch/qa/console-all.log`。
* **预期行为 (Expected)**：无效岗位深链应只做一次存在性查询（例如直接查
  `/api/jobs/{id}`），未命中即回退，避免对明显无效 id 连续探测两个
  legacy 路由并产生控制台错误。

#### 🔍 疑似根因与线索 (Suspected Cause & Code Context)
* **疑似文件/位置**：`src/resualign/static/app/split-canvas.js`
  `loadSession` 的 `/api/workspace/session/{id}` → `/api/workbench/session/{id}`
  双兜底逻辑（旧命令面板 session_id 问题修复后仍保留 legacy 探测）。
* **状态/网络线索**：`check_missing_workspace_job` 探针与
  `console-all.log` 的第 5-8 行完全一致。
* **修复状态**：已修复。`renderOptimizerCanvas` 现在先用岗位库列表确认
  job 存在，不存在时 toast 并直接回退；`loadSession` 只走
  `/api/workspace/session/{job_id}`，不再探测 legacy 路由。

#### 🤖 编码 Agent 专用修复 Prompt (Coder Agent Instruction)
> "优化无效工作台深链的降级路径：
> 1. 在 `split-canvas.js` 的 `loadSession` 中，先通过 `/api/jobs/{jobId}`
>    判断岗位是否存在；存在但无 session 时走 `buildSessionFromJob`，
>    不存在时直接回退 `#/dashboard`，不再探测 legacy session 路由。
> 2. 保留命令面板已生成的合法岗位深链行为不变。
> 3. 验收标准：访问 `#/workspace/__missing_job__` 时控制台无 404 资源错误，
>    访问真实岗位 id 时工作台正常渲染。"

---

## 3. 上一轮问题回归验证 (Regression Checks)

以下均为旧版 `ux-report.md` 或历史对话中的问题点，本轮加入针对性探针后
全部通过：

| 旧问题 | 本轮验证方式 | 结论 |
| --- | --- | --- |
| 移动端（390px）导航按钮被推出屏幕无法点击 | `check_mobile_nav_clickable`：逐一命中测试并真实点击 5 个按钮 | ✅ 全部可点击、路由正确 |
| 命令面板确认 JD 后跳转易失 session_id 且产生 404 | 确认后断言 hash 为 `#/workspace/{job_id}`，监听 `/api/workspace/session/` 4xx | ✅ 深链为真实岗位 id，无 404 |
| 「取消任务」对 running 任务文案误导 | 代码核对：running 显示「停止等待」，toast 明确“任务将继续在后台完成，结果仍会保存” | ✅ 文案已修正 |
| 采纳改写建议计数刷新后丢失 | 对齐后采纳 1 条 → F5 → 断言 `已采纳` 计数与禁用标记仍在 | ✅ 后端已持久化 accepted_diff_ids |
| 粘贴 JD 不提取公司/城市 | API 级用例：`公司：星河科技 / 地点：上海` 创建岗位 | ✅ company/location 正确落库 |
| 驾驶舱快速继续暴露英文状态 | 对齐后断言 quick-continue 无 `succeeded/running/queued/failed/idle` 原文 | ✅ 全部中文映射 |
| JD 标题推导括号残留/整行 noise/单行变整行标题 | 3 个 API 用例：`【测试岗位】…`、`【招聘】高薪诚聘…`、无换行 JD | ✅ 标题均准确且无噪声 |
| 导出菜单「已生成」徽标语义模糊 | 代码核对 `format.js` | ✅ 已改为「草稿已生成」 |
| 对齐后未显式保存即显示「已生成定稿」 | 代码核对 `workbenchGuideSteps` | ✅ 已区分「已生成草稿 / 已生成定稿」 |

---

## 4. 体验优化与 Vibe 建议 (UX Polish & Enhancements)

- **[控制台静默失败]** 工作台 SSE/轮询在路由切换时以 `net::ERR_ABORTED`
  结束属于正常的主动清理，但建议统一使用 `AbortController` 并抑制这类
  请求失败的日志，避免排查时误判。
- **[交互微调]** 移动端「工作台」导航会自动进入最近更新岗位；多岗位用户
  建议在进入时短暂展示“已自动打开最近岗位，可用顶部选择器切换”的提示，
  降低“我怎么突然进了这个岗位”的困惑。
- **[空状态]** 驾驶舱「快速继续」对尚未对齐的岗位显示「待分析 · 未知公司」；
  若 JD 确无公司信息，可将文案改为「未识别公司」并引导补全，语义更准确。
- **[文案调优]** 无效深链回退到驾驶舱前约 1-2 秒无明显转场提示，建议保留
  toast「岗位不存在，已返回驾驶舱」，避免用户感觉被“弹走”。

---

## 5. 测试证据与复现方式 (Evidence)

* **Harness**：`scripts/qa_dogfooder.py`（隔离实例自动启动 fake LLM +
  临时 SQLite + 随机端口，结束后清理）。
* **运行命令**：
  ```powershell
  python scripts\qa_dogfooder.py
  ```
* **结果文件**：
  - `.scratch/qa/findings.json`：本轮 `[]`（0 条记录级 finding）
  - `.scratch/qa/console-all.log`：全量 console / requestfailed / 4xx 证据
  - `.scratch/qa/desktop-*.png`、`.scratch/qa/mobile-*.png`：各路由截图
* **覆盖维度**：主路径与认知负荷、极端与异常边界、状态一致性与持久化、
  响应式与视觉交互、控制台与静默失败；桌面 1440×900 与移动 390×844
  双视口。
