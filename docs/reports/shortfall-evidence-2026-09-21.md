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
| B6 性能与容量 | 待补 | `benchmarks/capacity_benchmark.py` |
| B11 可部署与复现 | 待补 | `benchmarks/cold_start_benchmark.py` |

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
| 1 | 1, 2, 3 | 3 | 2343 |
| 2 | 1, 2, 3 | 3 | 2016 |
| 3 | 1, 2, 3 | 3 | 2016 |
| 4 | 1, 2, 3 | 3 | 1766 |
| 5 | 1, 2, 3 | 3 | 1875 |

恢复耗时 p50 = 2016 ms（Windows 交叉验证；正式环境为 Ubuntu CI）。
现有 `tests/test_llm_node_breaker.py` 等单测保留为语义契约，本脚本提供
“现场触发数字”，并作为 CI Stage 2 门禁（任一不变量失败即红）。
