# ResuAlign 交付状态

> 口径：本页是「什么算完成、现在到哪、什么不做」的单页声明。每个数字都带
> 口径与复现命令，明细在 [`EVIDENCE.md`](EVIDENCE.md)；历史轨迹在
> [`../CHANGELOG.md`](../CHANGELOG.md)。

## 状态声明

**技术层已具备交付条件，方向层被外部动作阻塞。**

- 版本：`v1.1.0`（tag 指向 PR #136 的 release commit）。
- 定位：**单机可复现的求职工作台 / 面试作品**，不宣称任何形态的生产上线。
- 项目评分：`71/81（87.65%）`，**合格 · 优秀**，P0 五维全 ≥2（未触发一票否决）。
  详见 `D:\WorkBuddyData\项目评估结果\ResuAlign-Lite\`。
- CI：`main` 四阶段全绿（单元/契约、benchmark 门禁、Playwright、冷启动）。

## 达标项（带口径）

| 维度 | 读数 | 口径 | 复现 |
| --- | --- | --- | --- |
| 后端测试 | 1179 passed / 7 skipped | `main@7b17607` 全量 pytest | `PYTHONPATH=src python -m pytest tests/ -q` |
| 后端覆盖率 | 89.18% | line coverage，硬门禁 85% | `PYTHONPATH=src python -m pytest --cov=resualign --cov-fail-under=85 tests/` |
| 前端/扩展 | 553 passed | node:test | `node --test tests/frontend/*.test.mjs tests/frontend/dom/*.test.mjs tests/extension/*.test.mjs` |
| E2E | 7 passed | Playwright，假 LLM | `PYTHONPATH=src python -m pytest tests/e2e -q --e2e` |
| 熔断降级 | 5/5 trial 恰第 3 次熔断 | 本地故障注入，零外部模型 | `python benchmarks/degradation_benchmark.py --trials 5` |
| 容量曲线 | 拐点 = 并发 8，错误率 0 | CI Ubuntu 确定性 API 负载 | `python benchmarks/capacity_benchmark.py --check-baseline` |
| 冷启动 | 原生 p50 616.8ms / 容器 808.5ms UID 1000 | CI Ubuntu，空数据卷 | `python benchmarks/cold_start_benchmark.py --check-baseline` |
| 备份恢复 | 在线一致性备份 + 恢复演练 | 见 `backup-restore.md` | `scripts/backup.ps1` |

> CI 的 JUnit / coverage artifact 是**持续事实源**；上表是一次带 commit 与命令的
> 固定快照，不承诺自动跟随测试数量。

## 未达标红线

| 项 | 现状 | 为什么不刷绿 |
| --- | --- | --- |
| **探针线判据** | `dist_not_executed`：四渠道 outreach 0/4，`2026-09-23 24:00` 判定线已过 | 这是**分发未执行**，不是证伪；不换判、不改阈值（ADR-0042 决定 6f） |
| **自用线判据** | 1 / 3 合格例（09-15 狗食两跳链） | 需真实投递中跑满 3 例；合成例、截图、口头复述一律不计 |
| **B10 配置与密钥** | 2 分（主动取舍） | 项目选择「钳制、绝不 raise」（`api/state.py`），与标准「非法值启动期拒绝」方向相反；**不为评分改设计**（ADR-0054 决定 6） |
| **真实 LLM 端到端质量** | 9 月真实对齐 4/5 零产出（假成功主症状，见 #110） | 由 #115 归因与模型侧行为决定，不由容量/冷启动数字代表 |
| 浏览器探针 | Chromium 版本漂移曾致 E2E 假红 | 门禁已固定为 `chromium-1243`；属环境约束非产品缺陷 |

## 已知边界

- **规模**：单机 SQLite、单进程；不承诺生产规模与多实例部署。
- **LLM 依赖**：真实改写质量取决于所配模型；本地小模型（Ollama qwen2.5:7b）
  是已知能力地板。
- **爬虫**：后端抓取已退役，岗位来源依赖油猴插件或粘贴；不承诺任意站点抓取。
- **容量/冷启动数字**：来自 CI Ubuntu 的确定性 API 负载，**不代表真实 LLM
  端到端延迟**。

## 冻结策略与触发条件

**冻结令（ADR-0041 决定 1）仍然有效**：探针时钟出结论前，app 侧一切新功能冻结
——agent 化 Phase A/B、商业化 PRD、网申回填扩展期二、托管 demo/落地页、
批量体验债修复。总闸见 issue #114（`frozen`）。

**冻结期内允许的两类工作**

1. 地基线：#110（归因诊断，只读）、#111（无建议分型，裁决已录）。
2. 探针包：skill 探针发布票 + 90 秒视频票。

**唯一解冻条件**：探针判据「过」（4 周内 ≥5 例非作者首跑附门禁摘要行，
或 1 例外部完整合格链）→ 按 ADR-0041 决定 9 重新立项；「证伪」走决定 10 剧本
（含归档条款）。

**反规避**：把新功能包装成「地基」或「体验债」绕开本令的，评审一律以 #114 驳回。

**例外流程**：自用闭环的直接摩擦须**逐项**引用 ADR-0042 决定 6e 登记后施工
（范例见 ADR-0048）。
