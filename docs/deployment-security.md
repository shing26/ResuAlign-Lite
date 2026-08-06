# 部署安全指南

本文档面向把 ResuAlign 部署到本机以外（局域网 / 公网 / 容器）的场景。
本地个人使用（`start.ps1` / `start.sh` 默认绑定 `127.0.0.1`）不在本文档的
风险范围内，但请先读完「个人模式风险」一节。

## 1. 个人模式风险说明

默认配置 `RESUALIGN_PERSONAL_MODE=1`（Dockerfile / compose 均已显式设置）：

- **匿名访问**：任何能访问到服务端口的人，**不需要任何登录凭据**即可读写
  全部数据——主简历、岗位、投递记录、设置，以及所有分析结果。匿名请求会
  映射到稳定的本地租户。
- **无会话边界**：不存在用户隔离。`GET /api/auth/me`、`/api/settings`、
  `/api/master-resumes/*`、`/api/jobs/*` 等全部对匿名请求开放。
- **`0.0.0.0` 监听风险**：容器内 uvicorn 监听 `0.0.0.0:8000`，
  `docker compose` 默认把 `8000:8000` 发布到宿主机**所有网卡**。若宿主机
  在局域网/公网，等于把个人工作台直接暴露给网络上的任何人。

结论：**个人模式只适合“只有你能访问”的网络位置**（本机回环，或受信任的
隔离网络）。

## 2. 部署前置要求（局域网 / 公网）

把服务暴露到局域网或公网前，必须满足**至少一项**：

1. **反向代理 + Basic Auth（推荐，改动最小）**
   - Nginx / Caddy / Traefik 置于 ResuAlign 之前，仅暴露代理端口，
     容器端口改为仅本机可访问（compose 中 `ports: "127.0.0.1:8000:8000"`）。
   - 代理层启用 Basic Auth（`htpasswd` / Caddy `basic_auth`），并强制 HTTPS。
   - 优点：不动应用代码；密码由代理层管理，可随时轮换。
2. **关闭个人模式，启用账号体系**
   - 设置 `RESUALIGN_PERSONAL_MODE=0`。此时每个 API 请求都需要
     `Authorization: Bearer <token>`（注册账号后由登录接口签发）。
   - 仍应放在 HTTPS 后面；token 明文传输等于没有鉴权。
3. **仅限受信任网络**
   - 若只部署在受信任的局域网（如家用 Wi-Fi），至少确保：
     - 不开放公网端口映射（路由器不做 `8000` 端口转发）；
     - 宿主机防火墙只放行需要的来源 IP；
     - 仍建议加一层 Basic Auth，因为 Wi-Fi 上可能有陌生人。

**任何情况下都不要把监听 `0.0.0.0` 的个人模式端口直接暴露到公网。**

## 3. `.env` 文件权限

`.env` 含 LLM API Key，属于敏感文件：

```powershell
# Windows：仅当前用户可读
icacls .env /inheritance:r /grant:r "$($env:USERNAME):(R,W)"
# 或取消继承后只保留当前用户
icacls .env /inheritance:r /grant "$($env:USERNAME):F"
```

```bash
# Linux / macOS
chmod 600 .env
chown "$(id -u):$(id -g)" .env
```

另外：`.env` 已在 `.gitignore` 中，提交代码前用
`git status` 确认它不会被带入 commit。

## 4. API Key 轮换

- LLM 提供方（DeepSeek / OpenRouter / Ollama 本地无需轮换）的控制台通常支持
  创建/吊销多个 key。
- 建议每 90 天轮换一次；怀疑泄露时立即轮换。
- 轮换步骤：改 `.env` 中的 `DEEPSEEK_API_KEY`（或对应 provider 变量）→
  重启服务 → 跑一次带 LLM 的流水线验证 → 到提供方控制台吊销旧 key。
- 容器部署时通过 `env_file` 注入，改完 `.env` 后执行 `docker compose up -d`
  重建容器即可。

## 5. 单进程约束（禁止 `--workers > 1`）

### 为什么必须单进程

分析任务队列由**进程内的 daemon 线程**消费（`resualign.api` 启动时拉起）。
启动 `uvicorn --workers N`（N>1）会产生多个独立进程：

- 每个进程各自拉起一个队列消费线程 → 同一任务被**多个进程同时处理**，
  任务状态互相踩踏；
- 内存态（租户缓存、会话缓存、队列状态）跨进程不一致——进程 A 认为任务
  已取消，进程 B 还在跑；
- SQLite WAL 对多进程写是安全的，但 `busy_timeout` 下会频繁互等，且
  以上两个问题与数据库无关，无法靠 SQLite 缓解。

因此：**任何启动方式都不得使用 `--workers > 1`**，包括手动命令、systemd、
容器 CMD（Dockerfile 的 CMD 已是单进程）、K8s 副本数必须为 1。
`start.ps1` / `start.sh` 已显式传 `--workers 1`。

### 进程内并发：`RESUALIGN_WORKER_CONCURRENCY`

进程内分析任务默认**串行**（`_WORKER_SEMAPHORE = BoundedSemaphore(1)`）——
这是刻意背压，防止 LLM 调用并发放大成本。个人用户批量对齐 5 个岗位时，
串行意味着 5×LLM 等待时间排队。

可设 `RESUALIGN_WORKER_CONCURRENCY=2`（或 3）让分析任务并行，对批量对齐
体验提升明显（LLM-bound，SQLite WAL 写并发足够）。取值范围 1..4，越界
自动钳制（无效值回落 1）。**多租户共享部署请保持 1**，避免配额放大。
队列深度与最老等待时长可经 `GET /api/ops/metrics` 观测。

### 正确的扩容/高可用替代方案

- **吞吐**：单进程 uvicorn 是异步事件循环，普通个人工作台负载远未触顶；
  如需更高并发，先优化 LLM 调用与缓存（见 `docs/operations.md`）。
- **可靠性**：靠 Docker HEALTHCHECK + `restart: unless-stopped` 实现
  进程级自愈；`stop_grace_period: 30s` 给在跑的分析任务收尾时间。
- **水平扩展**：需要把分析任务队列外置（如 Redis / 数据库轮询）并让
  worker 与 API 分离——这是后端架构改动，**不在当前运维范围内**，
  由主线程/后端 agent 决策后再实施。

## 6. 容器化部署要点

- 镜像以非 root 用户 `resualign`（UID 1000）运行。
- `./data` 绑定挂载到 `/app/data`：**Linux 宿主机**需保证该目录对
  UID 1000 可写：`sudo chown -R 1000:1000 ./data`；Windows/macOS 的
  Docker Desktop 自动映射宿主权限，无需额外操作。
- HEALTHCHECK 每 30s 探测 `GET /health`，失败 3 次标记 unhealthy，
  配合 `restart: unless-stopped` 自动重启。

## 7. 相关文档

- 备份与恢复演练：[docs/backup-restore.md](backup-restore.md)
- 数据维护（缓存清理 / 保留策略 / WAL 建议）：[docs/operations.md](operations.md)
- 静态资源缓存行为说明：[docs/operations.md](operations.md) 第 3 节
