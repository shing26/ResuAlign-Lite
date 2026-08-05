import { $, $$, api, esc, state } from "./events.js";
import {
  buildWbDetailHtml,
  buildWbResultHtmlFrom,
  lineDiff,
  renderWbProvenance,
} from "./format.js";

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
  panel.innerHTML = buildWbResultHtml(result, diffs, accepted);
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
  state.wbAcceptedIndices = accepted;
  await renderWbResult($("#app"));
  const target = $("[data-accept-result]");
  target.innerHTML = `
    <div class="drawer">
      <h4>采纳 ${body.accepted_count} 项修改后的草稿</h4>
      <div class="pre">${esc(body.draft)}</div>
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
