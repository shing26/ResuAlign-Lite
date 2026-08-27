# ResuAlign 前端设计改造方案

**基于**: 2026-08-18 设计评审报告（5 设计代理联合评审）
**状态**: 待实施

---

## 设计原则

1. **待办优先** — 首页回答"现在该做什么"，而非"过去发生了什么"
2. **进度可见** — 用户永远知道"当前处于哪个阶段、还要多久"
3. **零空状态** — 每一步都有引导，没有空白页
4. **闭环反馈** — 用户完成一个动作后，系统自动提示下一步
5. **品牌一致** — 统一的视觉语言，不靠 utility class 拼凑

---

## Phase A: 基础架构（P0，必须完成）

### A1: 建立 CSS 设计 Token 系统

**文件**: `src/resualign/static/styles.css`

**改动**:
- 在 `:root` 中定义品牌色、间距、圆角、字号 Token
- 将当前硬编码的 `bg-appbg`、`text-white/90` 等 utility class 迁移到 Token 变量
- 确保 `dark` / `light` 两套模式都有完整 Token 覆盖

**Token 清单**:
```css
:root {
  --color-brand: #4f8cff;
  --color-brand-hover: #3a7ae8;
  --color-brand-subtle: rgba(79, 140, 255, 0.12);
  --color-bg-app: #0f1117;
  --color-bg-card: #1a1d27;
  --color-bg-elevated: #22263a;
  --color-border: rgba(255, 255, 255, 0.08);
  --color-text-primary: rgba(255, 255, 255, 0.9);
  --color-text-secondary: rgba(255, 255, 255, 0.55);
  --color-text-tertiary: rgba(255, 255, 255, 0.35);
  --color-accent-green: #22c55e;
  --color-accent-amber: #f59e0b;
  --color-accent-red: #ef4446;
  --font-size-xs: 11px;
  --font-size-sm: 13px;
  --font-size-base: 14px;
  --font-size-lg: 16px;
  --font-size-xl: 20px;
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 8px;
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 12px;
  --space-lg: 16px;
  --space-xl: 24px;
}
```

**验收标准**:
- 所有现有视图使用 Token 变量而非硬编码值
- `theme-toggle` 切换时所有颜色平滑过渡（`transition: background-color 0.2s, color 0.2s`）
- 无回归：现有前端测试全绿

---

### A2: 仪表盘重构为待办优先视图

**文件**: `src/resualign/static/app/dashboard-view.js`

**改动**:
- 当前 KPI 数字卡片（resumes/jobs/applied/interview/offer/declined）改为辅助信息行，放在视图底部
- 首屏展示排好优先级的待办列表，从 `/api/reminders?scope=today` 获取数据
- 待办排序规则：已过期 > 今日到期 > 按 next_step_due_at 升序
- 每个待办项展示：岗位名 + 公司 + 状态 + 紧迫性标记 + 操作按钮（"去处理"）
- 空状态：当无待办时，展示"没有待办事项" + "去岗位库看看新岗位"的引导链接

**待办卡片的 HTML 结构**:

```html
<div class="todo-card" data-urgency="${overdue ? "critical" : due_today ? "high" : "normal"}">
  <div class="todo-card__urgency">
    ${overdue ? "已过期" : due_today ? "今天" : `${daysLeft} 天后`}
  </div>
  <div class="todo-card__body">
    <strong>${job_title}</strong>
    <span class="todo-card__meta">${company} · ${status}</span>
    <p class="todo-card__step">${next_step}</p>
  </div>
  <a class="btn btn-primary btn-sm" href="#/workspace/${job_id}">去处理</a>
</div>
```

**验收标准**:
- 首页加载后，用户第一眼看到的是"今天要做什么"而非数字
- 过期项视觉上突出（红色紧迫标记）
- 空状态展示引导链接
- 无回归：dashboard API 仍正常响应

---

### A3: 工作台阶段进度条

**文件**: `src/resualign/static/app/split-canvas.js` 或 `main.js`

**改动**:
- 在工作台顶部添加阶段进度条，展示 5 个阶段：诊断 → 分析 → 差距 → 改写 → 评估
- 每个阶段有三种状态：`pending`（灰色）、`active`（品牌色脉冲动画）、`done`（绿色勾）
- 从 SSE 事件的 `stage` 字段实时更新进度
- 当 LLM 正在运行时，当前阶段显示打字机动画（`...` 闪烁）

**CSS 结构**:

```css
.stage-progress {
  display: flex;
  gap: 0;
  padding: var(--space-md) 0;
}
.stage-step {
  flex: 1;
  text-align: center;
  position: relative;
}
.stage-step::after {
  content: "";
  position: absolute;
  top: 50%;
  right: -50%;
  width: 100%;
  height: 2px;
  background: var(--color-border);
}
.stage-step--done::after {
  background: var(--color-accent-green);
}
.stage-step--active .stage-step__dot {
  animation: pulse 1.5s infinite;
}
```

**验收标准**:
- 打开工作台时显示 5 个阶段点
- 对齐过程中，当前阶段点有脉冲动画
- 阶段完成后，点变为绿色勾
- 所有阶段完成后，进度条变为全绿

---

### A4: 空状态引导

**文件**: 涉及 `dashboard-view.js`、`format.js`（todayViewHtml）、`kanban.js`（jobs-view）

**改动**:
- 每个视图的空状态不再返回空列表，而是返回引导卡片
- 引导卡片包含：SVG 插画（先用纯 CSS 占位，后续替换为动物插画）、引导文案、操作按钮

**引导文案清单**:

| 视图 | 空状态文案 | 操作按钮 |
|------|-----------|---------|
| 岗位库 | "还没有岗位。粘贴一份 JD 或导入收藏链接开始。" | [粘贴 JD] |
| 简历中心 | "还没有简历。上传 PDF 或直接输入 Markdown。" | [上传简历] |
| 今日待办 | "今天没有待办。去岗位库看看新机会？" | [浏览岗位] |
| 工作台 | "选择一个岗位开始对齐。" | [去岗位库] |
| 仪表盘 | "欢迎使用 ResuAlign！先导入简历和岗位。" | [上传简历] [导入 JD] |

**验收标准**:
- 每个视图在对应数据为空时展示引导卡片而非空列表
- 引导卡片包含文案 + 可点击的操作按钮
- 按钮点击后跳转到对应功能页面

---

### A5: 投递后自动跟进提醒

**文件**: `src/resualign/api/routers/jobs.py`（记录投递端点）、`src/resualign/reminders.py`

**改动**:
- 当用户标记一个岗位为"已投递"时，自动创建一个 3 天后的跟进提醒
- 提醒内容：`"投递 ${company} 已 3 天，可以准备跟进消息"`
- 提醒到期时显示在今日待办中
- 用户可以在设置页关闭自动跟进（`auto_followup_reminder` 开关）

**后端改动**:

```python
# 在记录投递的端点中添加
if settings.get("auto_followup_reminder", True):
    due_at = datetime.utcnow() + timedelta(days=3)
    reminders.create_reminder(
        tenant_id=user["user_id"],
        job_id=job_id,
        due_at=due_at.isoformat(),
        message=f"投递 {company} 已 3 天，可以准备跟进消息",
    )
```

**验收标准**:
- 标记"已投递"后，自动创建 3 天后的提醒
- 提醒出现在今日待办和 /api/reminders 中
- 设置页有 `auto_followup_reminder` 开关
- 关闭开关后不再自动创建提醒

---

## Phase B: 体验增强（P1，建议完成）

### B1: 对齐过程打字机进度

**文件**: `src/resualign/static/app/split-canvas.js`

**改动**:
- 将阶段进度条中的每个阶段标签替换为动态文字
- 当前阶段显示"JD 分析中…"、"差距分析中…"等
- 每个阶段完成后，标签变为"JD 分析 ✅"
- 添加打字机光标闪烁效果

### B2: 采纳 diff 的盖章动画

**文件**: `src/resualign/static/styles.css` + `main.js` 中的 diff 采纳事件

**改动**:
- 在 `styles.css` 中添加 `@keyframes stamp` 动画
- 当用户点击"采纳"按钮时，diff 卡片添加 `is-accepting` class，触发盖章动画
- 动画结束后，卡片从 DOM 中移除

```css
@keyframes stamp {
  0% { transform: scale(0.8) rotate(-5deg); opacity: 0; }
  50% { transform: scale(1.05) rotate(0deg); opacity: 1; }
  100% { transform: scale(1) rotate(0deg); opacity: 0.3; }
}
.is-accepting {
  animation: stamp 0.35s ease-out forwards;
}
```

### B3: 今日待办优先级视觉区分

**文件**: `src/resualign/static/app/format.js`（todayViewHtml）

**改动**:
- 在 `today-row` 中添加 `data-urgency` 属性
- 已过期项：红色左侧边框 + "已过期"标签
- 今日到期项：黄色左侧边框 + "今日"标签
- 未来到期项：无特殊边框，只显示天数
- 按 urgency 排序：critical > high > normal

### B4: 前端漏斗埋点

**文件**: 新增 `src/resualign/static/app/analytics.js`

**改动**:
- 在 `localStorage` 中维护一个 `resualign_funnel` 对象
- 在关键动作点触发埋点：`jd_imported`、`aligned`、`diff_accepted`、`applied`、`followed_up`
- 埋点数据包含：时间戳、岗位 ID、耗时
- 埋点只写本地，不发送到任何外部服务

---

## Phase C: 趣味与品牌（P2，可延后）

### C1: 空状态动物插画

- 在空状态引导卡片中添加 SVG 动物插画
- 使用行内 SVG（无外部依赖）
- 每个动物有 2-3 帧呼吸动画（CSS animation）

### C2: Offer 庆祝仪式

- 当用户标记"已拿 Offer"时，触发 2 秒庆祝动画
- 顶部出现彩带渐隐效果（纯 CSS `@keyframes confetti`）
- 展示数据回顾："你改了 {n} 次简历，投递了 {m} 家，面试了 {k} 次"
- 提供"导出求职报告"按钮

### C3: 彩蛋

- Konami code（↑↑↓↓←→←→BA）：在 Ctrl+K 面板中输入时触发打字机加速模式
- 深夜模式：凌晨 2-5 点问候语改为"这么晚还在找工作？辛苦了 🌙"
- 版本里程碑：简历版本 v10 时显示"十项全能！"

---

## 实施顺序

```
Phase A (P0) ──────────────────────────────► 必须完成，下一轮开工
├── A1: 设计 Token 系统 ── 基础，先做
├── A2: 仪表盘重构 ── 核心体验，第二大
├── A3: 工作台进度条 ── 小改动，快速见效
├── A4: 空状态引导 ── 小改动，快速见效
└── A5: 自动跟进提醒 ── 后端改动，需配合

Phase B (P1) ──────────────────────────────► 建议完成
├── B1: 打字机进度
├── B2: 盖章动画
├── B3: 优先级视觉
└── B4: 漏斗埋点

Phase C (P2) ──────────────────────────────► 可延后
├── C1: 动物插画
├── C2: 庆祝仪式
└── C3: 彩蛋
```

## 验收总标准

1. 首页第一眼看到的是"今天要做什么"而非 KPI 数字
2. 工作台对齐过程有可见的 5 阶段进度条
3. 所有视图在数据为空时展示引导卡片
4. 投递后自动创建 3 天跟进提醒
5. 所有颜色使用 CSS 变量，而非硬编码值
6. 现有前端测试全部通过
