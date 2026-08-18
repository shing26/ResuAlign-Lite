# ResuAlign 工程架构评审报告

**生成日期**: 2026-08-18
**分析框架**: Frontend Developer, Backend Architect, Prompt Engineer, Multi-Agent Systems Architect

---

## 一、Frontend Developer — 前端架构评审

### 当前架构特征

| 维度 | 当前状态 | 评价 |
|------|---------|------|
| 框架 | 原生 JS + 字符串模板渲染 | 无框架，无虚拟 DOM，直接 innerHTML |
| 样式 | Tailwind 风格 utility class（自建） | 无构建工具，纯 CSS 文件 |
| 路由 | 基于 hash 的前端路由 | 手动管理，无 SPA 框架 |
| 状态管理 | 全局 `state` 对象 + `events.js` | 无响应式状态管理 |
| 模块化 | ES module（`import/export`） | 现代但未使用打包工具 |
| API 调用 | 原生 `fetch()` | 无 SWR/React Query 缓存层 |
| 测试 | happy-dom 单元测试 | 443 个前端测试通过 |

### 关键问题

#### 问题 1: 无组件化架构

**现状**：所有视图函数返回字符串模板，`main.js` 通过 `innerHTML` 注入 DOM。每次路由切换都销毁并重建整个视图。

**影响**：
- 状态丢失：视图切换后，滚动位置、选中状态、临时数据全部丢失
- 无生命周期：无法在组件卸载时清理资源（SSE 连接、定时器）
- 渲染性能：大列表重建时触发布局抖动

**建议**：渐进式引入 Lit 或 Preact（轻量级，< 5KB），无需构建工具，支持原生 template 语法。

#### 问题 2: 无 API 缓存层

**现状**：每个视图渲染时独立发起 `fetch()` 调用，没有请求去重和缓存。

**影响**：
- 岗位库和仪表盘各自独立请求 `/api/jobs`，造成重复网络开销
- 路由切换后所有数据重新加载，无缓存命中

**建议**：引入 `Cache API` 或简单内存缓存，TTL 30 秒，同路由复用。

#### 问题 3: 无虚拟滚动

**现状**：岗位库列表渲染全部 500 个岗位，DOM 节点数可能超过 1000。

**影响**：大列表页面滚动时掉帧，移动端尤为明显。

**建议**：实现 IntersectionObserver 驱动的虚拟滚动，只渲染可见区域。

#### 问题 4: 无构建工具

**现状**：CSS 文件直接加载，没有 postcss/autoprefixer，没有 CSS 变量降级。

**影响**：
- CSS 变量在旧浏览器不兼容
- 开发体验差：不能使用嵌套、不能自动前缀

**建议**：引入 `lightningcss` 或 `postcss-cli` 作为构建步骤，同时保持无框架架构。

### 前端架构改造建议

```
Phase 1（低风险，立即执行）：
├── 引入内存缓存层（CacheManager）
├── 实现 IntersectionObserver 虚拟滚动
└── 添加 CSS 变量降级

Phase 2（中风险，下一轮）：
├── 评估引入 Lit 或 Preact 的成本
├── 渐进式替换 dashboard-view → Lit 组件
└── 建立组件生命周期管理

Phase 3（高风险，可延后）：
├── 迁移到 Vite + Lit 作为构建工具链
└── 建立完整的组件库
```

---

## 二、Backend Architect — 后端架构评审

### 架构全景

```
┌─────────────┐  ┌──────────────┐  ┌──────────────────┐
│  FastAPI App │  │  SQLite (WAL)│  │  LLM Provider    │
│  62 endpoints│  │  5 tables    │  │  (DeepSeek/Ollama)│
│  56 schemas  │  │  + caches    │  │                  │
└──────┬───────┘  └──────┬───────┘  └────────┬─────────┘
       │                 │                   │
       └─────┬───────────┴───────────────────┘
             │
     ┌───────┴────────┐
     │  Engine Pipeline │
     │  diagnose →      │
     │  profile → gap → │
     │  tailor → eval   │
     └────────────────┘
```

### 关键问题

#### 问题 1: 模块文件过大（上帝模块）

**现状**：`job_library.py` 2956 行，`update_job` 方法 449 行。

**影响**：
- 可测试性差：单文件包含 71 个函数/方法，职责边界模糊
- 合并冲突高：多人同时修改同一个文件
- 认知负荷：新开发者需要阅读 3000 行代码才能理解岗位库

**建议**：拆分为 `job_library/` 包：`status_lifecycle.py`、`store.py`、`crawl_store.py`、`models.py`。

#### 问题 2: API 无版本前缀

**现状**：所有 62 个端点挂在 `/api/*` 下，无版本号。

**影响**：
- MCP server 已暴露工具，未来多客户端时破坏性变更风险高
- 无法同时维护 v1 和 v2

**建议**：在路由层加 `/api/v1` 前缀（FastAPI APIRouter prefix），一次性机械改动。

#### 问题 3: 异步作业模型薄弱

**现状**：`AnalysisJob` 使用内存线程池 + SQLite 轮询，没有持久化队列。

**影响**：
- 服务重启时运行中的任务丢失
- 没有任务重试和死信队列
- 无法水平扩展

**建议**：引入 SQLite-backed 任务队列（如 `arq` 或简易 `queue` 表），支持重启恢复。

#### 问题 4: 缺少 API 契约测试覆盖率

**现状**：62 个端点，只有 2 个契约测试（`test_contract.py`）。

**影响**：端点变更时容易遗漏，导致前端/客户端断裂。

**建议**：为每个端点添加 OpenAPI 契约测试，确保 response schema 与文档一致。

#### 问题 5: 缺少后台任务调度框架

**现状**：headless daemon 使用 `time.sleep()` 轮询。

**影响**：轮询间隔固定，不支持 cron 表达式，不支持分布式调度。

**建议**：引入 APScheduler 或保持简单轮询但增加 `RESUALIGN_POLL_INTERVAL` 可配置。

### 后端架构改造建议

```
P0：
├── 拆分 job_library.py 为 package
├── API 添加 /api/v1 前缀
└── 异步作业添加重启恢复（queue 表）

P1：
├── 为每个端点添加契约测试
├── 添加任务队列持久化
└── 统一错误响应格式

P2：
├── 引入健康检查端点（当前已有 /health）
├── 添加请求日志中间件
└── 添加请求 ID 追踪
```

---

## 三、Prompt Engineer — Prompt 工程评审

### 当前 Prompt 体系

| Prompt | 文件 | 行数 | Schema | 版本号 |
|--------|------|------|--------|--------|
| JD Profiler | `jd_profiler.py` | ~40 行 | JDProfileSchema | 有 |
| Gap Analyzer | `gap_analyzer.py` | ~20 行 | GapReportSchema | 无 |
| Tailor | `tailor.py` | ~80 行 | TailoredResumeSchema | 有 |
| Evaluator | `evaluator.py` | ~30 行 | EvalScoreSchema | 无 |
| Diagnose | `llm.py` | ~20 行 | AnalysisSchema | 无 |
| Intake Policy | `policy_llm.py` | ~20 行 | JdIntakeDecisionSchema | 无 |

### 评审发现

#### 问题 1: Prompt 版本号不一致

**现状**：`JD_PROFILER_PROMPT_VERSION = "1"` 和 `BULLET_REWRITE_PROMPT_VERSION = "bullet-rewrite-v1"` 存在，但 gap_analyzer、evaluator、diagnose 没有版本号。

**影响**：无法追踪哪些 prompt 已经变更，缓存 key 不能准确区分版本。

**建议**：为每个 prompt 添加 `{NAME}_PROMPT_VERSION` 常量，格式统一为 `v1`、`v2`。

#### 问题 2: Prompt 缺少约束条款

**现状**：当前 prompt 包含"不要捏造"、"输出 ONLY JSON"等指令，但缺少：
- **输出长度约束**：没有指定最大 token 数
- **失败处理指令**：模型不确定时该怎么办
- **温度指定**：prompt 中没有提示模型使用低温度

**建议**：为每个 prompt 添加标准约束节：

```markdown
## Output Constraints
- Max tokens: 500
- Temperature: 0.0
- If uncertain: return empty list instead of guessing
- If input is empty: return {"error": "empty_input"}
```

#### 问题 3: 缺少 Prompt 测试

**现状**：当前没有 prompt 测试套件（没有 `test_prompt_tailor.py` 等）。

**影响**：模型更新后 prompt 可能静默退化，regression 只有通过 benchmark 检测。

**建议**：为每个 prompt 建立 3+ 测试用例（happy path, edge case, failure mode），使用 `temperature=0.0` 固定输出。

#### 问题 4: System Prompt 中隐藏了太多业务逻辑

**现状**：Tailor 的 prompt 包含 12 条规则，其中规则 4-12 是关于"如何改写"的业务逻辑，不是"模型行为"的约束。

**影响**：业务逻辑变更时必改 prompt，prompt 变更又需要重新测试和验证。

**建议**：将业务逻辑与 prompt 模板分离：
- prompt 只定义角色、约束、输出格式
- 业务规则作为输入 context 的一部分传入

### Prompt 工程改造建议

```
P0：
├── 统一所有 prompt 的版本号格式
├── 为每个 prompt 添加输出约束节
└── 建立 prompt 测试套件（至少 3 个 case）

P1：
├── 将 Tailor 的 12 条规则从 prompt 中拆出
├── 改为 context 输入 + 5 条核心规则
├── 添加 prompt changelog 追踪
└── benchmark 用例覆盖全部 prompt 路径

P2：
├── 建立 prompt 性能基线（token 消耗、响应时间）
├── 自动检测 prompt 退化（AVG 对比）
└── 多模型 prompt 适配层
```

---

## 四、Multi-Agent Systems Architect — 多 Agent 架构评审

### 当前 Agent 拓扑

```
                    ┌──────────────────────┐
                    │   Orchestrator Agent  │ (ADR-0029)
                    │   JD Intake, Blockers │
                    └──────┬───────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌────────────┐  ┌────────────┐  ┌──────────────┐
    │ JdIntake   │  │ LLM Policy │  │ Headless     │
    │ Policy     │  │ (LLM)      │  │ Daemon       │
    │ (Rule)     │  │            │  │              │
    └────────────┘  └────────────┘  └──────────────┘

                    ┌──────────────────────┐
                    │   Engine Pipeline     │
                    │   (Sequential Chain)  │
                    │                       │
                    │  diagnose → profiler  │
                    │  → gap → tailor → eval│
                    └──────────────────────┘
```

### 评审发现

**拓扑类型**：混合拓扑（Sequential Chain + 少量 Parallel Fan-Out）

**当前已实现**：
- 角色化 Agent 拆分（5 个 LLM 角色）
- 并行诊断 + 概览（云端节点）
- 单次自动回退
- 分级超时

### 问题 1: 缺少失败传播控制

**现状**：当 `editor` 角色失败并回退到默认节点再次失败时，异常直接抛出到 `engine.run()` 调用方。调用方（jobs.py 或 workbench.py）的 `try/except` 捕获后标记任务失败。

**影响**：
- 用户看到的是"对齐分析失败"，但没有具体原因（哪个角色、哪个阶段）
- 无法部分成功：profile 和 gap 分析成功，但 editor 失败时，整个任务标记为失败

**建议**：引入**部分成功**模式：

```python
# 模型：部分成功容忍
class StageResult:
    stage: str
    status: "success" | "failed" | "degraded"
    result: Any | None
    error: str | None
    fallback_used: bool
    actual_model: str

# engine.run() 返回部分成功，不 throw
# 前端展示"简历改写失败，但其他分析已完成"
```

### 问题 2: 缺少 Agent 级别可观测性

**现状**：当前只有 `llm.call` 和 `agent.decision` 事件，没有：
- 每个 Agent 的输入/输出追踪
- 端到端 trace_id
- 失败链分析（哪个 Agent 的失败导致下游级联失败）

**建议**：引入 `trace_id` 贯穿整个 pipeline，每个 Agent 调用记录：

```python
{
    "trace_id": "abc123",
    "span_id": "def456",
    "parent_span_id": "xyz789",
    "agent": "profiler",
    "stage": "jd_analysis",
    "input_tokens": 450,
    "output_tokens": 120,
    "duration_ms": 2340,
    "status": "success",
    "fallback_used": False,
    "model": "deepseek-chat",
}
```

### 问题 3: Context 预算管理缺失

**现状**：每个 Agent 的输入上下文大小没有统一管理。`tailor` 可以接收 8000 字符的 JD + 完整简历 + 完整 Gap Report。

**影响**：
- 小模型（7B/8B）在长上下文下输出质量下降
- Token 消耗不可预测

**建议**：建立 Context Budget 管理器：

```python
class ContextBudget:
    max_input_tokens: int = 2000  # 每个 Agent 的输入预算
    max_output_tokens: int = 500   # 每个 Agent 的输出预算
    compression_strategy: "truncate" | "summarize" | "select"
    
    def apply(self, agent: str, input: str) -> str:
        # 根据 Agent 角色和预算策略压缩输入
        pass
```

### 问题 4: 缺少 HITL（Human-in-the-Loop）门控

**现状**：Agent 决策结果（如 diff 采纳）直接展示给用户，没有"自动采纳"和"人工审核"的区分。

**影响**：
- 低置信度 diff 可能被误采纳
- 用户信任度降低

**建议**：引入置信度门控：

```python
CONFIDENCE_GATES = {
    "high": "auto_accept",       # 自动采纳
    "medium": "suggest",         # 建议，用户确认
    "low": "require_review",     # 必须人工审核
}
```

### 多 Agent 架构改造建议

```
P0：
├── 引入部分成功模式（StageResult）
├── 添加 trace_id 贯穿 pipeline
└── 建立 Context Budget 管理器

P1：
├── 添加 Agent 输入/输出日志
├── 实现置信度门控（HITL）
├── 添加 Agent 级 metrics（成功率、平均耗时、回退率）
└── 建立 Agent 拓扑图可视化

P2：
├── 引入 Evaluator Agent 作为质量门
├── 实现 Agent 自动回退链（role → default → degraded）
└── 建立 Agent 行为测试套件
```

---

## 五、综合优先级

### P0 — 下一轮必须完成

| 项目 | 来源框架 | 工作量 | 影响 |
|------|---------|--------|------|
| 拆分 job_library.py 为 package | Backend Architect | 中 | 可维护性↑ |
| 统一 Prompt 版本号 + 约束节 | Prompt Engineer | 小 | 质量↑ |
| 引入部分成功模式 (StageResult) | Multi-Agent Architect | 中 | 可靠性↑ |
| 添加 trace_id 贯穿 pipeline | Multi-Agent Architect | 中 | 可观测性↑ |
| 前端内存缓存层 | Frontend Developer | 小 | 性能↑ |

### P1 — 建议完成

| 项目 | 来源框架 | 工作量 |
|------|---------|--------|
| API 添加 /api/v1 前缀 | Backend Architect | 小 |
| 异步作业重启恢复 | Backend Architect | 中 |
| Prompt 测试套件 | Prompt Engineer | 中 |
| Context Budget 管理器 | Multi-Agent Architect | 中 |
| 前端虚拟滚动 | Frontend Developer | 中 |

### P2 — 可延后

| 项目 | 来源框架 |
|------|---------|
| 前端框架迁移评估 | Frontend Developer |
| 所有端点契约测试 | Backend Architect |
| 业务逻辑与 Prompt 分离 | Prompt Engineer |
| Agent 置信度门控 | Multi-Agent Architect |
| 前端构建工具链 | Frontend Developer |
