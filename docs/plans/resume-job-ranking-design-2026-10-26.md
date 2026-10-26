# 简历 × 岗位排序（ranking-first）设计草案

- **状态**: 草案 v2（2026-10-26 重构，取代 v1「语义检索（RAG 前置）」；未采纳）
- **决策记录**: 本草案的决策项已展开为 `docs/adr/0065-resume-job-ranking.md`
  （提案状态，待拍板后转「已采纳」）
- **日期**: 2026-10-26
- **关联**: ADR-0059（P0 自用线 / P1 feature flag）；ADR-0064（prematch 词面信号，
  明确不做向量库——**本设计对其作限定性修订，见附录 A**）；ADR-0060 / 0061
  （allowlist 与 `jd_context` 边界）；ADR-0041 决定 11（`gate.py` vendor 锁）；
  ADR-0055（导入去重前置，0 次 LLM）；#167（门禁逐条隔离）
- **上游**: 不涉及（零触碰 `gate.py` 与 `tests/fixtures/gate/`）
- **议题**: 给岗位库增加「以简历为查询条件的确定性排序」，顺带补齐语义检索能力线

## 0. 相对 v1 的变更

| 项 | v1（2026-10-26 上午） | v2（本稿） | 为什么改 |
| --- | --- | --- | --- |
| 主张 | 补「语义检索 / RAG」能力线 | **简历 × 岗位排序**；检索只是实现手段 | 「问答/检索」是手段，「该投哪个岗位」才是需求 |
| 消费者 | 相似岗位 + 近重复提示 | **岗位→简历（best-resume）**、**简历→岗位（recommended）**、近重复提示 | 前两个才是用户每天要做的决策 |
| 评测集 | JD 语义改写 → 找回原文 | **作者手工标注「想投/不想投」→ hit@10 / nDCG@10** | 原评测测的是检索管线，不是「投递决策对不对」 |
| 问答 | C 档「默认否决」 | 明确列为**可选交互皮，不进默认路径** | 排序必须是确定性接口，LLM 最多做翻译与总结 |
| 数据依据 | 未实测 | 补 `data/jobs.db` 只读实测（§1） | 判据要落在真实规模上 |

## 1. 问题陈述（实测，2026-10-26 只读查询 `data/jobs.db`）

**规模事实（检索的必要性）**

- 真实岗位 **333** 条（另有 189 行标题为 `B` 的测试夹具，已排除）；
- `jd_text` 长度 **中位数 2,793 字 / 均值 2,742 / 最长 9,028**；
- 全库约 **90 万字**（粗算 60–90 万 token），**远超任何单次上下文**——跨库找岗位
  必须依赖检索，这一点不是可选项。

**当前是怎么找岗位的**

- 手动浏览岗位库 + `Ctrl+K` 的零 LLM 快速评估（`local_fallback` + `match_scorer`
  关键字覆盖分），没有「以简历为条件」的排序能力。
- 关键字口径的天花板有实测：`prematch.py` 注释记录 508 份真实 JD 离线分析中
  **40.6% 的岗位命中 ≤1 个词表技能**；同义表述（「高并发」vs「支撑 QPS」、
  「大模型」vs「LLM 应用」）无召回。

**岗位与简历之间没有矩阵**

- `master_resumes` 283 行（绝大多数是测试租户夹具，真实租户 `local` 下为个位数），
  **414 个岗位绑定过工作台简历**，但「这个岗位该用哪份底稿」目前完全靠手动。
- 这直接影响产出：**选错底稿 → 缺口全是真缺口 → 编辑器无据可改**，正对应
  209 个 failed 中 **43 个「未产出任何可用改写」**。

**近重复确实在浪费运行**

- 按 `(title, company)` 归并，真实岗位中有 **41 组近重复、多出 41 行**；
  这些行里有 79 行跑过工作台对齐。即便按最保守口径，也约 **41 次对齐是重复劳动**
  ≈ 41 × 194s ≈ **2.2 小时墙钟** + 对应配额（`daily_llm_cap` 消耗）。

**漏斗定位（决定本设计的边界）**

- 实测漏斗：可用建议 22 → 采纳 3 → **投递记录 2**。
- 断点在「产出」与「采纳」，不在「发现」。因此本设计**不承诺提升可用率**，
  只承诺两件事：把「翻 333 行」变成「看 10 行」；把「选哪份底稿」从猜变成有分数。
  唯一可能影响产出率的是 best-resume，**必须靠 §11 的评测证实，不许拍脑袋**。

## 2. 决策主张

> 把岗位库从「人翻列表」变成「以简历为查询条件的排序服务」：
> 给定一份简历，返回最该投的 K 个岗位；给定一个岗位，返回最适合做底稿的 K 份简历；
> 三条消费路径全部是**确定性接口、关键路径零 LLM**。

## 3. 目标 / 非目标

**目标**
1. `recommended`：简历 → 岗位 top-K，带可解释理由，hit@10 相对关键字基线有提升；
2. `best-resume`：岗位 → 底稿简历 top-3，缓解「选错底稿」导致的零可用；
3. 近重复提示（只提示不拦截），吃掉 2.2 小时/季度的重复对齐；
4. 能力线：混合检索（语义 + 词面）与**可进 CI 的检索评测**，补齐 RAG 能力缺口。

**非目标（明确不做）**
- 不做问答助手（见 §5.4，可选皮，不进默认路径）；
- 不改 `match_score` / `gap_report` / 编辑器 prompt / allowlist / 门禁任何语义；
- 不做自动投递、自动排序决策、岗位抓取；
- 不引入向量库、numpy、LangChain 等任何新依赖；
- 不做 UI 大改（列表侧栏 + 徽章为上限，不碰导航，遵守 ADR-0059）。

## 4. 与现行决定的冲突与处理

| 决定 | 原文 | 本设计处理 |
| --- | --- | --- |
| ADR-0064 | 「明确不做：嵌入向量/向量库（违背零依赖）」 | **限定性修订**该条（附录 A）。0064 已落地的 prematch 实现、词表、消费者一律不动 |
| ADR-0059 | P0 = 3 份真实 JD 自用验证；app 大改挂 feature flag | 评测脚本与只读接口不占 P0；产品面默认关、P0 后灰度 |
| ADR-0041 决定 11 | `gate.py` vendor 锁 | 零触碰，新增 AST 测试断言无 import |
| ADR-0060 / 0061 | allowlist 只认有依据的词；`jd_context` 不进许可链 | 排序结果**永不**进入 allowlist / 内容级校验 / 编辑器事实校验 |
| ADR-0055 | 导入去重前置（重复行 0 次 LLM） | 语义近重复是它的**延伸**，仍不额外调用 LLM |

**为什么必须显式修订 0064**：那是两天前的决定。要过，必须给「新证据 + 新边界」：
新证据是 §11 的预注册评测，新边界是「确定性接口、默认关闭、不进门禁」。
拿不出数字就维持 0064，把评测写成一篇否决记录——那也是可交付物。

## 5. 能力模型

| # | 消费者 | 输入 | 输出 | 有 LLM？ | 默认 |
| --- | --- | --- | --- | --- | --- |
| 1 | `GET /api/jobs/recommended` | 简历 + 结构化筛选 | top-K 岗位 + 分数 + 理由 | 否 | flag 关 |
| 2 | `GET /api/jobs/{id}/best-resume` | 岗位 | top-3 简历 + 分数 | 否 | flag 关 |
| 3 | 导入响应字段 | 新 JD 正文 | `similar_existing_job_ids`（只提示） | 否 | flag 关 |
| 4 | `POST /api/ask`（可选皮） | 自然语言 | 解析成筛选条件 → 调 #1 → 一句话总结 | 是（仅解析/总结） | 不进 main |

### 5.1 关键设计：排序永远确定性

- 打分 = **结构化硬过滤 → 双路召回 → RRF 融合 → 稳定排序**；
- LLM 最多出现在「把自然语言翻译成筛选条件」和「把 top-10 总结成一句话」，
  **不参与打分**。这样排序可复现、可回归、可 CI；
- 理由字段只给「命中了哪些有据技能 / 语义分位 / 缺口数」，不给「相似度 0.87」
  这种会被误读成概率的数字（给分位「高于 82% 的岗位」）。

### 5.2 结构化过滤先于打分

状态（未投递/已投递/面试中）、城市、薪资、截止日、是否已分析——全部走 SQL。
「筛掉不想投的」用规则比用向量准，**别用 LLM 做 SQL 能做的事**。

### 5.3 输出形态

列表 + 分数字段 + `why` 子对象；不做对话。前端上限：岗位库页一个「按简历推荐」
入口 + 卡片徽章（遵守 ADR-0059 §5 用户语言：不出现「向量」「相似度」）。

### 5.4 问答皮（可选，最后）

作用仅限于「帮我把条件说清楚」。实现为 function calling：解析出
`{resume_id, status, city, salary_min, limit}` → 调 #1 → 模板化总结。
**收益低、成本半天**，等 B 档数字出来再决定；即使做，也不进默认路径。

## 6. 评分与融合

三路信号：

| 信号 | 来源 | 成本 | 作用 |
| --- | --- | --- | --- |
| 结构化过滤 | SQL（状态/城市/薪资/截止/已分析） | 0 | 硬性排除 |
| 词面覆盖 | 现有 `prematch` + `match_scorer`（零网络） | 0 | 技能词命中，可解释 |
| 语义相似 | cos(embed(resume), embed(jd)) | 查询侧一次 embed | 同义/场景召回 |

- 融合用 **RRF（k=60）**，只吃排名不吃量纲，避免「加权系数调参」；
- 并列按 `job_id` 字典序，保证同一输入输出稳定；
- 评测里同时报「纯词面 / 纯语义 / RRF」三组，由数字决定是否保留 RRF（§11）。

## 7. 数据模型（迁移 47）

```sql
CREATE TABLE IF NOT EXISTS job_embeddings (
  tenant_id   TEXT NOT NULL,
  job_id      TEXT NOT NULL,
  model       TEXT NOT NULL,
  dim         INTEGER NOT NULL,
  text_sha256 TEXT NOT NULL,
  vec         BLOB NOT NULL,          -- float32 LE, dim*4 字节
  created_at  REAL NOT NULL,
  PRIMARY KEY (tenant_id, job_id, model)
);
CREATE INDEX IF NOT EXISTS idx_job_embeddings_model
  ON job_embeddings(tenant_id, model);

CREATE TABLE IF NOT EXISTS resume_embeddings (
  tenant_id   TEXT NOT NULL,
  resume_id   TEXT NOT NULL,
  model       TEXT NOT NULL,
  dim         INTEGER NOT NULL,
  text_sha256 TEXT NOT NULL,
  vec         BLOB NOT NULL,
  created_at  REAL NOT NULL,
  PRIMARY KEY (tenant_id, resume_id, model)
);
```

**不持久化 × 矩阵**：真实简历为个位数，333 × 10 = 3,330 次点积（内存缓存、
预归一化）约 25–40ms，实时算即可；持久化矩阵只会带来失效与重建负担。
若评测显示 p95 > 300ms，再考虑缓存，**先不预优化**。

不变量：`dim == len(vec)/4`；`text_sha256` 命中跳过重算；所有读写带 `tenant_id`；
模型切换保留旧行，`stats` 暴露 needs_rebuild，由重建命令处理。

**首次建库**：333 条约 2–5 分钟（本地 Ollama）。必须做成后台任务并暴露进度
（复用 `jobs` 表的状态机），期间接口返回 `degraded:true` + 关键字兜底，
**不允许首请求阻塞**。

## 8. 接口契约

```text
GET /api/jobs/recommended?resume_id=&limit=10&status=&city=&salary_min=
200 {items:[{job_id,title,company,status,score,
             why:{skill_hits:[], semantic_percentile, gap_count, usable_diffs}}],
     degraded:false, index_stats:{model, count, built_at}}

GET /api/jobs/{job_id}/best-resume?limit=3
200 {items:[{resume_id,title,current_version,score,
             why:{skill_hits:[], semantic_percentile}}]}

POST /api/jobs/import
200 {..., similar_existing_job_ids:[]}   # 只提示，不拦截，不加 LLM 调用
```

约束：
- 错误体沿用 #100 契约（`detail` + 顶层 `request_id`），不泄漏 `str(exc)`；
- 无向量 / embedder 不可用 → **200 + degraded**，不 5xx；
- 只读接口**不写库、不建 job、不调 LLM**（建库走独立后台任务）；
- best-resume **只建议、不自动写回** `workbench_resume_id`（写回属用户动作）。

## 9. 失败语义（与门禁严格区分）

| 场景 | 行为 | 理由 |
| --- | --- | --- |
| embedding 超时 / HTTP 错误 | 回退关键字排序，200 + degraded | 排序不是安全边界 |
| 索引未建 / 部分缺失 | 按命中部分排序；缺失岗位排后并标记 | 不阻塞主流程 |
| 模型 / 维度不匹配 | 该行不参与排序，`stats` 标 needs_rebuild | 防脏向量污染 |
| 租户不匹配 | 查不到即空 | 隐私边界 |
| 与 `gate.py` 的关系 | **零调用**，AST 测试锁 | fail-closed 不得被稀释 |

排序降级与门禁 fail-closed 是两套语义：**前者可以降级，后者永不**。这句话要进 ADR。

## 10. 开关与默认值

- `RESUALIGN_RESUME_RANKING=0`，**默认关闭**（同 `RESUALIGN_PREMATCH` 风格）；
- 打开且索引未就绪 → `degraded:true` + 关键字兜底；
- P0（3 份真实 JD）未过线前，`main` 默认值保持 0；P1 才允许灰度到单个入口。

## 11. 评测（本稿的核心变化）

### 11.1 评测集：作者手工标注（轻、真实、可复现）

- 从 333 条真实岗位分层抽 **40–60 条**（后端 / 前端 / 数据 / 算法 / 运维各 8–12）；
- 对 **2 份真实简历**分别标注，问法是：
  **「如果今天只投 10 个，我会投它吗」**（二值 relevant / not）；
- 标注口径：不看 `match_score`、不看模型输出，先标完再跑分（避免循环论证）；
- 落盘 `benchmarks/fixtures/resume_job_labels.json`（含标注时间、标注人、
  简历 sha256、口径说明）；**标注集 3 个月内不得改动**，改则重标并记录。
- **替代路径（2026-10-27 启用）**：人工标注不可得时，用作者口述政策生成标签
  （`benchmarks/make_policy_labels.py`），判据口径降为「政策一致性」，见
  ADR-0065「标注协议修订」与 `docs/reports/resume-ranking-policy-eval-2026-10-27.md`。

### 11.2 指标

| 指标 | 用途 |
| --- | --- |
| precision@10 | **主判据**：top-10 里「会投」的占比（hit@10 二值恒为 1、recall@10 被封顶 10/P，二者只作辅助，见 ADR 两次口径澄清） |
| nDCG@10 | 排序质量（相关性只有二值，nDCG 退化为位置加权命中率） |
| 人工浏览基线 | 按 `updated_at` 时间序 top-10 的 hit@10（证明不是偶然） |
| p50 / p95 延迟、建库耗时与体积 | 工程判据 |

### 11.3 预注册判据（事后不得重谈）

| 结果 | 处置 |
| --- | --- |
| **precision@10** 相对「关键字基线」**≥ +10pp** 且 p95 < 300ms | 进 B 档产品化（flag 默认关） |
| **+5 ～ +10pp** | 保留接口与评测，不铺 UI，不写回任何默认路径 |
| **< +5pp** | 关线，写 ADR「不采纳」，0064 维持原样 |

补充判据（best-resume 专用）：在 40 条标注里，若「top-1 推荐底稿」与「人工事后
认为最该用的底稿」一致率 ≥ 70%，才保留该接口；否则只保留数据表。

### 11.4 离线可跑

`benchmarks/resume_ranking_benchmark.py --offline`：用 `HashingEmbedder` +
固定 fixture 只校验**管线、排序稳定性、调用次数**，**不设质量阈值**（质量阈值由
一次性人工评测给出，避免 CI 依赖模型可用性）。

### 11.5 复现

```bash
python benchmarks/resume_ranking_benchmark.py --labels benchmarks/fixtures/resume_job_labels.json
```

数字进 `docs/EVIDENCE.md`（读数 · 口径 · 复现命令 · 判据 · 达标否）。

## 12. 模块与分层

```text
src/resualign/engine/embeddings.py          ~120 行  引擎层
    Embedder(Protocol) / HttpEmbedder（复用 OpenAIClient._post_json，
    POST {base}/embeddings，batch<=32）/ HashingEmbedder（256 维确定性兜底）
src/resualign/vector_index.py               ~130 行  存储层（modgraph 登记）
    VectorIndex.upsert/search/delete/rebuild/stats；纯 Python 余弦，内存缓存
src/resualign/api/services/resume_ranking.py ~140 行 服务层
    recommend_jobs() / best_resume() / near_duplicates()；RRF + 稳定排序
src/resualign/api/routers/jobs.py            +60 行  两个只读端点 + 导入响应字段
src/resualign/job_library/__init__.py        +15 行  迁移 47 + schema 两张表
tests/{engine,storage,domain,api,platform}/  ~45 用例
benchmarks/resume_ranking_benchmark.py      ~250 行 评测（labels 读取 + 指标）
```

依赖方向：引擎 ← 存储 ← 服务 ← API。`modgraph --check` 不得新增违规；
`vector_index` 需在 `LAYERS` 的存储层登记。

## 13. 测试计划

| 文件 | 覆盖 |
| --- | --- |
| `tests/engine/test_embeddings.py` | batch 切分、超时错误码、空文本、维度一致、Hashing 确定性 |
| `tests/storage/test_vector_index.py` | 读写删重建、cosine 排序、租户隔离、dim 不匹配拒绝、sha 跳过 |
| `tests/domain/test_rrf_rank.py` | RRF 数学、并列稳定、单路缺失、k 边界、空结果 |
| `tests/api/test_recommended_jobs.py` | 200/404/degraded、筛选透传、不写库、request_id |
| `tests/api/test_best_resume.py` | top-3、无简历、不自动写回 |
| `tests/platform/test_no_gate_coupling.py` | AST 断言不 import `gate`；vendor 哈希不变 |

CI：Stage 1 跑上述单测（全离线）；Stage 2 跑 `--offline` 管线检查；
覆盖率 85% 门禁不变。

## 14. 风险

| 风险 | 缓解 |
| --- | --- |
| 标注集太小 → 过拟合 | 40–60 条分层 + 二值标签 + 3 个月内冻结 + 同时报时间序基线 |
| 「相关性」定义漂移 | 问法固定为「今天只投 10 个会投它吗」，不看模型输出再标 |
| 排序被误读为概率 | 只给分位，不给相似度小数；UI 文案不含「向量/相似度」 |
| 选错底稿的判断被自动化 | best-resume 只建议不写回 |
| embedding 事实上扩大隐私面 | 默认本地 Ollama；远程节点等同聊天信任边界，写进 ADR |
| 与 0064 口径冲突 | 0065 显式限定性修订，保留 0064 其余全部决定 |
| P0 被插队 | A 档只读评测不占 P0；B 档默认关、P0 后灰度 |
| 向量规模漂移 | 5k 条阈值写进 ADR，超出再评估 ANN，不提前引库 |

## 15. 排期

| 阶段 | 工作量 | 前置 |
| --- | --- | --- |
| A1 标注 40–60 × 2 份简历 | 2 小时 | 无 |
| A2 评测脚本 + 出数字 + 报告 + EVIDENCE | 0.5 天 | A1 |
| 判据评审（拍板） | 0.2 天 | A2 |
| B1 模块 + 迁移 + 测试 + 两个只读接口 | 1.5 天 | 判据达标 |
| B2 前端入口 + 徽章（上限：一处） | 0.5 天 | B1 |
| C 问答皮（可选） | 0.5 天 | B 档数字之后 |

## 16. 验收（DoD）

1. `benchmarks/resume_ranking_benchmark.py` 在真实库可复现，报告含三组指标 + 延迟；
2. 判据结果（达标/不达标）进 `docs/EVIDENCE.md`，含复现命令；
3. 若进 B 档：`pytest tests/` 全绿、覆盖率 ≥85%、`modgraph --check` 零新增、
   flag 默认关、降级路径有测试、只读接口确实不写库；
4. ADR-0065 采纳，附对 ADR-0064 的限定性修订（附录 A）；
5. 用户可见措辞过审：不出现「向量 / 相似度 / RAG」，用「匹配度分位」「有据技能」。

## 17. 待拍板（7 项）

1. 立项动机按「面试作品能力线」还是「产品线」？（决定是否受 P0 排期约束）
2. 是否同意限定性修订 ADR-0064 的「不做嵌入向量」一条。
3. embedding 端点：强制本地 Ollama vs 复用用户已配置节点。
4. 默认值：默认关 + P0 后灰度（建议）vs 默认开。
5. 判据：40–60 条 × 2 份简历、±10pp 是否按本文预注册。
6. best-resume 只建议不写回（建议）vs 允许一键采用。
7. 问答皮：否决（建议）vs 独立分支 demo。

## 附录 A：ADR-0064「不做清单」的拟修订措辞

原文（第 54 行）：

> 明确不做：嵌入向量/向量库（违背零依赖）、技能图谱数据库（过度设计）、
> 全自动岗位排序（与「受控」定位冲突，见 ADR-0059）。

拟改为：

> 原「明确不做嵌入向量」一条由 ADR-0065 限定性修订：prematch 仍为**零网络、
> 零依赖的确定性信号**，不引入 embedder；语义相似仅作为**简历×岗位排序**的
> 一路召回信号，接口**默认关闭、确定性、不进 `gate`/allowlist/编辑器提示**，
> 评测判据与不引向量库的规模阈值（5k 条）见 ADR-0065。其余两条不变。

## 附录 B：拟提交 ADR-0065 的决定项（草案）

1. 新增「简历 × 岗位」确定性排序能力，默认关闭；消费者仅
   `recommended-jobs`、`best-resume`、导入近重复提示三处，**永不进入**
   `gate.py` / allowlist / 内容级校验 / 编辑器事实校验。
2. 排序关键路径零 LLM：结构化过滤 → 词面 + 语义双路召回 → RRF → 稳定排序；
   LLM 至多做条件解析与结果总结（可选皮，不进默认路径）。
3. 评测先行且预注册：作者手工标注 40–60 条 × 2 份简历，hit@10 相对关键字基线
   ≥ +10pp 才产品化；不达标即关线，ADR-0064 维持原样。
4. 数据模型为 `job_embeddings` + `resume_embeddings`（迁移 47），按
   `tenant_id + (job|resume)_id + model` 唯一，存 `dim` 与 `text_sha256`
   支持增量与重建；不持久化 × 矩阵。
5. 零新依赖、零向量库；纯 Python 余弦；规模超过 5k 条另开 ADR 评估 ANN。
6. 失败语义为**非阻断降级**（回退关键字），与门禁 fail-closed 明确分离；
   离线与 CI 一律走 `HashingEmbedder`。
7. 对 ADR-0064「不做嵌入向量」一条作限定性修订（附录 A）。
