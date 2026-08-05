/* Runtime helpers, modal handling, and progress/polling events. */

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

export const JOB_FUNCTIONS = [
  "后端", "前端", "算法", "数据", "测试", "运维",
  "产品", "设计", "运营", "销售", "其他",
];
export const SENIORITIES = ["初级", "中级", "高级", "资深", "未知"];
export const JOB_STATUSES = ["未投递", "已投递", "面试中", "已拿Offer", "放弃"];
export const JOB_STATUS_CANONICAL = ["draft", "applied", "interview", "offer", "withdrawn"];
export const JOB_STATUS_ALIASES = {
  "未投递": "draft",
  "已投递": "applied",
  "面试中": "interview",
  "已拿Offer": "offer",
  "放弃": "withdrawn",
};
export const JOB_STATUS_LABELS = {
  draft: "未投递",
  applied: "已投递",
  interview: "面试中",
  offer: "已拿Offer",
  withdrawn: "放弃",
};

export function canonicalJobStatus(status) {
  const value = String(status || "").trim();
  return JOB_STATUS_ALIASES[value] || value;
}

export function jobStatusLabel(status) {
  const canonical = canonicalJobStatus(status);
  return JOB_STATUS_LABELS[canonical] || canonical;
}

export const DEFAULT_VOCABULARY = {
  job_functions: JOB_FUNCTIONS,
  seniorities: SENIORITIES,
  statuses: JOB_STATUSES,
};

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
export const STAGE_LABELS = {
  queued: "排队中",
  running: "运行中",
  diagnose: "诊断简历",
  jd_profile: "提取JD画像",
  jd_analysis: "提取JD画像与差距分析",
  gap_analysis: "差距分析",
  tailoring: "AI 改写简历",
  evaluation: "LLM 评估",
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
  wbPolling: null,
  applicationPoll: null,
  wbResult: null,
  wbRun: null,
  wbOriginalContent: null,
  wbAcceptedIndices: null,
  wbCompareView: "list",
  wbAppraisal: null,
  wbAppraisalOpen: false,
  wbMobilePane: "controls",
  batchAlign: null,
  batchPolling: null,
  batchResumes: [],
  wbFinalDraft: null,
  wbRawJdOpen: false,
  diagnosis: null,
  diagnosisPolling: null,
  diagnosisResumeId: null,
  settings: null,
  vocabulary: null,
  token: localStorage.getItem("resualign_token") || "",
};

export function esc(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char],
  );
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

export function formatDate(timestamp) {
  if (!timestamp) return "—";
  const date = new Date(timestamp * 1000);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
    date.getDate(),
  ).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(
    date.getMinutes(),
  ).padStart(2, "0")}`;
}

export function formatSalary(job) {
  const min = job.salary_min;
  const max = job.salary_max;
  const unit = job.salary_currency || "CNY";
  if (min == null && max == null) return "薪资面议";
  if (min != null && max != null) return `${min / 1000}-${max / 1000}K`;
  return `${(min ?? max) / 1000}K`;
}

export function options(values, selected) {
  return values
    .map(
      (value) =>
        `<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${esc(value)}</option>`,
    )
    .join("");
}

export function normalizeVocabularyList(values, fallback) {
  if (!Array.isArray(values)) return [...fallback];
  const cleaned = values
    .map((value) => String(value ?? "").trim())
    .filter(Boolean);
  return cleaned.length ? cleaned : [...fallback];
}

export function normalizeVocabulary(vocabulary) {
  const source = vocabulary && typeof vocabulary === "object" ? vocabulary : {};
  return {
    job_functions: normalizeVocabularyList(source.job_functions, JOB_FUNCTIONS),
    seniorities: normalizeVocabularyList(source.seniorities, SENIORITIES),
    statuses: normalizeVocabularyList(source.statuses, JOB_STATUSES),
  };
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
    if (detail && typeof detail === "object") error.data = detail;
    throw error;
  }
  if (response.status === 204) return null;
  return response.json();
}

export function showModal(title, bodyHtml) {
  closeModal();
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
}

export function closeModal() {
  const backdrop = $(".modal-backdrop");
  if (backdrop) backdrop.remove();
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
  state.diagnosisPolling = {
    jobId,
    timer: window.setInterval(() => pollDiagnosisJob(jobId), 1000),
  };
  pollDiagnosisJob(jobId);
}

export function stopDiagnosisPolling() {
  if (state.diagnosisPolling) {
    window.clearInterval(state.diagnosisPolling.timer);
    state.diagnosisPolling = null;
  }
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
  const ringClass =
    score >= 80 ? "score-ring--high" : score >= 60 ? "score-ring--mid" : "score-ring--low";
  const verdict = score >= 80 ? "优秀" : score >= 60 ? "建议优化" : "需重点优化";
  target.innerHTML = `
    <div class="appraisal-score diagnosis-score">
      <div class="score-ring ${ringClass}" style="--score:${score}"><span>${score}</span></div>
      <div>
        <span class="badge ${verdictClass}">${verdict}</span>
        <div class="small muted" style="margin-top:4px">诊断分 ${score} / 100</div>
      </div>
    </div>
    ${skills.length ? `<div class="chips">${skills.map((skill) => `<span class="chip">${esc(skill)}</span>`).join("")}</div>` : ""}
    <div class="diagnosis-columns">
      <div>
        <h4>问题</h4>
        ${issues.length ? `<ul class="diagnosis-list motion-stagger">${issues.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : `<div class="muted small">未发现明显问题</div>`}
      </div>
      <div>
        <h4>优化建议</h4>
        ${suggestions.length ? `<ul class="diagnosis-list motion-stagger">${suggestions.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : `<div class="muted small">暂无建议</div>`}
      </div>
    </div>
    <div class="row" style="margin-top:12px">
      <button class="btn btn-outline btn-sm" data-action="rerun-diagnosis" data-id="${state.diagnosisResumeId || ""}">重新诊断</button>
    </div>`;
  const diagnoseBtn = $("[data-action='diagnose-resume']", panel);
  if (diagnoseBtn) {
    diagnoseBtn.disabled = false;
    diagnoseBtn.textContent = "诊断简历";
    diagnoseBtn.classList.remove("is-loading");
  }
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
}

export function buildDiagnosisMarkdown(originalContent = "") {
  const snapshot = state.diagnosis || {};
  const result = snapshot.result || {};
  const diagnosis = result.diagnosis || result;
  const titleNode = document.querySelector(".page-header h2");
  const title = titleNode ? titleNode.textContent : "简历诊断";
  const lines = [
    `# ${title}`,
    "",
    `> 诊断分：${diagnosis.score ?? "—"} / 100 · 模型：${diagnosis.model || "未知"}`,
    "",
  ];
  if ((diagnosis.skills || []).length) {
    lines.push(
      "## 技能",
      "",
      ...diagnosis.skills.map((skill) => `- ${skill}`),
      "",
    );
  }
  if ((diagnosis.issues || []).length) {
    lines.push(
      "## 问题",
      "",
      ...diagnosis.issues.map((issue) => `- ${issue}`),
      "",
    );
  }
  if ((diagnosis.suggestions || []).length) {
    lines.push(
      "## 优化建议",
      "",
      ...diagnosis.suggestions.map((item) => `- ${item}`),
      "",
    );
  }
  if (originalContent) {
    lines.push("## 原始简历", "", originalContent, "");
  }
  return lines.join("\n");
}

export function startBatchPolling(batchId) {
  stopBatchPolling();
  state.batchPolling = { batchId, timer: window.setInterval(() => pollBatch(batchId), 1000) };
  pollBatch(batchId);
}

export function stopBatchPolling() {
  if (state.batchPolling) {
    window.clearInterval(state.batchPolling.timer);
    state.batchPolling = null;
  }
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
  if (!batch.rows.some((row) => row.summary)) {
    results.innerHTML = `<div class="batch-progress">${batch.rows
      .map(
        (row) =>
          `<span class="badge badge-pending">${esc(row.title || row.job_id)}: ${esc(row.status)}</span>`,
      )
      .join("")}</div>`;
    return;
  }
  const rows = batch.rows
    .map((row) => {
      const summary = row.summary || {};
      const score = summary.score;
      const verdict =
        score == null ? "—" : score >= 75 ? "投递" : score >= 55 ? "考虑" : "放弃";
      return `<tr>
        <td>${esc(row.title || row.job_id)}</td>
        <td>${esc(score ?? "—")}</td>
        <td>${esc((summary.key_gaps || []).slice(0, 3).join("、") || "—")}</td>
        <td>${esc(verdict)}</td>
        <td>${esc(summary.next_step || row.status)}</td>
        <td><a class="btn btn-ghost btn-sm" href="#/workspace/${encodeURIComponent(row.job_id)}">打开工作台</a></td>
      </tr>`;
    })
    .join("");
  results.innerHTML = `<div class="table-wrap"><table class="data batch-matrix">
    <thead><tr><th>岗位</th><th>分数</th><th>关键缺口</th><th>结论</th><th>下一步</th><th>操作</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

export function renderWbProgress(snapshot) {
  const panel = $("[data-wb-progress-panel]");
  if (!panel) return;
  panel.hidden = false;
  const fill = $("[data-wb-progress-fill]", panel);
  const stage = $("[data-wb-stage]", panel);
  const message = $("[data-wb-message]", panel);
  const elapsed = $("[data-wb-elapsed]", panel);
  const weight = STAGE_WEIGHTS[snapshot.stage || snapshot.status] ?? STAGE_WEIGHTS.running;
  fill.style.width = `${Math.round(weight * 100)}%`;
  stage.textContent = STAGE_LABELS[snapshot.stage || snapshot.status] || snapshot.stage || snapshot.status;
  message.textContent = snapshot.message || "";
  elapsed.textContent = `${snapshot.elapsed_seconds || 0}s`;
  const cancel = $("[data-wb-cancel]");
  if (cancel) cancel.hidden = snapshot.status !== "queued" && snapshot.status !== "running";
}

export function stopWbPolling() {
  if (state.wbPolling) {
    window.clearInterval(state.wbPolling.timer);
    state.wbPolling = null;
  }
}

export function stopApplicationPolling() {
  if (state.applicationPoll) {
    window.clearInterval(state.applicationPoll.timer);
    state.applicationPoll = null;
  }
}
