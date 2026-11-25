/* 职位大厅（Job Hall）——岗位发现与投递工作台。
 *
 * 数据源只有现有 REST API：
 *   GET  /api/jobs?limit=500       职位库（标题/公司/城市/薪资/JD/匹配分）
 *   GET  /api/dashboard            全库计数（侧栏与进度概览共用同一口径）
 *   PATCH /api/jobs/{id}           投递状态与时间线字段
 *
 * 收藏是「候选清单」视图，不新增数据库字段：job_id 存在 localStorage，
 * 真正的投递状态仍以 library_jobs 为唯一事实源。
 */
import {
  api,
  confirmBackwardStatus,
  confirmTerminalStatus,
  ensureVocabulary,
  esc,
  isBackwardJobStatus,
  jobStatusLabel,
  state,
  toast,
} from "./events.js";
import {
  JOB_STATUS_CANONICAL,
  JOB_STATUS_LABELS,
  alignmentBadgeHtml,
  alignmentOutcomeKind,
  boardCard,
  canonicalJobStatus,
  formatSalary,
  jobSourceUrl,
  jobStatusOptionsHtml,
  jobMatchSource,
  renderMarkdown,
} from "./format.js";
import { icon } from "./icons.js";
import {
  bindBoardDrag,
  bindRecommendedPanel,
  runCanvasRenderHooks,
} from "./kanban.js";
import {
  ADVANCE_BUCKETS,
  ADVANCE_LABELS,
  AUDIENCES,
  SALARY_BANDS,
  activeFilterCount,
  advanceBucket,
  audienceLabel,
  cityOptions,
  companyInitial,
  computeHallStats,
  dueItems,
  filterHallJobs,
  functionOptions,
  inferAudience,
  isDeadlineOverdue,
  isDeadlineSoon,
  jobsRequestUrl as buildJobsRequestUrl,
  relativeTime,
  seniorityOptions,
  sortHallJobs,
  statusOptions,
} from "./job-hall-model.js";

const SHORTLIST_KEY = "resualign" + ".jobHall" + ".shortlist" + ".v1";
const JOBS_VIEW_KEY = "resualign.jobs.view";
const JOBS_DETAIL_STATE_KEY = "resualignJobsDetail";
const LIST_PAGE = 50;
const BOARD_PAGE = 20;
/* Server-side list cap (`GET /api/jobs` clamps limit to 500). */
const LIST_FETCH_LIMIT = 500;

/* 看板 chip 与职位页分组条共用这组键（ADR-0069：全页只有一个筛选来源）。
 * 旧键 pending/aligned/final 已删除且不保留别名：aligned 曾把「已定稿」与
 * 「差一次采纳」混在一起，是最误导人的地方。 */
const WORK_FILTERS = [
  { key: "all", label: "全部" },
  ...ADVANCE_BUCKETS.map((key) => ({ key, label: ADVANCE_LABELS[key] })),
];

const EMPTY_FILTERS = Object.freeze({
  query: "",
  audience: "all",
  city: "",
  jobFunction: "",
  seniority: "",
  status: "",
  salary: "",
  matchMin: 0,
  savedOnly: false,
  recentOnly: false,
  work_status: "all",
});

const hall = {
  root: null,
  jobs: [],
  details: new Map(),
  detailLoading: new Set(),
  detailErrors: new Map(),
  dashboard: null,
  total: 0,
  saved: new Set(),
  filters: { ...EMPTY_FILTERS },
  sort: "match_desc",
  view: "list",
  listLimit: LIST_PAGE,
  boardLimit: BOARD_PAGE,
  vocabulary: null,
  laneJobs: null,
  laneKey: null,
  laneToken: 0,
  selectedId: null,
  detailOpen: false,
  detailPushed: false,
  bound: false,
  requestToken: 0,
  paintFrame: null,
};

function detailJob(jobId) {
  if (!jobId) return null;
  return hall.details.get(jobId) || null;
}

function summaryJob(jobId) {
  if (!jobId) return null;
  const lane = Array.isArray(hall.laneJobs) ? hall.laneJobs : [];
  return (
    hall.jobs.find((item) => item.job_id === jobId) ||
    lane.find((item) => item.job_id === jobId) ||
    null
  );
}

function readShortlist() {
  try {
    const raw = localStorage.getItem(SHORTLIST_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(parsed) ? parsed.filter(Boolean) : []);
  } catch {
    return new Set();
  }
}

function writeShortlist(values) {
  try {
    localStorage.setItem(SHORTLIST_KEY, JSON.stringify([...values]));
  } catch {
    /* private mode / storage full: keep the in-memory set for this session */
  }
}

function readJobsViewMode() {
  try {
    return localStorage.getItem(JOBS_VIEW_KEY) === "board" ? "board" : "list";
  } catch {
    return "list";
  }
}

function writeJobsViewMode(mode) {
  hall.view = mode === "board" ? "board" : "list";
  try {
    localStorage.setItem(JOBS_VIEW_KEY, hall.view);
  } catch {
    /* storage unavailable: keep the in-memory choice for this session */
  }
}

function jobWorkState(job) {
  const status = String(job.alignment_status || "");
  if (status === "queued" || status === "running") return "running";
  // 五桶之外只剩「无缺口 / 无安全改写」这类已收口状态。
  return advanceBucket(job) || "no_gap";
}

function matchesWorkFilter(job, key) {
  if (key === "all" || !key) return true;
  return advanceBucket(job) === key;
}

function safeUrl(value) {
  const url = String(value || "").trim();
  return /^https?:\/\//i.test(url) ? url : "";
}

function displayWhen(value, dateOnly = false) {
  const raw = String(value || "").trim();
  if (!raw) return "—";
  return dateOnly ? raw.slice(0, 10) : raw.replace("T", " ").slice(0, 16);
}

function displayDate(ms) {
  if (!Number.isFinite(ms)) return "—";
  const date = new Date(ms);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
    date.getDate(),
  ).padStart(2, "0")}`;
}

function statusTone(status) {
  const canonical = canonicalJobStatus(status);
  if (canonical === "offer") return "success";
  if (canonical === "interview") return "info";
  if (canonical === "withdrawn") return "danger";
  if (canonical === "applied") return "accent";
  return "neutral";
}

function logoHtml(job, size = "md") {
  const company = job && job.company ? job.company : "未知公司";
  return `<span class="jh-logo jh-logo--${size}" aria-hidden="true">${esc(
    companyInitial(company),
  )}</span>`;
}

function workStateBadge(job) {
  const state = jobWorkState(job);
  const kind = alignmentOutcomeKind(job);
  let label = "待分析";
  let tone = "neutral";
  if (state === "running") {
    label = "对齐中";
    tone = "info";
  } else if (state === "failed") {
    label =
      kind === "no_safe_rewrite"
        ? "无安全改写"
        : "对齐失败";
    tone = "danger";
  } else if (state === "pending_draft") {
    label = "待定稿";
    tone = "accent";
  } else if (state === "finalized") {
    label = "已定稿";
    tone = "success";
  } else if (state === "unanalyzed") {
    label = "未预分析";
    tone = "neutral";
  } else if (state === "unaligned") {
    label = "未对齐";
    tone = "warning";
  } else if (state === "no_gap") {
    label = "无缺口";
    tone = "warning";
  }
  const hint =
    state === "failed"
      ? String(job.alignment_error || "本轮未产出可用改写建议")
      : state === "no_gap"
        ? "该岗位没有需要改写的缺口"
        : state === "pending_draft"
          ? "已产出可用建议，采纳并保存定稿即完成闭环"
          : "";
  return `<span class="jh-dotline jh-dotline--${tone}"${
    hint ? ` title="${esc(hint)}"` : ""
  }>${esc(label)}</span>`;
}

function deadlineBadge(job) {
  if (isDeadlineOverdue(job)) {
    return '<span class="jh-deadline is-overdue">已截止</span>';
  }
  if (isDeadlineSoon(job)) {
    return '<span class="jh-deadline">7 天内截止</span>';
  }
  return "";
}

function tagHtml(value) {
  const text = String(value || "").trim();
  return text ? `<span class="jh-tag">${esc(text)}</span>` : "";
}

function taglineHtml(values) {
  const parts = values.map((value) => String(value || "").trim()).filter(Boolean);
  return parts.length
    ? `<span class="jh-job__tagline">${esc(parts.join(" · "))}</span>`
    : "";
}

/* 投递状态与工作状态共用「4px 状态点 + 灰字」一种签名：卡片、详情、看板
 * 都不再出现彩色 pill，颜色只留在点上。 */
function statusLine(job) {
  return `<span class="jh-dotline jh-dotline--${statusTone(
    job.status,
  )}">${esc(jobStatusLabel(job.status))}</span>`;
}

function optionHtml(values, selected, allLabel) {
  const head = `<option value="">${esc(allLabel)}</option>`;
  return (
    head +
    values
      .map((item) => {
        const value = typeof item === "string" ? item : item.value;
        const label = typeof item === "string" ? item : item.label;
        return `<option value="${esc(value)}" ${
          String(selected || "") === String(value) ? "selected" : ""
        }>${esc(label)}</option>`;
      })
      .join("")
  );
}

function selectedOrDefault(id) {
  const job = (hall.jobs || []).find((item) => item.job_id === id);
  if (job) return job.job_id;
  const visible = sortHallJobs(
    filterHallJobs(hall.jobs, hall.filters, hall.saved),
    hall.sort,
  );
  return visible.length ? visible[0].job_id : null;
}

function loadingHtml() {
  return `<div class="view jh-view">
    <div class="jh-loading" role="status" aria-live="polite">
      <span class="skeleton is-shimmer jh-loading__bar"></span>
      <span class="skeleton is-shimmer jh-loading__bar"></span>
      <span class="jh-loading__hint">正在读取职位库…</span>
    </div>
  </div>`;
}

function errorHtml(message) {
  return `<div class="view jh-view">
    <div class="jh-empty jh-empty--error" role="alert">
      <span class="jh-empty__icon">${icon("triangle-alert", 24)}</span>
      <h3>职位库暂时没有响应</h3>
      <p>${esc(message || "请检查本地服务后重试。")}</p>
      <div class="jh-empty__actions">
        <button class="btn btn-primary" type="button" data-jh-retry>重新加载</button>
        <a class="btn btn-outline" href="#/jobs">去职位库</a>
      </div>
    </div>
  </div>`;
}

const MERGED_SORTS = [
  { value: "match_score_desc", label: "匹配优先" },
  { value: "updated_at_desc", label: "最近更新" },
  { value: "match_score_asc", label: "匹配从低到高" },
  { value: "salary_desc", label: "薪资从高到低" },
  { value: "deadline_asc", label: "截止日期最近" },
];

function sortOptionsHtml() {
  return MERGED_SORTS.map(
    (item) =>
      `<option value="${esc(item.value)}" ${
        hall.sort === item.value ? "selected" : ""
      }>${esc(item.label)}</option>`,
  ).join("");
}

function workFilterHtml() {
  const counts = workFilterCounts();
  return WORK_FILTERS.map(
    ({ key, label }) =>
      `<button type="button" class="jh-workbtn${
        hall.filters.work_status === key ? " is-active" : ""
      }" data-jh-work="${key}" aria-pressed="${
        hall.filters.work_status === key
      }">${label}<span data-jh-count>${
        counts[key] || 0
      }</span></button>`,
  ).join("");
}

/* 分组条的副标题：每段回答「这堆岗位现在缺什么」。
 * 键名与后端 advance_bucket 一致；顺序 = 离完成由近到远。 */
const ADVANCE_HINTS = {
  pending_draft: "已跑完对齐，差你采纳",
  unanalyzed: "导入后还没跑过",
  unaligned: "有 JD 画像，没生成建议",
  failed: "零产出 / 额度 / 服务错误",
  finalized: "可直接导出或记录投递",
};

function advanceLanesHtml() {
  const counts = workFilterCounts();
  return `<div class="jh-lanes" role="group" aria-label="按待推进阶段分组">${ADVANCE_BUCKETS.map(
    (key) => {
      const active = hall.filters.work_status === key;
      return `<button type="button" class="jh-lane jh-lane--${key}${
        active ? " is-active" : ""
      }" data-jh-work="${key}" aria-pressed="${active}">
        <span class="jh-lane__top"><b class="jh-lane__n" data-jh-count>${
          counts[key] || 0
        }</b><i class="jh-lane__dot" aria-hidden="true"></i></span>
        <span class="jh-lane__label">${esc(ADVANCE_LABELS[key])}</span>
        <span class="jh-lane__hint">${esc(ADVANCE_HINTS[key] || "")}</span>
      </button>`;
    },
  ).join("")}</div>`;
}

function advanceNoteHtml(visibleCount) {
  const key = hall.filters.work_status;
  if (!key || key === "all") return "";
  const total = workFilterCounts()[key] || 0;
  const narrowed = Number(visibleCount) !== total;
  return `<div class="jh-lanenote">
    <span>正在看 <b>${esc(ADVANCE_LABELS[key] || key)}</b>（${
      narrowed ? `筛选后 ${visibleCount} / ${total}` : total
    }）· ${esc(ADVANCE_HINTS[key] || "")}</span>
    <button type="button" class="jh-lanenote__clear" data-jh-work="all">显示全部</button>
  </div>`;
}

function workFilterCounts() {
  const counts = {
    all: hall.jobs.length,
    pending_draft: 0,
    unanalyzed: 0,
    unaligned: 0,
    failed: 0,
    finalized: 0,
  };
  // 服务端计数是全库口径；列表只加载前 500 条，所以优先用它，
  // 未取到（dashboard 请求失败）才退回本地已加载页的计数。
  const remote =
    hall.dashboard && hall.dashboard.advance
      ? hall.dashboard.advance
      : null;
  if (remote) {
    // 「全部」也是全库口径（kpi.jobs），不是已加载页的行数。
    const kpiTotal = Number(
      hall.dashboard && hall.dashboard.kpi && hall.dashboard.kpi.jobs,
    );
    if (Number.isFinite(kpiTotal)) counts.all = kpiTotal;
    for (const key of ADVANCE_BUCKETS) {
      counts[key] = Number(remote[key] || 0);
    }
    return counts;
  }
  for (const job of hall.jobs) {
    const key = advanceBucket(job);
    if (key) counts[key] += 1;
  }
  return counts;
}

function listSectionHtml() {
  return `<section class="jh-results" aria-label="岗位列表">
    <div class="jh-results__head">
      <div>
        <strong data-jh-list-title>岗位列表</strong>
        <span class="jh-results__sub" data-jh-list-sub>按匹配度优先</span>
      </div>
      <label class="jh-sort">
        <span>排序</span>
        <select data-jh-sort data-job-sort aria-label="岗位排序">${sortOptionsHtml()}</select>
      </label>
    </div>
    <div class="jh-list" data-jh-list aria-live="polite"></div>
  </section>
  <aside class="jh-detail" data-jh-detail aria-label="岗位详情"></aside>`;
}

function boardSectionHtml() {
  return `<section class="jh-board" aria-label="投递看板">
    <div class="jh-board__toolbar">
      <div class="jh-workfilter" role="group" aria-label="按工作状态筛选">${workFilterHtml()}</div>
      <label class="jh-sort">
        <span>排序</span>
        <select data-jh-sort data-job-sort aria-label="岗位排序">${sortOptionsHtml()}</select>
      </label>
    </div>
    <div id="job-board" class="pipeline-board jh-board__columns" data-jh-board></div>
  </section>
  <aside class="jh-detail jh-detail--drawer" data-jh-detail aria-label="岗位详情"></aside>`;
}

function shellHtml() {
  const cityValues = cityOptions(hall.jobs);
  const functionValues = functionOptions(hall.jobs);
  const seniorityValues = seniorityOptions(hall.jobs);
  const statusValues = statusOptions();
  const isBoard = hall.view === "board";
  const filtersOpen =
    !isBoard &&
    (typeof window === "undefined" ||
      typeof window.matchMedia !== "function" ||
      !window.matchMedia("(max-width: 900px)").matches);
  return `<div class="view jh-view${isBoard ? " is-board" : ""}" data-jh-shell data-jh-mode="${hall.view}">
    <header class="jh-head" data-jobs-topbar>
      <div class="jh-pagehead">
        <div class="jh-pagehead__title">
          <h2 data-jh-page-title>${isBoard ? "投递看板" : "职位大厅"}</h2>
          <p><span data-jh-result-count>共 0 个岗位</span> · 筛选岗位、查看匹配详情并推进投递</p>
        </div>
        <div class="jh-pagehead__actions" data-jobs-tools>
          <div class="jh-viewtoggle" role="group" aria-label="职位视图">
            <button type="button" data-jh-view="list" aria-pressed="${!isBoard}">列表</button>
            <button type="button" data-jh-view="board" aria-pressed="${isBoard}">看板</button>
          </div>
          <details class="jh-menu">
            <summary class="jh-menu__summary" aria-label="批量处理">
              <span class="jh-menu__label">批量处理</span>
              <span class="jh-menu__chevron">${icon("chevron-down", 16)}</span>
              <span class="jh-menu__narrow">${icon("clipboard-list", 16)}</span>
            </summary>
            <div class="jh-menu__body">
              <button type="button" data-recommended-toggle>按简历推荐</button>
              <button type="button" data-action="preanalyze-pending">一键预分析</button>
              <button type="button" data-action="batch-align-pending" data-batch-align>批量对齐</button>
            </div>
          </details>
          <details class="jh-menu">
            <summary class="jh-menu__summary" aria-label="数据">
              <span class="jh-menu__label">数据</span>
              <span class="jh-menu__chevron">${icon("chevron-down", 16)}</span>
              <span class="jh-menu__narrow">${icon("file-text", 16)}</span>
            </summary>
            <div class="jh-menu__body">
              <button type="button" data-action="show-import">批量导入</button>
              <button type="button" data-action="export-jobs-csv">导出 CSV</button>
              <button type="button" data-action="export-jobs-backup">整库备份</button>
            </div>
          </details>
          <button class="btn btn-primary jh-add" type="button" data-action="show-add-job">
            ${icon("plus", 16)} 添加岗位
          </button>
        </div>
      </div>
      <div class="jh-head__row">
        <div class="jh-scope" role="tablist" aria-label="招聘类型">
          ${AUDIENCES.map(
            (item) => `<button type="button" class="jh-scope__tab${
              hall.filters.audience === item.value ? " is-active" : ""
            }" data-jh-audience="${esc(item.value)}" role="tab" aria-selected="${
              hall.filters.audience === item.value
            }">${esc(item.label)}</button>`,
          ).join("")}
        </div>
        <label class="jh-search">
          <span class="jh-search__icon" aria-hidden="true">${icon("search", 20)}</span>
          <input
            type="search"
            name="search"
            data-jh-search
            value="${esc(hall.filters.query)}"
            placeholder="搜索岗位、公司、城市或技能，支持多关键词"
            autocomplete="off"
            spellcheck="false"
            aria-label="搜索岗位、公司、城市或技能，支持多关键词"
          >
        </label>
        <button type="button" class="jh-filterbtn" data-jh-toggle-filters>
          ${icon("sliders-horizontal", 16)} 筛选
          <span class="jh-count" data-jh-filter-count hidden>0</span>
        </button>
        <button type="button" class="jh-linkbtn" data-jh-clear>清除</button>
      </div>
      <div class="jh-head__meta">
        <span class="jh-head__note">校招/社招按岗位标题、职级与 JD 关键词自动归类；筛选在列表和看板之间共享</span>
      </div>
    </header>

    ${isBoard ? "" : advanceLanesHtml()}
    <div data-jh-lanenote>${advanceNoteHtml(0)}</div>

    <section class="jh-progress" aria-label="求职进度概览">
      <div class="jh-metrics" data-jh-metrics></div>
      <div class="jh-progress__foot" data-jh-progress-foot></div>
    </section>

    <div class="jh-workspace${isBoard ? " is-board" : ""}">
      <details class="jh-filters" ${filtersOpen ? "open" : ""} data-jh-filters>
        <summary class="jh-filters__summary">
          <span>筛选</span>
          <span class="jh-count" data-jh-filter-count hidden>0</span>
        </summary>
        <form class="jh-filters__body" data-form="job-filter" data-jh-filter-form>
          <label class="jh-field">
            <span>城市</span>
            <select name="city" data-jh-filter="city">${optionHtml(cityValues, hall.filters.city, "全部城市")}</select>
          </label>
          <label class="jh-field">
            <span>职能</span>
            <select name="job_function" data-jh-filter="jobFunction">${optionHtml(functionValues, hall.filters.jobFunction, "全部职能")}</select>
          </label>
          <label class="jh-field">
            <span>职级 / 经验</span>
            <select name="seniority" data-jh-filter="seniority">${optionHtml(seniorityValues, hall.filters.seniority, "不限经验")}</select>
          </label>
          <label class="jh-field">
            <span>薪资</span>
            <select name="salary" data-jh-filter="salary">${optionHtml(
              SALARY_BANDS.filter((item) => item.value),
              hall.filters.salary,
              "不限薪资",
            )}</select>
          </label>
          <label class="jh-field">
            <span>投递状态</span>
            <select name="status" data-jh-filter="status">${optionHtml(statusValues, hall.filters.status, "全部状态")}</select>
          </label>
          <label class="jh-field">
            <span>匹配分</span>
            <select name="matchMin" data-jh-filter="matchMin">
              <option value="0" ${hall.filters.matchMin ? "" : "selected"}>不限</option>
              <option value="60" ${hall.filters.matchMin === 60 ? "selected" : ""}>60 分以上</option>
              <option value="80" ${hall.filters.matchMin === 80 ? "selected" : ""}>80 分以上</option>
            </select>
          </label>
          <div class="jh-filtergroup">
            <span class="jh-filtergroup__label">工作状态</span>
            <div class="jh-workfilter" role="group" aria-label="按工作状态筛选">${workFilterHtml()}</div>
          </div>
          <div class="jh-quick" role="group" aria-label="快捷筛选">
            <button type="button" class="jh-quick__btn${
              hall.filters.matchMin === 80 ? " is-active" : ""
            }" data-jh-quick="match" aria-pressed="${
              hall.filters.matchMin === 80
            }">${icon("sliders-horizontal", 16)} 高匹配</button>
            <button type="button" class="jh-quick__btn${
              hall.filters.savedOnly ? " is-active" : ""
            }" data-jh-quick="saved" aria-pressed="${
              hall.filters.savedOnly
            }">${icon("bookmark", 16)} 已收藏</button>
            <button type="button" class="jh-quick__btn${
              hall.filters.recentOnly ? " is-active" : ""
            }" data-jh-quick="recent" aria-pressed="${
              hall.filters.recentOnly
            }">${icon("calendar", 16)} 7 天内更新</button>
          </div>
          <p class="jh-filters__hint">收藏只是候选清单；投递/面试/Offer 状态会写回职位库。</p>
        </form>
      </details>

      ${isBoard ? boardSectionHtml() : listSectionHtml()}
    </div>

    <div data-jobs-forms-mount></div>
    <div data-jobs-batch-mount></div>
    <div class="jh-recommended" data-recommended-panel hidden></div>
    <div class="jh-detail-backdrop" data-jh-detail-close data-jh-detail-backdrop hidden></div>
  </div>`;
}

async function renderShell() {
  hall.root.innerHTML = shellHtml();
  paintResults();
  bindRecommendedPanel(hall.root);
  await runCanvasRenderHooks(hall.root);
}

function jobCardHtml(job) {
  const saved = hall.saved.has(job.job_id);
  const selected = hall.selectedId === job.job_id;
  const tags = [
    job.job_function,
    job.seniority,
    ...(Array.isArray(job.tech_tags) ? job.tech_tags.slice(0, 3) : []),
  ]
    .filter(Boolean)
    .slice(0, 5);
  const match =
    job.match_score == null || job.match_score === ""
      ? null
      : Number(job.match_score);
  const hasMatch = match != null && Number.isFinite(match);
  const audience = inferAudience(job);
  return `<article class="jh-job${selected ? " is-selected" : ""}${
    saved ? " is-saved" : ""
  }" data-jh-card="${esc(job.job_id)}">
    <button type="button" class="jh-job__hit" data-jh-job="${esc(
      job.job_id,
    )}" aria-label="查看 ${esc(job.title || "未命名岗位")}" aria-current="${
      selected ? "true" : "false"
    }"></button>
    <div class="jh-job__content">
      ${logoHtml(job)}
      <div class="jh-job__main">
        <div class="jh-job__titleline">
          <h4 class="jh-job__title">${esc(job.title || "未命名岗位")}</h4>
          <span class="jh-job__salary">${esc(formatSalary(job))}</span>
        </div>
        <div class="jh-job__meta">
          <span>${esc(job.company || "未知公司")}</span>
          <span>${esc(job.location || "城市未填")}</span>
        </div>
        <div class="jh-job__tags">
          ${taglineHtml(tags)}
          ${
            audience === "campus"
              ? '<span class="jh-tag jh-tag--accent">校招</span>'
              : ""
          }
          ${workStateBadge(job)}
        </div>
      </div>
      <div class="jh-job__side">
        ${
          hasMatch
            ? `<span class="jh-matchscore" title="匹配分 · ${esc(
                jobMatchSource(job),
              )}"><b>${Math.round(match)}</b><i>匹配</i></span>`
            : ""
        }
        ${statusLine(job)}
        <span class="jh-job__time">${esc(relativeTime(job.updated_at))}</span>
        ${deadlineBadge(job)}
      </div>
    </div>
    <button type="button" class="jh-job__save${saved ? " is-saved" : ""}" data-jh-save="${esc(
      job.job_id,
    )}" aria-pressed="${saved}" aria-label="${
      saved ? "取消收藏" : "收藏岗位"
    }" title="${saved ? "取消收藏" : "收藏岗位"}">
      ${icon("bookmark", 16)}
    </button>
  </article>`;
}

function emptyLibraryHtml() {
  return `<div class="jh-empty">
    <span class="jh-empty__icon">${icon("compass", 24)}</span>
    <h3>职位库还是空的</h3>
    <p>职位大厅直接读取职位库，不另存一份数据。把招聘网站上的 JD 粘贴进来，或从岗位表批量导入后，这里就能按匹配度筛选。</p>
    <div class="jh-empty__actions">
      <button class="btn btn-primary" type="button" data-action="open-command-panel">粘贴 JD 添加岗位</button>
      <a class="btn btn-outline" href="#/jobs">去职位库批量导入</a>
    </div>
  </div>`;
}

function emptyFilterHtml() {
  return `<div class="jh-empty jh-empty--filter">
    <span class="jh-empty__icon">${icon("search", 24)}</span>
    <h3>当前条件下没有岗位</h3>
    <p>试试点变化城市、降低匹配分门槛，或清除筛选查看全部岗位。</p>
    <div class="jh-empty__actions">
      <button class="btn btn-primary" type="button" data-jh-clear>清除筛选</button>
    </div>
  </div>`;
}

function matchHtml(job) {
  const score =
    job.match_score == null || job.match_score === ""
      ? null
      : Number(job.match_score);
  const hasScore = score != null && Number.isFinite(score);
  const detail =
    job.match_score_detail && typeof job.match_score_detail === "object"
      ? job.match_score_detail
      : null;
  const dims = [
    ["hard_skills", "硬技能"],
    ["scenario", "场景"],
    ["expression", "表达"],
    ["experience", "经验"],
  ];
  if (!hasScore && !detail) {
    return `<div class="jh-hint">
      <span>${icon("crosshair", 16)} 尚未评分</span>
      <p>打开对齐工作台运行预分析后，这里会显示匹配分、理由与四维拆解。</p>
    </div>`;
  }
  return `<div class="jh-match">
    ${
      hasScore
        ? `<div class="jh-match__score"><span class="jh-matchscore jh-matchscore--detail"><b>${Math.round(
            score,
          )}</b><i>匹配</i></span>${
            job.match_stale
              ? '<em class="jh-match__stale">已过期</em>'
              : ""
          }</div>`
        : ""
    }
    ${
      job.match_stale
        ? `<button type="button" class="jh-rescore" data-jh-rescore="${esc(
            job.job_id,
          )}">重新评分</button>`
        : ""
    }
    <div class="jh-match__body">
      <p class="jh-match__reason">${esc(
        job.match_reason || (hasScore ? "暂无匹配理由" : "已记录岗位画像"),
      )}</p>
      ${
        detail
          ? `<div class="jh-meters">${dims
              .map(([key, label]) => {
                const raw = Number(detail[key]);
                const value = Number.isFinite(raw)
                  ? Math.max(0, Math.min(100, Math.round(raw)))
                  : null;
                return `<div class="jh-meter${
                  value != null && value < 50 ? " is-weak" : ""
                }"><span>${label}</span><div class="jh-meter__track"><i style="--fill:${
                  value == null ? 0 : value
                }%"></i></div><b>${value == null ? "—" : value}</b></div>`;
              })
              .join("")}</div>`
          : ""
      }
    </div>
  </div>`;
}

function requirementsHtml(job) {
  const profile =
    job.jd_profile && typeof job.jd_profile === "object"
      ? job.jd_profile
      : null;
  const must = Array.isArray(profile && profile.must_have_skills)
    ? profile.must_have_skills
    : [];
  const nice = Array.isArray(profile && profile.nice_to_have_skills)
    ? profile.nice_to_have_skills
    : [];
  const soft = Array.isArray(profile && profile.soft_skills)
    ? profile.soft_skills
    : [];
  const scenes = Array.isArray(profile && profile.business_scenarios)
    ? profile.business_scenarios
    : [];
  const education = Array.isArray(profile && profile.education_requirements)
    ? profile.education_requirements
    : [];
  const tags = Array.isArray(job.tech_tags) ? job.tech_tags : [];
  const groups = [
    ["硬性要求", must],
    ["加分项", nice],
    ["软技能", soft],
    ["业务场景", scenes],
  ].filter(([, values]) => values.length);
  if (!groups.length && !tags.length && !education.length) {
    return `<div class="jh-hint">
      <span>${icon("file-text", 16)} JD 尚未结构化</span>
      <p>打开对齐工作台运行预分析，岗位要求会拆成硬技能、加分项与业务场景。</p>
    </div>`;
  }
  return `<div class="jh-requirements">
    ${
      profile && profile.min_years_experience != null
        ? `<p class="jh-reqline">经验要求：${
            Number(profile.min_years_experience) > 0
              ? `${esc(profile.min_years_experience)} 年以上`
              : "不限经验"
          }</p>`
        : ""
    }
    ${
      education.length
        ? `<p class="jh-reqline">学历要求：${education
            .map((item) => esc(item))
            .join(" / ")}</p>`
        : ""
    }
    ${groups
      .map(
        ([label, values]) =>
          `<div class="jh-reqgroup"><span class="jh-reqgroup__label">${label}</span><div class="jh-tags">${values
            .map(tagHtml)
            .join("")}</div></div>`,
      )
      .join("")}
    ${
      tags.length
        ? `<div class="jh-reqgroup"><span class="jh-reqgroup__label">关键词</span><div class="jh-tags">${tags
            .slice(0, 10)
            .map(tagHtml)
            .join("")}</div></div>`
        : ""
    }
  </div>`;
}

function jdHtml(job) {
  const text = String(job.jd_text || "").trim();
  if (!text) {
    return `<p class="jh-hintline">尚未保存 JD 原文。可到职位库编辑岗位补全。</p>`;
  }
  return `<details class="jh-jd" ${job.jd_profile ? "" : "open"}>
    <summary><span>JD 原文</span><span class="jh-jd__count">${text.length} 字</span></summary>
    <div class="jh-jd__body">${renderMarkdown(text)}</div>
  </details>`;
}

function detailLoadingHtml(job) {
  const title = job && job.title ? job.title : "该岗位";
  return `<div class="jh-detail__empty" role="status" aria-live="polite">
    <span class="skeleton is-shimmer jh-loading__bar"></span>
    <span class="skeleton is-shimmer jh-loading__bar"></span>
    <h3>正在读取「${esc(title)}」的完整详情</h3>
    <p>列表只加载摘要；JD 原文、画像与改写建议会在打开岗位时按需读取。</p>
  </div>`;
}

function detailErrorHtml(job, message) {
  const title = job && job.title ? job.title : "该岗位";
  return `<div class="jh-detail__empty" role="alert">
    <span class="jh-empty__icon">${icon("triangle-alert", 24)}</span>
    <h3>「${esc(title)}」详情加载失败</h3>
    <p>${esc(message || "请检查本地服务后重试。")}</p>
    <div class="jh-empty__actions">
      <button class="btn btn-primary" type="button" data-jh-detail-retry>重试</button>
    </div>
  </div>`;
}

function detailHtml(job) {
  if (!job) {
    return `<div class="jh-detail__empty">
      <span class="jh-empty__icon">${icon("compass", 24)}</span>
      <h3>选择一个岗位</h3>
      <p>左侧列表里点开任一岗位，这里会显示匹配判断、岗位要求、投递状态与 JD 原文。</p>
    </div>`;
  }
  const saved = hall.saved.has(job.job_id);
  const canonical = canonicalJobStatus(job.status);
  const source = safeUrl(jobSourceUrl(job));
  const audience = inferAudience(job);
  return `<div class="jh-detail__inner">
    <header class="jh-detail__head">
      <div class="jh-detail__identity">
        ${logoHtml(job, "lg")}
        <div class="jh-detail__titlewrap">
          <h3 class="jh-detail__title">${esc(job.title || "未命名岗位")}</h3>
          <p class="jh-detail__company">${icon("building-2", 16)} ${esc(
            job.company || "未知公司",
          )}</p>
        </div>
      </div>
      <div class="jh-detail__tools">
        <button type="button" class="jh-savebtn${saved ? " is-saved" : ""}" data-jh-save="${esc(
          job.job_id,
        )}" aria-pressed="${saved}">
          ${icon("bookmark", 16)}<span data-jh-save-label>${
            saved ? "已收藏" : "收藏"
          }</span>
        </button>
        <button type="button" class="jh-iconbtn" data-jh-detail-close aria-label="关闭详情" title="关闭详情">
          ${icon("x", 20)}
        </button>
      </div>
    </header>

    <div class="jh-detail__meta">
      <span>${icon("map-pin", 16)} ${esc(job.location || "城市未填")}</span>
      <span>${icon("wallet", 16)} ${esc(formatSalary(job))}</span>
      <span>${icon("calendar", 16)} ${esc(
        relativeTime(job.updated_at) || "更新时间未知",
      )}</span>
      <span>${esc(job.job_function || "未分类")} · ${esc(
        job.seniority || "职级未知",
      )}</span>
      ${
        source
          ? `<a href="${esc(source)}" target="_blank" rel="noopener noreferrer">${icon(
              "external-link",
              16,
            )} 原站</a>`
          : ""
      }
    </div>

    <div class="jh-detail__badges">
      ${statusLine(job)}
      ${workStateBadge(job)}
      <span class="jh-tag jh-tag--accent">${esc(audienceLabel(audience))}</span>
      ${deadlineBadge(job)}
    </div>

    <div class="jh-detail__cta">
      ${alignmentCtaHtml(job, canonical)}
      <button type="button" class="btn btn-ghost" data-action="open-job-timeline" data-id="${esc(
        job.job_id,
      )}">完整时间线</button>
    </div>

    ${alignmentPanelHtml(job)}

    <section class="jh-detail__section">
      <h4>匹配判断</h4>
      ${matchHtml(job)}
    </section>

    <section class="jh-detail__section">
      <h4>岗位要求</h4>
      ${requirementsHtml(job)}
    </section>

    <section class="jh-detail__section">
      <h4>投递状态</h4>
      <label class="jh-statusselect">
        <span>当前状态</span>
        <select data-jh-status data-jh-status-id="${esc(
          job.job_id,
        )}" aria-label="更新 ${esc(job.title || "该岗位")} 的投递状态">
          ${jobStatusOptionsHtml(null, canonical)}
        </select>
      </label>
      <dl class="jh-facts">
        <div><dt>投递时间</dt><dd>${esc(displayWhen(job.applied_at, true))}</dd></div>
        <div><dt>下一步</dt><dd>${esc(job.next_step || "—")}</dd></div>
        <div><dt>跟进到期</dt><dd>${esc(displayWhen(job.next_step_due_at))}</dd></div>
        <div><dt>岗位截止</dt><dd>${esc(displayWhen(job.deadline, true))}</dd></div>
        <div><dt>面试阶段</dt><dd>${esc(job.interview_stage || "—")}</dd></div>
        ${
          job.notes
            ? `<div class="is-wide"><dt>备注</dt><dd>${esc(job.notes)}</dd></div>`
            : ""
        }
      </dl>
    </section>

    <section class="jh-detail__section">
      ${jdHtml(job)}
    </section>
  </div>`;
}

function alignmentCtaHtml(job, canonical) {
  const state = jobWorkState(job);
  const kind = alignmentOutcomeKind(job);
  if (state === "failed") {
    if (kind === "no_safe_rewrite") {
      return `<button type="button" class="btn btn-primary" data-action="open-optimizer" data-id="${esc(
        job.job_id,
      )}">${icon("columns", 16)} 查看证据</button>
        <button type="button" class="btn btn-outline" data-action="align-job" data-id="${esc(
          job.job_id,
        )}">${icon("rotate-ccw", 16)} 重新对齐</button>`;
    }
    return `<button type="button" class="btn btn-primary" data-action="align-job" data-id="${esc(
      job.job_id,
    )}">${icon("rotate-ccw", 16)} 重新对齐</button>
      <button type="button" class="btn btn-outline" data-action="open-optimizer" data-id="${esc(
        job.job_id,
      )}">${icon("columns", 16)} 打开工作台</button>`;
  }
  if (state === "no_gap") {
    return `<button type="button" class="btn btn-primary" data-action="open-optimizer" data-id="${esc(
      job.job_id,
    )}">${icon("columns", 16)} 查看说明</button>`;
  }
  if (state === "running") {
    return `<button type="button" class="btn btn-primary" data-action="open-optimizer" data-id="${esc(
      job.job_id,
    )}">${icon("columns", 16)} 查看对齐进度</button>`;
  }
  if (canonical === "draft") {
    return `<button type="button" class="btn btn-primary" data-action="open-optimizer" data-id="${esc(
      job.job_id,
    )}">${icon("columns", 16)} 开始对齐</button>
      <button type="button" class="btn btn-outline" data-jh-apply="${esc(
        job.job_id,
      )}">${icon("check", 16)} 标记已投递</button>`;
  }
  if (canonical === "offer" || canonical === "withdrawn") {
    return `<button type="button" class="btn btn-primary" data-action="open-optimizer" data-id="${esc(
      job.job_id,
    )}">${icon("columns", 16)} 查看定稿</button>`;
  }
  return `<button type="button" class="btn btn-primary" data-action="open-optimizer" data-id="${esc(
    job.job_id,
  )}">${icon("columns", 16)} 继续优化</button>
    <button type="button" class="btn btn-outline" data-action="open-job-followup" data-id="${esc(
      job.job_id,
    )}">${icon("calendar", 16)} 安排跟进</button>`;
}

function alignmentPanelHtml(job) {
  const state = jobWorkState(job);
  if (state !== "failed" && state !== "no_gap" && state !== "running") {
    return "";
  }
  const kind = alignmentOutcomeKind(job);
  const reason = String(job.alignment_error || "").trim();
  let title = "对齐未完成";
  let message =
    reason || "本轮没有产出可用改写建议，可重新运行对齐或到工作台查看诊断。";
  let tone = "danger";
  if (state === "no_gap") {
    title = "无需改写";
    message =
      reason || "该岗位与当前简历没有需要改写的缺口，无需重复运行对齐。";
    tone = "warning";
  } else if (state === "running") {
    title = "对齐进行中";
    message = reason || "任务正在后台运行，可打开工作台查看实时进度。";
    tone = "info";
  } else if (kind === "no_safe_rewrite") {
    title = "无安全改写";
    message =
      reason ||
      "简历原文没有足够依据支撑安全改写，请查看证据或补充事实后再重试。";
    tone = "warning";
  }
  return `<section class="jh-detail__section jh-alignpanel jh-alignpanel--${tone}">
    <div class="jh-alignpanel__head">
      <h4>${esc(title)}</h4>
      ${alignmentBadgeHtml(job)}
    </div>
    <p class="jh-alignpanel__reason">${esc(message)}</p>
  </section>`;
}

function metricsHtml() {
  const stats = computeHallStats(hall.jobs, hall.saved);
  const kpi = hall.dashboard && hall.dashboard.kpi ? hall.dashboard.kpi : null;
  const total = Number(kpi && kpi.jobs);
  const displayTotal = Number.isFinite(total) && total >= 0 ? total : stats.total;
  const truncated = displayTotal > stats.total;
  const cells = [
    {
      key: "total",
      label: "全部岗位",
      value: displayTotal,
      hint: truncated ? `已载入 ${stats.total} 个` : "职位库总量",
      tone: "neutral",
    },
    {
      key: "draft",
      label: "待投递",
      value: stats.draft,
      hint: "尚未投递",
      tone: "neutral",
    },
    {
      key: "applied",
      label: "已投递",
      value: stats.applied,
      hint: `累计投递 ${stats.appliedCumulative}`,
      tone: "accent",
    },
    {
      key: "interview",
      label: "面试中",
      value: stats.interview,
      hint: `面试转化 ${stats.interviewRate}%`,
      tone: "info",
    },
    {
      key: "offer",
      label: "Offer",
      value: stats.offer,
      hint: `Offer 率 ${stats.offerRate}%`,
      tone: "success",
    },
    {
      key: "saved",
      label: "已收藏",
      value: stats.saved,
      hint: "候选清单",
      tone: "neutral",
    },
  ];
  /* 过滤键用稳定 key，不用展示文案：改文案不该改变「哪些列常驻」。 */
  const core = new Set(["total", "draft", "applied", "saved"]);
  return cells
    .filter((cell) => core.has(cell.key) || Number(cell.value) > 0)
    .map(
      (cell) => `<div class="jh-metric jh-metric--${cell.tone}">
        <span class="jh-metric__label">${cell.label}</span>
        <strong class="jh-metric__value">${cell.value}</strong>
        <span class="jh-metric__hint">${cell.hint}</span>
      </div>`,
    )
    .join("");
}

function progressFootHtml() {
  const stats = computeHallStats(hall.jobs, hall.saved);
  const due = dueItems(hall.jobs).filter(
    (item) => item.at <= Date.now() + 7 * 86400000,
  );
  const next = due[0] || null;
  /* 零值转化率不进首屏：全部为 0 时只剩一串「0%」，对判断没有信息量。 */
  const rates = [
    ["投递率", stats.applyRate, "data-jobs-apply-rate"],
    ["面试率", stats.interviewRate, "data-jobs-interview-rate"],
    ["Offer 率", stats.offerRate, ""],
  ]
    .filter(([, value]) => Number(value) > 0)
    .map(
      ([label, value, attr]) =>
        `<span>${label} <b${attr ? ` ${attr}` : ""}>${value}%</b></span>`,
    )
    .join("");
  return `<div class="jh-conversion" data-jobs-conversion>
      ${rates || '<span class="jh-conversion__empty">暂无转化数据</span>'}
    </div>
    <button type="button" class="jh-duebtn" data-jh-due ${
      next ? "" : "disabled"
    }>
      ${icon("calendar", 16)}
      <span>本周待跟进 <b>${stats.dueSoon}</b>${
        stats.overdue ? ` · 逾期 <b>${stats.overdue}</b>` : ""
      }</span>
      ${
        next
          ? `<span class="jh-duebtn__hint">${esc(
              next.job.title || "未命名岗位",
            )} · ${esc(displayDate(next.at))}</span>`
          : '<span class="jh-duebtn__hint">暂无到期项</span>'
      }
    </button>`;
}

function paintMetrics() {
  const mount = hall.root && hall.root.querySelector("[data-jh-metrics]");
  const foot = hall.root && hall.root.querySelector("[data-jh-progress-foot]");
  if (mount) mount.innerHTML = metricsHtml();
  if (foot) foot.innerHTML = progressFootHtml();
}

function paintFilterCount() {
  const count = activeFilterCount(hall.filters);
  hall.root.querySelectorAll("[data-jh-filter-count]").forEach((node) => {
    node.textContent = String(count);
    node.hidden = count === 0;
  });
}

function paintAudience() {
  hall.root.querySelectorAll("[data-jh-audience]").forEach((button) => {
    const active = button.dataset.jhAudience === hall.filters.audience;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
}

function paintWorkFilter() {
  const counts = workFilterCounts();
  hall.root.querySelectorAll("[data-jh-work]").forEach((button) => {
    const key = button.dataset.jhWork || "all";
    const active = hall.filters.work_status === key;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
    // 分组条与看板 chip 的计数标记不同（<b>/<span>），统一用 data 属性定位。
    // 用裸 `span` 选择器会先命中分组条的 `.jh-lane__top`，把整块 top 行
    // （含小圆点）替换成纯数字。
    const count = button.querySelector("[data-jh-count]");
    if (count) count.textContent = String(counts[key] || 0);
  });
}

function boardColumnsHtml(visible) {
  const statuses = hall.vocabulary && hall.vocabulary.statuses;
  return JOB_STATUS_CANONICAL.map((canonical) => {
    const all = visible.filter(
      (job) => canonicalJobStatus(job.status) === canonical,
    );
    const label = esc(JOB_STATUS_LABELS[canonical] || canonical);
    if (!all.length) {
      return `<section class="board-column is-collapsed" data-status="${canonical}" data-board-drop aria-label="${label}">
        <div class="board-col-head">
          <h3><span class="dot dot-neutral" aria-hidden="true"></span><span class="board-col-collapsed__label">${label}</span></h3>
          <span class="board-col-count">0</span>
        </div>
      </section>`;
    }
    const shown = all.slice(0, hall.boardLimit);
    const more = all.length - shown.length;
    return `<section class="board-column" data-status="${canonical}" data-board-drop aria-label="${label}">
      <div class="board-col-head">
        <h3><span class="dot ${canonical === "offer" ? "dot-success" : "dot-neutral"}" aria-hidden="true"></span>${label}</h3>
        <span class="board-col-count">${all.length}</span>
      </div>
      <div class="board-col-body">
        ${shown
          .map(
            (job) =>
              `<div class="jh-boardcard" data-jh-board-card="${esc(
                job.job_id,
              )}">${boardCard(job, statuses)}</div>`,
          )
          .join("")}
        ${
          more > 0
            ? `<button type="button" class="btn btn-ghost btn-sm board-col__more" data-jh-board-more>还有 ${more} 个 · 显示更多</button>`
            : ""
        }
      </div>
    </section>`;
  }).join("");
}

function paintBoard(visible) {
  const mount = hall.root.querySelector("[data-jh-board]");
  if (!mount) return;
  mount.innerHTML = boardColumnsHtml(visible);
  bindBoardDrag(hall.root, () => renderShell());
}

function paintList(visible) {
  const mount = hall.root.querySelector("[data-jh-list]");
  const title = hall.root.querySelector("[data-jh-list-title]");
  const sub = hall.root.querySelector("[data-jh-list-sub]");
  const count = hall.root.querySelector("[data-jh-result-count]");
  if (count) {
    const laneActive =
      hall.laneKey != null && hall.laneKey === hall.filters.work_status;
    count.textContent = resultCountLabel(visible.length, laneActive);
  }
  if (title) {
    title.textContent = hall.filters.audience === "all"
      ? "岗位列表"
      : `${audienceLabel(hall.filters.audience)}岗位`;
  }
  if (sub) {
    sub.textContent = `${
      MERGED_SORTS.find((item) => item.value === hall.sort)?.label ||
      "匹配优先"
    }`;
  }
  if (!mount) return;
  if (!hall.jobs.length) {
    mount.innerHTML = emptyLibraryHtml();
    return;
  }
  if (!visible.length) {
    mount.innerHTML = emptyFilterHtml();
    return;
  }
  const shown = visible.slice(0, hall.listLimit);
  const more = visible.length - shown.length;
  mount.innerHTML =
    shown.map(jobCardHtml).join("") +
    (more > 0
      ? `<button type="button" class="btn btn-ghost jh-list__more" data-jh-list-more>还有 ${more} 个 · 显示更多</button>`
      : "");
}

function paintSelection() {
  hall.root.querySelectorAll("[data-jh-card]").forEach((card) => {
    const selected = card.dataset.jhCard === hall.selectedId;
    card.classList.toggle("is-selected", selected);
  });
  hall.root.querySelectorAll("[data-jh-job]").forEach((button) => {
    button.setAttribute(
      "aria-current",
      String(button.dataset.jhJob === hall.selectedId),
    );
  });
  hall.root.querySelectorAll("[data-jh-board-card]").forEach((card) => {
    card.classList.toggle(
      "is-selected",
      card.dataset.jhBoardCard === hall.selectedId,
    );
  });
}

function paintDetail() {
  const mount = hall.root.querySelector("[data-jh-detail]");
  const backdrop = hall.root.querySelector("[data-jh-detail-backdrop]");
  const view = hall.root.querySelector("[data-jh-shell]");
  if (!mount) return;
  const selected = summaryJob(hall.selectedId);
  const detail = detailJob(hall.selectedId);
  const wantsDetail =
    Boolean(hall.selectedId) && (hall.view === "list" || hall.detailOpen);
  if (detail) {
    mount.innerHTML = detailHtml(detail);
  } else if (!wantsDetail) {
    mount.innerHTML = detailHtml(null);
  } else if (hall.detailErrors.has(hall.selectedId)) {
    mount.innerHTML = detailErrorHtml(
      selected,
      hall.detailErrors.get(hall.selectedId),
    );
  } else {
    mount.innerHTML = detailLoadingHtml(selected);
  }
  if (view) view.classList.toggle("is-detail-open", hall.detailOpen);
  const isBoard = hall.view === "board";
  mount.hidden = isBoard && !hall.detailOpen;
  if (backdrop) backdrop.hidden = !isBoard || !hall.detailOpen;
}

/* AC 7d: a lane can exceed the 500-row server cap. Say so in the list header
 * instead of letting 500 look like the full bucket count. */
function resultCountLabel(visibleCount, laneActive) {
  let label = `共 ${visibleCount} 个岗位`;
  const laneCount =
    hall.dashboard && hall.dashboard.advance
      ? Number(hall.dashboard.advance[hall.filters.work_status])
      : NaN;
  if (
    laneActive &&
    visibleCount >= LIST_FETCH_LIMIT &&
    Number.isFinite(laneCount) &&
    laneCount > LIST_FETCH_LIMIT
  ) {
    label += "（仅显示前 500 条）";
  }
  return label;
}

function paintResults() {
  if (!hall.root) return;
  /* A lane comes from the server so rows beyond the first 500 still show
   * (AC 7b). Metrics keep reading hall.jobs below (AC 7c). */
  const laneActive =
    hall.laneKey != null && hall.laneKey === hall.filters.work_status;
  const source =
    laneActive && Array.isArray(hall.laneJobs) ? hall.laneJobs : hall.jobs;
  const visible = sortHallJobs(
    filterHallJobs(source, hall.filters, hall.saved),
    hall.sort,
  ).filter((job) => matchesWorkFilter(job, hall.filters.work_status));
  hall.visibleCount = visible.length;
  const selectedVisible = visible.some(
    (job) => job.job_id === hall.selectedId,
  );
  if (!selectedVisible) {
    hall.selectedId = hall.view === "list" && visible.length ? visible[0].job_id : null;
    if (!hall.selectedId) hall.detailOpen = false;
  }
  const count = hall.root.querySelector("[data-jh-result-count]");
  if (count) count.textContent = resultCountLabel(visible.length, laneActive);
  paintLaneNote();
  paintMetrics();
  paintFilterCount();
  paintAudience();
  paintWorkFilter();
  if (hall.view === "board") {
    paintBoard(visible);
  } else {
    paintList(visible);
  }
  paintSelection();
  paintDetail();
  if (
    hall.selectedId &&
    (hall.view === "list" || hall.detailOpen) &&
    !hall.details.has(hall.selectedId)
  ) {
    void ensureJobDetail(hall.selectedId);
  }
}

/* 分段条的计数来自 /api/dashboard，比列表晚一拍到达；首屏渲染时只能先用
 * 已加载页的本地计数。dashboard 回来后必须重画计数与说明条，否则页面上
 * 会一直停着错的数字（真实库里「待定稿」会显示成 0）。 */
function paintLaneNote() {
  const note = hall.root && hall.root.querySelector("[data-jh-lanenote]");
  if (note) note.innerHTML = advanceNoteHtml(hall.visibleCount || 0);
}

function schedulePaintResults() {
  if (hall.paintFrame != null) return;
  const run = () => {
    hall.paintFrame = null;
    paintResults();
  };
  if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
    hall.paintFrame = window.requestAnimationFrame(run);
  } else {
    hall.paintFrame = window.setTimeout(run, 0);
  }
}

async function ensureJobDetail(jobId, { force = false } = {}) {
  if (!jobId) return null;
  if (!force && hall.details.has(jobId)) return hall.details.get(jobId);
  if (hall.detailLoading.has(jobId)) return null;
  hall.detailErrors.delete(jobId);
  hall.detailLoading.add(jobId);
  if (hall.selectedId === jobId) paintDetail();
  try {
    const detail = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    hall.details.set(jobId, detail);
    return detail;
  } catch (error) {
    hall.detailErrors.set(
      jobId,
      (error && error.message) || "请检查本地服务后重试。",
    );
    return null;
  } finally {
    hall.detailLoading.delete(jobId);
    if (
      hall.selectedId === jobId &&
      (hall.view === "list" || hall.detailOpen)
    ) {
      paintDetail();
    }
  }
}

function selectJob(jobId) {
  if (!jobId) return;
  const job = summaryJob(jobId) || detailJob(jobId);
  if (!job) return;
  const wasOpen = hall.detailOpen;
  hall.selectedId = jobId;
  hall.detailOpen = true;
  if (!wasOpen) hall.detailPushed = true;
  writeJobsHash({ jobId, push: !wasOpen });
  paintSelection();
  paintDetail();
  if (!hall.details.has(jobId)) void ensureJobDetail(jobId);
}

function closeDetail() {
  if (hall.detailPushed) {
    hall.detailPushed = false;
    try {
      window.history.back();
      return;
    } catch {
      /* fall through to the in-place close */
    }
  }
  hall.detailOpen = false;
  writeJobsHash({ jobId: null });
  paintDetail();
}

function writeJobsHash({
  jobId = hall.detailOpen ? hall.selectedId : null,
  view = hall.view,
  push = false,
} = {}) {
  const params = new URLSearchParams();
  if (jobId) params.set("job", jobId);
  if (view === "board") params.set("view", "board");
  if (hall.filters.work_status && hall.filters.work_status !== "all") {
    params.set("advance", hall.filters.work_status);
  }
  const query = params.toString();
  const nextHash = `#/jobs${query ? `?${query}` : ""}`;
  const nextState = {
    [JOBS_DETAIL_STATE_KEY]: Boolean(jobId) && hall.detailPushed,
    jobId: jobId || null,
  };
  try {
    if (push) {
      window.history.pushState(nextState, "", nextHash);
    } else {
      window.history.replaceState(nextState, "", nextHash);
    }
  } catch {
    /* history unavailable: selection still works in memory */
  }
}

async function setView(view) {
  const next = view === "board" ? "board" : "list";
  if (next === hall.view) return;
  writeJobsViewMode(next);
  hall.listLimit = LIST_PAGE;
  hall.boardLimit = BOARD_PAGE;
  if (next === "list" && !hall.selectedId) {
    hall.detailOpen = false;
  }
  writeJobsHash({ view: next });
  await renderShell();
}

/* Browser Back/Forward on the jobs route must not rebuild the page and refetch
 * 500 jobs. Keep the loaded list and only reconcile the selected detail with
 * the hash. Filter deep links still fall through to the full router so their
 * server-side query is applied. */
export function syncJobHallFromHash() {
  if (!hall.root || !hall.root.querySelector("[data-jh-shell]")) return false;
  const value = String(window.location.hash || "").replace(/^#\/?/, "");
  const [pathPart, queryPart] = value.split("?");
  if ((pathPart || "").split("/")[0] !== "jobs") return false;
  const params = new URLSearchParams(queryPart || "");
  if (
    [
      "sort",
      "status",
      "search",
      "job_function",
      "seniority",
      "city",
      "audience",
    ].some((key) => params.has(key))
  ) {
    return false;
  }
  const requestedAdvance = params.get("advance");
  if (requestedAdvance && !ADVANCE_BUCKETS.includes(requestedAdvance)) {
    return false;
  }
  const nextLane = requestedAdvance || "all";
  const laneChanged = nextLane !== hall.filters.work_status;
  const requestedView = params.get("view");
  if (requestedView && requestedView !== "board" && requestedView !== "list") {
    return false;
  }
  const nextView = requestedView || hall.view;
  const requestedJob = params.get("job");
  const applySelection = () => {
    if (
      requestedJob &&
      (hall.jobs.some((job) => job.job_id === requestedJob) ||
        (Array.isArray(hall.laneJobs) &&
          hall.laneJobs.some((job) => job.job_id === requestedJob)) ||
        hall.details.has(requestedJob))
    ) {
      hall.selectedId = requestedJob;
      hall.detailOpen = true;
      hall.detailPushed = Boolean(
        window.history.state &&
          window.history.state[JOBS_DETAIL_STATE_KEY],
      );
      if (!hall.details.has(requestedJob)) {
        void ensureJobDetail(requestedJob);
      }
    } else {
      hall.detailOpen = false;
      hall.detailPushed = false;
    }
    paintSelection();
    paintDetail();
  };
  const restoreLane = (done) => {
    if (!laneChanged) {
      done();
      return;
    }
    hall.filters.work_status = nextLane;
    state.filters.work_status = nextLane;
    paintFilterCount();
    hall.listLimit = LIST_PAGE;
    void loadLane(nextLane).then(done);
  };
  if (nextView !== hall.view) {
    writeJobsViewMode(nextView);
    hall.listLimit = LIST_PAGE;
    hall.boardLimit = BOARD_PAGE;
    restoreLane(() => {
      void renderShell().then(applySelection);
    });
  } else {
    restoreLane(applySelection);
  }
  return true;
}

function toggleSaved(jobId) {
  if (!jobId) return;
  if (hall.saved.has(jobId)) hall.saved.delete(jobId);
  else hall.saved.add(jobId);
  writeShortlist(hall.saved);
  hall.root.querySelectorAll("[data-jh-save]").forEach((button) => {
    if (button.dataset.jhSave !== jobId) return;
    const saved = hall.saved.has(jobId);
    button.classList.toggle("is-saved", saved);
    button.setAttribute("aria-pressed", String(saved));
    button.setAttribute("aria-label", saved ? "取消收藏" : "收藏岗位");
    button.setAttribute("title", saved ? "取消收藏" : "收藏岗位");
    const label = button.querySelector("[data-jh-save-label]");
    if (label) label.textContent = saved ? "已收藏" : "收藏";
  });
  paintMetrics();
  if (hall.filters.savedOnly) paintResults();
}

function replaceJob(updated, fallback) {
  if (!updated && !fallback) return;
  const next = updated || fallback;
  const id = next.job_id || (fallback && fallback.job_id);
  if (!id) return;
  const index = hall.jobs.findIndex((item) => item.job_id === id);
  if (index >= 0) hall.jobs[index] = { ...hall.jobs[index], ...next };
  if (Array.isArray(hall.laneJobs)) {
    const laneIndex = hall.laneJobs.findIndex((item) => item.job_id === id);
    if (laneIndex >= 0) {
      hall.laneJobs[laneIndex] = { ...hall.laneJobs[laneIndex], ...next };
    }
  }
  if (hall.details.has(id)) {
    hall.details.set(id, { ...hall.details.get(id), ...next });
  } else if (
    updated &&
    ("jd_text" in updated || "diffs" in updated || "final_draft" in updated)
  ) {
    hall.details.set(id, { ...updated });
  }
  if (hall.selectedId === id && (hall.view === "list" || hall.detailOpen)) {
    paintDetail();
  }
}

function isTerminalStatus(status) {
  const canonical = canonicalJobStatus(status);
  return canonical === "offer" || canonical === "withdrawn";
}

async function patchStatus(job, status, extra = {}) {
  try {
    const updated = await api(`/api/jobs/${encodeURIComponent(job.job_id)}`, {
      method: "PATCH",
      body: JSON.stringify({ status, ...extra }),
    });
    replaceJob(updated, { ...job, status });
    toast("投递状态已更新", "success");
    paintResults();
  } catch (error) {
    toast(error.message || "投递状态更新失败", "error");
    throw error;
  }
}

async function patchBackwardStatus(job, status) {
  try {
    const result = await api("/api/kanban/bulk-status", {
      method: "POST",
      body: JSON.stringify({
        job_ids: [job.job_id],
        status,
        idempotency_key: `fe-jobhall-${job.job_id}-${status}-${Date.now()}`,
      }),
    });
    const row = Array.isArray(result && result.results)
      ? result.results.find((item) => item.job_id === job.job_id)
      : null;
    replaceJob(row && row.job, { ...job, status });
    toast("投递状态已更新", "success");
    paintResults();
  } catch (error) {
    toast(error.message || "投递状态更新失败", "error");
    throw error;
  }
}

function requestStatusChange(job, status, reset) {
  if (!job || !status) return;
  const current = canonicalJobStatus(job.status);
  if (current === status) {
    reset && reset();
    return;
  }
  if (isBackwardJobStatus(current, status)) {
    confirmBackwardStatus(
      job,
      status,
      () =>
        patchBackwardStatus(job, status).catch(() => {
          reset && reset();
        }),
      reset,
    );
    return;
  }
  if (isTerminalStatus(status)) {
    confirmTerminalStatus(
      job,
      status,
      (payload) =>
        patchStatus(job, status, payload).catch(() => {
          reset && reset();
        }),
      reset,
    );
    return;
  }
  patchStatus(job, status).catch(() => {
    reset && reset();
  });
}

function markApplied(jobId) {
  const job = summaryJob(jobId);
  if (!job) return;
  if (canonicalJobStatus(job.status) !== "draft") {
    toast("该岗位已经投递，可在详情里更新后续状态", "info");
    return;
  }
  patchStatus(job, "applied").catch(() => {});
}

async function rescoreJob(jobId, button) {
  const job = summaryJob(jobId);
  if (!job) return;
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "评分中…";
  try {
    const updated = await api(
      `/api/jobs/${encodeURIComponent(jobId)}/match`,
      { method: "POST" },
    );
    replaceJob(updated, job);
    toast(
      updated.match_reason ||
        `匹配分已更新：${updated.match_score == null ? "—" : Math.round(updated.match_score)}`,
      "success",
    );
    paintResults();
  } catch (error) {
    toast(error.message || "重新评分失败", "error");
    button.disabled = false;
    button.textContent = original;
  }
}

function resetFilters() {
  hall.filters = { ...EMPTY_FILTERS };
  hall.laneToken += 1;
  hall.laneJobs = null;
  hall.laneKey = null;
  hall.sort = "match_score_desc";
  state.filters = {
    ...state.filters,
    search: "",
    job_function: "",
    seniority: "",
    status: "",
    sort: "match_score_desc",
    audience: "all",
    city: "",
    salary: "",
    matchMin: 0,
    savedOnly: false,
    recentOnly: false,
    work_status: "all",
  };
  hall.boardLimit = BOARD_PAGE;
  hall.listLimit = LIST_PAGE;
  writeJobsHash({ jobId: null });
  void renderShell();
}

function syncStateFilters() {
  state.filters.search = hall.filters.query;
  state.filters.job_function = hall.filters.jobFunction;
  state.filters.seniority = hall.filters.seniority;
  state.filters.status = hall.filters.status;
  state.filters.sort = hall.sort;
  state.filters.audience = hall.filters.audience;
  state.filters.city = hall.filters.city;
  state.filters.salary = hall.filters.salary;
  state.filters.matchMin = hall.filters.matchMin;
  state.filters.savedOnly = hall.filters.savedOnly;
  state.filters.recentOnly = hall.filters.recentOnly;
  state.filters.work_status = hall.filters.work_status;
}

function applyStateFilters() {
  hall.filters.query = state.filters.search || "";
  hall.filters.audience = state.filters.audience || "all";
  hall.filters.city = state.filters.city || "";
  hall.filters.jobFunction = state.filters.job_function || "";
  hall.filters.seniority = state.filters.seniority || "";
  hall.filters.status = state.filters.status || "";
  hall.filters.salary = state.filters.salary || "";
  hall.filters.matchMin = Number(state.filters.matchMin) || 0;
  hall.filters.savedOnly = !!state.filters.savedOnly;
  hall.filters.recentOnly = !!state.filters.recentOnly;
  hall.filters.work_status = state.filters.work_status || "all";
  const sortAliases = {
    match_desc: "match_score_desc",
    match_asc: "match_score_asc",
    updated_desc: "updated_at_desc",
  };
  const requestedSort = state.filters.sort || hall.sort || "match_score_desc";
  const normalizedSort = sortAliases[requestedSort] || requestedSort;
  hall.sort = MERGED_SORTS.some((item) => item.value === normalizedSort)
    ? normalizedSort
    : "match_score_desc";
}

function bindEvents(root) {
  if (hall.bound) return;
  hall.bound = true;
  root.addEventListener("click", (event) => {
    const target = event.target;
    if (!target || typeof target.closest !== "function") return;
    if (target.closest("[data-jh-retry]")) {
      renderJobHall(hall.root, { jobId: hall.selectedId });
      return;
    }
    const viewButton = target.closest("[data-jh-view]");
    if (viewButton) {
      void setView(viewButton.dataset.jhView);
      return;
    }
    if (target.closest("[data-jh-toggle-filters]")) {
      const filters = root.querySelector("[data-jh-filters]");
      if (filters) filters.open = !filters.open;
      return;
    }
    const workButton = target.closest("[data-jh-work]");
    if (workButton) {
      const key = workButton.dataset.jhWork || "all";
      if (key === hall.filters.work_status && (key === "all" || hall.laneJobs)) {
        return;
      }
      hall.filters.work_status = key;
      syncStateFilters();
      paintFilterCount();
      hall.listLimit = LIST_PAGE;
      hall.boardLimit = BOARD_PAGE;
      writeJobsHash({ jobId: null });
      void loadLane(key);
      return;
    }
    const boardMore = target.closest("[data-jh-board-more]");
    if (boardMore) {
      hall.boardLimit += BOARD_PAGE;
      paintResults();
      return;
    }
    if (target.closest("[data-jh-list-more]")) {
      hall.listLimit += LIST_PAGE;
      paintResults();
      return;
    }
    const boardCardEl = target.closest("[data-jh-board-card]");
    if (
      boardCardEl &&
      !target.closest("button, a, select, input, label, summary")
    ) {
      selectJob(boardCardEl.dataset.jhBoardCard);
      return;
    }
    const save = target.closest("[data-jh-save]");
    if (save) {
      event.preventDefault();
      event.stopPropagation();
      toggleSaved(save.dataset.jhSave);
      return;
    }
    const jobButton = target.closest("[data-jh-job]");
    if (jobButton) {
      selectJob(jobButton.dataset.jhJob);
      return;
    }
    const audience = target.closest("[data-jh-audience]");
    if (audience) {
      hall.filters.audience = audience.dataset.jhAudience || "all";
      syncStateFilters();
      paintAudience();
      hall.listLimit = LIST_PAGE;
      paintResults();
      return;
    }
    const quick = target.closest("[data-jh-quick]");
    if (quick) {
      const kind = quick.dataset.jhQuick;
      if (kind === "match") {
        hall.filters.matchMin = hall.filters.matchMin === 80 ? 0 : 80;
      } else if (kind === "saved") {
        hall.filters.savedOnly = !hall.filters.savedOnly;
      } else if (kind === "recent") {
        hall.filters.recentOnly = !hall.filters.recentOnly;
      }
      quick.setAttribute(
        "aria-pressed",
        String(
          kind === "match"
            ? hall.filters.matchMin === 80
            : kind === "saved"
              ? hall.filters.savedOnly
              : hall.filters.recentOnly,
        ),
      );
      quick.classList.toggle(
        "is-active",
        quick.getAttribute("aria-pressed") === "true",
      );
      syncStateFilters();
      paintFilterCount();
      hall.listLimit = LIST_PAGE;
      paintResults();
      return;
    }
    if (target.closest("[data-jh-clear]")) {
      resetFilters();
      return;
    }
    if (target.closest("[data-jh-detail-close]")) {
      closeDetail();
      return;
    }
    const apply = target.closest("[data-jh-apply]");
    if (apply) {
      markApplied(apply.dataset.jhApply);
      return;
    }
    const rescore = target.closest("[data-jh-rescore]");
    if (rescore) {
      rescoreJob(rescore.dataset.jhRescore, rescore);
      return;
    }
    if (target.closest("[data-jh-detail-retry]")) {
      const jobId = hall.selectedId;
      if (jobId) {
        hall.details.delete(jobId);
        hall.detailErrors.delete(jobId);
        void ensureJobDetail(jobId, { force: true });
      }
      return;
    }
    if (target.closest("[data-jh-due]")) {
      const next = dueItems(hall.jobs).find(
        (item) => item.at <= Date.now() + 7 * 86400000,
      );
      if (next) selectJob(next.job.job_id);
      else toast("本周没有到期的跟进项", "info");
    }
  });

  root.addEventListener("input", (event) => {
    const input = event.target;
    if (!input || !input.matches || !input.matches("[data-jh-search]")) return;
    hall.filters.query = input.value;
    syncStateFilters();
    paintFilterCount();
    hall.listLimit = LIST_PAGE;
    schedulePaintResults();
  });

  root.addEventListener("change", (event) => {
    const target = event.target;
    if (!target || !target.matches) return;
    if (target.matches("[data-jh-filter]")) {
      const key = target.dataset.jhFilter;
      hall.filters[key] = key === "matchMin" ? Number(target.value) || 0 : target.value;
      syncStateFilters();
      paintFilterCount();
      hall.listLimit = LIST_PAGE;
      hall.boardLimit = BOARD_PAGE;
      paintResults();
      return;
    }
    if (target.matches("[data-jh-sort]")) {
      hall.sort = target.value || "match_score_desc";
      syncStateFilters();
      hall.listLimit = LIST_PAGE;
      hall.boardLimit = BOARD_PAGE;
      paintResults();
      return;
    }
    if (target.matches("[data-jh-status]")) {
      const jobId = target.dataset.jhStatusId;
      const job = summaryJob(jobId);
      if (!job) return;
      const previous = canonicalJobStatus(job.status);
      requestStatusChange(job, canonicalJobStatus(target.value), () => {
        target.value = previous;
      });
    }
  });

  root.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !hall.detailOpen) return;
    const target = event.target;
    if (target && target.closest && target.closest("input, select, textarea")) {
      return;
    }
    closeDetail();
  });

  root.addEventListener("submit", (event) => {
    if (event.target.closest && event.target.closest("[data-jh-filter-form]")) {
      event.preventDefault();
    }
  });
}

const SERVER_SORTS = new Set([
  "updated_at_desc",
  "match_score_desc",
  "match_score_asc",
]);

/* The first load carries the server-supported deep-link filters so a shared
 * #/jobs?status=applied&sort=... link yields the same page. `advance` is empty
 * on the first load so metric cards stay library-wide; a lane switch passes
 * the bucket explicitly. Client-only filters (audience/salary/match/saved/
 * recent) still run in memory over the fetched page. */
function jobsRequestUrl(advance = "") {
  return buildJobsRequestUrl({
    filters: hall.filters,
    sort: SERVER_SORTS.has(hall.sort) ? hall.sort : "updated_at_desc",
    advance,
    limit: LIST_FETCH_LIMIT,
  });
}

/* AC 7/7b: a lane is a server-side filter, not a scan of the loaded page.
 * `hall.jobs` stays untouched (AC 7c) and only feeds the metric cards. */
async function loadLane(key = hall.filters.work_status) {
  if (!key || key === "all") {
    hall.laneToken += 1;
    hall.laneJobs = null;
    hall.laneKey = null;
    paintResults();
    return;
  }
  if (hall.laneKey === key && Array.isArray(hall.laneJobs)) {
    paintResults();
    return;
  }
  const token = ++hall.laneToken;
  hall.laneKey = key;
  hall.laneJobs = null;
  paintResults();
  let rows;
  try {
    rows = await api(jobsRequestUrl(key));
  } catch (error) {
    if (token !== hall.laneToken || hall.filters.work_status !== key) return;
    toast(error.message || "筛选岗位失败，请重试。", "error");
    paintResults();
    return;
  }
  if (token !== hall.laneToken || hall.filters.work_status !== key) return;
  hall.laneJobs = Array.isArray(rows) ? rows : [];
  paintResults();
}

export async function renderJobHall(app, options = {}) {
  hall.root = app;
  hall.saved = readShortlist();
  hall.details = new Map();
  hall.detailLoading = new Set();
  hall.detailErrors = new Map();
  hall.error = "";
  hall.laneToken += 1;
  hall.laneJobs = null;
  hall.laneKey = null;
  const hashQuery = new URLSearchParams(
    String(window.location.hash || "").split("?")[1] || "",
  );
  const requestedAdvance = hashQuery.get("advance");
  if (requestedAdvance && ADVANCE_BUCKETS.includes(requestedAdvance)) {
    hall.filters.work_status = requestedAdvance;
    state.filters.work_status = requestedAdvance;
  }
  const requestedView = options.view || hashQuery.get("view");
  hall.view =
    requestedView === "board"
      ? "board"
      : requestedView === "list"
        ? "list"
        : readJobsViewMode();
  applyStateFilters();
  hall.root.innerHTML = loadingHtml();
  bindEvents(app);

  const token = ++hall.requestToken;
  /* Jobs first: the list must not wait for dashboard aggregates or the
   * vocabulary call. Those two only enrich metrics/status labels and are
   * reconciled after the first paint. */
  const jobsPromise = api(jobsRequestUrl());
  const dashboardPromise = api("/api/dashboard").then(
    (value) => ({ ok: true, value }),
    () => ({ ok: false, value: null }),
  );
  const vocabularyPromise = ensureVocabulary().then(
    (value) => ({ ok: true, value }),
    () => ({ ok: false, value: null }),
  );
  const jobsResult = await jobsPromise.then(
    (value) => ({ status: "fulfilled", value }),
    (reason) => ({ status: "rejected", reason }),
  );
  if (token !== hall.requestToken) return;
  if (jobsResult.status === "rejected") {
    hall.root.innerHTML = errorHtml(jobsResult.reason && jobsResult.reason.message);
    return;
  }
  hall.jobs = Array.isArray(jobsResult.value) ? jobsResult.value : [];
  state.jobs = hall.jobs;
  hall.vocabulary = null;
  hall.dashboard = null;
  hall.total = hall.jobs.length;

  const requested = options.jobId || hashQuery.get("job") || null;
  hall.selectedId = selectedOrDefault(
    requested && hall.jobs.some((job) => job.job_id === requested)
      ? requested
      : hall.selectedId,
  );
  hall.detailOpen = Boolean(requested && hall.selectedId === requested);
  hall.detailPushed = Boolean(
    hall.detailOpen &&
      window.history.state &&
      window.history.state[JOBS_DETAIL_STATE_KEY],
  );

  await renderShell();
  /* Deep link: the first fetch stays unfiltered for the metric cards, then
   * the lane is resolved server-side (AC 7). */
  if (hall.filters.work_status && hall.filters.work_status !== "all") {
    void loadLane(hall.filters.work_status);
  }
  if (
    hall.selectedId &&
    (hall.view === "list" || hall.detailOpen) &&
    !hall.details.has(hall.selectedId)
  ) {
    void ensureJobDetail(hall.selectedId);
  }

  void Promise.all([dashboardPromise, vocabularyPromise]).then(
    ([dashboardResult, vocabularyResult]) => {
      if (token !== hall.requestToken) return;
      hall.vocabulary =
        vocabularyResult.ok ? vocabularyResult.value : null;
      hall.dashboard =
        dashboardResult.ok ? dashboardResult.value : null;
      const kpiTotal = Number(
        hall.dashboard && hall.dashboard.kpi && hall.dashboard.kpi.jobs,
      );
      hall.total = Number.isFinite(kpiTotal) ? kpiTotal : hall.jobs.length;
      paintMetrics();
      /* 服务端计数到位：分段条的数字与说明条都要按全库口径重画。 */
      paintWorkFilter();
      paintLaneNote();
      if (hall.view === "board") paintResults();
    },
  );
}
