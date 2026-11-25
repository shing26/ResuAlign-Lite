# 验收契约：advance-lanes-2026-11-25

- 任务：职位页「待推进」五段分组 + 驾驶舱「继续」按完成度优先
- 基线 HEAD：`8970432`（设计稿提交）
- 设计稿：`docs/plans/advance-lanes-design-2026-11-25.md`
- 风险分级：**业务逻辑**（列表筛选 + 驾驶舱聚合），按根 `AGENTS.md` 走完整链路
- 用户已确认的三项：①五段（含「已定稿」）②看板 chip 一起换新键 ③驾驶舱只改选取、不改卡片形态

## 修订记录

- **2026-11-25 18:30，人审（root）**，依据独立 Verifier
  `/root/verify_advance_lanes_2` 的 REJECT 报告：
  1. 确认 P1「段切换只做本地过滤」成立：隔离库 503 行时服务端
     `advance=pending_draft` 返回 17、前端本地过滤只剩 14；963 行时只剩 0。
  2. 替换 Acceptance criteria 第 7 条，新增 7b/7c/7d（服务端筛选、指标口径、
     500 上限提示）。
  3. Allowed paths 补 `api/services/jobs.py`、`dashboard-view.js`，修正
     `contracts/incremental/manifest.json` 路径。
  4. 统一 AC#1 为 `五桶 + unclassified == 总数`，删除「无JD行数」旧口径。
  5. 背景表更新为 463 行快照并标注真实库持续增长。

## 背景事实（只读核对，`tenant_id='local'`，2026-11-25 18:24 快照 463 行，无夹具）

| 桶 | 谓词 | 数量 |
| --- | --- | ---: |
| ① 待预分析 | `alignment_status='idle'` ∧ 无 `jd_profile` | 79 |
| ② 已预分析 · 未对齐 | `alignment_status='idle'` ∧ 有 `jd_profile` | 152 |
| ③ 待定稿 | `alignment_status='succeeded'` ∧ `usable_diffs≥1` ∧ 无定稿 | 17 |
| ④ 对齐失败 | `alignment_status='failed'` | 207 |
| ⑤ 已定稿 | `final_draft_version≥1` | 8 |
| 合计 | 五桶互斥，无多重命中（SQL 已验 0 行） | **463** |

计数与筛选都必须服务端化，前端数不出真值。
真实库处于持续写入状态（本日 14:18 起仍在增加），任何验收数字都必须用
`data/jobs.db` 的**隔离副本**复跑，不得直接引用本表作为断言值。

> **更正（2026-11-25，实现期实测）**：原稿写的「17 个待定稿中 7 个排在第 500 条
> 之后」是**跨租户排序**造成的假象。按 `tenant_id='local'` 隔离后只有 449 行，
> `limit=500` 全覆盖，**越界 0 条**。服务端化仍然成立（库会继续增长，且列表
> 还叠加搜索/状态等其它筛选），但那个数字不成立，不得再引用。

## Allowed paths

- `src/resualign/job_library/__init__.py`
- `src/resualign/api/schemas.py`
- `src/resualign/api/routers/jobs.py`
- `src/resualign/api/routers/dashboard.py`
- `src/resualign/api/services/jobs.py`（`job_needs_preanalyze` 迁出后的兼容引用）
- `src/resualign/static/app/job-hall.js`
- `src/resualign/static/app/job-hall-model.js`
- `src/resualign/static/app/dashboard-view.js`
- `src/resualign/static/styles.css`
- `contracts/openapi-current.json`（仅重新生成快照，不手改）
- `contracts/incremental/manifest.json`（仅当契约测试要求时追加条目）
- `tests/api/test_job_api.py`（仅追加）
- `tests/api/test_dashboard.py`（仅追加）
- `tests/frontend/job-hall.test.mjs`（仅追加）
- `tests/frontend/dom/jobs-lane-filter.test.mjs`（新增，锁 P1 回归）
- `docs/plans/advance-lanes-design-2026-11-25.md`（仅状态行）
- `plans/advance-lanes-2026-11-25.md`

## 契约

### 1. 单一分桶谓词

1. 在 `api/services/jobs.py` 之外新增纯函数分桶入口
   `job_library.advance_bucket(job) -> Literal["pending_draft","unanalyzed",
   "unaligned","failed","finalized", None]`，**必须复用**现有
   `api/services/jobs.py::job_needs_preanalyze` 的判定语义（无 JD → 不归入任何桶）。
2. `JobLibraryStore.list_jobs` 新增可选参数 `advance: str | None`，在 SQL 侧用
   等价 `CASE`/`EXISTS` 条件过滤，**过滤发生在 LIMIT/OFFSET 之前**。
3. 新增 parity 测试：同一批夹具分别走 Python 分桶与 SQL 过滤，结果逐条相等；
   且 `五桶之和 + 无JD行数 == 该租户岗位总数`。无 JD 正文的行**不落入任何桶**
   ——「未预分析」这个桶必须能被「一键预分析」清空，塞入永远跑不了的行会让它永远清不掉。

### 2. 计数来自服务端

4. `GET /api/dashboard` 响应新增 `advance` 字段：
   `{pending_draft:int, unanalyzed:int, unaligned:int, failed:int, finalized:int}`
   （加性变更，不删改既有字段）。计数口径 = 全库该租户，与任何筛选无关。
5. 计数必须与 `GET /api/jobs?advance=<bucket>&limit=...` 的**全量**结果一致；
   测试断言 `五桶之和 + 无JD行数 == kpi.jobs`。

### 3. 筛选参数

6. `GET /api/jobs` 新增可选 `advance` 查询参数，取值限定上述五值；
   非法值返回 422，**不静默忽略**（静默忽略会让用户以为筛选生效）。
7. `advance` 与既有 `search`/`status`/`job_function`/`seniority` 取交集；
   与 `view=summary` 正交（两种 view 都必须支持）。

### 4. 前端：五段分组条

8. 职位页在标题与搜索行之间渲染五段分组条，键名与后端一致：
   `pending_draft`(17) / `unanalyzed`(65) / `unaligned`(152) / `failed`(207) / `finalized`(8)。
9. 默认 `advance=all`（不选中任何段），行为与改动前一致。
10. 选中段后：列表只显示该段；段下方说明条写明「正在看什么 + 该做什么」；
    列表头显示**交集后的实际条数**，段上的数字保持全库口径不变。
11. 深链 `#/jobs?advance=pending_draft` 可复现；与 `?view=` / `?status=` 可组合。
12. 移动端 390：五段为 2×2 + 第 5 段整行，无横向溢出。

### 5. 前端：看板 chip 换新键（用户确认）

13. `WORK_FILTERS` 由 5 项改为 6 项：
    `all` / `pending_draft` / `unanalyzed` / `unaligned` / `failed` / `finalized`。
    **删除旧键** `pending` / `aligned` / `final`，不保留别名。
14. `jobWorkState` 与 `matchesWorkFilter` 同步改为五桶语义；分组条与看板 chip
    读写同一个 `hall.filters.advance`，全页只有一个状态来源。
15. 状态徽标（`jobStatusLine` 等）沿用五桶命名，`aligned` 文案不再同时覆盖
    「已定稿」。

### 6. 驾驶舱：只改选取（用户确认）

16. `list_dashboard_jobs` 的 SELECT 补 `final_draft_version` 与 `match_score` 两列。
17. `get_dashboard` 的 `quick_continue` 选取改为：
    **`pending_draft` 单独置顶**；其余未完成岗位沿用既有「最近更新优先」，
    档内 `match_score DESC`（NULL 视为 0）→ `updated_at DESC`；
    无任何未完成岗位时退回「最近更新的一条」。

    > **修订（2026-11-25，实现期裁决）**：原稿写的
    > `pending_draft` → `unanalyzed` → `unaligned` → `failed` 四档定序**无法与
    > 既有测试共存**。`test_dashboard_quick_continue_failed_includes_failure_detail`
    > 断言「失败且更新更晚」的岗位压过未预分析岗位，而
    > `test_dashboard_quick_continue_picks_most_recent_unfinished` 断言未预分析
    > 岗位压过更早的失败岗位 —— 两条既有用例对 `unanalyzed` 与 `failed` 的
    > 相对次序要求互相矛盾。契约同时规定「既有测试必须仍绿」且「不得改断言」，
    > 因此只能保留两条用例都能满足的那部分：**`pending_draft` 置顶**（这才是
    > 本轮要修的真实缺陷），其余维持原行为。定序下沉到 `failed` 之前属于
    > P2 体验增强，需要先解除那两条用例的冲突，不在本轮范围。
18. `DashboardQuickContinue` 新增 `next_action: Literal[...] | None`（加性），
    前端据此把「待定稿」渲染为「审建议」主按钮；**卡片仍为单行**，不做三行列表。

## Acceptance criteria

1. 五桶互斥，且 `五桶之和 + unclassified == 岗位总数`（隔离副本 + 夹具各一次）。
   `unclassified` = 无 JD 正文行 ∪ `succeeded ∧ usable_diffs=0` 行；
   不再使用「无JD行数」这一旧口径。
2. Python 分桶与 SQL 过滤逐条一致（parity）。
3. `advance=pending_draft` 在真实库返回 **17** 条（不是 10 条）。
4. 存在待定稿岗位时，`quick_continue` 选中其中 `match_score` 最高的一条。
5. 既有 `test_dashboard_quick_continue_picks_most_recent_unfinished` 仍绿
   （该用例无待定稿岗位，落回原行为）。
6. 1440 / 390 双视口无横向溢出、无 console error。
7. 段切换由服务端筛选：点击任一段（含深链首屏）必须发起一次
   `GET /api/jobs?view=summary&limit=500&offset=0&advance=<bucket>`，
   并携带当前 `search` / `status` / `job_function` / `seniority` / `sort`；
   `advance` 必须进入请求，禁止只对已加载的 500 条做本地过滤。
   重复点击当前已选中的同一段不得再次请求；切回「全部」发不带 `advance`
   的请求（同一组服务端参数已缓存时可直接复用，不得重复请求）。
   深链 `#/jobs?advance=<bucket>` 走同一条服务端筛选路径。
7b. 在租户总数 > 500 的隔离库上，选中 `pending_draft` 后列表条数必须等于
   服务端 `advance=pending_draft&limit=500` 的返回条数；不得出现
   「段计数 17、列表 0 条」。段计数仍取 `/api/dashboard.advance` 的全库口径。
7c. 指标卡、`kpi.jobs`、漏斗/转化率继续使用 `/api/dashboard` 全库口径或
   未筛选列表；`advance` 子集只能影响列表与说明条，不得用于重算指标。
7d. 单段超过 500 条时列表显示前 500 条并在列表头标注「仅显示前 500 条」；
   此时允许列表条数 < 段计数，这是分页上限而非筛选错误。

## 实现期补充的契约条目

19. `advance_bucket` 必须同时接受 `jd_text` 与预算好的 `has_jd_body`
    布尔量。`list_dashboard_jobs` 的 SELECT **不得**新增 `jd_text`
    ——该投影刻意不加载 JD 正文（10 万行库的内存约束），改用
    `(trim(coalesce(jd_text,'')) <> '') AS has_jd_body` 在 SQL 侧算好。
20. 前端 `advanceBucket` 必须读摘要投影字段 `jd_excerpt` / `has_jd_profile`，
    不能只认 `jd_text` / `jd_profile`。职位页走 `view=summary`，后者恒为
    undefined —— 只认它们会让**整页岗位判成 `null`、分组条全 0**
    （ADR-0070 已为预估按钮踩过同一个坑）。
21. `advance_counts().unclassified` 的口径是**不属于任何桶的行数**，
    不只是「无 JD 行」。它同时覆盖无 JD 正文行与「已跑完且无可采纳项」
    （`succeeded ∧ usable=0`）行，因此
    `五桶之和 + unclassified == 租户岗位总数` 恒成立。
22. 分组条计数来自 `/api/dashboard`，比列表晚一拍到达。dashboard 返回后
    必须**重画分段计数与说明条**，否则首屏会一直显示本地页计数
    （真实库「待定稿」会显示成 0）。

## Verification commands

```powershell
cd D:\ResuAlign-Lite
git rev-parse HEAD; git status --short
$env:PYTHONPATH='D:\ResuAlign-Lite\src'
python -m pytest tests/api/test_job_api.py tests/api/test_dashboard.py -q
python -m pytest tests/contracts/test_contract.py -q
python -m pytest tests/ -q
node --test tests/frontend/job-hall.test.mjs tests/frontend/*.test.mjs tests/frontend/dom/*.test.mjs
```

## Forbidden

- 改/删/弱化既有测试断言换通过；删测试或加 skip 不记录
- 修改 `gate.py` / `tests/fixtures/gate/` / vendor 锁
- 手改 `contracts/openapi-current.json`（只能重新生成）
- 改 `library_jobs` 表结构或新增迁移
- 改模型、编辑器、对齐链路、`job_needs_preanalyze` 的既有语义
- 提交、建分支、推送

## 签收记录

- 2026-11-25：Verifier `/root/verify_advance_lanes_2` 裁决 **REJECT**（P1 未修，
  Allowed paths 越界）。契约已按该裁决修订，等修复后复审。
- 2026-11-25 19:02：Verifier `/root/verify_advance_lanes_2` 复审 **ACCEPT**。
  证据：前端 633 passed / 0 failed；窄后端 87 passed；隔离库 503 行下
  服务端 `pending_draft`=17、首屏本地=14；AC 7/7b/7c/7d 全部通过；
  同一 Verifier 书面同意 2026-11-25 18:30 的契约修订，确认可合并。
  合并前注意：排除未跟踪的 `.dsh/`，保留本契约与新增 DOM 测试。

## Implementer 交付说明（2026-11-25，未提交）

分支 `feat/advance-lanes`，基线 `8970432`。**未 commit / 未 push**，等 Verifier。

### 改动清单

| 文件 | 内容 |
| --- | --- |
| `job_library/__init__.py` | `ADVANCE_BUCKETS` / `advance_bucket` / `_ADVANCE_SQL_CONDITIONS` / `list_jobs(advance=)` / `advance_counts`；`job_needs_preanalyze` 迁入；`list_dashboard_jobs` 补 4 列 |
| `api/routers/jobs.py` | `GET /api/jobs` 新增 `advance` 参数 |
| `api/routers/dashboard.py` | `_pick_quick_continue`：待定稿置顶；`advance` 计数 |
| `api/schemas.py` | `AdvanceCounts`、`DashboardQuickContinue.next_action` |
| `static/app/job-hall-model.js` | `advanceBucket`（读摘要字段） |
| `static/app/job-hall.js` | 6 键 `WORK_FILTERS`、五段条、说明条、深链、计数重画 |
| `static/app/dashboard-view.js` | 待定稿 → 「审建议」 |
| `static/styles.css` | `.jh-lanes` 五段条 + 390 断点 |
| `contracts/*` | 重新生成快照 + manifest 追加 `AdvanceCounts` |
| `tests/*` | 新增 6 个 API 用例 + 6 个前端用例 |

### 实现期发现并修复的真实缺陷（超出原稿）

1. **摘要投影分桶全为 null**：`view=summary` 不带 `jd_text`/`jd_profile`，原前端
   `advanceBucket` 只认它们 → 整页岗位判空、分组条全 0。改读 `jd_excerpt` /
   `has_jd_profile`（与 ADR-0070 同一处理）。
2. **`unclassified` 口径错误**：原实现只数「无 JD」行，漏掉「已跑完且无可采纳项」，
   导致 `五桶 + unclassified ≠ 总数`。改为「不属于任何桶的余量」。
3. **dashboard 投影加载 JD 正文**：原实现 SELECT 了 `jd_text`，违反该投影
   「10 万行库不加载正文」的约束。改为 SQL 侧算 `has_jd_body` 布尔量。
4. **首屏计数不刷新**：dashboard 比列表晚到，原代码只重画指标 → 分段条一直显示
   本地页计数（真实库「待定稿」显示 0）。补 `paintWorkFilter()` + 说明条重画。
5. **计数选择器破坏 DOM**：`querySelector("span")` 先命中 `.jh-lane__top`，
   把整行（含小圆点）替换成纯数字。改用 `[data-jh-count]`。
6. **「全部」用了已加载页行数**：改为 `kpi.jobs` 全库口径。
7. **`dashboard-view.js` 分支顺序**（交接已知）：待定稿的 `alignment_status`
   也是 `succeeded`，新分支必须排在通用 succeeded 之前。

### 与原契约的偏差（已在上文标注）

- **§5 决定 17 定序**：原稿四档定序与两条既有用例冲突（见上文修订说明），
  降为「只把 `pending_draft` 置顶，其余沿用最近更新」。
- **§0 的「7 条越界」**：跨租户排序假象，实测 0 条，已更正。

### 验收结果（本机实测）

- `pytest tests/ -q` → **1450 passed, 7 skipped**（517s）
- `pytest tests/api/test_job_api.py tests/api/test_dashboard.py tests/contracts -q`
  → **87 passed**
- `node --test tests/frontend/*.test.mjs tests/frontend/dom/*.test.mjs` → **628 passed**
- 真实库（`tenant_id='local'`，探测开始时 449 行）：
  17 / 65 / 152 / 207 / 8，`unclassified=0`，合计 449；
  `advance=pending_draft` 返回 **17** 条。
- 视觉：1440 / 390 双视口，职位页与驾驶舱均无横向溢出、无 console error；
  待定稿段选中态、说明条、深链 `#/jobs?advance=pending_draft` 均正确。
  截图在 `.scratch/advance-verify/`（未入库）。

### 需要 Verifier 特别复核的点

1. **§5 决定 17 的降级**是否为可接受裁决（两条既有用例确实互斥）。
2. `advance_counts` 的 `unclassified` 新口径是否与 §2 决定 5 的
   「五桶之和 + 无JD行数 == kpi.jobs」表述一致 —— 我按更强的不变量实现。
3. 真实库在我探测期间由 449 增至 463（14 条 `source_type='url'` 的校招岗位，
   写入时间与我的探测窗口重叠）。这**不是本次改动写入的**：本分支没有任何
   写 `library_jobs` 的代码路径，且我随后已停掉所有自建实例。请以你复跑时的
   实时数字为准，不要用 449。

## P1 修复（2026-11-25 18:50，按 Verifier REJECT 裁决）

### 改动

| 文件 | 内容 |
| --- | --- |
| `static/app/job-hall-model.js` | 新增纯函数 `jobsRequestUrl({filters,sort,advance,limit,offset})`，首屏不传 `advance`，段切换显式传桶 |
| `static/app/job-hall.js` | `hall.laneJobs/laneKey/laneToken`；`loadLane()` 带 `advance` 请求服务端；`paintResults()` 在 lane 激活时以 `laneJobs` 为列表数据源；指标卡仍读 `hall.jobs`（AC 7c）；深链首屏后走同一路径；`summaryJob`/`replaceJob`/hash 还原兼容 lane 行；`paintList()` 与 `paintResults()` 共用 `resultCountLabel()`（AC 7d，修复被列表重绘覆盖的问题）；`markApplied`/`rescoreJob`/状态下拉改用 `summaryJob`，500 之外的 lane 行也能操作 |
| `tests/frontend/job-hall.test.mjs` | URL 构造器单测：首屏无 `advance`、段切换有、`all` 省略、其它服务端参数保留 |
| `tests/frontend/dom/jobs-lane-filter.test.mjs` | happy-dom 回归 4 条：首屏 500 条仅 2 条待定稿；点「待定稿」必须发 `advance=pending_draft` 并显示 17 条；指标卡仍 503；重复点同段不请求；切回「全部」不请求；段 600 / 返回 500 时结果头标注「仅显示前 500 条」 |

### 证据（本机）

- `node --test tests/frontend/*.test.mjs tests/frontend/dom/*.test.mjs`
  → **633 passed, 0 failed**（新增 5 条）
- `PYTHONPATH=src python -m pytest tests/api/test_job_api.py tests/api/test_dashboard.py tests/contracts -q`
  → **87 passed**（142.56s）
- 隔离副本（`data/jobs.db` + 40 填充行）：
  `total=503`，服务端 `advance=pending_draft&limit=500` → **17**，
  首屏 500 条本地分桶 → **14**（修复前 UI 会停在 14 / 0）；
  `advance_counts.sum + unclassified = 503`。

### 未变

- 首屏仍只请求一次未筛选 `/api/jobs`；`hall.jobs` 与指标卡口径不变。
- 单段结果超过 500 时只显示前 500，并在列表头注明（AC 7d）。
- 未提交、未推送。

### 复审修复（2026-11-25 18:58）

Verifier 首轮复审发现 AC 7d 文字被 `paintList()` 无条件重写覆盖
（`job-hall.js:1301-1303`），列表视图永远看不到「仅显示前 500 条」。
已让 `paintList()` 复用 `resultCountLabel()`，并补第 4 条 DOM 用例
（段 600 / 返回 500）。同轮 P2：`markApplied`/`rescoreJob`/状态下拉仍用
`hall.jobs.find`，500 之外的 lane 行操作会静默失败；已统一改用
`summaryJob()`。
