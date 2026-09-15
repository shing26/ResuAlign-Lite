# 地基线① 真实对齐成功率——逐案归因报告（#110）

> 日期：2026-09-15 ｜ 数据源：`data/jobs.db` **只读快照**
> （`.scratch/foundation-110/snapshot.db`，sqlite backup API）+
> `data/logs/app.log*` 四个轮转文件全量解析 ｜ 零产品代码变更，活库只读。

## 0. 方法与流量分离

`jobs` 表终态行会被清理（0 行），归因只能走日志。`app.log` 混有 pytest
流量（与真实实例共享 `tenant_id=local`），分离方法三重：
(1) llm.call 模型名过滤（`m1`/`test-model*` = 假模型）；
(2) 真实对齐必须带 job.stage 序列（diagnose→jd_profiled→gap_analyzed→
tailoring→evaluation），9 月以来 373 条 local 排队中仅 23 条有阶段痕迹；
(3) 错误话术含「对齐分析」。三者交叉后，真实对齐样本 = 8 月 11 次
（library_jobs）+ 9 月 7 次（阶段序列）+ 23 次硬失败（finished.error）。

## 1. 逐案表

### 8 月窗口（library_jobs，tenant local，11 job 全 succeeded）

| job | 模型 | 产出 | 定稿 | 归因 |
|---|---|---|---|---|
| f1253bbe（08-10） | deepseek-v4-flash | 5 diffs + 2 invalid | 否 | 正常产出 |
| bcb5d7bb（08-31） | deepseek-v4-flash | 9 diffs | **是** | 正常产出 |
| 08a6ba6b（09-05） | deepseek-v4-flash | 9 diffs | **是** | 正常产出，9 月唯一有效 run |
| 58125704 / 6246bb18（08-30） | qwen2.5:7b | 各 1 diff | 是 | **静默降级**：本地小模型贴地板产出 |
| cdf30253 等 6 job（08-30 批量） | qwen2.5:7b | 各 1 diff | 否 | 同上，批量对齐 6 连跑全部 1-diff |

### 硬失败 23 例（finished.error 含「对齐分析」，按 code 分类）

| 根因 code | 例数 | 时间分布 | 现状 |
|---|---|---|---|
| timeout（60-252s，各阶段） | 13 | 11 例 ≤08-29，2 例 09-13 | 08-29 后基本收敛；09-13 两例均在「JD 画像与差距分析」阶段、muse-glimmer-30b 节点 |
| 代码 bug：`evaluate() unexpected kwarg 'tailored_resume'` | 4 | 全部 08-18/08-19 | **已修复**（Round4 后无复现，当前 engine.py 调用路径已改） |
| schema/parse（「格式异常」） | 3 | 08-18→08-29 | 收敛 |
| 服务不可用（quota/auth 类） | 2 | 08-19、08-24 | DeepSeek 402 时代产物，已随节点切换消亡 |
| 空 error | 1 | — | 无法归因（见派单 E） |

### 9 月窗口（metrics 口径，local runs=5）

| 日期 | runs | diffs | saves | 归因 |
|---|---|---|---|---|
| 09-06 | 1 | 9 | 1（accepted 1） | deepseek 有效 run |
| 09-07→09-14 | 4 | **0** | 0 | **假成功**：succeeded 但 usable_diffs=0，激活节点为 muse-glimmer-30b（llm.call 失败率 25%：98/385） |

## 2. 分母三分解（真实对齐尝试 41 次 = 23 硬失败 + 11 月 8 月 job 级成功 + 9 月 5 runs + 2 例 09-13 失败）

- **硬失败 56%（23/41）**：其中 91% 发生在 08-30 Phase E 收口之前；
  收口后仅剩 2 例远程节点超时。**引擎硬失败已被治好。**
- **静默降级 20%（8/41）**：qwen2.5:7b 批量对齐 8 连跑各出 1 diff——
  状态机全绿，价值贴地板。这不是 bug，是**模型能力地板**，属于
  「换模型」决策而非「修代码」决策。
- **假成功 20%（8/41 中 4 runs + 4 例无阶段痕迹的 succeeded 存疑）**：
  9 月 muse-glimmer-30b 时代 succeeded + 零可用产出。**这是当前主症状**，
  且因 `usable_diffs` 字段不存在（#111 未实现）而无法自动计量。

ADR-0040 的「1/3」是 9 月窗口的 run 级口径（3 次 deepseek/muse 对比中
1 次有效）；本票的尝试级口径为 5/41 ≈ 12% 有效产出。两个数都指向同一
结论：**08-30 前死在硬失败，现在死在零产出。**

## 3. 可接受线提案（回写 ADR-0040）

> **地基线达标 = 连续 8 例真实对齐尝试中 `usable_diffs≥1` ≥7 例（≥87.5%），
> 且零代码级硬失败、超时类硬失败 ≤1 例。**

理由：当前 20%（9 月 run 级）→ 87.5% 是「作者一周狗食不撞墙」的最低体感线；
8 例 = 一周量；#111 落地 `usable_diffs` 后本线**可直接自动计量**，不再需要
本次这种日志取证。采纳/定稿率不设线——那是探针判据的地盘，不是引擎健康线。

## 4. 修复派单清单

- A. muse-glimmer-30b 零产出复现归因：隔离实例重跑 9 月 4 例零产出输入，
  判定是节点质量还是 prompt 适配（→ #115）
- B. 「JD 画像与差距分析」阶段对 30B 级远程模型超时（2 例 60-72s）：
  按角色超时与节点延迟分布调参（→ #116）
- C. pytest 与真实实例共享 `data/logs/app.log` + `tenant_id=local`，
  观测数据被测试流量污染，归因成本被人为抬高（→ #117）
- D. `jobs` 表终态行即时清理导致归因无源可查（→ #118，保留 ≥30 天）
- E. qwen 本地节点 1-diff 地板：不派单。记为已知模型能力边界，
  skill 探针 README 假设「云级模型」即源于此。

## 5. 边界与免责

- 日志轮转丢弃 08-18 之前的失败样本；8 月窗口统计是下界。
- 1 例空 error 失败无法归因。
- 「静默降级」的 1-diff 判定基于 diffs_json 计数，未评 diff 质量；
  9 月 4 例零产出的输入 job 无法从 library_jobs 反查（终态覆盖），
  复现归因走派单 A。
