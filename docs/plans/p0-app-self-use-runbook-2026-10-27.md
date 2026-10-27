# P0 app 自用验证执行清单（2026-10-27）

- **状态**：可执行（前置未跑，当前 0/3）
- **依据**：ADR-0059 §3（app 自用验证门槛）；issue #168；ADR-0065 决策 6（B 档灰度前置）
- **目标**：3 份**不同**真实投递 JD，每份至少采纳 1 条建议并保存定稿；其中至少 2 份
  完成导出（md/json/pdf）或记录投递（`status=applied` + `applied_at`）。
- **不可外包的部分**：**采纳、保存定稿、导出、记录投递必须由作者本人在 UI 完成**。
  agent 只做隔离、证据采集与汇总——代点等于自证，判据作废。

## 0. 前置检查（全部打勾才开跑）

| 项 | 要求 | 记录点 |
| --- | --- | --- |
| 3 份真实 JD | 不同公司/岗位，作者确实在投或今天会投，原文完整（含硬性要求） | 公司 / 岗位 / JD 来源 / 抓取日 |
| 主简历 | 1 份冻结版本（建议 `134ebf1e…` AI 应用/Agent 版），sha256 记入表 | resume_id + sha256 |
| 模型节点 | 可用、有额度、设置页「测试连接」通过 | provider / model / base_url（**不记 key**） |
| 额度 | `daily_llm_cap` 余量 ≥ 3 份 × 2 轮 | 设置页只读展示 |
| 隔离 | 8003 端口空闲；隔离目录为空 | `Get-NetTCPConnection -LocalPort 8003` |
| 基线 | 记录 git sha、8000 实例 `data/jobs.db` 行数与 mtime | 收尾对比，证明未写入 |
| 开关 | `RESUALIGN_RESUME_RANKING=0`（P0 不掺排序），prematch 默认开 | env 快照 |
| 时间 | setup 约 20 分钟；每份 JD 15–25 分钟（含人工审阅） | — |

> 注：完整 pytest 套件会往真实 `data/jobs.db` 写少量 `B`/`R` 夹具行（既有行为，
> 2026-10-27 全量回归后 +4 行）。P0 一律在隔离目录执行，不读写 8000 的数据。

> **当前输入状态（2026-10-27 核对）**：正式样本仍是 **1/3**——只有腾讯「后台开发」
> （`bcb5d7bb…`，`applied_at=2026-09-19`）可计入。Dida 与 Reolink 经作者确认
> **未实际投递**，永久排除；其余 `applied` 行是 7 字测试夹具。所以本清单当前的作用是
> **把方法与口径预注册**，不能开跑；出现另外 2 份真实投递 JD（附日期）后，issue #168
> 才从 `needs-info` 转 `ready-for-human`。**不得用未投递 JD、合成样例或同一 JD 重跑凑数。**

## 1. 隔离实例（8003，独立数据目录）

```powershell
# 1) 目录
$Root = "D:\ResuAlign-Lite\.scratch\p0-2026-10-27"
New-Item -ItemType Directory -Force "$Root\data", "$Root\logs", "$Root\evidence", "$Root\templates" | Out-Null

# 2) 环境变量（只作用于本进程）
$env:PYTHONPATH               = "D:\ResuAlign-Lite\src"   # 不设会报 No module named 'resualign'
$env:RESUALIGN_DATA_DIR       = "$Root\data"
$env:RESUALIGN_JOB_DB         = "$Root\data\jobs.db"
$env:RESUALIGN_LOG_DIR        = "$Root\logs"
$env:RESUALIGN_HOST           = "127.0.0.1"
$env:RESUALIGN_PORT           = "8003"
$env:RESUALIGN_PERSONAL_MODE  = "1"
$env:RESUALIGN_RESUME_RANKING = "0"

# 3) 启动（保持窗口不关）
Set-Location D:\ResuAlign-Lite
python -m resualign.api --host 127.0.0.1 --port 8003
```

启动后验证：

```powershell
curl.exe -s http://127.0.0.1:8003/health
# 期望 {"status":"ok"} 类响应；失败先看 $Root\logs
```

基线取证（开跑前 / 收尾各一次）：

```powershell
git rev-parse HEAD
(Get-Item D:\ResuAlign-Lite\data\jobs.db).Length
(Get-Item D:\ResuAlign-Lite\data\jobs.db).LastWriteTime
python scripts/p0_evidence.py --db "$Root\data\jobs.db" --tenant local --check-only
```

收尾：`Ctrl+C` 停 8003；**保留** `$Root\data`（证据），不要删；确认上面三个基线值未变
（8000 实例的 DB 在 P0 期间不应被写入）。

## 2. 每份 JD 的执行步骤（UI + 记录）

| # | 操作 | 记录点 | 失败处理 |
| --- | --- | --- | --- |
| 1 | 设置页配置节点 → 测试连接 → 保存/激活 | provider / model / base_url | 失败=env_blocked，修好再开跑 |
| 2 | 简历中心粘贴冻结主简历 → 保存 | resume_id / sha256 | — |
| 3 | 岗位库粘贴 JD → 创建岗位 | job_id / 分类结果 / 创建时间 | 重复岗位（409）换一份 JD |
| 4 | 工作台选该简历 → 运行对齐 | workbench_job_id / 开始时间 | 见 §5 重跑 |
| 5 | 等待结束，记录终端 | `alignment_status` / `alignment_reason` / `usable_diffs` / `invalid_diffs` / 墙钟 / model / prompt_version | 超时/失败记原因 |
| 6 | 逐条审阅建议 | 每条：采纳 / 跳过 + 原因（fabricated / noop / 无依据 / 质量不够） | — |
| 7 | 采纳 ≥1 条 → 保存定稿 | `final_draft_version`（必须 +1） | — |
| 8 | 导出 md/json/pdf **或** 记录投递（状态改「已投递」并填日期） | 导出格式 / 文件 sha256，或 applied_at | — |
| 9 | 截图留证 | 建议卡（含依据徽标）、被门禁拦截的条目、定稿、导出结果 | — |

**顺序纪律**：先选定 3 份 JD 再开跑，禁止跑完再看结果挑 JD（防 cherry-pick）。
同一份 JD 的多次运行各自成行，报告必须写清总运行次数。

## 3. 记录表格

模板：`$Root\templates\runs.csv`、`suggestions.csv`、`evidence-index.md`（脚本
`scripts/p0_evidence.py --write-templates` 生成）。

### 3.1 运行表 `runs.csv`（一行 = 一次对齐运行）

| 列 | 说明 |
| --- | --- |
| `seq` | JD 序号 1–3（重跑同号，用 `run_id` 区分） |
| `run_id` | `p0-01-r1` 形式 |
| `company` / `title` / `job_id` | 岗位标识 |
| `resume_id` / `resume_sha256` | 冻结简历 |
| `started_at` / `finished_at` / `wall_seconds` | 墙钟（由脚本从 `jobs` 表填） |
| `model` / `prompt_version` | 产出模型与提示版本 |
| `alignment_status` / `alignment_reason` | 终态（`no_safe_rewrite` / `model_failed` / `no_gap`） |
| `usable_diffs` / `diff_count` / `invalid_diff_count` | 有效 / 总数 / 被拦数 |
| `adopted_count` / `adopted_diff_ids` | **人工填**（UI 采纳结果） |
| `saved_final` / `final_draft_version` | 是否保存定稿（版本号必须 >0） |
| `exported` / `export_format` / `export_sha256` | 导出证据 |
| `applied_recorded` / `applied_at` | 是否记录投递 |
| `env` | `ok` / `env_blocked` / `quality_blocked` |
| `notes` | 失败阶段、异常、备注 |

示例行（一次通过运行）：

```text
seq,run_id,company,title,job_id,resume_id,resume_sha256,started_at,finished_at,wall_seconds,model,prompt_version,alignment_status,alignment_reason,usable_diffs,diff_count,invalid_diff_count,adopted_count,adopted_diff_ids,saved_final,final_draft_version,exported,export_format,export_sha256,applied_recorded,applied_at,env,notes
1,p0-01-r1,示例公司,后端工程师,<job_id>,<resume_id>,<sha>,2026-10-27T10:00:00,2026-10-27T10:04:12,252,nvidia/…,tailor/v5,succeeded,,2,5,3,2,d1;d3,yes,1,yes,markdown,<sha>,no,,ok,门禁拦了 3 条编造
```

### 3.2 逐条建议表 `suggestions.csv`（一行 = 一条 diff）

```text
run_id,suggestion_index,diff_type,gate_verdict,decision,reason,original_excerpt,proposed_excerpt
p0-01-r1,1,modify,passed,adopted,,…,… 
p0-01-r1,2,add,blocked,fabricated,原文无依据,,
```

`gate_verdict`：`passed` / `blocked`（来自 `invalid_diffs` 的 reason）；`decision`：
`adopted` / `skipped`。

### 3.3 证据索引 `evidence-index.md`

| 文件 | 类型 | sha256 | 说明 |
| --- | --- | --- | --- |
| `evidence/<job_id>.json` | 运行终态 | — | API 快照 |
| `evidence/jd-01.png` | 截图 | — | 建议卡 + 依据徽标 |
| `exports/jd-01.md` | 导出 | `<sha>` | 定稿导出 |

## 4. 判定口径（预注册，事后不得修改）

| 判定项 | 口径 |
| --- | --- |
| **采纳** | 在工作台点击采纳，且保存定稿后该条出现在 `final_draft`（用 `accepted_diff_ids` 与定稿正文交叉核对）；「可用建议」**不算**采纳 |
| **保存定稿** | `final_draft_version` ≥ 1 且 `final_draft` 非空 |
| **导出** | `POST /api/jobs/{id}/exports` 成功并落盘文件（记 sha256） |
| **记录投递** | `status=applied` 且 `applied_at` 非空 |
| **通过线** | 3/3 份「≥1 采纳 + 定稿」；且 ≥2 份「导出或记录投递」→ 通过 |
| **不通过** | 任一份 0 采纳或未定稿；或导出/投递 <2 份 → 不通过（重跑规则见 §5） |
| **环境失败** | auth / quota / 节点不可用 / 网络超时：标 `env_blocked`，**不计入产品结论**，按 §5 重跑；报告必须写原始失败次数 |
| **门禁硬阻断** | ADR-0019 整轮零建议：记为一次真实运行结果，登记 `alignment_reason`，是否重跑按 §5 |
| **报告口径** | 分子 = 满足条件的 JD 数，分母 = 3；不得把「可用建议」写成「采纳」，不得只报成功轮次 |

## 5. 重跑规则（同样预注册）

- **基础设施失败**（auth / quota / timeout / 节点不可用）：每份最多重跑 **2 次**；
  第 3 次仍失败 → `env_blocked`，判定不过线。
- **产出不可用**（`no_safe_rewrite` / `model_failed` / `no_gap`）：每份最多再跑 **1 次**
  （可换 granularity / prompt_focus / 更强节点），两次结果都登记，判定用「是否存在
  达标运行」，但报告必须列出总运行次数。
- 任何重跑都**不得改判据阈值**；若想改口径 → 新开 ADR。

## 6. 产出物与验收

1. `docs/reports/p0-app-self-use-2026-10-XX.md`：三张表（运行 / 建议 / 证据）+ 结论
   + 总运行次数 + 环境失败次数；
2. `docs/EVIDENCE.md` 新增一行（读数 · 口径 · 复现命令 · 判据 · 达标否）；
3. issue #168 评论结论并更新状态；本清单在结束后归档到 `docs/plans/`（保持不动）；
4. 证据目录：`$Root\data`（DB）、`$Root\evidence`（JSON/截图）、`$Root\exports`；
5. 若通过：新版工作台是否设默认、ADR-0065 B 档是否灰度**一处入口**（仍默认关）；
   若不过：记录卡点，回到可靠性修复，不放宽判据。

## 7. 风险与边界

- **模型能力地板**：本地 `qwen2.5:7b` 历史产出极低；P0 用强节点（NVIDIA 120B / DeepSeek），
  记 model 全名。
- **编辑器 150s 墙钟**是单次 POST 硬截止；撞上就记 `timeout_stage=editor`，不要靠重试掩盖。
- **A1 预检**会拦截 auth/quota/本地节点不可用；被拦时先修环境，不要记成产品失败。
- **单人操作偏差**：先定 JD 再跑；不要因为结果差就换 JD。
- **8000 实例只读**：P0 期间不打开 8000 的工作台做任何写操作。

## 8. 演练记录（2026-10-27，rehearsal，**不计入 P0 判据**）

用腾讯那份真实 JD（`bcb5d7bb…`，609 字）+ 冻结主简历（`134ebf1e…`，3287 字）在隔离
8003 走了一遍全链路。目的只是验证环境与流程，**不是 P0 证据**，不写 EVIDENCE 达标行、
不改 #168 状态、不代替人工采纳。

### 演练中发现的 3 个真实阻塞点（正式开跑前必须先修好）

| # | 阻塞点 | 现象 | 处置 |
| --- | --- | --- | --- |
| 1 | 启动命令缺 `PYTHONPATH` | `python -m resualign.api` 报 `No module named 'resualign'` | 上面 §1 启动块已补 `$env:PYTHONPATH` |
| 2 | DeepSeek 余额不足 | 工作台 422：**余额不足：请给该节点充值，或到「系统设置 → 模型节点」切换可用节点后重试**；A1 预检在排队前就拦住，未产生空跑 | 充值，或在隔离实例里配置可用节点 |
| 3 | 本机 Ollama 显存不足 | `qwen2.5:3b` 加载报 `cudaMalloc failed: unable to allocate CUDA0 buffer`（RTX 3050 Ti，4GB，已用 1.5GB）；`qwen2.5:1.5b` 可正常加载 | 演练/兜底用 1.5b；正式 P0 建议用远端强节点 |

### 用 `qwen2.5:1.5b` 跑通的全链路（可作为「流程可用」证据）

- 建库/建简历/建岗位 → 工作台运行 → `jd_analysis` → `tailoring` → **succeeded**，
  墙钟 **52.1s**，分析耗时 43.5s；
- `usable_diffs = 2`，diff 2 条、被门禁拦下 **1** 条（invalid_diffs=1），evaluator 85 分，
  `provenance_state` 全为 verified，prompt_version = `engine:diag:v3;profiler:v2;gap:v4;tailor:v5;eval:v3`；
- 导出守卫正常：未保存定稿时 `POST /exports` 返回 422「尚未保存定稿，请先在工作台保存定稿后再导出」；
- `scripts/p0_evidence.py` 对着隔离库跑通：1 个岗位、succeeded 1、usable≥1 为 1、定稿 0。

### 质量观察（小模型，仅供参照）

- 两条 diff 的 `section` 都标成「教育经历」，实际内容来自项目经历——**section 归属错**
  但 provenance 校验照样通过。说明门禁只保证「有据」，不保证「归位」；
- 编辑器输出带「优化算法以应对高并发和低延迟」这类与原文无关的套话，reason 里也自承
  「指标待补真实数据」。这正是 1.5B 的能力地板，不能用来判断正式 P0 的质量。

详见隔离目录 `.scratch/p0-2026-10-27/`（`data/`、`evidence/`、`resp-*.json`）。

## 附录 A：证据提取（只读，脚本已提供）

```powershell
# 运行表草稿（自动填库内字段；人工列留空）
python scripts/p0_evidence.py --db "$Root\data\jobs.db" --tenant local --out "$Root\runs-draft.csv"

# 单岗位终态快照
curl.exe -s "http://127.0.0.1:8003/api/jobs/<job_id>" -o "$Root\evidence\<job_id>.json"

# 模板
python scripts/p0_evidence.py --write-templates --dir "$Root\templates"
```

脚本只以 `mode=ro` 打开 SQLite，不写库、不联网、不调用 LLM。

## 附录 B：与 ADR-0059 / #168 的对应

| 本文 | 来源 |
| --- | --- |
| 3 份不同 JD、每份 ≥1 采纳 + 定稿 | ADR-0059 §3 |
| ≥2 份导出或记录投递 | ADR-0059 §3 |
| 隔离数据目录、不写 8000 | ADR-0059 §3 |
| 不过线则新工作台保持 flag 关闭 | ADR-0059 §3 |
| B 档（ADR-0065）灰度前置 | ADR-0065 决策 6 |
