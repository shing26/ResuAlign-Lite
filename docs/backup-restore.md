# 备份与恢复手册

ResuAlign 的全部业务数据都在 SQLite 里（`data/` 目录，可用
`RESUALIGN_DATA_DIR` 覆盖）。备份与恢复围绕三个库：

| 文件 | 内容 |
| --- | --- |
| `data/jobs.db` | 主库：用户/会话、主简历与版本、岗位库、投递记录、分析任务、设置 |
| `data/content.db` | 内容库（按需创建，可能不存在） |
| `data/content-cache.db` | 确定性 LLM 阶段的内容哈希缓存 |

> 三个库都处于 **WAL 模式**（`PRAGMA journal_mode=WAL`）。
> **绝不要**在服务运行时直接 `Copy-Item` / `cp` 复制 `.db` 文件——WAL 模式下
> 直接复制会漏掉未 checkpoint 的日志页，得到不一致快照。必须使用
> sqlite3 `.backup()` API（即 `scripts/backup.ps1` / `scripts/backup.sh`）。

## 1. 创建备份

服务**无需停止**：`.backup()` 是 SQLite 官方在线备份 API，会处理 WAL 快照一致性。

```powershell
# Windows（默认 data/ 目录）
powershell -File scripts/backup.ps1

# 指定数据目录
powershell -File scripts/backup.ps1 -DataDir "D:\resualign-data"
```

```bash
# macOS / Linux
./scripts/backup.sh
./scripts/backup.sh /path/to/data        # 或 RESUALIGN_DATA_DIR=/path ./scripts/backup.sh
```

输出示例：

```
[backup] start: data dir=D:\ResuAlign-Lite\data backup dir=D:\ResuAlign-Lite\data\backups
[backup] ok: jobs.db -> jobs.db-20260806-153000.db (1998848 bytes, integrity=ok)
[backup] skip: content.db not found
[backup] ok: content-cache.db -> content-cache.db-20260806-153000.db (12288 bytes, integrity=ok)
[backup] retention: removed 0 expired backup(s) (daily >7d, weekly >30d)
[backup] done: 2 database(s) backed up to D:\ResuAlign-Lite\data\backups
```

每个备份都会在目标文件上执行 `PRAGMA integrity_check`，只有 `ok` 才算成功；
失败的备份文件会被删除并返回非零退出码。

### 1.1 备份产物与保留策略

- 目录：`<DataDir>/backups/`
- 文件名：`{dbname}-{yyyyMMdd-HHmmss}.db`；**每月 1 号**生成的备份命名为
  `{dbname}-weekly-{yyyyMMdd-HHmmss}.db`
- 保留（按文件修改时间）：
  - 日备份（文件名不含 `weekly`）：超过 **7 天**删除（约 7 份日备份）
  - `weekly` 备份：超过 **30 天**删除（简化策略：以每月 1 号的备份充当
    周级全量快照，覆盖约 4 个自然周）

### 1.2 定期调度建议

```powershell
# Windows：任务计划程序 → 创建任务 → 操作：powershell
#   参数: -NoProfile -ExecutionPolicy Bypass -File "D:\ResuAlign-Lite\scripts\backup.ps1"
#   触发器: 每天 03:00（每月 1 号自动得到 weekly 备份）
```

```bash
# crontab：每天 03:00
0 3 * * * cd /path/to/ResuAlign-Lite && ./scripts/backup.sh >> /var/log/resualign-backup.log 2>&1
```

## 2. 恢复演练（Restore Drill）

恢复需要**停止服务**。恢复的是单个一致快照，演练步骤：

### 2.1 停止服务

```powershell
# 方式一：Ctrl+C 停止 start.ps1 进程；方式二（Windows 服务/任务）：
Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {
  $_.Path -match 'python' -and $_.CommandLine -match 'resualign' -and $_.CommandLine -match 'uvicorn'
} | Stop-Process -Force
```

```bash
# Docker
docker compose stop
# 或本地进程
pkill -f "uvicorn resualign.api:app"
```

确认端口已释放：

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
```

### 2.2 选择备份文件

```powershell
Get-ChildItem data\backups\jobs.db-*.db | Sort-Object LastWriteTime -Descending | Select-Object -First 5 Name, Length, LastWriteTime
```

```bash
ls -lt data/backups/jobs.db-*.db | head -5
```

选恢复目标后，记录**恢复前基线行数**（与备份时记录的对比）：

```bash
python -c "import sqlite3; c=sqlite3.connect('data/jobs.db'); print(c.execute('SELECT COUNT(*) FROM library_jobs').fetchone()[0])"
```

### 2.3 替换数据文件

先移走现有文件（保留现场，勿直接覆盖，便于回退），再复制备份到位，
并**删除陈旧的 `-wal` / `-shm` 文件**——若残留旧 WAL，SQLite 会在下次打开时
重放它，覆盖刚恢复的数据，导致“恢复无效”。

```powershell
# 以 jobs.db 为例；content.db / content-cache.db 同理（不存在则跳过）
Move-Item data\jobs.db data\jobs.db.pre-restore-$(Get-Date -Format yyyyMMdd-HHmmss)
Remove-Item data\jobs.db-wal, data\jobs.db-shm -Force -ErrorAction SilentlyContinue
Copy-Item data\backups\jobs.db-20260806-153000.db data\jobs.db
```

```bash
# 以 jobs.db 为例
mv data/jobs.db "data/jobs.db.pre-restore-$(date +%Y%m%d-%H%M%S)"
rm -f data/jobs.db-wal data/jobs.db-shm
cp data/backups/jobs.db-20260806-153000.db data/jobs.db
```

> 备份文件本身是完整一致快照，恢复时**不需要**同时复制 `-wal` / `-shm`。
> 若只想回滚到某时刻，把三个库的备份一起恢复，避免跨库时间点不一致。

### 2.4 启动服务并验证

```powershell
.\start.ps1          # 或 docker compose up -d
```

```powershell
# 健康检查
Invoke-RestMethod http://127.0.0.1:8000/health
```

行数验证（与恢复前基线对比）：

```powershell
$env:PYTHONPATH = "D:\ResuAlign-Lite\src"
python -c "import sqlite3; c=sqlite3.connect('data/jobs.db'); print({t: c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ['users','master_resumes','library_jobs','applications','analysis_jobs','crawl_tasks']})"
```

预期各表计数与备份前一致。缓存库可只做完整性检查：

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/content-cache.db'); print('integrity:', c.execute('PRAGMA integrity_check').fetchone()[0], 'rows:', c.execute('SELECT COUNT(*) FROM content_cache').fetchone()[0])"
```

### 2.5 验证通过后清理现场

确认业务数据（简历中心 / 岗位库 / 工作台）正常后，删除
`*.pre-restore-*` 文件，完成演练。演练频率建议：**每季度至少一次**。

## 3. 常见问题

- **`content.db` 报 skip**：正常，该库按需创建，尚未使用就不存在。
- **备份期间服务在写库**：安全。`.backup()` 会读取一致性快照；
  WAL 模式下并发读写与备份互不阻塞。
- **恢复后行数对不上**：先检查是否残留旧 `-wal` 文件（见 2.3）；
  其次确认选中的备份时间点在数据丢失之前。
- **数据目录被 `RESUALIGN_DATA_DIR` 覆盖**：备份脚本传同样的目录即可：
  `powershell -File scripts/backup.ps1 -DataDir $env:RESUALIGN_DATA_DIR`。
