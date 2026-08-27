# ADR-0023: Figma Workstation Design Tokens in the Frontend

Date: 2026-08-04

Status: Accepted

## Context

用户提供了一套 Figma 工作站设计规范：暗色玻璃拟态、Design Tokens
（`#0B0F19` 画布、`rgba(22,30,49,0.65)` 玻璃面、emerald/amber/purple 强调色、
12px 圆角）以及 Auto-Layout 结构（56px Header、左 35% JD/Gap、右 65% Diff Studio）。

当前环境没有可用的 Figma Plugin API 工具，因此把规范直接落地为前端 CSS
Tokens 与布局，而不是修改 Figma 文件。

## Decisions

1. 在 `styles.css` 的 Phase 20 变量区新增：
   `--surface-glass`、`--surface-glass-deep`、`--border-glass`、
   `--workbench-bg`、`--workbench-bg-deep`、`--emerald`、`--amber-token`、
   `--purple-token`，明暗主题各一套。
2. `.split-canvas` 变成工作站画布：18px 内边距、18px 圆角、
   深色下 `#0B0F19` → `#0D1420` 渐变，浅色下对应浅色玻璃渐变。
3. `.split-layout` 桌面列宽改为 `35% / 65%`；`.split-pane` 使用
   `surface-glass` + 16px backdrop blur + 12px 圆角 + 玻璃描边。
4. JD 摘要与 diff 卡片的左侧强调线统一为 emerald；对齐表单和原始 JD
   预览使用玻璃深色面。
5. 顶栏最小高度 56px，移动端保持单列并缩小内边距。

## Consequences

- 工作台在暗色主题下呈现完整的玻璃拟态工作站；浅色主题也有等价的浅色玻璃。
- 布局仍保留响应式单列与内部滚动，桌面/移动均无横向溢出。
- 后续若接入 Figma，可直接把同一套 Token JSON 导入 Tokens Studio / Variables。
