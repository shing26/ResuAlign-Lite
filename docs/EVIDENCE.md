# ResuAlign 证据台账

> 一句话规则：**每个数字一行，读数 · 口径 · 复现命令 · 判据 · 达标否。**
> 判据缺失的一律写「记录值（无判据）」——记录不等于达标。
>
> 正式性能环境是 **GitHub Actions Ubuntu**；本机 Windows 数字只作交叉验证，
> 分表记录、不与 CI 混表（ADR-0054 决定 1）。

## 测试与覆盖率

| 读数 | 口径 | 复现命令 | 判据 | 达标否 |
| --- | --- | --- | --- | --- |
| 1179 passed / 7 skipped | `main@7b17607` 全量 pytest（固定快照，2026-09-25） | `PYTHONPATH=src python -m pytest tests/ -q` | 退出码 0 | ✅ |
| 89.18% line coverage | `--cov=resualign` | `PYTHONPATH=src python -m pytest --cov=resualign --cov-fail-under=85 tests/` | ≥85% | ✅ |
| 553 passed | 前端 + 扩展 node:test | `node --test tests/frontend/*.test.mjs tests/frontend/dom/*.test.mjs tests/extension/*.test.mjs` | 退出码 0 | ✅ |
| 7 passed | Playwright E2E（假 LLM，自启自停） | `PYTHONPATH=src python -m pytest tests/e2e -q --e2e` | 退出码 0 | ✅ |
| 1186 collected | tests/ 分层后的收集数 | `PYTHONPATH=src python -m pytest tests/ --collect-only -q` | 与用例数一致 | ✅ |

> CI 的 JUnit XML / coverage XML artifact 是**持续事实源**；上表是一次带日期与
> 命令的历史快照。

## 超时与熔断（B3）

装置：`benchmarks/degradation_benchmark.py` 起两个本地 OpenAI 兼容上游（主节点
持续 503、备用节点健康），真实走 `OpenAIClient → role_router → LLMNodeStore`，
零外部模型与凭据。

| 读数 | 口径 | 复现命令 | 判据 | 达标否 |
| --- | --- | --- | --- | --- |
| 5/5 trial 通过 | 每 trial 独立库 + 独立上游 | `PYTHONPATH=src python benchmarks/degradation_benchmark.py --trials 5` | 全部不变量成立 | ✅ |
| 计数失败序列 `[1,2,3]` | 连续计数失败 | 同上 | 恰第 3 次后 `auto_disabled=1` | ✅ |
| 熔断当次备用接管 | `fallback_used=true` | 同上 | 主节点禁用即回退 | ✅ |
| 禁用节点不再被调用 | 主节点请求数不再增长 | 同上 | 后续调用跳过 | ✅ |
| 恢复耗时 p50 = 625 ms | Windows 交叉验证（非门禁） | 同上 | 成功探测后 `auto_disabled=0` | ✅ |
| 阈值 = 3 次 | `llm_nodes` 迁移 5 | `PYTHONPATH=src python -m pytest tests/engine/test_llm_node_breaker.py -q` | 语义契约 | ✅ |

## 性能与容量（B6）

装置：`benchmarks/capacity_benchmark.py` 独立 uvicorn 子进程 + 临时
`RESUALIGN_DATA_DIR`，固定负载 50% `POST /api/quick-eval` / 25% `GET /api/jobs`
/ 25% `GET /health`，无真实 LLM。并发档 `1,2,4,8,16,32`，每档 200 请求 ×3 取中位数。

**正式基线（CI Ubuntu，写入 `benchmarks/baselines/capacity-ci.json`）**

| 并发 | QPS | P50 (ms) | P95 (ms) | P99 (ms) | 错误 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 47.0 | 27.58 | 29.00 | 32.10 | 0 |
| 2 | 90.5 | 28.07 | 30.54 | 32.96 | 0 |
| 4 | 121.2 | 40.85 | 48.96 | 52.77 | 0 |
| 8 | 122.2 | 75.38 | 115.37 | 130.14 | 0 |
| 16 | 118.1 | 150.59 | 231.53 | 251.56 | 0 |
| 32 | 120.5 | 272.82 | 447.66 | 480.28 | 0 |

| 读数 | 口径 | 复现命令 | 判据 | 达标否 |
| --- | --- | --- | --- | --- |
| 拐点 = 并发 8 | QPS 增幅首次 < 20% | `PYTHONPATH=src python benchmarks/capacity_benchmark.py --check-baseline` | 曲线进入平台 | ✅ |
| 全档错误率 0 | 5xx / 连接失败计数 | 同上 | 必须为 0 | ✅ |
| P50 ≤ P95 ≤ P99 | 分位数单调 | 同上 | 单调 | ✅ |
| 同档 QPS ≥ 基线 50% | 与提交基线比 | 同上 | ≥50% | ✅ |
| P99 ≤ max(2×基线, 基线+100ms) | 与提交基线比 | 同上 | 不超阈 | ✅ |

> 基线只能由显式 `--update-baseline` 更新，阈值不因一次失败静默放宽。
> 本机 Windows 交叉验证拐点抖动为 `2 / 16 / 16`，QPS 与 P99 明显高于 CI，
> 符合「正式数字只取 CI」。

## 可部署与复现（B11）

装置：`benchmarks/cold_start_benchmark.py` 分三层记录，互不混表。

| 读数 | 口径 | 复现命令 | 判据 | 达标否 |
| --- | --- | --- | --- | --- |
| 原生 5/5 ok，p50 616.8 ms / p95 1260.9 ms | CI Ubuntu，全新进程 + 临时数据目录 | `PYTHONPATH=src python benchmarks/cold_start_benchmark.py --trials 5 --check-baseline` | 5/5 且 p95 进基线 | ✅ |
| 镜像构建 13.6 s | `docker build --no-cache` | 同上 | 只记录、不门禁 | 记录值（无判据） |
| 空卷容器启动 808.5 ms | `docker run` → `/health` 200 | 同上 | 进提交基线，按 `max(2×基线, 基线+5000ms)` 门禁 | ✅ |
| 容器 UID = 1000 | 非 root | 同上 | 必须为 1000 | ✅ |
| 原生 Windows p50 3172 ms | 交叉验证（非门禁） | 同上 | 单列、不混表 | 记录值（无判据） |

> 部署短板：`requirements.txt` 曾缺 `cryptography`（仅 `pyproject.toml` 有），
> 导致容器 `import resualign.api` 即 `ModuleNotFoundError`。已补依赖，纯修复无行为变更。

## 可观测性

| 读数 | 口径 | 复现命令 | 判据 | 达标否 |
| --- | --- | --- | --- | --- |
| 错误体全 JSON + `request_id` | #100 错误契约 | `PYTHONPATH=src python -m pytest tests/api/test_error_contract.py -q` | 形状锁定 | ✅ |
| request_id 贯穿 job/llm 日志 | #101，`jobs` 迁移 3 | `PYTHONPATH=src python -m pytest tests/observability/test_request_id_flow.py -q` | 同一 id | ✅ |
| watchdog 1800s | #102，`RESUALIGN_JOB_MAX_RUNTIME_S` | `PYTHONPATH=src python -m pytest tests/api/test_watchdog.py -q` | 超时翻 failed | ✅ |
| 熔断阈值 3 | #103，`llm_nodes` 迁移 5 | `PYTHONPATH=src python -m pytest tests/api/test_llm_node_breaker.py -q` | 语义契约 | ✅ |

## 数据一致性与并发

| 读数 | 口径 | 复现命令 | 判据 | 达标否 |
| --- | --- | --- | --- | --- |
| WAL 并发 0 失败 | 多线程写同一 store | `PYTHONPATH=src python -m pytest tests/storage/test_wal_concurrency.py -q` | 无错误 | ✅ |
| 租户隔离互不相交 | 8 线程并发 | `PYTHONPATH=src python -m pytest tests/api/test_concurrency_tenant.py -q` | id 不相交 | ✅ |
| 备份一致性 | 在线备份，服务可运行 | `powershell -File scripts\backup.ps1` | 恢复演练通过 | ✅ |

## 项目评分

| 读数 | 口径 | 复现命令 | 判据 | 达标否 |
| --- | --- | --- | --- | --- |
| 79/81（97.53%） | 《项目开发判断标准-三维度评分体系-20260920》，后端表，基线 `c7e3caf` | `python D:\WorkBuddyData\项目评估结果\_tools\score.py` | P0 全 ≥2 | ✅ 合格 · 优秀 |
| B3/B6/B9/B11 各 3 分 | ADR-0054 补齐后重评分（20260928-后端-431790b9） | 同上 | 四项跃迁 | ✅ |
| B10 = 2 分 | 主动取舍，不为评分改设计 | 同上 | 接受 | 记录值（接受取舍） |

## 探针与分发（未达标）

| 读数 | 口径 | 复现命令 | 判据 | 达标否 |
| --- | --- | --- | --- | --- |
| 四渠道 0/4 | ADR-0042 决定 1 的四条 outreach | `gh api repos/shing26/truetailor` | 全发出 = 时钟起点 | ❌ `dist_not_executed` |
| discussions 1 / comments 0 / 0★ | truetailor 曝光侧 | `gh api graphql -f query='{repository(owner:"shing26",name:"truetailor"){discussions{totalCount}}}'` | 探针线 ≥5 例非作者首跑 | ❌ PENDING |
| 自用线 1/3 合格例 | 合格例取证 JSONL | `round`/`trigger`/`chain`/`resume_sha256` | ≥3 例 | ❌ 需 2 例 |

> 这三行是**未达标**，如实登记，不通过改口径或阈值刷绿。

## 复现总入口

```powershell
$env:PYTHONPATH = "D:\ResuAlign-Lite\src"

# 测试与覆盖率
python -m pytest tests/ -q
python -m pytest --cov=resualign --cov-fail-under=85 tests/
node --test tests/frontend/*.test.mjs tests/frontend/dom/*.test.mjs tests/extension/*.test.mjs
python -m pytest tests/e2e -q --e2e

# 三类 benchmark 门禁
python benchmarks\degradation_benchmark.py --trials 5
python benchmarks\capacity_benchmark.py --check-baseline
python benchmarks\cold_start_benchmark.py --trials 5 --check-baseline
```

CI（`.github/workflows/ci.yml`）四阶段复跑同一组命令；JUnit/coverage artifact
是持续事实源。
