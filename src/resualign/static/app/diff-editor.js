import { $, $$, api, esc, state } from "./events.js";
import {
  applyDiffToDraft,
  buildWbDetailHtml,
  buildWbResultHtmlFrom,
  lineDiff,
  renderWbProvenance,
} from "./format.js";

/* Scroll positions of the two .cmp-columns, kept across re-renders so
 * view toggles (side <-> list) and accept re-renders preserve the
 * reader's place in the compare view. */
let wbColumnScrollTops = [];
let wbSyncCleanup = null;

/* Mirror source.scrollTop onto target; returns true when it moved.
 * Scroll sync is position state, not animation, so it stays active
 * under prefers-reduced-motion (the reduced-motion CSS already forces
 * scroll-behavior: auto for any native smooth scrolling). */
export function syncScrollTop(target, source) {
  if (!target || !source || target === source) return false;
  if (target.scrollTop === source.scrollTop) return false;
  target.scrollTop = source.scrollTop;
  return true;
}

/* Wire two compare columns so scrolling one mirrors the other, guarded
 * by a reentrancy flag (programmatic scrollTop assignment fires scroll
 * events in real browsers). Returns an unbind function. */
export function bindColumnScrollSync(columns) {
  const [left, right] = columns;
  if (!left || !right || left === right) return () => {};
  let syncing = false;
  const onLeftScroll = () => {
    if (syncing) return;
    syncing = true;
    syncScrollTop(right, left);
    syncing = false;
  };
  const onRightScroll = () => {
    if (syncing) return;
    syncing = true;
    syncScrollTop(left, right);
    syncing = false;
  };
  left.addEventListener("scroll", onLeftScroll);
  right.addEventListener("scroll", onRightScroll);
  return () => {
    left.removeEventListener("scroll", onLeftScroll);
    right.removeEventListener("scroll", onRightScroll);
  };
}

/* Read the .cmp-column scroll positions inside `container`. */
export function captureColumnScrolls(container) {
  if (!container) return [];
  return $$(".cmp-column", container).map((column) => column.scrollTop);
}

/* Restore .cmp-column scroll positions from `tops`; returns the number
 * of columns restored. */
export function restoreColumnScrolls(container, tops) {
  if (!container || !Array.isArray(tops)) return 0;
  let restored = 0;
  $$(".cmp-column", container).forEach((column, index) => {
    const top = tops[index];
    if (typeof top === "number" && Number.isFinite(top)) {
      column.scrollTop = top;
      restored += 1;
    }
  });
  return restored;
}

export async function renderWbResult(app) {
  const panel = $("[data-wb-result]");
  if (!panel) return;
  panel.hidden = false;
  const result = state.wbResult || {};
  const diffs = result.diffs || [];
  const sections = (result.tailored_resume || {}).sections || {};
  const progressPanel = $("[data-wb-progress-panel]");
  if (progressPanel) progressPanel.hidden = true;

  const pinnedResumeId =
    (state.wbRun && state.wbRun.masterResumeId) ||
    (state.wbJob && state.wbJob.workbench_resume_id);
  if (!state.wbOriginalContent && pinnedResumeId) {
    try {
      const resume = await api(
        `/api/master-resumes/${encodeURIComponent(pinnedResumeId)}`,
      );
      state.wbOriginalContent = resume.content || "";
    } catch {
      state.wbOriginalContent = "";
    }
  }
  const optimizedText =
    Object.values(sections).join("\n\n") || result.tailored_resume || "";
  const originalText = state.wbOriginalContent || "";
  const diffRows = lineDiff(originalText, optimizedText);
  const removedLines = new Set(
    diffRows
      .filter((row) => row.type === "remove")
      .map((row) => row.text.trim()),
  );
  const addedLines = new Set(
    diffRows
      .filter((row) => row.type === "add")
      .map((row) => row.text.trim()),
  );
  const modifyOriginal = new Set();
  const modifyProposed = new Set();
  const proposedIndex = new Map();
  const removeIndex = new Map();
  diffs.forEach((diff, index) => {
    const orig = String(diff.original || "").trim();
    const prop = String(diff.proposed || "").trim();
    if (diff.type === "modify") {
      if (orig) modifyOriginal.add(orig);
      if (prop) modifyProposed.add(prop);
    }
    if (diff.type !== "remove" && prop) proposedIndex.set(prop, index);
    if (diff.type === "remove" && orig) removeIndex.set(orig, index);
  });
  const reasonByLine = new Map();
  for (const diff of diffs) {
    if (diff.proposed && diff.reason) {
      reasonByLine.set(String(diff.proposed).trim(), diff.reason);
    }
  }
  const accepted = new Set(state.wbAcceptedIndices || []);
  /* Preserve the reader's place: remember current column positions
   * before re-rendering (list view has no columns, so the last side-view
   * positions are kept), then restore them on the fresh columns and
   * re-wire the scroll mirroring. */
  const savedScrollTops = captureColumnScrolls(panel);
  if (savedScrollTops.length) wbColumnScrollTops = savedScrollTops;
  panel.innerHTML = buildWbResultHtml(result, diffs, accepted);
  restoreColumnScrolls(panel, wbColumnScrollTops);
  if (wbSyncCleanup) wbSyncCleanup();
  wbSyncCleanup = null;
  if (state.wbCompareView === "side") {
    wbSyncCleanup = bindColumnScrollSync($$(".cmp-column", panel));
  }
}

export function buildWbResultHtml(result, diffs, accepted) {
  return buildWbResultHtmlFrom(
    result,
    diffs,
    accepted,
    state.wbOriginalContent || "",
    state.wbCompareView,
  );
}

export function renderWbError(app, snapshot) {
  const panel = $("[data-wb-result]");
  if (!panel) return;
  panel.hidden = false;
  const progressPanel = $("[data-wb-progress-panel]");
  if (progressPanel) progressPanel.hidden = true;
  panel.innerHTML = `
    <h3>运行${snapshot.status === "canceled" ? "已取消" : "失败"}</h3>
    <p class="muted">${esc(snapshot.error || "")}</p>
    <div class="row"><button class="btn btn-primary" data-action="retry-workbench">重新运行</button></div>`;
}

export async function acceptSelectedDiffs() {
  const jobId = state.wbJob.job_id;
  const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
  const accepted = [
    ...new Set(
      $$("[data-accept-diff]:checked").map((input) =>
        Number(input.dataset.acceptDiff),
      ),
    ),
  ];
  const body = await api(`/api/jobs/${encodeURIComponent(jobId)}/workbench/accept`, {
    method: "POST",
    body: JSON.stringify({ job_id: job.workbench_job_id, accepted_indices: accepted }),
  });
  /* U7: 后端 /workbench/accept 总是从「原始主简历」重建草稿，连续两轮
   * 「采纳选中修改」会丢上一轮结果。这里把本轮新增的 accepted index 增量
   * 合并进工作草稿（state.wbWorkingDraft），保证多轮采纳累积。 */
  const diffs = job.diffs || [];
  const previous = new Set(state.wbAcceptedIndices || []);
  const fresh = accepted.filter((index) => !previous.has(index));
  let draft = body.draft;
  if (state.wbWorkingDraft && state.wbWorkingDraft.jobId === jobId) {
    draft = state.wbWorkingDraft.draft;
    for (const index of fresh) draft = applyDiffToDraft(draft, diffs[index]);
  }
  state.wbWorkingDraft = { jobId, draft };
  state.wbAcceptedIndices = accepted;
  await renderWbResult($("#app"));
  const target = $("[data-accept-result]");
  target.innerHTML = `
    <div class="drawer">
      <h4>采纳 ${body.accepted_count} 项修改后的草稿</h4>
      <div class="pre">${esc(draft)}</div>
      <div class="row" style="margin-top:8px">
        <button class="btn btn-primary btn-sm" data-action="save-final-draft">保存定稿</button>
        <button class="btn btn-secondary btn-sm" data-action="export-draft">导出草稿</button>
      </div>
    </div>`;
}

export function regenerateDiff() {
  const form = $('[data-form="wb-run"]');
  if (form) form.dispatchEvent(new Event("submit", { cancelable: true }));
}

export function toggleWbView(button) {
  state.wbCompareView = button.dataset.wbView;
  renderWbResult($("#app"));
}
