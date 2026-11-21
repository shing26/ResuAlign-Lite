# 验收契约：adopt-multiline-diffs-2026-11-21

- 任务：修复多行 modify 建议无法采纳（original 换行被折叠为空格）
- 基线 HEAD：`bbd80926f5566f6a1a4c1f286adea06d096916db`
- 风险分级：业务逻辑（采纳链路），走完整链路。

## 问题证据（真实自用跑批 2026-11-21）

- 腾讯后台开发 `bcb5d7bb`，分析任务 `a0900333`（nvidia nemotron-3-ultra）：
  `usable_diffs=3`，`POST /workbench/accept` 返回 `accepted_count=0`。
- 根因：编辑器产出的多行 `original` 把 `\n` 折叠为空格
  （720 字符块内 4 处 `\n`→空格），`_apply_diffs` 用 `original in draft`
  精确匹配必然失配；建议看得见、采纳不了（与 2026-10-26 P2 同类）。

## Allowed paths

- `src/resualign/api/services/workbench.py`
- `tests/engine/test_tailor.py`（仅追加用例）
- `plans/adopt-multiline-diffs-2026-11-21.md`
- `docs/EVIDENCE.md`（仅追加证据段）

## 契约

1. `_apply_diffs` 对 `modify`：先保留现有 `original in draft` 精确匹配；
   失配时改用空白容错匹配——把 `original` 中的连续空白（含 `\n`）当作
   任意空白串在 draft 中定位唯一 span，命中则用 `proposed` 原文替换该
   span。两轮匹配仍失配才跳过（applied 不计数）。
2. `add`/`remove` 行为不变；`proposed` 的占位剥离不变；顺序与去重不变。
3. 匹配到多个 span 时取第一个，不报错。

## Acceptance criteria

1. 新增用例：多行 diff（original 含空格折叠、draft 含换行）→
   `applied=1` 且 draft 中 `proposed` 出现、`original` 首行不再出现。
2. 既有 `tests/engine/test_tailor.py` 全绿；`tests/api/test_job_api.py`
   全绿。
3. 真实复跑：腾讯岗位 accept 返回 `accepted_count>=1`，保存定稿并导出。

## Verification commands

```powershell
cd D:\ResuAlign-Lite
git rev-parse HEAD; git status --short
$env:PYTHONPATH='D:\ResuAlign-Lite\src'
python -m pytest tests/engine/test_tailor.py tests/api/test_job_api.py -q
```

## Forbidden

- 改/删/弱化既有测试断言换通过
- 修改 `gate.py` / vendor fixtures / OpenAPI 快照
- 提交、建分支、推送

## 签收记录

- 2026-11-21 独立 Verifier **ACCEPT**（HEAD `bbd8092`，服务 PID 28788）：
  98 passed / exit 0；`tests/engine/test_tailor.py` diff 纯追加 22 行；
  `gate.py`/contracts 零 diff；真实复跑 accept `accepted_count=3`、
  腾讯定稿 v4（sha256 `81b23ede…`）。P2 留观：`final-draft` 端点允许
  `accepted_count=0` 落库（腾讯 v3 即修复前空采纳版本），历史可能混入
  未采纳版本，后续单独评估。
