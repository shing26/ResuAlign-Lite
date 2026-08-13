# ResuAlign 求职工作台

ResuAlign 把简历诊断、岗位对齐、岗位爬取分类和投递价值评估放在一个本地
工作台里。核心引擎与前端解耦：CLI 和 FastAPI + Web UI 共用同一套流水线。

四个工作台模块：

1. 简历中心：主简历维护、版本历史与回滚，并支持独立诊断（评分 / 技能 /
   问题 / 建议）、结果重跑与导出，刷新后可恢复最近一次诊断。
2. 岗位库：粘贴/链接/批量导入岗位，自动分类与薪资提取；解析失败可一键改用
   粘贴 JD 并保留来源链接；分类失败降级为「分类待定」并可重新分类。
3. 工作台：单岗位对齐调优、实时进度、取消/重跑、Diff 采纳、保存定稿 /
   刷新恢复 / 另存为新主简历、Markdown/JSON/PDF 导出、地区感知评估与基准
   来源标注。
4. 设置：评估权重、薪资参照表、分类词表，保存后立即生效；岗位库下拉与编辑
   弹窗同步使用自定义词表。

## 快速开始（本地）

```powershell
# Windows
.\start.ps1
```

```bash
# macOS / Linux
./start.sh
```

然后打开 <http://127.0.0.1:8000>。默认是个人模式，无需登录；模型 API Key
通过 `.env` 提供（复制 `.env.example` 为 `.env` 并填写）。

也可以手动启动：

```powershell
$env:PYTHONPATH = "D:\ResuAlign-Lite\src"
python -m uvicorn resualign.api:app --reload
```

## Docker（可选）

```bash
docker compose up --build
```

容器把 `./data` 挂载为数据卷（`RESUALIGN_DATA_DIR=/app/data` 显式统一数据
目录），`RESUALIGN_JOB_DB` 指向 `/app/data/jobs.db`，`.env` 通过 `env_file`
注入。镜像以非 root 用户（UID 1000）运行并带 HEALTHCHECK（`GET /health`，
每 30s 探测），`stop_grace_period: 30s` 留给分析任务收尾。

> Linux 宿主机需保证挂载目录对容器用户可写：
> `sudo chown -R 1000:1000 ./data`（Docker Desktop 自动映射，无需处理）。

把服务暴露到局域网/公网前，务必阅读
[docs/deployment-security.md](docs/deployment-security.md)
（个人模式匿名访问风险、反向代理 Basic Auth、单进程约束等）。

## 命令行

```powershell
# Diagnose only
python run.py resume.pdf

# Diagnose + full alignment pipeline
python run.py resume.pdf --jd "Java backend engineer, Spring Boot"

# Read the JD from a file or URL
python run.py resume.pdf --jd-file jd.txt
python run.py resume.pdf --jd-url https://example.com/job

# Extra options
python run.py resume.pdf --jd "..." --model deepseek-v4-flash --output-dir reports --quiet
```

CLI 会打印分数、技能、问题、Diff 建议、耗时与模型，并把 JSON 报告写入
`resualign-report-{timestamp}.json`。

## 流水线

1. 诊断简历（分数、技能、问题）。
2. 提取结构化 JD 画像（必会技能、加分技能、软技能、业务场景）。
3. 分析简历与 JD 的差距。
4. 基于差距改写简历，Diff 带溯源；模型只能改写/重排/强调已有事实，不得编造。
5. 可选：用 LLM 裁判评估改写结果（`eval_score.jd_match_score`）。

## 配置

复制 `.env.example` 为 `.env` 并设置：

```dotenv
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_MODEL=deepseek-chat

RESUALIGN_PERSONAL_MODE=1
RESUALIGN_JOB_DB=data/jobs.db
RESUALIGN_HOST=127.0.0.1
RESUALIGN_PORT=8000
```

优先级：CLI 参数 > `.env` > 环境变量。支持 `deepseek`、`openrouter`、
`ollama`。`RESUALIGN_PERSONAL_MODE=0` 时每个 API 请求都需要
`Authorization: Bearer <token>`。服务器日志由 uvicorn 输出到标准输出；
生产环境可自行接日志收集器。

## 数据备份与重置

所有数据（用户、简历、岗位、投递记录、设置、任务）都在 SQLite 文件
`data/jobs.db`（另有按需创建的 `data/content.db` 与 `data/content-cache.db`）
中，数据目录可用 `RESUALIGN_DATA_DIR` 覆盖。

```powershell
# 备份（在线一致性备份，服务可保持运行；不要直接 Copy-Item .db 文件）
powershell -File scripts\backup.ps1

# 重置（先停止服务）
Remove-Item data\jobs.db
```

```bash
# macOS / Linux
./scripts/backup.sh
```

备份输出到 `data/backups/`，日备份保留 7 天、每月 1 号的 weekly 备份保留
30 天。恢复演练（停服务 → 替换文件 → 启动 → 行数验证）见
[docs/backup-restore.md](docs/backup-restore.md)；缓存清理与数据维护建议见
[docs/operations.md](docs/operations.md)。

## API 摘要

- `GET /health`：存活检查。
- `POST /api/auth/*`、`GET /api/auth/me`：账号与会话。
- `POST /api/analyze`、`GET /api/jobs/{id}`：异步分析任务与轮询。
- `POST /api/master-resumes/{resume_id}/diagnose`：简历独立诊断。
- `POST /api/jobs/{id}/cancel`：取消排队中的任务。
- `POST /api/jobs/{job_id}/final-draft`：保存岗位定稿。
- `POST /api/jobs/{job_id}/reclassify`：重新分类待定岗位。
- `/api/master-resumes`、`/api/jobs`、`/api/applications`：三大数据域 CRUD。
- `POST /api/jobs/{id}/workbench`：
  单岗位工作台对齐与定稿。
- `GET/PUT /api/settings`：用户设置。

详细使用说明见 [docs/user-guide.md](docs/user-guide.md)。

## 测试与基准

```powershell
$env:PYTHONPATH = "D:\ResuAlign-Lite\src"
python -m pytest tests/
python -m pytest --cov=resualign --cov-report=term-missing tests/

# 离线确定性基准（无网络）
python benchmarks/run_benchmark.py --offline

# Phase 16 全量前端冒烟（桌面 1440x900 + 移动 390x844，独立端口自启自停）
python .scratch/phase-16/playwright_smoke.py

# 真实 LLM 基准（使用 .env 凭据）
python benchmarks/run_benchmark.py --online
```

基准结果写入 `benchmarks/results/benchmark-{timestamp}.json`。CI 会执行
pytest、85% 覆盖率门槛、离线基准、`node --check` 和 Phase 16 桌面 / 移动
Playwright 全量冒烟。
