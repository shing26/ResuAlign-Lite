# ADR-0031: 文档润色（Document Polishing）交互范式转型

**状态**: 已接受
**日期**: 2026-08-19

---

## 背景

ResuAlign 的核心交互隐喻当前是"代码审查 diff"：左右分栏对比 Original / Proposed，绿色高亮新增行，红色标注删除行。这一设计哲学源自开发者语境，对普通求职者造成显著的认知摩擦：

- 用户需要理解"diff"概念才能使用产品
- 术语（Granularity、Prompt Focus、Provenance）增加心理负担
- 三栏布局类似 IDE 侧边栏，缺少叙事引导
- 操作完成后缺少"变强了"的仪式感

## 决策

将交互范式从"代码审查 diff"全面迁移至"文档润色（Document Polishing）"，以 Google Docs 建议模式为产品心智模型。

### 核心映射

| 当前（代码审查） | 目标（文档润色） |
|---|---|
| diffCard 左右对比 | 浅蓝色高亮标记 + 侧边批注气泡 |
| Original / Proposed 标签 | 悬浮 tooltip 显示"原文内容" |
| Provenance: 80% | 可信度徽章 `🛡️ 高可信` / `⚠️ 建议复核` |
| accept / reject 按钮 | ✓ 采纳 / ✗ 跳过 |
| Granularity: medium | 下拉选择"精修 / 微调 / 仅补充关键词" |
| Prompt Focus: balanced | 开关"侧重技术深度 / 侧重业务价值" |
| 工作台三栏布局 | 单栏文档视图 + 右侧浮动建议抽屉 |

### 为什么不选"纯文档编辑器"范式

"文档润色"优于"文档编辑器"的两点关键差异：

1. **心智负担更低**：Google Docs 建议模式用户已熟悉，蓝色标记 = 有修改建议，点击接受或拒绝。
2. **保留用户掌控感**：求职者最怕"AI 把我的简历改得面目全非"。建议模式天然赋予裁决权，与 ProvenanceGate 防幻觉哲学完全一致。

---

## 四步实施路线图

### Step 1 — 纯视觉/文案替换（安全，只需快照更新）

**范围**：`format.js`（diffCard 渲染函数）、`styles.css`（颜色语义）

| 改动项 | 当前 | 目标 |
|---|---|---|
| diffCard 标签 | `Original / Proposed` | `原文 / 建议修改` |
| 操作按钮 | `accept / reject` | `✓ 采纳 / ✗ 跳过` |
| 可信度显示 | 百分比数字 | `🛡️ 高可信` / `⚠️ 建议复核` / `❓ 待确认` |
| 删除线颜色 | 红色 | 浅灰色 |
| 新增内容底色 | 绿色 | 品牌色淡蓝底 + 深蓝字 |

**验收标准**：443 前端测试全部通过，无 DOM 结构变更。

---

### Step 2 — 布局调整：三栏 → 单栏 + 浮动建议抽屉

**范围**：`split-canvas.js`（工作台布局）、`styles.css`（grid 定义）

- 左侧 Inspector 面板折叠为右侧浮动建议抽屉（`position: fixed`，可拖拽/可折叠）
- 工作台主区域 `grid-template-columns: 22% 48% 30%` → `1fr`
- 原左侧控制面板的功能迁移至顶部工具栏或浮动抽屉内

**验收标准**：`split-canvas.test.mjs`、`workbench-guide.test.mjs` DOM 选择器更新后通过。

---

### Step 3 — Diff 呈现方式重构：左右对比 → 内联建议

**范围**：`format.js`（`diffCard`、`buildCmpSideHtml`、`renderInlineDiffSide`）、`diff-editor.js`

- 不再渲染左右两列 `cmp-column`，改为单列文本流
- 每条 diff 在原文中标记：蓝色底 = 建议新增，删除线 = 建议删除，灰色底 = 建议替换
- 点击标记弹出批注气泡（显示建议内容 + 修改理由 + 采纳/拒绝操作）

**验收标准**：`diff-editor.test.mjs`、`snapshots.test.mjs` 更新后通过。

---

### Step 4 — 空状态与引导打磨

**范围**：`dashboard-view.js`、`format.js`（引导组件）、`styles.css`（空状态样式）

- 空状态插画（SVG 动物插画 + CSS 呼吸动画）
- 渐进式引导卡片：第一步上传简历 → 第二步导入岗位 → 第三步开始优化
- 完成仪式：Offer 庆祝动画增强

**验收标准**：现有 453 前端测试全部通过，新增空状态引导测试覆盖。

---

## 依赖关系

```
Step 1 (文案/颜色) ── 独立，无依赖
    │
    ▼
Step 2 (布局调整) ── 依赖 Step 1 完成
    │
    ▼
Step 3 (内联建议) ── 依赖 Step 2 布局到位
    │
    ▼
Step 4 (空状态/引导) ── 独立，可并行于 Step 2-3
```

## 明确不做（范围外）

- 推翻 SQLite / FastAPI / Role-Router 底座
- 引入前端框架迁移（Lit / Preact / Vue）
- 多模态简历 / 视频简历
- 面试模拟 / 薪资谈判助手

## 后果

### 正面

- 降低求职者的认知门槛，扩大目标用户群
- 与 ProvenanceGate 防幻觉哲学形成互补
- 分步实施保证每步可测试、可交付

### 负面

- Step 2 和 Step 3 需更新大量 DOM 选择器测试
- 文档润色范式对"批量操作"场景的覆盖不如 diff 直观
- 内联建议在移动端小屏上的交互密度需额外适配
