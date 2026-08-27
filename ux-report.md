# ResuAlign 求职工作台 — 产品体验问题报告

> 本报告为 2026-08-15 的历史快照，多数问题已在后续迭代中修复。
> 最新一轮狗食测试结论见 `docs/qa-dogfood-report-2026-08-16.md`。

- **测试对象**：ResuAlign-Lite（`D:\ResuAlign-Lite`，前端 `src/resualign/static/app/`，后端 `src/resualign/api/`）
- **测试实例**：隔离实例 `http://127.0.0.1:8631`（独立进程，未触碰用户服务/端口）
- **测试数据**：`D:\ResuAlign-Lite\.scratch\ux-test-data\jobs.db`（全部为测试数据，未操作真实数据）
- **测试时间**：2026-08-15
- **测试方式**：Playwright 真实浏览器（Chromium）驱动，390×844 移动视口与 1440×900 桌面视口；DOM 定位 + API 响应 + 控制台/网络日志分析；截图留档于 `ux_scripts/`（`shot_mobile_nav.png`、`shot_mobile_workspace.png` 等）
- **严重级别定义**：阻塞 = 主流程不可用、数据损坏/丢失或崩溃；高 = 核心功能错误但可绕过；中 = 非核心功能错误、明显体验问题；低 = 细节瑕疵

---

## 一、问题清单（按严重度排序）

### 【高】移动端（≤640px）导航按钮被推出屏幕，完全无法点击

- **复现步骤**：
  1. 打开应用，视口设为 390×844（is_mobile + has_touch）；
  2. 观察顶部导航栏（`.app-rail`），尝试点击任意导航按钮（驾驶舱/工作台/岗位库/简历中心/设置）。
- **实际表现**：导航栏变为横向条（h=78），左侧品牌区 `.rail-brand` 宽 353px 占满整行，5 个 `.nav-btn` 定位 x=377~744，全部落在 390px 视口之外；`elementFromPoint(按钮中心)` 命中为 null；Playwright 点击报错「app-rail/rail-brand intercepts pointer events」。桌面 1440px 正常（rail 为 240px 竖栏）。
- **预期表现**：移动端应显示可点击的横向导航（或隐藏品牌区、允许 tabs 横向滚动）。
- **根因**：`src/resualign/static/styles.css` 存在多个重复的 `@media (max-width: 900px)` 块且规则互相冲突：第 7149 行附近先写 `.rail-brand { display: none }`，随后第 7820 行附近的块又写 `.app-rail .rail-brand { display: block; width: 100% }` 将其重新显示并撑满整行；`.tabs--rail { overflow-x: auto }`（第 2586 行）因 tabs 容器本身已被挤到视口右侧（x≥365）而形同虚设。640px 媒体查询（第 2646 行）只调整了 padding，未处理品牌区。
- **证据**：`ux_scripts/23b_mobile_nav.py` 输出的 DOM 测量（rail 390×78、brand 353 宽、btn x=377~744）、命中测试 null、`shot_mobile_nav.png`；`dispatchEvent` 程序化点击可切换路由（事件 handler 在按钮上，但用户无法真实点击）。
- **影响**：移动端/窄窗口下无法进入任何模块，只能靠地址栏 hash 或命令面板操作，核心入口不可用。
- **建议修复方向（未实施）**：在 ≤900px 时隐藏 `.rail-brand`（或让其收缩为仅 logo），保证 `.tabs--rail` 在视口内并 `overflow-x: auto`；统一去重重复的媒体查询块。

---

### 【中】命令面板确认 JD 后跳转到易失的 session_id，且每次产生一次 404

- **复现步骤**：
  1. Ctrl+K 打开命令面板，选择粘贴 JD 模式，预览并确认；
  2. 观察控制台与地址栏 hash。
- **实际表现**：toast「岗位已入库，正在预分析」后跳转到 `#/workspace/{session.session_id}`（随机会话 id，非岗位 job_id）；控制台出现一次 404（`GET /api/workspace/session/{session_id}`）。刷新后 `loadSession` 靠兜底 `/api/workbench/session/{session_id}` 才加载成功。会话 TTL 为 30 分钟（`src/resualign/api/services/workbench.py:18`，注释明确「intentionally ephemeral (TTL 30 minutes)」），服务重启或 TTL 过期后该深链失效，工作台加载失败。
- **预期表现**：应跳转到 `#/workspace/{job.job_id}`，深链可长期有效；不应产生 404 请求。
- **根因**：`src/resualign/static/app/main.js:2010-2013` `handleForm` 的 `case "command-panel"` 用 `navigate("workspace", session.session_id)`；而 `split-canvas.js:735-750` 的 `loadSession` 先请求 `/api/workspace/session/{id}`（该路由按 job_id 查询，`routers/workspace.py:206`，对 session id 必然 404）再兜底 `/api/workbench/session/{id}`。已用 curl 实测：`/api/workspace/session/{分析任务id}` → 404，`/api/workspace/session/{真实job_id}` → 200。
- **证据**：`ux_scripts/22_command_panel.py`（此前实测记录）；curl 端点行为如上；代码行号见上。
- **建议修复方向（未实施）**：改为 `navigate("workspace", session.job.job_id)`，或让 command-panel 分支直接使用返回的 job_id。

---

### 【中】「取消任务」对运行中的对齐/诊断任务无效，文案误导用户

- **复现步骤**：
  1. 对岗位发起对齐（或对简历发起诊断），任务进入 running 后点击「取消任务」按钮；
  2. 观察 toast 与后台任务状态。
- **实际表现**：toast 显示「任务运行中无法中断，已停止本地等待」，但后台分析任务仍继续运行并最终完成、持久化结果；刷新页面后结果（如对齐版本/诊断分数）仍会出现。用户在界面看到的是「已取消」的暗示，实际结果照常落库。
- **预期表现**：要么真正中断任务并标注失败/取消，要么文案明确说明「任务将继续在后台完成，结果仍会保存」，避免误导。
- **根因**：后端只支持取消 queued 任务——`src/resualign/api/routers/jobs.py:119-130` 对 running 任务返回 409「Only queued jobs can be canceled」；`routers/batch.py:43-44` 注释明确「running rows are not interrupted」。前端 `main.js:864`（诊断）与 `split-canvas.js:1140`（对齐）对非 queued 状态只停止本地轮询并提示「已停止本地等待」。
- **证据**：`ux_scripts/24b_cancel_align.py` 实测：排队 ~2.5s 后点击取消，toast 如上；后台任务 `9f37e18e…` 状态仍为 running 并最终完成；后端代码如上。
- **建议修复方向（未实施）**：按 queued/running 区分按钮文案与提示；或对 running 任务不做「取消」语义，改为「停止等待，结果将在后台完成」的明确说明。

---

### 【中】采纳改写建议的计数不持久化，刷新后「已采纳」数量丢失

- **复现步骤**：
  1. 工作台对齐完成后，采纳 1 条改写建议（按钮变「已采纳」，计数显示「1 已采纳」）；
  2. 刷新页面。
- **实际表现**：刷新后计数回到「0 已采纳」，但最终稿（final_draft）内容仍包含已采纳语句。用户看到「0 已采纳」与最终稿内容自相矛盾。
- **预期表现**：已采纳状态应持久化，刷新后仍显示 1 已采纳。
- **根因**：采纳状态只存在前端内存 `state.wbAcceptedBullets`（`main.js:1417-1433`），后端 `POST /api/jobs/{job_id}/final-draft`（`routers/jobs.py:157-165`，`save_final_draft`）只持久化 draft 文本，不更新任何采纳/验证状态（diffs 的 `provenance_state` 仍为 'verified'）。渲染侧 `split-canvas.js:113-118`（`acceptedIds`）、157、185 都基于内存状态。
- **证据**：`ux_scripts/09_accept_save.py` 与 `10_reload.py` 实测（采纳→刷新→计数归零）；代码定位如上。

---

### 【中】粘贴 JD 不提取公司/城市，首行含公司信息的 JD 仍显示「未知公司 · 未知城市」

- **复现步骤**：
  1. 命令面板/岗位库粘贴一段首行含公司名与城市的 JD（如「公司：XX 科技，地点：上海」）；
  2. 查看入库岗位卡片。
- **实际表现**：卡片显示「未知公司 · 未知城市」并带「待补全」徽标（`format.js:1874-1883` 的 `jobCompletenessBadge`，缺失项 company/salary 等）。
- **预期表现**：JD 中明显存在的公司/城市信息应被提取填入（薪资已有 `extract_salary_range` 提取逻辑可作参照）。
- **根因**：`src/resualign/api/services/jobs.py:186` `_create_job_from_source` 直接 `company=payload.get('company'), location=payload.get('location')` 存传入值，无任何从 jd_text 解析公司/城市的逻辑；仅薪资有提取。
- **证据**：`ux_scripts/22_command_panel.py`、`16_edge_cases.py` 实测记录；代码定位如上。
- **备注**：CSV 批量导入缺 company 时显示「未知公司 · 北京」属正常降级显示（该场景正常）。

---

### 【中/低】驾驶舱「快速继续」卡片与状态 pill 暴露英文状态值

- **复现步骤**：打开驾驶舱，观察「快速继续」卡片。
- **实际表现**：卡片显示「未知公司 · succeeded」，pill 显示英文 `succeeded`，未汉化为「已对齐」；应用其余界面均为中文。
- **预期表现**：应显示「已对齐」等中文状态。
- **根因**：`src/resualign/static/app/dashboard-view.js:61, 109, 112` 直接输出 `alignment_status` 原始值（`escAttr(quick.alignment_status)`），未做状态文案映射；岗位库等其他视图有 `jobStatusLabel`/`canonicalJobStatus` 映射（`format.js`），驾驶舱未复用。
- **证据**：DOM 实测文本；代码行号如上。

---

### 【低】粘贴 JD 的标题推导缺陷：括号残留、整行 noise 判空、单行粘贴整行变标题

- **复现步骤**：
  1. 粘贴首行带「【测试岗位】高级数据分析师…」的 JD → 标题为「测试岗位】高级数据分析师」（残留右括号】）；
  2. 粘贴首行为「【招聘】…」整行描述的 JD → 标题为「未命名岗位」；
  3. 粘贴无换行的整段 JD（单行）→ 整行都成为标题（最长 120 字符）。
- **实际表现**：标题推导与用户预期不符；命令面板实测创建了 title 为「测试岗位】高级数据分析师…」（整行 JD + 残留】）的岗位。
- **预期表现**：正确剥离【】对并识别真实岗位名；「招聘」行应被当作 noise 跳过而不是整行丢弃；单行文本应尝试截取合理标题。
- **根因**：`src/resualign/api/services/jobs.py:85-124` `_clean_title_candidate` 用 `_TITLE_BRACKET_RECRUIT.sub("", line).strip(" 【】")` 只去掉「【…】招聘」整段或右括号，无法处理「【测试岗位】」这类不匹配 `_TITLE_BRACKET_RECRUIT` 的前缀；`_is_title_noise`（第 93 行）对含「【招聘】」的行直接返回 True 导致 `_derive_title` 跳过整行；无换行输入时第一行即整段 JD。
- **证据**：`ux_scripts/22_command_panel.py` 实测（岗位 `218ccb12…` 标题含残留】）；代码定位如上。

---

### 【低】导出菜单内「已生成」徽标语义模糊

- **复现步骤**：工作台打开导出下拉菜单（草稿生成后）。
- **实际表现**：导出菜单项旁出现 `<span class="badge badge-green">已生成</span>`（`src/resualign/static/app/format.js:687`），用户难以分辨是指「草稿已生成」还是「该导出项已生成过」。
- **预期表现**：文案更明确（如「草稿已生成」），或改为导出项状态（已导出/未导出）。
- **根因**：`format.js:677-687` `exportDock` 中徽标绑定在 `alignment.draft` 上，语义指向草稿已生成，但位于导出下拉内造成歧义。
- **证据**：DOM 实测；代码定位如上。

---

### 【低】对齐后未显式保存即显示「已生成定稿」并推进引导

- **复现步骤**：对齐完成后不点击任何保存，观察工作台引导步骤。
- **实际表现**：自动生成的 draft 被当作 final_draft，界面显示「已生成定稿」并推进引导到「记录投递」；用户未显式保存即被视为定稿（`format.js:1569-1592` `workbenchGuideSteps` 步骤 2 label「已生成定稿」；`split-canvas.js:133` `guideJob = job.final_draft`）。draft 已由 `save_alignment` 持久化，刷新后仍在，不会丢数据。
- **预期表现**：定稿语义上应区分「草稿已生成」与「用户确认的定稿」，避免误导用户以为已保存确认。
- **根因**：前端将 draft 与 final_draft 等同展示；属产品语义模糊，非数据错误。
- **证据**：`ux_scripts/07/08_alignment*.py` 实测记录；代码定位如上。

---

## 二、主流程与正常功能验证摘要（未发现问题）

以下流程经真实操作验证均正常，无 console error / 4xx：

1. **简历中心**：新建主简历（表单/弹窗）→ 编辑（标题/内容/版本 v2 保存）→ 上传解析 → 删除；版本号与内容正常。
2. **岗位库**：新建岗位（填公司/城市正常）→ 编辑（公司/城市/标签保存后卡片即时更新）→ 删除（确认弹窗 → 确认 → 卡片消失）；批量导入 CSV 2 条全部入库，状态轮询「完成：新建 2」。
3. **对齐主流程**：选择岗位 → 运行对齐（进度条/事件流）→ 结果 diff 展示 → 采纳/拒绝 → 导出（另存为 PDF/Markdown）→ 记录投递 → 驾驶舱 KPI 更新；draft 持久化刷新不丢。
4. **命令面板 Ctrl+K**：搜岗位模式（建议 → Enter 跳转岗位工作台）正常；Esc 关闭正常；重复岗位 409 弹窗提示正常。
5. **诊断**：诊断主简历 → 进度条 + 取消按钮可见 → 结果 45/100「需重点优化」+ 导出入口正常。
6. **重新分类**：confirm 弹窗 → 接受 → toast「分类成功：前端 · 未知 · React」正常。
7. **设置页**：LLM「测试连通性」→「HTTP ok · 2359 ms 连接成功：deepseek · deepseek-v4-flash」；API Key 掩码显示 `sk-b••••e9de`；词表追加后岗位库筛选下拉立即同步；「恢复默认设置」正常还原。
8. **移动端工作台布局（390px 补测）**：`#/workspace/{job_id}` 在 390px 视口正常渲染——无横向滚动（docScrollW=390）、`wb-mobile-tabs`（调优/结果）可见且可点击、各面板（context/main/aux）均在视口宽度内、无 console error/4xx；唯一越界元素为已知的导航按钮（见【高】）。
9. **SSRF 防护**：parse-jd-link 对本地/非 80/443 端口 URL 返回 502 并提示「链接格式无效」，属设计行为；公共 URL（example.com）解析成功。

## 三、已排除项（确认非 bug）

- 新建主简历弹窗出现时命令面板常驻 DOM 但未实际打开 → 非 bug。
- 重复岗位返回 409 弹窗 → 符合预期。
- parse-jd 本地 URL 502 → SSRF 安全设计。
- 岗位状态存「未投递」、显示时经 `canonicalJobStatus` 映射为「草稿」→ 设计行为。

## 四、待确认/未覆盖项

- `server.err.log` 中历史错误（JDProfile 参数不匹配、schema validation failed）疑似旧开发痕迹，非本次测试产生，**待确认**，未纳入问题清单。
- 移动端在「驾驶舱/岗位库/简历中心/设置」四个页面除导航不可点击外的页面内部布局，因导航按钮不可点击（【高】）无法通过常规点击进入验证；已通过 hash 直达验证工作台页面布局正常，其余页面布局**待确认**（预计与工作台同样由 CSS 网格堆叠处理，但未经实测）。
- 多标签并发/多用户并发场景未做深测。
- 服务端定时任务/通知类功能未覆盖。

## 五、测试收尾

- 隔离测试实例 `http://127.0.0.1:8631` 与临时静态服务器 `http://127.0.0.1:8641` 将在测试完成后停止；测试数据目录 `D:\ResuAlign-Lite\.scratch\ux-test-data\` 保留供复现。
- 测试脚本保留于 `ux_scripts/`（01~25），可复现本报告所有结论。
