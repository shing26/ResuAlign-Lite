/* ResuAlign v2.0 — Job Kanban (蓝图文件 5)
 * 岗位库重构：URL 自动抓取 Bar + Funnel Metrics + 5 列 surface3 沉降式
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
  ensureVocabulary,
  esc,
  state,
  toast,
  vocabularyList,
} from "./events.js";
import {
  boardCard,
  computeJobStats,
  options,
  renderJobStatsHtml,
} from "./format.js";

let canvasRenderHooks = [];
let draggingJobId = null;

export function setCanvasRenderHook(fn) {
  if (typeof fn === "function") canvasRenderHooks.push(fn);
}

function moveBoardJob(jobId, status) {
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
  for (const key of ["job_function", "seniority", "status", "search"]) {
    if (!state.filters[key]) query.delete(key);
  }
  state.jobs = await api(`/api/jobs?${query}`);
  const vocabulary = await ensureVocabulary();
  const columns = JOB_STATUS_CANONICAL.map((canonical) => {
    const items = state.jobs.filter(
      (job) => canonicalJobStatus(job.status) === canonical,
    );
    return `
      <section class="board-column" data-status="${canonical}" data-board-drop aria-label="${esc(JOB_STATUS_LABELS[canonical])}">
        <div class="board-column__head">
          <span class="board-column__dot board-dot--${canonical}" aria-hidden="true"></span>
          <h3>${esc(JOB_STATUS_LABELS[canonical])}</h3>
          <span class="board-column__count">${items.length}</span>
        </div>
        <div class="board-column__body">
          ${items.map(boardCard).join("") || '<div class="board-column__empty">暂无岗位</div>'}
        </div>
      </section>`;
  }).join("");
  const statuses = vocabulary.statuses || [];
  app.innerHTML = `
    <div class="page-header page-header--jobs">
      <div>
        <h2>岗位库</h2>
        <div class="sub">共 ${state.jobs.length} 条 · 拖拽或选择状态推进投递进度</div>
      </div>
      <div class="row">
        <button class="btn btn-primary" data-action="open-command-panel">粘贴 JD / 链接</button>
      </div>
    </div>
    ${renderJobStatsHtml(computeJobStats(state.jobs))}
    <details class="board-filter panel panel-card" data-board-filter>
      <summary class="board-filter__summary" data-filter-summary>
        <span class="board-filter__label">🔍 筛选岗位</span>
        <span class="board-filter__hint small muted">关键词 / 职能 / 级别 / 状态</span>
        <span class="board-filter__toggle" aria-hidden="true">展开</span>
      </summary>
      <form class="board-filter__form" data-form="job-filter">
        <label class="field"><span class="small">关键词</span>
          <input type="text" name="search" value="${esc(state.filters.search || "")}" placeholder="搜索标题 / 公司 / 技能..."></label>
        <label class="field"><span class="small">职能</span>
          <select name="job_function">${options(vocabulary.job_functions || [], state.filters.job_function || "")}</select></label>
        <label class="field"><span class="small">级别</span>
          <select name="seniority">${options(vocabulary.seniorities || [], state.filters.seniority || "")}</select></label>
        <label class="field"><span class="small">状态</span>
          <select name="status">${options(statuses, state.filters.status || "")}</select></label>
        <div class="board-filter__actions">
          <button class="btn btn-primary btn-sm" type="submit">应用筛选</button>
          <button class="btn btn-ghost btn-sm" type="button" data-action="clear-filters">清除</button>
        </div>
      </form>
    </details>
    <div class="board-toolbar panel panel-card">
      <span class="small muted">拖拽卡片到目标列；触屏 / 键盘：使用卡片内下拉菜单移动状态。</span>
    </div>
    <div id="job-board" class="pipeline-board" data-pipeline-board>${columns}</div>`;
  bindBoardDrag(app);
  canvasRenderHooks.forEach((hook) => {
    try {
      hook(app);
    } catch {
      /* a failing hook must not break the board render */
    }
  });
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
      try {
        const result = await moveBoardJob(jobId, status);
        if (result.updated) toast("岗位状态已更新", "success");
        renderKanban($("#app-router-view"));
      } catch (error) {
        toast(error.message, "error");
      }
    });
  });
}
