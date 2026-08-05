import { $, $$, api, esc, state } from "./events.js";
import { buildWbDetailHtml, renderWbProvenance } from "./appraisal-panel.js";

export function lineDiff(original, proposed) {
  const originalLines = String(original || "").split("\n");
  const proposedLines = String(proposed || "").split("\n");
  const oldSet = new Set(originalLines.map((line) => line.trim()));
  const newSet = new Set(proposedLines.map((line) => line.trim()));
  const rows = [];
  for (const line of originalLines) {
    const trimmed = line.trim();
    if (trimmed && !newSet.has(trimmed)) rows.push({ type: "remove", text: line });
  }
  for (const line of proposedLines) {
    const trimmed = line.trim();
    if (trimmed && !oldSet.has(trimmed)) rows.push({ type: "add", text: line });
  }
  return rows;
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
  panel.innerHTML = buildWbResultHtml(result, diffs, accepted);
}

export function buildWbResultHtml(result, diffs, accepted) {
  const sections = (result.tailored_resume || {}).sections || {};
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
  const originalHtml =
    String(originalText)
      .split("\n")
      .map((line) => {
        const trimmed = line.trim();
        const changed = removedLines.has(trimmed) || modifyOriginal.has(trimmed);
        return `<div class="cmp-line ${changed ? "diff-remove" : ""}">${changed ? "−" : ""}${esc(line)}</div>`;
      })
      .join("") || '<div class="muted small">原版内容不可用</div>';
  const optimizedHtml =
    optimizedText
      .split("\n")
      .map((line) => {
        const trimmed = line.trim();
        if (!trimmed) return '<div class="cmp-line">&nbsp;</div>';
        const changed = addedLines.has(trimmed) || modifyProposed.has(trimmed);
        return `<div class="cmp-line ${changed ? "diff-add" : ""}">${changed ? "＋" : ""}${esc(line)}</div>`;
      })
      .join("") || '<div class="muted small">暂无优化内容</div>';
  const sideView = `
    <div class="cmp-grid cmp-grid--workbench">
      <section class="cmp-column-wrap"><h4>原版</h4><div class="cmp-column motion-stagger">${originalHtml}</div></section>
      <section class="cmp-column-wrap"><h4>优化版</h4><div class="cmp-column motion-stagger">${optimizedHtml}</div></section>
    </div>`;
  const diffCards = diffs
    .map(
      (diff, index) => `
      <div class="card diff-card card-base card-hover-soft">
        <div class="row" style="align-items:flex-start">
          <label class="cmp-check"><input type="checkbox" data-accept-diff="${index}" ${accepted.has(index) ? "" : "checked"} aria-label="采纳此条"><span class="small">采纳</span></label>
          <span class="badge badge-${diff.type === "add" ? "green" : diff.type === "remove" ? "red" : "blue"}">${esc(diff.type)}</span>
          <span class="small muted">${esc(diff.reason || "")} · ${esc(diff.confidence || "")}</span>
        </div>
        ${diff.type !== "add" ? `<div class="diff-line diff-remove">- ${esc(diff.original)}</div>` : ""}
        ${diff.type !== "remove" ? `<div class="diff-line diff-add">+ ${esc(diff.proposed)}</div>` : ""}
        ${renderWbProvenance(diff)}
        <div class="row" style="margin-top:8px">
          <button class="btn btn-secondary btn-sm" data-action="regenerate-diff" data-index="${index}">重新生成</button>
        </div>
      </div>`,
    )
    .join("");
  const score = result.score ?? "—";
  const ringClass =
    score >= 80
      ? "score-ring--high"
      : score >= 60
        ? "score-ring--mid"
        : "score-ring--low";
  return `
    <div class="wb-level">
      <div class="wb-score-row">
        <div class="score-ring ${ringClass}" style="--score:${esc(score)}"><span>${esc(score)}</span></div>
        <div>
          <span class="badge badge-green">已完成</span>
          <div class="small muted" style="margin-top:4px">总分 ${esc(score)} / 100 · ${esc(result.model || "—")} · ${esc(result.elapsed_seconds ?? 0)}s</div>
        </div>
      </div>
      <div class="row">
        <button class="btn btn-primary btn-sm" data-action="print-workbench">导出 PDF</button>
        <button class="btn btn-secondary btn-sm" data-action="export-markdown">导出 Markdown</button>
        <button class="btn btn-outline btn-sm" data-action="export-json">导出 JSON</button>
      </div>
    </div>
    <div class="segmented segmented-card" role="group" aria-label="结果视图">
      <button type="button" class="segmented-button" data-action="toggle-wb-view" data-wb-view="side" aria-pressed="${state.wbCompareView === "side"}">并排对比</button>
      <button type="button" class="segmented-button" data-action="toggle-wb-view" data-wb-view="list" aria-pressed="${state.wbCompareView === "list"}">修改列表</button>
    </div>
    ${state.wbCompareView === "side" ? sideView : ""}
    <div class="wb-level">
      <h4>逐条修改（${diffs.length}）</h4>
      <div class="card-list motion-stagger">${diffCards || '<div class="muted small">无修改项</div>'}</div>
      <div class="row" style="margin-top:10px"><button class="btn btn-primary" data-action="accept-diffs">采纳选中修改</button></div>
    </div>
    <div class="wb-level">
      <h4>分析详情</h4>
      ${buildWbDetailHtml(result, diffs)}
    </div>
    <div data-accept-result></div>`;
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
