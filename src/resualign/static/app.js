/* ResuAlign workbench frontend (ES module, no build step). */

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const JOB_FUNCTIONS = [
  "后端", "前端", "算法", "数据", "测试", "运维",
  "产品", "设计", "运营", "销售", "其他",
];
const SENIORITIES = ["初级", "中级", "高级", "资深", "未知"];
const JOB_STATUSES = ["未投递", "已投递", "面试中", "已拿Offer", "放弃"];
const DEFAULT_VOCABULARY = {
  job_functions: JOB_FUNCTIONS,
  seniorities: SENIORITIES,
  statuses: JOB_STATUSES,
};

let vocabularyRequest = null;
const APP_STATUSES = ["draft", "applied", "interview", "offer", "rejected", "withdrawn"];
const APP_STATUS_LABELS = {
  draft: "草稿",
  applied: "已投递",
  interview: "面试中",
  offer: "已拿Offer",
  rejected: "未通过",
  withdrawn: "已放弃",
};
const STAGE_LABELS = {
  queued: "排队中",
  running: "运行中",
  diagnose: "诊断简历",
  jd_profile: "提取JD画像",
  jd_analysis: "提取JD画像与差距分析",
  gap_analysis: "差距分析",
  tailoring: "AI 改写简历",
  evaluation: "LLM 评估",
};
const STAGE_WEIGHTS = {
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

const state = {
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
  wbCompareView: "side",
  wbAppraisal: null,
  wbFinalDraft: null,
  wbRawJdOpen: false,
  diagnosis: null,
  diagnosisPolling: null,
  diagnosisResumeId: null,
  settings: null,
  vocabulary: null,
  token: localStorage.getItem("resualign_token") || "",
};

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

function esc(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char],
  );
}

function toast(message, kind = "info") {
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

function formatDate(timestamp) {
  if (!timestamp) return "—";
  const date = new Date(timestamp * 1000);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
    date.getDate(),
  ).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(
    date.getMinutes(),
  ).padStart(2, "0")}`;
}

function formatSalary(job) {
  const min = job.salary_min;
  const max = job.salary_max;
  const unit = job.salary_currency || "CNY";
  if (min == null && max == null) return "薪资面议";
  if (min != null && max != null) return `${min / 1000}-${max / 1000}K`;
  return `${(min ?? max) / 1000}K`;
}

function options(values, selected) {
  return values
    .map(
      (value) =>
        `<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${esc(value)}</option>`,
    )
    .join("");
}

function normalizeVocabularyList(values, fallback) {
  if (!Array.isArray(values)) return [...fallback];
  const cleaned = values
    .map((value) => String(value ?? "").trim())
    .filter(Boolean);
  return cleaned.length ? cleaned : [...fallback];
}

function normalizeVocabulary(vocabulary) {
  const source = vocabulary && typeof vocabulary === "object" ? vocabulary : {};
  return {
    job_functions: normalizeVocabularyList(source.job_functions, JOB_FUNCTIONS),
    seniorities: normalizeVocabularyList(source.seniorities, SENIORITIES),
    statuses: normalizeVocabularyList(source.statuses, JOB_STATUSES),
  };
}

function vocabularyList(key) {
  return normalizeVocabularyList(
    state.vocabulary && state.vocabulary[key],
    DEFAULT_VOCABULARY[key],
  );
}

async function ensureVocabulary() {
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

function download(filename, content, mime) {
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

async function printTarget(kind) {
  let root = $("#print-root");
  if (!root) {
    root = document.createElement("div");
    root.id = "print-root";
    document.body.append(root);
  }
  root.innerHTML = "";
  if (kind === "resume") {
    const titleNode = document.querySelector(".page-header h2");
    const heading = document.createElement("h1");
    heading.textContent = titleNode ? titleNode.textContent : "简历";
    root.append(heading);
    const doc = document.querySelector(".resume-doc");
    if (doc) root.append(doc.cloneNode(true));
  } else if (kind === "workbench") {
    const prevView = state.wbCompareView;
    if (prevView !== "side") {
      state.wbCompareView = "side";
      await renderWbResult($("#app"));
    }
    const panel = $("[data-wb-result]");
    if (panel) {
      const clone = panel.cloneNode(true);
      clone
        .querySelectorAll("button, [data-action]")
        .forEach((node) => node.remove());
      root.append(clone);
    }
    const finalPanel = $("[data-final-draft-panel]");
    if (finalPanel) {
      const clone = finalPanel.cloneNode(true);
      clone
        .querySelectorAll("button, [data-action], input, select, textarea")
        .forEach((node) => node.remove());
      root.append(clone);
    }
    if (prevView !== "side") {
      state.wbCompareView = prevView;
      await renderWbResult($("#app"));
    }
  } else if (kind === "final-draft") {
    const job = state.wbJob || {};
    const heading = document.createElement("h1");
    heading.textContent = job.title || "定稿简历";
    root.append(heading);
    const panel = $("[data-final-draft-panel]");
    if (panel) {
      const clone = panel.cloneNode(true);
      clone
        .querySelectorAll("button, [data-action], input, select, textarea")
        .forEach((node) => node.remove());
      root.append(clone);
    }
  } else if (kind === "diagnosis") {
    const titleNode = document.querySelector(".page-header h2");
    const heading = document.createElement("h1");
    heading.textContent = titleNode ? titleNode.textContent : "简历诊断";
    root.append(heading);
    const panel = $("[data-diagnosis-panel]");
    if (panel) {
      const clone = panel.cloneNode(true);
      clone
        .querySelectorAll("button, [data-action], input, select, textarea")
        .forEach((node) => node.remove());
      root.append(clone);
    }
    const doc = document.querySelector(".resume-doc");
    if (doc) root.append(doc.cloneNode(true));
  }
  window.print();
}

function lineDiff(original, proposed) {
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

/* ------------------------------------------------------------------ */
/* API                                                                */
/* ------------------------------------------------------------------ */

async function api(path, options = {}) {
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

/* ------------------------------------------------------------------ */
/* Routing                                                             */
/* ------------------------------------------------------------------ */

const ROUTE_NAMES = ["resume", "jobs", "workspace", "settings"];
const ROUTE_LABELS = {
  resume: "简历中心",
  jobs: "岗位库",
  workspace: "工作台",
  settings: "设置",
};

function parseHash() {
  const hash = window.location.hash.replace(/^#\/?/, "");
  const parts = hash.split("/").filter(Boolean);
  if (parts[0] === "workspace" && parts[1]) {
    let jobId = parts[1];
    try {
      jobId = decodeURIComponent(jobId);
    } catch {
      /* keep raw value */
    }
    return { name: "workspace", jobId };
  }
  if (parts[0] === "resume" && parts[1]) {
    let resumeId = parts[1];
    try {
      resumeId = decodeURIComponent(resumeId);
    } catch {
      /* keep raw value */
    }
    return { name: "resume", jobId: null, resumeId };
  }
  const name = ROUTE_NAMES.includes(parts[0]) ? parts[0] : "resume";
  return { name, jobId: null, resumeId: null };
}

function navigate(name, id = null) {
  if (name === "workspace" && id) {
    window.location.hash = `#/workspace/${encodeURIComponent(id)}`;
  } else if (name === "resume" && id) {
    window.location.hash = `#/resume/${encodeURIComponent(id)}`;
  } else {
    window.location.hash = `#/${name}`;
  }
}

function setActiveTab() {
  $$(".tabs button").forEach((button) => {
    const selected = button.dataset.route === state.route.name;
    button.setAttribute("aria-selected", String(selected));
    button.classList.toggle("active", selected);
  });
}

async function render() {
  state.route = parseHash();
  setActiveTab();
  stopWbPolling();
  stopApplicationPolling();
  stopDiagnosisPolling();
  const app = $("#app");
  const printNode = $("#print-root");
  if (printNode) printNode.innerHTML = "";
  app.innerHTML = `<div class="skeleton is-shimmer">加载中...</div>`;
  try {
    if (state.route.name === "resume" && state.route.resumeId) {
      await renderResumeDetailView(app, state.route.resumeId);
    } else if (state.route.name === "resume") await renderResumeView(app);
    else if (state.route.name === "jobs") await renderJobsView(app);
    else if (state.route.name === "workspace") await renderWorkspaceView(app);
    else await renderSettingsView(app);
  } catch (error) {
    app.innerHTML = `<div class="panel"><h3>出错了</h3><p class="muted">${esc(error.message)}</p>
      <div class="row" style="margin-top:12px"><button class="btn btn-primary" data-action="reload">重试</button></div></div>`;
  }
}

/* ------------------------------------------------------------------ */
/* Resume Center                                                       */
/* ------------------------------------------------------------------ */

async function renderResumeView(app) {
  state.resumes = await api("/api/master-resumes");
  const hasResumes = state.resumes.length > 0;
  const cards = state.resumes
    .map(
      (resume) => `
      <div class="card resume-card card-base card-hover-soft">
        <div class="card-head">
          <div>
            <div class="card-title">${esc(resume.title)}</div>
            <div class="card-meta">更新于 ${formatDate(resume.updated_at)} · v${resume.current_version}</div>
          </div>
          <span class="badge badge-teal">当前版本 v${resume.current_version}</span>
        </div>
        <div class="pre" style="max-height:160px">${esc(resume.content)}</div>
        <div class="row" style="margin-top:10px">
          <button class="btn btn-primary btn-sm" data-action="open-resume-archive" data-id="${resume.resume_id}">查看档案</button>
          <button class="btn btn-outline btn-sm" data-action="edit-resume" data-id="${resume.resume_id}">编辑</button>
          <button class="btn btn-danger btn-sm" data-action="delete-resume" data-id="${resume.resume_id}">删除</button>
        </div>
      </div>`,
    )
    .join("");

  app.innerHTML = `
    <div class="page-header page-header--resume">
      <div>
        <h2>简历中心</h2>
        <div class="sub">维护主简历与版本历史，工作台始终基于当前版本生成对齐稿</div>
      </div>
      <div class="row">
        <button class="btn btn-primary" data-action="new-resume">新建主简历</button>
        <button class="btn btn-outline" data-action="upload-resume">上传简历文件</button>
        <input type="file" id="resume-upload-input" accept=".pdf,.docx,.txt" hidden>
      </div>
    </div>
    <form class="panel panel-card" data-form="resume-create" hidden>
      <h3>新建主简历</h3>
      <div class="form-grid">
        <div class="field"><label>标题</label><input type="text" name="title" required placeholder="例如：2026 后端大厂版"></div>
        <div class="field"></div>
        <div class="field wide"><label>简历内容（Markdown）</label>
          <textarea name="content" rows="10" required placeholder="个人信息、工作经历、项目经历..."></textarea></div>
      </div>
      <div class="row"><button class="btn btn-primary" type="submit">保存</button>
        <button class="btn btn-ghost" type="button" data-action="cancel-new-resume">取消</button></div>
    </form>
    <div id="resume-list" class="card-list motion-stagger">${hasResumes ? cards : `
      <div class="panel panel-card empty-state">
        <div class="big">还没有主简历</div>
        <div>先创建一份主简历，工作台才能生成对齐版本。</div>
        <div class="actions"><button class="btn btn-primary" data-action="new-resume">新建主简历</button></div>
      </div>`}
    </div>`;
}

async function renderResumeDetailView(app, resumeId) {
  const resume = await api(`/api/master-resumes/${encodeURIComponent(resumeId)}`);
  const versions = resume.versions || [];
  const versionCards = versions
    .map((version, index) => {
      const previous = versions[index - 1];
      const diffRows = previous
        ? lineDiff(previous.content, version.content)
        : [{ type: "add", text: "初始版本" }];
      const diffHtml =
        diffRows
          .map(
            (row) =>
              `<div class="diff-line ${row.type === "add" ? "diff-add" : "diff-remove"}">${
                row.type === "add" ? "+" : "-"
              } ${esc(row.text)}</div>`,
          )
          .join("") || `<div class="muted small">内容未变化</div>`;
      return `
        <div class="card version-card card-base card-hover-soft">
          <div class="card-head">
            <div class="card-title">v${version.version}</div>
            <span class="badge ${version.version === resume.current_version ? "badge-green" : "badge-gray"}">${
              version.version === resume.current_version ? "当前" : "历史"
            }</span>
          </div>
          <div class="card-meta">创建于 ${formatDate(version.created_at)}</div>
          <div style="margin:8px 0">${diffHtml}</div>
          ${version.version !== resume.current_version
            ? `<button class="btn btn-outline btn-sm" data-action="rollback-resume" data-id="${resumeId}" data-version="${version.version}">回滚到 v${version.version}</button>`
            : ""}
        </div>`;
    })
    .join("");

  app.innerHTML = `
    <div class="page-header page-header--resume">
      <div>
        <button class="btn btn-ghost btn-sm" data-action="back-resume-center">← 返回简历中心</button>
        <h2 style="margin-top:6px">${esc(resume.title)}</h2>
        <div class="sub">更新于 ${formatDate(resume.updated_at)} · 当前版本 v${resume.current_version} · 共 ${versions.length} 个版本</div>
      </div>
      <div class="row">
        <button class="btn btn-primary btn-sm" data-action="diagnose-resume" data-id="${resume.resume_id}">诊断简历</button>
        <button class="btn btn-primary btn-sm" data-action="print-resume">导出 PDF</button>
        <button class="btn btn-secondary btn-sm" data-action="export-resume-md" data-id="${resume.resume_id}">导出 Markdown</button>
        <button class="btn btn-outline btn-sm" data-action="edit-resume" data-id="${resume.resume_id}">编辑</button>
        <button class="btn btn-danger btn-sm" data-action="delete-resume" data-id="${resume.resume_id}">删除</button>
      </div>
    </div>
    <section class="panel panel-card panel--teal diagnosis-panel" data-diagnosis-panel>
      <div class="diagnosis-head">
        <div>
          <h3>简历诊断</h3>
          <div class="small muted" data-diagnosis-meta>尚未诊断</div>
        </div>
        <div class="row">
          <button class="btn btn-outline btn-sm" data-action="export-diagnosis" hidden>导出 PDF</button>
          <button class="btn btn-secondary btn-sm" data-action="export-diagnosis-md" hidden>导出 Markdown</button>
        </div>
      </div>
      <div class="progress-wrap" data-diagnosis-progress hidden>
        <div class="progress-track"><div class="progress-fill" data-diagnosis-fill style="width:5%"></div></div>
        <span class="small" data-diagnosis-stage>排队中</span>
        <span class="small muted" data-diagnosis-elapsed>0s</span>
        <button class="btn btn-ghost btn-sm" type="button" data-action="cancel-diagnosis" hidden>取消任务</button>
      </div>
      <div data-diagnosis-result hidden></div>
      <div class="form-error" data-diagnosis-error hidden></div>
    </section>
    <div class="resume-archive-grid">
      <section class="panel panel-card">
        <h3>完整简历</h3>
        <div class="resume-doc">${renderMarkdown(resume.content)}</div>
      </section>
      <section class="panel panel-card">
        <h3>版本历史</h3>
        <div class="card-list motion-stagger">${versionCards || `<div class="muted small">暂无版本</div>`}</div>
      </section>
    </div>`;
  state.diagnosisResumeId = resumeId;
  await recoverDiagnosis(resume);
}

async function recoverDiagnosis(resume) {
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

function startDiagnosisPolling(jobId, resumeId) {
  stopDiagnosisPolling();
  state.diagnosisResumeId = resumeId || state.diagnosisResumeId;
  state.diagnosisPolling = {
    jobId,
    timer: window.setInterval(() => pollDiagnosisJob(jobId), 1000),
  };
  pollDiagnosisJob(jobId);
}

function stopDiagnosisPolling() {
  if (state.diagnosisPolling) {
    window.clearInterval(state.diagnosisPolling.timer);
    state.diagnosisPolling = null;
  }
}

async function pollDiagnosisJob(jobId) {
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

function renderDiagnosisIdle() {
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

function renderDiagnosisProgress(snapshot) {
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

function renderDiagnosisResult(snapshot) {
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

function renderDiagnosisError(snapshot) {
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

function buildDiagnosisMarkdown(originalContent = "") {
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

function inlineMarkdown(text) {
  return text
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function renderMarkdown(text) {
  const html = [];
  let listOpen = false;
  const closeList = () => {
    if (listOpen) {
      html.push("</ul>");
      listOpen = false;
    }
  };
  for (const raw of String(text || "").split("\n")) {
    const line = esc(raw);
    const trimmed = line.trim();
    if (!trimmed) {
      closeList();
      continue;
    }
    const heading = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      closeList();
      const level = heading[1].length;
      html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    const listItem = trimmed.match(/^[-*•]\s+(.*)$/);
    if (listItem) {
      if (!listOpen) {
        html.push("<ul>");
        listOpen = true;
      }
      html.push(`<li>${inlineMarkdown(listItem[1])}</li>`);
      continue;
    }
    closeList();
    html.push(`<p>${inlineMarkdown(trimmed)}</p>`);
  }
  closeList();
  return html.join("");
}

async function openResumeEditor(resumeId) {
  let resume = state.resumes.find((item) => item.resume_id === resumeId);
  if (!resume) {
    try {
      resume = await api(`/api/master-resumes/${encodeURIComponent(resumeId)}`);
    } catch {
      toast("简历不存在或已删除", "error");
      return;
    }
  }
  if (!resume) return;
  showModal(
    `编辑「${resume.title}」`,
    `<form data-form="resume-edit">
      <input type="hidden" name="resume_id" value="${resume.resume_id}">
      <div class="field"><label>简历内容（Markdown）</label>
        <textarea name="content" rows="16" required>${esc(resume.content)}</textarea></div>
      <div class="actions"><button class="btn btn-ghost" type="button" data-action="close-modal">取消</button>
        <button class="btn btn-primary" type="submit">保存新版本</button></div>
    </form>`,
  );
}

/* ------------------------------------------------------------------ */
/* Job Library                                                         */
/* ------------------------------------------------------------------ */

async function renderJobsView(app) {
  const query = new URLSearchParams({
    ...state.filters,
    limit: String(state.limit),
    offset: String(state.offset),
  });
  for (const key of ["job_function", "seniority", "status", "search"]) {
    if (!state.filters[key]) query.delete(key);
  }
  state.jobs = await api(`/api/jobs?${query}`);
  const vocabulary = await ensureVocabulary();
  const cards = state.jobs
    .map(
      (job) => `
      <div class="card job-card ${job.classification_pending ? "job-card--pending" : ""} card-base card-hover-soft">
        <div class="card-head">
          <div>
            <div class="card-title">${esc(job.title)}</div>
            <div class="card-meta">${esc(job.company || "未知公司")} · ${esc(job.location || "未知城市")} · ${formatSalary(job)}</div>
          </div>
          <span class="badge badge-blue">${esc(job.job_function || "未分类")}</span>
        </div>
        <div class="row" style="margin-top:8px">
          <span class="badge badge-gray">${esc(job.seniority || "未知")}</span>
          ${job.classification_pending ? '<span class="badge badge-amber badge-pending">分类待定</span>' : ""}
          <span class="badge ${job.status === "未投递" ? "badge-amber" : "badge-teal"}">${esc(job.status)}</span>
          ${job.classification_pending ? `<button class="btn btn-ghost btn-sm" data-action="reclassify-job" data-id="${job.job_id}">重新分类</button>` : ""}
        </div>
        <div class="chips">${(job.tech_tags || [])
          .map((tag) => `<span class="chip">${esc(tag)}</span>`)
          .join("")}</div>
        <details class="drawer job-raw-jd" data-raw-jd="${job.job_id}">
          <summary class="small">查看原始 JD</summary>
          <div class="pre raw-jd">${esc(job.jd_text)}</div>
        </details>
        <div class="row" style="margin-top:10px">
          <button class="btn btn-primary btn-sm" data-action="open-workspace" data-id="${job.job_id}">打开工作台</button>
          <button class="btn btn-outline btn-sm" data-action="edit-job" data-id="${job.job_id}">编辑</button>
          <button class="btn btn-danger btn-sm" data-action="delete-job" data-id="${job.job_id}">删除</button>
        </div>
      </div>`,
    )
    .join("");

  app.innerHTML = `
    <div class="page-header page-header--jobs">
      <div>
        <h2>岗位库</h2>
        <div class="sub">共 ${state.jobs.length} 条（当前页） · 粘贴或导入 JD，分类后进入工作台</div>
      </div>
      <div class="row">
        <button class="btn btn-primary" data-action="show-add-job">添加岗位</button>
        <button class="btn btn-outline" data-action="show-import">批量导入</button>
      </div>
    </div>
    <form class="panel panel-card filter-bar" data-form="job-filter">
      <div class="field"><label>职能</label><select name="job_function"><option value="">全部</option>${options(vocabulary.job_functions, state.filters.job_function)}</select></div>
      <div class="field"><label>级别</label><select name="seniority"><option value="">全部</option>${options(vocabulary.seniorities, state.filters.seniority)}</select></div>
      <div class="field"><label>状态</label><select name="status"><option value="">全部</option>${options(vocabulary.statuses, state.filters.status)}</select></div>
      <div class="field"><label>搜索</label><input type="search" name="search" value="${esc(state.filters.search)}" placeholder="标题 / 公司 / JD"></div>
      <button class="btn btn-secondary" type="submit">筛选</button>
      <button class="btn btn-ghost" type="button" data-action="clear-filters">清空</button>
    </form>
    <form class="panel panel-card" data-form="job-create" hidden>
      <h3>添加岗位</h3>
      <div class="segmented segmented-card" role="group" aria-label="输入方式">
        <button type="button" class="segmented-button" data-mode="paste" aria-pressed="true">粘贴 JD</button>
        <button type="button" class="segmented-button" data-mode="url" aria-pressed="false">JD 链接</button>
      </div>
      <div class="form-grid" style="margin-top:10px">
        <div class="field"><label>标题</label><input type="text" name="title" placeholder="留空则从 JD 首行提取"></div>
        <div class="field"><label>公司</label><input type="text" name="company"></div>
        <div class="field"><label>城市</label><input type="text" name="location"></div>
        <div class="field"><label>来源链接</label><input type="url" name="source_url"></div>
        <div class="field"><label>最低薪资（月，元）</label><input type="number" name="salary_min" min="0" step="100"></div>
        <div class="field"><label>最高薪资（月，元）</label><input type="number" name="salary_max" min="0" step="100"></div>
        <div class="field"><label>薪资币种</label><input type="text" name="salary_currency" placeholder="CNY"></div>
        <div class="field wide"><label>JD 文本</label><textarea name="jd_text" rows="8"></textarea></div>
        <div class="field wide" data-url-field hidden><label>JD 链接</label>
          <div class="row">
            <input type="url" name="jd_url" placeholder="https://..." style="flex:1;min-width:0">
            <button class="btn btn-secondary" type="button" data-action="parse-jd-link">解析 JD 链接</button>
          </div>
        </div>
        <div class="jd-parse-status" data-jd-parse-status role="status" aria-live="polite"></div>
      </div>
      <div class="row"><button class="btn btn-primary" type="submit">保存岗位</button>
        <button class="btn btn-ghost" type="button" data-action="cancel-add-job">取消</button></div>
    </form>
    <form class="panel panel-card" data-form="job-import" hidden>
      <h3>批量导入</h3>
      <div class="field"><label>粘贴 CSV 或 JSON 数组（字段含 title / jd_text / jd_url / company / location）</label>
        <textarea name="import_text" rows="6" placeholder='title,jd_text,location&#10;后端工程师,要求 Python 和 FastAPI,上海'></textarea></div>
      <div class="field"><label>或选择文件（.csv / .json）</label><input type="file" name="import_file" accept=".csv,.json,text/csv,application/json"></div>
      <div class="row"><button class="btn btn-primary" type="submit">开始导入</button>
        <button class="btn btn-ghost" type="button" data-action="cancel-import">取消</button>
        <span class="small muted" data-import-status></span></div>
    </form>
    <div id="job-list" class="card-list motion-stagger">${cards || `<div class="panel panel-card empty-state">
      <div class="big">岗位库为空</div>
      <div>添加或批量导入岗位后，即可在单岗位工作台做对齐分析。</div>
      <div class="actions"><button class="btn btn-primary" data-action="show-add-job">添加岗位</button>
      <button class="btn btn-outline" data-action="show-import">批量导入</button></div></div>`}
    </div>
    <div class="row" style="justify-content:center;margin-top:12px">
      <button class="btn btn-outline btn-sm" data-action="prev-page" ${state.offset === 0 ? "disabled" : ""}>上一页</button>
      <span class="small muted">${state.offset / state.limit + 1} 页</span>
      <button class="btn btn-outline btn-sm" data-action="next-page" ${state.jobs.length < state.limit ? "disabled" : ""}>下一页</button>
    </div>`;
}

function openJobEditor(job) {
  showModal(
    `编辑「${job.title}」`,
    `<form data-form="job-edit">
      <input type="hidden" name="job_id" value="${job.job_id}">
      <div class="form-grid">
        <div class="field"><label>标题</label><input type="text" name="title" value="${esc(job.title)}"></div>
        <div class="field"><label>公司</label><input type="text" name="company" value="${esc(job.company || "")}"></div>
        <div class="field"><label>城市</label><input type="text" name="location" value="${esc(job.location || "")}"></div>
        <div class="field"><label>状态</label><select name="status">${options(vocabularyList("statuses"), job.status)}</select></div>
        <div class="field"><label>职能</label><select name="job_function"><option value="">未分类</option>${options(vocabularyList("job_functions"), job.job_function || "")}</select></div>
        <div class="field"><label>级别</label><select name="seniority"><option value="">未知</option>${options(vocabularyList("seniorities"), job.seniority || "")}</select></div>
        <div class="field"><label>最低薪资（月，元）</label><input type="number" name="salary_min" value="${job.salary_min ?? ""}"></div>
        <div class="field"><label>最高薪资（月，元）</label><input type="number" name="salary_max" value="${job.salary_max ?? ""}"></div>
        <div class="field wide"><label>技术标签（逗号分隔）</label><input type="text" name="tech_tags" value="${esc((job.tech_tags || []).join(", "))}"></div>
        <div class="field wide"><label>JD 文本</label><textarea name="jd_text" rows="8">${esc(job.jd_text)}</textarea></div>
      </div>
      <div class="actions"><button class="btn btn-ghost" type="button" data-action="close-modal">取消</button>
        <button class="btn btn-primary" type="submit">保存</button></div>
    </form>`,
  );
}

/* ------------------------------------------------------------------ */
/* Workspace                                                           */
/* ------------------------------------------------------------------ */

async function renderWorkspaceView(app) {
  const [jobs, resumes, applications] = await Promise.all([
    api("/api/jobs?limit=200"),
    api("/api/master-resumes"),
    api("/api/applications"),
    ensureVocabulary(),
  ]);
  state.wbResumes = resumes;
  state.wbApplications = applications;

  let job = state.route.jobId ? state.wbJob : null;
  if (state.route.jobId && (!job || job.job_id !== state.route.jobId)) {
    try {
      job = await api(`/api/jobs/${encodeURIComponent(state.route.jobId)}`);
    } catch (error) {
      job = null;
    }
  }
  if (state.route.jobId && job && job.job_id !== state.route.jobId) {
    state.route.jobId = job.job_id;
  }
  state.wbJob = job;
  state.wbFinalDraft =
    job && job.final_draft
      ? {
          draft: job.final_draft,
          version: job.final_draft_version || 1,
          updated_at: job.final_draft_updated_at,
        }
      : null;

  if (!job) {
    app.innerHTML = `
      <div class="page-header page-header--workspace"><div><h2>单岗位工作台</h2>
        <div class="sub">选择一个岗位，对比主简历并生成对齐版本</div></div></div>
      <div class="panel panel-card">
        <div class="field"><label>选择岗位</label>
          <select data-wb-job-select>
            <option value="">${jobs.length ? "选择岗位..." : "岗位库为空，先到岗位库添加"}</option>
            ${jobs.map((item) => `<option value="${item.job_id}">${esc(item.title)} · ${esc(item.company || "")}</option>`).join("")}
          </select></div>
        ${jobs.length ? '<div class="row"><button class="btn btn-primary" data-action="goto-selected-job">进入工作台</button></div>' : `
          <div class="row"><a href="#/jobs" class="btn btn-primary">去岗位库添加</a></div>`}
      </div>
      <div data-applications-panel></div>`;
    renderApplicationsPanel(app);
    return;
  }

  const appraisal = state.wbAppraisal && state.wbAppraisal.job_id === job.job_id
    ? state.wbAppraisal
    : null;
  const savedGranularity = job.tailor_granularity || "medium";
  const savedFocus = job.tailor_focus || "balanced";
  const savedPrompt = job.custom_prompt || "";
  app.innerHTML = `
    <div class="page-header page-header--workspace">
      <div>
        <h2>${esc(job.title)}</h2>
        <div class="sub">${esc(job.company || "未知公司")} · ${esc(job.location || "未知城市")} · ${formatSalary(job)} · ${esc(job.status)}</div>
      </div>
      <div class="row">
        <button class="btn btn-outline" data-action="toggle-raw-jd">${state.wbRawJdOpen ? "收起原始 JD" : "查看原始 JD"}</button>
        <button class="btn btn-ghost" data-action="back-workspace">换一个岗位</button>
      </div>
    </div>
    ${state.wbRawJdOpen ? `<div class="panel panel-card"><h3>原始 JD</h3><div class="pre raw-jd">${esc(job.jd_text)}</div></div>` : ""}
    <div class="grid-2">
      <div class="stack">
        <form class="panel panel-card" data-form="wb-run">
          <h3>对齐调优</h3>
          <div class="field"><label>选择主简历</label>
            <select name="master_resume_id" required>
              <option value="">${resumes.length ? "选择简历..." : "先到简历中心创建主简历"}</option>
              ${resumes.map((resume) => `<option value="${resume.resume_id}">${esc(resume.title)}（v${resume.current_version}）</option>`).join("")}
            </select></div>
          <div class="field"><label>改写颗粒度</label>
            <div class="segmented segmented-card" role="group" aria-label="改写颗粒度">
              <button type="button" class="segmented-button" data-granularity="fine" aria-pressed="${savedGranularity === "fine"}">微调</button>
              <button type="button" class="segmented-button" data-granularity="medium" aria-pressed="${savedGranularity === "medium"}">重构</button>
              <button type="button" class="segmented-button" data-granularity="coarse" aria-pressed="${savedGranularity === "coarse"}">重塑</button>
            </div>
            <div class="small muted">
              <div>微调：只改不匹配 JD 的条目</div>
              <div>重构：保持结构自由改写</div>
              <div>重塑：重排合并条目</div>
            </div>
          </div>
          <div class="field"><label>Prompt 聚焦策略</label>
            <div class="segmented segmented-card" role="group" aria-label="Prompt 聚焦策略">
              <button type="button" class="segmented-button" data-focus="balanced" aria-pressed="${savedFocus === "balanced"}">均衡</button>
              <button type="button" class="segmented-button" data-focus="quantified" aria-pressed="${savedFocus === "quantified"}">量化数据</button>
              <button type="button" class="segmented-button" data-focus="skills" aria-pressed="${savedFocus === "skills"}">技能匹配</button>
            </div></div>
          <div class="field"><label>自定义补充要求（可选）</label>
            <textarea name="custom_prompt" rows="2" placeholder="例如：强调高并发缓存场景、突出量化结果">${esc(savedPrompt)}</textarea></div>
          <div class="row">
            <button class="btn btn-primary" type="submit" data-wb-run>一键生成对齐简历</button>
            <button class="btn btn-danger" type="button" data-action="cancel-workbench" data-wb-cancel hidden>取消任务</button>
          </div>
        </form>
        <div class="panel panel-card" data-wb-progress-panel hidden>
          <h3>运行进度</h3>
          <div class="progress-wrap">
            <div class="progress-track"><div class="progress-fill" data-wb-progress-fill style="width:5%"></div></div>
            <span class="small muted" data-wb-elapsed>0s</span>
          </div>
          <div class="small"><strong data-wb-stage>排队中</strong> · <span class="muted" data-wb-message></span></div>
        </div>
        <div class="panel panel-card panel--info" data-wb-result hidden></div>
        <div class="panel panel-card panel--success final-draft-panel" data-final-draft-panel hidden></div>
      </div>
      <div class="stack">
        <div class="panel panel-card panel--info appraisal-panel" data-appraisal-panel>
          <h3>投递价值评估</h3>
          <div class="muted small">运行一次对齐分析后生成</div>
        </div>
        <div class="panel panel-card">
          <h3>岗位状态</h3>
          <div class="row">
            <select data-job-status>${options(vocabularyList("statuses"), job.status)}</select>
            <button class="btn btn-secondary btn-sm" data-action="update-job-status" data-id="${job.job_id}">保存</button>
          </div>
        </div>
        <div data-applications-panel></div>
      </div>
    </div>`;
  renderApplicationsPanel(app);
  renderFinalDraftPanel(app);

  const savedJob = state.wbJob;
  if (savedJob && savedJob.workbench_job_id) {
    try {
      const snapshot = await api(
        `/api/jobs/${encodeURIComponent(savedJob.workbench_job_id)}`,
      );
      if (
        snapshot.status === "succeeded" ||
        snapshot.status === "failed" ||
        snapshot.status === "canceled"
      ) {
        if (snapshot.status === "succeeded") {
          state.wbResult = snapshot.result;
          renderWbResult(app);
          await renderAppraisal(app);
        } else {
          renderWbError(app, snapshot);
        }
      } else if (
        snapshot.status === "queued" ||
        snapshot.status === "running"
      ) {
        startWbPolling(savedJob.workbench_job_id, app);
      }
    } catch {
      /* expired or missing analysis job; leave the workspace idle */
    }
  } else if (state.wbResult) {
    renderWbResult(app);
    await renderAppraisal(app);
  }
  renderFinalDraftPanel(app);
}

async function refreshWbJob(app = $("#app")) {
  if (!state.wbJob) return;
  state.wbJob = await api(`/api/jobs/${encodeURIComponent(state.wbJob.job_id)}`);
  state.wbResult = null;
  state.wbAppraisal = null;
  await renderWorkspaceView(app);
}

function startWbPolling(jobId, app = $("#app")) {
  stopWbPolling();
  state.wbPolling = { jobId, app, timer: window.setInterval(() => pollWbJob(jobId), 1000) };
  pollWbJob(jobId);
}

function stopWbPolling() {
  if (state.wbPolling) {
    window.clearInterval(state.wbPolling.timer);
    state.wbPolling = null;
  }
}

function stopApplicationPolling() {
  if (state.applicationPoll) {
    window.clearInterval(state.applicationPoll.timer);
    state.applicationPoll = null;
  }
}

async function pollWbJob(jobId) {
  if (!state.wbPolling || state.wbPolling.jobId !== jobId) return;
  try {
    const snapshot = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    if (!state.wbPolling || state.wbPolling.jobId !== jobId) return;
    renderWbProgress(snapshot);
    if (["succeeded", "failed", "canceled"].includes(snapshot.status)) {
      const app = state.wbPolling ? state.wbPolling.app : $("#app");
      stopWbPolling();
      if (snapshot.status === "succeeded") {
        state.wbResult = snapshot.result;
        renderWbResult(app);
        await renderAppraisal(app);
        if (state.wbJob) {
          try {
            state.wbJob = await api(
              `/api/jobs/${encodeURIComponent(state.wbJob.job_id)}`,
            );
          } catch {
            /* keep the current job object */
          }
        }
      } else {
        renderWbError(app, snapshot);
      }
    }
  } catch (error) {
    stopWbPolling();
    toast(error.message, "error");
  }
}

function renderWbProgress(snapshot) {
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

async function renderWbResult(app) {
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

  const originalHtml =
    String(originalText)
      .split("\n")
      .map((line) => {
        const trimmed = line.trim();
        const changed = removedLines.has(trimmed);
        const modified = modifyOriginal.has(trimmed);
        const removeIdx = removeIndex.get(trimmed);
        const keepCheckbox =
          removeIdx !== undefined
            ? `<label class="cmp-check"><input type="checkbox" data-accept-diff="${removeIdx}" ${accepted.has(removeIdx) ? "" : "checked"} aria-label="采纳此条"><span class="small">采纳</span></label>`
            : "";
        return `<div class="cmp-line ${modified ? "diff-modify" : changed ? "diff-remove" : ""}">${
          modified || changed ? "− " : ""
        }${keepCheckbox}${esc(line)}</div>`;
      })
      .join("") ||
    `<div class="muted small">原版内容不可用，可在修改列表查看逐条差异</div>`;

  const optimizedHtml =
    optimizedText
      .split("\n")
      .map((line) => {
        const trimmed = line.trim();
        if (!trimmed) return `<div class="cmp-line">&nbsp;</div>`;
        const added = addedLines.has(trimmed);
        const modified = modifyProposed.has(trimmed);
        const changed = added || modified;
        const idx = proposedIndex.get(trimmed);
        const acceptCheckbox =
          idx !== undefined
            ? `<label class="cmp-check"><input type="checkbox" data-accept-diff="${idx}" ${accepted.has(idx) ? "" : "checked"} aria-label="采纳此条"><span class="small">采纳</span></label>`
            : "";
        const reason = reasonByLine.get(trimmed) || "针对 JD 优化";
        return `<div class="cmp-line ${modified ? "diff-modify" : added ? "diff-add" : ""}">${acceptCheckbox}${
          changed
            ? `<span class="opt-badge" tabindex="0" role="button" aria-label="查看优化说明">已优化</span><span class="opt-bubble" hidden>${esc(reason)}</span>`
            : ""
        }${esc(line)}</div>`
          ;
      })
      .join("") || `<div class="muted small">暂无优化内容</div>`;

  const sideView = `
    <div class="cmp-grid cmp-grid--workbench">
      <section class="cmp-column-wrap">
        <h4>原版</h4>
      <div class="cmp-column motion-stagger">${originalHtml}</div>
      </section>
      <section class="cmp-column-wrap">
        <h4>优化版</h4>
      <div class="cmp-column motion-stagger">${optimizedHtml}</div>
      </section>
    </div>
    <div class="row" style="margin-top:10px"><button class="btn btn-primary" data-action="accept-diffs">采纳选中修改</button></div>`;

  const listView = diffs.length
    ? `<h4>修改项（${diffs.length}）</h4>
      <div class="card-list motion-stagger">
        ${diffs.map((diff, index) => `
          <div class="card diff-card card-base card-hover-soft">
            <label class="row" style="align-items:flex-start">
              <input type="checkbox" data-accept-diff="${index}" ${accepted.has(index) ? "" : "checked"}>
              <span>
                <span class="badge badge-${diff.type === "add" ? "green" : diff.type === "remove" ? "red" : "blue"}">${esc(diff.type)}</span>
                <span class="small muted">${esc(diff.reason || "")}</span>
              </span>
            </label>
            ${diff.type !== "add" ? `<div class="diff-line diff-remove">- ${esc(diff.original)}</div>` : ""}
            ${diff.type !== "remove" ? `<div class="diff-line diff-add">+ ${esc(diff.proposed)}</div>` : ""}
          </div>`).join("")}
      </div>
      <div class="row" style="margin-top:10px"><button class="btn btn-primary" data-action="accept-diffs">采纳选中修改</button></div>`
    : `<div class="muted small">无修改项</div>`;

  panel.innerHTML = `
    <h3>对齐结果 · 诊断分 ${result.score ?? "—"}</h3>
    <div class="row">
      <button class="btn btn-primary btn-sm" data-action="print-workbench">导出 PDF</button>
      <button class="btn btn-secondary btn-sm" data-action="export-markdown">导出 Markdown</button>
      <button class="btn btn-outline btn-sm" data-action="export-json">导出 JSON</button>
    </div>
    <div class="segmented segmented-card" role="group" aria-label="结果视图">
      <button type="button" class="segmented-button" data-action="toggle-wb-view" data-wb-view="side" aria-pressed="${state.wbCompareView === "side"}">并排对比</button>
      <button type="button" class="segmented-button" data-action="toggle-wb-view" data-wb-view="list" aria-pressed="${state.wbCompareView === "list"}">修改列表</button>
    </div>
    ${state.wbCompareView === "side" ? sideView : listView}
    <div data-accept-result></div>`;
}

function renderWbError(app, snapshot) {
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

function renderFinalDraftPanel(app) {
  const panel = $("[data-final-draft-panel]");
  if (!panel) return;
  const draft = state.wbFinalDraft;
  if (!draft || !draft.draft) {
    panel.hidden = true;
    panel.innerHTML = "";
    return;
  }
  panel.hidden = false;
  panel.innerHTML = `
    <div class="final-draft-head">
      <div>
        <h3>定稿简历</h3>
        <div class="draft-meta">
          <span class="badge badge-green">已保存</span>
          <span class="small muted">${formatDate(draft.updated_at)} · 第 ${draft.version} 版</span>
        </div>
      </div>
    </div>
    <div class="pre draft-preview">${esc(draft.draft)}</div>
    <div class="row final-draft-actions">
      <button class="btn btn-outline btn-sm" data-action="export-final-draft">导出 PDF</button>
      <button class="btn btn-outline btn-sm" data-action="export-final-draft-md">导出 Markdown</button>
      <button class="btn btn-secondary btn-sm" data-action="save-as-new-resume">另存为新主简历</button>
    </div>`;
}

function benchmarkSourceBadge(appraisal) {
  const source = appraisal.benchmark_source || "暂无基准";
  const city = appraisal.city_normalized;
  if (source === "设置表（城市）") {
    return {
      className: "badge-teal",
      label: city ? `设置表（${city}）` : "设置表（城市）",
      detail: city
        ? `基准来源：设置表（城市） · 城市归一化：${city}`
        : "基准来源：设置表（城市）",
    };
  }
  if (source === "库内同类中位") {
    return {
      className: "badge-gray",
      label: "库内同类中位",
      detail: "基准来源：库内同类中位",
    };
  }
  return {
    className: "badge-amber",
    label: "暂无基准，中性处理",
    detail: "基准来源：暂无基准",
  };
}

async function renderAppraisal(app) {
  const panel = $("[data-appraisal-panel]");
  if (!panel || !state.wbJob) return;
  try {
    const appraisal = await api(`/api/jobs/${encodeURIComponent(state.wbJob.job_id)}/appraisal`);
    state.wbAppraisal = { job_id: state.wbJob.job_id, ...appraisal };
    const verdictClass =
      appraisal.verdict === "投递" ? "badge-green" : appraisal.verdict === "考虑" ? "badge-amber" : "badge-red";
    const ringClass =
      appraisal.score >= 80
        ? "score-ring--high"
        : appraisal.score >= 60
          ? "score-ring--mid"
          : "score-ring--low";
    const benchmark = benchmarkSourceBadge(appraisal);
    panel.innerHTML = `
      <h3>投递价值评估</h3>
      <div class="appraisal-score">
        <div class="score-ring ${ringClass}" style="--score:${appraisal.score}"><span>${Math.round(appraisal.score)}</span></div>
        <div>
          <span class="badge ${verdictClass}">${esc(appraisal.verdict)}</span>
          <div class="small muted" style="margin-top:4px">综合评分 ${appraisal.score} / 100</div>
        </div>
      </div>
      <div class="components">
        ${Object.entries(appraisal.components || {}).map(([key, value]) => `
          <div class="component-box"><div class="label">${esc(key)}</div><div class="value">${esc(value)}</div></div>`).join("")}
      </div>
      <div class="benchmark-source">
        <span class="badge ${benchmark.className}">${esc(benchmark.label)}</span>
        <span class="small muted">${esc(benchmark.detail)}</span>
      </div>
      <ul style="margin:10px 0 0 18px">${(appraisal.reasons || []).map((reason) => `<li class="small">${esc(reason)}</li>`).join("")}</ul>`;
  } catch (error) {
    panel.innerHTML = `<h3>投递价值评估</h3><p class="muted">${esc(error.message)}</p>`;
  }
}

function renderApplicationsPanel(app) {
  const panel = $("[data-applications-panel]", app);
  if (!panel) return;
  const apps = state.wbApplications || [];
  panel.innerHTML = `
        <div class="panel panel-card">
      <h3>投递记录</h3>
      <form data-form="application-create" class="drawer" style="margin-top:8px">
        <div class="form-grid">
          <div class="field"><label>标题</label><input type="text" name="title" required placeholder="例如：Acme 后端"></div>
          <div class="field"><label>主简历</label><select name="master_resume_id" required><option value="">选择简历</option>${state.wbResumes.map((resume) => `<option value="${resume.resume_id}">${esc(resume.title)}</option>`).join("")}</select></div>
          <div class="field wide"><label>JD 文本</label><textarea name="jd_text" rows="3"></textarea></div>
          <div class="field wide"><label>JD 链接</label><input type="url" name="jd_url"></div>
        </div>
        <div class="row"><button class="btn btn-secondary btn-sm" type="submit">创建投递记录</button></div>
      </form>
      <div class="card-list motion-stagger" style="margin-top:10px">
        ${apps.map((item) => `
          <div class="card application-card card-base card-hover-soft">
            <div class="card-head">
              <div class="card-title">${esc(item.title)}</div>
              <span class="badge badge-gray">${esc(APP_STATUS_LABELS[item.status] || item.status)}</span>
            </div>
            <div class="card-meta">简历 v${item.resume_version} · 更新于 ${formatDate(item.updated_at)}</div>
            ${item.latest_job_id ? `<div class="small muted">最近任务：${esc(item.latest_job_id)}</div>` : ""}
            <div class="row" style="margin-top:8px">
              <select data-application-status data-id="${item.application_id}">
                ${Object.entries(APP_STATUS_LABELS).map(([value, label]) => `<option value="${value}" ${item.status === value ? "selected" : ""}>${esc(label)}</option>`).join("")}
              </select>
              <button class="btn btn-outline btn-sm" data-action="update-application-status" data-id="${item.application_id}">保存状态</button>
              <button class="btn btn-primary btn-sm" data-action="run-application" data-id="${item.application_id}">运行</button>
              <button class="btn btn-danger btn-sm" data-action="delete-application" data-id="${item.application_id}">删除</button>
            </div>
          </div>`).join("") || `<div class="muted small">还没有投递记录</div>`}
      </div>
    </div>`;
}

/* ------------------------------------------------------------------ */
/* Settings                                                            */
/* ------------------------------------------------------------------ */

async function renderSettingsView(app) {
  state.settings = await api("/api/settings");
  const settings = state.settings;
  const weights = settings.appraisal_weights;
  const vocabulary = settings.classification_vocabulary;
  state.vocabulary = normalizeVocabulary(vocabulary);
  app.innerHTML = `
    <div class="page-header page-header--settings"><div><h2>设置</h2><div class="sub">评估权重、薪资参照与分类词表，保存后立即生效</div></div></div>
    <div class="grid-2">
      <div class="stack">
        <form class="panel panel-card" data-form="settings-weights">
          <h3>评估权重</h3>
          <div class="form-grid">
            ${Object.entries(weights).map(([key, value]) => `
              <div class="field"><label>${esc(key)}</label>
                <input type="number" name="${esc(key)}" value="${esc(value)}" min="0" max="100" step="1" required></div>`).join("")}
          </div>
          <div class="small muted" data-weight-sum>合计：${Object.values(weights).reduce((a, b) => a + b, 0)} / 100</div>
          <div class="row" style="margin-top:10px"><button class="btn btn-primary" type="submit">保存权重</button></div>
        </form>
        <form class="panel panel-card" data-form="settings-vocabulary">
          <h3>分类词表</h3>
          <div class="field"><label>岗位职能（每行一个）</label>
            <textarea name="job_functions" rows="6">${esc(vocabulary.job_functions.join("\n"))}</textarea></div>
          <div class="field"><label>级别（每行一个）</label>
            <textarea name="seniorities" rows="4">${esc(vocabulary.seniorities.join("\n"))}</textarea></div>
          <div class="field"><label>状态（每行一个）</label>
            <textarea name="statuses" rows="5">${esc(vocabulary.statuses.join("\n"))}</textarea></div>
          <div class="row"><button class="btn btn-primary" type="submit">保存词表</button></div>
        </form>
      </div>
        <form class="panel panel-card" data-form="settings-salary">
        <h3>薪资参照表（月薪，元）</h3>
        <div class="table-wrap">
          <table class="data">
            <thead><tr><th>职能</th><th>城市</th><th>P50</th><th>P75</th><th></th></tr></thead>
            <tbody data-salary-rows>
              ${settings.salary_reference.map((row, index) => `
                <tr>
                  <td><input type="text" name="job_function" value="${esc(row.job_function)}" required></td>
                  <td><input type="text" name="city" value="${esc(row.city)}" required></td>
                  <td><input type="number" name="p50" value="${esc(row.p50)}" min="0" required></td>
                  <td><input type="number" name="p75" value="${esc(row.p75)}" min="0" required></td>
                  <td><button class="btn btn-danger btn-sm" type="button" data-action="remove-salary-row" data-index="${index}">删除</button></td>
                </tr>`).join("")}
            </tbody>
          </table>
        </div>
        <div class="row" style="margin-top:10px">
          <button class="btn btn-outline btn-sm" type="button" data-action="add-salary-row">添加一行</button>
          <button class="btn btn-primary" type="submit">保存薪资表</button>
        </div>
      </form>
    </div>`;
}

/* ------------------------------------------------------------------ */
/* Modal + login                                                       */
/* ------------------------------------------------------------------ */

function showModal(title, bodyHtml) {
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

function closeModal() {
  const backdrop = $(".modal-backdrop");
  if (backdrop) backdrop.remove();
}

function openLoginModal() {
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

/* ------------------------------------------------------------------ */
/* Event delegation                                                    */
/* ------------------------------------------------------------------ */

const actions = {
  reload: () => render(),
  "new-resume": async () => {
    $('[data-form="resume-create"]').hidden = false;
  },
  "cancel-new-resume": () => {
    $('[data-form="resume-create"]').hidden = true;
  },
  "upload-resume": () => {
    const input = $("#resume-upload-input");
    if (input) input.click();
  },
  "open-resume-archive": (button) => navigate("resume", button.dataset.id),
  "back-resume-center": () => navigate("resume"),
  "print-resume": () => printTarget("resume"),
  "print-workbench": () => printTarget("workbench"),
  "export-diagnosis": () => printTarget("diagnosis"),
  "export-diagnosis-md": async () => {
    const resumeId =
      state.diagnosisResumeId || (state.route && state.route.resumeId);
    let content = "";
    if (resumeId) {
      try {
        const resume = await api(
          `/api/master-resumes/${encodeURIComponent(resumeId)}`,
        );
        content = resume.content || "";
      } catch {
        /* keep the diagnosis-only export */
      }
    }
    download(
      `resume-diagnosis.md`,
      buildDiagnosisMarkdown(content),
      "text/markdown;charset=utf-8",
    );
  },
  "diagnose-resume": async (button) => {
    const resumeId = button.dataset.id || state.diagnosisResumeId;
    if (!resumeId) return;
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = "诊断中...";
    renderDiagnosisProgress({
      status: "queued",
      stage: "",
      message: "排队中...",
      elapsed_seconds: 0,
    });
    try {
      const response = await api(
        `/api/master-resumes/${encodeURIComponent(resumeId)}/diagnose`,
        { method: "POST" },
      );
      state.diagnosis = { job_id: response.job_id, ...response };
      state.diagnosisResumeId = resumeId;
      startDiagnosisPolling(response.job_id, resumeId);
      toast("诊断任务已排队，正在运行", "success");
    } catch (error) {
      button.disabled = false;
      button.textContent = originalText;
      button.classList.remove("is-loading");
      renderDiagnosisError({ status: "failed", error: error.message });
    }
  },
  "rerun-diagnosis": (button) => {
    const diagnoseBtn = $("[data-action='diagnose-resume']");
    if (diagnoseBtn && !diagnoseBtn.disabled) {
      diagnoseBtn.click();
    } else if (button.dataset.id) {
      actions["diagnose-resume"](button);
    }
  },
  "cancel-diagnosis": async () => {
    const snapshot = state.diagnosis;
    if (!snapshot || !snapshot.job_id) return;
    if (snapshot.status === "queued") {
      await api(
        `/api/jobs/${encodeURIComponent(snapshot.job_id)}/cancel`,
        { method: "POST" },
      );
      stopDiagnosisPolling();
      renderDiagnosisError({
        status: "canceled",
        error: "Canceled by user",
      });
      toast("诊断任务已取消", "success");
    } else {
      stopDiagnosisPolling();
      toast("任务运行中无法中断，已停止本地等待", "info");
    }
  },
  "export-resume-md": async (button) => {
    const resume = await api(
      `/api/master-resumes/${encodeURIComponent(button.dataset.id)}`,
    );
    download(`resume-${resume.title}.md`, resume.content || "", "text/markdown;charset=utf-8");
  },
  "edit-resume": (button) => openResumeEditor(button.dataset.id),
  "delete-resume": async (button) => {
    if (!window.confirm("确定删除这份主简历及全部版本？")) return;
    await api(`/api/master-resumes/${encodeURIComponent(button.dataset.id)}`, { method: "DELETE" });
    toast("主简历已删除", "success");
    if (state.route.resumeId === button.dataset.id) navigate("resume");
    else render();
  },
  "rollback-resume": async (button) => {
    await api(`/api/master-resumes/${encodeURIComponent(button.dataset.id)}/rollback`, {
      method: "POST",
      body: JSON.stringify({ version: Number(button.dataset.version) }),
    });
    toast(`已回滚到 v${button.dataset.version}`, "success");
    render();
  },
  "show-add-job": () => {
    $('[data-form="job-create"]').hidden = false;
    $('[data-form="job-import"]').hidden = true;
  },
  "cancel-add-job": () => {
    $('[data-form="job-create"]').hidden = true;
  },
  "parse-jd-link": async (button) => {
    const form = button.closest('[data-form="job-create"]');
    const urlInput = form.querySelector('input[name="jd_url"]');
    const status = form.querySelector("[data-jd-parse-status]");
    const url = (urlInput.value || "").trim();
    if (!url) {
      toast("请先输入 JD 链接", "error");
      return;
    }
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = "解析中...";
    button.classList.add("is-loading");
    if (status) {
      status.className = "jd-parse-status";
      status.removeAttribute("role");
      status.textContent = "正在抓取并解析岗位内容...";
    }
    try {
      const parsed = await api("/api/jobs/parse-jd", {
        method: "POST",
        body: JSON.stringify({ jd_url: url }),
      });
      const titleInput = form.querySelector('input[name="title"]');
      if (titleInput && !(titleInput.value || "").trim()) {
        titleInput.value = parsed.title || "";
      }
      const jdText = form.querySelector('textarea[name="jd_text"]');
      if (jdText && !(jdText.value || "").trim()) {
        jdText.value = parsed.jd_text || "";
      }
      const companyInput = form.querySelector('input[name="company"]');
      if (companyInput && !(companyInput.value || "").trim()) {
        companyInput.value = parsed.company || "";
      }
      const locationInput = form.querySelector('input[name="location"]');
      if (locationInput && !(locationInput.value || "").trim()) {
        locationInput.value = parsed.city || "";
      }
      const sourceInput = form.querySelector('input[name="source_url"]');
      if (sourceInput && !(sourceInput.value || "").trim()) {
        sourceInput.value = parsed.source_url || "";
      }
      const salaryMinInput = form.querySelector('input[name="salary_min"]');
      const salaryMaxInput = form.querySelector('input[name="salary_max"]');
      const currencyInput = form.querySelector('input[name="salary_currency"]');
      if (
        salaryMinInput &&
        salaryMinInput.value === "" &&
        parsed.salary_min != null
      ) {
        salaryMinInput.value = parsed.salary_min;
      }
      if (
        salaryMaxInput &&
        salaryMaxInput.value === "" &&
        parsed.salary_max != null
      ) {
        salaryMaxInput.value = parsed.salary_max;
      }
      if (
        currencyInput &&
        !(currencyInput.value || "").trim() &&
        parsed.salary_currency
      ) {
        currencyInput.value = parsed.salary_currency;
      }
      setJdInputMode("paste");
      if (status) {
        status.className = "jd-parse-status form-success";
        status.textContent = `已解析：${parsed.title || "未知岗位"}，请核对 JD 文本后保存`;
      }
      toast("JD 链接解析完成", "success");
    } catch (error) {
      if (status) renderJdParseError(status, error.data);
    } finally {
      button.disabled = false;
      button.textContent = originalText;
      button.classList.remove("is-loading");
    }
  },
  "use-paste-mode": () => {
    const form = $('[data-form="job-create"]');
    const urlInput = form && form.querySelector('input[name="jd_url"]');
    const sourceInput = form && form.querySelector('input[name="source_url"]');
    if (
      urlInput &&
      sourceInput &&
      (urlInput.value || "").trim() &&
      !(sourceInput.value || "").trim()
    ) {
      sourceInput.value = urlInput.value.trim();
    }
    setJdInputMode("paste");
    const status = $("[data-jd-parse-status]");
    if (status) clearJdParseStatus(status);
  },
  "retry-parse-jd": (button) => {
    const form = button.closest('[data-form="job-create"]');
    const parseButton = form && form.querySelector('[data-action="parse-jd-link"]');
    if (parseButton) parseButton.click();
  },
  "show-import": () => {
    $('[data-form="job-import"]').hidden = false;
    $('[data-form="job-create"]').hidden = true;
  },
  "cancel-import": () => {
    $('[data-form="job-import"]').hidden = true;
  },
  "clear-filters": () => {
    state.filters = { job_function: "", seniority: "", status: "", search: "" };
    state.offset = 0;
    render();
  },
  "prev-page": () => {
    state.offset = Math.max(0, state.offset - state.limit);
    render();
  },
  "next-page": () => {
    state.offset += state.limit;
    render();
  },
  "edit-job": (button) => {
    const job = state.jobs.find((item) => item.job_id === button.dataset.id);
    if (job) openJobEditor(job);
  },
  "delete-job": async (button) => {
    if (!window.confirm("确定删除这个岗位？")) return;
    await api(`/api/jobs/${encodeURIComponent(button.dataset.id)}`, { method: "DELETE" });
    toast("岗位已删除", "success");
    render();
  },
  "reclassify-job": async (button) => {
    const job = state.jobs.find((item) => item.job_id === button.dataset.id);
    const hasManualFields =
      job &&
      Boolean(
        (job.job_function || "").trim() ||
          (job.seniority || "").trim() ||
          (job.tech_tags || []).length,
      );
    if (
      hasManualFields &&
      !window.confirm(
        "重新分类会用 LLM 结果覆盖当前职能、级别和标签，是否继续？",
      )
    ) {
      return;
    }
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = "分类中...";
    button.classList.add("is-loading");
    try {
      const updated = await api(
        `/api/jobs/${encodeURIComponent(button.dataset.id)}/reclassify`,
        { method: "POST" },
      );
      toast(
        `分类成功：${updated.job_function || "未分类"} · ${updated.seniority || "未知"} · ${(updated.tech_tags || []).join("/") || "无标签"}`,
        "success",
      );
      render();
    } catch (error) {
      toast(
        `重新分类失败：${error.message}，岗位仍为分类待定，可稍后重试`,
        "error",
      );
    } finally {
      button.disabled = false;
      button.textContent = originalText;
      button.classList.remove("is-loading");
    }
  },
  "open-workspace": (button) => navigate("workspace", button.dataset.id),
  "goto-selected-job": () => {
    const select = $("[data-wb-job-select]");
    if (select && select.value) navigate("workspace", select.value);
  },
  "back-workspace": () => navigate("workspace"),
  "toggle-raw-jd": () => {
    state.wbRawJdOpen = !state.wbRawJdOpen;
    render();
  },
  "cancel-workbench": async () => {
    const snapshot = state.wbJob && state.wbJob.workbench_job_id
      ? await api(`/api/jobs/${encodeURIComponent(state.wbJob.workbench_job_id)}`)
      : null;
    if (!snapshot || !["queued", "running"].includes(snapshot.status)) {
      toast("当前没有可取消的任务", "error");
      return;
    }
    if (snapshot.status === "queued") {
      await api(`/api/jobs/${encodeURIComponent(snapshot.job_id)}/cancel`, { method: "POST" });
      stopWbPolling();
      toast("任务已取消", "success");
      await refreshWbJob();
    } else {
      stopWbPolling();
      toast("任务运行中无法中断，已停止本地等待", "info");
    }
  },
  "retry-workbench": () => {
    const form = $('[data-form="wb-run"]');
    if (form) form.dispatchEvent(new Event("submit", { cancelable: true }));
  },
  "toggle-wb-view": (button) => {
    state.wbCompareView = button.dataset.wbView;
    renderWbResult($("#app"));
  },
  "accept-diffs": async () => {
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
  },
  "save-final-draft": async () => {
    const node = $("[data-accept-result] .pre");
    const draft = node ? node.textContent : "";
    if (!draft.trim()) {
      toast("草稿为空，无法保存", "error");
      return;
    }
    const jobId = state.wbJob.job_id;
    const saved = await api(`/api/jobs/${encodeURIComponent(jobId)}/final-draft`, {
      method: "POST",
      body: JSON.stringify({ draft }),
    });
    state.wbFinalDraft = {
      draft: saved.draft,
      version: saved.version,
      updated_at: saved.updated_at,
    };
    renderFinalDraftPanel($("#app"));
    const finalPanel = $("[data-final-draft-panel]");
    if (finalPanel) finalPanel.classList.add("is-saved");
    try {
      state.wbJob = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    } catch {
      /* keep the current job object */
    }
    toast(`定稿已保存为第 ${saved.version} 版`, "success");
  },
  "export-final-draft": () => printTarget("final-draft"),
  "export-final-draft-md": () => {
    const draft = state.wbFinalDraft && state.wbFinalDraft.draft;
    if (!draft) return;
    const job = state.wbJob || {};
    download(
      `resualign-${job.title || "final-draft"}.md`,
      draft,
      "text/markdown;charset=utf-8",
    );
  },
  "save-as-new-resume": () => {
    const draft = state.wbFinalDraft && state.wbFinalDraft.draft;
    if (!draft) {
      toast("请先保存定稿", "error");
      return;
    }
    showModal(
      "另存为新主简历",
      `<p class="muted">将当前定稿创建为一份新的主简历，不会改动当前主简历。</p>
       <div class="actions">
         <button class="btn btn-ghost" type="button" data-action="close-modal">取消</button>
         <button class="btn btn-primary" type="button" data-action="confirm-save-as">确认另存</button>
       </div>`,
    );
  },
  "confirm-save-as": async () => {
    const draft = state.wbFinalDraft && state.wbFinalDraft.draft;
    const job = state.wbJob || {};
    closeModal();
    if (!draft) {
      toast("请先保存定稿", "error");
      return;
    }
    const now = new Date();
    const suffix = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(now.getDate()).padStart(2, "0")}`;
    const baseResume = (state.wbResumes || []).find(
      (resume) => resume.resume_id === job.workbench_resume_id,
    );
    const title = `${baseResume ? baseResume.title : "主简历"}-${job.title || "岗位"}-${suffix}`;
    const created = await api("/api/master-resumes", {
      method: "POST",
      body: JSON.stringify({ title, content: draft }),
    });
    toast(`已创建新主简历：${created.title}`, "success");
    navigate("resume", created.resume_id);
  },
  "export-markdown": () => {
    const job = state.wbJob;
    const result = state.wbResult || {};
    const sections = (result.tailored_resume || {}).sections || {};
    const content = [
      `# ${job ? job.title : "对齐简历"}`,
      "",
      `> 诊断分：${result.score ?? "—"} · 模型：${result.model || ""}`,
      "",
      "## 优化后内容",
      "",
      Object.values(sections).join("\n\n"),
      "",
      "## 修改项",
      "",
      ...(result.diffs || []).map((diff, index) => `${index + 1}. [${diff.type}] ${diff.reason || ""}`),
    ].join("\n");
    download(`resualign-${job ? job.title : "resume"}.md`, content, "text/markdown;charset=utf-8");
  },
  "export-json": () => {
    const job = state.wbJob;
    download(
      `resualign-${job ? job.title : "resume"}.json`,
      JSON.stringify({ job, result: state.wbResult }, null, 2),
      "application/json",
    );
  },
  "export-draft": () => {
    const node = $("[data-accept-result] .pre");
    if (node) download("resualign-draft.md", node.textContent, "text/markdown;charset=utf-8");
  },
  "update-job-status": async (button) => {
    const select = $("[data-job-status]");
    await api(`/api/jobs/${encodeURIComponent(button.dataset.id)}`, {
      method: "PATCH",
      body: JSON.stringify({ status: select.value }),
    });
    toast("岗位状态已保存", "success");
    await refreshWbJob();
  },
  "run-application": async (button) => {
    stopApplicationPolling();
    const response = await api(
      `/api/applications/${encodeURIComponent(button.dataset.id)}/run`,
      { method: "POST" },
    );
    toast("已开始运行投递分析", "success");
    const jobId = response.job_id;
    const timer = window.setInterval(async () => {
      try {
        const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
        if (!["queued", "running"].includes(job.status)) {
          stopApplicationPolling();
          await refreshWbJob();
          toast(
            job.status === "succeeded" ? "投递分析完成" : `投递分析${job.status}`,
            job.status === "succeeded" ? "success" : "error",
          );
        }
      } catch (error) {
        stopApplicationPolling();
        toast(error.message, "error");
      }
    }, 1000);
    state.applicationPoll = { jobId, timer };
  },
  "update-application-status": async (button) => {
    const select = $(`[data-application-status][data-id="${button.dataset.id}"]`);
    await api(`/api/applications/${encodeURIComponent(button.dataset.id)}`, {
      method: "PATCH",
      body: JSON.stringify({ status: select.value }),
    });
    toast("投递状态已保存", "success");
    await refreshWbJob();
  },
  "delete-application": async (button) => {
    if (!window.confirm("确定删除这条投递记录？")) return;
    await api(`/api/applications/${encodeURIComponent(button.dataset.id)}`, { method: "DELETE" });
    toast("投递记录已删除", "success");
    await refreshWbJob();
  },
  "add-salary-row": () => {
    const tbody = $("[data-salary-rows]");
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="text" name="job_function" required></td>
      <td><input type="text" name="city" required></td>
      <td><input type="number" name="p50" min="0" required></td>
      <td><input type="number" name="p75" min="0" required></td>
      <td><button class="btn btn-danger btn-sm" type="button" data-action="remove-salary-row">删除</button></td>`;
    tr.querySelector("[data-action]").addEventListener("click", () => tr.remove());
    tbody.append(tr);
  },
  "remove-salary-row": (button) => {
    button.closest("tr").remove();
  },
  "close-modal": closeModal,
};

function setJdInputMode(mode) {
  $$("[data-mode]").forEach((button) =>
    button.setAttribute("aria-pressed", String(button.dataset.mode === mode)),
  );
  const urlField = $("[data-url-field]");
  const jdText = $('[name="jd_text"]');
  if (mode === "url") {
    if (urlField) urlField.hidden = false;
    if (jdText) jdText.closest(".field").hidden = true;
  } else {
    if (urlField) urlField.hidden = true;
    if (jdText) jdText.closest(".field").hidden = false;
  }
  const status = $("[data-jd-parse-status]");
  if (status && status.classList.contains("form-error")) {
    clearJdParseStatus(status);
  }
}

function clearJdParseStatus(status) {
  status.className = "jd-parse-status";
  status.removeAttribute("role");
  status.textContent = "";
}

function renderJdParseError(status, detail) {
  status.className = "jd-parse-status form-error";
  status.setAttribute("role", "alert");
  const reason =
    detail && detail.reason ? detail.reason : "未能从该链接提取岗位内容";
  const action =
    detail && detail.action ? detail.action : "可改用粘贴 JD 或稍后重试";
  status.innerHTML = `
    <div class="jd-parse-error-text"><strong>解析失败</strong>：${esc(reason)}，${esc(action)}</div>
    <div class="row">
      <button class="btn btn-secondary btn-sm" type="button" data-action="use-paste-mode">改用粘贴 JD</button>
      <button class="btn btn-ghost btn-sm" type="button" data-action="retry-parse-jd">重新解析</button>
    </div>`;
}

function setSegmented(selector, active) {
  $$(selector).forEach((button) =>
    button.setAttribute("aria-pressed", String(button === active)),
  );
}

document.addEventListener("click", async (event) => {
  const badge = event.target.closest(".opt-badge");
  if (badge) {
    const bubble = badge.nextElementSibling;
    if (bubble && bubble.classList.contains("opt-bubble")) {
      bubble.hidden = !bubble.hidden;
    }
  }
  const granularityButton = event.target.closest("[data-granularity]");
  if (granularityButton) setSegmented("[data-granularity]", granularityButton);
  const focusButton = event.target.closest("[data-focus]");
  if (focusButton) setSegmented("[data-focus]", focusButton);
  const modeButton = event.target.closest("[data-mode]");
  if (modeButton) setJdInputMode(modeButton.dataset.mode);
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const action = actions[button.dataset.action];
  if (!action) return;
  try {
    await action(button, event);
  } catch (error) {
    toast(error.message, "error");
  }
});

document.addEventListener("change", (event) => {
  const target = event.target;
  if (target.matches("[data-mode]")) {
    setJdInputMode(target.dataset.mode);
  }
  if (target.matches("[data-granularity]")) {
    setSegmented("[data-granularity]", target);
  }
  if (target.matches("[data-focus]")) {
    setSegmented("[data-focus]", target);
  }
  if (target.matches('[data-form="settings-weights"] input')) {
    const sum = $$('[data-form="settings-weights"] input').reduce(
      (total, input) => total + (Number(input.value) || 0),
      0,
    );
    const label = $("[data-weight-sum]");
    if (label) {
      label.textContent = `合计：${sum} / 100`;
      label.style.color = sum === 100 ? "" : "var(--red)";
    }
  }
});

document.addEventListener("submit", async (event) => {
  const form = event.target;
  const formName = form.dataset.form;
  if (!formName) return;
  event.preventDefault();
  const submitBtn = form.querySelector('button[type="submit"]');
  if (submitBtn) submitBtn.classList.add("is-loading");
  try {
    const data = Object.fromEntries(new FormData(form).entries());
    await handleForm(formName, data, form);
  } catch (error) {
    toast(error.message, "error");
  } finally {
    if (submitBtn) submitBtn.classList.remove("is-loading");
  }
});

async function handleForm(formName, data, form) {
  switch (formName) {
    case "resume-create":
      await api("/api/master-resumes", {
        method: "POST",
        body: JSON.stringify({ title: data.title, content: data.content }),
      });
      toast("主简历已创建", "success");
      render();
      break;
    case "resume-edit":
      await api(`/api/master-resumes/${encodeURIComponent(data.resume_id)}`, {
        method: "PATCH",
        body: JSON.stringify({ content: data.content }),
      });
      toast("新版本已保存", "success");
      closeModal();
      render();
      break;
    case "job-create": {
      const payload = {
        title: data.title || null,
        jd_text: data.jd_text || null,
        jd_url: data.jd_url || null,
        company: data.company || null,
        location: data.location || null,
        salary_min: data.salary_min ? Number(data.salary_min) : null,
        salary_max: data.salary_max ? Number(data.salary_max) : null,
        salary_currency: data.salary_currency || null,
        source_url: data.source_url || null,
      };
      await api("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
      toast("岗位已添加", "success");
      render();
      break;
    }
    case "job-edit": {
      const payload = {
        title: data.title,
        jd_text: data.jd_text,
        company: data.company || null,
        location: data.location || null,
        salary_min: data.salary_min ? Number(data.salary_min) : null,
        salary_max: data.salary_max ? Number(data.salary_max) : null,
        status: data.status,
        job_function: data.job_function || null,
        seniority: data.seniority || null,
        tech_tags: (data.tech_tags || "").split(",").map((tag) => tag.trim()).filter(Boolean),
      };
      await api(`/api/jobs/${encodeURIComponent(data.job_id)}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      toast("岗位已更新", "success");
      closeModal();
      render();
      break;
    }
    case "job-filter":
      state.filters = {
        job_function: data.job_function || "",
        seniority: data.seniority || "",
        status: data.status || "",
        search: data.search || "",
      };
      state.offset = 0;
      render();
      break;
    case "job-import":
      await submitImport(data, form);
      break;
    case "wb-run": {
      const masterResumeId = data.master_resume_id;
      const granularity = ($('[data-granularity][aria-pressed="true"]') || {}).dataset?.granularity || "medium";
      const promptFocus = ($('[data-focus][aria-pressed="true"]') || {}).dataset?.focus || "balanced";
      const customPrompt = data.custom_prompt || "";
      if (!masterResumeId) {
        toast("请先选择主简历", "error");
        return;
      }
      const pinnedResume = (state.wbResumes || []).find(
        (item) => item.resume_id === masterResumeId,
      );
      state.wbOriginalContent = (pinnedResume && pinnedResume.content) || "";
      state.wbAcceptedIndices = null;
      state.wbCompareView = "side";
      state.wbRun = { masterResumeId, granularity, promptFocus, customPrompt };
      const result = await api(`/api/jobs/${encodeURIComponent(state.wbJob.job_id)}/workbench`, {
        method: "POST",
        body: JSON.stringify({ master_resume_id: masterResumeId, granularity, prompt_focus: promptFocus, custom_prompt: customPrompt }),
      });
      $("[data-wb-progress-panel]").hidden = false;
      startWbPolling(result.job_id);
      toast("任务已排队，正在运行", "success");
      break;
    }
    case "application-create":
      await api("/api/applications", {
        method: "POST",
        body: JSON.stringify({
          title: data.title,
          master_resume_id: data.master_resume_id,
          jd_text: data.jd_text || null,
          jd_url: data.jd_url || null,
        }),
      });
      toast("投递记录已创建", "success");
      await refreshWbJob();
      break;
    case "login": {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: data.email, password: data.password }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "登录失败");
      state.token = body.token;
      localStorage.setItem("resualign_token", body.token);
      state.personal = false;
      closeModal();
      toast("登录成功", "success");
      render();
      break;
    }
    case "settings-weights": {
      const weights = Object.fromEntries(
        Object.entries(data).map(([key, value]) => [key, Number(value)]),
      );
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({ appraisal_weights: weights }),
      });
      toast("评估权重已保存", "success");
      render();
      break;
    }
    case "settings-vocabulary": {
      const vocabulary = {
        job_functions: (data.job_functions || "").split("\n").map((item) => item.trim()).filter(Boolean),
        seniorities: (data.seniorities || "").split("\n").map((item) => item.trim()).filter(Boolean),
        statuses: (data.statuses || "").split("\n").map((item) => item.trim()).filter(Boolean),
      };
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({ classification_vocabulary: vocabulary }),
      });
      state.vocabulary = normalizeVocabulary(vocabulary);
      toast("分类词表已保存", "success");
      render();
      break;
    }
    case "settings-salary": {
      const rows = $$('[data-salary-rows] tr').map((row) => ({
        job_function: row.querySelector('[name="job_function"]').value.trim(),
        city: row.querySelector('[name="city"]').value.trim(),
        p50: Number(row.querySelector('[name="p50"]').value),
        p75: Number(row.querySelector('[name="p75"]').value),
      }));
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({ salary_reference: rows }),
      });
      toast("薪资参照表已保存", "success");
      render();
      break;
    }
    default:
      break;
  }
}

async function submitImport(data, form) {
  const file = form.querySelector('[name="import_file"]').files[0];
  const pasted = data.import_text || "";
  let payload = {};
  if (file) {
    const text = await file.text();
    if (file.name.toLowerCase().endsWith(".json")) {
      const rows = parseImportText(text, file.name);
      if (rows.length) payload = { jobs: rows };
    } else if (text.trim()) {
      payload = { csv_text: text };
    }
  } else if (pasted.trim()) {
    if (pasted.trim().startsWith("[")) {
      const rows = parseImportText(pasted, "paste");
      if (rows.length) payload = { jobs: rows };
    } else {
      payload = { csv_text: pasted };
    }
  }
  if (!payload.jobs && !payload.csv_text) {
    toast("没有可导入的岗位数据", "error");
    return;
  }
  const statusNode = form.querySelector("[data-import-status]");
  statusNode.textContent = "已提交，正在处理...";
  const body = await api("/api/jobs/import", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!body.queued) {
    statusNode.textContent = "没有可导入的数据";
    return;
  }
  statusNode.textContent = `已提交 ${body.total} 条，正在处理...`;
  const timer = window.setInterval(async () => {
    try {
      const status = await api(`/api/jobs/import/${body.import_id}`);
      statusNode.textContent = `处理中：新建 ${status.created}，跳过 ${status.skipped}`;
      if (!status.queued) {
        window.clearInterval(timer);
        statusNode.textContent = `完成：新建 ${status.created}，跳过 ${status.skipped}`;
        toast(`导入完成：新建 ${status.created}，跳过 ${status.skipped}`, status.created ? "success" : "error");
        render();
      }
    } catch (error) {
      window.clearInterval(timer);
      statusNode.textContent = `导入失败：${error.message}`;
    }
  }, 800);
}

function parseImportText(text, filename) {
  const trimmed = text.trim();
  if (!trimmed) return [];
  if (trimmed.startsWith("[") || filename.endsWith(".json")) {
    try {
      const parsed = JSON.parse(trimmed);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }
  const lines = trimmed.split(/\r?\n/).filter(Boolean);
  if (!lines.length) return [];
  const headers = lines[0].split(",").map((header) => header.trim());
  return lines.slice(1).map((line) => {
    const values = line.split(",").map((value) => value.trim());
    const row = {};
    headers.forEach((header, index) => {
      if (header) row[header] = values[index] || "";
    });
    return row;
  });
}

/* ------------------------------------------------------------------ */
/* Boot                                                                */
/* ------------------------------------------------------------------ */

async function boot() {
  $$(".tabs button").forEach((button) => {
    button.addEventListener("click", () => navigate(button.dataset.route));
  });
  document.addEventListener("change", async (event) => {
    const input = event.target;
    if (
      !(input instanceof HTMLInputElement) ||
      input.id !== "resume-upload-input"
    ) {
      return;
    }
    const file = input.files && input.files[0];
    input.value = "";
    if (!file) return;
    try {
      const formData = new FormData();
      formData.append("file", file);
      const parsed = await api("/api/master-resumes/parse", {
        method: "POST",
        body: formData,
      });
      const form = $('[data-form="resume-create"]');
      if (!form) return;
      form.hidden = false;
      form.querySelector('input[name="title"]').value =
        parsed.title || file.name;
      form.querySelector('textarea[name="content"]').value = parsed.content;
      toast(`已解析 ${file.name}，请确认后保存`, "success");
      form.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      toast(error.message, "error");
    }
  });
  try {
    await api("/api/auth/me");
    state.personal = true;
  } catch {
    state.personal = false;
  }
  window.addEventListener("hashchange", render);
  await render();
}

boot();
