# 验收契约：job-list-projection-2026-11-20

- 任务：职位大厅首屏性能——列表轻投影 + 详情按需加载
- 基线 HEAD：`6a9101e92066f7a39424e3e985055acf97be3207`
- 工作树：已有合并工作台改动未提交；本任务只追加下表文件，不回退他人改动。
- 风险分级：涉及 `GET /api/jobs` 查询参数与响应字段，按「业务/API」走完整链路。

## 问题证据

- 真实库 `GET /api/jobs?limit=500`：响应 5,994,155 bytes，服务端约 2.39s。
- 同一路由 cProfile：432 条中 219 条执行 `compute_match_signals`，
  `_prematch_for` 累计 1.648s，占 1.821s 的 90%+。
- 前端首张岗位卡约 3127ms；列表与详情共用同一份全量响应。

## Allowed paths

- `src/resualign/api/routers/jobs.py`
- `src/resualign/static/app/job-hall.js`
- `src/resualign/static/app/job-hall-model.js`
- `src/resualign/static/app/format.js`
- `src/resualign/static/app/main.js`
- `src/resualign/static/styles.css`
- `scripts/qa_dogfooder.py`
- `tests/api/test_job_api.py`
- `tests/frontend/alignment-gap.test.mjs`（仅追加预分析估算回归断言）
- `contracts/openapi-current.json`
- `docs/adr/0069-unified-jobs-workspace.md`
- `docs/adr/0070-job-list-summary-projection.md`
- `docs/EVIDENCE.md`
- `plans/job-list-projection-2026-11-20.md`

## 契约

1. `GET /api/jobs` 新增可选查询参数 `view=full|summary`，默认 `full`。
   - `full`（不传或显式 `full`）保持现有响应形状；不得删除既有字段。
   - `summary` 只返回列表/看板卡所需字段；禁止返回 `jd_text`、`diffs`、
     `invalid_diffs`、`jd_profile`、`gap_report`、`draft`、`final_draft`、
     `eval_score`、`custom_prompt`、`prematch`。
   - `summary` 必须保留：身份/公司/地点/薪资/职能/职级/标签/投递状态、
     匹配分与四维明细、对齐状态/原因/错误、`usable_diffs`、`has_gap`、
     `final_draft_version`、截止/跟进/投递时间、`jd_excerpt`（最多 500 字）、
     `has_jd_profile`、`profile_skills`、`audience`。
   - `audience` 由服务端用完整 JD 计算，取值 `campus|experienced`，与前端
     `inferAudience` 的既有信号一致；前端优先使用该字段。
   - `summary` 跳过 `prematch` 批量正则扫描；单个岗位详情仍返回 `prematch`。
2. `GET /api/jobs/{job_id}` 不变，仍返回完整岗位（含 JD、diffs、画像、
   prematch）。
3. 工作台列表请求改为 `view=summary`；详情只在选中/深链时请求
   `GET /api/jobs/{id}`，并缓存到内存。
4. 详情加载中、加载失败与重试必须有可见状态；失败不得静默。
5. 浏览器后退只关闭详情，不重拉列表；详情已缓存时前进不重拉详情。
6. 状态 PATCH 成功后，摘要列表与已缓存详情同步更新。
7. 其他页面从 `state.jobs` 读取岗位时，若对象是摘要（无 `jd_text`），
   编辑/详情/追加投递等需要完整字段的入口必须先取完整岗位。
8. 同一轮按用户指令继续的对比度与 QA 锚点修复不改变业务状态机：
   - 职位页小字号正文对比度 ≥ 4.5:1（装饰性 logo/分隔符除外）；
   - `scripts/qa_dogfooder.py` 适配合并页的列表/看板/数据菜单锚点，
     22 个用例 findings = 0。

## Acceptance criteria

1. 本地真实库 `GET /api/jobs?view=summary&limit=500` 响应 ≤ 1.5MB，
   连续 5 次服务端耗时中位数 ≤ 500ms（基线 5.99MB / 2.39s）。
2. `summary` 响应逐条通过禁止字段检查；`full` 响应仍含 `jd_text` 与 `diffs`。
3. `view=bogus` 返回 422。
4. 390×844 真实页面：首张岗位卡出现时间 ≤ 1500ms（基线 3127ms），
   控制台 0 error。
5. 点击岗位只新增 1 次 `/api/jobs/{id}` 请求；后退不新增列表请求；
   前进到已缓存详情不新增详情请求。
6. 详情失败注入后出现重试入口，点击可恢复。
7. 前端全量 `node --test --test-concurrency=1 tests/frontend/*.test.mjs
   tests/frontend/dom/*.test.mjs` 全绿。
8. API 相关 pytest 全绿，OpenAPI 快照按新增可选参数**有意**更新。
9. 390×844 与 1440×900 职位页可见正文（aria-hidden 装饰除外）对比度
   ≥ 4.5:1。
10. QA 狗食走查 `python scripts/qa_dogfooder.py` 输出 `findings: 0`。

## Verification commands（Verifier 亲自重跑）

```powershell
cd D:\ResuAlign-Lite
git rev-parse HEAD
git status --short

$env:PYTHONPATH='D:\ResuAlign-Lite\src'
python -m pytest tests/api/test_job_api.py tests/api/test_match_score.py tests/contracts/test_contract.py -q

node --test --test-concurrency=1 tests/frontend/*.test.mjs tests/frontend/dom/*.test.mjs

# 真实服务测量（服务需运行在 127.0.0.1:8000；curl.exe 启动开销会污染计时）
@'
import json, time, urllib.request
sizes = []
for _ in range(5):
    t = time.perf_counter()
    with urllib.request.urlopen(
        "http://127.0.0.1:8000/api/jobs?view=summary&limit=500"
    ) as r:
        body = r.read()
    sizes.append((len(body), round(time.perf_counter() - t, 3)))
print(sizes, "median_s=", sorted(x[1] for x in sizes)[2])
rows = json.loads(body)
assert all("jd_text" not in r and "diffs" not in r for r in rows)
'@ | python -

python scripts/qa_dogfooder.py
```

浏览器探针：`390×844` 与 `1440×900` 各跑一次「首屏 → 点岗位 → 后退 → 前进」，
记录首卡时间、`/api/jobs` 与 `/api/jobs/{id}` 请求数、console error。

## Forbidden

- 修改/删除/弱化既有测试断言来换取通过
- 修改 `contracts/openapi-v1.json`（v1 基线只读）
- 改变 `view=full` 的既有字段集合
- 在 `summary` 中夹带 JD 全文/diffs/画像大字段
- 为省请求把详情永久写回 `state.jobs` 冒充完整对象
- 回退工作树中他人已完成的合并工作台改动
- 提交、建分支、推送

## 签收记录

- 2026-11-20 15:07 Verifier 首轮：**REJECT**。
  - P1-A：summary 列表下「一键预分析」按 `jd_text` 估算得 0，点击被前端短路，
    0 次 POST；后端全库实际待分析 48 条。违背契约 §7。
  - P1-B：页面级可见文本仍有 4 处对比度 < 4.5（顶栏搜索占位 4.40；
    侧栏 tagline / foot status 4.24；`SQLite` 2.31）。
  - P1-C：8000 服务启动早于 `jobs.py` 最后修改，计时证据未绑定最终代码。
  - P1-D：整工作树含 11-19 前序改动，契约未给 commit 边界，归因靠 mtime。

## 修复轮（Verifier 驳回后）

新增验收：

1. 预分析估算在摘要对象上使用 `jd_excerpt` + `has_jd_profile`，与后端
   `job_needs_preanalyze` 同义；估算为 0 时仍调用后端，由后端给真值，
   不得在前端短路。
2. 页面级可见正文（`aria-hidden` 装饰除外）在 390×844 与 1440×900 均
   ≥ 4.5:1，包含顶栏搜索占位与侧栏品牌/状态文字。
3. 最终代码重启 8000 后重新计时；证据记录进程启动时间。
4. P1-D 以「本任务增量 + 前序改动清单」签收：前序改动单独列明，不并入
   本任务 Forbidden 裁决；两处前序测试改动需在签收中说明语义。

### 修复轮复跑（2026-11-20 15:25，HEAD `6a9101e`，未提交）

| 项 | 结果 |
| --- | --- |
| P1-A 预分析 | `estimatePreanalyzePending` 改读 `jd_excerpt/has_jd_profile`；0 估算不再短路，直接请求后端。浏览器：按钮「一键预分析（48）」，确认后拦截到 1 次 POST。 |
| P1-B 对比度 | 顶栏命令条、搜索占位、侧栏品牌 tagline / foot / `SQLite` 改用 `--text-secondary`。390×844 与 1440×900 页面级可见正文 0 处 <4.5。 |
| P1-C 证据绑定 | 8000 重启为 PID 40416（15:16:28），晚于最终代码；summary 5 次 0.576/0.322/0.307/0.374/0.430s，中位 0.374s；1,111,717 bytes。 |
| P1-D 归因 | 本任务写入窗口 14:09–15:25，均在 Allowed paths；11-19 前序 modified 清单与 `.dsh/`、`job-hall.test.mjs` 单独列明，按前序工作另行裁决。 |

复跑证据：

- `pytest tests/api/test_job_api.py tests/api/test_match_score.py tests/contracts/test_contract.py -q` → 62 passed。
- `node --test --test-concurrency=1 tests/frontend/*.test.mjs tests/frontend/dom/*.test.mjs` → 621 passed / 0 failed。
- `python scripts/qa_dogfooder.py` → `findings: 0`。
- 浏览器探针：移动热态首卡中位 984ms（冷 1218ms），桌面热态 1123ms（冷 1217ms）；详情点击 +1、后退/前进 0；console 0 error。

前序测试改动语义（非本任务）：

- `tests/frontend/dom/jobs-match.test.mjs`：默认排序改为 `match_score_desc`；
  合并后的职位页排序在客户端完成，旧的服务端 `sort=` 请求断言改为卡片顺序断言。
- `tests/frontend/css-architecture.test.mjs`：浮动阴影白名单新增
  `jh-menu__body` 与看板筛选/详情抽屉，对应新增 UI，不是关闭既有检查。

签收口径：本轮只对本任务增量签收；整工作树前序改动不冒充本任务产物。

### 独立 Verifier 终裁（2026-11-20 15:35，ACCEPT）

- 绑定：HEAD `6a9101e`，分支 `main`，暂存区 0；服务 PID 40416（15:16:28），
  `jobs.py`/`main.js` 15:14:28、`styles.css` 15:20:11。
- 复跑：API/契约 **62 passed**；前端 **621 passed**；QA **findings: 0**。
- AC1–AC10 全 PASS。干净服务 summary 中位 **0.224–0.240s** / 1,111,717 B；
  390 首卡最高 **1419ms**；点击详情 +1、后退/前进 0；页面级对比度
  390 最小 **4.71**、1440 最小 **4.51**，0 处 <4.5。
- §7：按钮「一键预分析（48）」，确认后 1 次 POST；强制空摘要时仍 1 次 POST。
- 路径：本轮写入均在 Allowed paths；P1-D 口径被接受，前序合并需自身 reviewer
  签收，本 ACCEPT 不为前序改动背书。
- 无剩余 P0/P1。P2：空摘要 0 估算会跳过确认弹窗直接排批（花钱型边界）；
  `jd_profile={}` 缺专门 API 用例。P3：1440 最小对比度 4.51 贴线。
