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
