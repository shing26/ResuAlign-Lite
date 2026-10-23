# UI/UX 审计：驾驶舱 / 投递复盘 / 系统设置

- 审计人：audit-dashboard（只读审计，未改动 `src/` 任何文件）
- 日期：2026-10-22
- 现场：`http://127.0.0.1:8000`，真实数据（318 岗位 / 1 已投递 / 22 已对齐 / 0 优化条目 / 7 份简历）
- 范围：`dashboard-view.js`、`review-view.js`、`settings-form.js` + `main.js::renderSettingsView`、`format.js` 中对应渲染函数、`styles.css`

## 0. 证据与限制（先看这段，决定下面数字怎么来的）

**用了什么**

1. 只读 GET：`/api/dashboard`、`/api/jobs?limit=500`、`/api/review`，核对页面数字与后端字段。
2. Playwright 只读渲染 **驾驶舱 / 投递复盘**（1440×900 与 390×844 两种视口），读取 DOM 几何（`getBoundingClientRect`）与 computed style。抓到的关键数值都写在正文「证据」里，可复现。
3. **设置页**：为避免触发页面加载时自动发出的 LLM 探针（见 S3，`POST /api/llm/nodes/{id}/test`，真实 provider 请求），用 Playwright 拦截该请求后再渲染简单/专家两种模式并测量。拦截计数 = 2 次（两次访问各一次）——这本身就是 S3 的证据：**页面确实会自动发起该请求**，只是被我拦下，没有产生费用。
4. 截图：`.scratch/ui-audit-2026-10-22/shots/` 下已有截图；我另外把局部放大图放在 `%TEMP%`（未写入工作区，避免污染交付目录），正文用「区域描述」+ 数值代替。

**没做什么**：未点击保存 / 测试连接 / 恢复默认 / 标注 / 批量对齐；未提交表单；未写入任何表；未改 `src/`。切换「简单/专家」只写 `localStorage`（`main.js:2088-2095` → `writeSettingsMode`），已确认不写库。

**已知干扰**
- `census.json` 是 UTF-8，但 PowerShell `ConvertFrom-Json` 用默认编码读会乱码，故未作为证据源；下面所有数值来自我自己的只读测量。
- **工作区在审计期间被并发修改**：`git status` 显示 `src/resualign/static/app/format.js`、`styles.css`、`index.html`、`tests/frontend/adr0033.test.mjs` 有他人改动（19:54 前后，属岗位库卡片重构，不是本审计所为——我只写了本文件）。本文所有 `文件:行号` 已在 **19:58 以当前工作区版本重新核对**（`format.js` 因卡片改动整体 +6 行、`styles.css` +51 行，已按其偏移修正）。若 Lead 后续再改这几个文件，行号需再对一次；每条问题同时给了选择器/函数名，可按名定位。

**总量**：18 条（P0 × 1、P1 × 11、P2 × 6）+ 2 条跨模块一致性（X1 P1、X2 P2），预估合计 ≈ 13.5 人时。

---

## 1. 驾驶舱

### D1 [P0] 「最近岗位动态」长标题横向溢出，压住「状态」和「更新时间」列

**证据**
- `dashboard-view.js:275`：`<a class="recent-job__title">` 直接塞进 `<td>`。
- `styles.css:8998-9003`：`.recent-job__title { overflow:hidden; text-overflow:ellipsis; white-space:nowrap }` —— 这套写法是为旧的列表布局 `.recent-job`（grid 子项）写的。
- `styles.css:11494-11499`：`.dashboard-view .data-table { table-layout: fixed }`，且**没有 colgroup / 列宽声明**。
- 实测（1440×900）：表格 654px 宽，4 列**各 164px**；`.recent-job__title` computed `display:inline`（行内元素 → `overflow`/`text-overflow` 不生效，只剩 `white-space:nowrap`），链接盒子实测宽 **499px**（第 2、3 行 254px / 244px）。
- 实测布尔值：`titleOverlapsStatus = true`（3/3 行）、`titleOverlapsTime = true`（第 1 行）。第 1 行 `2026-10-22 19:32` 的 `textContent` 存在但被标题文字**盖在上面**。
- 截图：`desktop-dashboard.png` 表格第 1 行（`…Internship Program-Engineer（MJ001827）` 一路压过「未投递」并压到日期上）；第 2、3 行 `招）` / `）` 从徽标右侧露出来。`desktop-dashboard-dark.png` 同样复现。

**用户影响**：三行里状态徽标和时间被标题压成重叠字，看起来像「未投递」徽标压字 + 更新时间列空着」——第一眼就是「这页面坏了」。

**根因**（两层，缺一不可）
1. `.recent-job__title` 是 `<a>` 行内元素，`overflow:hidden` / `text-overflow:ellipsis` 对 inline 无效；`styles.css:8998` 这套规则只在原来的 grid/flex 列表项里成立。
2. 表格 `table-layout: fixed` + 四列均分 164px，没给「岗位」列更高权重；「操作」列同样占 164px，实际只放了一个 16px 图标（浪费约 120px）。

**改法建议**
- JS：`dashboard-view.js:275` 改为
  `<td class="recent-job__cell"><a class="recent-job__title" title="${escAttr(job.title)}">…</a></td>`；
- CSS（新增，只作用于表格）：
  ```css
  .dashboard-view .recent-table .recent-job__cell { min-width: 0; overflow: hidden; }
  .dashboard-view .recent-table .recent-job__title {
    display: block; max-width: 100%;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  ```
- 列宽：给 `.recent-table` 加 `<colgroup>`（岗位 `auto`、状态 `96px`、更新时间 `150px`、操作 `44px`），或 CSS：`.recent-table th:nth-child(2){width:96px}` / `:nth-child(3){width:150px}` / `th:last-child{width:44px}`。

**预估工时**：0.5–1 h（含浅色/深色/移动端各一张回归截图）

---

### D2 [P1] KPI 条与下方卡片左右边缘错开 22px

**证据**：实测 `[data-dashboard-kpis]` 为 `x=270, w=1120`；`.dash-grid` 为 `x=248, w=1164` → 左右各缩进 22px。根因 `styles.css:11346-11352`：`.dashboard-view .metric-strip.dashboard-strip { max-width: calc(var(--space-1) * 280); margin-inline: auto }`（= 1120px），而下方的 grid 撑满 1164px。

**用户影响**：顶部四个数字和下面两张卡不在一条竖线上，页面整体显得「差一点对齐」，是典型的廉价感来源。

**改法建议**：把该 `max-width` 去掉（`max-width:none`），与 grid 同宽；若想保留窄栏，则给 `.dash-grid` 同宽约束（推荐前者，一行改动）。

**预估工时**：0.25 h

---

### D3 [P1] 「快速继续」卡下方 135px 死区：内容撑不满卡片

**证据**：实测左卡 `panel` 高 505px，`panel-body` 结束于 595，最后一个子元素（`.recent-jobs`）底边 575 → **卡内空白 135px**；右列技能缺口 `panel-body` 高 411px（8 行表格）把 grid 行撑高。根因：`styles.css:7253-7262` `.dash-grid { align-items: stretch }` + `.dash-grid .panel { min-height: 360px }`，行高由较高的右列决定，左侧内容不纵向分配。

**用户影响**：屏幕上最贵的位置出现一大块空白，读起来像「内容没加载完」，用户不知道该往下看什么。

**改法建议**（三选一，推荐 a + b 组合）
- a) `.dashboard-view .dash-grid { align-items: start }`，让两卡各自高度（0.25h，但两卡底边不齐，需视觉确认）；
- b) `.recent-jobs` 由 3 条扩到 5–6 条 + 底部加「查看全部岗位 →」出口（见 D8），把空白变成内容（0.3h）；
- c) 面板改 flex column，`.recent-jobs { flex:1 }`，给「最近动态」更多行（0.5h）。

**预估工时**：0.5 h

---

### D4 [P1] 「已完成对齐 22/318」与「已优化条目 0 条」并排自相矛盾（时间窗口未标注）

**证据**：`GET /api/dashboard` 实测 `kpi.jobs=318`、`quality={window_days:7, saves:0, diffs_accepted:0, diffs_total:0}`。`dashboard-view.js:100-107` 的 `alignedCount` 是**历史全量**（`alignment_status==='succeeded' && usable_diffs>=1`）且不标时间；`:131-174` 的「已优化条目」带「近 7 天」。截图 `desktop-dashboard.png` KPI 第 2、4 格：`22 /318 完成率7%` 与 `0 条 近 7 天·定稿0次·采纳 0/0 条建议`。

**用户影响**：22 次对齐完成、却 0 条优化产出，用户第一反应是「数据坏了」或「对齐白做了」，信任成本极高；`采纳 0/0 条建议` 还像除零 bug。

**根因**：一个 KPI 是全量口径、一个带 7 天窗口，但只有后者写了时间窗；「完成对齐」也不区分 `usable_diffs>=1`（真有改写建议）与 `no_gap`（无缺口）。

**改法建议**
- 「已完成对齐」下加同款时间窗说明，或统一改成同一窗口（产品口径，见「需要 Lead 决策」#2）；
- `quality.diffs_total === 0` 时 hint 改成「近 7 天暂无建议记录」，不要输出 `0/0`；
- 可选：`22 / 318` 旁加一行「其中无缺口 N 条」（数据已有：`noGapCount`，`dashboard-view.js:103-105`）。

**预估工时**：0.5 h

---

### D5 [P1] 技能缺口榜的热力配色完全失效：8 条全部同色

**证据**：实测 `.meter-cell` 的 className 是 `meter-cell ord-5`，但内层 `.meter` 的 computed `color = rgb(106,115,129)`（来自 `styles.css:11405` 的 `--text-tertiary`），8 条 `.meter__fill` 背景全部 `rgb(106,115,129)`。原因：`format.js:2879-2880` 把强度类 `ord-5/ord-4/…` 加在 **`.meter-cell`** 上，而配色选择器是 `styles.css:11420-11438` 的 **`.meter.ord-1…5`**，类永远落不到 `.meter` 上。放大截图可见 8 条全是同一种灰蓝（`desktop-dashboard.png` 右栏）。

**用户影响**：「需求强度」列只剩长度信息，137（Java）和 42（Go）的冷热档看不出差别，热力编码等于白做；也无法一眼判断「最该先补哪个」。

**改法建议**：二选一
- `format.js:2874`：`<span class="meter meter--sm ${strength}">`（把类移到 `.meter` 上）；或
- 补 5 条 CSS：`.meter-cell.ord-1 .meter{color:var(--ord-1)} … .ord-5`。

**预估工时**：0.25 h

---

### D6 [P1] 「技能缺口」只表达需求频次，不表达「我缺什么 / 先补哪个」

**证据**：`dashboard-view.js:251-259` 把 `/api/dashboard.skill_gaps` 直接交给 `format.js:2854-2904` 的表格；接口契约只有 `{skill, count}`（实测：`[{"skill":"Java","count":137}, …]`），没有「主简历是否已有」字段。表头是「需求岗位 / 需求强度」，卡片副标题是「目标岗位高频硬技能」，但数据是整个 318 岗位库的技能画像。唯一的行动指引是表格底部一段 11px 灰字（`format.js:2903`）。整块占首屏右栏 420×411px。

**用户影响**：这是全站最典型的「无从下手」：给了一个 137 的大数字，既不说这算不算「我缺」，也不说下一步做什么；用户要么忽略，要么被吓到。

**根因**：接口契约 `{skill,count}` 无法区分「岗位要求」与「简历缺失」——前端拿不到「缺/已覆盖」，所以只能显示需求热度却挂在「缺口」标题下。

**改法建议**
- 短期（纯前端，推荐先做）：标题改「岗位高频技能」，副标题改「318 个岗位里被要求最多的硬技能」；表头「需求岗位」→「要求岗位数」；首行加一句 + 主 CTA「拿主简历对比一次 → #/workspace」；
- 中期（需后端）：`skill_gaps` 增 `covered: bool`，前端拆成「待补 N 项 / 已覆盖 M 项」两段，热力只作用于「待补」。

**预估工时**：1 h（短期）/ +2 h（含后端字段）

---

### D7 [P2] 「最近岗位动态」副标题写「投递快照」，内容却是全库按更新时间排序

**证据**：`dashboard-view.js:304` 文案 `最近 3 条 · 投递快照`；数据来自 `dashboard-view.js:261-269`（`/api/jobs` 按 `updated_at` 倒序、排除快速继续那条、`slice(0,3)`）。实测三行状态全是「未投递」（`status=draft`）。而「投递快照」在本产品里是另一个专有概念（`printTarget('snapshot')`，`main.js:839-846`）。

**用户影响**：用户以为这是投递记录，点进去发现是没投过的岗位；同时真正**唯一**那条已投递岗位（腾讯 / 后台开发）因为时间早被挤出列表，看板上永远看不到「我投了什么」。

**改法建议**：副标题改「最近更新 · 全库」；并把「已投递/面试中」的岗位固定 pin 一行（或按状态加权排序），保证漏斗有实际进展时一定出现在动态里。

**预估工时**：0.3 h

---

### D8 [P2] 「最近 3 条」硬截断，没有「查看全部」出口

**证据**：`dashboard-view.js:269` `.slice(0, 3)`；卡片头部的唯一链接是「进入完整工作台 → #/workspace」（`:297`），不是岗位列表。库里有 318 条。

**用户影响**：想看更多岗位必须自己想起来去左侧「岗位库」；从驾驶舱没有横向出口。

**改法建议**：`.recent-jobs__head` 右侧加 `<a class="link" href="#/jobs">查看全部 318 个岗位 →</a>`，并把 slice 放到 5。

**预估工时**：0.25 h

---

### D9 [P2] 四格 KPI 只有第一格可点，可点击性不一致

**证据**：实测 `[data-dashboard-kpis]` 四格内 `a/button` 数量 = `4 / 0 / 0 / 0`。`dashboard-view.js:144-157` 的 4 个 `count-pair` 是 `<a>`（带 `aria-label`），`:159-174` 三格是纯文本。

**用户影响**：用户学会「数字能点」之后点「已完成对齐 22」没反应，形成「有些地方点了没用」的坏印象。

**改法建议**：统一——要么三格也变成链接（`#/jobs?aligned=1`、`#/resume`、`#/workspace`），要么把第一格的 4 个 `count-pair` 降级成纯文本、只保留 `href` 在整格上。

**预估工时**：0.5 h

---

### D10 [P1] 移动端：KPI 条吃掉首屏 384px，且四格高度不一致（109/65/84/66）

**证据**：390×844 实测 `.dashboard-strip` = `x16 y234 w358 h384`（到 y=618），`.dash-grid` 从 **y=638** 才开始；四格高度 **109 / 65 / 84 / 66**，间距 20px，无分隔线。`styles.css:11613-11626` 在 ≤640px 只改了 `grid-template-columns: 1fr` 和 padding，没做密度收敛。

**用户影响**：手机上打开驾驶舱，第一屏只有四组数字（其中两块还矮一截），唯一入口「快速继续」在 700px 以下——这就是「无从下手」的第一现场。

**改法建议**：移动端把 4 格改成 2×2 紧凑网格（大数字 + 一行标签，次级 hint 收进 `title`/折叠），整条目标 ≤180px；或只保留「跟踪岗位 / 已完成对齐 / 待处理」三格。配套：`.dashboard-strip{ grid-template-columns: repeat(2, minmax(0,1fr)); gap:8px 16px }`。

**预估工时**：1 h

---

### D11 [P2] 移动端 topbar 占 208px：主题按钮独占一行 + 全宽搜索独占一行

**证据**：`mobile-dashboard.png` y0–208（导航 0–49、页标题 84、主题切换 120–155、搜索 165–205）；`styles.css:11606-11611` 在 ≤640px 把 `.topbar-title` 改为纵向。主题按钮为 `padding:8px 12px` 的文字按钮（`styles.css:10926-10942`）。

**用户影响**：首屏被界面 chrome 吃掉 1/4，进一步加剧 D10。

**改法建议**：≤640px 时主题切换收成 32×32 图标按钮并入标题行右侧；搜索收成图标，点开后走已有 `Ctrl+K` 命令面板。

**预估工时**：0.75 h

---

### D12 [P2] 移动端表格仍是 4 列 × 71px：标题 499px 溢出（D1 的放大版）

**证据**：390 宽实测 `td` 各 **71px**、行高 **73px**（桌面 39px），`titleOverlapsStatus/Time` 全为 `true`（第 1 行链接宽 499px）。截图 `mobile-dashboard.png` 需滚动到 y≈940 才能看到该区域。

**用户影响**：手机上这张表根本不可读，状态和时间全部被标题覆盖。

**改法建议**：≤640px 换成卡片列表：第一行「岗位名（`-webkit-line-clamp:2`）+ ›」，第二行「状态徽标 · 更新时间」。可复用项目里已有的 `.recent-job` grid 样式（`styles.css:8973-9003`），它本来就是为窄屏双列写的。

**预估工时**：1 h（与 D1 同一批做，边际成本低）

---

## 2. 投递复盘

### R1 [P1] 「本周投递节奏」7 天全 0 时只画出 7 个 5px 灰条，没有空态与引导

**证据**
- `review-view.js:14-30`：`paceBars()` 对 `count=0` 也渲染元素，高度 `Math.max(pct, count ? 12 : 4)`；`count` 文本为空串。
- `styles.css:10975-11001`：`.review-pace{height:120px}`、`.review-pace__bar.is-empty{background:var(--line)}`。
- 实测：7 列各 83px 宽，bar 高 **4.8px**、背景 `rgb(214,218,225)`（=`--line` `#D6DAE1`），`.review-pace__count` 全是空文本。
- `/api/review` 实测：`week_pace` 7 天全部 `count:0`。
- 截图：`desktop-review.png` 左卡（7 个灰点 + 日期轴）、`mobile-review.png` 同区域。

**用户影响**：整块看起来像「加载中的骨架屏」，用户读不到「本周确实 0 投」这个结论，也就不会改变投递行为——复盘页最核心的钩子失效。

**根因**：无数据分支仍然走「画柱子」的渲染路径，用一个 4% 高度的占位条代替空态；同时空 `count` span 还在占位，让每列看起来像缺内容。

**改法建议**
- `paceBars`：`if (!days.some(d => toCount(d.count) > 0))` 时返回空态 HTML：一行「本周 0 次投递」+ 一句「挑一个岗位，今天投出去」+ 主按钮「去岗位库 →」；
- 有数据时：给 y 轴最大刻度标注（`max` 次）或峰值点上标注，`count=0` 的列不渲染空 span；
- `.review-pace__bar.is-empty` 改成 1px 底线（`height:1px`）而不是 4% 高的小方块，避免「骨架屏」观感。

**预估工时**：0.75 h

---

### R2 [P1] 节奏卡 438px 高、卡内 160px 空白；真正的行动区在右侧小卡

**证据**：实测第一个 `panel` = 728×**438**，`panel-body` 高 221、最后一个子元素（`.review-stages`）底边 354，面板底边 514 → **卡内空白 160px**。根因：`.dash-grid{align-items:stretch}`（`styles.css:7257`），行高由右列（需要处理 438px）决定。截图 `desktop-review.png` 左卡下半部整片空白。

**用户影响**：首屏最值钱的位置被一张「没数据的图」占满，而唯一要处理的「超过 7 天无进展 1」被挤在右栏窄卡里。

**改法建议**：卡内内容高度固定（120px 图 + 60px chips），不留伸展空白；无投递时把这张卡降级为一行窄条（或与「需要处理」调换主次，让行动卡占左栏）。

**预估工时**：0.5 h

---

### R3 [P1] 「阶段分布」5 个 chip 没有标题，且与卡片标题的时间口径冲突（本周 vs 全库）

**证据**：`review-view.js:225` 直接把 `stageChips(...)` 塞进 `.review-pace` 下方，无小标题、无分隔说明；卡片标题与副标题是「本周投递节奏 / 近 7 天按日投递次数——…」（`:220`）。而 chips 数据是 `/api/review.stage_distribution` 全库值（实测 `{draft:317, applied:1}`，其余补 0）。截图：`317 未投递 | 1 已投递 | 0 面试中 | 0 已拿Offer | 0 放弃` 紧贴日期轴下方，视觉上像图例。

**用户影响**：用户会把 317 理解成「本周某天的量」或「图的图例」，得出错误结论；复盘页的两个口径（本周 vs 全库）在同一张卡里混着，是误读的直接来源。

**改法建议**：chips 上方加小标题「岗位阶段分布（全库 318）」+ 一条分隔线；或把阶段分布整体移到「需要处理」卡顶部作为背景信息。同时把「317 未投递」和驾驶舱 KPI 的「已投递 1」口径对齐说明。

**预估工时**：0.5 h

---

### R4 [P2] 「对齐有效性」样本不足时只剩两个「—」，像渲染失败

**证据**：`review-view.js:70-102`（`rateCell`，`rate == null` → 输出 `—`）。实测两格各 319×87，正文只有一个大 `—` + 一行 11px 灰字「已对齐 · 0/0 过筛（样本 < 3，暂不展示比率）」。`/api/review` 实测 `aligned_total=0, unaligned_total=1, 两个 pass_rate 均 null`。

**用户影响**：分不清「样本不足」和「功能没做完」，87px 高的空格子让人以为坏图。

**改法建议**：样本不足时整块换成进度态：「已积累 1/3 条归因，再标 2 条就能算过筛率」+ 用 3 个格点表示进度；把 `—` 降级成次要文字。

**预估工时**：0.5 h

---

### R5 [P2] 复盘页复用 `.dashboard-view` 类名，第 3 张卡独占左列、右侧 420px 空洞

**证据**：`review-view.js:205` 根节点 `class="view view-scroll dashboard-view"`（借用驾驶舱的密度规则）；`.dash-grid` 两列 728+420（`styles.css:11440-11443`），3 张卡按顺序落位 → 第 2 行只有左列「对齐有效性」，右侧 420×221 空着。实测三个 panel 位置与此一致。

**用户影响**：页面下半部一个明显空洞；将来想加「投递漏斗趋势」等卡没有既定位置。

**改法建议**：复盘页用独立 grid（`.review-grid`）并显式定义 grid-area（节奏占左上、行动占右通栏、归因跨两列），或本次先让「对齐有效性」`grid-column: 1 / -1`。

**预估工时**：0.5 h

---

### R6 [P2] 复盘首屏没有「本周结论」，只有图和 0 徽标

**证据**：`review-view.js:204-255` 的结构是 pace → actions → attribution，没有任何 summary 段；页级副标题（`main.js:195`）是「每周投递节奏、停滞预警与归因对比」——描述的是功能而非结论。实测本次数据：本周投递 0、停滞 1、待标注 0。

**用户影响**：复盘的价值是「先给结论再给证据」，现在要用户自己读完 3 张卡才能拼出「这周我没投、有 1 条卡了 7 天」。

**改法建议**：页顶加一行摘要条（可用 `.metric-strip` 规范，见 X1）：「本周投递 0 次 · 停滞 1 条 · 逾期 0 条」+ 一句建议「先跟进 腾讯/后台开发」。

**预估工时**：0.75 h

---

### R7 [P1] 移动端复盘首屏是一张空图，行动卡在 y=656 之后

**证据**：390 实测 pace panel `y=234 h=390`；「需要处理」panel `y=656`（首屏 844px 只能看到它的标题）。截图 `mobile-review.png`。

**用户影响**：手机上打开复盘，看到的是 7 个灰点和「317 未投递」，必须滚过一整屏才能看到唯一要处理的事。

**改法建议**：移动端排序改为「摘要 → 需要处理 → 节奏图」，或节奏图为空时折叠成一行；`.dash-grid` 在 ≤640px 用 `order` 控制。

**预估工时**：0.75 h

---

## 3. 系统设置

### S1 [P1] 简单模式整页只有 1 张卡 + 下方 340px 空白；副标题承诺的「自动化规则 / 本地摄入 Token」在页内没有任何入口

**证据**
- 实测 simple 模式只有 `.simple-llm-panel`（`y=134 h=426`，底边 560），`.settings-view` 高 848 → **空白 340px**（截图 `desktop-settings.png`，卡片下方整片空白）。
- 唯一提到专家模式的一句话在 `format.js:3778`：`${isEdit ? "" : '<p>…备用节点、角色分工…与自动化规则在「专家模式」中配置。</p>'}` —— 当前**已有节点**（`isEdit === true`），这句不渲染，所以页内**完全没有**指向专家模式的说明。
- 文案三处不一致：顶栏副标题 `main.js:199`「LLM 节点、自动化规则与本地摄入 Token」；页内副标题 `main.js:731`「连接 AI 助手、配置节点与自动化规则」；专家模式再追加「（专家模式）」。
- 专家模式实测：`本地摄入 Token` 面板在 `y=789`（桌面首屏 900 只露出标题），`LLM 节点` 在 `y=1004`；移动端分别 1459 / 1727（见 S6）。

**用户影响**：用户被顶栏写着「自动化规则 / 本地摄入 Token」吸引进设置，看到的却是一个已经填好的表单加一大片空白，找不到那两块；「简单 / 专家」切换没有任何解释——「无从下手」在设置页最典型的一处。

**根因**：信息架构把 4 个能力面（AI 连接 / 节点分工 / 自动化规则 / 摄入 Token）压成「全部 / 只有一个」的二元模式，简单模式没有「其余能力的摘要指针」；指向专家模式的文案又被 `isEdit` 条件吞掉。

**改法建议**
1. 简单模式卡片下方补 2–3 行「更多设置」摘要（每行：能力名 + 当前状态 + 「查看 →」），点击即切专家模式并滚动锚点：
   - 自动化规则 · 0 条拦截规则 → 查看
   - 本地摄入 Token · 已生成 → 查看/复制
   - 节点分工 · 全部跟随主节点 → 查看
2. `format.js:3778` 去掉 `isEdit` 条件，已配置用户也要看到「更多设置在哪」。
3. mode switch 旁加 `title`/tooltip：「专家模式：节点分工、自动化规则、摄入 Token」。

**预估工时**：1 h

---

### S2 [P1] 移动端设置页头部被挤成竖排断字（「LLM 已配置」3 行、简单/专家竖排、恢复默认设置 2 行）

**证据**：390 实测 `.settings-head` 高 57px，内部三块：`.status-line` **48×50**（桌面 74×17）、`.settings-mode-switch` **67×57**（桌面 102×38，按钮文字被压成「简 / 单」竖排）、`.btn` **68×41**（桌面 96×28，文字两行）。截图 `mobile-settings.png` y234–291 区域。根因：`styles.css:8138-8159` `.settings-head{display:flex;justify-content:space-between}` 没有 `flex-wrap`，`.settings-head-actions{display:flex}` 同样不换行，`.status-line` 也没 `white-space:nowrap`。

**用户影响**：这一行在手机上完全不可读，最危险的「恢复默认设置」被挤在角落还折行，误触风险上升（见 S5）。

**改法建议**：≤640px：
```css
.settings-head { flex-direction: column; align-items: stretch; gap: var(--space-3); }
.settings-head-actions { flex-wrap: wrap; gap: var(--space-2); }
.status-line, .settings-mode-switch__btn { white-space: nowrap; }
```
危险操作「恢复默认设置」移动端收进「⋯」菜单或独占一行右对齐。

**预估工时**：0.5 h

---

### S3 [P1] 打开设置页会自动向 LLM 发一次真实探针请求（每次进页面重跑）

**证据**
- `main.js:742-770`：`if (activeNode && !activeLastTest && !(inflight))` → `api('/api/llm/nodes/{id}/test', { method: 'POST' })`，结果写进内存 `state.llmNodeTests`（刷新即丢）。
- `nodes.py:322-334`：该端点注释「Probe the node's provider with a minimal one-token chat request」，且结果**落库**（`last_test_status/last_test_at`）。
- 我的 Playwright 拦截计数：两次访问设置页（桌面 + 移动）共发出 **2 次** `POST /api/llm/nodes/85c60cdb…/test`，全部被 abort —— 证明请求确实由页面自动发出；本次审计因此**没有产生任何 LLM 费用**。

**用户影响**：只想改个开关也会触发一次外部请求（最长约 10s），节点欠费/断网时每次进设置都要白等一次失败；用户完全不知道发生了什么，也没有同意。

**根因**：把「测连通性」当成渲染时的自动补数据（为了填 bento 的「API 延迟」格），而不是用户动作；缓存又只在内存，所以每次进页面都重来。

**改法建议**：删掉渲染后的自动探测；把「API 延迟」格的 hint 改成按钮「测试连通性」（复用 `data-action="llm-node-test"`），或仅当 `last_test_at` 超过 24h 且用户点击才跑。若必须自动，至少改成 `GET` 只读缓存、不落库。

**预估工时**：0.5 h

---

### S4 [P1] 设置页「降级路径」实际会 TypeError 整页不渲染（与注释承诺相反）

**证据**
- `main.js:633-639`：`settings`、`status` 两个请求都是 `.catch(() => null)`。
- `main.js:649`：`settings.classification_vocabulary`（`settings` 可能是 `null`）→ TypeError。
- `main.js:734`：`${status.api_key_configured ? …}` —— 模板用的是**局部变量 `status`**（可能为 `null`），而 644 行兜底的是 `state.settingsStatus`，两处不一致 → TypeError。
- 对照注释 `main.js:640-642`：「If `/api/settings/status` fails, the main body still renders」——实现与该承诺相反。

**用户影响**：`/api/settings` 或 `/api/settings/status` 偶发失败时，设置页不是「局部不可用」，而是整页停在旧内容/空白，只在 console 留一条 TypeError；用户无从恢复。

**改法建议**：在请求处就兜底：
```js
const settings = (await api("/api/settings").catch(() => null)) || {};
const status = (await api("/api/settings/status").catch(() => null)) || { _degraded: true };
```
模板统一读 `state.settingsStatus`；`settingsBentoHtml` 的 `degraded` 分支（`format.js:3552`）已经写好，能直接复用。

**预估工时**：0.25 h

---

### S5 [P1] 「恢复默认设置」一键无确认，且重置范围说不清（不清 LLM 节点）

**证据**：`main.js:1989-1993` 直接 `POST /api/settings/reset` 然后 `render()`，无任何确认；按钮位置 `main.js:736` 与「简单/专家」模式切换同级、同为 `btn btn-outline btn-sm`。后端 `settings.py:332-343` 只 `update_settings(default_settings())` + 保留 local token，**不动 `llm_nodes`**。

**用户影响**：误点一下 API Key / 模型 / 词表配置回默认；而且用户会以为节点也一并重置，或反过来以为「恢复默认」等于全部清空，余留状态无法预测。

**改法建议**：`showModal` 二次确认，正文列清「会重置：AI 节点配置、分类词表；不会重置：LLM 节点列表、本地摄入 Token」；按钮降级为 `btn-ghost` 或移入「⋯」菜单；成功 toast 里写明影响项。

**预估工时**：0.5 h

---

### S6 [P2] 专家模式信息架构：4 个大面板共 2048px（移动端 3441px），小信息插在两个大面板之间

**证据**：实测 expert `view.scrollHeight=2048` vs `clientHeight=848`（2.4 屏）；面板 y 坐标：节点分工 271（h498）→ **本地摄入 Token 789（h195）** → LLM 节点 1004（h1057）→ 自动化规则 1004（h288）。移动端：611 / 1459 / 1727 / 3339，`view` 高 3441（4 屏）。顺序出自 `main.js:665-726`。

**用户影响**：专家模式的入口顺序是「节点分工（最难的一张）」在前；一块 195px 的小信息（本地 Token）把下游内容又推远 214px；移动端要滚 1.7 屏才看到 Token、2 屏才看到 LLM 节点。

**改法建议**：顺序改为 **LLM 节点 → 节点分工 → 自动化规则 →（本地摄入 Token 移到最后或收进「高级」折叠）**；本地 Token 面板压成单行（token + 复制 + 重置），高度从 195px 降到约 80px。

**预估工时**：1 h

---

### S7 [P2] 专家模式 bento：模型 ID 折行导致四格基线不齐；「API 延迟」提示指向屏幕外的按钮

**证据**：`format.js:3534-3573`；实测 `desktop-expert` 第一格值 `nvidia · nvidia/nemotron-3-super-120b-a12b` 折成 **2 行**，其余 3 格单行 → 四格值基线不齐；第 4 格 hint「尚未测试，可点节点卡「测试连通性」」，而节点卡在 **y=1004**（首屏 900 之外）。

**用户影响**：概览条看起来歪；提示让用户去点一个当前看不见的东西，找一圈后放弃。

**改法建议**：`.settings-bento__value` 加 `overflow:hidden; text-overflow:ellipsis; white-space:nowrap` + `title` 全量（或只显示 model、provider 进 label）；第 4 格 hint 换成按钮「测试连通性」，点击直达（正好可复用 S3 的改造）。

**预估工时**：0.5 h

---

### S8 [P2] 三处副标题口径互相打架，且混用内部术语

**证据**：`main.js:199`（顶栏）「LLM 节点、自动化规则与本地摄入 Token」/ `main.js:731`（页内）「连接 AI 助手、配置节点与自动化规则」/ 专家模式追加「（专家模式）」；`format.js:3551-3572`、`main.js:676` 面向用户出现「本地摄入 Token」「油猴脚本」「pipeline 角色」「统一主节点 / 本地分析+云端写作 / 全本地」。

**用户影响**：同一页面三个「这页是干嘛的」说法，加一堆内部术语，直接放大「无从下手」。

**改法建议**：统一成一句用户语言（例：「AI 选择 · 自动化规则 · 浏览器插件接入」），技术名词只留在 hint 里；专家模式标识改成 `badge` 而不是改副标题。

**预估工时**：0.5 h

---

## 4. 跨模块一致性

### X1 [P1] 三个页面的「指标条」是三套实现、三种字号、两套容器规则

**证据**
- 驾驶舱：`.metric-strip.dashboard-strip` —— 无背景无边框、`max-width:1120` 居中、值 `--text-3xl`(24px) mono、四格带左分隔线（`styles.css:7127-7160` + `styles.css:11346-11374`）。
- 设置（专家）：`.settings-bento.metric-strip` —— 有背景有边框的 4 张卡、值 `--text-lg`(16px)、label/hint 用 `color-mix` 40%（`styles.css:6615-6648`，另有 5432 / 5741 / 6798 / 10017 多处覆盖）。
- 复盘：**没有**指标条，改用 `.review-stage__item` chip（20px 数字 + 小标签，`styles.css:11016-11035`）。
- 同一类「阶段/数量」数据，驾驶舱是 4 个 `count-pair` 链接、复盘是 5 个 chip；驾驶舱 KPI 四格里只有 1 格可点（D9）。

**用户影响**：用户在三个页面之间移动时，密度、字号、对齐、可点性全部变化；318 / 317 这类同源数字出现两种视觉语言，像两个产品拼在一起。

**改法建议**：定一条「指标条」规范并落地为一个可复用块（统一高度、label `--text-2xs`、value 二选一、分隔线规则、与 grid 同宽），复盘用它替掉 stage chips；chip 只保留给「分布/标签」，不承担 KPI 职责。

**预估工时**：1.5 h

---

### X2 [P2] 卡片密度规则分叉：驾驶舱 20px / 设置 16px，复盘靠「借用驾驶舱类名」偶然一致

**证据**：`styles.css:11451-11464`（`.dashboard-view .panel-head{padding:8px 20px}`、`.panel-body{padding:20px}`）vs `styles.css:7182-7205`（base 16px）。且复盘页根节点直接挂 `dashboard-view` 类（`review-view.js:205`）才拿到 20px 密度——是**偶然复用**，改类名就会歪。

**用户影响**：设置页卡片与另两页内边距不同（视觉上更松/更紧），复盘页的一致性没有代码保证。

**改法建议**：把密度规则提升为显式页面级修饰符（如 `.view--dense`）供三页显式套用；复盘页去掉 `dashboard-view` 类名，避免语义漂移。

**预估工时**：0.75 h

---

## 5. 覆盖度对照

| 要求覆盖项 | 条目 |
|---|---|
| 首屏动线与信息层级 | D3、D10、D11、R2、R6、R7、S1、S6 |
| KPI 卡片一致性 | D2、D4、D9、X1 |
| 岗位动态表格（溢出/列对齐/空时间） | D1（P0）、D7、D8、D12 |
| 技能缺口榜 | D5、D6 |
| 稀疏数据（318 岗位 / 1 投递）下的表达 | D4、R1、R4、R6 |
| 复盘图表与空态 | R1、R2、R3、R4 |
| 设置页信息架构与留白 | S1、S2、S5、S6、S7、S8 |
| 移动端 | D10、D11、D12、R7、S2 |
| 三页面卡片高度 / 信息密度一致性 | X1、X2 |
| 额外发现（非视觉但影响体验） | S3（自动 LLM 探针）、S4（降级即崩）、S5（无确认重置） |

## 6. Top3 最该先修

1. **D1 岗位动态长标题溢出（P0）** —— 首屏最直观的「坏了」，用户第一眼就会归因为「这产品不行」；根因清楚、30 分钟能修、影响三个页面（D12 同源），修它性价比最高。
2. **R1 复盘节奏图无空态（P1）** —— 复盘页 438px 的主卡在真实数据下展示「零信息 + 骨架屏观感」，等于复盘的价值主张没有落地；一个空态分支就能把「0 投递」变成行动指令。
3. **S1 设置页简单模式没有「更多设置」入口（P1）** —— 顶栏承诺的三块内容在页内一处都找不到，是「无从下手」最标准的样本；补 3 行摘要 + 一个锚点即可解决，不用重排整页。

**排序理由一句话**：先修「看起来坏了」的（信任），再修「看了没用」的（价值），最后修「找不到」的（可发现性）。

## 7. 如果只能做一件事

**把驾驶舱首屏重做一次**：D1（表格不溢出）+ D3（不留 135px 死区，动态扩到 5–6 条）+ D8（给「查看全部岗位」出口）+ D4（KPI 口径不打架）。理由：驾驶舱是唯一每天必开的页面，它同时承担「信任」（不能有压字）和「下一步」（看完知道干什么）两个问题；改动集中在 `dashboard-view.js` + `styles.css` 两处，0.5–1 天可完成并验证，且 D1 的修法能顺带修掉移动端 D12。

## 8. 我不确定 / 需要 Lead 决策

1. **后端契约能不能动（D6）**：「技能缺口」要真正区分「缺 / 已覆盖」需要 `/api/dashboard` 增 `covered` 字段，这会牵动接口与测试；我只做只读审计，没有评估后端成本。若本轮只允许前端，D6 按短期方案（改文案 + CTA）处理。
2. **KPI 口径（D4）**：「已完成对齐 22/318」是否改成 7 天窗口会改变用户看到的数字，这是产品口径决策而非纯 UI，需要拍板。
3. **设置页自动探针（S3）**：`last_test_at` 落库后被哪些地方消费（工作台 pre-flight / 设置徽标）我没查全；删除自动探测前需确认「新鲜度」语义没有别处依赖。
4. **简单模式要不要保留「恢复默认设置」（S5）**：我倾向移出简单模式或收进菜单，但这关系到老用户操作路径，需确认。
5. **移动端是否本轮就做**：D10 + D11 + D12 + R7 + S2 合计约 3.5 h，若本轮只保桌面，建议至少先做 D12（表格不可读）与 S2（头部断字）。
6. **「快速继续」的定位**：它现在与「最近岗位动态」同卡（`dashboard-view.js:291-321`），语义上「继续做一件事」和「看最近变化」是两回事；是否拆成两张卡，属于结构决策，我没擅自建议具体方案。

---

*审计方式：只读（GET + Playwright 只读渲染 + 设置页拦截 LLM 探针后渲染）。未修改 `src/`、未提交表单、未触发 LLM、未改用户数据。本次唯一写入 = 本文件。*
