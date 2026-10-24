# 0064 — 确定性预匹配词面信号（prematch）

- **状态**: 已采纳
- **日期**: 2026-10-24
- **关联**: ADR-0061；ADR-0059（P0 自用线、P1 feature flag）；ADR-0060；PR #182（匹配质量指标）
- **上游**: 不涉及（`gate.py` vendor 锁不触碰）

## 背景

外部对比分析（2026-10-24，PR #182 核验）指出：改写端已有 provenance 硬门禁，
但**匹配端的可解释性依赖 LLM 的自然语言输出**，缺少结构化、可回归的确定性
信号（对标 ResumeLens 的多信号融合）。同时工作台编辑器 prompt 的 JD 上下文
只有 `jd_context_summary()` 从 JDProfile/GapReport 摘出的结构化字段，没有
任何「简历 ↔ JD 词面重叠」的确定性信号。

约束（不可放松）：

1. ADR-0061：`jd_context` 永不进入 allowlist/内容级校验；摘要**不得包含
   `jd_text` 与 `missing_keywords`**，避免把真缺口重新灌进编辑器提示。
2. ADR-0041 决定 11：`gate.py` 是 vendor 锁副本，本决策零触碰。
3. 本地优先：不引入新依赖（不上向量库/嵌入服务）、零网络。

## 决策

1. 新增领域模块 `src/resualign/prematch.py`：纯 stdlib 的确定性词面信号——
   精选**技能别名词典**（k8s→kubernetes、ts→typescript 等，宁缺毋滥，
   只收无歧义词）+ 词边界正则检测 + 命中重叠率。分词只处理 ASCII 词
   （技术 JD 的技能名以 ASCII 为主），不做 CJK 分词。
2. 信号恰好两个消费者：
   - `jd_context_summary(..., prematch=…)`：编辑器 prompt 的一行
     「匹配信号：命中核心技能 X、Y（n/m）」——**只含简历有据词**
     （resume ∩ JD，与 supported_keywords 同类）；JD-only 词与
     `missing_keywords` 一样**禁止**进入该行。300 字预算不变。
   - 后续 UI 可解释性展示（岗位卡重叠徽章等）——本 ADR 只定接口，
     UI 实现另行落地。
3. **永不进入** allowlist / 内容级校验 / gate.py。信号可以影响措辞方向，
   不能让任何 JD 术语变成已验证事实（与 ADR-0061 第 5 条同语义）。
4. 默认开启；`RESUALIGN_PREMATCH=0`（或 false/no/off）一键关闭，
   关闭时两个调用方跳过信号计算，行为与 0064 之前完全一致。
5. 两个注入点：`engine.run` 的编辑器 prompt 与工作台单条重写
   （`api/routers/jobs.py::rewrite_workbench_bullet`）。计算失败或字段
   缺失时一律静默降级为无信号，绝不阻断主流程。

## 后果

- 编辑器 prompt 多一行**简历有据**的词面信号（可影响措辞方向，不改变
  事实边界）；`missing_keywords` 与 JD-only 词仍然进不来，fail-closed
  语义不变。
- 匹配端多一个**可回归的确定性信号**：`compute_match_signals` 输出可
  直接进 benchmark 断言（与 PR #182 的作者标注指标互补但不混淆——
  词面重叠 ≠ 匹配等级）。
- 别名词典的词表维护成为长期小事：新词条走普通 PR + 单测
  （误报案例进 `tests/domain/test_prematch.py`）。
- 明确不做：嵌入向量/向量库（违背零依赖）、技能图谱数据库（过度设计）、
  全自动岗位排序（与「受控」定位冲突，见 ADR-0059）。

## 验证

- `tests/domain/test_prematch.py`：别名与词边界（js 不命中 json）、
  多词技能、JD-only 不进信号行、`jd_context_summary` 预算与
  missing_keywords 排除、开关行为。
- `modgraph --check`：`prematch` 登记「领域」层，零外向依赖。
