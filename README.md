# ResuAlign 求职工作台

ResuAlign 是一个**本地优先**的求职工作台：把简历诊断、岗位库管理、单岗位
对齐精修和投递闭环放在一个 FastAPI + Web UI 里。核心引擎与前端解耦——
CLI 和 Web 共用同一套流水线；所有数据落在本地 SQLite，不依赖外部服务。

核心闭环：**岗位库 → 工作台对齐 → 记录投递 → 安排跟进**。

防编造是硬约束：每条改写建议都携带指向主简历原文的 provenance；模型只能
改写/重排/强调已有事实，缺来源的建议会被 provenance 硬门禁拦截并标记
「建议复核」，永远不会静默混入定稿。

## 功能总览

- **驾驶舱**：KPI 总览（简历/岗位/对齐进度）、技能缺口排行（来自真实岗位
  JD 聚合）、快速继续最近任务。
- **简历中心**：主简历列表与单份档案；独立诊断（评分/技能/问题/建议）、
  版本历史、导出 Markdown，刷新后可恢复最近一次诊断。`#/resumes` 与
  `#/resume/list` 均进列表，`#/resume/<id>` 进单份档案。
- **岗位库**：万能输入（Ctrl+K 粘贴 JD / 链接）、油猴插件一键摄入
  （local-ingest）、自动分类与薪资提取；解析失败可降级为粘贴 JD 并保留
  来源；看板五列跟踪投递状态（未投递 → 已投递 → 面试中 → Offer → 放弃）。
- **工作台**：单岗位对齐调优。对照编辑（逐条 Diff）与 A4 纸预览双视图；
  Live Sheet 定稿实时预览；建议卡带 provenance 徽标与置信度，支持
  采纳/跳过/单条润色/手工编辑；保存定稿、刷新恢复、另存为主简历；
  导出 Markdown / JSON / PDF。
- **设置**：LLM 多节点管理（主节点 + 备用节点、连通性测试）、按角色
  超时与成本护栏（每日调用上限，达限返回 429）、分类词表自定义，
  保存即生效。
- **主题**：默认浅色（Slate + Indigo），支持明暗切换；移动端完整适配
  （底部导航、触控尺寸、抽屉交互）。

## 快速开始（本地）

```powershell
# Windows
.\start.ps1
```

```bash
# macOS / Linux
./start.sh
```

然后打开 <http://127.0.0.1:8000>。默认个人模式，无需登录；模型 API Key
通过 `.env` 提供（复制 `.env.example` 为 `.env` 并填写）。

手动启动：

```powershell
$env:PYTHONPATH = "D:\ResuAlign-Lite\src"
python -m uvicorn resualign.api:app --reload
```

## Docker（可选）

```bash
docker compose up --build
```

容器把 `./data` 挂载为数据卷（`RESUALIGN_DATA_DIR=/app/data`），`.env`
通过 `env_file` 注入；镜像以非 root 用户（UID 1000）运行，带 HEALTHCHECK
（`GET /health`，每 30s 探测），`stop_grace_period: 30s` 留给分析任务收尾。

> Linux 宿主机需保证挂载目录对容器用户可写：
> `sudo chown -R 1000:1000 ./data`（Docker Desktop 自动映射，无需处理）。

把服务暴露到局域网/公网前，务必阅读
[docs/deployment-security.md](docs/deployment-security.md)
（个人模式匿名访问风险、反向代理 Basic Auth、单进程约束等）。

## 命令行

```powershell
# 仅诊断
python run.py resume.pdf

# 诊断 + 完整对齐流水线
python run.py resume.pdf --jd "Java backend engineer, Spring Boot"

# 从文件读取 JD
python run.py resume.pdf --jd-file jd.txt

# 其他选项
python run.py resume.pdf --jd "..." --model deepseek-v4-flash --output-dir reports --quiet
```

CLI 会打印分数、技能、问题、Diff 建议、耗时与模型，并把 JSON 报告写入
`resualign-report-{timestamp}.json`。注：`--jd-url` 已随后端爬虫退役而
废弃，岗位链接请通过 Web 端油猴插件或粘贴 JD 录入。

## 流水线

1. **诊断简历**：分数、技能、问题清单。
2. **JD 画像**：结构化萃取必会/加分技能、软技能、业务场景。
3. **差距分析**：简历画像 vs JD 画像，输出缺口/错位/匹配项。
4. **对齐改写**：基于差距逐条改写，每条 Diff 带溯源；provenance 硬门禁
   拦截无来源建议。
5. **评估（可选）**：LLM 裁判对改写结果打分（`eval_score.jd_match_score`）。

多节点模式下调用经角色路由（diagnose / profiler / gap_analyzer / editor /
evaluator 分级超时与 token 预算），节点失败自动回退默认节点；缓存按
租户/模型/提示词版本/内容哈希四级键命中，过期条目自动清理。

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
`Authorization: Bearer <token>`。

## 数据备份与重置

所有数据（用户、简历、岗位、投递记录、设置、任务）都在 SQLite 文件
`data/jobs.db`（另有按需创建的 `data/content.db` 与 `data/content-cache.db`）
中，数据目录可用 `RESUALIGN_DATA_DIR` 覆盖。

```powershell
# 备份（在线一致性备份，服务可保持运行；不要直接 Copy-Item .db 文件）
powershell -File scripts\backup.ps1
```

```bash
# macOS / Linux
./scripts/backup.sh
```

备份输出到 `data/backups/`，日备份保留 7 天、每月 1 号的 weekly 备份保留
30 天。恢复演练见 [docs/backup-restore.md](docs/backup-restore.md)；缓存
清理与数据维护建议见 [docs/operations.md](docs/operations.md)。

## API 摘要

- `GET /health`：存活检查（含 DB/缓存自检）。
- `POST /api/auth/*`、`GET /api/auth/me`：账号与会话。
- `POST /api/workbench/session/init`：万能输入建会话（粘贴 JD / 链接）。
- `POST /api/jobs/local-ingest`：油猴插件本地摄入岗位。
- `GET /api/jobs/{id}`、`POST /api/analyze`：岗位详情与异步分析任务。
- `POST /api/master-resumes`、`GET /api/master-resumes/{id}`：主简历 CRUD
  与版本。
- `POST /api/jobs/{id}/workbench`：对齐任务排队；`POST
  /api/jobs/{job_id}/accept`：采纳建议；`POST /api/jobs/{job_id}/final-draft`：
  保存定稿；`POST /api/jobs/{job_id}/exports`：导出（md/json/pdf）。
- `POST /api/jobs/{id}/reclassify`：重新分类待定岗位；`POST
  /api/jobs/{id}/cancel`：取消排队任务。
- `GET /api/dashboard`：驾驶舱 KPI 与技能缺口聚合。
- `GET/PUT /api/settings`、`/api/llm/nodes`：设置与 LLM 节点管理。

完整契约见 `contracts/openapi-current.json`（或运行时 `/docs`）。

## 测试与基准

```powershell
$env:PYTHONPATH = "D:\ResuAlign-Lite\src"
python -m pytest tests/                                   # 全量单元/契约测试
python -m pytest --cov=resualign --cov-report=term-missing tests/
python -m pytest tests/e2e -v --e2e                       # Playwright e2e
node --test tests/frontend/*.test.mjs tests/frontend/dom/*.test.mjs

# 离线确定性基准（无网络，15 用例）
python benchmarks/run_benchmark.py --offline

# 关键路径冒烟（假 LLM，独立端口自启自停，不烧额度）
python .scratch/phase-20/playwright_smoke.py

# 真实 LLM 基准（使用 .env 凭据）
python benchmarks/run_benchmark.py --online
```

前端回归护栏集中在 `tests/frontend/`：`ux-regression.test.mjs`（导航对比度
WCAG AA、路由矩阵、硬门禁建议卡渲染契约）与 `css-structure.test.mjs`
（花括号平衡、关键布局选择器 v3 定义存活、简历网格行高约束）。
当前基线：**815 个 pytest + 486 个前端 node 测试**（2026-08-31 阶段 E 对齐收口后实测）。

## CI

三阶段（GitHub Actions，见 [.github/workflows/ci.yml](.github/workflows/ci.yml)）：

1. **Stage 1**：ruff 门禁 + 单元/契约测试（并行，85% 覆盖率门槛）+
   前端 node:test 全量 + ESM import 图检查。
2. **Stage 2**：延迟/调用次数基准门禁 + 离线基准套件。
3. **Stage 3**：Phase 20 关键路径 Playwright 冒烟（假 LLM，桌面 + 移动
   双视口，失败自动落盘诊断产物）+ e2e 套件。

## 文档

- 用户手册：[docs/user-guide.md](docs/user-guide.md)
- 架构决策：[docs/adr/](docs/adr/)（ADR-0026 v3 shell、ADR-0031 文档润色
  范式、ADR-0032 LLM 稳定性与流式、ADR-0033 消费者视觉刷新等）
- 领域词汇表：[CONTEXT.md](CONTEXT.md)
- 部署安全：[docs/deployment-security.md](docs/deployment-security.md)
- 备份恢复：[docs/backup-restore.md](docs/backup-restore.md) ·
  运维：[docs/operations.md](docs/operations.md)
- 代理说明：[AGENTS.md](AGENTS.md)
