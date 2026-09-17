# 0045 — 锁定 Lucide 为唯一图标源，以 `app/icons.js` 内联 SVG 工厂交付

Status: accepted (2026-09-18 用户逐项裁定；施工待 ADR-0042 冻结令解冻)

## 背景（证据链，非估计）

1. **全站没有图标体系**。内联 `<svg>` 合计 **8 个，全部集中在
   `format.js`**（`ICON_CHECK` / `ICON_X` / `ICON_WARN` /
   `ICON_PROGRESS_CHECK` / 溯源盾牌 / 溯源警示 / `empty-state__illustration` /
   1 处长行）。`styles.css` 的 `@font-face` 计数为 **0**（无图标字体），
   全站 `<img>` 计数为 **0**，`static/` 目录零二进制资产。
2. **其余「图标」由 Unicode 字符充当**：`·` U+00B7 ×97、`→` U+2192 ×34、
   `…` U+2026 ×14、`•` U+2022 ×13、`←` U+2190 ×1、`◐` U+25D0 ×1、
   `✕` U+2715 ×1。字形重量与基线来自操作系统字体，彼此不统一。
3. **P0-1 违规 2 处**：`format.js:767` 与 `main.js:2127` 用
   U+270F U+FE0F（铅笔 emoji）当「编辑」按钮图标。`styles.css:5015` 与
   `kanban.js:3` 的同形字符在注释内，不渲染，但会让 emoji 正则门禁误报。
4. **已有正确先例**。`format.js:685` 注释载明 ADR-0033 决策 9
   「emoji 全部替换为 16px 线性 SVG 图标」；`styles.css` 已有 `.ic` /
   `.ic--sm` 载体。
5. **约束**。用户裁定不得引入需要打包的图标 npm 包。

## 决定

**1. 锁定 Lucide（ISC 许可证）为图标语义与 path 几何的唯一来源。**

硬理由（逐条可机器验证）：Lucide 全部图标统一 `viewBox="0 0 24 24"`、
`fill="none"`、`stroke="currentColor"`、`stroke-linecap/linejoin="round"`、
单值 `stroke-width`。`currentColor` 使其自动跟随 `--text-*` token，明暗主题
零额外工作。

备选否决理由：Heroicons 有 outline/solid 双套（违反「一套不混用」）；
Phosphor 多 weight 变体（混用风险高）；Feather 已停止主维护。

**2. 交付形态 = `app/icons.js` 内联 SVG 工厂函数库。** 不使用 sprite 文件、
图标字体、npm 包。

否决 sprite + `<use>` 的理由：① 多 1 次 HTTP 请求；② 本产品是本地个人模式
（`rail-foot` 显示「本地 · 个人模式」），`file://` 或受限嵌入上下文下同源策略
可能导致 `<use href="sprite.svg#id">` **取不到而图标全丢**——这是本产品特有的
高风险；③ sprite 只存一套 path 会导致 16px 档描边比例失真；④ 与现有
`ICON_*` 内联模式不一致（基线改动面更大）。

**3. 尺寸三档 + 一个受限例外。**

| 档 | token | 类名 | 用途 |
|---|---|---|---|
| 受限例外 | `--ic-2xs`（12px） | 由 `icon(name, 12)` 直出 | **仅** meter 内对勾、徽标内警示。新增 12px 须说明理由 |
| 行内 | `--ic-sm`（16px） | `.ic--sm`（已有，冻结）+ `.ic--16` | 与 13–14px 文字并排、表格单元格 |
| 按内 | `--ic-md`（20px） | `.ic--20` | 按钮内、导航项、字段前缀 |
| 独立 | `--ic-lg`（24px） | `.ic--24` | 独立图标位、空态、页头动作 |

描边统一 `--ic-stroke: 1.75`（24 网格基准），随 `viewBox` 等比缩放。
**不使用** `vector-effect: non-scaling-stroke`（会让 16px 图标比 24px 的粗）。
统一属性含 `aria-hidden="true"` 与 `focusable="false"`；装饰性图标不污染
无障碍树，语义性图标改用 `role="img"` + `<title>`。

**4. 现有字符的逐类判定（不能一刀切）。**

| 字符 | 数量 | 判定 | 处置 |
|---|---|---|---|
| `→` U+2192 | 34 | 混用：散文里的「A → B」vs 按钮里的「去投递 →」 | 散文保留；按钮 / 链接 / 状态转移改 `#i-arrow-right`（16px）或 `#i-chevron-right`；三步转移改 `.stepper` 组件 |
| `·` U+00B7 | 97 | **全部是元数据分隔符，不是图标** | 不用字符，改 `.meta-sep` 元素（行内 1px 竖条 / 列表内 2px 圆点） |
| `•` U+2022 | 13 | 列表项 | CSS `::marker` 自绘或 `#i-circle-dot`（12px） |
| `…` U+2026 | 14 | 混用：文本截断 vs 「更多」按钮 | 截断用 CSS `text-overflow: ellipsis`；按钮改 `#i-more-horizontal`（20px） |
| `←` U+2190 | 1 | 「返回列表」 | `#i-arrow-left`（16px）+ 文字 |
| `◐` U+25D0 | 1 | `index.html:82` 主题切换 | `#i-sun` / `#i-moon` / `#i-monitor` 三态，`aria-pressed` 保留 |
| `✕` U+2715 | 1 | `events.js:292` 模态关闭 | `#i-x`（20px）+ `aria-label="关闭"` |
| `U+270F U+FE0F` | 2 | **P0-1 违规** | `#i-pencil`（16px）+ 文字「编辑」 |
| `U+25BE` | 多处 | `<details>` 折叠指示 | `#i-chevron-down`（16px）+ `transform: rotate(180deg)`；补 `aria-expanded` |
| `U+2794` | 注释内 | 非功能图标 | 改写注释为 `->` |

**保留 `·` / `•` / `…` 共 124 处**是刻意的：它们属排版字符域，
一刀切禁掉会误伤正常排版。CI 规则只能扫「作为按钮 / 控件内容」的符号，
不能全文件裸扫。

**5. 类名冻结。** `.ic` / `.ic--sm` / `.rail-icon` 已被
`adr0033.test.mjs:94` 与 `alignment-gap.test.mjs:127` 断言锁定，不得改名。
新增尺寸类名用 `.ic--16` / `.ic--20` / `.ic--24`。

**6. P0-1 两处替换的具体契约。**

- `format.js:767`：`✏️ 编辑</button>` → `${icon("pencil", 16)} 编辑</button>`。
- `main.js:2127`：`button.textContent = "✏️ 编辑"` → `button.innerHTML = \`${icon("pencil", 16)} 编辑\``。
  切换 `textContent` → `innerHTML` 前必须确认该按钮内容不含用户输入
  （此处为固定文案「编辑」，已核对）。若含用户输入必须先 `esc()`。
- 两处替换后 `aria-label` 不得丢失。
- `styles.css:5015` 与 `kanban.js:3` 注释内的同形字符一并改写为纯文字，
  以通过零命中要求。

**7. 四条 CI 校验。**

| # | 规则 | 实现 |
|---|---|---|
| 1 | `<svg` 字面量只允许出现在 `app/icons.js` | grep，例外：`empty-state__illustration` 结构性插图（非图标） |
| 2 | 禁止符号字形充当功能图标 | 结合 `class="btn"` / `<button>` 上下文扫，不全文件裸扫 |
| 3 | 禁用图标字体与外部图标请求 | `@font-face` 只允许 ADR-0044 批准的 Inter Variable / JetBrains Mono 文本字体 family，且同源自托管；图标字体计数 = 0，`url(*.svg)` / 外部请求计数 = 0 |
| 4 | 禁止 emoji 码点 | 复用 P0-1 正则 |

**门禁口径**：只扫 `src/resualign/static/` 下的 css / js / html 与最终样张
HTML，**不扫方案与取证类 `.md`**——取证文档引用 `✏️` / `◐` / `✕` / `→`
是在**描述**现有违规，不是把 emoji 当图标用。

## 后果

**正面**

- P0-1 两处违规清除；全站图标一套、三档尺寸、可矢量缩放、跟随主题色。
- 零请求、零 CORS、零打包；与现有 `ICON_*` 模式一脉相承，改动面最小。
- 图标数据是纯 `d` 字符串，未来换库只需换数据，不影响调用点。

**负面 / 代价**

- 图标 path 数据内联进 JS，增大产物体积；`format.js` 已有 167.8KB，需注意。
- 约 40 个图标的语义与当前中文界面用词需逐个映射确认，属一次性成本。
- `app/icons.js` 是新增 JS 文件，**违反本轮「零 JS 改动」约束**，
  故实际落地须待 ADR-0042 解冻。

## 与既有 ADR 的关系

- **ADR-0033 决策 9**（emoji → 16px 线性 SVG）：本 ADR 是其延续与补齐，
  从「替换几个字形」扩到「锁定图标库 + 交付形态 + 门禁」。
- **ADR-0044**：图标尺寸 token 与本 ADR 三档对齐。
- **ADR-0043**：`.ic` 系列归 `components` 层。
- **ADR-0042（冻结令）**：约束本 ADR 的落地时点。
