# ResuAlign-Lite 短板实证加固计划

> 依据：`ADR-0054-score-evidence-hardening.md` 与 GitHub issue #129。
> before：clean `main@0df6a18`。
> 性质：一次性执行计划；完成后归档进 `docs/plans/`，实测数字进入
> `docs/reports/shortfall-evidence-2026-09-21.md`。

## 1. 目标与边界

按 `B9 → B3 → B6 → B11` 补齐四类证据：

| 维度 | 目标 | 实现证据 |
| --- | --- | --- |
| B9 | 2→3 | clean 测试快照 + CI JUnit/coverage artifact |
| B3 | 2→3 | 本地故障注入的熔断、接管、恢复数字 |
| B6 | 2→3 | P50/P95/P99 + 并发→QPS 曲线与拐点 |
| B11 | 2→3 | 原生冷启动 + 无缓存构建 + 容器启动耗时 |

B10 继续保持 2 分并记录“接受低分”的理由。本计划不新增产品或 API 功能。

## 2. 交付结构

- 分支：`codex/shortfall-evidence-hardening`
- 基线：`0df6a18`
- issue：#129
- PR：一个 umbrella PR，包含 ADR/计划前置提交与四个独立实现提交
- 生成型 benchmark JSON 不入库；持久证据只保留基线快照和人工报告

## 3. 执行顺序

### 3.1 B9 — 测试数字可信度

命令：

```powershell
$env:PYTHONPATH='src'
python -m pytest -n auto --cov=resualign --cov-report=term-missing `
  --cov-report=xml --cov-fail-under=85 --junitxml=test-results.xml tests/
node --test tests/frontend/*.test.mjs tests/frontend/dom/*.test.mjs `
  tests/extension/*.test.mjs
python -m pytest tests/e2e -v --e2e
```

证据：

- 后端 passed/skipped；
- 覆盖率；
- 前端/扩展 passed；
- E2E 结果；
- commit、平台、日期与命令。

README 只记录一次带 commit/日期的固定快照，并声明 CI artifact 是持续事实源。

### 3.2 B3 — 故障注入

新增 `benchmarks/degradation_benchmark.py`：

- 本地坏上游持续返回 503；
- 本地好上游返回有效 OpenAI-compatible JSON；
- 真实调用链：`OpenAIClient`、`role_router`、`LLMNodeStore`；
- 5 个 trial；
- 断言主节点在第 3 次计数失败后熔断、备用接管、禁用节点不再被选择、
  探测成功后恢复；
- JSON 记录触发次数、恢复耗时与结果。

拒绝条件：任一 trial 出现第 2 次即熔断、未接管、仍调用禁用节点或不能恢复。

### 3.3 B6 — 容量曲线

新增 `benchmarks/capacity_benchmark.py`：

- 自启独立 uvicorn，使用临时数据目录；
- 负载比例 50% quick-eval / 25% jobs / 25% health；
- 并发放 `1,2,4,8,16,32`，必要时 64；
- 每档 200 请求，3 次 trial 取中位数；
- 输出 overall + per-endpoint P50/P95/P99、QPS、errors、knee；
- 将 CI 标准值写入 `benchmarks/baselines/capacity-ci.json`；
- CI 使用 `--check-baseline`，不在失败时自动改基线。

### 3.4 B11 — 冷启动

新增 `benchmarks/cold_start_benchmark.py`：

- 原生模式：5 次新进程、新临时数据目录，spawn→`/health`；
- Docker 模式：测量 `docker build --no-cache`，再测空数据卷容器启动；
- 验证容器 UID 1000；
- 基线写入 `benchmarks/baselines/cold-start-ci.json`；
- CI 构建时间只记录，启动时延参与回归门禁。

## 4. 验收

- B9：README 与 clean 实测一致；覆盖率 ≥85%；前端/扩展、E2E 全绿。
- B3：5/5 trial 恰好第 3 次成功触发熔断并完成接管和恢复。
- B6：所有档位错误率为 0，分位数单调，曲线和拐点进入证据报告，CI 基线
  比较通过。
- B11：原生 5/5 成功；容器 UID、健康检查、构建和启动数字完整；CI 基线
  比较通过。
- 回归：ruff、modgraph、后端全量、前端/扩展、benchmark、Playwright/E2E。
- OpenAPI 快照不变。
- 重新评分后 B3/B6/B9/B11 均为 3 分，B10 为 2 分，总分 `79/81`。

## 5. 回滚

- B9：只回滚 README 与报告，无运行时影响。
- B3：移除 benchmark 脚本、测试与 CI step。
- B6：移除脚本、基线与 CI step。
- B11：移除脚本、基线与容器 job。

四个实现提交不得互相依赖；回滚任一项不得要求修改另外三项的代码。
