# 角色级超时校准（P4）

日期：2026-10-09

## 结论

本轮保留 `_ROLE_TIMEOUT_DEFAULTS` 现有数值：

| 角色 | 当前超时 | 120B p95 | 余量 |
| --- | ---: | ---: | ---: |
| diagnose | 45.0 s | 5.888 s | 39.112 s |
| profiler | 75.0 s | 2.656 s | 72.344 s |
| gap_analyzer | 60.0 s | 4.104 s | 55.896 s |
| editor | 90.0 s | 3.987 s | 86.013 s |
| evaluator | 60.0 s | 2.632 s | 57.368 s |

120B 节点在这组短输入上远快于当前超时，但没有足够证据支持下调：
本地 `qwen2.5:7b` 的历史 p95 为 61.7 s（见 `role_router.py` 的 #116
注释），profiler/gap 的 75 s/60 s 预算正是为慢模型和长输出保留的。
只凭一个快节点下调，会把本地 fallback 和长简历编辑重新推回超时风险。

## 测量环境

| 项 | 值 |
| --- | --- |
| 模型 | `nvidia/nemotron-3-super-120b-a12b` |
| 供应商 | NVIDIA integrate API |
| 节点来源 | 本机 `data/jobs.db` 的 active 节点，复制到临时 store 后测量 |
| commit | `d2f43fa8d3d1b65a3a835ee036fa08817da2f60c` |
| 平台 | Windows 10，Python 3.11.9 |
| 样本 | 每角色 5 次 |
| 结果 | 5/5 全部成功，无 fallback |

## 复现

```powershell
$env:PYTHONPATH='src'
python benchmarks\role_latency_benchmark.py --samples 5 --json-out role-latency.json
```

脚本读取配置节点后复制到临时 `LLMNodeStore`，因此校准失败不会改动正式
节点的 breaker 状态。输出 JSON 包含 `schema_version`、`generated_at`、
`git_sha`、`platform`、`python`、`command`、每角色 p50/p95/p99、
当前 timeout、余量和 verdict。

## 边界

1. 输入是短合成样例，editor 没有覆盖长简历和 `max_tokens=3072` 的最坏情况；
   这些数字应视为下界。
2. 只测了当前 active 的 120B 远程节点，没有覆盖本地 Ollama 的冷启动和
   网络抖动。
3. 该脚本需要真实模型，不进入 CI 门禁；正式环境数字仍以 CI Ubuntu 为准。
4. 若后续要下调默认超时，需要新的 ADR/用户裁决，并同时覆盖慢节点和长输入。
