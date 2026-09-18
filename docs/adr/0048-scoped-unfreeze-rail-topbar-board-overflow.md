# ADR-0048: 冻结令 6e 逐项例外 —— 侧栏 / 顶栏 / 看板溢出

- **状态**: 已采纳
- **日期**: 2026-09-18
- **依据**: ADR-0042 决定 6e（冻结令例外流程）；ADR-0044 决定 10（token 命名与
  `--rail-w` / `--topbar-h` 取值）；施工单 `docs/plans/css-architecture-refactor-plan-2026-09-18.md`
- **关系**: 不推翻任何 ADR；本 ADR 只登记本轮冻结期内的三项例外及其边界

## 背景

ADR-0042 决定 6e 规定：自用线推进期间 app 冻结令继续有效，任何改动须逐项走
冻结令例外流程并留记录。本 ADR 即该流程的落地记录。

申请例外的动机是三条**自用闭环的直接摩擦**，不是架构动机：

1. 岗位库看板在 1706×780 视口下横向溢出 224px，第 5 列被裁，每轮投放操作都要
   横向滚动才能看到完整列；
2. `styles.css` 里 `.app-rail` / `.topbar` 有多份互相覆盖的 240px / 230px / 64px
   定义，实测生效值与设计定稿（224px / 52px）不一致，且「改一处不生效」本身
   持续消耗调试时间；
3. `alignment-gap.test.mjs` 锁的是被覆盖的死定义（240px / 64px），永远绿灯，
   无法作为护栏。

改造前实测基线（Playwright，1706×780，DPR 1，8 路由 0 console error）：

| 指标 | 实测 |
|---|---|
| `.app-rail.rail` 宽 | 230px |
| `.topbar` 高 | 64px |
| `#job-board` 可视宽 / 内容宽 | 1424px / 1648px（溢出 224px） |
| `.board-column` flex 简写 | `0 0 320px`（`styles.css:8922`） |

## 决定

**决定 1（范围）**：本轮只做以下三项，任何第四项改动都须另开例外：

1. `.app-rail.rail` 与 `.app-shell` 桌面端宽度：230px → **224px**，并统一引用
   `--rail-w`；
2. `.topbar` 高度：64px → **52px**，并统一引用 `--topbar-h`；
3. `.board-column` 弹性：`flex: 0 0 320px` → **可收缩弹性列**，使 5 列在
   1424px 可视宽内不被裁切。

**决定 2（token 落点）**：`--rail-w: 224px` 与 `--topbar-h: 52px` 本批落在
`styles.css` 顶部既有基础 `:root` 块内，作为 B1 `@layer tokens` 的前置形态；
不新增第二个 `<link>`、不新增 `design-tokens.css` 文件。取值与 ADR-0044 决定 10
完全一致。

**决定 3（清理死定义）**：本批同时把 `.app-rail` / `.topbar` 的旧魔法数字改写为
token 引用，并清掉被后文覆盖的无效 token 定义，避免留下「声明了但不生效」的
第二处验证死定义。

**决定 4（测试同步）**：`alignment-gap.test.mjs` 的两条魔法数字断言改为「必须引用
`--rail-w` / `--topbar-h`」；`adr0033.test.mjs` 的静态版本号 v=33 → v=34。测试
先改，再改 CSS。

**决定 5（不做）**：本轮不引入 `@layer`、不做 token 全量收敛、不删 100 处
`!important`、不做字体自托管、不引入构建工具。B0–B7 施工单的其余内容保持
「解冻后执行」。

## 验收

- DOM 度量：`.app-rail.rail` = 224px、`.topbar` = 52px、`#job-board` 溢出 = 0、
  5 列等宽且第 5 列右边界不超出视口。
- 8 条路由 0 console error；`node --test` 前端全绿；后端回归基线不变
  （997 passed / 7 skipped）。
- 探针与前后快照归档 `.scratch/css-metrics-*.json`，不入库。

## 后果

- 自用闭环的看板操作不再需要横向滚动才能看全 5 列；字号、间距、配色、图标、
  层序均未触碰，视觉改动限于侧栏 −6px、顶栏 −12px、看板列由 320px 缩至
  275px 左右。
- 本轮为 B1 预置了 `--rail-w` / `--topbar-h` 两个 canonical token，B1 施工时
  只需改 token 值所在层，不必再追魔法数字。
- 未解冻其余前端架构改造；B0–B7 仍然整单待施工。
