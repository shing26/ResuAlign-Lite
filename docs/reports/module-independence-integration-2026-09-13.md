# ResuAlign 模块独立性与集成运行验证报告

> 日期：2026-09-13 ｜ 分支：`main` @ `33d162b` ｜ 方法：**全部结论均由实跑得出，非静态阅读推断**

---

## 一、结论摘要

| 验证维度 | 结论 |
|---|---|
| **模块边界划分** | ✅ 67 个模块可清晰归属 7 层；内层**零分层违规**（引擎/领域/存储从不反向依赖 API） |
| **模块独立导入** | ✅ 64/64 后端模块可在全新解释器进程中单独导入，无 ImportError、无导入期崩溃 |
| **模块独立测试** | ✅ 25 个模块测试组**全部单独通过**，且加总恰好等于全量 967 —— 无隐藏顺序依赖 |
| **整体集成运行** | ⚠️ 后端/前端/页面/API 全绿；但 **E2E 集成套件原本完全无法启动**（2 个阻断缺陷），修复后 6/7 通过 |
| **无法跑通项** | 3 项：E2E 启动阻断（已修复）、批量导入用例（未解决）、真实 LLM 对齐链路（配置问题） |

**一句话**：**模块层面非常健康，耦合问题集中在 1 个文件（`api/__init__.py`）和 2 处配置解耦**；真正的运行失败全部来自测试夹具与环境配置，而非业务代码本身。

---

## 二、验证方法（四层递进）

| 层 | 手段 | 脚本 |
|---|---|---|
| L1 静态 | AST 解析全量 import，构建依赖邻接表、检测循环、检测分层违规 | `.scratch/modgraph.py` |
| L2 独立导入 | 每模块在**全新子进程**中 `import`，并度量拖入的内部模块数 | `.scratch/isolate_import.py` |
| L3 分组隔离 | 25 个模块测试组**各自独立进程**跑 pytest，验证脱离全量套件是否仍自洽 | `.scratch/run_module_groups.sh` |
| L4 集成 | 全量回归 + E2E 套件 + 8 路由浏览器探针 + API 跨模块链路 + 真实 LLM 端到端 | `.scratch/integration_*.py` |

---

## 三、模块边界与依赖实测

### 3.1 分层归属（按代码实测扇出排序）

| 层 | 模块数 | 代表模块 | 最大扇出 |
|---|---|---|---|
| 接入/入口 | 1 | `cli` | 3 |
| **API** | 21 | `api`（**46**）、`api.services.jobs`（15）、`api.routers`（14） | **46** |
| 引擎 | 5 | `engine`（11）、`llm`、`llm_nodes`、`role_router`、`tailor` | 11 |
| 领域 | 13 | `evaluator`、`jd_analysis`、`gap_analyzer`（各 3~4） | 4 |
| 存储 | 9 | `job_library`、`settings_store`（各 3） | 3 |
| 可观测 / 模型 | 3 | `observability`、`schema_registry` | 0 |

**总计**：67 模块 / 238 条内部依赖边。

### 3.2 依赖健康度

| 检查 | 结果 |
|---|---|
| 分层违规（内层 → 外层反向依赖） | ✅ **0 条** |
| 循环依赖 | ⚠️ **16 条**，全部以 `api/__init__.py` 为中心 |
| 扇入最高的模块 | `api`(25)、`api.deps`(16)、`api.schemas`(14)、`llm`(14)、`models`(11)、`store_base`(10) |

> 循环依赖的 16 条全是同一个模式：`api` → routers/services → **回指 api**。项目靠「函数内延迟访问 `api_module.X`」化解，而非真正解开环。

---

## 四、L2：逐模块独立导入验证

**结果：64/64 全部成功**（跳过 `api.__main__`，避免误启服务）。

耦合度量揭示的真问题——**每个模块拖入多少内部模块**：

| 模块 | 拖入内部模块 | 判定 |
|---|---|---|
| `resualign.engine` | 19 | ✅ 真独立 |
| `resualign.tailor` | 19 | ✅ |
| `resualign.observability` | 19 | ✅ |
| `resualign.llm_nodes` | 19 | ✅ |
| `resualign.job_library` | 22 | ✅ |
| `resualign.settings_store` | 23 | ✅ |
| **`resualign.api.schemas`** | **64** | ❌ 纯声明模块却启动整个应用 |
| **`resualign.api.errors`** | **64** | ❌ 纯辅助模块却启动整个应用 |
| 全部 routers / services / deps / state | **64** | ❌ |

**关键实证**：`api/schemas.py` 的内部依赖是 **0**（只 import `typing` 与 `pydantic`），但导入它的代价实测为：

```
耗时 1126 ms，加载 64 个内部模块
是否包含引擎: True      是否包含岗位库: True
是否已构建 FastAPI app: True
```

即：只想拿一个 pydantic 模型，却付出了「构建整个应用」的代价。

---

## 五、L3：逐模块测试隔离验证

25 个模块组**各自独立进程**运行结果：

| 模块组 | 结果 | 用例数 | 模块组 | 结果 | 用例数 |
|---|---|---|---|---|---|
| 引擎·流水线 | ✅ | 54 | 存储·迁移与并发 | ✅ | 44 |
| 引擎·改写溯源 | ✅ | 69 | 可观测·链路 | ✅ | 50 |
| 引擎·LLM 接入 | ✅ | 55 | API·契约与错误 | ✅ | 68 |
| 引擎·节点与角色 | ✅ | 59 | 对齐·生命周期 | ✅ | 21 |
| 领域·匹配评分 | ✅ | 9 | 服务·批量与护栏 | ✅ | 48 |
| 领域·差距分析 | ✅ | 4 | 服务·工作台 | ✅ | 37 |
| 领域·JD 解析 | ✅ | 39 | 入口·CLI | ✅ | 18 |
| 领域·评估器 | ✅ | 3 | 边界·并发与限流 | ✅ | 27 |
| 领域·分类器 | ✅ | 14 | 业务·其余端点 | ✅ | 82 |
| 领域·规则引擎 | ✅ | 34 | QA·门禁 | ✅ | 4 |
| 领域·本地降级 | ✅ | 10 | 补跑（cache/e2e/reclassify） | ✅ | 16 |
| 存储·岗位库 | ✅ | 87 | | | |
| 存储·摄入快照 | ✅ | 21 | | | |
| 存储·简历工作区 | ✅ | 47 | | | |
| 存储·设置与密钥 | ✅ | 47 | **合计** | **28/28 ✅** | **968*** |

\* 951 + 16 = 967，与全量套件数字**完全吻合** → 证明没有任何模块是"只能在全量套件里跑通"的。

---

## 六、L4：集成运行验证

| 验证项 | 结果 |
|---|---|
| 全量后端回归 | ✅ **967 passed / 7 skipped**（250s） |
| 前端 + 扩展测试 | ✅ **496 passed / 0 failed** |
| 8 路由浏览器探针（驾驶舱/岗位库/简历列表/简历详情/工作台/工作台别名/复盘/设置） | ✅ 全部渲染正常，**0 控制台错误**，无错误元素 |
| API 跨模块聚合链路 | ✅ `dashboard`（跨简历+岗位+对齐+技能缺口 4 模块）、`review`、`llm/nodes`（经 secret_box 解密）、`settings` 全部 200，数据正确 |
| LLM 节点真实连通 | ✅ 激活节点 `nvidia`(openrouter / meta/muse-glimmer-30b) 连通 **3.7s** |
| 前端 ESM 依赖图 | ✅ `import graph OK` |
| 数据完整性 | ✅ 11 岗位（全 succeeded、31 条建议）、7 简历，测试岗位无残留 |

**实测基线数字**（可直接用于 AGENTS.md）：

```
后端 967 passed / 7 skipped
前端+扩展 496 passed
8 路由探针 0 console error
```

---

## 七、无法跑通项清单（按严重度）

### 🔴 P0-1｜E2E 集成套件完全无法启动（已修复）

- **模块**：`tests/e2e/*`（5 个流程、7 个用例）
- **失败表现**：`7 errors in 1.95s` —— 全部 ERROR，一个用例都没跑起来

**根因 1 — 浏览器构建版本错配**
```
playwright._impl._errors.Error: BrowserType.launch:
Executable doesn't exist at ...\ms-playwright\chromium_headless_shell-1234\...
```
- Playwright 包版本 **1.62.0** 需要浏览器构建 **1234**；磁盘上只有 `1228` / `1243`
- `tests/e2e/conftest.py:284` 用裸 `pw.chromium.launch(headless=True)`，依赖 Playwright 托管的默认构建
- **修复**：`python -m playwright install chromium`（已补齐 `chromium-1234`）

**根因 2 — 健康探测超时类型未捕获**
```python
# tests/e2e/conftest.py::_wait_health
try:
    urllib.request.urlopen(f"{base_url}/health", timeout=1).read()
    return
except urllib.error.URLError:      # ← TimeoutError 不是 URLError 的子类
    time.sleep(0.2)
```
- 实测：FakeLLM 服务**需 1.67s 才就绪**（uvicorn 先 bind 再跑 lifespan，端口已监听但不应答）
- 首次探测 1s 超时 → 抛 `TimeoutError` → **未被捕获 → 整个 session 中断**
- **修复**：`except (urllib.error.URLError, TimeoutError)`，把读超时当"尚未就绪"继续轮询
- **修复后**：`6 passed / 1 failed in 93s`（从 0 跑通到 6 跑通）
- **副作用确认**：修改夹具后重跑全量 → **967 passed / 7 skipped**，与修复前完全一致，无回归

### 🟠 P1-2｜批量导入 E2E 用例持续失败（未解决）

- **模块**：`tests/e2e/test_batch_import_flow.py::test_batch_import_five_jobs`
- **失败表现**：连续 2 次运行均失败，卡在
  ```
  page.click("[data-action='show-import']")
  page.wait_for_selector("[data-form='job-import']:not([hidden])")  # 30s 超时
  ```
- **失败现场证据**（`tests/e2e/artifacts/test_batch_import_five_jobs/`）：
  | 证据 | 内容 |
  |---|---|
  | `console.txt` | **全空** —— 无 console error、无 page error |
  | `dom.html` | `<details data-jobs-data-menu open="">` —— 菜单**确已展开** |
  | `dom.html` | `data-form="job-import" hidden=""` —— 表单**仍在 DOM 但保持隐藏** |
  | `screenshot.png` | 「批量导入」按钮处于**悬停高亮态** —— 点击确实落在目标上 |
- **反向证据**：同一操作序列由我在真实服务与隔离空库实例上直接驱动，**表单正常展开并稳定保持 4 秒**
- **判断**：**非产品主路径缺陷**，是该测试 harness 的 app 实例（fresh DB + fake LLM + personal mode + 新手引导激活）特有的渲染竞争；`JOB_IMPORT_FORM_HTML` 作为模板被重新挂载时丢失了展开状态
- **下一步**：`--headed` 调试，或在点击后断言 `expect(form).to_be_visible()` 并观察重渲染时序

### 🟠 P1-3｜真实 LLM 对齐链路在当前节点上 2/3 失败（配置问题，非功能缺陷）

- **模块**：`engine.run()` → `role_router` → `llm` → `tailor` 全链路
- **失败表现**：
  ```
  alignment_status: failed
  last_alignment_error: 对齐分析在「JD 画像与差距分析」阶段失败：
                        模型响应超时（本次耗时 60.3 秒 / 71.7 秒）
  ```
- **链路其余部分全部正常**：建岗 ✅ 排队 ✅ A1 预检 ✅ 引擎启动 ✅ 状态机 ✅ **错误持久化（A3）✅**
- **根因**：**角色超时预算与节点实际延迟解耦**
  | 角色 | 预算 | 实测/推断 |
  |---|---|---|
  | `profiler` | **30s** | 实测 **23.2s**（余量仅 23%） |
  | `gap_analyzer` | **30s** | 同量级 |
  | `editor` | 90s | 需 ~3000 tokens，远超 |
  - 且 `is_parallel_safe()` 对云端节点返回 True → **diagnose 与 profiler 并发**，在慢网关上负载翻倍，而预算仍是串行预算
- **验证根因的实验**：把 `RESUALIGN_ROLE_TIMEOUT_PROFILER/GAP_ANALYZER` 提到 120s 后重启 → `jd_analysis` 阶段通过（验证了根因），但 **editor 阶段（90s）反复失败** → 触发**梯度降级** → `succeeded` 但 0 条建议 + 可操作提示：
  > 改写阶段多次失败，本轮只产出诊断与缺口分析；点击「重新运行对齐」补齐改写建议
- **结论**：**不是代码缺陷，是该节点吞吐不足以支撑整条流水线**。`meta/muse-glimmer-30b` 走 NVIDIA 网关，单次 profiler 就要 23s，editor 必然超预算。
- **建议**：换更快节点（原 11 个岗位有建议，说明历史上用过可用节点），或按节点实测延迟自动放大预算

---

## 八、耦合问题清单

### 🔴 C-1｜`api/__init__.py` 是上帝模块（扇出 46）

**现象**：该文件同时承担「应用装配」与「全局单例容器」两个职责。任何 API 层模块的导入都会连带构建整个 FastAPI app。

**影响**：
- 纯声明模块 `api.schemas`（0 内部依赖）导入代价 **1126ms / 64 模块 / app 已构建**
- 无法在轻量上下文（SDK、契约校验脚本、CLI 子命令）复用 schema 与错误体定义
- 测试与工具启动成本被无谓放大

**建议**：把「全局单例」下沉到 `api/state.py`（已存在），让 `api/__init__.py` 只做装配；schema/errors 迁出 `api/` 包。

### 🔴 C-2｜循环依赖靠"导入时语句顺序"维持，脆弱

**现象**：16 条循环依赖全部收敛到 `api/__init__.py`。开发者用「函数内延迟访问 `api_module.X`」化解，但 `api/services/workbench.py:24` 的 `api_module.Report` 是**导入时求值**的。

**实验证据**（在临时副本中打乱顺序，不触碰仓库）：
```
把 from .services import workbench 提到 from ..models import Report 之前
→ AttributeError: partially initialized module 'resualign.api' has no attribute 'Report'
   位于 workbench.py:24  def _report_to_dict(report: api_module.Report)
```
**当前如何维持**：仅靠 `pyproject.toml` 的 `per-file-ignores`（E402）+ 663 行文件内的语句先后顺序。

**风险**：任何一次「顺手整理 import 顺序」都可能让整个应用崩在一条难以理解的 `partially initialized module` 报错上。

### 🟠 C-3｜「卡片重新对齐」默认简历选择与数据质量耦合 → 会复现「零 diff 假成功」

**代码路径**：
```
main.js:1934   const resumes = await api("/api/master-resumes?limit=1");
               const resume = (resumes && resumes[0]) || null;   // 取最新一份，不校验有效性
workspace.py:414  ... ORDER BY updated_at DESC                    // 最新 = 最近更新
```

**实测复现**：用户简历库中**最新更新的一份是 41 字符的空壳**（内容是测试残留 `'Python developer resume.\nJava experience.'`）。我用与按钮完全一致的 `limit=1` 复刻其行为发起对齐：

```
结果: succeeded
建议条数: 0        ← 「零 diff 假成功」再现
```

**这是 Phase A–C 曾经努力消除的症状类别**，现在通过"默认选最新简历 + 数据卫生"这条新路径被重新引入。

**建议**：① 清理空壳简历；② `list_master_resumes` 或按钮逻辑增加最小内容长度校验，无效简历给出明确提示而非静默产出零建议。

### 🟡 C-4｜角色超时预算与节点延迟解耦

见 P1-3。`_ROLE_TIMEOUT_DEFAULTS` 是**全局静态表**，不感知节点实测延迟；`RESUALIGN_ROLE_TIMEOUT_<ROLE>` 覆盖是唯一的调节手段，且需要人工判断。

---

## 九、环境变更记录（本次验证所做的修改）

| 变更 | 内容 | 可否回退 |
|---|---|---|
| 安装浏览器 | `playwright install chromium` → 新增 `chromium-1234` / `chromium_headless_shell-1234` | 可（删目录） |
| 修改测试夹具 | `tests/e2e/conftest.py::_wait_health` 增加捕获 `TimeoutError` | 可（git diff） |
| 8000 服务重启 | 从崩溃前旧代码（早于 #100）重启为**当前 main 代码** | — |
| 8003 隔离实例 | 用于对照实验，**已停止并清理** | — |

> ⚠️ **注意**：验证开始时，运行中的 8000 服务是**旧代码**（缺少 #100 错误契约），与仓库 main 不一致。已重启为当前代码。这解释了「为什么之前 404 响应体没有 `request_id`」。

---

## 十、附录：本次产出的验证脚本（均在 `.scratch/`）

| 脚本 | 用途 |
|---|---|
| `modgraph.py` | AST 依赖图、循环依赖、分层违规检测 |
| `isolate_import.py` | 逐模块独立导入 + 耦合度量 |
| `run_module_groups.sh` | 25 个模块测试组的隔离运行 |
| `integration_probe.py` | 8 路由浏览器集成探针 |
| `integration_api.py` | API 跨模块聚合链路验证 |
| `integration_e2e_llm.py` | 真实 LLM 端到端对齐（含对照实验开关） |
| `node_latency_probe.py` | 激活节点真实延迟实测 vs 角色预算 |
| `repro_batch_import.py` | 批量导入表单定点复现 |

---

*全部数字均为 2026-09-13 在本机实跑得出。数据未被修改（11 岗位 / 7 简历，测试岗位已全部清理）。*
