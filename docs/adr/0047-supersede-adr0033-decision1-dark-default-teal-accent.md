# 0047 — 取代 ADR-0033 决策 1：默认主题由浅色改为深色，主色由 Indigo `#4F46E5` 改为冷青 `#1FA8BC`

Status: accepted (2026-09-18 用户逐项裁定；施工待 ADR-0042 冻结令解冻)

## 背景（证据链，非估计）

ADR-0033（消费者视觉刷新）决策 1 当时拍定两条：

1. **配色 Slate + Indigo**，其中 `--primary: #4F46E5`、
   `--primary-hover: #4338CA`、`--primary-soft: #EEF2FF`；
2. **默认浅色**，并要求 `index.html` 移除硬编码 `class="dark"`，
   默认主题由 `:root` 决定。

ADR-0042 的护栏要求：**阈值不得中途重谈，如需更改必须新开 ADR 并回答
「为什么现在改」**。本条按该要求立项。理由全部锚在**事实变化**上，
不锚在偏好上，且每条均可在仓库内复现：

1. **`class="dark"` 的运行事实与测试断言相反。**
   `adr0033.test.mjs:37-40` 断言 `index.html` 不含 `class="dark"`，
   据此「默认浅色」在测试上成立。但用户提供的 6 张运行时截图
   （2026-09-17）**全部为深色渲染**——即产品**实际长期运行在深色**下。
   实测复核：`index.html:2` 当前为 `<html lang="zh-CN">`，无 `class`，
   与断言一致；而实际交付面是深色。**测试锁的「默认浅色」与用户实际
   看到的产品状态不一致。**

2. **`theme.js` 的兜底方向与交付面相反，属实现漂移。**
   `theme.js` 的 `preferredTheme()` 优先级为：localStorage →
   `documentElement.classList.contains("dark")` → `prefers-color-scheme`
   → **兜底 `"light"`**（实测该行存在）。当 `class="dark"` 存在时它能返回
   `"dark"`，但对**首访、无 localStorage、且系统偏好浅色**的用户，
   它会返回 `"light"`——与「产品实际交付面是深色」相反，且造成首屏 FOUC。

3. **主色系的收敛压力已外显为可测缺陷。**
   现状并存 **4 个互不相同的「蓝」**：`#2563eb`（Tailwind blue-600）×13、
   `#007aff`（Apple blue）×8、`#6366f1`/`#4f46e5`（indigo）×12、
   以及 `--card-shadow-selected` 里的 `rgba(22,86,232,.22)`。
   即：**ADR-0033 选的 Indigo 并未真正统一主色**，反而成为 4 个蓝之一；
   「单一强调色」这一目标当时**未达成**。

## 决定

**取代 ADR-0033 决策 1 的全部内容**，变更为：

**1. 默认主题 = 深色。**

- `index.html` 携带 `class="dark"` + `data-theme="dark"`（同时消除首屏 FOUC）。
- `theme.js` 的 `preferredTheme()` 兜底由 `"light"` 改为 `"dark"`。
- 浅色降级为**次级可切换主题**，通过 `:root[data-theme="light"]` 重映射
  「必须换值」的 token（底阶 / 描边 / 前景 / 强调色 / 状态色 / 序数色 /
  遮罩 / 阴影 / data-URI 图形）。

**2. 主色 = 冷青 `#1FA8BC`**（hue ≈ 190），取代 Indigo `#4F46E5`：

| token | 深色（默认） | 浅色（次级） |
|---|---|---|
| `--accent` | `#1FA8BC` | `#0E7C8F` |
| `--accent-hover` | `#2CBACF` | `#0C6D7E` |
| `--accent-active` | `#178EA0` | `#0A5F6E` |
| `--accent-text` | `#4FC3D4` | `#0B6C7D` |
| `--accent-soft` | `#0B333B` | `#E2F3F6` |
| `--accent-on` | `#04242B` | `#FFFFFF` |

`--info` 保留蓝色（`#4E9BF0` / 浅色 `#1F6FB8`），与 accent 的青明确分工：
info 管「中性提示」，accent 管「主操作与选中」。

**3. 明确保留 ADR-0033 的其余决策**（不随本条失效）：
决策 5（投递快照右侧抽屉）、决策 7（全站唯一「投递快照」术语）、
决策 9（emoji → 16px 线性 SVG 图标），以及静态缓存版本机制。

**4. `--paper-*` 语义不受本条影响。** A4 纸在深色主题下仍恒为白纸黑字
（`--paper-bg: #FFFFFF` 写在主题无关常量块，浅色块禁止重声明）。
这是打印 / 导出正确性与 a11y 红线。相应断言
`adr0033.test.mjs`「`html.dark` 下 `--paper-bg: #ffffff`」**保留有效**。

## 被取代 / 被修订的条款（可追溯清单）

| 被取代项 | 原位置 | 状态 |
|---|---|---|
| 决策 1 前半「配色 Slate + Indigo，`--primary: #4F46E5`」 | `docs/adr/0033-consumer-visual-refresh.md` 决策 1 | **被取代** |
| 决策 1 后半「默认浅色；`index.html` 移除硬编码 `class="dark"`」 | 同上 | **被取代** |
| 决策 1 的后果段「`index.html` 移除硬编码 `class="dark"`，默认浅色由 `:root` 决定」 | 同上（Consequences） | **被取代** |
| 决策 5 / 7 / 9 | 同上 | **保留，不失效** |

> 按仓库既有惯例（见 ADR-0041 顶部的 2026-09-16 注记），已在
> `docs/adr/0033-consumer-visual-refresh.md` 顶部加入一条带日期的注记回指本条，
> 而不是就地改写其决策正文。ADR 只增不改。

## 随之失效的测试断言（属施工阶段 B0）

| 文件 | 行号 | 现状断言 | 处置 |
|---|---|---|---|
| `tests/frontend/adr0033.test.mjs` | `:30` | `--primary: #4f46e5` | 改为新主色 `#1FA8BC`，或改断言为「必须引用 `--accent`」 |
| 同上 | `:31` | `--primary-hover: #4338ca` | 改为 `--accent-hover: #2CBACF` |
| 同上 | `:32` | `--primary-soft: #eef2ff` | 改为 `--accent-soft: #0B333B` |
| 同上 | `:33` | `--bg: #f8fafc` | 改为 `--bg-canvas: #0B0D11` |
| 同上 | `:37-40` | `index.html` 不得含 `class="dark"` | **删除该断言**（新决策要求必须含） |
| 同上 | `:34` | `html.dark` 下 `--paper-bg: #ffffff` | **保留**（见决定 4） |
| 同上 | `:101-104` | `styles.css?v=33` / `main.js?v=33` | bump 到 `v=34`（`index.html:8` / `:122` 同步） |
| `tests/frontend/dom/theme.test.mjs` | `:11-22` | 手动加 `dark` 类时返回 `dark` | **不失效**（该测试手动设类，与新兜底不冲突）；建议净增一条「无 localStorage 且系统偏好浅色时兜底仍为 `dark`」 |

## 后果

**正面**

- 测试锁定的默认主题与用户实际看到的产品面一致，消除「测试绿灯但交付面不符」
  的认知偏差。
- 首屏 FOUC 消除（`index.html` 直接带 `class="dark"`，不依赖 JS 执行）。
- 主色真正收敛为 1 个（冷青），「info 是蓝、accent 是青」的分工在 token 层被
  结构性解决——原 4 个蓝的问题不再靠约定维持。
- 决策有迹可循：本条显式列出被取代条款与失效断言行号，并回答了「为什么现在改」。

**负面 / 代价**

- `adr0033.test.mjs` 一次改动 4 条断言 + 删除 1 条，是本次测试改动面最大的一处；
  须在 B0 批单独 commit 并重点回归。
- 冷青 `#1FA8BC` 在深底上的对比度须逐个使用场景验证（设计已给出
  `--accent-text` 专供文字色，并以 `--accent-on: #04242B` 保证实底前景 5.8:1）。
- 深色成为默认后，**浅色主题的回归覆盖度天然下降**（默认看不到）→ 施工须把
  「明暗双主题截图」列为强制验收项，否则浅色会静默腐化。

## 与既有 ADR 的关系

- **ADR-0033（消费者视觉刷新）**：本条取代其决策 1 及相关后果段；
  保留决策 5 / 7 / 9。
- **ADR-0042（冻结令）**：本条按其「须新开 ADR 并回答为什么现在改」的要求立项；
  施工时点受其约束（须解冻后执行）。
- **ADR-0044**：本条给出 `--accent` 的最终值，承载于其 tokens 层结构。
- **ADR-0043**：`:root[data-theme="light"]` 的重映射落在 `@layer tokens`。
