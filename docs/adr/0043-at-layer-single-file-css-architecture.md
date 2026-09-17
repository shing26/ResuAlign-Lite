# 0043 — 用原生 `@layer` 单文件分层取代四代 CSS 补丁叠层

Status: accepted (2026-09-18 用户逐项裁定；施工待 ADR-0042 冻结令解冻)

## 背景（证据链，非估计）

1. **体量**。`src/resualign/static/styles.css` 实测 12269 行 / 265155 字节 /
   2043 个规则块，`@layer` 声明 **0 处**，`@media` 61 处，`:root` 块 **10 个**，
   `!important` **100 处**。
2. **四代视觉补丁叠加**。按文件顺序存在基础层 / Phase 17 / Phase 18 /
   Phase 20 / Apple Native Visual Patch / v3 detail / v3.1 / AI 优化共 8 段，
   后写的层覆盖先写的层。
3. **源码自证**。`styles.css:11006` 原文注释：
   `/* ---- 3. 壳层压平：压过 v2.0 硬编码深色的 !important ---- */`。
   即某一层存在的唯一目的是盖住上一层硬编码深色。
4. **缺少层序的必然后果**。在没有 `@layer` 的 CSS 里，「让新规则生效」的唯一
   手段是写得更靠后或加 `!important`。100 处 `!important` 中约 45 处是
   Apple 层（`styles.css:6525-6571`）与 v3.1 层（`styles.css:11006-11073`）
   逐条对消的产物：`.topbar`/`header`、`.card`、`.kanban-col`、
   `select option`、`ins`/`del` 全部成对出现。
5. **实测现状锚点**（Playwright，视口 1706×780）：
   `.app-rail` 计算宽度 **230px**（源码同时存在 230 与 240 两套声明）、
   `.topbar` 高度 **64px**、`#job-board` 可视宽 1424 / 内容宽 1648
   → **横向溢出 224px**，第 5 列被裁。
6. **约束**。用户裁定零构建：禁 Vite / PostCSS / Sass / Tailwind / CSS Modules，
   禁需打包的依赖。因此多文件打包与 `@import` 分文件两种方案均不在可选集内。

## 决定

**1. 保持单文件 `src/resualign/static/styles.css`，文件顶部用一行声明 8 层层序。**

```css
@layer reset, tokens, base, layout, components, patterns, utilities, overrides;
```

| # | 层 | 唯一职责 | 允许依赖 |
|---|---|---|---|
| 1 | `reset` | 归零与浏览器默认消歧 | 无 |
| 2 | `tokens` | 只放自定义属性（`:root` / `:root[data-theme]`），零选择器样式 | 只允许 token 引用 token |
| 3 | `base` | 元素默认外观与真实控件外观 | tokens |
| 4 | `layout` | 页面骨架，只做定位与栅格，不做颜色 | tokens, base |
| 5 | `components` | 单个自包含组件，不跨组件命中 | tokens, base |
| 6 | `patterns` | 跨组件组合模式（空态、加载态、模态、Toast） | reset…components |
| 7 | `utilities` | 白名单制原子类（`.truncate` / `.sr-only` / `.is-hidden`） | 全部 |
| 8 | `overrides` | **只允许**主题重映射与 `@media print` | 全部 |

依赖方向铁律：`overrides ⊃ utilities ⊃ patterns ⊃ components ⊃ layout ⊃ base ⊃ tokens ⊃ reset`。
低层永远打不过高层，因此低层不需要 `!important` 自查。

**2. 不拆多个 `<link>`。** 零构建下无打包，多 `<link>` 会把层序从 CSS 内部
（可断言）搬到 HTML 标签顺序（不可断言），比现状更隐蔽。附带事实：7 个前端
测试文件全部 `readFileSync(styles.css)`，拆文件需同步重写。

**3. `overrides` 层内容受限。** 出现非主题、非 `@media print` 的功能选择器即
验收失败。这是「第五代补丁」的物理闸门：任何新视觉必须声明自己属于哪一层，
想覆盖 `components` 只能进 `overrides`，而 `overrides` 有内容校验。

**4. 响应式覆盖写进「被覆盖规则所属的同一层」内，位置放在基础规则之后。**
媒体查询是条件，不是职责，因此**不新增 `responsive` 层**；`overrides` 的职责
也**不放宽**。同层内后写覆盖先写，天然生效。

依据：现状 11 处响应式覆盖（`styles.css:7770-7802` 的
`@media (max-width: 900px)` 块，覆盖 `.dash-grid` / `.resume-grid` /
`.settings-grid-2` / `.split-layout` / `.split-pane` / `.wb-mobile-tabs`）
之所以全部带 `!important`，是因为它们写在文件中段，而要压过的组件规则在
后段（v3.1 层）。**这是「顺序不够、`!important` 来补」的实例，不是响应式
本身需要 `!important`。** 分层后这些 `!important` 自然消失。

**5. `!important` 全文件收敛到 ≤ 1，唯一豁免 `[hidden]{display:none!important}`。**

这不是洁癖，是 `@layer` 能否安全上线的先决条件：**在分层 CSS 中，低层的
`!important` 会赢过高层的 `!important`**（规范明文）。若带着 100 处
`!important` 分层，读代码时看到的层序与实际胜负**完全相反**，会制造出比现状
更难 debug 的级联。

实现路径按现存 100 处逐类处置（这是本 ADR 与初稿的实质差异——初稿只给了
目标值，未给路径，导致目标事实上不可达）：

| 类 | 条数 | 处置 |
|---|---|---|
| 对消补丁（Apple 层 × v3.1 层） | ~45 | 两侧一并删除，改由 tokens 层供值 |
| `prefers-reduced-motion` | 13 | 移入 `tokens` 层：`@media (prefers-reduced-motion: reduce){ :root{ --dur-*: 1ms } }` —— 前提是全部动效时长走 `var(--dur-*)`。**不保留任何 `*{animation-duration:0.01ms!important}`** |
| `@media print` | 17 | 移入 `overrides` 层；作为最高层不需要 `!important` |
| `[hidden]` / `.hidden` 守卫 | 6 | 合并为 `reset` 层 1 条 `[hidden]{display:none!important}` |
| 响应式布局覆盖 | ~11 | 按决定 4 写回同层媒体查询 |
| 其余 | 剩余 | 归零 |

**6. token 源内联在 `styles.css` 的 `@layer tokens` 顶部。**
设计侧交付的 `design-tokens.css` 内容作为该层的唯一内容内联进主文件，
**不新增第二份 `<link>`，也不使用 `@import`**。理由：独立文件若不进 `@layer`
即为未分层声明，而未分层声明压过所有分层声明，会使
`@layer overrides` 的主题重映射失效，第 3 条的「`overrides` 只准放主题」
在语义上不成立。内联是唯一同时满足决定 1/2/3 的形态。

**7. 层内纪律（`@layer` 治不到的部分，必须另立约束）。**
组件层内只写单类选择器（`.board-card`，不写 `.board .board-col-body .board-card`），
禁止跨组件后代选择器。这条不守，`@layer` 只治了「层间」，「层内」照旧。

## 已知边界（本 ADR 不能解决的）

- **层内特异性与源码顺序仍然有效**，靠决定 7 的纪律治理。
- **不能删死代码**：499 个「CSS 有定义但 JS 模板未出现」的类不会因分层消失。
- **不能对抗内联样式**：模板里的 `style="..."` 不属于任何层，永远赢过所有层。
  见 ADR-0046。
- **不能统一 token 语义**：`--bg` 与 `--bg-canvas` 指向同一色时，`@layer`
  无法告诉你该用哪个。见 ADR-0044。

## 后果

**正面**

- 跨职责的意外覆盖被层序根治，100 处 `!important` 有明确归零路径。
- 层序成为可被 CI 断言的不变式（8 层、顺序正确、声明唯一）。
- 文件名与路径不变 → 7 个读 `styles.css` 的测试不需要因「拆文件」而重写。

**负面 / 代价**

- 单文件改一次 = 全量缓存失效，靠现有 `?v=` 机制缓解（需从 33 bump 到 34）。
- `@layer` 需 Chrome 99+ / Safari 15.4+ / Firefox 97+；本项目为本地现代浏览器，接受。
- 第 5 条的实现路径要求「全部动效时长走 token」先成立，因此 `!important` 归零
  与 token 收敛**必须同批交付**，存在耦合风险。
- `css-structure.test.mjs` 的「关键选择器必须出现在文件后 34% 区段」这一不变式
  在分层后语义失效（层序已决定胜负，与文件位置无关），必须替换为
  「定义在 `@layer layout/components` 内」。

## 与既有 ADR 的关系

- **ADR-0033 / ADR-0026 / ADR-0017**：前三者用「后写覆盖」实现视觉换代，
  本 ADR 不改其视觉结论，只改承载机制。
- **ADR-0042（冻结令）**：本 ADR 的施工受其约束，须解冻后执行；本轮不动代码。
- **ADR-0044 / 0045 / 0046**：分别承接本 ADR 的 token 语义、图标、内联样式三条边界。
- **ADR-0047**：给出主题与主色的最终值。
