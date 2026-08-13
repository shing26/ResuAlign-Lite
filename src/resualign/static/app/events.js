/* Runtime helpers, modal handling, and progress/polling events. */

import {
  focusInitial,
  lockBodyScroll,
  restoreFocus,
  trapTabKey,
  unlockBodyScroll,
} from "./focus-trap.js";
import {
  DEFAULT_VOCABULARY,
  STAGE_LABELS,
  atsHealthCardHtml,
  buildDiagnosisMarkdownFrom,
  esc,
  formatElapsed,
  isBackwardJobStatus,
  jobTerminalConfirmFormHtml,
  jobStatusLabel,
  jobStatusRank,
  normalizeVocabulary,
  normalizeVocabularyList,
  renderBatchMatrixHtml,
} from "./format.js";

/* Pure formatting / vocabulary / status helpers now live in format.js.
 * They are re-exported here so every existing import path keeps working. */
export {
  DEFAULT_VOCABULARY,
  JOB_FUNCTIONS,
  JOB_STATUS_ALIASES,
  JOB_STATUS_CANONICAL,
  JOB_STATUS_LABELS,
  JOB_STATUSES,
  SENIORITIES,
  STAGE_LABELS,
  canonicalJobStatus,
  esc,
  formatDate,
  formatSalary,
  isBackwardJobStatus,
  jobStatusRank,
  jobStatusLabel,
  normalizeVocabulary,
  normalizeVocabularyList,
  options,
} from "./format.js";

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

let vocabularyRequest = null;

export const APP_STATUSES = ["draft", "applied", "interview", "offer", "rejected", "withdrawn"];
export const APP_STATUS_LABELS = {
  draft: "草稿",
  applied: "已投递",
  interview: "面试中",
  offer: "已拿Offer",
  rejected: "未通过",
  withdrawn: "已放弃",
};
export const STAGE_WEIGHTS = {
  queued: 0.05,
  running: 0.1,
  diagnose: 0.2,
  jd_profile: 0.4,
  jd_analysis: 0.45,
  gap_analysis: 0.6,
  tailoring: 0.85,
  evaluation: 0.95,
  succeeded: 1,
};

export const state = {
  route: { name: "resume", jobId: null },
  resumes: [],
  jobs: [],
  filters: { job_function: "", seniority: "", status: "", search: "" },
  offset: 0,
  limit: 20,
  wbJob: null,
  wbResumes: [],
  wbApplications: [],
  applicationPoll: null,
  wbResult: null,
  wbRun: null,
  wbOriginalContent: null,
  wbAcceptedIndices: null,
  wbCompareView: "list",
  wbMobilePane: "controls",
  batchAlign: null,
  batchPolling: null,
  batchResumes: [],
  wbFinalDraft: null,
  wbRawJdOpen: false,
  wbControlsOpen: true,
  wbExportDockOpen: false,
  /* U7: 工作台工作草稿——采纳/应用基于当前草稿增量合并，连续采纳不丢前一条。
   * wbWorkingDraft = { jobId, draft }；wbAcceptedBullets = { [jobId]: [diffId] } */
  wbWorkingDraft: null,
  wbAcceptedBullets: {},
  diagnosis: null,
  diagnosisPolling: null,
  diagnosisResumeId: null,
  settings: null,
  vocabulary: null,
  pollers: {},
  token: localStorage.getItem("resualign_token") || "",
};

/* ------------------------------------------------------------------ */
/* Polling registry: one start/stop API for every async poller.        */
/* startPolling registers fn under id and runs it immediately;         */
/* stopAllPolling() clears every registered timer (used on render).    */
/* ------------------------------------------------------------------ */

export function startPolling(id, fn, interval) {
  stopPolling(id);
  const timer = window.setInterval(fn, interval);
  state.pollers[id] = { timer, fn, interval };
  fn();
  return timer;
}

export function stopPolling(id) {
  const entry = state.pollers[id];
  if (entry) {
    window.clearInterval(entry.timer);
    delete state.pollers[id];
  }
}

export function stopAllPolling() {
  for (const id of Object.keys(state.pollers)) stopPolling(id);
}

export function toast(message, kind = "info") {
  const region = $("#toast-region");
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  const text = document.createElement("span");
  text.textContent = message;
  const close = document.createElement("button");
  close.type = "button";
  close.setAttribute("aria-label", "关闭提示");
  close.textContent = "×";
  close.addEventListener("click", () => node.remove());
  node.append(text, close);
  region.append(node);
  setTimeout(() => node.remove(), 6000);
}

export function vocabularyList(key) {
  return normalizeVocabularyList(
    state.vocabulary && state.vocabulary[key],
    DEFAULT_VOCABULARY[key],
  );
}

export async function ensureVocabulary() {
  if (state.vocabulary) return state.vocabulary;
  if (!vocabularyRequest) {
    vocabularyRequest = api("/api/settings")
      .then(
        (settings) =>
          normalizeVocabulary(settings && settings.classification_vocabulary),
      )
      .catch(() => normalizeVocabulary(null));
  }
  state.vocabulary = await vocabularyRequest;
  return state.vocabulary;
}

export function download(filename, content, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (
    options.body &&
    !headers["Content-Type"] &&
    !(options.body instanceof FormData)
  ) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401 && !state.personal) {
    openLoginModal();
    throw new Error("登录已过期，请重新登录");
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = await response.json();
      detail = data.detail || detail;
    } catch {
      /* keep status text */
    }
    const message =
      typeof detail === "string"
        ? detail
        : detail && detail.reason
          ? detail.reason
          : JSON.stringify(detail);
    const error = new Error(message);
    error.status = response.status;
    if (detail && typeof detail === "object") error.data = detail;
    throw error;
  }
  if (response.status === 204) return null;
  return response.json();
}

let modalReturnFocus = null;
let modalKeydownHandler = null;

export function showModal(title, bodyHtml) {
  closeModal();
  modalReturnFocus =
    document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.setAttribute("role", "dialog");
  backdrop.setAttribute("aria-modal", "true");
  backdrop.setAttribute("aria-label", title);
  backdrop.innerHTML = `<div class="modal"><h3>${esc(title)}</h3>${bodyHtml}</div>`;
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) closeModal();
  });
  document.body.append(backdrop);
  lockBodyScroll(document.body);
  modalKeydownHandler = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeModal();
      return;
    }
    trapTabKey(backdrop, event, document.activeElement);
  };
  document.addEventListener("keydown", modalKeydownHandler);
  window.setTimeout(() => focusInitial(backdrop), 0);
}

export function closeModal() {
  const backdrop = $(".modal-backdrop");
  if (backdrop) backdrop.remove();
  if (modalKeydownHandler) {
    document.removeEventListener("keydown", modalKeydownHandler);
    modalKeydownHandler = null;
  }
  unlockBodyScroll(document.body);
  restoreFocus(modalReturnFocus);
  modalReturnFocus = null;
}

let pendingStatusTransition = null;

export function confirmBackwardStatus(job, targetStatus, onConfirm, onCancel) {
  pendingStatusTransition = { onConfirm, onCancel };
  const title = job && job.title ? job.title : "该岗位";
  showModal(
    "确认后退状态",
    `<p>将「${esc(title)}」从「${esc(jobStatusLabel(job && job.status))}」后退到「${esc(jobStatusLabel(targetStatus))}」，会清理后续阶段的时间戳与跟进信息。确定继续吗？</p>
     <div class="actions">
       <button class="btn btn-ghost" type="button" data-action="cancel-status-back">取消</button>
       <button class="btn btn-primary" type="button" data-action="confirm-status-back">确认后退</button>
     </div>`,
  );
}

export function confirmTerminalStatus(
  job,
  targetStatus,
  onConfirm,
  onCancel,
  options = {},
) {
  pendingStatusTransition = { onConfirm, onCancel };
  showModal(
    `收口确认 · ${jobStatusLabel(targetStatus)}`,
    jobTerminalConfirmFormHtml(job, targetStatus, options),
  );
}

export async function applyPendingStatusTransition(payload) {
  const pending = pendingStatusTransition;
  if (!pending) return;
  pendingStatusTransition = null;
  closeModal();
  if (typeof pending.onConfirm === "function") {
    await pending.onConfirm(payload || {});
  }
}

export function cancelPendingStatusTransition() {
  const pending = pendingStatusTransition;
  pendingStatusTransition = null;
  closeModal();
  if (pending && typeof pending.onCancel === "function") pending.onCancel();
}

export function openLoginModal() {
  showModal(
    "登录 ResuAlign",
    `<form data-form="login">
      <div class="field"><label>邮箱</label><input type="email" name="email" required></div>
      <div class="field"><label>密码</label><input type="password" name="password" required minlength="8"></div>
      <div class="actions"><button class="btn btn-ghost" type="button" data-action="close-modal">取消</button>
        <button class="btn btn-primary" type="submit">登录</button></div>
    </form>`,
  );
}

export async function recoverDiagnosis(resume) {
  stopDiagnosisPolling();
  const jobId = resume.latest_diagnosis_job_id;
  if (!jobId) {
    renderDiagnosisIdle();
    return;
  }
  state.diagnosisResumeId = resume.resume_id || state.diagnosisResumeId;
  let snapshot;
  try {
    snapshot = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
  } catch {
    renderDiagnosisIdle();
    return;
  }
  state.diagnosis = { job_id: jobId, ...snapshot };
  if (snapshot.status === "succeeded") {
    renderDiagnosisResult(snapshot);
  } else if (snapshot.status === "failed" || snapshot.status === "canceled") {
    renderDiagnosisError(snapshot);
  } else {
    renderDiagnosisProgress(snapshot);
    startDiagnosisPolling(jobId, resume.resume_id);
  }
}

export function startDiagnosisPolling(jobId, resumeId) {
  stopDiagnosisPolling();
  state.diagnosisResumeId = resumeId || state.diagnosisResumeId;
  state.diagnosisPolling = { jobId };
  startPolling("diagnosis", () => pollDiagnosisJob(jobId), 1000);
}

export function stopDiagnosisPolling() {
  stopPolling("diagnosis");
  state.diagnosisPolling = null;
}

export async function pollDiagnosisJob(jobId) {
  if (!state.diagnosisPolling || state.diagnosisPolling.jobId !== jobId) return;
  try {
    const snapshot = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    if (!state.diagnosisPolling || state.diagnosisPolling.jobId !== jobId) return;
    renderDiagnosisProgress(snapshot);
    if (["succeeded", "failed", "canceled"].includes(snapshot.status)) {
      stopDiagnosisPolling();
      state.diagnosis = { job_id: jobId, ...snapshot };
      if (snapshot.status === "succeeded") {
        renderDiagnosisResult(snapshot);
        toast(`简历诊断完成，得分 ${snapshot.result && snapshot.result.diagnosis ? snapshot.result.diagnosis.score : snapshot.result ? snapshot.result.score : ""}`, "success");
      } else {
        renderDiagnosisError(snapshot);
      }
    }
  } catch (error) {
    stopDiagnosisPolling();
    renderDiagnosisError({ status: "failed", error: error.message });
  }
}

export function renderDiagnosisIdle() {
  const panel = $("[data-diagnosis-panel]");
  if (!panel) return;
  const meta = $("[data-diagnosis-meta]", panel);
  if (meta) meta.textContent = "尚未诊断";
  const progress = $("[data-diagnosis-progress]", panel);
  if (progress) progress.hidden = true;
  const result = $("[data-diagnosis-result]", panel);
  if (result) {
    result.hidden = true;
    result.innerHTML = "";
  }
  const error = $("[data-diagnosis-error]", panel);
  if (error) {
    error.hidden = true;
    error.innerHTML = "";
  }
  $$("[data-action='export-diagnosis'], [data-action='export-diagnosis-md']", panel).forEach(
    (node) => {
      node.hidden = true;
    },
  );
  const diagnoseBtn = $("[data-action='diagnose-resume']", panel);
  if (diagnoseBtn) {
    diagnoseBtn.disabled = false;
    diagnoseBtn.textContent = "诊断简历";
  }
  /* Sprint 4 T3: 空闲态把右侧 ATS 卡重置为占位。 */
  const atsNode = $("[data-ats-health-mount]");
  if (atsNode) atsNode.innerHTML = atsHealthCardHtml(null);
}

export function renderDiagnosisProgress(snapshot) {
  const panel = $("[data-diagnosis-panel]");
  if (!panel) return;
  const progress = $("[data-diagnosis-progress]", panel);
  if (progress) progress.hidden = false;
  const result = $("[data-diagnosis-result]", panel);
  if (result) result.hidden = true;
  const error = $("[data-diagnosis-error]", panel);
  if (error) {
    error.hidden = true;
    error.innerHTML = "";
  }
  const meta = $("[data-diagnosis-meta]", panel);
  if (meta) {
    meta.textContent =
      snapshot.message ||
      (snapshot.status === "queued" ? "排队中..." : "诊断进行中...");
  }
  const fill = $("[data-diagnosis-fill]", panel);
  const stage = $("[data-diagnosis-stage]", panel);
  const elapsed = $("[data-diagnosis-elapsed]", panel);
  const weight =
    STAGE_WEIGHTS[snapshot.stage || snapshot.status] ?? STAGE_WEIGHTS.running;
  if (fill) fill.style.width = `${Math.round(weight * 100)}%`;
  if (stage) {
    stage.textContent =
      STAGE_LABELS[snapshot.stage || snapshot.status] ||
      snapshot.stage ||
      snapshot.status;
  }
  if (elapsed) elapsed.textContent = `${snapshot.elapsed_seconds || 0}s`;
  const cancel = $("[data-action='cancel-diagnosis']", panel);
  if (cancel) {
    cancel.hidden =
      snapshot.status !== "queued" && snapshot.status !== "running";
  }
  const diagnoseBtn = $("[data-action='diagnose-resume']", panel);
  if (diagnoseBtn) {
    diagnoseBtn.disabled = true;
    diagnoseBtn.textContent = "诊断中...";
    diagnoseBtn.classList.add("is-loading");
  }
}

export function renderDiagnosisResult(snapshot) {
  const panel = $("[data-diagnosis-panel]");
  if (!panel) return;
  const result = snapshot.result || {};
  const diagnosis = result.diagnosis || result;
  const score = Math.max(0, Math.min(100, Number(diagnosis.score) || 0));
  const skills = diagnosis.skills || [];
  const issues = diagnosis.issues || [];
  const suggestions = diagnosis.suggestions || [];
  const meta = $("[data-diagnosis-meta]", panel);
  if (meta) {
    meta.textContent = `最近诊断 · 用时 ${snapshot.elapsed_seconds || 0}s · 模型 ${diagnosis.model || "未知"}`;
  }
  const progress = $("[data-diagnosis-progress]", panel);
  if (progress) progress.hidden = true;
  const error = $("[data-diagnosis-error]", panel);
  if (error) {
    error.hidden = true;
    error.innerHTML = "";
  }
  $$("[data-action='export-diagnosis'], [data-action='export-diagnosis-md']", panel).forEach(
    (node) => {
      node.hidden = false;
    },
  );
  const target = $("[data-diagnosis-result]", panel);
  if (!target) return;
  target.hidden = false;
  const verdictClass =
    score >= 80 ? "badge-green" : score >= 60 ? "badge-amber" : "badge-red";
  const verdict = score >= 80 ? "优秀" : score >= 60 ? "建议优化" : "需重点优化";
  target.innerHTML = `
    <div class="diagnosis-banner__result">
      <span class="diagnosis-banner__score">${score}</span>
      <span class="badge ${verdictClass}">${verdict}</span>
      <span class="small muted">诊断分 ${score} / 100 · 详情见右侧 ATS 健康度</span>
      <span class="diagnosis-banner__actions">
        <button class="btn btn-outline btn-sm" data-action="diagnosis-to-align" data-id="${state.diagnosisResumeId || ""}">去对齐</button>
        <button class="btn btn-ghost btn-sm" data-action="rerun-diagnosis" data-id="${state.diagnosisResumeId || ""}">重新诊断</button>
      </span>
    </div>`;
  const diagnoseBtn = $("[data-action='diagnose-resume']", panel);
  if (diagnoseBtn) {
    diagnoseBtn.disabled = false;
    diagnoseBtn.textContent = "诊断简历";
    diagnoseBtn.classList.remove("is-loading");
  }
  /* Sprint 4 T3: 诊断完成同步刷新右侧 ATS 健康度卡。 */
  const atsNode = $("[data-ats-health-mount]");
  if (atsNode) atsNode.innerHTML = atsHealthCardHtml(diagnosis);
}

export function renderDiagnosisError(snapshot) {
  const panel = $("[data-diagnosis-panel]");
  if (!panel) return;
  const meta = $("[data-diagnosis-meta]", panel);
  if (meta) meta.textContent = "最近一次诊断失败";
  const progress = $("[data-diagnosis-progress]", panel);
  if (progress) progress.hidden = true;
  const result = $("[data-diagnosis-result]", panel);
  if (result) {
    result.hidden = true;
    result.innerHTML = "";
  }
  const error = $("[data-diagnosis-error]", panel);
  if (error) {
    error.hidden = false;
    error.setAttribute("role", "alert");
    error.innerHTML = `
      <div><strong>${snapshot.status === "canceled" ? "诊断已取消" : "诊断失败"}</strong>：${esc(snapshot.error || "诊断任务暂时失败，请重试")}</div>
      <div class="row" style="margin-top:10px">
        <button class="btn btn-primary btn-sm" data-action="rerun-diagnosis" data-id="${state.diagnosisResumeId || ""}">重新诊断</button>
      </div>`;
  }
  $$("[data-action='export-diagnosis'], [data-action='export-diagnosis-md']", panel).forEach(
    (node) => {
      node.hidden = true;
    },
  );
  const diagnoseBtn = $("[data-action='diagnose-resume']", panel);
  if (diagnoseBtn) {
    diagnoseBtn.disabled = false;
    diagnoseBtn.textContent = "诊断简历";
    diagnoseBtn.classList.remove("is-loading");
  }
  /* Sprint 4 T3: 失败态清空右侧 ATS 卡，避免展示过期结果。 */
  const atsNode = $("[data-ats-health-mount]");
  if (atsNode) atsNode.innerHTML = atsHealthCardHtml(null);
}

export function buildDiagnosisMarkdown(originalContent = "") {
  const snapshot = state.diagnosis || {};
  const result = snapshot.result || {};
  const diagnosis = result.diagnosis || result;
  const titleNode = document.querySelector(".page-header h2");
  const title = titleNode ? titleNode.textContent : "简历诊断";
  return buildDiagnosisMarkdownFrom(diagnosis, title, originalContent);
}

export function startBatchPolling(batchId) {
  stopBatchPolling();
  state.batchPolling = { batchId };
  startPolling("batch", () => pollBatch(batchId), 1000);
}

export function stopBatchPolling() {
  stopPolling("batch");
  state.batchPolling = null;
}

export async function pollBatch(batchId) {
  if (!state.batchPolling || state.batchPolling.batchId !== batchId) return;
  try {
    const batch = await api(`/api/batch-align/${encodeURIComponent(batchId)}`);
    state.batchAlign = batch;
    renderBatchResults(batch);
    if (batch.summary.completed === batch.summary.total) {
      stopBatchPolling();
      const cancel = $("[data-batch-cancel]");
      if (cancel) cancel.hidden = true;
    }
  } catch (error) {
    stopBatchPolling();
    toast(error.message, "error");
  }
}

export function renderBatchResults(batch) {
  const status = $("[data-batch-status]");
  if (status) status.textContent = `已完成 ${batch.summary.completed}/${batch.summary.total}`;
  const results = $("[data-batch-results]");
  if (!results) return;
  results.innerHTML = renderBatchMatrixHtml(batch);
}

/* F5: 移动端工作台 tab 切换（controls / diff）。激活指定 pane：
 * 更新 [data-wb-tab] 的 aria-selected 与 [data-wb-pane] 的 is-active。 */
export function setWbMobilePane(pane) {
  const target = ["controls", "diff"].includes(pane) ? pane : "controls";
  state.wbMobilePane = target;
  $$("[data-wb-tab]").forEach((tab) =>
    tab.setAttribute("aria-selected", String(tab.dataset.wbTab === target)),
  );
  $$("[data-wb-pane]").forEach((paneNode) => {
    paneNode.classList.toggle("is-active", paneNode.dataset.wbPane === target);
  });
}

export function stopApplicationPolling() {
  const poll = state.applicationPoll;
  if (poll && poll.timer) window.clearInterval(poll.timer);
  stopPolling("application");
  state.applicationPoll = null;
}
