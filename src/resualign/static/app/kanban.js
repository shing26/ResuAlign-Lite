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
  confirmBackwardStatus,
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
  options,
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
        <div class="board-col-head">
          <h3>
            <span class="dot dot-${canonical === "offer" ? "success" : "neutral"}" aria-hidden="true"></span>
            ${esc(JOB_STATUS_LABELS[canonical])}
          </h3>
          <span class="board-col-count">${items.length}</span>
        </div>
        <div class="board-col-body">
          ${items.map(boardCard).join("") || '<div class="board-column__empty">暂无岗位</div>'}
        </div>
      </section>`;
  }).join("");
  const statuses = vocabulary.statuses || [];
  const stats = computeJobStats(state.jobs);
  const funnel = stats.funnel || {};
  const percent = (value) => (value == null ? "—" : `${value}%`);
  app.innerHTML = `
    <div class="view view-fit jobs-view">
      <div class="jobs-command jobs-topbar" data-jobs-topbar>
        <div class="fetch-url" data-fetch-url-bar>
          <input type="url" data-fetch-url placeholder="粘贴岗位 JD 链接自动抓取..." aria-label="岗位链接" autocomplete="off">
          <button type="button" class="btn btn-light" data-action="fetch-job-url">自动抓取</button>
        </div>
        <span class="blocker-btn" data-blocker-badge></span>
        <div class="conversion" data-jobs-conversion aria-label="投递面试转化统计">
          <span>投递转化 <b data-jobs-apply-rate>${esc(percent(funnel.applyRate))}</b>（${esc(funnel.applied || 0)}/${esc(funnel.total || 0)}）</span>
          <span>面试转化 <b data-jobs-interview-rate>${esc(percent(funnel.interviewRate))}</b>（${esc(funnel.interview || 0)}/${esc(funnel.applied || 0)}）</span>
        </div>
      </div>
      <div class="jobs-toolbar">
        <div class="toolbar-left">
          <details class="filter-details board-filter" data-board-filter>
            <summary class="btn btn-secondary btn-sm board-filter__summary">筛选</summary>
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
          <div class="jobs-tools" data-jobs-tools>
            <button type="button" class="btn btn-primary btn-sm" data-action="show-add-job">添加岗位</button>
            <details class="toolbar-more" data-jobs-data-menu>
              <summary class="btn btn-secondary btn-sm toolbar-more__trigger">数据 ▾</summary>
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
    <div id="job-board" class="board pipeline-board" data-pipeline-board>${columns}</div>
    </div>`;
  const fetchInput = app.querySelector("[data-fetch-url]");
  if (fetchInput) {
    fetchInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        const button = app.querySelector('[data-action="fetch-job-url"]');
        if (button) button.click();
      }
    });
  }
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
      const applyMove = async () => {
        try {
          const result = await moveBoardJob(jobId, status);
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
      } else {
        applyMove();
      }
    });
  });
}
