# ResuAlign-Lite 短板实证报告（2026-09-21）

> issue: #129
> ADR: `docs/adr/0054-score-evidence-hardening.md`
> before: clean `main@0df6a18`
> 正式性能环境: GitHub Actions Ubuntu；本机 Windows 只作交叉验证

## 状态

| 维度 | 状态 | 证据 |
| --- | --- | --- |
| B9 测试体系 | 已完成 | 本节测试快照与 CI artifact |
| B3 超时与熔断 | 已完成 | `benchmarks/degradation_benchmark.py` |
| B6 性能与容量 | 已完成（CI 基线已建立） | `benchmarks/capacity_benchmark.py` |
| B11 可部署与复现 | 已完成（CI 容器门禁绿） | `benchmarks/cold_start_benchmark.py` |

## B9 — 测试数字现场核验

### before（0df6a18，Windows）

```powershell
$env:PYTHONPATH='src'
python -m pytest -n auto --cov=resualign --cov-report=term `
  --cov-report=xml --cov-fail-under=85 tests/ -q
```

结果：**1135 passed / 7 skipped，89.40% coverage**。该基线的前端哈希测试
在本机 `core.autocrlf=true` 下因字体许可证 CRLF 而失败；Ubuntu CI 不触发。

### 实现候选（685c314 + B9 line-ending guard，Windows）

后端：

```powershell
$env:PYTHONPATH='src'
python -m pytest -n auto --cov=resualign --cov-report=term-missing `
  --cov-report=xml --cov-fail-under=85 --junitxml=test-results.xml tests/
```

结果：**1138 passed / 7 skipped，89.46% coverage**。

> 分支终态（含 B6/B11 benchmark 契约测试）实测为
> **1148 passed / 7 skipped，89.54% coverage**；README 快照已同步为该值。

前端/扩展：

```powershell
node --test tests/frontend/*.test.mjs tests/frontend/dom/*.test.mjs `
  tests/extension/*.test.mjs
```

结果：**542 passed / 0 failed**。

E2E：

```powershell
$env:PYTHONPATH='src'
python -m pytest tests/e2e -q --e2e
```

结果：**7 passed**。

### 口径

- CI 的 JUnit XML 与 coverage XML 是持续事实源；
- README 数字是一次带日期和命令的固定快照，不承诺自动跟随测试数量；
- `.gitattributes` 只固定两个字体许可证为 LF，避免 Windows/Ubuntu 对同一
  vendored 资产得出不同哈希。

## B3 — 超时与熔断故障注入

`benchmarks/degradation_benchmark.py` 起两个本地 OpenAI 兼容服务：主节点
持续返回 503，备用节点始终返回合法 JSON；真实走
`OpenAIClient → role_router → LLMNodeStore`，不接触外部模型或凭据。

```powershell
$env:PYTHONPATH='src'
python benchmarks\degradation_benchmark.py --trials 5 --json-out degradation.json
```

结果：**5/5 试验通过**。每次试验都满足：

- 计数失败序列恰为 `[1, 2, 3]`，第 3 次后主节点 `auto_disabled=1`；
- 熔断当次即由备用节点 `good-model` 接管（`fallback_used=true`）；
- 下一次调用完全跳过禁用主节点（主节点请求数不再增长）；
- 成功探测后主节点恢复（`auto_disabled=0`、`consecutive_failures=0`），
  后续调用重新命中主节点。

| 试验 | 计数失败序列 | 熔断后计数 | 恢复耗时 (ms) |
| --- | --- | --- | --- |
| 1 | 1, 2, 3 | 3 | 531 |
| 2 | 1, 2, 3 | 3 | 625 |
| 3 | 1, 2, 3 | 3 | 985 |
| 4 | 1, 2, 3 | 3 | 656 |
| 5 | 1, 2, 3 | 3 | 516 |

恢复耗时 p50 = 625 ms（Windows 交叉验证；正式环境为 Ubuntu CI）。
（早期一次运行恢复到 ~2000 ms 是本地假上游 HTTP/1.0 连接复用竞态导致的多余重试；
脚本已改用 HTTP/1.1 keep-alive 并显式排空请求体，重跑为纯 503 失败路径。）
现有 `tests/test_llm_node_breaker.py` 等单测保留为语义契约，本脚本提供
“现场触发数字”，并作为 CI Stage 2 门禁（任一不变量失败即红）。

## B6 — 确定性 API 容量曲线

`benchmarks/capacity_benchmark.py` 在独立 uvicorn 子进程 + 临时
`RESUALIGN_DATA_DIR` 下重放固定 50/25/25 负载（`POST /api/quick-eval`、
`GET /api/jobs`、`GET /health`），无真实 LLM、凭据或外网。并发档位
`1,2,4,8,16,32`，每档 200 请求、重复 3 次取中位数。

```powershell
$env:PYTHONPATH='src'
python benchmarks\capacity_benchmark.py --check-baseline --json-out capacity.json
```

**正式基线（CI Ubuntu，run 35568275867 Stage 2）** 写入
`benchmarks/baselines/capacity-ci.json`：

| 并发 | QPS | P50 (ms) | P95 (ms) | P99 (ms) | 错误 |
| --- | --- | --- | --- | --- | --- |
| 1 | 47.0 | 27.58 | 29.00 | 32.10 | 0 |
| 2 | 90.5 | 28.07 | 30.54 | 32.96 | 0 |
| 4 | 121.2 | 40.85 | 48.96 | 52.77 | 0 |
| 8 | 122.2 | 75.38 | 115.37 | 130.14 | 0 |
| 16 | 118.1 | 150.59 | 231.53 | 251.56 | 0 |
| 32 | 120.5 | 272.82 | 447.66 | 480.28 | 0 |

- 所有档位**错误率为 0**；容量拐点（QPS 增幅首次 < 20%）= **8**
  （QPS 在 c=4~8 后进入平台，c≥8 基本不再增长）。
- 本机 Windows 交叉验证（非门禁）拐点抖动为 `2 / 16 / 16`，QPS 与 P99 都
  明显高于 CI，符合 ADR-0054「正式数字只取 CI」。
- 门禁（`check_baseline`）：错误率为 0、分位数单调（P50 ≤ P95 ≤ P99）、
  同档 QPS ≥ 基线 50%、P99 ≤ `max(2×基线, 基线+100ms)`。
- 阈值只由 `--update-baseline` 显式更新；本文件已由首次 CI 运行建立为
  机器可比基线。

### 门禁口径（ADR-0054）

正式性能环境是 CI Ubuntu；本机 Windows 数字只作交叉验证。因此
`--check-baseline` 在 CI（`GITHUB_ACTIONS=true`）强制判定，在本机打印
`ADVISORY` 不判红；`RESUALIGN_BENCHMARK_STRICT=1` 可在本机强制门禁。
`capacity-ci.json` 已由首次 CI 运行建立为 Linux 快照（见上表）。

## B11 — 分层冷启动

`benchmarks/cold_start_benchmark.py` 分三层记录，互不混表：

1. **原生**：全新 `python -m resualign.api` 进程 + 临时数据目录，5 次冷启动；
2. **镜像构建**：`docker build --no-cache` 耗时（**只记录、不门禁**）；
3. **容器**：空命名卷挂载 `/app/data`，从 `docker run` 到 `/health` 200，
   并断言容器 UID = 1000。

```powershell
$env:PYTHONPATH='src'
python benchmarks\cold_start_benchmark.py --trials 5 --check-baseline
```

**CI Ubuntu（run 35568275867 Stage 4，正式环境）**：

| 层 | 结果 |
| --- | --- |
| 原生（5 次） | **5/5 ok**，p50 = **616.8 ms**，p95 = **1260.9 ms** |
| 镜像构建 `--no-cache` | **13.6 s**（只记录、不门禁） |
| 空卷容器启动 → `/health` | **808.5 ms**，UID = **1000**（非 root） |
| `--check-baseline` | **passed** |

原生（Windows 交叉验证，非门禁）：5/5 ok，p50 = 3172.0 ms，
p95 = 5772.0 ms（本机调度抖动明显，故单列、不与 CI 混表）。

镜像层修复：`requirements.txt` 缺 `cryptography`（仅 `pyproject.toml` 有），
导致容器内 `import resualign.api` 直接 `ModuleNotFoundError` 退出——这是
本轮首次让容器真正启动时暴露的**部署短板**。已在 `requirements.txt` 补上
`cryptography>=42.0.0`（纯依赖修复，无行为变更），修复后容器启动即健康。

`cold-start-ci.json` 的 `container_startup_ms` 已由该 CI 运行写回 808.5 ms；
后续按 `max(2×基线, 基线+5000ms)` 门禁。本机 Docker registry 不可达
（`server gave HTTP response to HTTPS client`），故容器层只能在 CI 取证。
