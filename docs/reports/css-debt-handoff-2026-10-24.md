# 交接：UI 体验债收尾 + CSS 结构债（2026-10-24）

> 给下一个接手 agent 的完整现场。读完 §0/§1 就能动手；§3 是项目怎么继续；
> §4 是本仓库/本机的坑（不读会浪费半天）；§6 是剩余待办与建议顺序。

## 0. 三句话总结

1. **UI 体验债 B1–B8 已全部合并**（审计 57 条问题中 P0/P1/P2 体验项清零）；**CSS 结构债项目已完成 Phase 0/1/2a/2b**，`main` = `ae7f172`。
2. 结构债下一步按顺序做 **Phase 3（内联样式/颜色字面量）→ Phase 4（断点/动效）→ Phase 5（X1/X2 + CI 接入）**；Phase 2c（语义重构降重复选择器）可选且优先级最低。
3. 本机 **`git push` 到 github.com:443 不通**，提交必须走 `scripts/push_via_api.py`（已入库，§4.1）；Windows 编码/引号坑见 §4.2；每个 PR 必须过 589 前端测试 + e2e 7 + `css_budget` + 视觉/计算样式对比，然后 CI 绿再 merge。

## 1. 仓库与分支状态（2026-10-24 08:40 快照）

- 远端 `main` head：`ae7f1726400fe590e23c71b3051f579a02f332ff`（PR #175 的 merge commit）
- 本会话产出的 PR（全部 MERGED）：

| PR | 内容 | merge commit |
|---|---|---|
| #169 | UI 体验债 B1–B6 | `5c938f75` |
| #170 | B7 小项（引导卡/移动失败态 CTA/500 条提示/简历列表/KPI 可点性/W7） | `9ba5ed1c` |
| #171 | B8（简历页级滚动、对话框可达性、失败态 LLM 入口收敛） | `3240f06b` |
| #172 | 结构债 Phase 0（度量/基线/棘轮门禁/视觉基线工具） | `2088b20d` |
| #173 | 结构债 Phase 1（零引用 token 97→0） | `121f81ce` |
| #174 | 结构债 Phase 2a（同上下文重复规则 225→141） | `6919ee0a` |
| #175 | 结构债 Phase 2b（元素级计算样式快照工具 + 安全下限结论） | `ae7f1726` |

- 本地当前分支：`structure/css-debt-phase2b`（`dbd7617`，已合并）。历史上还有 `structure/css-debt`、`structure/css-debt-phase1`、`structure/css-debt-phase2` 分支，都已合并。
- **本地 `origin/main` ref 是旧的**（github.com git 协议不通）。判断最新远端请用：
  `gh api repos/shing26/ResuAlign-Lite/commits/main --jq .sha`
- 工作区应干净；`.scratch/` 是本机证据目录（**不入库**），换机器会丢失，重要证据要落到 `docs/reports/`。

## 2. 已完成内容

### 2.1 UI 体验债 B1–B8（施工单 `docs/plans/ui-polish-direction-2026-10-22.md` §0.5–§0.12）
审计 57 条问题，按 8 批落地，关键验收数字：

| 指标 | 之前 | 之后 |
|---|---|---|
| 工作台外壳高度 | 218px | 152px |
| 顶栏 | 155px | 89px |
| 驾驶舱 KPI 区 | 384px | 208px |
| 工作台详情操作按钮 | 15 个 | 7 个 |
| 首屏 DOM 节点 | 20,147 | 3,318 |
| 简历页头 | 213px | 82px |
| 3 段流水线 chips | 251px | 44px |
| 右栏 inspector | 223px | 615px |
| 版本时间线 | 108px | 38px |

重点行为改动（接手前建议 git log 看 commit message）：驾驶舱四格 KPI 可点、最近动态置顶已投递、待办分群、工作台失败态只留 1 个 LLM 入口 + 移动底栏 CTA、简历详情桌面改页面级滚动 + 页头吸顶、对话框 `inert` + 焦点恢复、被拦截卡来源信号合并、岗位列表默认视图 + 500 条截断提示、简历列表字数/ATS 徽标/「去看诊断」、批量对齐二次确认、命令面板（`/` 或 Ctrl+K）、深色主题、加载骨架屏与错误面板带 request_id。

### 2.2 结构债项目（施工单 `docs/plans/css-debt-project-2026-10-24.md`）
| 阶段 | 内容 | 结果 | PR |
|---|---|---|---|
| P0 | 度量脚本、基线 JSON、棘轮门禁、视觉基线（20 张截图） | 工具落地 | #172 |
| P1 | 零引用 token 清零；修正度量口径（行首声明/真实消费点） | 97 → **0**；token 257→155；CSS gzip −1,520 B | #173 |
| P2a | 删「整条被覆盖」的冗余规则；重复口径改为同上下文 | 225 → **141**；`.topbar` 17→11；规则块 1,879→1,795；gzip 62,959 B | #174 |
| P2b | 元素级计算样式快照工具；验证三种激进合并 | 141 是机械安全下限；工具落地 | #175 |

当前度量（`node scripts/css_audit.mjs`）：

```
零引用 token: 0
同上下文重复定义: 141（116 组）
规则块: 1795；唯一选择器: 1499；.topbar 定义: 11
断点: 17 个不同 @media 条件；!important: 1
JS 内联 style=" 属性: 45（format 20 / resume-center 15 / main 6 / 其余 4）
JS style.* 写入: 17；JS/HTML 颜色字面量: 20；Tailwind 遗留类: 11
CSS 体积: 297,380 B（gzip 62,959 B）
```

## 3. 结构债项目怎么继续

### 3.1 施工单与工具
- 施工单：`docs/plans/css-debt-project-2026-10-24.md`（§2 度量口径 / §3 阶段计划 / §6 实现记录，含 2b 的坑）
- 工具（都在 `scripts/`，Node 标准库 + Playwright，无第三方依赖）：

| 命令 | 用途 |
|---|---|
| `node scripts/css_audit.mjs [--pretty] [--write <path>]` | 11 项度量；写基线 JSON |
| `node scripts/css_budget.mjs` | 棘轮门禁：任何指标比基线差即非零退出 |
| `node scripts/css_duplicates.mjs [--top N] [selector...]` | 重复组明细（行号 + 声明体） |
| `node scripts/css_merge_duplicates.mjs [--write]` | 只删可证明级联等价的冗余规则 |
| `python scripts/visual_baseline.py --tag <t> [--compare]` | 20 张固定尺寸截图 + 0.2% 像素对比 |
| `python scripts/style_snapshot.py --tag <t> [--compare]` | 20 页每元素 ~35 个计算属性快照/对比（CSS 重构首选验证） |

- 基线文件：`docs/reports/css-debt-baseline-2026-10-24.json`（Phase 0，历史口径）、`docs/reports/css-debt-phase1-2026-10-24.json`、`docs/reports/css-debt-phase2-2026-10-24.json`（**当前默认基线**，`css_budget.mjs` 里指向它）。
- 只有「阶段合并后」才更新基线，并在 PR 里说明为什么某指标不再降。

### 3.2 测试与服务（Windows / PowerShell 可用命令）
```powershell
# 本地服务（8000）
$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m resualign.api   # 后台 job
# 前端全量（必须显式给文件列表；node --test 通配在 Windows 会漏 dom/）
$files = @(Get-ChildItem tests\frontend\*.test.mjs | ForEach-Object FullName) + @(Get-ChildItem tests\frontend\dom\*.test.mjs | ForEach-Object FullName)
node --test --test-concurrency=1 $files
# e2e（自带 fake-LLM 与独立端口，不碰 8000）
python -m pytest tests/e2e -q --e2e
# Stage 1 等价（ruff + pytest）
python -m ruff check src/ tests/ benchmarks/ run.py；python -m pytest tests/ -q
# 结构债门禁
node scripts/css_budget.mjs
# 视觉 / 计算样式（先采 before，再改，再 after --compare）
python scripts/visual_baseline.py --tag before
python scripts/style_snapshot.py --tag before
```

### 3.3 各阶段入口建议
**Phase 3（内联样式/颜色字面量，建议下一棒）**
- 45 处 `style="`：主要在 `format.js`(20) / `resume-center.js`(15) / `main.js`(6)
  - 找：`Select-String -Path src\resualign\static\app\*.js -Pattern 'style="'`
  - 静态值 → 项目 class；动态值（进度条宽度、分数颜色、打分环）→ `el.style.setProperty("--x", value)` + CSS class 消费
  - 运行时计算值白名单写进 `scripts/css_audit.mjs` 或施工单，避免度量假阴性
- 17 处 `style.*` 写入同理；20 处颜色字面量 → tokens（tokens 层之外不允许色值）；11 类 Tailwind 原子类（`bg-appbg`、`text-white/90`、`h-screen`…）→ 项目 class
- 验收：三项归零（白名单除外）+ 589 + e2e + `style_snapshot` 对比无差异

**Phase 4（断点/动效）**
- 17 个 @media 条件 → 6 个（≤640 / ≤900 / ≤1024 / ≥1280 / print / prefers-reduced-motion）；`node scripts/css_audit.mjs | jq .css.breakpoints` 看全量
- `prefers-reduced-motion` 7 份合并为 1；`--dur-*`/`--ease-*` 全部接线
- 验收：断点 ≤6、reduced-motion 块 =1、视觉/计算样式无差异

**Phase 5（X1/X2 + CI）**
- X1：`.metric-strip` 有三套实现（styles.css L6778 / L8440 / L10969 起，另有 dashboard 变体）→ 收敛成一套
- X2：卡片密度（驾驶舱 20px / 设置 16px）→ 两档语义 token（注意 Phase 1 已删除旧 `--card-pad`，需新增）
- CI：`.github/workflows/` 增加 `css-budget` job（`node scripts/css_budget.mjs` 失败即红）与 visual advisory（不阻塞）

**Phase 2c（可选，最低优先级）**
- 141 条同上下文重复定义为级联锁死：拼接会跨 `@media` 覆盖改变结果（2b 已用计算样式快照证明 1,392 个属性变化）。只能逐组件选 canonical 规则 + 按属性插 shim，并用 `style_snapshot --compare` 逐页确认

## 4. 环境与仓库的坑（必读）

### 4.1 推送：github.com:443 不通，只能用 GitHub API
- `git push`/`git fetch`/`curl https://github.com` 都失败；`api.github.com` 可用（`gh` 可用）。
- 流程：本地 commit → `scripts/push_via_api.py` 用 Git Data API 重放（blob→tree→commit→ref，**SHA 保持一致**，字节保真）。
  - 分支名：`$env:PUSH_BRANCH='<branch>'; python scripts/push_via_api.py`
  - 新分支：脚本 GET ref 404 时自动创建，基准默认 `HEAD~1`（即分支起点提交）；或显式 `--create-from <sha>`
  - 脚本自动从 `git remote get-url origin` 识别仓库、从当前分支识别分支；新分支基准默认 `HEAD~1`，也可 `--create-from <sha>`
  - 脚本用 `ProxyHandler({})` 绕过系统代理 DevSidecar（`127.0.0.1:3118x`），否则 api.github.com 会 500/证书错误
  - 偶尔 `WinError 10060` 超时：**重试即可**（本会话遇到 2 次，第 2 次成功）
- PR/CI/merge 都用 `gh`（可用）：`gh pr create --base main --head <branch> --body-file ...`、`gh pr checks <n>`、`gh pr merge <n> --merge`
- CI：Stage 1 unit+contract / Stage 2 benchmark / Stage 3 Playwright smoke / Stage 4 cold start，push 与 pull_request 各跑一遍；Stage 3 有时 6–12 分钟，耐心轮询。

### 4.2 Windows 文件写入
- **不要用 PowerShell `Set-Content -Encoding utf8` 写含中文的文件**（BOM/编码会花）。统一用 Python `io.open(path, "w", encoding="utf-8", newline="")` 或 `write` 工具。
- PowerShell 里 `python -c "..."` 带引号/反斜杠极易炸；**把一次性脚本写成 `.scratch/*.py` 再执行**。
- 本仓库文件用 LF；工作区检出可能是 CRLF。度量脚本已统一按 LF 归一化，别用磁盘字节数直接比较。
- `git status` 显示文件「未修改」但磁盘字节数不同，多半是 CRLF 归一化，不是丢改动。

### 4.3 测试/数据安全
- 验证时**禁止真实 LLM 调用与写用户数据**：Playwright 里拦截 `/api/llm*`、`/api/jobs/*/workbench`、批量 POST（route abort）；只读 GET。
- `src/resualign/gate.py` 与 `tests/fixtures/gate/*` 是 **vendor 副本**，改规则必须上游 truetailor 先行（`VENDOR.json` 哈希锁 + `test_skill_vendor_lock.py`）。
- 岗位页默认是**列表视图**（`localStorage['resualign.jobs.view']`），e2e 里用 `tests/e2e/helpers.py::use_board_view(page)` 切看板。
- 本机 8000 端口常驻自己的服务；e2e 用独立端口，不会冲突。
- 缓存版本：改静态资源要同步 bump `src/resualign/static/index.html` 的 `?v=` 与 `tests/frontend/adr0033.test.mjs`（当前 `v=72`）。

### 4.4 CSS 约定（写样式前必看）
- 单文件 `src/resualign/static/styles.css`，`@layer reset, tokens, base, layout, components, patterns, utilities, overrides`。
- **层序优先于特异性**：改规则位置/合并规则前先想清楚是否跨层、是否跨 `@media`。`@layer components` 内 `@media` 必须排在普通规则之后（当前文件基本如此，B1–B8 追加块在部分媒体块之后，改动时勿随意重排）。
- 设计系统门禁在 `tests/frontend/css-architecture.test.mjs`：
  - 间距 4px 网格、字号/圆角/阴影/z-index 只走 token、业务层无色值、`var()` 必须能解析（G4）
  - **G6 休眠 token**：`DECLARED_ZERO_REF_API` 已清空——新增 token 必须有消费点，否则 CI 红
  - 视觉规则（`.topbar`/`.rail`/`modal` 等）有多条源码断言，删除/重命名选择器会红
- `tests/frontend/css-structure.test.mjs`：禁止空规则体、页面头不得重复 h2、v3 区段比例阈值 55%（B1–B6 append-only 润色块的妥协，别再随意调）。

## 5. 任务板 / 队友

- 共享任务板当前**无 open/claimed 任务**（task-1..15 均已 completed）。本会话的 4 个 teammate（b1-settings、b1-review、b2-shell、b3-resume）任务已结束，不要再等它们。
- 若续用 Agent Teams：CSS 单文件写操作必须串行；并行只适合「不同 app/*.js + 独立验证脚本」；每个任务写明 write scopes 与验收命令。

## 6. 剩余待办（按建议优先级）

| 优先级 | 事项 | 入口/约束 |
|---|---|---|
| P0 | **Phase 3** 内联样式/颜色字面量/Tailwind 归零 | 见 §3.3；先采 style_snapshot before |
| P0 | **Phase 4** 断点 17→6、reduced-motion 7→1、动效 token 接线 | 注意移动端与打印样式 |
| P0 | **Phase 5** X1 指标条三套合一、X2 卡片密度 token、CI 接入 css-budget | `.github/workflows/` |
| P1 | 模型失败态横幅仍有 2 个 LLM 入口（「换节点重试」+「重新运行」），审计理想是「1 主 + 下拉」 | `split-canvas.js::workbenchAlignmentErrorBanner`，需新组件 |
| P1 | Ctrl+K 命令面板是自写焦点陷阱，未走 `showModal` 的 inert/焦点恢复 | `command-panel.js` |
| P2 | 简历列表「当前主简历」徽标 | 阻塞在后端 `list_master_resumes` projection 缺 `is_primary`/`diagnosis_status` 字段（改 backend + 迁移） |
| P2 | Phase 2c 语义合并降重复选择器 | 需要 style_snapshot 逐页确认，ROI 最低 |
| P2 | 视觉基线/计算样式纳入 CI（advisory） | Phase 5 一起做 |

UI 审计原始报告（57 条明细）：`docs/reports/ui-audit-dashboard-review-settings-2026-10-22.md`、`ui-audit-jobs-workspace-2026-10-22.md`、`ui-audit-resume-system-2026-10-22.md`。

## 7. 建议的第一小时（可直接照做）

```powershell
cd D:\ResuAlign-Lite
gh api repos/shing26/ResuAlign-Lite/commits/main --jq .sha      # 确认 ae7f172...
git checkout -b structure/css-debt-phase3 <main-sha>
$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m resualign.api   # 后台起 8000
python scripts/style_snapshot.py --tag before
# 按 §3.3 Phase 3 改 code；每改完一组：
$files = @(Get-ChildItem tests\frontend\*.test.mjs | % FullName) + @(Get-ChildItem tests\frontend\dom\*.test.mjs | % FullName)
node --test --test-concurrency=1 $files
node scripts/css_budget.mjs
python scripts/style_snapshot.py --tag after; python scripts/style_snapshot.py --tag after --compare
# 提交 & 推送 & PR
git commit -m "chore(css-debt): phase 3 — inline styles to classes/tokens"
$env:PUSH_BRANCH='structure/css-debt-phase3'; python scripts/push_via_api.py
gh pr create --base main --head structure/css-debt-phase3 --title ... --body-file ...
# 轮询 gh pr checks <n>，全绿后 gh pr merge <n> --merge
```

## 8. 关键文件地图

| 路径 | 说明 |
|---|---|
| `src/resualign/static/styles.css` | 唯一样式表（~297KB / LF，13k+ 行），`@layer` 结构 |
| `src/resualign/static/index.html` | 壳层、主题 bootstrap、`?v=72` 缓存版本 |
| `src/resualign/static/app/main.js` | 路由/渲染主干、设置页、批量确认、错误面板 |
| `src/resualign/static/app/format.js` | 纯 HTML 渲染（diff 卡、列表行、引导卡、简历预览、版本时间线） |
| `src/resualign/static/app/split-canvas.js` | 对齐工作台（三栏、流水线、失败态、移动底栏） |
| `src/resualign/static/app/resume-center.js` | 简历列表/详情/版本/编辑 |
| `src/resualign/static/app/kanban.js` | 岗位库（列表/看板/筛选/分页/截断提示） |
| `src/resualign/static/app/dashboard-view.js` | 驾驶舱 KPI / 待办 / 动态 |
| `src/resualign/static/app/command-panel.js` | Ctrl+K 命令面板 |
| `src/resualign/static/app/events.js` | API 封装、toast、showModal（inert/焦点恢复/滚动锁） |
| `scripts/css_*.mjs` / `scripts/*_baseline.py` | 结构债度量与验证工具 |
| `tests/frontend/css-architecture.test.mjs` | 设计系统 & token 门禁（G4/G6 等） |
| `tests/frontend/css-structure.test.mjs` | 结构/空规则/标题 h2 门禁 |
| `tests/e2e/helpers.py` | e2e 选择器助手（含 `use_board_view`） |
| `docs/plans/ui-polish-direction-2026-10-22.md` | UI 施工单 + §0.5–§0.12 每批记录（含验收数字） |
| `docs/plans/css-debt-project-2026-10-24.md` | 结构债施工单（口径/阶段/记录/风险） |
| `docs/reports/css-debt-*.json` | 结构债基线快照（Phase 0/1/2） |

## 9. 合并前验证清单（每个 PR 都过一遍）

- [ ] 前端全量 589 pass（显式文件列表命令见 §3.2）
- [ ] e2e `pytest tests/e2e -q --e2e` 7 pass
- [ ] `node scripts/css_budget.mjs` 全 ok（改样式时）
- [ ] `python scripts/style_snapshot.py --tag after --compare` 无差异（改样式/结构时）；纯视觉调整需人工确认
- [ ] 视觉基线 `--compare` 仅预期差异（改样式时）
- [ ] 缓存版本 bump（改 `index.html`/`styles.css`/`app/*.js` 时）
- [ ] 没有真实 LLM 调用 / 用户数据写入（验证脚本只 GET 或 route abort）
- [ ] 未触碰 `src/resualign/gate.py`、`tests/fixtures/gate/*`
- [ ] commit message 说明「为什么」+ 数字；PR body 带 before/after 与验证命令
- [ ] `gh pr checks <n>` 全绿后再 merge

## 10. 证据位置（本机 `.scratch/`，不入库）

| 路径 | 内容 |
|---|---|
| `.scratch/ui-audit-2026-10-22/` | B1–B8 前后截图、`verify-*.py` 探针 |
| `.scratch/b7-*` / `.scratch/b8-*` | B7/B8 各小项实测截图与报告 |
| `.scratch/style-snapshots/` | 计算样式快照（before/after/diff） |
| `tests/visual/baseline` 等 | 视觉基线截图（PNG 不入库，manifest/diff 入库） |
| `scripts/push_via_api.py` | API 推送脚本（已入库；本机 `git push` 不通，必需） |
| `.scratch/commit-msg-*.txt` / `pr-body-*.md` | 各批 commit/PR 文案（可复用格式） |

> 证据目录是本机文件，换机器/清理后不恢复；需要长期留存的结论请写进 `docs/reports/` 或施工单。
