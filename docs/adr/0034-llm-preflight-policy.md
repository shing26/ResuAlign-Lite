# ADR-0034: LLM 预检策略（节点类型区分快速失败）

**状态**: 已接受
**日期**: 2026-08-31

---

## 背景

Phase A1（2026-08-30）在 workbench 排队前引入 `_probe_active_llm_quick`
来做节点预检，但当时只对 HTTP 401/402/403 做确定性失败拦截，网络错误/超时
全部非阻塞。这个策略对远程云服务（如 DeepSeek）是合理的——瞬时网络抖动不应
阻塞排队——但对本地 Ollama 节点有问题：本地服务未启动时，每次对齐等待 90s
角色超时再失败，用户体验差。

此外，Phase A1 的实现有一个隐蔽 bug：`_probe_active_llm_quick` 内部使用了
`from .routers.settings import probe_llm_connection` 相对导入，但实际
`routers` 包不在 `resualign.api.services` 下，该导入在运行时抛出
ImportError 被 `except Exception: return True, ''` 静默吞掉，导致 A1 预检
在生产路径上从未生效。Phase E 修复为 `from ..routers.settings import`。

## 决策

预检策略按节点类型区分：

1. **HTTP 401/402/403**：所有节点硬拦截，返回 422 + 引导文案（"模型账户欠费"、
   "请检查设置"等）。这是确定性鉴权/额度失败，与节点类型无关。
2. **本地节点（Ollama 或 localhost/127.0.0.1/0.0.0.0/[::1] base_url）的
   network_error / timeout**：硬拦截为 422 + 引导。本地服务未启动或超时是
   确定性失败，等待 90s 角色超时再慢速失败没有意义。Ollama provider 默认
   视为本地（即使 base_url 指向远程 LAN IP，也因为 Ollama 是个人开发工具，
   同 LAN 的不可达同样应快速失败）。
3. **远程节点的 network_error / timeout**：保持非阻塞，排队继续，失败由
   `last_alignment_error` 延迟透出。云服务瞬时网络抖动不应阻断一次对齐。
4. **每租户单线程排队**：不考虑节点类型，所有对齐运行共用每租户一个
   `threading.Lock`，避免慢速本地 Ollama 7B 被并发请求拖垮。`_run_job` 先
   获取租户门再获全局 `_WORKER_SEMAPHORE`，防止同一个租户塞满所有全局槽位。

## 实现

- `_probe_active_llm_quick` 中的 `_is_local_node(provider, base_url)` 函数
  判断节点类型：provider 为 ollama 或 hostname 匹配 localhost/127.0.0.1/
  0.0.0.0/[::1] 时为本地。
- 本地节点的 network_error/timeout 走 `return False, message` 分支。
- 远程节点仍走 `return True, ''`，让 job 入队后由 `_run_job` 的运行时失败
  通过 `last_alignment_error` 透出。
- 每租户门：`_get_tenant_run_gate` 返回一个 `threading.Lock`，按 tenant_id
  单例缓存。`_run_job` 在获取 `_WORKER_SEMAPHORE` 前先获取该锁。

## 为什么不

- **不对远程节点也做硬拦截**：云服务 5s 探针超时可能是公网不稳定，放行让
  对齐进入 90s 角色超时并透出具体错误，用户可据此判断是网络问题还是节点配置。
- **不允许并发**：Ollama 7B 单线程服务对并发请求无保护，同时跑两个对齐会
  互相拖慢到 2x 甚至 3x 时间，且增加 OOM 风险。多租户间通过全局
  `_WORKER_SEMAPHORE` 控制并发总数（current=1）。

## 后果

- 本地 Ollama 关闭/超时 → 点击对齐立即 422 + 引导，用户感知从"卡住 90s"降为"即时反馈"。
- 远程网络抖动 → 不误伤，对齐正常排队，失败由 `last_alignment_error` 透出。
- 每租户同一时间只有一个对齐在运行，Ollama 7B 不会被并发拖垮。
- 测试策略：`test_phase_e.py` 中的 probe 分支测试需 mock 节点返回值和
  `probe_llm_connection` 返回值，验证本地/远程的正确拦截/放行。
- 该策略记录在 CONTEXT.md 的「节点预检」词汇中。
- 测试 `stub_workbench_llm_probe`（conftest.py）保持 autouse，但只 stub
  `api_module._probe_active_llm_quick` 本身，不覆盖 Phase E 新增的行为分支。
  Phase E 新增的 probe 测试直接调用 `_probe_active_llm_quick` 函数源码。
- **已修复的 A1 bug**：`_probe_active_llm_quick` 内部相对导入路径从
  `from .routers.settings` 修正为 `from ..routers.settings`，确保预检在生产
  路径上实际生效。A1 的现有测试通过 `stub_workbench_llm_probe` 绕过了此函数，
  因此未暴露该 bug。
