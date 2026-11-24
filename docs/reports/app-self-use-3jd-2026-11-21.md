# app 自用线：2026-11-21 跑批复核（正式 1/3 + 2 份技术旁证）

> **2026-11-25 复核更正**：本报告初版写「ADR-0059 通过线 3/3 达成」，经库内
> 状态与预注册口径核对后**不成立**，已下调。正式判据仍是 **1/3**（只有腾讯
> 一份可计入），Dida / Reolink 两份降级为「技术可行性旁证」，不计入 P0。
> 更正依据见「方法偏差」与「复核结论」两节；初版结论请勿再引用。

对照 ADR-0059 通过线：3 份作者**真实投递过**的不同 JD，每份至少采纳 1 条
并保存定稿，至少 2 份导出或记录投递。本轮跑批的真实情况是：3 份 JD 都
走完了「对齐 → 采纳 → 定稿 → 导出」，但**只有 1 份满足输入条件**。

全部走真实 LLM（nvidia · `nvidia/nemotron-3-ultra-550b-a55b`，探活 3.1s ok）。

## 结果

| JD | job_id | 投递状态（库内） | 主简历 | usable | 采纳 | 定稿 | 导出 | 是否计入 P0 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 腾讯 后台开发 | `bcb5d7bb` | `applied` · 2026-09-19 | `7cefa4b1`（Java 全栈/后端，fine） | 3 | **3** | v4 | `export-tencent.md` | ✅ 正式样本 |
| Dida 后端开发（深圳创新实验室） | `c132fa2c` | **`draft` · `applied_at=null`** | `134ebf1e`（AI 应用/Agent，medium） | 1 | 1 | v1 | `export-dida.md` | ❌ 未投递，旁证 |
| Reolink web 后端 | `76e52224` | **`draft` · `applied_at=null`** | `134ebf1e`（AI 应用/Agent，medium） | 3 | 1 | v1 | `export-reolink.md` | ❌ 未投递，旁证 |

只读核对（`data/jobs.db`，`mode=ro`，2026-11-25）：

- `status='applied'` 共 4 行，其中 3 行是 7 字测试夹具（`bdff6bc9` /
  `96772f88` / `5fc6a5d9`），唯一真实投递是腾讯 `bcb5d7bb`。
- Dida / Reolink 始终是 `draft`、`applied_at` 为空；作者已在
  `docs/plans/p0-app-self-use-runbook-2026-10-27.md` 与 issue #168 中**两次
  确认二者未实际投递、永久排除、不得回填**。

## 方法偏差（为什么这轮不能算 3/3）

1. **输入不合规**：ADR-0059 §3 与 runbook §0 都把「作者真实投递过的 JD」作为
   输入前提。Dida / Reolink 未投递，用它们凑数等同于「用未投递 JD 凑数」，
   而 runbook 明文禁止。
2. **代点违反硬边界**：本轮由 `.scratch/selfuse-3jd-run.py` 自动调用
   `POST /workbench/accept`、`POST /final-draft`、`POST /exports`，并自动
   全选可用建议（`usable = [...]` → `indices = [...]`）。runbook §0/§4 规定
   「采纳、保存定稿、导出、记录投递必须由作者本人在 UI 完成；agent 只做隔离
   与取证——**代点等于自证，判据作废**」。所以即使输入合规，这轮也不能计入。
3. **证据字段缺口**：`evidence.jsonl` 中三处 `final_draft_saved` 的
   `final_draft_version` 均为 `null`，而库内实际为 v4 / v1 / v1。原因是保存
   路由返回的键是 `version`（`job_library.save_final_draft` 返回
   `{"draft","version","version_id","sha256",...}`），脚本按
   `final_draft_version` 取值必然拿到 `None`。初版报告直接写了 v4/v1/v1，
   属于**证据与报告不对应**，且未登记该不一致。

## 技术结论（保留，但标注为非 P0 证据）

以下三条是这轮跑批仍然有效的技术信息，与判据无关：

1. **腾讯首次零产出是护栏正确行为**：medium + `134ebf1e` 时
   `usable_diffs=0`（`alignment_reason=model_failed`），缺口词（C/C++、Go）
   在简历无事实支撑，编辑器按零幻觉护栏拒绝编造。换 Java 主简历 + fine 后
   3 条可用。
2. **多行采纳 P1 真实存在且已修**：编辑器把多行 bullet 的 `\n` 折叠为空格，
   `_apply_diffs` 的 `original in draft` 精确匹配必然失配，首次 accept
   `accepted_count=0`；空白容错回退修复后 `accepted_count=3`。契约
   `plans/adopt-multiline-diffs-2026-11-21.md`，独立 Verifier ACCEPT
   （98 passed）。
3. **节点能力有量级提升**：`nemotron-3-ultra` 下 3 跑 3 产出（0 次基础设施
   错误、0 deadline），对比 2026-10 `nemotron-3-super` 的 1/9 usable。
   这是「换个更强节点能否稳定出建议」的正向信号，但不是「自用闭环已过线」。

## 复核结论

- ADR-0059 app 自用线：**正式样本 1/3**（腾讯），未过线。新工作台的回退
  开关继续保留，issue #168 保持 `needs-info`。
- 2026-11-21 这轮的真实价值是「技术旁证 + 一个 P1 修复」，不是验收通过。
- 解除阻塞的条件不变：出现另外 **2 份不同且作者真实投递过的 JD（附投递
  日期）**，由作者本人在 UI 完成采纳/定稿/导出后重跑。

证据文件（本地、未入库）：`.scratch/selfuse-20261121/evidence.jsonl`、
`export-{tencent,dida,reolink}.md`。引用时请同时说明 `final_draft_version`
字段缺口。
