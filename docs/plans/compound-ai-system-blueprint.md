# ResuAlign Compound AI System 架构蓝图

**基于**: 2026-08-18 工程评审 + 用户约束
**核心原则**: DAG + 轻量状态机 + MCP + 事实锚定

---

## 一、架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│  MCP Protocol Layer (FastMCP)                                    │
│  ├── Tool: fetch_jd(url) → Job                                  │
│  ├── Tool: profile_jd(jd_id) → JDProfile                        │
│  ├── Tool: analyze_gaps(resume_id, jd_id) → GapReport           │
│  ├── Tool: tailor_resume(resume_id, gap_id) → TailoredResume    │
│  ├── Tool: evaluate(tailored_id) → EvalScore                    │
│  ├── Tool: record_application(job_id) → Status                  │
│  └── Tool: create_followup(job_id, due_at) → Reminder           │
└───────────────────────┬──────────────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────────────┐
│  State Graph Layer (DAG + Bounded Loops)                        │
│                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐   │
│  │ JD       │───→│ JD       │───→│ Gap      │───→│ Tailor   │   │
│  │ Profiler │    │ Analysis │    │ Analysis │    │ Editor   │   │
│  └──────────┘    └──────────┘    └──────────┘    └────┬─────┘   │
│       │                                                 │        │
│       │ (max 1 retry)                                   │        │
│       ▼                                                 ▼        │
│  ┌──────────┐                                    ┌──────────┐    │
│  │ Fallback │                                    │ Evaluate │    │
│  │ Router   │                                    │ (Quality)│    │
│  └──────────┘                                    └────┬─────┘    │
│                                                       │          │
│                                                       ▼          │
│                                              ┌──────────────┐    │
│                                              │ Applied /    │    │
│                                              │ Follow-up    │    │
│                                              └──────────────┘    │
└───────────────────────┬──────────────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────────────┐
│  LLM Role Layer (5 个结构化决策节点)                              │
│  ├── diagnose:  Resume → Score + Skills + Issues                 │
│  ├── profiler:  JD → Structured Profile (JSON Schema)            │
│  ├── gap_analyzer: Resume + Profile → GapReport (JSON)           │
│  ├── editor:    Resume + Gap → Tailored Sections + Diffs         │
│  └── evaluator: Original + Tailored + JD → EvalScore             │
└──────────────────────────────────────────────────────────────────┘
```

---

## 二、决策节点规范（LLM 的受限边界）

### 节点类型

| 节点 | 输入 | 输出 | LLM 决策范围 | 回退路径 |
|------|------|------|-------------|---------|
| diagnose | resume_text | Score, Skills, Issues | 仅提取结构化字段 | 无 LLM：返回空结果 |
| profiler | jd_text | JDProfile | 仅提取结构化字段 | 无 LLM：返回空结果 |
| gap_analyzer | resume + profile | GapReport | 仅比较 + 列表输出 | 无 LLM：返回空列表 |
| editor | resume + gap + jd | TailoredResume | 仅改写命中段 | 无 LLM：返回原文 |
| evaluator | original + tailored + jd | EvalScore | 仅评分 | 无 LLM：返回默认分 |

**核心约束**：
- 每个节点输出必须是 **Pydantic Schema** 约束的 JSON
- Editor 的 provenance 字段必须引用原文段落
- 任何节点不得自由扩写/自省/修正输入

### 决策门

```
profiler 结果 → [confidence < 0.7] → 标记 degraded，仍继续
gap_analyzer 结果 → [gap_count == 0] → 跳过 editor
editor 结果 → [provenance 丢失 > 20%] → 标记 degraded，仍继续
evaluator 结果 → [score < 60] → 标记 degraded，不阻塞输出
```

---

## 三、状态图实现（轻量级）

### 核心状态机

```python
# states.py
from enum import Enum, auto

class JobState(Enum):
    IMPORTED = auto()
    PROFILED = auto()
    ANALYZED = auto()
    ALIGNED = auto()
    APPLIED = auto()
    INTERVIEWING = auto()
    OFFERED = auto()
    DECLINED = auto()
    DEGRADED = auto()  # 部分成功，非阻塞

class StageState(Enum):
    PENDING = auto()
    RUNNING = auto()
    SUCCEEDED = auto()
    FAILED = auto()
    FALLBACK_USED = auto()
    SKIPPED = auto()
```

### 状态转换

```python
# dag.py - 有向无环图定义
PIPELINE_DAG = {
    "start": ["diagnose"],
    "diagnose": ["profiler"],
    "profiler": ["gap_analyzer"],
    "gap_analyzer": ["editor", "skip_editor"],  # 条件分支
    "editor": ["evaluator"],
    "skip_editor": ["evaluator"],
    "evaluator": ["end"],
}

# 条件分支逻辑
def route_after_gap(report: GapReport) -> str:
    """Gap 为空时跳过 editor，直接评估"""
    return "skip_editor" if not report.has_gaps() else "editor"
```

### 轻量执行引擎

```python
# engine_v2.py - 替代当前 engine.py
class PipelineEngine:
    def __init__(self, dag: dict, state_store: StateStore):
        self.dag = dag
        self.store = state_store
    
    async def run(self, job_id: str, context: RunContext) -> PipelineResult:
        current = "start"
        results = {}
        while current != "end":
            node = self._get_node(current)
            # 确定分支
            if node.is_decision:
                current = node.decide(context, results)
            else:
                # 执行 LLM 节点
                result = await self._execute_node(node, context, results)
                results[current] = result
                current = self._next_node(current, result)
        return PipelineResult(results=results)
```

---

## 四、MCP 工具契约

### 工具粒度：中粒度（按功能分组）

```python
# tools/jd.py - JD 相关工具
@mcp.tool()
def fetch_jd(url: str) -> Job: ...
@mcp.tool()
def profile_jd(jd_id: str) -> JDProfile: ...

# tools/resume.py - 简历相关工具
@mcp.tool()
def diagnose_resume(resume_id: str) -> Diagnosis: ...
@mcp.tool()
def analyze_gaps(resume_id: str, jd_id: str) -> GapReport: ...
@mcp.tool()
def tailor_resume(resume_id: str, gap_id: str) -> TailoredResume: ...

# tools/application.py - 投递相关工具
@mcp.tool()
def record_application(job_id: str) -> Application: ...
@mcp.tool()
def create_followup(job_id: str, due_at: str) -> Reminder: ...
```

### 工具契约

每个 MCP 工具必须满足：
1. **输入 Schema**：Pydantic model 定义
2. **输出 Schema**：Pydantic model 定义
3. **错误处理**：返回结构化错误，不抛异常
4. **幂等性**：同参数多次调用结果一致
5. **超时**：每个工具独立超时配置

---

## 五、Provenance 锚定（不变铁律）

### 数据流

```
Master Resume (单一事实源)
    │
    ├──→ diagnose: 只读，不修改
    ├──→ gap_analyzer: 只读，不修改
    ├──→ editor: 读取 → 输出改写版本 + provenance 引用
    │       │
    │       └──→ 每个 diff 必须有 provenance_quote 指向原文
    │
    └──→ evaluator: 只读，不修改
```

### Provenance 验证

```python
class ProvenanceValidator:
    """验证每个 diff 的 provenance 是否可追溯到 Master Resume"""
    
    def verify(self, diff: DiffItem, master_resume: str) -> bool:
        if diff.type == "remove":
            return diff.original in master_resume
        if diff.type == "modify":
            return diff.original in master_resume
        if diff.type == "add":
            return True  # 新增内容不需要 provenance
        return False
    
    def batch_verify(self, diffs: list[DiffItem], master: str) -> VerificationReport:
        total = len(diffs)
        verified = sum(1 for d in diffs if self.verify(d, master))
        return VerificationReport(
            total=total,
            verified=verified,
            ratio=verified / total if total > 0 else 1.0,
            threshold=0.8,  # 80% 以上验证通过即可
            passed=(verified / total >= 0.8) if total > 0 else True,
        )
```

---

## 六、轻量框架选型

### 状态机

```python
# 使用 transitions 库（无外部依赖，纯 Python）
from transitions import Machine

class JobLifecycle:
    states = ["imported", "profiled", "analyzed", "aligned", "applied", 
              "interviewing", "offered", "declined", "degraded"]
    
    transitions = [
        {"trigger": "profile", "source": "imported", "dest": "profiled"},
        {"trigger": "analyze", "source": "profiled", "dest": "analyzed"},
        {"trigger": "align", "source": "analyzed", "dest": "aligned"},
        {"trigger": "apply", "source": "aligned", "dest": "applied"},
        {"trigger": "interview", "source": "applied", "dest": "interviewing"},
        {"trigger": "offer", "source": "interviewing", "dest": "offered"},
        {"trigger": "decline", "source": "*", "dest": "declined"},
        {"trigger": "degrade", "source": "*", "dest": "degraded"},
        {"trigger": "retry", "source": "degraded", "dest": "imported"},
    ]
```

### DAG 执行引擎

```python
# 自建轻量 DAG，不引入 LangGraph
class DAGExecutor:
    """有向无环图执行器，每个节点可退化为确定性函数"""
    
    def __init__(self):
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, list[str]] = {}
    
    def add_node(self, name: str, fn: Callable, is_llm: bool = False):
        self.nodes[name] = Node(name=name, fn=fn, is_llm=is_llm)
    
    def add_edge(self, source: str, target: str, condition: Callable = None):
        self.edges.setdefault(source, []).append((target, condition))
    
    async def execute(self, context: dict) -> dict:
        # 拓扑排序，顺序执行
        order = self._topological_sort()
        results = {}
        for node_name in order:
            if node_name in results:
                continue
            node = self.nodes[node_name]
            result = await node.fn(context, results)
            results[node_name] = result
            # 确定下一个节点
            next_nodes = self.edges.get(node_name, [])
            if len(next_nodes) == 1:
                continue  # 继续执行下一个
            elif len(next_nodes) > 1:
                # 条件分支
                for target, condition in next_nodes:
                    if condition is None or condition(context, results):
                        results[target] = None  # 标记为已调度
                        break
        return results
```

---

## 七、实施路线

### Phase 1 — 状态机封装（当前即可做）

```
├── 提取 JobLifecycle 状态机（transitions 库）
├── 将当前 engine.py 的 5 阶段改为 DAG 节点
├── 添加条件分支（gap 为空时跳过 editor）
└── 添加部分成功结果（StageResult）
```

### Phase 2 — MCP 工具标准化

```
├── 将当前 3 个 MCP 工具拆为 7 个中粒度工具
├── 每个工具添加独立超时和 schema
├── 添加工具幂等性验证
└── 添加工具调用日志（trace_id）
```

### Phase 3 — 决策节点强化

```
├── 为每个 LLM 节点添加置信度门控
├── 添加 ProvenanceValidator
├── 添加 degraded 路径（非阻塞降级）
└── 添加 HITL 门控（低置信度转人工）
```

### 明确不做

- 多 Agent 辩论（禁止）
- 开放式自主规划（禁止）
- Agent 自由扩写简历（禁止）
- 引入 LangGraph / CrewAI（禁止）
- 服务化部署（保持 Local-first）
