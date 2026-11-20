/* Shared jobs-view interactions.
 *
 * The merged jobs page owns the shell (job-hall.js); this module keeps only
 * the interactions both list and board reuse: render hooks contributed by
 * main.js, the recommendation panel, and board drag-and-drop. The old
 * standalone renderKanban page was removed when #/jobs and #/job-hall were
 * merged into one route.
 */
import {
  $$,
  api,
  confirmBackwardStatus,
  confirmTerminalStatus,
  isBackwardJobStatus,
  state,
  toast,
} from "./events.js";
import { recommendedJobsHtml } from "./format.js";

let canvasRenderHooks = [];
let draggingJobId = null;

export function setCanvasRenderHook(fn) {
  if (typeof fn === "function") canvasRenderHooks.push(fn);
}

export async function runCanvasRenderHooks(app) {
  await Promise.all(
    canvasRenderHooks.map((hook) =>
      Promise.resolve()
        .then(() => hook(app))
        .catch((error) => {
          /* a failing hook must not break the merged jobs render */
          console.error("canvas render hook failed:", error);
        }),
    ),
  );
}

/* ADR-0065：按简历推荐的唯一入口（工具栏按钮 + 一个卡片面板）。
 * 任何失败都降级成一句提示，不弹错、不改任何岗位状态。 */
export function bindRecommendedPanel(app) {
  const toggle = app.querySelector("[data-recommended-toggle]");
  const panel = app.querySelector("[data-recommended-panel]");
  if (!toggle || !panel) return;
  toggle.addEventListener("click", async () => {
    panel.hidden = !panel.hidden;
    if (panel.hidden) return;
    panel.innerHTML = '<div class="muted small">正在计算推荐…</div>';
    try {
      const resumes = await api("/api/master-resumes");
      if (!Array.isArray(resumes) || !resumes.length) {
        panel.innerHTML = '<div class="muted small">先在简历中心添加一份主简历。</div>';
        return;
      }
      const payload = await api(
        "/api/jobs/recommended?limit=10&resume_id=" +
          encodeURIComponent(resumes[0].resume_id),
      );
      panel.innerHTML = recommendedJobsHtml(payload);
    } catch (error) {
      console.error("recommended jobs failed:", error);
      panel.innerHTML = '<div class="muted small">暂时无法生成推荐。</div>';
    }
  });
}

function isTerminalJobStatus(status) {
  return status === "offer" || status === "withdrawn";
}

function moveBoardJob(jobId, status, extra = {}) {
  const dateField = extra.offer_at
    ? "offer_at"
    : extra.rejected_at
      ? "rejected_at"
      : null;
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

function prefersCoarsePointer() {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(pointer: coarse)").matches
  );
}

export function bindBoardDrag(root, rerender = () => {}) {
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
    column.addEventListener("dragleave", () =>
      column.classList.remove("is-drag-over"),
    );
    column.addEventListener("drop", async (event) => {
      event.preventDefault();
      column.classList.remove("is-drag-over");
      const jobId =
        draggingJobId ||
        (event.dataTransfer && event.dataTransfer.getData("text/plain"));
      if (!jobId) return;
      const status = column.dataset.status;
      const applyMove = async (extra = {}) => {
        try {
          const result = await moveBoardJob(jobId, status, extra);
          if (result.updated) toast("岗位状态已更新", "success");
          rerender();
        } catch (error) {
          toast(error.message, "error");
        }
      };
      const job = (state.jobs || []).find((item) => item.job_id === jobId);
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
