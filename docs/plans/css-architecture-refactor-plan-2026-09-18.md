# ResuAlign 前端 CSS 架构重构 · 批次施工单

**状态**: B0/B1/B2a/B2b/B2c/B2d/B2e/B3a/B3b 已完成；B4–B7 按 ADR-0050 逐批推进
**日期**: 2026-09-18
**依据**: ADR-0043（分层）/ ADR-0044（token）/ ADR-0045（图标）/
ADR-0046（内联变量）/ ADR-0047（主题与主色）
**母方案**: `D:\WorkBuddyData\ResuAlign-UI重构\` 下的 00–06 与
`design-tokens.css`（设计档案，权威以本单与上述 ADR 为准）

> **前提**：本单是解冻后的施工计划。施工期间不得跳过 B0；
> 任何一批未通过验证即回滚该批，不得进入下一批。

---

## 1. 已锁定的 11 条决策

| # | 决策 | 值 |
|---|---|---|
| 1 | 本轮边界（文档阶段） | 只产出文档，零代码改动 |
| 2 | ADR 落盘 | `docs/adr/0043`–`0047`，全部落盘 |
| 3 | token 落点 | 内联进 `styles.css` 顶部 `@layer tokens`，不新增第二份 `<link>`，不用 `@import` |
| 4 | `!important` 门禁 | 全文件 ≤ 1（唯一豁免 `[hidden]{display:none!important}`） |
| 5 | 响应式归宿 | 写进被覆盖规则所属的同一层、位于基础规则之后；不加层、不放宽 `overrides` |
| 6 | B0 基线 | 先修 `resume-center.test.mjs` 那 2 条验证死定义的断言，再冻结基线 |
| 7 | 字体 | Inter Variable + JetBrains Mono 均自托管，补 `@font-face` 与 OFL 许可 |
| 8 | `--rail-w` | **224px** |
| 9 | `--topbar-h` | **52px** |
| 10 | 视觉验收 | DOM 度量探针替代像素 diff；截图只作目视，不入库 |
| 11 | 产出物落点 | ADR + 施工单入仓；WorkBuddyData 的 00–06 留作设计档案 |

**现状实测锚点**（Playwright，视口 1706×780，DPR 1）：
`.app-rail` = 230px、`.topbar` = 64px、`#job-board` 可视宽 1424 / 内容宽 1648
→ 横向溢出 **224px**，第 5 列被裁。

---

## 2. 批次（B0–B7，八批）

> **相对方案初稿的编号变化**：初稿的 B1（加层序）与 B7（`!important` 归零）
> **已合并为新的 B1**——分层后 `!important` 的优先级是反的（低层压高层），
> 带着 100 处 `!important` 分层会制造比现状更难 debug 的级联，因此两者必须同批。
> 初稿的 B8（删别名层 + 守卫测试）成为新的 B7。批次总数由 9 降为 8。

| 批 | 内容 | 落点层 | 回滚粒度 | 验证动作 | 触及测试 |
|---|---|---|---|---|---|
| **B0** | 基线冻结：`git tag pre-css-refactor`；全量测试记录基线；6 页 × 明暗截图存档（`.scratch`，不入库）；**修 `resume-center.test.mjs` 那 2 条验证死定义的断言** | 无 | — | 基线必须全绿 | `resume-center` |
| **B1**（已完成） | **加层序 + token 内联 + `!important` 归零**（三者同批）：① 文件顶部加 8 层 `@layer` 声明；② 现有规则按块归入各层（不改声明值）；③ `design-tokens.css` 内容内联进 `@layer tokens`；④ 迁移别名块**临时启用**（选择器写回 `:root`）；⑤ 100 处 `!important` 按第 3 节逐类归零。B1a/B1b 实作记录见 `docs/plans/b1-token-alias-bridge-2026-09-18.md` §7–§8 | reset…overrides | 单 commit revert | DOM 度量探针全通过；视觉与 B0 基线一致；`node --test` 全绿 | `adr0033` / `ux-regression` / `css-structure` / `alignment-gap` / `css-architecture` |
| **B2** | 尺度收敛（5 个子批，逐维度独立）：②a 字号 63→8、②b 间距→4px 网格 11 档、②c 圆角 40→7、②d 阴影 70→4（废弃全部卡片阴影）、②e z-index→9 档 | components / patterns | **每维度单独 revert** | 每子批后 DOM 度量 + 逐页明暗截图比对 | `resume-center` |
| **B3** | 颜色归位：508 hex + 299 rgba → token（含 `#fff`/`#000`）；删 9 处软失效硬编码 fallback；删 5 处装饰性渐变；`--match-soft` 补定义。**B3a（已完成的视觉零变化半批）** = canonical 颜色桥前置 + `--shadow-ink` 基元 + 字面量棘轮；**B3b** = 业务规则替换、fallback/渐变清理、门禁归零 | tokens + 全层 | 单 commit revert | 明暗双主题逐页截图；颜色字面量门禁归零 | 全部 CSS 测试 |
| **B4** | 原生控件改造：`appearance: none` + 自绘箭头 + 等高 + `outline` 焦点环 + `color-scheme` 同步 | base / components | 单 commit revert | 6 页控件截图（含 select 展开态）；Tier 1/2 判据逐处落点 | 无 |
| **B5** | 图标替换：新增 `app/icons.js`；替换 2 处 emoji + `◐`/`✕` 图标化；`→` 逐个判定；`·`/`•`/`…` 改元素或 `::marker` | components | 单 commit revert | P0-1 正则零命中；交互态截图 | `adr0033`（emoji 正则） |
| **B6** | 死代码清理：按 C1/C2/C3 三批判定后处置（499 个候选，**禁直接批量删**） | — | **按批 revert** | 逐页走查；发现「删了还活着」立即回滚 | 全部 |
| **B7** | **删除迁移别名块** + 落地守卫测试 | tokens | 单 commit revert | 全量测试 + 全页 DOM 度量 + 走查 | 全部 |

### B0 必做的 2 条断言修正

`resume-center.test.mjs` 用 `stylesCss.match(/…/)`（**不带 `g`，只返回第一个匹配**）
抽取 CSS 规则体。全文件 13 处该模式中，**2 处命中的是被覆盖的定义**：

| 断言 | 读到 | 实际生效 |
|---|---|---|
| `:38` `.board-column` | `styles.css:3776`（`--surface-tint` / `--line` / `inset`） | `styles.css:8921`（`--surface-3` / `--border-hairline` / `box-shadow:none`） |
| `:46` `.board-card:hover` | `styles.css:3864`（`translateY(-2px)` + `--shadow-2`） | `styles.css:8989`（`--surface-hover` + `--border-strong`，无 transform 无阴影） |

处置：把这 2 处的解析从「第一个匹配」换成「取生效定义」
（复用 `ux-regression.test.mjs:61-83` 已有的特异性解析原型），
**其余 11 处不动**（已核实：它们的「第一个匹配」就是唯一/生效定义）。

> 附带事实，供后续参考：`live-sheet.test.mjs:156/162` 的 `.split-layout`
> 有 2 处定义，但两处都写 `grid-template-columns: 1fr`、都不含
> `22% 48% 30%`，断言对两份定义都成立，**不是**死定义问题。

---

## 3. `!important` 归零的实现路径（B1 内）

实测 100 处，按类逐条处置：

| 类 | 条数 | 位置 | 处置 |
|---|---|---|---|
| 对消补丁 | ~45 | `styles.css:6525-6571`（Apple 层）× `11006-11073`（v3.1 层） | **两侧一并删除**，值改由 tokens 层供 |
| `prefers-reduced-motion` | 13 | 4 个媒体块 | 移入 `tokens` 层：`@media (prefers-reduced-motion: reduce){ :root{ --dur-*: 1ms } }`；前提是全部动效时长走 `var(--dur-*)`。**不保留任何 `*{animation-duration:0.01ms!important}`** |
| `@media print` | 17 | 多个媒体块 | 移入 `overrides` 层；作为最高层不需要 `!important` |
| `[hidden]` / `.hidden` 守卫 | 6 | `:10`、`:9178`、`:9643`、`:11401`、`:11659` 等 | 合并为 `reset` 层 1 条 `[hidden]{display:none!important}` |
| 响应式布局覆盖 | ~11 | `:7770-7802` | 按 ADR-0043 决定 4 写回**同层媒体查询**，位于基础规则之后 |
| 其余 | 剩余 | — | 归零 |

**门禁**：`grep -c '!important' src/resualign/static/styles.css` 必须 = 1，
且该处必须命中 `[hidden]` 白名单。

---

## 4. 迁移期别名块：为什么必须临时启用

ADR-0044 决定 3 规定 `--ra-*` 只允许存在于**默认不生效**的别名块
（`:root:where([data-ra-alias])`）。但存量 `styles.css` 里大量引用 `--ra-*`，
若别名块在迁移期不生效，这些引用会全部变成未定义——**恰好制造出第 11 个
「引用但未定义」的变量，而它正是本次要消灭的病**。

因此本单明确：

1. **B1 里把别名块的选择器临时改回 `:root`（即生效）**，构成「别名共存」的
   安全网——即某处选择器忘了迁移，仍读到正确值，物理上不会出现
   「改 token 名导致大面积变白/变黑」。
2. **B7 里整块删除**（不是改回默认不生效）。
3. 别名块的存续窗口 = B1…B6，**从不与 canonical 长期并存**，
   与 ADR-0044「禁止第三套命名长期存在」不冲突。

---

## 5. 验收：DOM 度量探针（替代像素 diff）

新增一个探针脚本（建议 `.scratch/prod-readiness/css_metrics_probe.py`，
仿既有 `gate_probe.py` 模式），运行条件：

- 隔离实例：fresh `RESUALIGN_DATA_DIR`，端口 8003（**不得碰用户的 8000**）。
- 视口 1706×780，DPR 1，`prefers-reduced-motion: reduce`（冻结动画）。
- 逐路由 `#/`、`#/dashboard`、`#/jobs`、`#/resumes`、`#/resume`、
  `#/workspace`、`#/settings`、`#/review`。

断言项（全部为 DOM / 计算样式度量，非像素比对）：

| # | 断言 | 判据 |
|---|---|---|
| D1 | 看板 5 列完整可见 | `#job-board` 的 `scrollWidth - clientWidth == 0`（现状 224） |
| D2 | `.app-rail` 宽度 | 计算宽度 = `var(--rail-w)` = 224px |
| D3 | `.topbar` 高度 | 计算高度 = `var(--topbar-h)` = 52px |
| D4 | 卡片 / 面板无阴影 | 计算 `box-shadow` 为 `none`（除 `.is-dragging` 与浮层） |
| D5 | A4 纸面宽度 | `.a4-paper` 计算宽度 = 794px（1920 与 1440 下一致） |
| D6 | 内容最大宽生效 | `.dash-grid` 容器宽度 ≤ `--content-max`（1560px） |
| D7 | 强调色每屏可见 ≤ 2 处 | 统计含 `--accent` 实底/文字色的可见元素 |
| D8 | 页面级横向滚动 | `documentElement.scrollWidth == innerWidth` |

### 回滚触发条件（写死，不留裁量）

命中任一条即 revert 当前批：

1. 任一测试由绿转红（不得「先红后修」）；
2. 任一 D1–D8 断言失败；
3. 出现黑底黑字 / 白底白字 / 正文对比度 < 4.5:1；
4. 关键选择器丢失（`css-structure.test.mjs` 的骨架类；
   `jobs-match.test.mjs` 的禁复活名单）；
5. `!important` 数量不降反升。

---

## 6. 必须在 B0/B1 同步修改的 5 个测试文件

| # | 文件 | 改动 | 性质 |
|---|---|---|---|
| 1 | `css-structure.test.mjs` | 「关键选择器须在文件后 34% 区段」→「须定义在 `@layer layout/components` 内」（`:68-83`） | 测试编码了旧架构的反模式护栏 |
| 2 | `adr0033.test.mjs` | 删 `class="dark"` 断言（`:37-40`）；配色 4 条断言（`:30-33`）按 ADR-0047 重写；`v=33`→`v=34`（`:101-104`，同步 `index.html:8`/`:122`）。**保留** `:34` 的 `--paper-bg: #ffffff` 断言 | 测试编码了被取代的旧决策 |
| 3 | `resume-center.test.mjs` | 解析器改「取生效定义」（`:38`/`:46`）；hover 断言改「有可见层级变化」；拖拽态用 `--shadow-drag`；`--surface-tint` → `--surface-3` | 测试一直在保护死定义 |
| 4 | `ux-regression.test.mjs` | `:133` 的 `:root` 正则须穿透 `@layer tokens`；`--ra-text-secondary` 名字断言（`:96-116`）改为「引用 token 白名单内的名字」；块标记 `--ra-canvas` → `--bg-canvas` | 解析方式不适配新结构 + 命名基准变更 |
| 5 | `alignment-gap.test.mjs` | `.app-rail{240px}`（`:121`）→「必须引用 `--rail-w`」；`.topbar{height:64px}`（`:124`）→「必须引用 `--topbar-h`」 | 魔法数字断言被 ADR-0044 决定 10 超越；且现状 240px 命中的是被覆盖的定义 |

**纪律：先改测试，再改 CSS。** 与规格冲突时先改规格；上述 5 处都是
「测试编码了旧架构 / 保护死定义 / 锁魔法数字」，迁就测试等于让旧架构借测试还魂。

> 可复用模式（建议写进团队规范）：凡「断言某个 CSS 值等于某个魔法数字 /
> 字面量」的测试，都会随设计系统演进**静默失效**（照旧绿灯）。改为
> 「断言引用了正确的 token」，同时通过「新结构生效」与「旧值不再写死」两个检验。

---

## 7. 守卫测试（B7 交付，净增不替换）

每条须写明守的是什么不变式：

| # | 不变式 |
|---|---|
| G1 | `@layer` 声明**唯一且顺序正确**（8 层，顺序符合 ADR-0043 决定 1） |
| G2 | `!important` 计数 = 1，且该处命中 `[hidden]` 白名单 |
| G3 | 业务代码颜色字面量 0 处（**除 `@layer tokens` 内**——白名单按**层名**判定，不按文件名） |
| G4 | 每个 token 引用名必须精确命中定义表或别名映射表（专治 `--ra-warn` vs `--ra-warning` 那类一字之差） |
| G5 | 裸 `font-size: <px/rem>` 0 处；裸 `z-index: <n>` 0 处 |
| G6 | 静默失效变量 0；零引用变量 0 |
| G7 | `<svg` 字面量只允许出现在 `app/icons.js`（例外：`empty-state__illustration`） |

> 既有断言只能证明「没改坏原来那几处」；守卫测试才能证明「第五代补丁不会再来」。
> **前者是防守，后者是免疫。**

---

## 8. 字体资产的待办（B1 内落地）

ADR-0044 决定 11 已批准引入，施工时须一并确定：

- 文件落点：`src/resualign/static/fonts/`（**`static/` 目录第一次引入二进制**）。
- 自托管 woff2：Inter Variable（拉丁 UI）+ JetBrains Mono（数字/等宽）。
- **`font-display` 取值**：本产品为本地应用、字体同源同机加载，建议
  `font-display: swap`（避免首屏文字不可见）；若实测出现可见字形跳动，
  再评估 `optional`。
- **OFL 许可文件落点**：随字体文件同目录放 `LICENSE-Inter.txt` /
  `LICENSE-JetBrainsMono.txt`。
- `@font-face` 声明落 `@layer tokens`；`--font-ui` 以 Inter Variable 起头
  并保留 CJK 系统栈兜底。
- 数字对齐仍依赖 `font-variant-numeric: tabular-nums`，字体不替代该属性。
- 禁止引用远程字体 CDN。

---

## 9. 明确不做

- 不引入 Vite / PostCSS / Sass / Tailwind / CSS Modules / 任何打包或预处理。
- 不引入需打包的图标 npm 包、SVG sprite 文件、图标字体。
- 不改后端、不改 `data-*` 契约与路由（ADR-0042 冻结期零冲突要求）。
- 不修 `format.js:1858` 的 confetti 色板（含 purple `#a855f7` / rose `#f43f5e`）——
  记录为 advisory，解冻后改 `--accent` / `--success` / `--warning` / `--info` 四色。
- 不重绘 `empty-state__illustration` 的结构（它是插图，不是功能图标）。
- **不做「删除 `styles.css:3309` / `3350` 的错峰延迟声明」**——该结论已被复核
  证伪撤回，见 ADR-0046 背景第 4 条。
- 不动 `--paper-*` 命名与取值。

---

## 10. 已知缺口（不在本单解决）

| 项 | 说明 |
|---|---|
| 设计样张 `05_视觉样张.html` 不入仓 | 它保留在 WorkBuddyData 作设计档案；其侧栏 224px 与 `--rail-w` 最终值一致 |
| 死代码 499 个候选的判定 | B6 才做，须走「词集差集 + 运行时 DOM 确证」四步，禁直接批量删 |
| 控件高度归位是语义决策 | B2 子批 ②a–②e 中唯一需要人工逐组件确认的维度 |
| `--ls-*` 等组件私有 token | 属 C 组（作用域合法），B1 重命名为 `--<component>-*` 形态，不删除 |

---

## 11. B2a 字号收敛实作记录（2026-09-18）

**范围**：只替换 `styles.css` 业务规则中的裸 `font-size`，不触碰
`@layer tokens` 的 8 档定义，也不触碰 `@layer overrides` 的打印字号。

**结果**：

- 229 处业务字号归位到 `--text-2xs..3xl`；
- 业务层裸 `font-size: <px/rem>` 计数为 0；
- 新增 `css-architecture.test.mjs` 守卫，防止字号重新写死；
- 静态缓存版本 `v=37 → v=38`；
- 前端全量 **494 passed / 0 failed**；
- 8 路由 DOM 度量：rail 224 / topbar 52 / 看板溢出 0 / 0 console error；
- 16 张明暗截图完成目视检查，标题层级、看板密度、长文本区无异常；
- 唯一保留的裸字号为 `@media print` 中 `#print-root h1` 的
  `1.35rem`，位于允许的 `overrides` 层。

**归位口径**：按数值就近，等距取小档。`10px → 2xs(11)`、
`15px → base(14)`、`17px → lg(16)`、`26px → 3xl(24)`；该子批会使部分
小字略增、部分大字略减，这是收敛刻度的预期效果，不是像素保真批。

---

## 12. B2b 间距归位实作记录（2026-09-18）

**范围**：`margin*` / `padding*` / `gap` / `row-gap` / `column-gap`
归位到 `--space-1..16`；只处理 `@layer base/components/patterns/utilities`，
不改 token 定义与打印覆盖。

**结果**：

- 1125 个间距维度归位；高频 `6px → 8px`、`10px → 12px`，
  与 ADR-0044 的迁移代价预期一致；
- `1px` 描边和 `em` 相对间距保留；`calc()` / `env()` 内未包在 `var()`
  中的 px 也一并 token 化；
- 业务层裸间距 px/rem 计数为 0；
- 新增 `css-architecture.test.mjs` 的 4px 网格守卫；
- 静态缓存版本 `v=38 → v=39`；
- 前端全量 **495 passed / 0 failed**；
- 8 路由 DOM 度量：rail 224 / topbar 52 / 看板溢出 0 / 0 console error；
- 16 张明暗截图完成目视检查；
- 修复截图暴露的看板四维标签回归：容器查询下
  `.match-dim > span:first-child` 改为不换行 flex，避免「硬技能 / 弱项」
  被挤成竖排。

---

## 13. B2c 圆角收敛实作记录（2026-09-18）

**范围**：只替换 `@layer reset/base/components/patterns/utilities` 中的
`border-radius` 字面量与旧命名入口，不改 token 定义、打印覆盖或 JS/HTML 契约。

**结果**：

- 191 处圆角声明归位到 `--radius-xs/sm/md/lg/xl/2xl/pill`；
- 业务层不再出现裸 px/rem、`--radius-4/6/8` 或 `--ra-radius-*`；
- 归位按交互语义而非原数值机械就近：卡片 / 看板列 / 下拉 `lg`，
  面板 / 抽屉 `xl`，模态 / 命令面板 `2xl`，普通控件 `md`，
  只有胶囊、状态点、进度条等使用 `pill`；
- 修正了两类脚本初稿误判：方形 `.icon-btn` 回到 `md`；普通
  `.settings-bento__card`、`.llm-node-card`、`.card`、`.board-column`
  保持 `lg`，不再因原值 12/16px 被动升到 `xl/2xl`；
- 新增 `css-architecture.test.mjs` 的圆角 token 和关键组件语义守卫；
- 静态缓存版本 `v=39 → v=40`；
- 前端全量 **497 passed / 0 failed**；
- 8 路由 DOM 度量：rail 224 / topbar 52 / 看板溢出 0 / 0 console error；
- 16 张明暗截图完成目视检查，卡片、按钮、标签、抽屉、模态没有出现
  “全站同一圆角”或卡片明显比面板更圆的问题。

---

## 14. B2d 阴影收敛实作记录（2026-09-18）

**范围**：只替换 `@layer reset/base/components/patterns/utilities` 中的
`box-shadow`，不改 token 定义、打印覆盖或 JS/HTML 契约。

**结果**：

- 业务层 125 处 `box-shadow` 完成语义归位；
- 其中 69 处卡片、面板、按钮、输入框、表头与静态容器归零为
  `var(--shadow-none)`；
- 16 处真实脱离文档流的元素只允许四档 canonical token：
  `.inline-suggestion__paper` / 菜单 / 自绘 popover 使用
  `var(--shadow-popover)`，`.modal` / 命令面板 / 抽屉 /
  `.offer-celebration__card` 使用 `var(--shadow-modal)`，`.toast`
  使用 `var(--shadow-toast)`，`.board-card.is-dragging` 使用
  `var(--shadow-drag)`；
- 30 处 `inset` / `0 0 0` 是状态环、选中环或左侧语义条，不属于浮层阴影，
  原样保留；10 处焦点环继续走 `--focus` / `--focus-ring*`；
- `--ra-shadow-card`、`--card-shadow-*`、`--shadow-1..4`、`--shadow-sm`
  的业务引用归零；兼容别名仍保留到 B7 删除；
- `--shadow-none` 补齐到浅色主题 token，明暗主题均为五档闭环；
- 新增 `css-architecture.test.mjs` 守卫：业务层不得使用 legacy shadow
  token，四档浮层阴影只允许出现在浮层 / 模态 / Toast / 拖拽选择器；
- `resume-center.test.mjs` 的拖拽断言改为 `var(--shadow-drag)`；
- 静态缓存版本 `v=40 → v=41`；
- 前端全量 **500 passed / 0 failed**；
- 后端全量 **997 passed / 7 skipped**；
- 8 路由 DOM 度量：rail 224 / topbar 52 / 看板溢出 0 / 0 console error；
- 16 张明暗截图完成目视检查，卡片、面板、表格靠描边和底阶区分，
  下拉、模态、抽屉、Toast 仍保留脱离感。

---

## 15. B2e z-index 收敛实作记录（2026-09-18）

**范围**：只替换 `@layer reset/base/components/patterns/utilities` 中
的业务层 `z-index`，不改 token 数值、打印覆盖或 JS/HTML 契约。

**结果**：

- 业务层裸 `z-index: <number>` 归零，业务规则不得再引用兼容名
  `var(--ra-z-*)`；
- 收敛为 9 档 canonical token：
  `--z-below/base/sticky/rail/dropdown/drawer/modal/popover/toast`；
- 浮层语义按职责归位：Toast 与庆祝态 `toast`，模态遮罩与命令面板
  `modal`，导航栏 `rail`，菜单与筛选浮层 `dropdown`，模态内浮层
  `popover`，页内 sticky 区域 `sticky`，装饰底层 `below/base`；
- `.batch-fab` 从旧值 `80` 归到 `--z-dropdown`（30），不再越级压过抽屉、
  模态与 Toast；
- 新增 `css-architecture.test.mjs` 守卫：九档 token 必须存在、业务层不得
  写裸值或引用 legacy alias、关键组件必须使用正确语义 token；
- 静态缓存版本 `v=41 → v=42`；
- 前端全量 **502 passed / 0 failed**；
- 后端全量 **997 passed / 7 skipped**；
- 8 路由 DOM 度量：rail 224 / topbar 52 / 看板溢出 0 / 0 console error；
- 16 张明暗截图完成目视检查，菜单、模态、抽屉、看板和移动底栏层级正常。

---

## 16. B3a 颜色桥实作记录（2026-09-18）

**范围**：只改 `@layer tokens`。把 legacy 颜色名到 canonical 语义的映射放在
B1a 旧值重放**之前**，并新增 `--shadow-ink` 基元；业务规则、组件私有
`--ls-*`、打印覆盖与 JS/HTML 契约均不动。B3a 不改变当前渲染，只建立 B3b
可以逐条迁移的依据。

**结果**：

- 98 个 legacy 颜色名建立 canonical 映射；B1a migration replay 仍是最终
  旧值宿主，visual-zero fallback pins 继续排在末尾；
- `--shadow-ink: #000000` 进入 canonical token，预留给 B3b 的 rgba 黑色
  阴影/遮罩迁移；
- 业务规则颜色字面量棘轮：hex ≤ 207、rgb(a) ≤ 202、hsl(a) = 0；
- 新增 `css-architecture.test.mjs` 两条守卫：颜色桥必须保持休眠顺序；
  颜色字面量债务不得回涨；
- 前端全量 **504 passed / 0 failed**；
- 后端全量 **997 passed / 7 skipped**；
- 8 路由 DOM 度量 JSON 与 B2e 基线完全相等；
- 16 张明暗截图与 B2e 基线逐像素一致（0/16 差异）；
- 静态缓存版本不变，仍为 `v=42`。

---

## 17. B3b 颜色归位实作记录（2026-09-18）

**范围**：`@layer tokens` 颜色桥正式接管渲染，业务层颜色字面量与
硬编码 fallback 归位；`index.html` 静态缓存版本 `v=42 → v=43`。

**结果**：

- canonical 颜色命名空间生效：浅色 `--accent: #0E7C8F`，深色
  `--accent: #1FA8BC`；legacy 名只通过 B3 迁移别名指向 canonical；
- 业务规则颜色字面量归零；唯一例外是 `.live-sheet` 的 7 个组件私有
  `--ls-*` 深色纸张常量，按 ADR-0044 决定 2 保留在组件块内；
- 删除品牌标、进度条、Split Canvas、对齐进度条、技能警告条 5 处
  装饰性双色渐变；meter 的 conic-gradient 按 ADR-0044 决定 7 保留；
- 删除 9 处软失效 fallback，业务规则不再携带主题固定色兜底；
- 实底按钮统一切到 `--text-on-accent` / `--text-on-solid`，浅色主题不再
  出现白底白字或深字压深底；
- `css-architecture.test.mjs` 新增：canonical 命名空间生效、业务规则零
  颜色字面量、live-sheet 组件私有常量保持、装饰性双色渐变禁止；
- 前端全量 **506 passed / 0 failed**；
- 后端全量 **997 passed / 7 skipped**；
- 同数据 8 路由 × 明暗对比度探针：B3a 基线 199 项低对比命中，
  B3b 降至 114 项；无新增 console error；
- 16 张明暗截图完成目视检查；浅色主按钮、深色设置页、岗位看板与复盘页
  均正常，主色切到冷青后信息层级仍成立。
