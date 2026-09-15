# ResuAlign — Domain Glossary

> 终局：简历-岗位全链路优化平台。
> CLI 只是前端之一，未来会扩展 Web UI / API 层。
> 核心引擎前端无关，多阶段 pipeline 可组合，铁律：不捏造事实。

## Recovery (2026-08-30, 分阶段重构)

- **Phase 0 基线**：爬虫退役收尾固化提交；契约同步（manifest 声明
  parse-jd/JDParseRequest 移除，清除 WorkstationCrawlSection 残留）→
  3 个契约测试转绿；油猴插件端口 8011→8000。
- **Phase 1 布局**：简历详情 65/35 网格行高约束（`align-items:stretch` +
  `grid-template-rows:minmax(0,1fr)`），正文不再被 overflow:hidden 裁切。
- **Phase 2 摄入收口**：UI 移除「JD 链接」模式与命令面板 jd_url 发送；
  批量导入 jd_url 行明确报错；crawl 措辞全库清理。
- **Phase 3 对齐可靠性**：溯源兜底（original 回退 + 自适应阈值）；
  sections 推导章节级 diff（模型只回全文时不再 0 建议）；云节点可选
  map-reduce（`RESUALIGN_BULLET_EDITOR_CLOUD=1`）；失败持久化
  （library_jobs.last_alignment_error，迁移 42）；离线占位 diffs。
- **Phase 4 护栏**：`tests/frontend/css-structure.test.mjs` 锁定 CSS
  结构不变式（括号平衡、关键选择器 v3 存活、网格行高约束）。
- 壳层选择器自动合并验证发现会破坏 @media 移动端级联，已回滚留待
  按媒体上下文逐属性合并。
- **Phase A 对齐运行时收口**：workbench 排队前节点预检
  （`_probe_active_llm_quick`，5s 探测；401/402/403 确定性失败拦截为
  422+引导，网络/超时非阻塞）；noop diff 过滤（original==proposed 移入
  invalid_diffs）；last_alignment_error 透出到 API 与岗位卡片徽章
  （对齐失败/无建议）；岗位库「批量对齐」入口（idle/失败逐个排队）。
- **Phase B 爬虫残留清理**：自动化规则移除「城市白名单」死选项
  （rules.py 标记 deprecated，DB 兼容保留）；油猴占位符 8011→8000；
  「抓取失败，可重试」徽章改「JD 文本异常」；设置页措辞收口。
- **Phase C 标题去重**：简历列表页/设置页视图内重复 h2 移除（顶栏
  PAGE_META 已渲染页标题）；移动端顶栏瘦身（副标题隐藏 + 间距压缩，
  165→145px）；css-structure 护栏新增单 h2 不变式。
- **Phase E 对齐收口（2026-08-31）**：批量对齐统一到矩阵接口
  `/api/batch-align`（`selector="pending"` 覆盖 idle/failed/卡死 queued），
  删除看板旧的逐条 POST workbench 轻量循环；看板卡片按 alignment_status
  显示单岗对齐按钮（idle→「开始对齐」，failed/零 diff succeeded→「重新对齐」，
  直接走 `/api/jobs/{id}/workbench` + medium 粒度 + 最近主简历）；A1 预检按
  节点类型区分快速失败（本地网络错误/超时硬拦截 422，远程保持非阻塞）；
  A2 全 noop 保持 succeeded + 0 有效 diff；对齐运行每租户单线程排队
  （防止 Ollama 7B 被并发拖垮）。

## Implementation Status (2026-08-03)

- Core pipeline stages (diagnose, JD profile, gap analysis, tailor, evaluate)
  are implemented in `src/resualign/`.
- CLI, FastAPI, web UI, crawler URL input, and two-stage extractor are live.
- The regression suite covers 300+ pytest tests at 90%+ coverage; benchmark
  harness is in `benchmarks/` with nine synthetic cases, offline 28/28 goals.
- Phase 10 adds tenant scoping: email/password accounts, bearer-token
  sessions, and tenant-owned analysis jobs (ADR-0013).
- Phase 11 adds a SaaS workbench: versioned Master Resume management,
  per-tenant applications, pinned resume snapshots, and application reruns.
- Phase 16 closes the personal workbench loop: independent resume diagnosis,
  job-specific final drafts with refresh recovery and save-as-new-resume,
  JD parse failure fallback with salary prefill, classification degradation
  and reclassification, and frontend vocabulary sync. A unified
  desktop/mobile Playwright gate covers the new and old flows in CI.
- Phase 18 redesigns the frontend as a card-based local workbench with
  CSS-only component motion: list stagger, nav/segmented indicators, progress
  pulse, diff reveal, toast and skeleton feedback, all gated by
  `prefers-reduced-motion`. ADR-0026 supersedes the ADR-0017 old-class
  clause for the v3 shell; `data-*` / `aria-*` and route contracts remain
  unchanged. ADR-0025 removes the delivery appraisal, delivery-weight
  evaluation, and salary-benchmark surfaces.
- Workbench latency optimization (ADR-0018): JD profile + gap analysis are one
  LLM call, a diagnosis cache is reused when the same resume reruns, and long
  JD contexts are capped. Cold workbench runs drop from 4 to 3 LLM calls;
  cached reruns drop to 2. `benchmarks/latency_benchmark.py` reproduces the
  wall-clock gain at 4.0s -> 3.0s -> 2.0s with simulated 1s calls.
- The web UI defaults to personal mode: no login screen, anonymous requests
  map to a stable local tenant, and 401 responses render as readable local
  errors without login modals. `RESUALIGN_PERSONAL_MODE=0` re-enables the
  dormant auth branch, but personal mode is the only delivered default.

## Pipeline Stages (long-term vision)

**Stage 1 — JD Ingestion**
Client-side capture via the collector userscript (划词 / 实习僧 Specific 模式)
or pasted JD text into `POST /api/jobs/local-ingest` / `POST /api/jobs`.
Backend crawling was retired (2026-08-27 de-bloat): raw text → LLM structured
extraction → standard JSON; JD links are captured by the userscript, never
fetched server-side.

**Stage 2 — JD Profiling**
Deep analysis of a JD: extract must-have vs nice-to-have, hard skills vs soft skills, business scenarios (high-concurrency, low-latency, etc.). Produces a \JDProfile\.

**Stage 3 — Gap Analysis**
Compare Master Resume against JDProfile. Output a structured gap report: missing keywords, misaligned emphasis, weak evidence.

**Stage 4 — Dynamic Tailoring**
Rewrite resume sections to close gaps. **Iron rule: never invent.** LLM may rephrase, reorder, or re-emphasize existing facts only. Provenance tracked per diff.

**Stage 5 — Evaluation**
LLM-as-Judge: compare original vs tailored resume against the JD. Score improvement, flag hallucinations.

## Token Optimization Principle

Two-stage extraction for all long texts:
1. Lightweight pass (regex / NLP heuristics) to narrow scope
2. LLM pass for refinement on the narrowed context

Applies to JD ingestion, resume parsing, and gap analysis. Saves 60-80% token cost on long documents.

## Core Entities

**Job Description (JD)**
A textual description of a job opening. In the minimal version, provided inline (\--jd\) or from file (\--jd-file\). In the full version, crawled and structured by the ingestion pipeline.

**JD Profile**
Structured extraction of a JD: must-have skills, nice-to-have skills, soft skills, business scenarios, required years of experience, education requirements. Used as the target for gap analysis.

**Master Resume**
The candidate's full, un-tailored resume. The single source of truth that all tailored versions derive from. The gap analysis and tailoring engine always reference back to this to prevent hallucination.

**简历中心 (Resume Center)**
The Master Resume management view. UI canonical routing semantics: the list
view (all resumes) and the single-resume archive are different entries —
`#/resume/list` and the legacy plural alias `#/resumes` BOTH open the list;
only `#/resume/<id>` (or bare `#/resume`, which opens the newest resume's
archive) enters a single archive page.
_Avoid_: `#/resumes` opening a single archive (2026-08-28 UX walkthrough P1-A
regression), list and archive sharing one route without a list sentinel.

**Gap Report**
Structured comparison between Master Resume and JD Profile. Lists missing keywords, misaligned descriptions (emphasis on wrong aspects), and strength matches (good alignment to keep).

**Tailored Resume**
A version of the Master Resume rewritten for a specific JD. Every change traces back to a source sentence in the Master Resume. No invented content.

**采纳率 (Adoption Ratio)**
近 7 天窗口内，保存定稿时被标记为 accepted 的 diff 数 / 定稿时的 diff 总数
（`alignment_metrics` 按 tenant+日聚合）。零分母如实显示「—」，不伪装成
100%。它度量"模型建议里有多少被用户认为值得保留"，是对齐质量的核心信号。
2026-09-10 起驾驶舱 KPI 卡主数字不再展示该比率（低服从率在首页核心位
构成负向引导），降级为卡内明细「采纳 Y/Z 条建议」。
_Avoid_: 把 runs（运行次数）当作分母；把单个岗位的历史采纳状态当作窗口采纳率；
把采纳率百分比当驾驶舱主指标。

**已优化条目 (Optimized Entries)**
窗口内被用户采纳并进入定稿的 diff 总数。驾驶舱 KPI 卡的主数字口径：
单调只增、强调"工具帮你改了多少"的进步叙事，与 Aha 指标（采纳溯源卡存
终稿）同源但口径更宽（Aha 强调首次达成，本指标强调累计量）。
_Avoid_: 与「采纳率」混用（一个是量、一个是率）；把定稿保存次数当作条目数。

**简单模式 / 专家模式 (Settings Modes)**
设置页的双视角。简单模式面向求职者：只保留连接 AI 助手所需的最小配置
（服务商、模型、API Key、测试连接）；专家模式面向运维者：完整暴露节点
管理、成本护栏、Guardrails、自动化规则与词表。无任何已配置节点时默认
简单模式；专家需用户显式切换。
_Avoid_: 把 Guardrails/超时等极客配置塞进简单模式；用「高级设置」折叠
代替真双模式（2026-09-10 决策）。

**投递结果归因 (Application Result)**
用户对一份已投递定稿的结局标注：过筛通过 (screen_pass) / 简历挂筛
(ats_reject) / 暂无回音 (no_response) / 其他 (other)。可选字段，不改变
投递状态机的任何行为（ADR-0027 时间线照旧）；它是验证"对齐是否有效"
（对齐 vs 未对齐简历通过率）的原始数据。
_Avoid_: 把归因当作第六种投递状态；用归因自动推导 Alignment 或看板列。

**Eval Score**
Quality metric from LLM-as-Judge: how well the tailored resume matches the JD, whether any hallucination was detected, and what fraction of gaps were addressed.
UI 中称「对齐评估」，区别于「投递评估」（Worth Appraisal）。默认关闭，可在设置页设全局默认、工作台按次勾选。
_Avoid_: 投递评估 (Worth Appraisal), evaluation tab

**Engine / Pipeline**
The core orchestration. In the minimal version: parse → diagnose → align → output. In the full version: ingest → profile → gap → tailor → evaluate. Accepts a \ResuAlignConfig\ and returns a \Report\. Frontend-agnostic.

**Resume**
A candidate's professional profile, submitted as a file in PDF, DOCX, or plain-text format. The system extracts raw text for LLM analysis.

**Diagnosis** *(minimal version)*
An LLM-produced evaluation of a resume, containing a score (0–100), a list of detected skills, and a list of textual issues/improvement suggestions. Produced without any JD context.
UI 中称「诊断分」，不再用作「匹配度」。

**Match Score**
The resume-to-JD fit percentage shown on jobs and workbench. Primary source
is the Gap Report's gap match score; when alignment evaluation (Eval) ran,
the Eval Score's jd_match_score is used and labeled "来自对齐评估".
_Avoid_: 匹配率, fit score (ambiguous with Worth Appraisal)

**Alignment** *(minimal version)*
The process of comparing a resume with a specific JD and generating suggested edits.
UI 中「对齐」只指该过程；「已对齐」= 该岗位 final draft 的 alignment_status
为 succeeded（看板 badge 用，不是第 6 种投递状态）。
_Avoid_: 对齐快照, 对齐成功当状态流转用

**Diff**
A single atomic edit suggestion. Carries a type (add/modify/remove), the original sentence, proposed sentence, reason, confidence, and a **provenance field** linking back to the exact source sentence in the Master Resume. Never invents.

**无效建议 / noop Diff**
对齐产出的 modify/remove diff 中 `original` 与 `proposed` 逐字相同者
（如模型自述"无可用改动"却仍生成一条 modify）。这类 diff 不计入有效建议：
移入 `invalid_diffs`，`diffs` 只含真实改动。

**无建议（badge）**
零可用产出对齐的终端语义，按证据分型（ADR-0041 决定 5 裁决，实现走
#111）：新增 `usable_diffs` 计数（noop 过滤与 #74 拦截后的有效 diff 数）。
**有缺口但 usable=0 → `failed` + reason `no_output`**，可重跑；
**无缺口（gap 报告为空）且 usable=0 → 保 `succeeded`**，徽章
「无缺口 · 无需改写」，不得渲染为「已对齐」。驾驶舱「完成对齐」分子只数
`usable_diffs≥1`，「100% 完成率」从制度上不可能出现。旧语义（全 noop 仍
succeeded + 琥珀「无建议」徽章）自本裁决起废弃。
_Avoid_: 拿「跑完没报错」当「产出了价值」；把「无缺口」当可信结论——
小模型摆烂与真无缺口数据同形，徽章文案必须带换模型重跑引导

**节点预检（LLM pre-flight probe）**
对齐排队前对实际服务节点（激活节点，否则 .env/默认配置）做的一次 5s 最小
连通 + 鉴权探测。确定性 HTTP 失败（401/402/403）对所有节点硬拦截为
422 + 引导；本地节点（Ollama 或 localhost base_url）的网络错误/超时同样
硬拦截（本地服务未起是确定性失败）；远程节点的网络错误/超时保持非阻塞，
由 `last_alignment_error` 延迟透出，避免云服务瞬时抖动误伤。

**单岗对齐 / 批量对齐 / 批量对比矩阵**
单岗对齐 = 看板卡片按 alignment_status 显示的「开始对齐 / 重新对齐」按钮，
直接 POST `/api/jobs/{id}/workbench`，默认 medium 粒度 + 最近创建主简历。
批量对齐 = 看板「批量对齐」按钮，走 `/api/batch-align`（`selector="pending"`，
覆盖 idle/failed/卡死 queued），结果在「批量对比矩阵」面板展示。两者共用
同一后端排队与并发上限（每租户同时最多 1 个运行）。

**Report** *(current)*
Combined output: diagnosis + alignment diffs + metadata. Printed to terminal and optionally written to JSON.

**Report** *(full version)*
Extended output: JD profile + gap report + tailored resume + eval score. All sections referenceable independently by frontends.

## Delivery & Progress

**Analysis Job**
An asynchronous run of the alignment pipeline owned by the Web/API layer. It
transitions through queued, running, succeeded, and failed, and eventually
holds a Report. Jobs are persisted in SQLite and scoped to the owning tenant;
queued/running jobs interrupted by a restart end in a clear failed state.
_Avoid_: request, task

**User**
An account with an email and a hashed password that owns a tenant workspace.
Authentication uses opaque bearer tokens with hashed session records.
_Avoid_: account holder, login

**Tenant**
The scoping boundary for jobs, master resumes, and applications. Every user is
a tenant in the MVP; cross-tenant reads behave like missing resources.
_Avoid_: organization, workspace owner

**Master Resume Version**
An immutable snapshot of a Master Resume. Updating the resume appends a new
version; rollback points the current version back without rewriting history.
_Avoid_: resume edit, history entry

**Application** *(legacy)*
A dormant per-tenant record that previously pinned a Master Resume version
and analysis job. The delivery loop no longer tracks applications through
this entity; Job is the single source of truth (ADR-0027).
_Avoid_: job application, submission

**Stage Progress**
A notification emitted before each pipeline stage, carrying the stage name and
a human-readable message. The engine stays I/O-free by handing progress to a
callback instead of printing.
_Avoid_: status text, log line

### Delivery Loop (投递闭环)

**投递闭环 (Delivery Loop)**
The canonical job-hunting journey: 岗位库 → 工作台对齐 → 记录投递 → 安排跟进 →
终态收口. Job is the single source of truth for the whole loop.
_Avoid_: Application 双轨记录, 投递记录面板

**状态生命周期 (Status Lifecycle)**
A half-constrained transition policy: forward moves auto-fill timestamps and
clear later-stage fields; backward corrections require explicit confirmation
and clean stale fields; terminal states keep historical timestamps.
_Avoid_: 自由改状态, 无约束状态

**记录投递 (Record Application)**
A one-click action that stamps today's applied_at and moves the Job to 已投递;
it is idempotent and never downgrades a later stage.
_Avoid_: 重复记录, 倒回状态

**投递定稿快照 (Applied Draft Snapshot)**
An immutable per-application copy of the Job's final_draft, match_score,
master-resume reference, and applied_at, captured atomically when 记录投递
transitions a Job into 已投递. The snapshot, not the mutable final_draft,
is what a later 面试回溯 shows.
Snapshots are append-only: re-recording the same Job appends a new
`version_index` row instead of overwriting, and the drawer lists them newest
first. Legacy applied Jobs without a snapshot fall back to the current
final_draft with an explicit 早期投递版本 warning.
UI canonical term: **投递快照**（快照抽屉 / 工作台入口统一叫法）。
_Avoid_: 对齐快照, 记录快照, 投递版本快照, 当前定稿冒充投递版,
快照可被覆盖, 同岗多轮覆盖

**安排跟进 (Schedule Follow-up)**
A quick capture of interview stage, next step, and due time that updates the
Job and its active reminder in one step.
_Avoid_: 详情弹窗手工多步

**历史峰值漏斗 (Historical Peak Funnel)**
Funnel metrics derived from the strongest historical evidence
(offer_at > applied_at > status), so withdrawn jobs keep their past-stage
credit.
_Avoid_: 只看当前状态

**待跟进提醒 (Follow-up Reminder)**
A due-based reminder shown only for active stages (已投递/面试中); terminal
states automatically stop reminders.
_Avoid_: 终态仍提醒

**直达投递 (Direct Application)**
A 去投递 action that opens the Job's source_url so the user can submit the
tailored resume; missing links route to a 补链接 flow.
_Avoid_: 详情里找不到 JD 原文

**JD Source**
Anything that turns a job posting reference into JD text: an inline paste, a
file, a crawled URL, or (future) an agent-based fetcher. Frontends treat all
JD Sources as producing the same plain-text input to the pipeline.
_Avoid_: fetcher, scraper

**Site Handler**
A site-specific extraction strategy for a known job board, such as LinkedIn or
BOSS直聘. Unknown boards use generic extraction rather than failing.

**双模摄入 (Dual-Mode Ingestion)**
The client-side JD capture strategy: a Specific mode with a high-precision
extractor for 实习僧 (shixiseng.com) job pages, plus a Universal mode that
ingests any user-selected JD text from any career-site page together with
document.title and the page URL. Both modes POST to the local-ingest endpoint.
_Avoid_: 反爬对抗, 后端常驻无头浏览器

**本地摄入端点 (Local Ingest Endpoint)**
`POST /api/jobs/local-ingest`, a dedicated local-only job-creation endpoint
that accepts structured page fields or raw selected JD text. It performs only
deterministic parsing on the request path, marks new jobs
`classification_pending=1`, and never overwrites an existing Job on duplicate.
_Avoid_: 复用批量导入, 公网导入入口

**Local Ingest Token**
The secret carried in the `X-ResuAlign-Token` request header for the
local-ingest endpoint. The server generates it on first start, the settings
page can copy or regenerate it, and the userscript prompts for it once and
re-prompts on 401.
_Avoid_: 免鉴权 localhost 信任, 用户自填双端 token

## Benchmark & Quality

**Benchmark Case**
A synthetic resume + JD pair with concrete expected tailoring directions and a
provenance note. Cases are authored, PII-free, and stable for offline
regression runs.
_Avoid_: fixture, sample

**Expected Direction**
A concrete tailoring goal attached to a Benchmark Case, used by the regression
harness to measure keyword coverage.

**Case Tag**
Optional metadata on a Benchmark Case describing role, domain, or language;
reserved for future subset selection without changing the case schema.

## Configuration

**ResuAlignConfig**
A dataclass holding all runtime configuration (provider, api_key, model, base_url, etc.). Can be constructed from:
  1. Explicit kwargs (programmatic API / future Web layer)
  2. \dotenv\ + env var fallback (CLI convenience)

CLI-specific flags (like \--output-dir\) live in the CLI layer and are translated into \ResuAlignConfig\ before calling the engine.

**Provider**
The LLM service backend. Supported values: \deepseek\, \openrouter\, \ollama\. Mapped to base URLs internally.

**Config Source**
A layer in the priority stack: CLI argument > \.env\ file > environment variable. Higher layers override lower ones.

## Module Boundaries (full vision)

**esualign/engine.py\**
Pipeline orchestrator. Imports stage modules, chains them. Frontend-agnostic. No argparse, no HTTP, no I/O.

**esualign/cli.py\**
CLI frontend. Parses arguments → builds config → calls \engine.run()\ → prints/dumps report.

**esualign/api.py\** *(future)*
FastAPI frontend. Builds config from request params → calls \engine.run()\ → returns JSON response.

**esualign/parser.py\**
File-format abstraction: PDF/DOCX/txt → plain text.

**esualign/llm.py\**
LLM interaction. Builds prompt, sends HTTP request, parses JSON response. Retries on failure.

**esualign/models.py\**
Data classes: \DiffItem\, \Analysis\, \Report\, \ResuAlignConfig\, plus future types: \JDProfile\, \GapReport\, \TailoredResume\, \EvalScore\.

**esualign/extractor.py\** *(future)*
Two-stage extraction: regex/NLP → LLM refinement.

**esualign/crawler.py\** *(future)*
JD crawling abstraction. Playwright/Selenium for career sites.

**esualign/jd_profiler.py\** *(future)*
JD → structured \JDProfile\. Prompt + JSON schema for must-have/nice-to-have, skills, scenarios.

**esualign/gap_analyzer.py\** *(future)*
Master Resume + JDProfile → \GapReport\. Keyword matching + LLM-based semantic gap detection.

**esualign/tailor.py\** *(future)*
Master Resume + GapReport → TailoredResume. Constraint-guided rewriting with provenance tracking.

**esualign/evaluator.py\** *(future)*
LLM-as-Judge: original vs tailored vs JD. Produces EvalScore + hallucination audit.

## Key Quality Attributes

- **Provenance**: every word in a tailored resume traces back to the Master Resume. No hallucination.
- **Testability**: LLM calls mockable at the httpx transport layer; parsers testable with real fixture files.
- **Frontend-agnostic engine**: \engine.run()\ accepts config + input, returns Report. No I/O inside engine.
- **Token efficiency**: two-stage extraction on all long-text paths.
- **Simplicity**: Single-responsibility modules, no framework, minimal runtime dependencies.
- **Observability**: Warnings on stderr; progress markers for long operations.

## Workbench Modules (2026-08-02)

**Job Library**
The core entity of the personal workbench. A persisted, tenant-scoped store of
job postings with raw JD text, source, location, salary range, classification
tags, and application status. All other workbench modules read from it.
_Avoid_: job feed, scraped cache

**Job Classification**
The multi-dimensional tagging of a Job Library record: job function (backend,
frontend, algorithm, data, client, ops, testing, product, design, operations),
seniority (intern, campus, junior, mid, senior, expert), and free-form
technology/domain tags. Produced by the LLM and editable by the user.
_Avoid_: job category, job type

**Master Resume Diagnosis**
An async no-JD pipeline run against one Master Resume, producing a 0-100
score, skills, issues, and suggestions. The resume record keeps the latest
diagnosis job id so archive refreshes restore the most recent result.
诊断结果会被 Single-Job Workspace 复用（诊断缓存复用）：同一主简历在工作台
rerun 时跳过 diagnose 阶段的 LLM 调用。
_Avoid_: analyze-only page, report history

**Final Draft**
A job-specific persisted copy of an accepted tailored resume. It survives
refresh and re-opening of the workspace, overwrites as a new version, and can
be explicitly saved as a new Master Resume without mutating the original.
_Avoid_: automatic master resume overwrite, throwaway draft

**Classification Pending**
A durable library-job flag set when the classification LLM fails. The job is
still saved, shows an amber badge, and can be reclassified later without
blocking ingestion or batch import.
_Avoid_: failed row skip, silent unknown classification

**Vocabulary Sync**
Job function, seniority, and status options rendered by the library filters
and edit modal come from `/api/settings`; the frontend caches the list per
page load and falls back to built-ins when the settings API is unavailable.
_Avoid_: duplicated hard-coded dropdowns, per-filter settings requests

**Application Status**
A lightweight per-job lifecycle marker: not applied, applied, interviewing,
offered, or declined. The Single-Job Workspace is the one-stop entry for
status updates and the tailored draft.
_Avoid_: pipeline stage, funnel state

**Interview Stage**
The interview-process phase marker on a Job (first round, second round, HR
round, offer talk). Orthogonal to Application Status: status is the funnel
bucket, interview stage is the follow-up anchor inside "interviewing".
_Avoid_: interview phase, round number

**Follow-up**
A Job's structured follow-up information: a free-text next action, an
optional due datetime, and an Interview Stage. Drives the due reminders.
_Avoid_: next step (ambiguous with Batch Decision), reminder entry

**Batch Decision**
The per-job conclusion shown in the batch alignment matrix (apply, consider,
skip). Distinct from Follow-up despite sharing the label "下一步" in the UI.
_Avoid_: next step (ambiguous with Follow-up)

**Single-Job Workspace**
The per-job working page combining JD analysis, status, and generation of a
tailored resume draft from the Master Resume version.
_Avoid_: job detail page, application form

**Rewrite Granularity**
The prompt-level rewrite intensity for the tailor stage: `fine` (微调) keeps
structure and wording, `medium` (重构, default) rewrites within the existing
structure, and `coarse` (重塑) permits full restructure.

## Agent 化（指挥台 / Agent Orchestration, 2026-09-14）

**指挥台 (Command Deck)**
产品内的 agent 操作员入口：一句自然语言指令驱动既有流程，与工作台并列、同数据同队列——是给产品加席位，不是改造工作台。它的定义特征只有「单入口 + 自然语言路由」两件事；**执行期是否由模型逐步决定下一步（决策循环）不属于它的定义**（ADR-0040：先做厚预设流，循环只在实测到决策点处获准）。
_Avoid_: 聊天机器人, 第二条对齐路径（2026-08 试点正死于「无真实入口的并行路径」）；把「要不要上指挥台」偷换成「要不要上循环」（两者独立获准，2026-09-14 裁决）

**预设流 (Macro)**
由服务端预先定好的参数与顺序、一次调用即可跑完的流程编排；执行期不需要对中间结果做判断。四个招牌场景（挑高分 / 归因 / 批量对齐 / 周复盘）都属这一型。
_Avoid_: 把预设流叫成 agent 编排；为它付决策循环的成本与风险

**决策点 (Decision Point)**
执行过程中下一步动作取决于运行时观察、且该观察无法预先枚举成调用参数的位置；是 agent 循环与普通 API 调用的分界。审计判据：某步若在 30 次重放里能被一条确定性规则复现同一选择，它就不是决策点。
_Avoid_: 把「选哪份简历」「阈值取多少」这类服务端可确定性算出的取值当决策点

**三线门槛 (Three Gates)**
Phase A 开工前的三道灯（ADR-0040，accepted）：能力线 = Phase 0 过线（只证明当前模型能不能做）；地基线 = 对齐成功率回到可接受线（可接受线由 #110 诊断产出，不许先拍）+ 零 diff 假成功被 CI 锁死（#111）；需求线 = 合格例 ≥3（见下条）。三线全亮才开工，Phase 0 过线只点亮其中一条。地基线两票与 Phase 0/harness **并行**，不排队。
_Avoid_: 用 Phase 0 过线当三线总和；把「未上线所以验不了」当成需求线的 false 理由；把「可接受线」留成开口术语等最忙那天现场解释

**合格例 (Qualifying Case)**
需求线的计数单位，三条全满足才算一例：同一份简历 ≥3 轮「改→评→改」 ∧ ≥1 轮有 diff 采纳 ∧ ≥2 轮的触发原因是上一轮评测结论。第三条是因果链条款——把决策点的判据（可被确定性规则复现即非决策点）反过来用在需求上：没有因果链的三轮手点不证明需要循环。狗食数据（租户 `local`）计入。
_Avoid_: 拿「同一简历跑了三次」凑计数（缺采纳与因果链，会伪造循环需求）

**决策循环 (Explicit Loop)**
执行期由模型逐步决定下一个工具调用的编排形态，与**预设流**相对。Phase A 的实现顺序是先做厚预设流 + 单入口路由，循环按实测决策点再决定（ADR-0037 模板臂的产品化写法）。
_Avoid_: 把「agent 项目」默认等于「有循环」；为演示效果给不可枚举假设为真

**授权档位 (Approval Tier)**
agent 可用工具的三档授权：读档自由调用；写档只能经既有入口排队（受租户门、成本闸、看门狗约束）；审批档（采纳 diff、定稿、覆盖主简历、导出、删除）只能提议，人确认后才生效。
_Avoid_: agent 直接定稿, 跳过审批档, 无上限的「管理员工具」

**轨迹评测 (Trajectory Eval)**
评 agent 一次会话的完整步骤序列而非只看终态：任务成功率、工具调用正确率、步数与成本上限。放 `benchmarks/agent/`，接 CI。
_Avoid_: 只看终态（终态可能是编出来的调用凑巧走到的）

**无编造率 (No-Fabrication Rate)**
轨迹评测的核心指标：会话中不含无出处内容的比例；「不捏造事实」铁律在 agent 维度的延伸，对抗用例下必须 100%。
_Avoid_: 用 Eval Score 高当无编造的证据

**轨迹报价 (Trajectory Quote)**
含写档步骤的 agent 指令在执行前向用户出示的两行预演卡：决策调用行（agent 桶余量，硬顶只罩这行）＋ 引擎调用行（与按钮路径共享的每日池余量，撞顶即既有的排队拒绝）。数字一律算术派生，不许模型口算。读档轨迹不设报价门；报价是事前知情，审批档是事后生效，两道门互不替代。
_Avoid_: 只在「大轨迹」才弹报价（Q3 裁决否决）；把引擎行报成 agent 桶的死刑（它是别人家账本的行情）

**agent 预算卡 (Agent Budget Card)**
agent 循环决策调用的专属额度账本：轨迹起点原子预留、步界结算、退还未消费；agent 派生的引擎调用不在账上——走按钮路径同一共享池。帽值以「招牌演示不撞帽」标定（口径与红线见 ADR-0039）。
_Avoid_: 把引擎调用计入 agent 桶（按钮花谁的池子，agent 按的就花谁的池子）；「撞顶次日自动续跑」（零自动语义，续跑=新指令+重新报价）

**门禁摘要 (Gate Report)**
skill 验证器每次运行输出的一行机器可读汇总：`N diffs / K blocked
(missing/fabricated/noop) / sha256`。探针判据的唯一取证形式——非作者首跑
报告必须附此行才算数（贴得出即真跑过，见 ADR-0041 决定 4）。
_Avoid_: 口头「我用过了」当首跑；agent 转述或重打摘要（必须原样粘贴脚本输出）

**合格例取证 (Qualifying Evidence)**
验证器落盘的 append-only JSONL 运行日志（时间戳、简历哈希、轮次、触发
原因、采纳计数），用于证明 ADR-0040 (a) 合格例的因果链：第 n+1 轮的
trigger 必须指向第 n 轮复评结论。狗食数据计入（2026-09-14 裁决）。
_注_：轮次连续性由验证器自己判定并写入 `chain{prev_round,cites_prev}`
（2026-09-15 R5），不再靠 agent 自觉声明；`resume_sha256` 跨轮不变即
「同一份文本重放」，不算迭代证据。
_Avoid_: 手填轮次凑数（无 JSONL 佐证不算）；无因果链的三轮手点

**skill 探针 (Skill Probe)**
掉头期主线：独立公开仓库（默认命名 `truetailor`）= prompt skill +
单文件确定性验证器（stdlib 零依赖），在 app 之外验证「逐条可溯源改写」
的需求。判据、时间盒与终态剧本见 ADR-0041 决定 4/9/10。
_注_：仓库已于 2026-09-15 公开（`shing26/truetailor`，MIT），故
`gate.py` 与黄金 fixtures 的**唯一事实源在上游**；主仓持 vendor 副本，
由 `tests/fixtures/gate/VENDOR.json` 哈希清单 + `test_skill_vendor_lock.py`
锁定，改规则须先改上游再同步。
_Avoid_: 把探针当产品第一步（它是需求探针，过与死各有剧本）；证伪后
另起第三渠道（决定 10 禁止）

**冻结令 (Freeze Order)**
探针期内 app 一切新功能冻结（agent 化 Phase A/B、商业化 PRD、扩展期二、
托管 demo），仅保留地基修复 #110/#111 与探针包两类工作。解冻条件唯一：
探针判据「过」（ADR-0041 决定 1/9）。
_注_：ADR-0042 决定 6e 明确自用线推进期间冻结令继续有效；「让自用闭环
好用」的改动须逐项引用该条走例外流程。
_Avoid_: 把体验债修复包装成地基工作绕开冻结；探针观察窗内做落地页或 demo

**探针线 / 自用线 (Probe Line / Dogfood Line)**
掉头期判据的两条**独立**线（ADR-0042 决定 3），各自取证、各自判定，
不许互相顶替。探针线 = ADR-0041 决定 4 原文（非作者首跑 ≥5 例附门禁摘要行，
或 1 例外部完整合格链 = 过；≥100★ 或社区二创 = 强信号；4 周后 <2 例 = 证伪），
测「陌生人要不要它」；自用线 = ADR-0040 需求线 (a) 原文（合格例 ≥3），
测「作者自己在真实投递中会不会反复用它」，取证走合格例取证 JSONL，
输入必须是真实投递过的岗位 JD。
_Avoid_: 用自用线成果去替探针线达标（形态判定仍以探针线为准）；
把自用线当成「反正没人用就先自用」的兜底

**分发未执行 (dist_not_executed)**
ADR-0042 决定 2 新增的判据状态：四渠道 outreach 未在 2026-09-23 24:00 前
全部发出时，判据登记为此态——时钟不启动、判据保持 PENDING、观察窗不开启。
它的作用是把「没发出去」与「发了没人要」在制度上分开，**它不是证伪**；
处置是「先执行分发，再谈判据」。
_Avoid_: 把分发未执行读成探针证伪（会让主线按合同误降级）；
用「反正要重锚」为由拖延分发而不登记
