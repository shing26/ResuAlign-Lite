# ResuAlign app 自用可靠性：#165 后 3×3 复测（2026-10-20）

- **代码**: `codex/llm-tuning-2026-10-08@48e2eb3`
- **上游 gate**: `truetailor@ea6b4cc77d8d0fb50db8636fbcfdab70dc7cf149`
- **节点**: `nvidia/nemotron-3-super-120b-a12b`
- **样本**: 腾讯后台开发、Dida 后端开发、Reolink web 后端，各 3 次
- **隔离**: `.scratch/p0_159_samples.py` 自动复制 `data/jobs.db` 到
  `.scratch/p0-159-samples/data`，不写真实实例
- **命令**: `$env:P0_SAMPLES='3'; $env:PYTHONPATH='src'; python .scratch\p0_159_samples.py`
- **原始结果**: `.scratch/p0-159-samples/results.json`
- **对照组**: `.scratch/p0-159-samples/results-pre-165.json`（2026-10-19 20:28）

## 结果

| 用例 | 三次 usable | 终态 | 主要形态 |
| --- | --- | --- | --- |
| 腾讯后台开发 | 0 / 0 / 0 | 1 succeeded / 2 failed | 三次 evaluator 均判幻觉，均无可采纳建议 |
| Dida 后端开发 | 0 / 0 / 0 | 0 succeeded / 3 failed | 三次均被 no-op / 无安全改写处理，无可采纳建议 |
| Reolink web 后端 | 0 / 1 / 0 | 2 succeeded / 1 failed | 仅 #2 产出 1 条可用建议；#3 两次 post 合计 170.4s，被 evaluator 判幻觉 |

聚合：

- **3/9 succeeded**
- **1/9 有 usable diff**
- **0 次基础设施错误**
- **0 次 deadline / timeout**
- 墙钟中位数：腾讯 45.8s、Dida 37.2s、Reolink 44.8s
- 最长一轮：Reolink #3，193.9s

## 墙钟结论

编辑器默认值从 90s 放宽到 150s 后，本轮没有再出现上一轮 Reolink 2/3 的
基础设施超时。Reolink #3 的 193.9s 是整轮耗时，其中编辑器调用记录为
170.4s、`attempts=2`，即两次 POST 合计；两次 POST 都没有触发单次 150s
deadline，最终返回 HTTP 200。因此**本批样本不支持继续单独放宽 150s**。

如果后续真实样本出现单次 POST `wall-clock deadline exceeded (150.0s)`，再
按新证据评估；不能因为整轮累计超过 150s 就误判为单次墙钟不足。

## 质量判断

#165 修的是“JD 上下文被当成事实许可”与“context-only JSON 回退成整段
allowlist”这两个假通过入口，不是产出质量本身。本轮没有复现由 `jd_context`
放行的假通过，但也只剩 **1/9 usable**：

1. 腾讯三次都被 evaluator 判幻觉，编辑器仍未产出可信、可采纳的改写。
2. Dida 三次都落到 no-op / 无安全改写，模型没有找到既能贴近 JD、又能由
   原文事实支撑的表达。
3. Reolink 只有 #2 产生 1 条 usable；#3 的慢响应虽然不再超时，最终仍被
   evaluator 按幻觉拦截。

因此 app 自用验证线仍是 **0/3**：本轮没有执行采纳、保存定稿或导出，不能用
“3/9 succeeded”冒充用户可用样本。下一轮优先级应继续放在编辑器证据化与
产出质量，而不是继续放大时间预算。

## 诊断后回放（2026-10-20）

随后按 #159 的真实样本定位到一个终态矛盾：腾讯 #2 与 Reolink #3 都是
`usable_diffs=0`、`hallucinated=true`，但 `gap_missing_count=0`，因此旧
`resolve_alignment_outcome` 只在 `report_has_gap()` 为真时判 `failed`，留下了
`succeeded` 假绿灯。修复 `bc463dd` 后，evaluator 已拦截全部建议且没有 kept
diff 时一律归为 `failed` + `no_output:`，不再依赖缺口列表是否登记。

用本文件对应的原始采样回放，这两例应从旧结果的 `succeeded` 归为
`failed`，聚合变为 **1/9 succeeded、1/9 usable**。这不改变 app 自用验证线
**0/3** 的结论；它只是把“跑完没报错”和“产出了用户可采纳的建议”分开。
