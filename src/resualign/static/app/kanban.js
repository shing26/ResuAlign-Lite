/* ResuAlign v2.0 — Job Kanban (蓝图文件 5)
 * 岗位库重构：Funnel Metrics + 5 列 surface3 沉降式
 * Kanban（未投递 ➔ 已投递 ➔ 面试中 ➔ 已拿 Offer ➔ 放弃），卡片悬浮带
 * Apple 微动效。搜索/职能/级别/状态筛选以苹果风折叠 Toolbar 呈现
 * （收合式，展开不挤占看板空间）；事件绑定复用 main.js 的
 * data-form="job-filter" → handleForm → state.filters 委托，保持架构。
 * 原实现位于 split-canvas.js（renderCopilotBoard），v2.0 拆分为独立模块。
 */
import {
  $,
  $$,
  JOB_STATUS_CANONICAL,
  JOB_STATUS_LABELS,
  api,
  canonicalJobStatus,
  confirmBackwardStatus,
  confirmTerminalStatus,
  ensureVocabulary,
  esc,
  isBackwardJobStatus,
  state,
  toast,
  vocabularyList,
} from "./events.js";
import {
  boardCard,
  computeJobStats,
  jobListRow,
  jobsEmptyGuideHtml,
  options,
} from "./format.js";
import { icon } from "./icons.js";

let canvasRenderHooks = [];
let draggingJobId = null;

/* 工作状态维度（2026-10-22，审计 J3）：看板列按「投递阶段」切，但用户此刻
 * 真正的工作量在「对齐状态」——318 条里 209 条失败 / 22 条已对齐 / 87 条
 * 待分析，之前列表上一格都看不到。这里在工具条加一排前端筛选，不新增请求：
 * 数据本来就一次拉全量（limit=500），过滤在内存里做。 */
const WORK_FILTERS = [
  { key: "all", label: "全部" },
  { key: "pending", label: "待分析" },
  { key: "aligned", label: "已对齐" },
  { key: "failed", label: "对齐失败" },
  { key: "final", label: "已定稿" },
];

/* 岗位的「工作状态」归并：与 format.js::boardAlignmentChip 的展示语义一一
 * 对应（失败 / 已对齐 / 待分析 / 已定稿），用于工具条筛选。 */
function jobWorkState(job) {
  const status = String(job.alignment_status || "");
  if (status === "failed") return "failed";
  if (status === "succeeded") {
    const usable =
      typeof job.usable_diffs === "number"
        ? job.usable_diffs
        : (job.diffs || []).length;
    return usable >= 1 ? "aligned" : "no_gap";
  }
  if (status === "queued" || status === "running") return "running";
  return "pending";
}

function isFinalDraft(job) {
  return Number(job.final_draft_version) > 0 || job.has_final_draft === true;
}

function matchesWorkFilter(job, key) {
  if (key === "all" || !key) return true;
  if (key === "final") return isFinalDraft(job);
  return jobWorkState(job) === key;
}

function activeFilterCount(filters) {
  const base = ["search", "job_function", "seniority", "status"].filter(
    (key) => Boolean(filters[key]),
  ).length;
  const work = filters.work_status && filters.work_status !== "all" ? 1 : 0;
  return base + work;
}

/* B2（2026-10-22，审计 J2/J7）：318 条数据在 5 等分看板里要滚 121 屏，且
 * 空列白占 76% 宽度。改为：
 * - 列表视图（默认）：单列行卡，一屏 8–10 条，可扫；看板保留给投递阶段管理；
 * - 看板空列折叠成 56px 竖条，非空列不再被 4 个空列挤到 223px；
 * - 两种视图都分页渲染（列表 50 条 / 每列 20 张），「显示更多」再追加。
 * 视图选择存 localStorage，刷新后保持。 */
const JOBS_VIEW_KEY = "resualign.jobs.view";
const LIST_PAGE = 50;
const BOARD_PAGE = 20;
let listLimit = LIST_PAGE;
let boardLimit = BOARD_PAGE;
let jobsViewMode = readJobsViewMode();

function readJobsViewMode() {
  try {
    return localStorage.getItem(JOBS_VIEW_KEY) === "board" ? "board" : "list";
  } catch {
    return "list";
  }
}

function writeJobsViewMode(mode) {
  jobsViewMode = mode === "board" ? "board" : "list";
  try {
    localStorage.setItem(JOBS_VIEW_KEY, jobsViewMode);
  } catch {
    /* storage unavailable: keep in-memory choice for this session */
  }
}

function resetPaging() {
  listLimit = LIST_PAGE;
  boardLimit = BOARD_PAGE;
}

export function setCanvasRenderHook(fn) {
  if (typeof fn === "function") canvasRenderHooks.push(fn);
}

function isTerminalJobStatus(status) {
  const canonical = canonicalJobStatus(status);
  return canonical === "offer" || canonical === "withdrawn";
}

function moveBoardJob(jobId, status, extra = {}) {
  const dateField = extra.offer_at ? "offer_at" : extra.rejected_at ? "rejected_at" : null;
  if (dateField) {
    return api(`/api/jobs/${encodeURIComponent(jobId)}`, {
      method: "PATCH",
      body: JSON.stringify({
        status,
        [dateField]: extra[dateField],
        ...(extra.notes ? { notes: extra.notes } : {}),
      }),
    }).then((job) => ({ updated: 1, results: [{ updated: true, job }] }));
  }
  return api("/api/kanban/bulk-status", {
    method: "POST",
    body: JSON.stringify({
      job_ids: [jobId],
      status,
      idempotency_key: `fe-${jobId}-${status}`,
    }),
  });
}

export async function renderKanban(app) {
  const query = new URLSearchParams({
    ...state.filters,
    limit: "500",
    offset: "0",
  });
  for (const key of ["job_function", "seniority", "status", "search", "sort"]) {
    if (!state.filters[key]) query.delete(key);
  }
  /* work_status 是纯前端视图筛选，不进 API 契约（后端只认投递状态）。 */
  query.delete("work_status");
  state.jobs = await api(`/api/jobs?${query}`);
  const vocabulary = await ensureVocabulary();
  const workFilter = state.filters.work_status || "all";
  const visibleJobs = (state.jobs || []).filter((job) =>
    matchesWorkFilter(job, workFilter),
  );
  const workCounts = { all: (state.jobs || []).length, pending: 0, aligned: 0, failed: 0, final: 0 };
  for (const job of state.jobs || []) {
    const workState = jobWorkState(job);
    if (workState === "pending") workCounts.pending += 1;
    if (workState === "aligned") workCounts.aligned += 1;
    if (workState === "failed") workCounts.failed += 1;
    if (isFinalDraft(job)) workCounts.final += 1;
  }
  const workFilterHtml = `
          <div class="jobs-workfilter" role="group" aria-label="按工作状态筛选">
            ${WORK_FILTERS.map(
              ({ key, label }) => `
              <button type="button" class="jobs-workfilter__btn" data-work-status="${key}" aria-pressed="${workFilter === key}">${label}<span class="jobs-workfilter__count">${esc(workCounts[key] || 0)}</span></button>`,
            ).join("")}
          </div>`;
  const viewToggleHtml = `
          <div class="jobs-viewtoggle" role="group" aria-label="岗位视图">
            ${[
              ["list", "列表"],
              ["board", "看板"],
            ]
              .map(
                ([key, label]) =>
                  `<button type="button" class="jobs-viewtoggle__btn" data-jobs-view="${key}" aria-pressed="${jobsViewMode === key}">${label}</button>`,
              )
              .join("")}
          </div>`;
  const columns = JOB_STATUS_CANONICAL.map((canonical) => {
    const all = visibleJobs.filter(
      (job) => canonicalJobStatus(job.status) === canonical,
    );
    const label = esc(JOB_STATUS_LABELS[canonical]);
    if (!all.length) {
      /* 空列折叠成竖条：把 892px 还给有数据的列（审计 J2）。 */
      return `
      <section class="board-column is-collapsed" data-status="${canonical}" data-board-drop aria-label="${label}">
        <div class="board-col-head">
          <h3><span class="dot dot-neutral" aria-hidden="true"></span><span class="board-col-collapsed__label">${label}</span></h3>
          <span class="board-col-count">0</span>
        </div>
      </section>`;
    }
    const shown = all.slice(0, boardLimit);
    const more = all.length - shown.length;
    return `
      <section class="board-column" data-status="${canonical}" data-board-drop aria-label="${label}">
        <div class="board-col-head">
          <h3>
            <span class="dot dot-${canonical === "offer" ? "success" : "neutral"}" aria-hidden="true"></span>
            ${label}
          </h3>
          <span class="board-col-count">${all.length}</span>
        </div>
        <div class="board-col-body">
          ${shown.map((job) => boardCard(job, vocabulary.statuses)).join("")}
          ${more > 0 ? `<button type="button" class="btn btn-ghost btn-sm board-col__more" data-jobs-show-more>还有 ${more} 个 · 显示更多</button>` : ""}
        </div>
      </section>`;
  }).join("");
  const listRows = visibleJobs.slice(0, listLimit);
  const listMore = visibleJobs.length - listRows.length;
  const listHtml = `
      <div class="jobs-list" data-jobs-list>
        <div class="jobs-list__head" aria-hidden="true">
          <span></span><span>岗位</span><span>匹配</span><span>工作状态</span><span>投递状态</span><span>更新时间</span><span>操作</span>
        </div>
        ${listRows.map((job) => jobListRow(job, vocabulary.statuses)).join("")}
        ${
          listMore > 0
            ? `<button type="button" class="btn btn-outline btn-sm jobs-list__more" data-jobs-show-more>显示更多（还有 ${listMore} 条）</button>`
            : ""
        }
      </div>`;
  const statuses = vocabulary.statuses || [];
  const stats = computeJobStats(state.jobs);
  const funnel = stats.funnel || {};
  /* 2026-10-22（审计 J11）：0.3% 被四舍五入成「0%」，看起来像 bug；小于 1%
   * 时明确写「<1%」，其余保持整数。 */
  const percent = (value) => {
    if (value == null) return "—";
    const num = Number(value);
    if (!Number.isFinite(num)) return "—";
    if (num > 0 && num < 1) return "<1%";
    return `${Math.round(num)}%`;
  };
  const filterCount = activeFilterCount(state.filters);
  const hasVisibleJobs = visibleJobs.length > 0;
  const emptyGuide =
    state.jobs.length === 0 && !filterCount ? jobsEmptyGuideHtml() : "";
  /* 2026-10-22（审计 J6）：筛选零结果 ≠ 空库。之前复用空库引导会告诉用户
   * 「还没有岗位」，而库里其实有 318 条；这里给列表级空态和唯一恢复动作。 */
  const filteredEmptyHtml =
    !hasVisibleJobs && filterCount
      ? `<div class="jobs-empty-filter" data-jobs-filter-empty>
           <strong>没有匹配的岗位</strong>
           <p>当前筛选条件下 0 条；换个关键词，或清除筛选查看全部岗位。</p>
           <button type="button" class="btn btn-primary btn-sm" data-action="clear-filters">清除筛选</button>
         </div>`
      : "";
  app.innerHTML = `
    <div class="view view-fit jobs-view">
      <div class="jobs-command jobs-topbar" data-jobs-topbar>
        <div class="conversion" data-jobs-conversion aria-label="投递面试转化统计">
          <span>投递转化 <b data-jobs-apply-rate>${esc(percent(funnel.applyRate))}</b>（${esc(funnel.applied || 0)}/${esc(stats.total || 0)}）</span>
          <span>面试转化 <b data-jobs-interview-rate>${esc(percent(funnel.interviewRate))}</b>（${esc(funnel.interview || 0)}/${esc(funnel.applied || 0)}）</span>
        </div>
      </div>
      <div class="jobs-toolbar">
        <div class="toolbar-left">
          ${viewToggleHtml}
          <details class="filter-details board-filter" data-board-filter>
            <summary class="btn btn-secondary btn-sm board-filter__summary">筛选${filterCount ? `<span class="board-filter__count">${esc(filterCount)}</span>` : ""}</summary>
            <form class="filter-pop board-filter__form" data-form="job-filter">
              <label><span>关键词 / 公司</span><input class="field-input" type="text" name="search" value="${esc(state.filters.search || "")}" placeholder="Java / 公司名"></label>
              <label><span>职能</span><select class="field-input" name="job_function">${options(vocabulary.job_functions || [], state.filters.job_function || "")}</select></label>
              <label><span>职级</span><select class="field-input" name="seniority">${options(vocabulary.seniorities || [], state.filters.seniority || "")}</select></label>
              <label><span>状态</span><select class="field-input" name="status">${options(statuses, state.filters.status || "")}</select></label>
              <div class="board-filter__actions">
                <button type="button" class="btn btn-ghost btn-sm" data-action="clear-filters">清除</button>
                <button class="btn btn-primary btn-sm" type="submit">应用</button>
              </div>
            </form>
          </details>
          ${workFilterHtml}
          <label class="board-sort">
            <span>排序</span>
            <select data-job-sort aria-label="排序岗位">
              <option value="updated_at_desc" ${state.filters.sort === "updated_at_desc" ? "selected" : ""}>最近更新</option>
              <option value="match_score_desc" ${state.filters.sort === "match_score_desc" ? "selected" : ""}>匹配分从高到低</option>
              <option value="match_score_asc" ${state.filters.sort === "match_score_asc" ? "selected" : ""}>匹配分从低到高</option>
            </select>
          </label>
          <div class="jobs-tools" data-jobs-tools>
            <button type="button" class="btn btn-outline btn-sm" data-action="preanalyze-pending">一键预分析</button>
            <button type="button" class="btn btn-outline btn-sm" data-action="batch-align-pending" data-batch-align>批量对齐</button>
            <button type="button" class="btn btn-primary btn-sm" data-action="show-add-job">添加岗位</button>
            <details class="toolbar-more" data-jobs-data-menu>
              <summary class="btn btn-secondary btn-sm toolbar-more__trigger">数据 ${icon("chevron-down", 16)}</summary>
              <div class="toolbar-more__menu">
                <button type="button" class="btn btn-secondary btn-sm" data-action="show-import">批量导入</button>
                <button type="button" class="btn btn-secondary btn-sm" data-action="export-jobs-csv">导出 CSV</button>
                <button type="button" class="btn btn-outline btn-sm" data-action="export-jobs-backup">整库备份</button>
              </div>
            </details>
          </div>
        </div>
      </div>
    <div class="jobs-forms-mount" data-jobs-forms-mount></div>
    <div class="board-toolbar" data-jobs-batch-mount></div>
    ${emptyGuide}
    ${filteredEmptyHtml}
    ${
      hasVisibleJobs
        ? jobsViewMode === "board"
          ? `<div id="job-board" class="board pipeline-board" data-pipeline-board>${columns}</div>`
          : listHtml
        : ""
    }
    </div>`;
  const sortSelect = app.querySelector("[data-job-sort]");
  if (sortSelect) {
    sortSelect.addEventListener("change", () => {
      state.filters.sort = sortSelect.value || "updated_at_desc";
      const query = new URLSearchParams({ sort: state.filters.sort });
      window.history.pushState(
        null,
        "",
        state.filters.sort === "updated_at_desc"
          ? "#/jobs"
          : `#/jobs?sort=${encodeURIComponent(state.filters.sort)}`,
      );
      renderKanban(app);
    });
  }
  bindBoardDrag(app);
  /* 工作状态筛选：纯前端视图筛选，切换后重渲染（不新增接口）。 */
  app.querySelectorAll("[data-work-status]").forEach((button) => {
    button.addEventListener("click", () => {
      state.filters.work_status = button.dataset.workStatus || "all";
      resetPaging();
      renderKanban(app);
    });
  });
  /* 视图切换 / 显示更多：都只重渲染当前视图，不发写请求。 */
  app.querySelectorAll("[data-jobs-view]").forEach((button) => {
    button.addEventListener("click", () => {
      writeJobsViewMode(button.dataset.jobsView);
      resetPaging();
      renderKanban(app);
    });
  });
  app.querySelectorAll("[data-jobs-show-more]").forEach((button) => {
    button.addEventListener("click", () => {
      if (jobsViewMode === "board") boardLimit += BOARD_PAGE;
      else listLimit += LIST_PAGE;
      renderKanban(app);
    });
  });
  /* Hooks are async (the job-table form mount awaits /api/master-resumes
   * before appending), so firing them without awaiting made renderKanban
   * resolve *before* the import/create forms existed in the DOM — and a
   * synchronous try/catch could never see their rejections. Await them so a
   * caller that does `await render()` can rely on the finished view, and log
   * failures instead of dropping them on the floor. */
  await Promise.all(
    canvasRenderHooks.map((hook) =>
      Promise.resolve()
        .then(() => hook(app))
        .catch((error) => {
          /* a failing hook must not break the board render */
          console.error("canvas render hook failed:", error);
        }),
    ),
  );
}

function prefersCoarsePointer() {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(pointer: coarse)").matches
  );
}

function bindBoardDrag(root) {
  const touchOnly = prefersCoarsePointer();
  $$("[data-board-drag]", root).forEach((card) => {
    if (touchOnly) {
      /* HTML5 drag & drop is mouse-only; on touch devices the card's
         status <select> is the supported interaction (#5). Disabling
         draggable also stops long-press drag ghosts on mobile Safari. */
      card.draggable = false;
      return;
    }
    card.addEventListener("dragstart", (event) => {
      draggingJobId = card.dataset.jobId;
      card.classList.add("is-dragging");
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", card.dataset.jobId);
      }
    });
    card.addEventListener("dragend", () => {
      draggingJobId = null;
      card.classList.remove("is-dragging");
      $$(".board-column.is-drag-over", root).forEach((column) =>
        column.classList.remove("is-drag-over"),
      );
    });
  });
  if (touchOnly) return;
  $$("[data-board-drop]", root).forEach((column) => {
    column.addEventListener("dragover", (event) => {
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
      column.classList.add("is-drag-over");
    });
    column.addEventListener("dragleave", () => column.classList.remove("is-drag-over"));
    column.addEventListener("drop", async (event) => {
      event.preventDefault();
      column.classList.remove("is-drag-over");
      const jobId = draggingJobId || (event.dataTransfer && event.dataTransfer.getData("text/plain"));
      if (!jobId) return;
      const status = column.dataset.status;
      const applyMove = async (extra = {}) => {
        try {
          const result = await moveBoardJob(jobId, status, extra);
          if (result.updated) toast("岗位状态已更新", "success");
          renderKanban($("#app-router-view"));
        } catch (error) {
          toast(error.message, "error");
        }
      };
      const job = (state.jobs || []).find(
        (item) => item.job_id === jobId,
      );
      if (job && isBackwardJobStatus(job.status, status)) {
        confirmBackwardStatus(job, status, applyMove);
      } else if (job && isTerminalJobStatus(status)) {
        confirmTerminalStatus(job, status, applyMove);
      } else {
        applyMove();
      }
    });
  });
}
