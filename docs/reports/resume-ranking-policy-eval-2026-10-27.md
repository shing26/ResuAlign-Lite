# 简历 × 岗位排序：政策标签评测（2026-10-27）

- **关联**: ADR-0065（决策 4 与「标注协议修订（2026-10-27）」）；issue #196
- **状态**: 一次性评测报告（判据按政策口径判定）
- **数据**: 本地 `data/jobs.db`（租户 `local`，真实岗位 329 条）

## 1. 为什么要用政策标签

原计划是作者逐条标注 40–60 条 × 2 份简历。实测人工标注表 0/50，三个自动替代源
都不成立：

| 来源 | 实测 | 结论 |
| --- | --- | --- |
| `jd_text` 历史结论 | 高精度抽取 71 正 / 7 负；50 样本内 10 正 / 0 负 | 无负例 → P@10 失效 |
| `workbench_resume_id` | 225 个对齐岗位里 216 个绑同一份简历 | 默认值，非选择 |
| `applications` / 采纳 | 2 / 3 条 | 样本不足 |

因此改用**作者口述政策**生成标签（`benchmarks/make_policy_labels.py`）：

> 只投 后端 / 算法 / 数据 / 测试开发；运营 / 销售 / 外包不投；实习也投。

## 2. 方法

- **标签**：`job_function∈{后端,算法,数据,测试}` 且非外包 → 1；`{产品,运营,前端,运维,架构,其他}`
  或含外包词 → 0；未分类 96 条排除。标签与简历无关、与两个 ranker 均无共享信号。
- **集合**：full = 233 条（198 正 / 35 负，正例 85%，P@10 必然饱和）；balanced =
  35 负 + 35 确定性抽样正例（随机基线 P@10 = 50%）。**判据在 balanced 上判定。**
- **模型**：本地 Ollama `bge-m3`，1024 维，batch 16，超长文本递归切分 + 长度加权池化。
- **对比**：time_order 基线 / keyword（`prematch` 词面重叠）/ vector（余弦）/ RRF(k=60)。
- **指标**：P@10（主）、recall@10、nDCG@10、MRR、延迟。

## 3. 结果

balanced（35 正 / 35 负）：

| 简历 | time_order | keyword | vector | RRF | vector Δ | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| A（AI 应用/Agent） | 0.600 | **0.200** | **0.800** | 0.400 | **+60.0 pp** | ✅ ≥ +10pp |
| B（Java 全栈） | 0.600 | **0.400** | **0.900** | 0.900 | **+50.0 pp** | ✅ ≥ +10pp |

full（233 条，饱和交叉检查）：A keyword 0.600 → vector 1.000（+40.0 pp）；
B keyword 1.000 → vector 1.000（0.0 pp，饱和）。

工程读数：建库 341 ms/doc（balanced）/ 455 ms/doc（full，233 条 106 s）；
排序路径 6–14 ms；keyword 排序 0.5 s（balanced）/ 2.2 s（full）——**B 档必须把词面分
预计算到岗位侧**，不能每请求重算。

## 4. 这个结果证明了什么 / 没证明什么

**证明**：在本库的岗位族区分任务上，向量排序显著强于技能词重叠基线；且随简历不同
排序结果不同（A/B 的 P@10 分别为 0.800 / 0.900，top-10 重叠 5/10）。

**没有证明**：
1. 不测「你想不想投」——政策是族级规则，粒度只到岗位族；
2. 关键词基线有大量 0 分并列、按 job_id 断裂，其 P@10 偏低含 tie-break 成分，
   不能直接读成「关键字检索有 20% 准确率」；
3. 不能推导「投递效率提升 N 倍」。

## 5. 复现

```bash
python benchmarks/make_policy_labels.py
python benchmarks/resume_ranking_benchmark.py \
  --labels .scratch/ranking-a1/labels-policy-balanced.json --embedder ollama \
  --out .scratch/ranking-a1/results-policy-balanced.json
python benchmarks/resume_ranking_benchmark.py --selftest
```

（依赖本地 `data/jobs.db` 与本地 Ollama `bge-m3`。）

## 6. 结论

- 按**政策口径**，判据达标（+60 / +50 pp），B 档允许进入开发；
- B 档仍按 ADR-0065 决策 6 执行：`RESUALIGN_RESUME_RANKING=0` 默认关、P0 后灰度、
  UI 上限一处、用户语言不出现「向量 / 相似度」；
- **「投递意愿」判据仍缺人类锚点**。补齐方式：`annotation.html` 键盘版 15 分钟，
  或对政策标签做 15–20 条抽检。补齐前，对外只说「政策一致性」与「岗位族区分度」。
