# 运维手册：数据维护与缓存说明

本文档只做**说明与建议**（文档层面），不包含自动任务实现。
自动清理任务的代码改动由主线程 / 后端 agent 决策后另行实施。

## 1. 数据文件清单

数据目录默认 `data/`（可用 `RESUALIGN_DATA_DIR` 覆盖，优先级见
`src/resualign/jobs.py` 的 `resolve_data_dir`）：

| 文件 | 用途 | 备注 |
| --- | --- | --- |
| `data/jobs.db` | 主库：用户/会话、主简历、岗位库、投递、分析任务、设置 | 必须备份 |
| `data/content.db` | 内容库 | 按需创建，可能不存在 |
| `data/content-cache.db` | LLM 内容哈希缓存（`content_cache` 表） | 可安全清理 |
| `data/backups/` | 备份输出目录（`scripts/backup.*` 创建） | 见 backup-restore.md |

所有库为 WAL 模式（`src/resualign/store_base.py` 的 `_apply_sqlite_pragmas`
设置 `journal_mode=WAL`、`synchronous=NORMAL`、`busy_timeout=5000`）。

## 2. 前端静态资源缓存行为

`src/resualign/api/__init__.py` 的 `_cache_static_assets` 中间件对
`/static/` 下的响应设置 `Cache-Control`：

| 路径 | 响应头 | 行为 |
| --- | --- | --- |
| `/static/index.html`、`/static/app/*`（ESM 入口与模块） | `Cache-Control: no-cache` | 协商缓存：浏览器每次加载都向服务器校验（ETag / Last-Modified），新部署不会混用新旧模块 |
| `/static/styles.css` 等其他静态资源 | `Cache-Control: public, max-age=3600` | 短时公共缓存（1 小时） |

前端通过 `?v=` 查询串做版本化引用（如
`/static/styles.css?v=22`）：升级样式时**递增 `?v=` 值**即可强制浏览器
拉取新文件，无需依赖长 max-age。`index.html` 本身是 no-cache，
因此发布新版后浏览器会先重新校验入口页，再带上新的 `?v=` 引用。

> 运维提示：若改了 CSS/JS 但页面表现未更新，先确认 `index.html` 中的
> `?v=` 是否已递增；不要手动清空浏览器缓存作为常规流程。

## 3. 缓存库清理（content_cache）

### 3.1 过期行清理

`content_cache` 表结构（`src/resualign/cache.py`）：
`tenant / model / prompt_version / content_sha256 / payload /
created_at REAL / expires_at REAL`——时间列为 **REAL 类型的 Unix 秒**。

建议 SQL（对 `data/content-cache.db` 执行）：

```sql
DELETE FROM content_cache
WHERE expires_at < CAST(strftime('%s', 'now') AS REAL);
```

说明：

- 应用按 `ttl_seconds=3600`（1 小时）写入 `expires_at`，过期行不会被读取，
  但会持续占用空间；建议**每周**执行一次。
- `strftime('%s','now')` 返回 TEXT，SQLite 的 REAL 亲和性在比较时会做数值
  转换，但显式 `CAST(... AS REAL)` 更清晰、不受后续 schema 变化影响。
- 也可用等价写法 `expires_at < unixepoch()`（SQLite ≥ 3.38）。
- 本地 Python / sqlite3 示例：

```powershell
$env:PYTHONPATH = "D:\ResuAlign-Lite\src"
python -c "import sqlite3; c=sqlite3.connect('data/content-cache.db'); c.execute(\"DELETE FROM content_cache WHERE expires_at < CAST(strftime('%s','now') AS REAL)\"); c.commit(); print('deleted rows:', c.total_changes)"
```

```bash
sqlite3 data/content-cache.db "DELETE FROM content_cache WHERE expires_at < CAST(strftime('%s','now') AS REAL);"
```

清理后建议执行 `PRAGMA wal_checkpoint(TRUNCATE);` 收回空间（见第 5 节）。

### 3.2 全量清空（应急）

`DELETE FROM content_cache;` 只影响缓存命中率（LLM 调用会变多），不影响
任何业务数据，可随时执行。

## 4. 任务/操作记录表保留策略（jobs.db）

| 表 | 内容 | 建议保留期 |
| --- | --- | --- |
| `crawl_tasks` | 爬取任务（每行一个 JD 抓取） | 已结束（`finished_at` 非空）的行保留 30 天；排队/运行中的不要删 |
| `kanban_bulk_ops` | 批量导入/看板批量操作（幂等记录） | 建议保留 90 天（幂等键用于去重，太短会导致重放风险） |

建议 SQL（`data/jobs.db`）：

```sql
-- crawl_tasks：删除 30 天前已结束的任务
DELETE FROM crawl_tasks
WHERE finished_at IS NOT NULL
  AND finished_at < CAST(strftime('%s', 'now') AS REAL) - 2592000;

-- kanban_bulk_ops：删除 90 天前的幂等记录
DELETE FROM kanban_bulk_ops
WHERE created_at < CAST(strftime('%s', 'now') AS REAL) - 7776000;
```

说明：

- 应用删除岗位时已级联删除其 `crawl_tasks` 行（`job_library.py`
  `delete_job` 路径），上述 SQL 只清理“岗位还在但任务早已结束”的历史。
- `created_at` / `finished_at` 均为 REAL Unix 秒。
- 建议频率：`crawl_tasks` 每月一次；`kanban_bulk_ops` 每季度一次。

## 5. WAL 文件大小建议

### 现状

应用未设置 `PRAGMA journal_size_limit`；实测（本仓库环境验证）该 pragma
**是连接级设置，不随数据库文件持久化**（设置 → 关闭连接 → 重开返回
`-1` 无限制）。因此用 `sqlite3` CLI 执行一次
`PRAGMA journal_size_limit=67108864;`（64MB）**不会**对后续连接生效。

### 建议（留给后端 agent 决策）

在 `src/resualign/store_base.py` 的 `_apply_sqlite_pragmas()` 中追加
`PRAGMA journal_size_limit=67108864;`（64MB），使每个新连接都带上该限制，
WAL 文件在 checkpoint 后会被截断到 ≤ 64MB。此改动在 `src/` 域外，
运维侧不实施。

### 运维侧的过渡手段

低峰期手动 checkpoint 并截断 WAL（可在服务运行时执行，若正被其他连接
占用会返回 `busy`，稍后重试）：

```bash
sqlite3 data/jobs.db "PRAGMA wal_checkpoint(TRUNCATE);"
sqlite3 data/content-cache.db "PRAGMA wal_checkpoint(TRUNCATE);"
```

`TRUNCATE` 在 checkpoint 后把 WAL 文件截断回零；默认自动 checkpoint
阈值约 1000 页（4KB 页 ≈ 4MB），批量导入等大事务后 WAL 可能显著增长，
手动截断可及时回收磁盘。

## 6. 备份与恢复

见 [docs/backup-restore.md](backup-restore.md)（在线备份脚本
`scripts/backup.ps1` / `scripts/backup.sh`、保留策略与恢复演练）。
