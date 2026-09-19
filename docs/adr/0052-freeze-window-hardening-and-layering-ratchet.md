# 0052 — 冻结期加固：原始报文归档、分层棘轮与 LLM 失败码契约

Status: accepted (2026-09-19)。现在批三件**已施工**；R1/R2/R3/R7 只写施工单，
不在冻结期内动代码。

## 背景（证据链，非估计）

1. **层错位（最严重）。** 实测 `api_module._` 引用 **332 处**，分布在
   `src/resualign/` 内 **127 个 (文件, 属性) 组合**；`api/__init__.py` 反向
   再导出 30+ 个 service 私有函数，因此组合根与所有服务互指成环。
2. **调用图工具不可信。** `.scratch/modgraph.py`（6500 字节）存在但 `.github/`
   与 `scripts/` 零引用，且带两个已确证缺陷：
   - `layer_of` 前缀遮蔽：`api/` 排在 `api/services/` 之前且用 `startswith`
     判定，于是 `api/services/jobs.py` 被判成 API，**「服务」层永不返回**；
   - 判据只检查源层 ∈ {引擎, 领域, 存储, 模型, 可观测}，**服务 → API 完全
     不可见**。
   修好这两点后，工具立刻报出 **9 条服务层反向依赖** ——它们一直存在，只是
   从没被任何门禁看见。
3. **失败码靠字符串散落。** `LLMResponseError.code` 的 9 个取值同时被
   `llm`（产出）、`engine`（降级判据）、`api/services/jobs`（用户文案）、
   `llm_nodes`（熔断计数）读取，却各自写成字符串字面量。拼错一个字就会静默
   落进 `other` 桶，正是 R4 P0-1 当初要消灭的失败模式。
4. **原始报文没有归档。** `observability.py` 已有 request_id、结构化日志与
   `redact_fields`，`llm.call` 事件记录了 provider/model/耗时/token，但**没有
   留下发了什么、回了什么**。「模型忽略了我的 JD」这类争议无法复盘。
5. **冻结令在途。** ADR-0042 的自用线仍在推进（探针时钟 PENDING，四渠道
   0/4），功能票 #20–#69 全部 frozen。本轮所有改动都必须满足「零行为变更」。

## 决定

**1. 现在批 = 三件零行为变更加固，顺序为 归档层 → 棘轮 → 契约层。**

依据：归档**不可补录**（今天没落的报文，将来补不回来），棘轮**必须先于
重构**（否则债还完了才有记录），契约层最晚但收益随重构放大。

**2. 归档层默认关闭，写入前显式脱敏。**

- 落点 `<RESUALIGN_LOG_DIR>/llm-traces.jsonl`，`RotatingFileHandler`，
  10 MB × 5，与 `app.log` 同策略。
- 开关 `RESUALIGN_LLM_TRACE`，默认 `0`。关闭时调用方传 `None`
  正文，不产生 I/O 与额外分配 —— 默认路径与加固前逐字节一致。
- 每条记录显式走 `observability.redact_fields`（掩码 `sk-*`、截断超长
  `error`），并带 `ts` / stage / provider / model / status / attempts /
  duration_ms / request / response。
- 写失败只记 warning，绝不影响 LLM 调用本身。
- 请求体在 HTTP 出口单点捕获（`OpenAIClient._post_json`），流式调用捕获
  实际累积的输出（失败时的部分输出同样是证据）。

**3. 分层棘轮用「集合差」，只允许减少。**

- 工具从 `.scratch/` 移入 `src/resualign/tools/modgraph.py`（原 scratch 副本
  删除），`layer_of` 改为**最长前缀优先 + 模块名边界匹配**
  （`engine_utils.py` 不再冒充 `engine`）。
- 新增规则：**服务层不得依赖 API / 接入层**（服务 → 服务仍允许）。
- 基线 `src/resualign/tools/layering-baseline.json` 入仓，记录三类集合：
  分层违规、循环依赖、`api_module._` 引用站点（键为 `file::attr` + 计数，
  不含行号，避免格式化噪声）。
- `--check` 只在**新增**违规/环/引用增加时退出 1；减少只提示，用 `--update`
  收紧。CI Stage 1 增加一步 `python -m resualign.tools.modgraph --check`。
- 契约层作为最内层加入层表（`contracts/`），纳入「不得向外依赖」集合。

**4. 契约层只收 LLM 失败码，HTTP 错误码不动。**

- 新建 `src/resualign/contracts/errors.py`：`LlmFailureCode(str, Enum)`
  9 个成员（timeout / empty / parse / schema / quota / rate_limit / auth /
  http / other），Python 3.10 兼容，故不用 `StrEnum`。
- 消费侧集合一律持有 `.value`（Enum mixin 覆盖 `__hash__`，成员集合不会与
  `str` 命中）；`LLMResponseError.code` 归一化为**普通 str**，现有比较与
  JSON 载荷不变。
- HTTP 错误体契约（`{code, message, request_id}`，ticket #100）是另一个
  命名空间，本轮不动。

**5. 挂起批 = R1/R2、R3、R7 + 配置 fail-fast + 扩展点注册表，写成施工单。**

细则见 `docs/architecture-hardening-plan-2026-09-19.md`。它们**不自动开工**：

**6. 触发条件是「时钟出结论」，不是「outreach 发出」。**

ADR-0042 探针线到截止日（登记为 2026-09-23 24:00 判定线）后**强制一次评审**，
评审结论决定解冻与否；评审本身不改代码。冻结令继续由 ADR-0042 持有，本 ADR
不新增例外、不放宽任何阈值。

## 后果

- 争议复盘从此有原始报文可查；代价是开启后每调用一行 JSONL，且**正文含简历/
  JD 原文**，因此默认关闭、按需开启，并与其他日志同目录同权限管理。
- 分层债务第一次被量化：**9 条违规 + 56 个循环**（循环全部围绕组合根
  `resualign.api`）。棘轮把这些数字冻在当前水位，只许下降。
- 契约层没有消灭文本回退分支（`jobs.py` 的 `code == "other"` 兜底仍在），
  因为那是 R4 的独立题目，不属于本轮「只收 LLM 失败码」的范围。
