# app 自用线：3 份真实 JD 闭环验证（2026-11-21）

对照 ADR-0059 通过线：3 份作者真实投递过的不同 JD，每份至少采纳 1 条
并保存定稿，至少 2 份导出或记录投递。本轮 **3/3 达成**，全部走真实
LLM（nvidia · `nvidia/nemotron-3-ultra-550b-a55b`，探活 3.1s ok）。

## 结果

| JD | job_id | 主简历 | usable | 采纳 | 定稿 | 导出 |
| --- | --- | --- | --- | --- | --- | --- |
| 腾讯 后台开发（2026-09-19 已投递） | `bcb5d7bb` | `7cefa4b1`（Java 全栈/后端，fine） | 3 | **3** | v4 | `export-tencent.md` |
| Dida 嵌入式软件工程师 | `c132fa2c` | `134ebf1e`（AI 应用/Agent，medium） | 1 | 1 | v1 | `export-dida.md` |
| Reolink web 前端工程师 | `76e52224` | `134ebf1e`（AI 应用/Agent，medium） | 3 | 1 | v1 | `export-reolink.md` |

定稿 sha256 与逐阶段证据见 `.scratch/selfuse-20261121/evidence.jsonl`
（start / queued / pipeline_done / accepted / final_draft_saved / exported）。
导出件为 `POST /api/jobs/{id}/exports` 真实产物，meta 携带定稿版本与
sha256。

## 过程要点

1. 腾讯首次（medium + `134ebf1e`）`usable=0`：缺口词（C/C++、Go 等）
   在简历无事实支撑，编辑器按零幻觉护栏拒绝编造——护栏行为正确，非故障。
   换 Java 主简历 + fine 后 3 条可用。
2. 腾讯采纳时暴露 **P1 bug**：编辑器把多行 bullet 的 `\n` 折叠为空格，
   `_apply_diffs` 的 `original in draft` 精确匹配必然失配，
   `accepted_count=0`（建议看得见、采纳不了）。已走验收链路修复
   （契约 `plans/adopt-multiline-diffs-2026-11-21.md`：空白容错回退匹配），
   重放后 `accepted_count=3`。
3. Dida / Reolink 一次跑通；Reolink 3 条可用中 1 条落地
   （其余 2 条为多行块，修复前仅单行 bullet 能匹配）。

## 结论

- ADR-0059 app 自用线 **3/3 通过**：本轮起新工作台不再触发「不过线回旧版」。
- 模型节点 `nemotron-3-ultra` 下 3 跑 3 产出（0 次基础设施错误、0 deadline），
  与 2026-10 `nemotron-3-super` 的 1/9 usable 相比是节点升级带来的质变。
- 遗留：多行采纳修复待 Verifier 签收后随下次提交入库；`accepted_count`
  语义（按命中数计）已在 `docs/reports` 留痕。
