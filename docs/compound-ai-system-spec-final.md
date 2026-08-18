# ResuAlign Compound AI System — 最终架构规格

**基于**: 2026-08-18 用户决策（Q1-Q4 全部收敛）
**修订**: 2026-08-18

---

## 一、双层状态图架构

### 外层：业务生命周期 FSM（异步持久化）

```
┌─────────────────────────────────────────────────────────────────────┐
│                     JobLifecycle FSM                                 │
│  SQLite 持久化，受 HITL / 外部事件驱动，存活周期数周                   │
│                                                                      │
│  IMPORTED ──→ DIAGNOSED ──→ TAILORED ──→ APPLIED ──→ INTERVIEWING   │
│     │              │             │            │         │           │
│     │              │             │            │         ├──→ OFFER  │
│     │              │             │            │         └──→ REJECTED│
│     │              │             │            │                      │
│     └──→ BLOCKED ←┘             │            │                      │
│          │                      │            │                      │
│          └──→ RETRY ────────────┘            │                      │
│                                               │                      │
│          [Auto Follow-up] ←───────────────────┘                      │
└─────────────────────────────────────────────────────────────────────┘
```

**外层 FSM 触发条件**：
- `IMPORTED → DIAGNOSED`：内层 Graph 完成诊断后自动触发
- `DIAGNOSED → TAILORED`：内层 Graph 完成对齐后自动触发
- `TAILORED → APPLIED`：用户手动标记"已投递"
- `APPLIED → INTERVIEWING`：用户手动标记
- `INTERVIEWING → OFFER/REJECTED`：用户手动标记
- `* → BLOCKED`：内层 Graph 返回不可恢复错误
- `BLOCKED → RETRY`：用户手动或自动重试

### 内层：单次执行流水线 Graph（瞬时状态图）

```
┌─────────────────────────────────────────────────────────────────────┐
│                   Alignment Graph (DAG)                              │
│  短生命周期（秒级/分钟级），执行完后终态触发外层 FSM 更新              │
│                                                                      │
│  START ──→ JD Profiling ──→ Gap Analysis ──→ STAR Tailoring         │
│    │            │                │                 │                │
│    │            │                │                 │                │
│    │            ▼                ▼                 ▼                │
│    │       [Hard Gate]     [Hard Gate]      [Provenance Gate]       │
│    │       · 年限/学历      · 关键词密度     · 实体词必须属于        │
│    │       · 敏感词过滤     · 面要性排序      Master Resume 集合     │
│    │            │                │                 │                │
│    │            └────────────────┼─────────────────┘                │
│    │                             ▼                                  │
│    │                     Anti-Hallucination Gate                    │
│    │                     · 事实校验拦截                              │
│    │                     · 实体锚定验证                              │
│    │                             │                                  │
│    │                    ┌────────┴────────┐                         │
│    │                    ▼                 ▼                         │
│    │              [PASS]              [FAIL]                        │
│    │                    │                 │                         │
│    │                    ▼                 ▼                         │
│    │              ATS Scoring      [Agent 定向修复]                  │
│    │                    │            (max 1 retry)                  │
│    │                    │                 │                         │
│    │                    └────────┬────────┘                         │
│    │                             ▼                                  │
│    │                     COMPLETED / BLOCKED                        │
│    │                             │                                  │
│    │                             ▼                                  │
│    │                  触发外层 FSM 状态更新                          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 二、执行机制分工

### 硬编码确定性逻辑（Deterministic Rules）

| 环节 | 规则 | 实现方式 | 拦截条件 |
|------|------|---------|---------|
| 原始文本清洗 | 去除 HTML 标签、空白压缩 | 正则 | 自动 |
| AST 结构提取 | 简历/JD 的章节解析 | 正则 + 行号匹配 | 自动 |
| 硬性门槛过滤 | 工作年限、学历、敏感词 | 代码比较 | 不满足则标记 BLOCKED |
| 事实溯源（Provenance） | 改写结果中的实体词必须属于 Master Resume | 集合比较 | 低于 80% 则标记 FAILED |
| ATS 关键词密度 | 硬性关键词匹配打分 | 关键词集合 | 自动 |

### 受限 Agent 决策点（Constrained LLM Decisions）

| 决策点 | 触发条件 | 输入 | 输出 | 退出条件 |
|--------|---------|------|------|---------|
| 改写风格路由 | 进入 STAR Tailoring 前 | JD Profile | 风格选择（业务深耕型 / 底层架构型 / 通用型） | 输出一个枚举值 |
| 动态重试与定向修复 | Provenance Gate FAILED | Evaluator 反馈 + 原文 | 修正 Prompt 注入 | 最多 1 次重试 |
| HITL 阻断决策 | 匹配度低于置信阈值 | Gap Report + Profile | 终止生成 / 生成补全卡片 | 输出决策枚举值 |

---

## 三、轻量 Pydantic State Graph

### 状态上下文

```python
# graph/state.py
from pydantic import BaseModel
from typing import Optional, List, Literal
from enum import Enum

class AlignmentStatus(str, Enum):
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEGRADED = "DEGRADED"  # 部分成功，但降级

class AlignmentState(BaseModel):
    """单个对齐任务的瞬时状态上下文"""
    job_id: str
    resume_text: str
    jd_text: str
    
    # 各阶段产物
    jd_profile: Optional[dict] = None
    gap_report: Optional[dict] = None
    tailored_draft: Optional[dict] = None
    eval_score: Optional[dict] = None
    
    # 执行追踪
    retry_count: int = 0
    max_retries: int = 1
    current_node: str = "start"
    completed_nodes: List[str] = []
    status: AlignmentStatus = AlignmentStatus.RUNNING
    errors: List[dict] = []
    fallback_used: bool = False
```

### 节点路由

```python
# graph/router.py
NODE_ROUTER: dict[str, dict] = {
    "start": {
        "next": "jd_profiling",
        "type": "pass_through",
    },
    "jd_profiling": {
        "next": "hard_gate_1",
        "type": "llm",
        "role": "profiler",
        "timeout": 15.0,
        "fallback_role": "profiler",
        "max_retries": 1,
    },
    "hard_gate_1": {
        "next": "gap_analysis",
        "type": "deterministic",
        "gate": "years_experience >= min_years and education matches",
        "block_action": "mark_blocked",
    },
    "gap_analysis": {
        "next": "style_router",
        "type": "llm",
        "role": "gap_analyzer",
        "timeout": 15.0,
    },
    "style_router": {
        "next": "star_tailoring",
        "type": "llm_decision",
        "role": "editor",
        "decision": "route_style(jd_profile)",
        "output": "tailor_style",
    },
    "star_tailoring": {
        "next": "provenance_gate",
        "type": "llm",
        "role": "editor",
        "timeout": 40.0,
    },
    "provenance_gate": {
        "next": "anti_hallucination_gate",
        "type": "deterministic",
        "gate": "provenance_ratio >= 0.8",
        "fail_action": "request_retry",
    },
    "anti_hallucination_gate": {
        "next": "ats_scoring",
        "type": "deterministic",
        "gate": "all_entities_in_master_resume",
        "fail_action": "mark_degraded",
    },
    "ats_scoring": {
        "next": "end",
        "type": "deterministic",
        "scorer": "keyword_density + structure_score + experience_match",
    },
    "end": {
        "type": "terminal",
        "action": "trigger_fsm_transition",
    },
}
```

### 轻量执行引擎

```python
# graph/executor.py
class GraphExecutor:
    """Pydantic 驱动的轻量 DAG 执行器，不支持 LangGraph"""
    
    def __init__(self, router: dict, llm_roles: dict):
        self.router = router
        self.llm_roles = llm_roles
    
    async def run(self, state: AlignmentState) -> AlignmentState:
        current = "start"
        while current != "end" and state.status == AlignmentStatus.RUNNING:
            node = self.router[current]
            state.current_node = current
            
            if node["type"] == "pass_through":
                current = node["next"]
                
            elif node["type"] == "deterministic":
                result = await self._run_deterministic(node, state)
                if not result["passed"]:
                    action = node.get("fail_action", "mark_failed")
                    state = self._apply_action(state, action, result)
                current = node["next"]
                
            elif node["type"] == "llm":
                result = await self._run_llm_node(node, state)
                state = self._update_state(state, current, result)
                current = node["next"]
                
            elif node["type"] == "llm_decision":
                decision = await self._run_llm_decision(node, state)
                state.outputs[decision["output"]] = decision["value"]
                current = node["next"]
                
            elif node["type"] == "terminal":
                state.status = AlignmentStatus.COMPLETED
            
            state.completed_nodes.append(current)
        
        return state
```

---

## 四、4 个中粒度 MCP 工具

### 工具 1: `job_ingest_and_profile`

```python
@mcp.tool()
async def job_ingest_and_profile(
    source: str,           # URL 或 raw text
    source_type: str,      # "url" | "text"
) -> JobProfileResult:
    """
    接收 URL 或 Raw Text，完成解析并返回结构化 JD 画像与硬门槛。
    
    内部流程：
    1. URL 抓取 / 文本清洗（确定性）
    2. AST 结构提取（确定性）
    3. JD Profiler（LLM 角色）
    4. 硬门槛过滤（确定性）
    
    输出：
    - jd_profile: 结构化 JD 画像
    - hard_gates: 年限/学历/敏感词门槛
    - classification: 岗位分类标签
    """
```

### 工具 2: `resume_align_and_tailor`

```python
@mcp.tool()
async def resume_align_and_tailor(
    job_id: str,
    resume_id: str,
    style: Optional[str] = None,  # 改写风格，可选覆盖
) -> AlignmentResult:
    """
    传入 Job ID 与 Master Profile ID，执行完整 Graph 编排流水线。
    
    内部流程（Graph 执行）：
    1. Gap Analysis（LLM 角色）
    2. 改写风格路由（LLM 决策）
    3. STAR Tailoring（LLM 角色）
    4. Provenance Gate（确定性）
    5. Anti-Hallucination Gate（确定性）
    6. ATS Scoring（确定性）
    
    输出：
    - diff_report: 逐条 diff 含 provenance
    - ats_score: 关键词密度评分
    - status: COMPLETED / DEGRADED / BLOCKED
    - errors: 非阻塞错误列表
    """
```

### 工具 3: `job_tracker_manage`

```python
@mcp.tool()
async def job_tracker_manage(
    job_id: str,
    action: str,           # "apply" | "update_stage" | "log_note" | "set_reminder"
    stage: Optional[str] = None,
    note: Optional[str] = None,
    due_at: Optional[str] = None,
) -> TrackerResult:
    """
    管理外部看板状态流转。
    
    动作：
    - apply: 标记已投递，创建 3 天跟进提醒
    - update_stage: 更新面试轮次
    - log_note: 记录沟通日志
    - set_reminder: 设置跟进提醒
    """
```

### 工具 4: `master_resume_query`

```python
@mcp.tool()
async def master_resume_query(
    resume_id: str,
    query: str,            # 关键词或语义搜索
    top_k: int = 5,
) -> list[ExperienceFragment]:
    """
    基于关键词或语义检索用户的原子经历库（STAR 经历片段）。
    
    输入：
    - resume_id: 简历 ID
    - query: 搜索关键词（如"Redis 高并发"）
    - top_k: 返回结果数
    
    输出：
    - experience_fragments: 匹配的 STAR 经历片段列表
      - 每个片段包含：situation, task, action, result, tags
      - 来源引用（provenance）
    """
```

---

## 五、Provenance 与防幻觉体系

### 双层校验

```
第一层：Provenance Gate（确定性）
  - 在 STAR Tailoring 完成后立即执行
  - 提取改写结果中的所有实体词（技能名、技术栈、项目名、数字指标）
  - 检查每个实体词是否属于 Master Resume 集合
  - 阈值：≥ 80% 通过，否则触发定向修复

第二层：Anti-Hallucination Gate（确定性）
  - 在 Provenance Gate 通过后执行
  - 交叉验证：ATSScore 中的关键词是否全部在 Master Resume 中出现
  - 检查数字指标（QPS、延迟、覆盖率）是否与原文一致
  - 发现不一致时标记 DEGRADED 但不阻塞输出
```

### 定向修复流程

```
Provenance Gate FAILED (ratio < 80%)
    │
    ▼
[Agent 定向修复] —— max 1 次重试
    │
    ├── 输入：Evaluator 反馈 + 原文 + 改写结果
    ├── 输出：修正 Prompt 注入
    ├── 注入到 STAR Tailoring 节点重跑
    └── 重跑后再次通过 Provenance Gate
    
    ├── 通过 → 继续 ATS Scoring
    └── 仍失败 → 标记 DEGRADED，继续输出（不阻塞）
```

---

## 六、实施顺序

### Phase 1（当前可做）

```
├── 提取 GraphExecutor 框架（基于现有 engine.py 的 5 阶段）
├── 添加 AlignmentState Pydantic model
├── 添加 NODE_ROUTER 配置字典
├── 添加硬编码门控（provenance gate、anti-hallucination gate）
├── 添加定向修复逻辑（max 1 retry）
└── 添加 DEPLOYED 状态（部分成功，非阻塞）
```

### Phase 2

```
├── 提取外层 JobLifecycle FSM（基于现有 job_library.py 的状态管理）
├── 内层 Graph 完成时自动触发外层 FSM 状态更新
├── 添加 4 个中粒度 MCP 工具
├── 为每个工具添加独立超时和 Schema
└── 添加 trace_id 贯穿所有节点
```

### Phase 3

```
├── 添加 HITL 阻断决策点
├── 添加改写风格路由（LLM 决策）
├── 添加前端 Graph 拓扑可视化（非阻塞）
└── 添加 Graph 执行日志追踪
```

### 明确不做

- 多 Agent 辩论
- 开放式自主规划
- Agent 自由扩写简历
- 引入 LangGraph / CrewAI
- 引入 LangChain 生态
