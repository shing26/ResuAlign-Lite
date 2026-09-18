# B1 施工单（续）：token 别名桥与分层

**状态**: 待施工（B0 已完成，见 ADR-0049；本单是 B1 的可执行细化）
**日期**: 2026-09-18
**依据**: ADR-0043（分层）/ ADR-0044（token 收敛）/ ADR-0047（默认浅色）/
ADR-0049（解冻与 B0 基线）
**母施工单**: `docs/plans/css-architecture-refactor-plan-2026-09-18.md`

---

## 1. 为什么需要本单

母施工单的 B1 写的是「`design-tokens.css` 内容内联进 `@layer tokens`」。
实际取证后发现三个必须先处理的约束，原样内联会把 B1 从「视觉零变化」变成一次
视觉重设计。

### 1.1 主题默认面是反的（必须先改写）

`design-tokens.css` 的主题结构：

| 行 | 选择器 | 内容 |
|---|---|---|
| 24 | `:root` | 主题无关常量：字体栈 / 字号阶 / 间距 / 圆角 / 动效 / 层级 / 栅格 / 焦点环 / 图标 / 纸面语义 |
| 206 | `:root, :root[data-theme="dark"]` | **深色值设为默认设计面**（中性底阶 / 描边 / 前景 / 强调 / 状态 / 序数 / 阴影 / data-URI 图形） |
| 321 | `:root[data-theme="light"]` | 浅色值（整体反相） |
| 407 | `:root` | B-slot 组件别名（导航 / 页头 / 按钮 / 输入 / 卡片 / 徽标 / 表格 / 看板 / 空态 / 加载 / 浮层） |
| 510 | `@media (prefers-reduced-motion: reduce) :root` | 动效时长归零（`--dur-*: 1ms`） |
| 539 | `:root:where([data-ra-alias])` | `--ra-*` 兼容别名（139 条，默认**不生效**） |

本仓现状与 ADR-0047 都是**默认浅色**。原样内联会让默认主题翻成深色。

**处置**：内联时按 ADR-0047 改写主题结构：

- 默认 `:root` ← 原 `:root[data-theme="light"]` 的值（浅色成为默认面）
- `[data-theme="dark"]` ← 原 `:root, :root[data-theme="dark"]` 的值
- 主题无关常量与 B-slot 保持不变，落在默认 `:root`
- `@media (prefers-reduced-motion)` 保持 `:root` 作用域
- `--ra-*` 别名块在 B1–B6 迁移窗口内**临时把选择器改回 `:root`**（ADR-0043 决定 4），
  B7 整块删除

### 1.2 字体二进制不存在（`@font-face` 必须推迟）

`src/resualign/static/fonts/` 目录不存在，Inter Variable / JetBrains Mono 的
woff2 与 OFL 许可文件都没有。B1 若写入 `@font-face`，浏览器会对不存在的文件发
404，违反「8 路由 0 console error」判据。

**处置**：B1 不写 `@font-face`；字体栈按现有系统回退运行；字体资产落盘后单独一批
补 `@font-face`（施工单母本 §8 的落点约定不变）。

### 1.3 别名桥的量化依据

| 项 | 数量 |
|---|---|
| `design-tokens.css` 定义的 token | 367 |
| `styles.css` 引用的 token | 221 |
| 两边同名 | 56 |
| **只在 `styles.css` 里存在、需要桥接的** | **165** |

这 165 个旧名（`--bg` / `--surface` / `--border` / `--apple-*` / `--card-*` …）
必须在新 token 落地后仍有值，否则规则大面积变成未定义。

---

## 2. B1 执行顺序（每步可独立验证）

### 步骤 A：内联并改写 token（单独一次写盘）

1. 读取 `D:\WorkBuddyData\ResuAlign-UI重构\design-tokens.css`；
2. 按 §1.1 交换两个主题块的宿主选择器；
3. 跳过任何 `@font-face`（§1.2）；
4. 把结果写入 `styles.css` 顶部的 `@layer tokens { … }`；
5. `--ra-*` 别名块选择器改为 `:root`（迁移窗口临时启用）；
6. **不改动 `styles.css` 里任何现有规则的声明值**。

验证：`node --test tests/frontend/*.test.mjs` 允许失败（解析器未适配），
但 DOM 度量与 16 张基线截图必须逐页一致。

### 步骤 B：加 8 层声明并归层

文件顶部声明（ADR-0043 决定 1）：

```css
@layer reset, tokens, base, layout, components, patterns, utilities, overrides;
```

`styles.css` 真实结构是 **24 个顶层段落**（此前误按 32 段规划）。
归层映射（段落起始行 → 层）：

| 段落 | 内容 | 层 |
|---|---|---|
| 13 | 设计 token（合并收敛 #8） | `tokens`（被 §2A 替换） |
| 19 | 基础 + Phase 0-16 组件样式 | `base`（含 reset 前缀段） |
| 1732 | Phase 17 visual redesign overlay | `overrides` |
| 3005 | Phase 18 card system + motion | `components` |
| 4141 | T5 design tokens + 三栏工作台 | `components` |
| 4313 | Phase 20 command bar + split-canvas | `components` |
| 5264 | #11 三步引导卡 | `components` |
| 5357 | F1/B7 表单护栏 | `components` |
| 5379 | Sprint 1 Dashboard | `components` |
| 5660 | Sprint 2 三栏工作台 + Live Sheet | `components` |
| 5853 | Sprint 4 漏斗 + 简历中心 + ATS | `components` |
| 6191 | Sprint 5 设置页 | `components` |
| 6511 | Apple Native Visual Patch | `overrides` |
| 6579 | Apple Native Aesthetic override | `overrides` |
| 6797 | v2.1 sidebar + topbar | `overrides` |
| 7277 | Shell 1:1 utility layer | `utilities` |
| 7669 | v2 preview final polish | `utilities` |
| 7902 | v3 preview layer | `overrides` |
| 10032 | v3 detail refinement | `overrides` |
| 10862 | v3.1 consumer visual refresh | `overrides` |
| 11703 | AI optimize panel | `components` |
| 11957 | R5 frontend finish | `overrides` |
| 12038 | UX walkthrough fixes | `overrides` |
| 12133 | 投递复盘 | `components` |

工具：`.scratch/b1_apply_layers.py`（已在真实文件上跑通；注意 tokens 段必须
放 `tokens` 层，否则留下空层会让 `css has no empty rule bodies` 失败）。

验证：DOM 度量 8 路由一致；允许 `css-structure` 的 v3 区段断言失败待步骤 D 修。

### 步骤 C：`!important` 归零

实测 **100 处**，按母施工单第 3 节分类处置：

| 类 | 处置 |
|---|---|
| `[hidden]` 守卫（1 处，`styles.css` 前缀段） | **保留**，唯一豁免 |
| `@media print` 块 | 归 `overrides` 层，删 `!important` |
| `prefers-reduced-motion` 块 | 时长走 `--dur-*`，删 `!important`；不保留 `*{animation-duration:0.01ms!important}` |
| Apple 层 × v3.1 层对消补丁 | 两侧一并删 `!important`，改由层序决胜 |
| 响应式布局覆盖 | 写回被覆盖规则所属层的媒体查询，删 `!important` |

验证：`grep -c '!important'` = 1，且命中 `[hidden]`。

### 步骤 D：同步 5 个测试

| # | 文件 | 改动 |
|---|---|---|
| 1 | `css-structure.test.mjs` | 「关键选择器须在后 34% 区段」→「须定义在 `@layer layout/components` 内」 |
| 2 | `adr0033.test.mjs` | 删 `class="dark"` 断言；配色按 ADR-0047 重写；缓存版本号递增 |
| 3 | `resume-center.test.mjs` | **B0 已完成**（取生效定义 + token 断言） |
| 4 | `ux-regression.test.mjs` | `:root` 正则须穿透 `@layer tokens`；`--ra-*` 名字断言改白名单；块标记改 canonical 名 |
| 5 | `alignment-gap.test.mjs` | **已完成**（B0 改断言 token 引用） |

---

## 3. 验收

- DOM 度量探针（`.scratch/css_metrics_probe.py`）8 路由与 B0 基线一致；
- 关键指标：rail 224 / topbar 52 / 1706 视口看板溢出 0 / 1024 视口列宽 ≥ 220px；
- 16 张截图（`.scratch/css-refactor-baseline/`）逐页目视比对，明暗各一遍；
- `!important` = 1；
- 前端 489 passed、后端 997 passed / 7 skipped 不降；
- 8 路由 0 console error。

## 4. 明确不做

- 不引入字体二进制与 `@font-face`；
- 不删除 `--ra-*` 别名块（B7 才删）；
- 不删除「引用但未定义」的 12 个变量中的历史遗留（B3 处理颜色字面量时一并核对）；
- 不动后端与 `data-*` 契约。
