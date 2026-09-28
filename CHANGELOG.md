# Changelog

本文件记录 ResuAlign 的迭代轨迹。

**版本单位**：`v1.0.0` 到 `v1.1.0` 之间项目按 **Phase** 推进（Phase 0–21 + 收口期
Phase A–E + CSS 架构重构 B0–B7），每批改动挂一篇或多篇 ADR。全仓只有两个 tag
（`v1.0.0` 起点基线、`v1.1.0` 当前），因为在这个粒度上语义化版本没有信息量，
**ADR 编号 + Phase 名才是主要索引**。

| 索引 | 位置 |
| --- | --- |
| 决策 | [`docs/adr/`](docs/adr/)（编号 0001–0058；**0029 有意缺号**，见 [ADR-0036](docs/adr/0036-agent-shape-a-only-mcp-deferred.md)） |
| 指标证据 | [`docs/EVIDENCE.md`](docs/EVIDENCE.md) |
| 发布声明与冻结策略 | [`docs/STATUS.md`](docs/STATUS.md) |
| 领域词汇表 | [`CONTEXT.md`](CONTEXT.md) |

日期取该批次首次提交日。ADR 列是该批次**新增**的决策，不是全部改动。

---

## [Unreleased]

`v1.1.0` 之后的仓库结构与交付契约收口，未打新 tag。

### Added

- 交付契约五要素补全：[`CHANGELOG.md`](CHANGELOG.md)、[`docs/STATUS.md`](docs/STATUS.md)、
  [`docs/EVIDENCE.md`](docs/EVIDENCE.md)。依据：`项目交付结构复盘_2026-09-20`
  指出的「入口层缺失」——五要素里只有「改版记录」是全局性空洞。
- 评分重算落盘：ResuAlign-Lite **79/81（97.53%）**，B3/B6/B9/B11 由 2 → 3、
  B10 保持 2（接受的设计取舍）。ADR-0054 验收闭合，issue #129 关闭。

### Changed

- `tests/` 按层分包：根目录 103 个 `test_*.py` 移入
  `api/ engine/ storage/ domain/ model/ observability/ contracts/ platform/`，
  与 `src/resualign/` 的模块分层一一对应（PR #141）。
- `CONTEXT.md` 由 604 行的「术语表 + 阶段史 + 状态 + 愿景」混合体收敛为
  一屏定位 + 领域术语表；历史与状态移入本文件与 `docs/STATUS.md`。
- `AGENTS.md` 记录模块布局是刻意选择、archive 的既定处置，并修正冻结标签口径（PR #140）。
- CI 与 E2E 脱离 `.scratch` 路径，QA agent 配置入库（PR #138）。

### Removed

- 3 个已死的阶段脚本（1488 行）与陈旧的 `src/data/content-cache.db`（PR #139）。

---

## [1.1.0] — 2026-09-28

从「对齐引擎 + 工作台」演进为**本地优先的求职工作台**：补全投递闭环、可靠性收口、
多节点 LLM、网申回填扩展、agent 方向裁决与 skill 探针主线。tag 指向
PR #136 合并的 release commit。

### Added

**投递闭环（ADR-0027 / ADR-0028）**

- 岗位库 → 工作台对齐 → 记录投递 → 安排跟进 → 终态收口的单事实源闭环；
  Job 取代休眠的 Application 双轨记录。
- 投递定稿快照：记录投递时原子捕获 final_draft / match_score / 主简历引用，
  append-only，面试回溯看快照而非可变定稿。
- 本地摄入端点 `POST /api/jobs/local-ingest` + 油猴插件双模摄入
  （实习僧 Specific + 通用划词），后端爬虫退役。

**工作台与前端（ADR-0015 / ADR-0017 / ADR-0022 / ADR-0026 / ADR-0033 / ADR-0043–0047）**

- 单岗位工作台：逐条 Diff 对照编辑、Live Sheet 定稿实时预览、A4 纸预览、
  采纳/跳过/单条润色、保存定稿/刷新恢复/另存为主简历、Markdown/JSON/PDF 导出。
- v3 卡片式本地工作台 shell：CSS-only 动效、导航对比度、路由矩阵与
  `prefers-reduced-motion` 门禁；移动端完整适配。
- CSS 架构重构（ADR-0043 单文件 @layer、ADR-0044 token 单命名空间、
  ADR-0045 lucide-only 图标、ADR-0046 inline style 白名单、ADR-0047 浅色默认）。
- 网申回填扩展（`extension/`）：Chrome MV3，读本地结构化档案逐字段回填，
  数据零上传。

**可靠性与多节点（ADR-0030 / ADR-0032 / ADR-0034 / ADR-0035 / ADR-0058）**

- 按角色拆分的 LLM 节点路由（diagnose / profiler / gap_analyzer / editor /
  evaluator 分级超时与 token 预算），主/备节点切换与健康徽标。
- 对齐排队前节点预检（`_probe_active_llm_quick`）：确定性 HTTP 失败硬拦截为
  422 + 引导，本地节点网络失败硬拦截，远程节点非阻塞。
- API Key 加密落库（secret_box）；结构化输出的推理 token 预算（ADR-0058）。
- LLM 节点熔断（`llm_nodes` 迁移 5，阈值 3，`consecutive_failures` /
  `auto_disabled`）；watchdog（`RESUALIGN_JOB_MAX_RUNTIME_S`，默认 1800s）。

**岗位表与护栏（ADR-0055 / ADR-0056 / ADR-0057）**

- 岗位表 CSV 自动同步 + 去重预检（`jobtable:` 稳定身份，重读不改库不烧额度）。
- 采集摄入字段与去重修复（ADR-0057）。

**方向裁决与探针（ADR-0036–0042）**

- agent 形态裁决（ADR-0036/0037/0038/0039/0040）：先做厚预设流 + 单入口路由，
  决策循环按实测决策点再定；三线门槛与合格例判据。
- 掉头（ADR-0041）：skill 探针升主线，app 新功能冻结；探针线判据 ≥5 例非作者
  首跑或 1 例外部合格链。
- 预注册重锚（ADR-0042）：探针线 / 自用线双线独立取证，时钟起点 = 四渠道
  outreach 全发出当日。

**工程实证与交付（ADR-0052 / ADR-0054）**

- 架构加固：原始 LLM 报文归档、分层棘轮、LLM 失败码契约（ADR-0052）。
- 评分短板实证加固（ADR-0054）：降级故障注入、确定性 API 容量曲线、
  分层冷启动三个 benchmark CLI + CI Stage 2/4 门禁。
- 一键备份/恢复（在线一致性备份）、部署安全文档、事故手册与故障演练。
- 可观测性：#100 错误形状统一（JSON + request_id）、#101 request_id 贯穿
  job/llm 日志、#102 watchdog、#103 节点熔断。

### Changed

- 交付评估、投递权重、薪资基准三块面板下线（ADR-0025）。
- 「无建议」语义分型（ADR-0041 决定 5 / #111）：有缺口且 `usable_diffs=0` →
  `failed` + `no_output`；无缺口 → 保持 `succeeded`，徽章「无缺口 · 无需改写」。
- 默认个人模式：无登录屏，匿名请求映射到稳定的本地租户；`RESUALIGN_PERSONAL_MODE=0`
  才恢复休眠的鉴权分支。
- 招聘平台采集退役：`--jd-url` 废弃，岗位链接改由油猴插件或粘贴录入。
- ADR-0047 局部 supersede ADR-0033 决定 1（浅色默认 + indigo 强调色）。

### Fixed

- 对齐可靠性（Phase 3）：溯源兜底（original 回退 + 自适应阈值）、
  sections 推导章节级 diff、失败持久化、离线占位 diffs。
- noop diff 过滤（A2）：`original == proposed` 的 modify/remove 移入 `invalid_diffs`。
- 简历详情 65/35 网格行高约束，正文不再被 `overflow:hidden` 裁切（Phase 1）。
- 批量取消不再把丢失的分析任务误标为 canceled；批处理矩阵透出逐行失败原因。
- LLM 请求超时有界化（180s → 60s read + 10s connect）。
- 测试日志隔离（#117）：pytest 子进程写临时日志目录，真实 `data/logs/app.log`
  保持干净；任务终态保留 30 天（#118）。
- 岗位卡操作面移出 hover 折叠层；模型选择器 + 工作台/简历中心/设置四项摩擦修复。
- 字体资产自托管；颜色/间距/圆角/阴影/z-index 刻度收敛。

### Removed

- 图管线死代码（graph pipeline）、旧 applications 面板、投递评估/薪资基准面板。
- 后端爬虫与 `--jd-url` 入口。
- 自动化规则「城市白名单」死选项（DB 兼容保留）。

---

## [1.0.0] — 2026-08-04

起点基线：`resualign` 包的最小可用版本。

### Added

- 核心流水线：parse → diagnose → align → output（`engine.py` 编排，
  frontend-agnostic）。
- CLI 前端（`run.py` / `resualign/cli.py`）。
- 多格式输入（PDF / DOCX / txt，ADR-0001）、配置分层（ADR-0002）、
  模块分解（ADR-0003）、测试策略（ADR-0004）。
- 防编造 provenance（ADR-0006）、LLM-as-Judge 评估（ADR-0007）、
  两阶段抽取（ADR-0008）、异步分析任务（ADR-0009）。

---

_维护约定：新增版本段时按 Added / Changed / Fixed / Removed 归类，每条挂 PR 号或
ADR 号；日期取该批次首次提交日。_
