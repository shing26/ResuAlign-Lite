# Runbook：日志治理与故障演练

Ticket #13 的运维手册。覆盖：日志设施说明、四类常见故障的症状→诊断→恢复→验证，
以及演练记录（每季度至少各执行一次 kill -9 恢复与备份还原演练）。

## 0. 日志设施速览（Ticket #13 交付）

| 项目 | 配置 |
| --- | --- |
| 落盘位置 | `<数据目录>/logs/app.log`；可用 `RESUALIGN_LOG_DIR` 覆盖 |
| 轮转 | `RotatingFileHandler`：单文件 10 MB，保留 5 个备份（`app.log.1` … `app.log.5`） |
| 编码 | UTF-8 |
| 格式 | 控制台与文件均为 `时间 级别 模块 JSON事件行`（`log_event` 产出单行 JSON） |
| 采样 | `http.request` 默认 1%（`RESUALIGN_LOG_SAMPLE_RATE`，0=不记，1=全记）；`http.slow`（>3s）始终记录 |
| 脱敏 | 所有 handler 挂 `RedactingFilter`：`sk-...` 密钥 token → `sk-***`，`error` 字段超 500 字符截断 |
| Docker | `compose.yaml` 的 `logging` 段：json-file driver，`max-size: 10m`、`max-file: "5"`（容器日志 10MB×5） |
| 配置时机 | `resualign.api` 导入时 `dictConfig` 一次（幂等），**不在** lifespan 里配置 |

关键事件（来自 #9，落盘在 `app.log`）：

- `job.queued` / `job.claimed` / `job.stage` / `job.finished`（含 `outcome`，失败带 `error`）/ `job.requeued`
- `llm.call`（`provider` / `model` / `stage` / `mode` / `duration_ms` / `attempts` / `status`）
- `http.request`（采样）/ `http.slow`

速查：

```powershell
# 实时查看结构化事件
Get-Content data\logs\app.log -Wait -Tail 50

# 只看失败事件
Select-String -Path data\logs\app.log -Pattern '"event": "job.finished"' | Select-Object -Last 20

# 统计 LLM 失败
(Select-String -Path data\logs\app.log -Pattern '"event": "llm.call"' | Where-Object { $_ -match '"status": "failed"' }).Count
```

---

## 1. 场景一：LLM 故障（Key 错误 / 超时 / 上游不可用）

### 症状

- 分析任务在 UI 上失败，提示"诊断任务暂时失败：模型服务不可用或返回异常，请检查 API Key 与网络连接后重试"
- `GET /api/jobs/{id}` 返回 `status: "failed"`，`error` 含认证/超时信息
- `GET /api/ops/metrics` 中 `llm.success_rate` 明显下降、`llm.failures` 上升
- `app.log` 中连续出现 `llm.call` 且 `"status": "failed"`（错误原因在 `job.finished` 的 `error` 字段，日志中已脱敏截断）

### 诊断

```powershell
# 1) 最近的 LLM 失败事件（注意：error 已脱敏/截断，凭 event 数量与 job.finished 定位）
Select-String -Path data\logs\app.log -Pattern '"event": "llm.call"' | Select-Object -Last 10

# 2) 指标快照
Invoke-RestMethod http://127.0.0.1:8000/api/ops/metrics

# 3) 确认当前生效的 provider / key（.env 或环境变量；settings 页面保存的 key 会覆盖 .env）
#    注意：日志与 metrics 都不会打印明文 key —— 这是预期行为
Get-Content .env | Select-String -Pattern 'API_KEY|BASE_URL|MODEL'

# 4) 直接探测上游（拿 .env 中的 base_url 替换）
curl.exe -s -o NUL -w "%{http_code}" -X POST https://api.deepseek.com/chat/completions `
  -H "Authorization: Bearer $env:DEEPSEEK_API_KEY" -H "Content-Type: application/json" `
  -d '{\"model\":\"deepseek-chat\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}'
```

### 恢复

1. **改错 key**：修正 `.env` 的 `<PROVIDER>_API_KEY`（或在"设置 → 模型服务"页面重新保存），重启：
   `powershell -File start.ps1`（Docker：`docker compose restart resualign`）。
2. **超时/网络**：确认 `DEEPSEEK_BASE_URL` 可达、代理环境变量未干扰；必要时临时提高超时再观察。
3. **重试路径（无需清库）**：UI 上对失败任务重跑（工作台 rerun / 岗位库重跑），系统会创建新的
   `analysis_job`；失败任务本身保留 `error` 供排查。批量失败时确认是持续故障而非偶发，再决定是否全量重跑。

### 验证

```powershell
# 提交一个最小分析任务并确认成功
$body = @{ resume_text = "Python developer"; jd_text = "招聘 Python 工程师" } | ConvertTo-Json
$r = Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/analyze -Body $body -ContentType "application/json"
# 轮询 GET /api/jobs/{r.job_id} 直到 succeeded；观察 app.log 出现 status=ok 的 llm.call
Invoke-RestMethod http://127.0.0.1:8000/api/ops/metrics | ConvertTo-Json -Depth 4
```

### 自愈（O3 巡检）

进程**重启时**的启动巡检 `_recover_stale_alignments()` 会扫描 `alignment_status IN ('queued','running')`
的岗位库任务：若对应的 registry 任务已终态或缺失（崩溃窗口），把该任务标记 `alignment_status='failed'`，
UI 上可重跑。该巡检只在启动时执行——持续运行中不做主动自愈，需人工重试或重启。

---

## 2. 场景二：进程被强制杀死（kill -9 / taskkill /F / OOM / 断电）

### 症状

- 服务进程消失且没有优雅退出（无 shutdown 日志）
- 任务卡在 `running`：`GET /api/jobs/{id}` 一直是 `running`，但没有任何新事件
- `GET /api/ops/metrics` 中 `queue.depth` 含 running 任务、`jobs.by_status.running` 非 0
- 端口已无监听

### 诊断

```powershell
# 1) 确认进程与端口
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -match 'python' }

# 2) 找出遗留的 running 任务
$env:PYTHONPATH = "D:\ResuAlign-Lite\src"
python -c "import sqlite3; c=sqlite3.connect('data/jobs.db'); print([dict(r) for r in c.execute(\"SELECT job_id, status, stage FROM jobs WHERE status IN ('queued','running')\")])"

# 3) 岗位库中遗留的 alignment 状态
python -c "import sqlite3; c=sqlite3.connect('data/jobs.db'); print(c.execute(\"SELECT job_id, alignment_status FROM library_jobs WHERE alignment_status IN ('queued','running')\").fetchall())"
```

### 恢复（重启即自愈，无需手工改库）

```powershell
powershell -File start.ps1          # 或 docker compose up -d
```

启动时 `_recover_pending_jobs()` 依次执行：

1. **分析任务 requeue**：`pending_job_ids()` 找出 queued/running 任务 →
   `requeue_interrupted` 把 `running` 置回 `queued`（`started_at` 清空）→ 每个任务起一个新 worker 线程，
   payload 从 `job_payloads` 持久化表恢复（内存 payload 随旧进程丢失，不影响）。
2. **crawl 恢复**：`CrawlTaskStore.recover_interrupted()` 恢复中断的抓取任务。
3. **O3 巡检**：`_recover_stale_alignments()` 把"registry 已终态但 alignment 未落盘"的岗位库任务标记 failed。

### 验证

```powershell
# 1) app.log 出现 job.requeued（每个遗留任务一条）
Select-String -Path data\logs\app.log -Pattern '"event": "job.requeued"' | Select-Object -Last 10

# 2) 任务被重新认领并推进（queued -> running -> 终态）
#    对每个遗留 job_id 轮询 GET /api/jobs/{id}，应观察到状态流转而非永久卡死

# 3) 遗留任务最终全部终态
python -c "import sqlite3; c=sqlite3.connect('data/jobs.db'); print(c.execute(\"SELECT status, COUNT(*) FROM jobs GROUP BY status\").fetchall())"
```

> 注意：`requeue` 只把 `running` 置回 `queued` 并重跑。若任务本身无法成功（如 LLM key 失效），
> 重跑后仍会 failed —— 按场景一排查。被 kill 时正在写的 SQLite 事务由 WAL + `busy_timeout` 兜底，
> 重启后库一致性由 SQLite 自身保证，无需手工修复。

---

## 3. 场景三：磁盘空间不足

### 症状

- 任务失败，`error` 或系统日志出现 `database or disk is full`
- `scripts/backup.ps1` 失败（无法写入备份文件）
- 日志轮转异常（`app.log` 写入失败）
- Docker 下容器反复重启 / 健康检查失败

### 诊断

```powershell
# 1) 磁盘余量
Get-PSDrive -Name C | Select-Object Used, Free

# 2) 找出大文件（按体积排序）
Get-ChildItem data -Recurse -File | Sort-Object Length -Descending | Select-Object -First 10 FullName, @{n='MB';e={[math]::Round($_.Length/1MB,1)}}

# 3) Docker 磁盘占用（如使用 Docker 部署）
docker system df
```

典型占用：`data/logs/app.log*`（轮转后最多 10MB×6）、`data/backups/*.db`（保留 7 天日备份 + 30 天周备份）、
数据库 WAL 文件（`*.db-wal`，运行中正常存在）。

### 恢复

1. **清日志**：`Remove-Item data\logs\app.log.* -ErrorAction SilentlyContinue`（保留当前 `app.log`；
   轮转策略会重新生成备份）。Docker 下由 `compose.yaml` 的 json-file 限额（10m×5）自动兜底，
   手动清理可用 `docker system prune --volumes` 前先确认无在用卷。
2. **清旧备份**：重跑 `scripts/backup.ps1` 会按保留策略删除过期备份；也可手动删除
   `data/backups/jobs.db-*.db` 中早于保留期的文件（先核对文件名时间戳）。
3. **若 WAL 文件异常膨胀**（服务停止后仍巨大）：停止服务 → 删除 `*.db-wal` / `*.db-shm` → 重启
   （删除前确认有可用备份，见场景四）。
4. **长期措施**：迁移数据目录到更大磁盘（设置 `RESUALIGN_DATA_DIR` 后移动 `data/` 内容），
   或调低日志采样率（`RESUALIGN_LOG_SAMPLE_RATE`）。

### 验证

```powershell
Get-PSDrive -Name C | Select-Object Free
powershell -File scripts/backup.ps1        # 应正常完成，integrity=ok
Invoke-RestMethod http://127.0.0.1:8000/health
```

---

## 4. 场景四：备份还原

完整流程见 `docs/backup-restore.md`（在线备份 API、WAL 注意事项、保留策略、恢复步骤）。
此处只列演练要点：

1. **备份**（服务可不停）：`powershell -File scripts/backup.ps1` → 产物
   `data/backups/jobs.db-<yyyyMMdd-HHmmss>.db` 与 `manifest-*.json`，
   每个备份都做过 `PRAGMA integrity_check`，上传目录同时进快照。
2. **还原前置**：停止服务；记录还原前基线行数。
3. **一键还原**：`powershell -File scripts/restore.ps1`（自动选最新 manifest；
   也可用 `scripts/restore.sh`）。脚本保留 `*.pre-restore-*` 现场、清理
   陈旧 `-wal`/`-shm`，DB 与上传目录一起还原，避免跨时间点混搭。
4. **验证**：`/health` 正常；各表行数与备份一致（`docs/backup-restore.md` §2.4 有一键对比命令）。
5. **收尾**：确认业务数据正常后删除 `*.pre-restore-*` 现场文件。

---

## 5. 演练记录

> 演练频率：kill -9 恢复与备份还原各**每季度至少一次**。每次执行后在此追加日期与结果。

### 2026-08-06 — kill -9 / 强制杀进程恢复演练（PASS）

执行：`python scripts/drill_kill9.py`（Windows 本地，`TerminateProcess` 等价 kill -9）

过程与结果：

```
app healthy on 127.0.0.1:61028 (pid 24164)
queued analysis job 806043ea5c884ad49a6c7b2379f4ef7f
job running (statuses=['running'])
force-killing uvicorn pid 24164 (kill -9 / TerminateProcess)
orphaned DB row after kill: status=running
restarted app healthy (pid 40932)
post-restart statuses=['running'] job.requeued=True http.request=True
RESULT: PASS — interrupted job recovered via startup requeue
```

要点：

- 演练用临时数据目录 + 假 LLM（本地挂起 HTTP 服务模拟 LLM 不可达，使任务稳定停留在 `running`），
  不触碰真实 `data/`。
- kill 后直接读库确认孤儿行状态 `running`（未优雅退出）；
- 重启后启动巡检 `requeue_interrupted` 将其置回 `queued` 并被新 worker 重新认领（`running`）；
- `app.log` 中出现 `job.requeued` 与 `http.request` 事件，日志链路（#9 事件 + #13 落盘）同时得到验证。

### 2026-08-06 — 备份还原演练（PASS）

执行：`powershell -File scripts/backup.ps1` + 还原校验（恢复至临时目录，不停止真实服务）

```
[backup] ok: jobs.db -> jobs.db-20260806-180348.db (1998848 bytes, integrity=ok)
[backup] ok: content-cache.db -> content-cache.db-20260806-180348.db (69632 bytes, integrity=ok)
[backup] done: 2 database(s) backed up to D:\ResuAlign-Lite\data\backups
```

还原校验（备份文件复制到 `%TEMP%` 作为"恢复位"，只读比对 + 临时启动）：

```
integrity: ok
live : {'users': 12, 'master_resumes': 3, 'library_jobs': 8, 'applications': 2, 'jobs': 1, 'crawl_tasks': 10}
rest : {'users': 12, 'master_resumes': 3, 'library_jobs': 8, 'applications': 2, 'jobs': 1, 'crawl_tasks': 10}
MATCH: all 6 tables equal
health: {"status":"ok","checks":{"db":{"ok":true,"detail":"database readable"},"cache":{"ok":true,"detail":"cache read/write ok"}}}
library_jobs via API: 8
```

要点：

- 在线备份成功且每个产物 `integrity=ok`（`content.db` 未使用故 skip，正常）；
- 备份产物在独立连接下完整性 `ok`，6 张业务表行数与实时库**逐一相等**；
- 用恢复的库作为 `RESUALIGN_DATA_DIR` 启动完整应用：`/health` ok、`/api/jobs` 返回 8 条与实时一致；
- 真实库的"停服→换文件→启服"切换步骤按 `docs/backup-restore.md` §2 执行（本次为防误伤真实数据，
  以临时目录完成等价的恢复链路验证）。
