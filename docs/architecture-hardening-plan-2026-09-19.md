# ResuAlign 架构加固计划（2026-09-19）

Status: 现在批**已施工并验证**；挂起批为决策完备施工单，等待解冻触发。

依据：`D:\WorkBuddyData\2026-09-19-02-48-20\code-review-agent\docs\全项目框架补强建议.md`
§3.1（R1–R7）与 §四（跨项目共性四项）。决策记录见
`docs/adr/0052-freeze-window-hardening-and-layering-ratchet.md`。

## 一、范围与姿态

- **范围 B**：R1–R7 + 跨项目共性四项（契约层 / 配置 fail-fast / 归档层 /
  扩展点注册表）。
- **姿态 A**：ADR-0042 冻结令不动。现在批＝零行为变更加固；挂起批＝写死
  施工单，不自动开工。
- **并行**：outreach 与现在批并行；挂起批解锁绑「探针时钟出结论」，不绑
  「outreach 发出」。
- **第一步门禁**：先提交推送 → CI 三阶段绿 → 才开工。已满足
  （`e5f2641` 三阶段全绿后开工）。

**R1–R7 与共性四项的归属（防漏项对照）**

| 项 | 归属 | 状态 |
| --- | --- | --- |
| R1 / R2 组合根双向绑定 | 挂起批 §3.1 | 施工单就绪 |
| R3 两个 god method | 挂起批 §3.2 | 施工单就绪 |
| R4 错误码文本回退 | 契约层（现在批 §2.3）+ 残余 挂起批 §3.6 | 码表已收口，文本回退待删 |
| R5 配置 clamp 而非 fail | 挂起批 §3.4 | 施工单就绪 |
| R6 调用图工具未接 CI | 现在批 §2.2 | **已落地** |
| R7 领域目录平铺 | 挂起批 §3.3 | 施工单就绪 |
| 共性 1 契约层 | 现在批 §2.3 | **已落地**（LLM 码；HTTP 码按裁定不动） |
| 共性 2 配置 fail-fast | 挂起批 §3.4 | 施工单就绪 |
| 共性 3 原始报文归档 | 现在批 §2.1 | **已落地** |
| 共性 4 扩展点注册表 | 挂起批 §3.5 | 施工单就绪（首步定位清单） |

## 二、现在批（已落地）

### 2.1 归档层（原始 LLM 报文）

- 落点：`src/resualign/archive/llm_trace.py`（+ 包 `__init__`）。
- 目标文件 `<RESUALIGN_LOG_DIR>/llm-traces.jsonl`，`RotatingFileHandler`
  10 MB × 5，与 `app.log` 同策略。
- 开关 `RESUALIGN_LLM_TRACE`，**默认 0 = 关**。关闭时
  `_post_json` / `_stream_deltas` 不填充正文，默认路径零 I/O。
- 每条记录显式 `redact_fields`（`sk-*` 掩码、超长 `error` 截断），字段
  含 `ts` / stage / provider / model / status / mode / attempts /
  duration_ms / request / response。
- 注入点：`OpenAIClient._post_json`（非流式唯一出口，含 deadline 分支）。
  **请求体在 POST 之前捕获**：超时、墙钟 deadline、连不上这类「没有响应」的
  失败同样留下「我们发了什么」，此时 `response` 为 `null`；流式在
  `_stream_deltas` 记录请求体、在 `stream_chat_json` 记录**累积输出**
  （失败时的部分输出同样保留为证据）。
- 写失败只 warning，不影响调用。
- 测试：`tests/test_llm_trace.py`（7 条：默认关、全量落盘、脱敏、
  空正文不落、轮转参数、端到端 chat_json、禁用时不触碰正文）。

### 2.2 分层棘轮（R6）

- 工具落点：`src/resualign/tools/modgraph.py`；基线
  `src/resualign/tools/layering-baseline.json`。`.scratch/modgraph.py` 已删除。
- 修复两个已确证缺陷：
  - `layer_of` 改为**最长前缀优先**（`api/services/*` 不再被判成 API），
    且裸模块名按边界匹配（`engine_utils.py` 不再冒充 `engine`）。
  - 新增规则**服务层不得依赖 API / 接入层**（服务 → 服务仍允许）。
- 棘轮三类集合差：分层违规、循环依赖、`api_module._` 引用站点
  （键 `file::attr` + 计数，不含行号）。只允许减少；`--update` 收紧。
- 实测基线（修复后）：**违规 9 项 / 循环 56 项 / 引用站点 332 处
  （127 个组合）/ 模块 73**。
- CI：Stage 1 增加 `python -m resualign.tools.modgraph --check`。
- 测试：`tests/test_modgraph_layers.py`（11 条，含「基线必须与当前树一致」）。

### 2.3 契约层（LLM 失败码）

- 落点：`src/resualign/contracts/errors.py`，`LlmFailureCode(str, Enum)`
  9 个成员（timeout / empty / parse / schema / quota / rate_limit / auth /
  http / other）；Python 3.10 兼容，不用 `StrEnum`。
- 消费侧（`llm`、`engine`、`api/services/jobs`、`llm_nodes`）改为引用枚举；
  集合一律持有 `.value`（Enum mixin 覆盖 `__hash__`，成员集合不会命中 `str`）。
- `LLMResponseError.code` 归一化为**普通 str**：`isinstance` 时取 `.value`，
  未知值回落 `other` —— 现有比较、日志与 JSON 载荷不变。
- **明确不做**：HTTP 错误体契约（ticket #100）不动；`jobs.py` 的
  `code == "other"` 文本回退分支仍在（属 R4 独立题目）。
- 模块加入 modgraph 层表的**最内层** `contracts/`，纳入「不得向外依赖」集合。
- 测试：`tests/test_contract_errors.py`（8 条）。

## 三、挂起批施工单（解冻后按序执行）

执行顺序原则：**先降耦，再拆函数，最后搬目录**。R7（搬目录）排最后，因为
它与 R1 触及同一批文件，先搬会让 R1 的 diff 无法审阅。

### 3.1 R1 / R2 —— 应用层承接编排

**目标**
- `api_module._` 引用站点：332 处 → 0。
- 服务层反向依赖：9 条违规 → 0；组合根相关循环（56 项中围绕
  `resualign.api` 的部分）消失。
- `api/__init__.py` 不再反向再导出 service 私有函数。

**手段**
- 新增 `src/resualign/app/`，用显式注入对象替代 `import resualign.api as
  api_module` 的隐式全局取用。

**步骤（每步一个 commit）**
1. 定义 `app/context.py`：`AppContext` 承载 registry / library /
   applications / llm_nodes / settings / 相关回调（字段清单由现有
   `api_module._*` 使用点反推）。
2. 逐个 services 文件迁移，顺序按引用密度：
   `jobs` → `workbench` → `batch` → `cost_guard` → `watchdog` →
   `resume_optimize` → `resumes`。每个文件迁完即提交。
3. 服务函数改为接收注入对象；删除文件内 `import resualign.api as api_module`。
4. `api/__init__.py:270-303` 的再导出删除；routers 改为从 app 层取对象。
5. `--update` 收紧 baseline（违规数必须下降）。

**验收**
- `python -m resualign.tools.modgraph --check` 无新增；`--update` 后
  违规数 < 9。
- `api_module._` 站点集合为空。
- `python -m pytest tests/ -q` 全绿；`tests/test_error_contract.py` 形状不变。

**回滚粒度**：单个 services 文件。任一文件迁不动就停在该提交，不回滚已迁部分。

### 3.2 R3 —— 拆两个 god method

**A. `update_job`（445 行）**
- 手段：40 字段 if 墙 → 单一 `_JOB_UPDATE_FIELDS` 白名单表
  （请求字段名 → 列名 + 转换器）+ 一个 UPDATE 构造器。
- 验收：函数 < 100 行；每个字段一条参数化 PATCH 等价测试。
- 回滚粒度：一个 commit。

**B. `_run_job_holding_gate`（426 行 / 15 职责）**
- 手段：拆 claim / run / persist / notify 四段；持久化编排抽到
  `app/services/alignment_writer.py`。
- 注意：必须保留 ADR-0042 相关边界（job 表 `request_id` 恢复、watchdog
  条件 UPDATE、tenant gate 语义）。
- 验收：单函数 < 100 行；`tests/test_alignment_persistence.py`、
  `tests/test_phase_e.py` 全绿。
- 回滚粒度：一个 commit。

### 3.3 R7 —— 领域目录分包

**现状**：`src/resualign/` 一级 **41 个条目**（含本次新增的 `archive/`、
`contracts/`、`tools/` 三个包）。

**目标形态（决策已定）**

| 子包 | 收纳 |
| --- | --- |
| `contracts/` | 已有：跨层契约（失败码等） |
| `engine/` | `engine.py`（先转包）、`tailor.py`、`role_router.py`、`llm.py`、`llm_nodes.py`、`llm_providers.py` |
| `domain/` | `match_scorer`、`gap_analyzer`、`jd_profiler`、`jd_analysis`、`evaluator`、`classifier`、`rules`、`rule_diagnose`、`local_fallback`、`extractor`、`parser`、`resume_optimize`、`batch` |
| `storage/` | `store_base`、`job_library/`、`workspace`、`settings_store`、`llm_usage`、`cache`、`secret_box`、`alignment_lifecycle`、`jobs` |
| `observability/` | `observability.py`（先转包） |
| `archive/`、`tools/` | 已有 |

**步骤**
1. 先迁移叶子模块（无内部依赖者），每包一个 commit。
2. `modgraph.py` 的 `LAYERS` 同步改成新路径前缀，`--check` 必须无新增。
3. 迁移完成后跑 `git grep` 残留引用自检。

**验收**：全量测试绿；`modgraph --check` 无新增；`git grep` 无旧路径。

### 3.4 配置 fail-fast（跨项目共性 2）

- 位置（实测坐标）：
  - `src/resualign/api/state.py:66-77` `_clamp_worker_concurrency` —— 非法值
    静默夹到 1..4，`RESUALIGN_WORKER_CONCURRENCY=0/-1/99` 都不报错；
    `config.py:89-91` 只是那句「故意用 str，交给 resolver clamp」的注释。
  - `src/resualign/observability.py:186-191` `log_sample_rate` —— 非法值回落
    默认 1% 并夹到 [0, 1]。
  - 施工时用 `git grep -n "clamp\|max(.*min(" src/resualign/` 复核是否还有第三处。
- 手段：clamp → `raise ValueError`，错误信息必须含**环境变量名与合法区间**。
- 验收：每个受管变量一条测试，断言非法值启动失败且报错含变量名。
- 回滚粒度：一个变量一个 commit。

### 3.5 扩展点注册表（跨项目共性 4）

- 现状：补强建议记为「ResuAlign 新版式 5 处常量」，**具体位置需在解锁时
  用一次定位扫描确认**（施工首步产出清单，再决定表结构）。
- 手段：散落常量 → 单表注册；漏注册即报错（不是静默回落）。
- 验收：新增一种版式只需改注册表一处，diff < 20 行。

### 3.6 R4 残余 —— 删除 message 子串回退

- 现状（实测 `api/services/jobs.py:352-395`）：结构化 code 分支已经就位，
  但 `code == "other"` 时仍回退到子串嗅探，共 5 组 21 个片段 ——
  `"429"`/`"rate limit"`；`"401"`/`"403"`/`"unauthorized"`/`"authentication"`/
  `"invalid api key"`/`"api key"`；`"timeout"`/`"timed out"`/`"time-out"`；
  `"empty response"`/`"empty content"`/`"returned empty"`/`"was empty"`/
  `"empty after"`；`"expecting value"`/`"no json object found"`/
  `"not a json object"`/`"invalid json"`/`"schema validation"`/
  `"failed validation"`。
- 手段：先确认没有生产路径会产出无 code 的异常
  （`git grep -n "LLMResponseError(" src/` 逐个核对是否带 `code=`），
  然后把整段子串分支降级为单一兜底文案「模型服务暂时不可用，请稍后重试」。
- 验收：
  - `git grep -n "invalid api key\|unauthorized" src/resualign/api/services/jobs.py`
    为空（嗅探分支消失）。
  - 构造「无 code 的旧式异常」，断言落到兜底文案，**不会**被误判成
    「检查 API Key」—— 这正是 R4 当初要消灭的误归因。
  - `tests/test_r4_aie_guardrails.py`、`tests/test_llm_timeout.py`、
    `tests/test_alignment_persistence.py` 全绿。
- 排序：排在 §3.1（R1/R2）**之后** —— 同一个 `jobs.py` 会被 R1 大改，
  先删回退只会制造冲突。
- 回滚粒度：一个 commit。

## 四、触发与门禁

- 挂起批**不自动开工**。触发条件＝ADR-0042 探针线到截止日（判定线
  2026-09-23 24:00）后**强制一次评审**，由评审结论决定是否解冻。
- 评审不改代码；解冻需新 ADR 或 ADR-0042 决定 6e 逐项引用（现状：例外只有
  #98 与 #115）。
- 任何挂起批改动都必须保持 CI 三阶段绿（Stage 1 / benchmark / Playwright）。

## 五、验证命令

```bash
# 现在批（每次改动都跑）
python -m resualign.tools.modgraph --check      # 分层棘轮（需 PYTHONPATH=src）
python -m resualign.tools.modgraph --update     # 仅当违规/引用减少时收紧基线
python -m pytest tests/test_llm_trace.py tests/test_modgraph_layers.py \
    tests/test_contract_errors.py -q
python -m pytest tests/ -q                       # 全量后端
node --test tests/frontend/*.test.mjs tests/frontend/dom/*.test.mjs
python -m pytest tests/e2e -q --e2e              # 独立端口 + 临时数据目录
ruff check src/ tests/ benchmarks/ run.py
```

`modgraph --check` 失败的含义：**你新增了耦合**，不是工具坏了。修代码或
（仅当是误报时）改工具，然后 `--update` 之前先确认集合差确实为空。
