# 结构债项目：CSS / Token / 视觉基线（2026-10-24 立项）

> 状态：**Phase 0 已落地**（度量脚本 + 基线 + 棘轮门禁 + 视觉基线工具），Phase 1 待开工。
> 背景审计：`docs/reports/ui-audit-resume-system-2026-10-22.md` SH-05 / SH-08 / SH-12 / X1 / X2。
> 本文档是该项目的**唯一施工单**；每个阶段一个 PR，不与功能改动混提。

## 1. 为什么单独立项

B1–B8 已经让界面「看起来」对了，但底层是不断追加的 CSS：审计时 styles.css 已 1,616 个规则块、296 个选择器被重复定义、16 个 `.topbar`、12 种断点；token 层有 251 个 token、102 个从未被引用；JS 里另有 44 处内联 style 与 Tailwind 遗留原子类。

这些问题**不会在截图里直接显形**，却决定了以后每次改样式的成本与风险：

- 同一个 `.topbar` 有 17 处定义 → 改一处要翻全文找哪条最后生效；
- 97 个零引用 token → 每次做设计决策都要在「看似可用的 token」里排除噪音；
- 没有视觉基线 → 合并选择器后「测试全绿但界面变样」无法被机器发现。

所以它需要独立的度量、基线与棘轮门禁，而不是夹在功能 PR 里顺手删两行。

## 2. 度量口径（Phase 0 已落地）

脚本：`scripts/css_audit.mjs`（Node 标准库，无依赖）

| 指标 | 基线（2026-10-24，`cb91057`） | 目标 |
|---|---|---|
| styles.css 体积 | 312,491 B（gzip 65,303 B） | gzip ≤ 60 KB |
| CSS 规则块 | 1,879 | ≤ 1,600 |
| 唯一选择器 | 1,499 | — |
| 重复定义次数（同一选择器被定义多次） | **773**（404 个选择器） | ≤ 100 |
| `.topbar` 定义次数 | **17** | ≤ 2 |
| `!important` | 1 | ≤ 1 |
| 断点数量（不同 @media 条件） | **17** | ≤ 6 |
| token 定义 / 被引用 / 零引用 | 257 / 207 / **97** | 零引用 = 0 |
| JS 内联 `style="` 属性 | **45** | 0（运行时计算值走 `style.setProperty` 白名单） |
| JS `style.*` 写入 | 17 | 0（同上） |
| JS/HTML 颜色字面量 | **20** | 0（除 tokens 层） |
| Tailwind 遗留原子类 | 11 类（`bg-appbg`、`text-white/90`、`h-screen`…） | 0 |

基线 JSON：`docs/reports/css-debt-baseline-2026-10-24.json`

```bash
node scripts/css_audit.mjs --pretty                 # 看当前度量
node scripts/css_audit.mjs --write <path>.json      # 存基线
node scripts/css_budget.mjs                         # 棘轮门禁（任何指标变差即失败）
```

视觉基线：`scripts/visual_baseline.py`（Playwright + Pillow）
- 采集 5 条主路由 × 明暗 × 1440/390 = 20 张固定尺寸截图 + `manifest.json`（sha256）
- `--compare` 与 `baseline/` 逐像素对比，>0.2% 记为变化并输出 `diff-report.json`
- 截图产物不入库（`.gitignore`），manifest 与报告入库；基线按「每个阶段 PR 合并后重采」维护

## 3. 阶段计划

### Phase 0 — 度量、基线与门禁（0.5 天，已完成）
- ✅ `scripts/css_audit.mjs` + `docs/reports/css-debt-baseline-2026-10-24.json`
- ✅ `scripts/css_budget.mjs` 棘轮门禁（11 项指标只降不升）
- ✅ `scripts/visual_baseline.py` 采集/对比工具
- ✅ 文档（本文）

**Gate**：`node scripts/css_budget.mjs` 通过；脚本可在 CI 里作为独立 job（Phase 1 接入）。

### Phase 1 — 零引用 token 清零（0.5–1 天）
- 逐项核对 97 个零引用 token：确认是「死 token」还是「运行时注入」（`style.setProperty`、JS 模板里的 `--x: value`）
- 死 token 从 tokens 层删除；运行时注入的写入 `RUNTIME_INJECTED_TOKENS`（`tests/frontend/css-architecture.test.mjs`）并保留
- 同步清理 `DECLARED_ZERO_REF_API` 冻结表（当前 100+ 项），G6 断言改为「冻结表为空」

**Gate**：零引用 token 97 → 0；G6 冻结表为空；589 测试 + e2e 绿；视觉对比 0 变化（token 删除不应影响任何计算值）。

### Phase 2 — 重复选择器合并（1–1.5 天）
按 `.topbar`(17) → `.app-shell`(14) → `select`(13) → `.app-rail`(11) → `.card`(11) → `.app-main`(10) → `textarea`(10) 顺序处理：
- 后面的覆盖块（B1–B8 追加的润色层）合并进组件主定义，删除只改 1–2 个属性的重复定义
- 保留 `@layer` 语义；合并前先跑视觉基线，合并后 `--compare` 确认仅预期差异
- 每合并一个组件跑一次 589 + e2e + 截图对比

**Gate**：重复定义 773 → ≤100；`.topbar` ≤2；CSS gzip 下降 ≥5%；视觉差异仅出现在预期页面（需人工确认截图）。

### Phase 3 — JS 内联样式与颜色字面量（0.5–1 天）
- 45 处 `style="`：静态值改成 class；动态值（进度条宽度、分数颜色）改成 `style.setProperty("--x", value)` + class 消费
- 17 处 `style.*` 写入同上收敛
- 20 处颜色字面量 + 11 类 Tailwind 原子类 → tokens / 项目 class

**Gate**：内联属性/写入/颜色字面量/Tailwind 类全部为 0（白名单除外）；对比度测试不回归。

### Phase 4 — 断点与动效 token（0.5 天）
- 17 个 @media 条件合并到 6 个：`≤640` / `≤900` / `≤1024` / `≥1280` / `print` / `prefers-reduced-motion`（hover/pointer 查询保留语义但归入同一处）
- 7 份 `prefers-reduced-motion` blanket 合并为 1 份；`--dur-*` / `--ease-*` 全部接线
- 断点 token 化（`--bp-*` 仅文档用途，CSS 里直接写条件）

**Gate**：断点数量 17 → 6；reduced-motion 块 7 → 1；视觉对比无差异。

### Phase 5 — X1/X2 收敛与 CI 接入（1 天）
- X1：三套「指标条」实现合并为 `.metric-strip` 一套（驾驶舱/复盘/设置共用）
- X2：卡片密度分叉（驾驶舱 20px / 设置 16px）收敛到 `--card-pad` 两档语义 token
- CI 增加 `css-budget` job（`node scripts/css_budget.mjs`，失败即红）与 `visual-baseline`（advisory，先不阻塞）
- 更新本施工单的「实现记录」节

**Gate**：预算门禁在 CI 生效；X1/X2 代码只剩一套；README/CONTEXT 记录新的 token 使用规则。

## 4. 验收标准（项目级）

1. `node scripts/css_budget.mjs` 长期绿；所有指标 ≤ 基线（目标见 §2）。
2. 每个阶段 PR：前端 589 + e2e 7 全绿，视觉基线 `--compare` 无未确认差异。
3. 行为零变化：不新增/删除功能，不改接口与路由；每阶段独立 PR，可单独回滚。
4. `styles.css` gzip ≤ 60 KB；重复定义 ≤100；零引用 token = 0；内联样式/颜色字面量 = 0。

## 5. 风险与对策

| 风险 | 对策 |
|---|---|
| 合并选择器时覆盖顺序变化 → 视觉回归 | 每阶段先采基线；按组件小步合并；`--compare` 人工确认差异；保留旧块直到新块验证通过再删 |
| 删除 token 后运行时注入失效 | Phase 1 先扫 JS 的 `--x` 引用与 `style.setProperty`；运行注入项进白名单，不动 |
| CSS 规范层（@layer）被破坏 → 优先级连锁反应 | 只合并同层内规则；跨层调整单独提交并在 PR 说明 |
| 一次改动过大难以 review | 每阶段一个 PR，单 PR 变更行 ≤ 1,500；Phase 2 内部按组件拆 commit |
| 视觉基线本身受数据变化影响（时间/数字） | 对比阈值 0.2%；差异报告需人工确认为「预期变化」；基线在每阶段合并后重采 |

## 6. 实现记录

### Phase 2a（2026-10-24，已落地；2b 待做）
- 新增 `scripts/css-rules.mjs`（共享规则解析：选择器/声明/偏移/@layer+@media 上下文）与 `scripts/css_duplicates.mjs`（重复组明细报告，施工用）
- **度量口径修正**：重复选择器只统计「同上下文（同 @layer + 同 @media 链）内的重复定义」。跨上下文的同名选择器（桌面规则 + `@media` 覆盖）是合法响应式写法，原口径把它们算进去得到虚高的 773。新口径同上下文重复定义 = 225（116 组）
- 新增 `scripts/css_merge_duplicates.mjs`：删除「每个属性都被后续同上下文同选择器规则覆盖」的冗余规则（可证明级联等价）。**共删 84 条**
- 结果：同上下文重复定义 **225 → 141**（.topbar 17 → 11 次定义）；规则块 1,879 → 1,795；CSS 306,120 → 297,380 B（gzip 63,783 → 62,959 B）
- 视觉基线 20/20 张 **ratio 0.0**；589 测试 + e2e 全绿（`ux-regression` 的级联解析器同步改为 @layer 感知：旧实现用正则扫嵌套块会错位、且忽略层序）
- 新基线快照：`docs/reports/css-debt-phase2-2026-10-24.json`（预算默认基线切换到这里）
- **Phase 2b 记下的坑**：试过把剩余 141 条重复规则「拼接合并到最后一条」，移动端视觉基线出现 14%–32% 回归——声明被移动到最后一条的位置后，会越过夹在中间的 `@media` 覆盖（同选择器、不同上下文）。正确做法是「按属性保留各自原位置」的合并：只把后面规则重复声明的属性并到后面，前面独有的属性留在原位置，这样每条属性的有效位置不变。留给 2b 实现

### Phase 1（2026-10-24，已落地）
- 修正 token 度量口径：定义只认「行首声明」（此前 `.dashboard-kpi--teal::before` 里的 `--teal::` 被误当成定义，虚增 token 数并制造假零引用）；「被引用」只认 `var()` / `getPropertyValue` / `setProperty`（注释里提到的字样不算）
- 删除 94 个零引用 token（明/暗两处重复定义的按出现次数逐条删），冻结表 `DECLARED_ZERO_REF_API` 清空
- `--font-num`（被 fonts 测试断言存在）接线到 `.metric-value`；`--ic-stroke`（原来只被 JS 注释提到）改成 `icons.js` 读取该 token 生成 `stroke-width`，让图标描边在 token 层单一来源
- 结果：**零引用 token 97 → 0**；token 定义 257 → 155；CSS 312,491 → 306,120 B（gzip 65,303 → 63,783 B，−1,520 B）
- 验证：589 测试 + e2e 7 全绿；`scripts/css_budget.mjs` 11 项全 ok；视觉基线 20/20 张 **ratio 0.0**（纯清理，零视觉变化）
- 新增基线快照：`docs/reports/css-debt-phase1-2026-10-24.json`

### Phase 0（2026-10-24，已落地）
- `scripts/css_audit.mjs`：规则块/选择器重复度/断点/token 定义与引用/内联样式/颜色字面量/Tailwind 类/gzip 体积
- `docs/reports/css-debt-baseline-2026-10-24.json`：基线快照
- `scripts/css_budget.mjs`：11 项指标的棘轮门禁
- `scripts/visual_baseline.py`：20 张截图采集 + 0.2% 阈值对比
- 基线数字见 §2

