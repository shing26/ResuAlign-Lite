# ResuAlign 交付状态

> 口径：本页是「什么算完成、现在到哪、什么不做」的单页声明。每个数字都带
> 口径与复现命令，明细在 [`EVIDENCE.md`](EVIDENCE.md)；历史轨迹在
> [`../CHANGELOG.md`](../CHANGELOG.md)。

## 状态声明

**技术层已具备交付条件；ADR-0059 恢复 app / skill 双主线，app 自用验证优先。**

- 版本：`v1.1.0`（tag 指向 PR #136 的 release commit）。
- 定位：**单机可复现的求职工作台 / 面试作品**，不宣称任何形态的生产上线。
- app 自用线：**正式 1/3**（仅腾讯 `bcb5d7bb`，2026-09-19 已投递）。2026-11-21
  跑批中 Dida / Reolink 未实际投递、且由脚本代点，按 runbook 不计入判据，
  降级为技术旁证（[报告](reports/app-self-use-3jd-2026-11-21.md)）；总闸 #168
  保持 `needs-info`。
- 项目评分：`79/81（97.53%）`，**合格 · 优秀**，P0 均值 3.00（未触发一票否决）。
  详见 `D:\WorkBuddyData\项目评估结果\ResuAlign-Lite\20260928-后端-431790b9.md`。
- CI：六阶段门禁（单元/契约、benchmark、Playwright、冷启动、CSS 预算、视觉快照）
  以 GitHub Actions 的 `main` 运行为准；本页不代替 CI 结论。

## 达标项（带口径）

| 维度 | 读数 | 口径 | 复现 |
| --- | --- | --- | --- |
| 后端测试 | 1439 passed / 7 skipped | 2026-11-21 全量 pytest（新工作台与取消竞态修复之后） | `PYTHONPATH=src python -m pytest tests/ -q` |
| 后端覆盖率 | ≥85%（最近快照 89.18%，`main@7b17607`） | line coverage，硬门禁 85%；本批由 CI 复核（本地 `--cov` 受 pydantic/pytest-cov 环境问题，未改动测试同样复现） | `PYTHONPATH=src python -m pytest --cov=resualign --cov-fail-under=85 tests/` |
| 前端/扩展 | 644 passed | node:test（2026-11-21） | `node --test tests/frontend/*.test.mjs tests/frontend/dom/*.test.mjs tests/extension/*.test.mjs` |
| E2E | 7 collected | Playwright + Chromium，假 LLM；通过数以 CI Stage 3 为准 | `PYTHONPATH=src python -m pytest tests/e2e -q --e2e` |
| 熔断降级 | 5/5 trial 恰第 3 次熔断 | 本地故障注入，零外部模型 | `python benchmarks/degradation_benchmark.py --trials 5` |
| 容量曲线 | 拐点 = 并发 8，错误率 0 | CI Ubuntu 确定性 API 负载 | `python benchmarks/capacity_benchmark.py --check-baseline` |
| 冷启动 | 原生 p50 616.8ms / 容器 808.5ms UID 1000 | CI Ubuntu，空数据卷 | `python benchmarks/cold_start_benchmark.py --check-baseline` |
| 备份恢复 | 在线一致性备份 + 恢复演练 | 见 `backup-restore.md` | `scripts/backup.ps1` |
| 简历×岗位排序（ADR-0065） | B1+B2 已实现，**默认关**；政策口径 P@10 +60 / +50 pp | 政策标签（非投递意愿），balanced 集 35+35 | `python benchmarks/resume_ranking_benchmark.py --selftest` + `docs/reports/resume-ranking-policy-eval-2026-10-27.md` |

> CI 的 JUnit / coverage artifact 是**持续事实源**；上表是一次带 commit 与命令的
> 固定快照，不承诺自动跟随测试数量。

## 待签收

| 项 | 现状 | 为什么不直接刷绿 |
| --- | --- | --- |
| **app 自用验证线** | **1 / 3** 真实投递 JD（腾讯 `bcb5d7bb`）；2026-11-21 另两份为未投递 JD + 脚本代点，不计入 | 缺的是输入而非方法：需另外 2 份作者真实投递过的 JD（附日期）；#168 保持 `needs-info` |

> **关于「回退开关」**：ADR-0059 §3 要求新工作台挂 feature flag，但该工作台
> （#160 三步重构）**尚未实现**，代码里也没有对应的开关——当前 `#/workspace`
> 就是唯一的工作台，没有「新/旧」可切。本页此前写的「回退开关保留」是计划
> 语言的残留，不代表已实现的保护，已删除。

## 未达标红线

| 项 | 现状 | 为什么不刷绿 |
| --- | --- | --- |
| **探针线判据** | `dist_not_executed`：四渠道 outreach 0/4，`2026-09-23 24:00` 判定线已过 | 这是**分发未执行**，不是证伪；不换判、不改阈值（ADR-0042 决定 6f） |
| **skill 自用线判据** | 1 / 3 合格例（09-15 狗食两跳链） | 需真实投递中跑满 3 例；合成例、截图、口头复述一律不计 |
| **B10 配置与密钥** | 2 分（主动取舍） | 项目选择「钳制、绝不 raise」（`api/state.py`），与标准「非法值启动期拒绝」方向相反；**不为评分改设计**（ADR-0054 决定 6） |
| **真实 LLM 端到端质量** | 9 月真实对齐 4/5 零产出（假成功主症状，见 #110）；2026-11-21 新节点 3 跑 3 产出（技术旁证，非 P0 判据） | 两批数据口径不同、都不由容量/冷启动数字代表；#115 归因与模型侧行为仍是主变量 |
| 浏览器探针 | Chromium 版本漂移曾致 E2E 假红 | 门禁已固定为 `chromium-1243`；属环境约束非产品缺陷 |

## 已知边界

- **规模**：单机 SQLite、单进程；不承诺生产规模与多实例部署。
- **LLM 依赖**：真实改写质量取决于所配模型；本地小模型（Ollama qwen2.5:7b）
  是已知能力地板。
- **爬虫**：后端抓取已退役，岗位来源依赖油猴插件或粘贴；不承诺任意站点抓取。
- **容量/冷启动数字**：来自 CI Ubuntu 的确定性 API 负载，**不代表真实 LLM
  端到端延迟**。
- **app 自用验证线**：正式 1/3，2026-11-21 的另外两份属未投递 JD + agent
  代点，判据作废。

## 双主线与触发条件

**ADR-0059 取代 ADR-0041 的 app 冻结总闸。** app 与 skill 探针同时推进；
探针阈值、取证口径和 `dist_not_executed` 事实不变。

**app 侧优先顺序**

1. P0：3 份真实投递 JD 的可靠性验证；当前 1/3，缺 2 份真实投递输入。
2. P1：ADR、术语、实施票与灰度开关。
3. P2：三步工作台、用户文案、真实性检查与输出体验。
4. P3：演示命名空间、BYOK 简化、首页空状态与本地漏斗指标。
5. P4：导航命名、评分图形与高级配置展示优化。

**冲突裁决**：app 的真实自用验证优先于探针扩面；探针仍独立判定，不能用
app 使用量代替探针证据，也不能再次冻结 app。

**历史标签**：`frozen` 保留 ADR-0041 时期的历史含义；具体票必须按 ADR-0059
重新分诊，不能继续把 `frozen` 当自动拒绝。
