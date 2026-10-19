# ADR-0060：缺口报告的关键词拆分（supported_keywords / missing_keywords）

日期：2026-10-19
状态：已采纳
关联：issue #164、#163、#159；ADR-0041 决定 11（漂移锁）；ADR-0059（app 自用优先）

## 背景

gap report 里的 `missing_keywords` 同时承担了两个相反的语义：

- 上游 `truetailor`（`SKILL.md`）定义为「JD 要求、**简历有证据但没写出来**」的词，
  因此 `gate.py::allowlist_corpus` 把它当作合法改写语料；
- app 的 `gap_analyzer.py` 定义为「JD 要求、**简历没有**」的真缺口。

同名不同义，直接后果是 app 把真缺口词灌进 allowlist，`gate_diff_items` 的
内容级校验放行「把 JD 缺口词写成自己的技能」。2026-10-19 腾讯用例实证：
`usable=2`，两条都是往技能清单里加 JD 术语——假通过，不是误杀。

## 决策

1. allowlist 语料只认 `supported_keywords`：JD 要求、简历原文**已有依据但没写明**
   的词。它是唯一允许「新术语」进入 `proposed` 的来源。
2. `missing_keywords` 语义固定为「JD 要求、简历原文**完全没有依据**」的真缺口，
   只用于诊断 / 评分 / UI / 改写方向提示，**永不进 allowlist**。
3. 两侧同步：上游 `gate.py::allowlist_corpus` 与 app `tailor.py::_gap_support_text`
   的键列表统一为 `supported_keywords / misaligned_emphasis / strength_matches /
   business_scenarios / jd_context`。
4. app 侧 `gap_analyzer` 与 `jd_analysis` 按此拆分产出两个字段，版本分别 bump 到
   `gap_analyzer/v3`、`jd-analysis-v4`；`tailor` 提示词同步 bump 到 `tailor/v4`。
5. 落地顺序固定为：上游 truetailor（gate + fixtures + SKILL/README/contract）→
   同步 vendor（`src/resualign/gate.py` + `tests/fixtures/gate/` + `VENDOR.json`）→
   重跑 parity（`tests/engine/test_gate.py::TestDriftLockParity` 与
   `tests/platform/test_skill_vendor_lock.py`）。ADR-0041 决定 11 不变。

## 后果

- 黄金场景 17 → 19：新增 `d11-` / `e8-missing-keyword-not-a-rewrite-source`，
  锁定「列在 `missing_keywords` 里的词仍被拦成 fabricated」。
- 假通过被根治：即使模型把 JD 缺口词写进简历，内容级校验也不再放行。
- 代价是编辑器可用语料变窄：`missing_keywords` 不再能当改写素材，必须真的产出
  `supported_keywords`，否则可改写项减少。这是刻意的 fail-closed 取舍。
- app 侧原有的中文缺口术语 guard 与 evaluator 逐条隔离保留，作为纵深防御。

## 未决

- `supported_keywords` 仍依赖模型自证「简历有依据」，gate 无法逐字验证。若要
  代码级验证，需要为每个 supported keyword 附简历锚点句（后续可选项，不在本
  ADR 承诺范围内）。
