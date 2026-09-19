# ADR-0051: 冻结令例外 — LLM 服务商自动识别与模型发现

- **状态**: 已采纳
- **日期**: 2026-09-19
- **依据**: ADR-0042 决定 6e（app 冻结期内「让自用闭环好用」的改动须逐项引用
  本条走例外流程并留记录）
- **关系**: 只解冻本条列出的范围；不改探针线/自用线判据、不改
  ADR-0042 的 6b/6c/6d 护栏，不解除 ADR-0041 决定 1 的功能票冻结

## 背景

用户在使用工作台与设置页时报告了四条真实摩擦，其中一条落在 AI 服务商配置上：

1. 节点表单的 `provider` 是三值 `Literal["deepseek", "openrouter", "ollama"]`，
   实际在用的 NVIDIA NIM / 硅基流动 / 智谱 / 百炼 / 火山 / Groq 等 OpenAI 兼容
   服务商无法录入；
2. 模型名必须手填，写错要到「运行对齐」失败才发现——配置错误反馈太靠后；
3. 服务商元数据此前散在 `llm.py`（默认 URL）、`llm_nodes.py`（白名单）、
   `settings_store.py`（另一份白名单）三处，任一处漏改都会造成口径分裂。

ADR-0042 决定 6e 要求这类「让自用闭环好用」的改动逐项引用并留记录，因此本 ADR
是该项的例外凭据，而不是一次功能解冻。

## 决定

**决定 1（后端只读例外）**：新增 `POST /api/llm/models`——按 Base URL 识别
服务商并返回该端点的模型 id 列表。它只读、不落库、不改 jobs/对齐管线、不改
SQLite schema。OpenAI 兼容走 `{base_url}/models`，Ollama 走 `/api/tags`；
编辑态可复用后端已存的 Key。

**决定 2（服务商元数据单一来源）**：服务商默认 URL / 显示名 / 主机识别规则
收敛到 `src/resualign/llm_providers.py`；`llm.py`、`llm_nodes.py`、
`settings_store.py` 共用同一份白名单，不再各自维护。

**决定 3（provider 字段类型放宽）**：`LLMNodeCreateRequest` /
`LLMNodeUpdateRequest` / `LLMSettingsUpdate` / `SettingsTestConnectionRequest`
的 `provider` 从三值 `Literal` 放宽为带长度上限的字符串。未知值不再 422，
而是**降级为 `custom`**（写入路径仍只接受白名单内的值）；非法配置由
`/api/llm/models` 或连通性测试的失败信息暴露。

**决定 4（前端可见模型清单）**：节点表单（专家 Modal 与设置页简单模式）新增
「获取模型」按钮与**可见可点的模型清单**；服务商下拉扩展为完整清单 +
「自动识别」。原生 `datalist` 只在「聚焦 + 输入过滤」时才可见，单独用它等于
按钮点了没反应，故不作为唯一出口。

**决定 5（契约同步）**：新端点属 additive 变更，
`contracts/openapi-current.json` 与 `contracts/incremental/manifest.json`
同步登记；`contracts/openapi-v1.json` 保持不变。

**决定 6（冻结边界）**：本例外不外溢——不解除 ADR-0041 决定 1 的功能票冻结
（#20–#69 仍冻结），不引入新运行时依赖，不新建通用 provider 适配层；非
OpenAI 兼容协议的接入须另开 ADR。

## 后果

- 用户不改代码即可接入任意 OpenAI 兼容服务商，并在保存前确认 Key / Base URL
  是否真的可用（模型列表是第一个可验证信号）。
- 服务商白名单从三处收敛到一处，降低再次漂移的风险。
- 代价：`provider` 的类型收紧被放宽，非法值从「写入时 422」变成「读模型时
  失败」。这是有意的取舍——三值白名单正是本次摩擦的根因。

## 与既有 ADR 的关系

- **ADR-0042 决定 6e**：本 ADR 即该条的逐项例外记录，冻结令其余部分继续有效。
- **ADR-0050**：其范围是前端 CSS 重构，未覆盖后端；本 ADR 补的是后端与前端
  功能面，两者不重叠、不互相授权。
- **ADR-0041 决定 1**：功能票总闸（#114 `frozen`）不变，本例外不外溢。
