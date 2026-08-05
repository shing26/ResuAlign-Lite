import {
  $,
  $$,
  APP_STATUS_LABELS,
  api,
  buildDiagnosisMarkdown,
  canonicalJobStatus,
  closeModal,
  download,
  ensureVocabulary,
  esc,
  formatDate,
  formatSalary,
  JOB_STATUS_CANONICAL,
  JOB_STATUS_LABELS,
  normalizeVocabulary,
  openLoginModal,
  options,
  recoverDiagnosis,
  renderBatchResults,
  renderDiagnosisError,
  renderDiagnosisProgress,
  renderDiagnosisResult,
  renderWbProgress,
  showModal,
  startBatchPolling,
  startDiagnosisPolling,
  state,
  stopApplicationPolling,
  stopBatchPolling,
  stopDiagnosisPolling,
  stopWbPolling,
  toast,
  vocabularyList,
} from "./events.js";
import {
  acceptSelectedDiffs,
  lineDiff,
  regenerateDiff,
  renderWbError,
  renderWbResult,
  toggleWbView,
} from "./diff-editor.js";
import { renderAppraisal } from "./appraisal-panel.js";
import { initTheme, toggleTheme } from "./theme.js";
import {
  closeCommandPanel,
  confirmCommandPanel,
  initializeCommandPanel,
  openCommandPanel,
} from "./command-panel.js";
import {
  analyzeActiveJd,
  activeSessionForExport,
  closeSplitCanvas,
  copyAlignMarkdown,
  exportAlignMarkdown,
  exportAlignJson,
  renderCopilotBoard,
  renderOptimizerCanvas,
  startAlignmentRun,
} from "./split-canvas.js";

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
  document.body.classList.remove("wb-appraisal-drawer-open");
  closeSplitCanvas();
  setActiveTab();
  stopWbPolling();
  stopApplicationPolling();
  stopDiagnosisPolling();
  stopBatchPolling();
  const app = $("#app");
  const printNode = $("#print-root");
  if (printNode) printNode.innerHTML = "";
  app.innerHTML = `<div class="skeleton is-shimmer">加载中...</div>`;
  try {
    if (state.route.name === "resume" && state.route.resumeId) {
      await renderResumeDetailView(app, state.route.resumeId);
    } else if (state.route.name === "resume") await renderResumeView(app);
    else if (state.route.name === "jobs") await renderCopilotBoard(app);
    else if (state.route.name === "workspace") await renderOptimizerCanvas(app, state.route.jobId);
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
    limit: "500",
    offset: "0",
  });
  for (const key of ["job_function", "seniority", "status", "search"]) {
    if (!state.filters[key]) query.delete(key);
  }
  state.jobs = await api(`/api/jobs?${query}`);
  const vocabulary = await ensureVocabulary();
  state.batchResumes = await api("/api/master-resumes");
  renderPipelineBoard(app, vocabulary, state.batchResumes);
  return;
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

function renderBoardCard(job) {
  const canonical = canonicalJobStatus(job.status);
  const statusOptions = JOB_STATUS_CANONICAL.map(
    (value) =>
      `<option value="${value}" ${canonical === value ? "selected" : ""}>${esc(JOB_STATUS_LABELS[value])}</option>`,
  ).join("");
  return `
    <article class="board-card ${job.classification_pending ? "board-card--pending" : ""}" data-job-id="${job.job_id}">
      <div class="board-card__top">
        <label class="board-check"><input type="checkbox" data-board-check value="${job.job_id}" aria-label="选择 ${esc(job.title)}"><span></span></label>
        <button type="button" class="board-card__title" data-action="open-job-detail" data-id="${job.job_id}">${esc(job.title)}</button>
      </div>
      <div class="board-card__meta">${esc(job.company || "未知公司")} · ${esc(job.location || "未知城市")} · ${formatSalary(job)}</div>
      <div class="board-card__tags">
        <span class="badge badge-blue">${esc(job.job_function || "未分类")}</span>
        <span class="badge badge-gray">${esc(job.seniority || "未知")}</span>
        ${job.classification_pending ? '<span class="badge badge-amber badge-pending">分类待定</span>' : ""}
      </div>
      <div class="board-card__timeline">
        ${job.applied_at ? `<span class="small muted">投递 ${esc(job.applied_at)}</span>` : ""}
        ${job.next_step ? `<span class="small muted">下一步：${esc(job.next_step)}</span>` : ""}
      </div>
      <div class="row" style="margin-top:8px">
        <select class="board-status-select" data-board-status data-id="${job.job_id}" aria-label="移动状态">${statusOptions}</select>
        <button class="btn btn-ghost btn-sm" data-action="open-workspace" data-id="${job.job_id}">工作台</button>
        <button class="btn btn-ghost btn-sm" data-action="edit-job" data-id="${job.job_id}">编辑</button>
      </div>
    </article>`;
}

function renderPipelineBoard(app, vocabulary, resumes = []) {
  const columns = JOB_STATUS_CANONICAL.map((canonical) => {
    const items = state.jobs.filter(
      (job) => canonicalJobStatus(job.status) === canonical,
    );
    return `
      <section class="board-column" data-status="${canonical}" aria-label="${esc(JOB_STATUS_LABELS[canonical])}">
        <div class="board-column__head">
          <span class="board-column__dot board-dot--${canonical}" aria-hidden="true"></span>
          <h3>${esc(JOB_STATUS_LABELS[canonical])}</h3>
          <span class="board-column__count">${items.length}</span>
        </div>
        <div class="board-column__body">
          ${items.map(renderBoardCard).join("") || '<div class="board-column__empty">暂无岗位</div>'}
        </div>
      </section>`;
  }).join("");

  app.innerHTML = `
    <div class="page-header page-header--jobs">
      <div>
        <h2>岗位库</h2>
        <div class="sub">共 ${state.jobs.length} 条 · 在五状态看板中移动岗位，批量更新投递进度</div>
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
    ${renderBatchPanel(resumes)}
    <div class="board-toolbar panel panel-card">
      <label class="row" style="gap:6px"><input type="checkbox" data-board-select-all aria-label="全选当前岗位"><span class="small">全选</span></label>
      <span class="small muted" data-board-selected-count>已选 0</span>
      <select data-board-bulk-status aria-label="批量移动到">
        <option value="">批量移动到...</option>
        ${JOB_STATUS_CANONICAL.map((value) => `<option value="${value}">${esc(JOB_STATUS_LABELS[value])}</option>`).join("")}
      </select>
      <button class="btn btn-secondary btn-sm" data-action="bulk-move-status">批量移动</button>
    </div>
    <div id="job-board" class="pipeline-board" data-pipeline-board>${columns}</div>`;
}

function renderBatchPanel(resumes) {
  const jobOptions = state.jobs
    .map(
      (job) =>
        `<label class="batch-job-option"><input type="checkbox" name="job_ids" value="${job.job_id}" data-batch-check> <span>${esc(job.title)} 路 ${esc(job.company || "")}</span></label>`,
    )
    .join("");
  const resumeOptions = resumes
    .map(
      (resume) =>
        `<option value="${resume.resume_id}">${esc(resume.title)}（v${resume.current_version}）</option>`,
    )
    .join("");
  return `
    <form class="panel panel-card batch-panel" data-form="batch-align" data-batch-panel>
      <h3>批量对齐</h3>
      <div class="form-grid">
        <div class="field"><label>主简历</label><select name="master_resume_id" required>
          <option value="">${resumes.length ? "选择简历..." : "先到简历中心创建主简历"}</option>${resumeOptions}</select></div>
        <div class="field"><label>对齐粒度</label><select name="granularity">
          <option value="fine">微调</option><option value="medium">重构</option><option value="coarse">重写</option>
        </select></div>
        <div class="field wide"><label>选择 2-5 个岗位</label>
          <div class="batch-job-list">${jobOptions || '<div class="muted small">岗位库为空</div>'}</div></div>
        <div class="field wide"><label>自定义补充要求（可选）</label>
          <textarea name="custom_prompt" rows="2" placeholder="例如：强调高并发缓存场景"></textarea></div>
      </div>
      <div class="row">
        <button class="btn btn-primary" type="submit">开始批量对齐</button>
        <button class="btn btn-danger" type="button" data-action="cancel-batch-align" data-batch-cancel hidden>取消排队</button>
        <span class="small muted" data-batch-status></span>
      </div>
      <div data-batch-results></div>
    </form>`;
}

function openJobDetail(job) {
  showModal(
    `岗位详情 · ${job.title}`,
    `<form data-form="job-detail-edit">
      <input type="hidden" name="job_id" value="${job.job_id}">
      <div class="form-grid">
        <div class="field"><label>状态</label><select name="status">${JOB_STATUS_CANONICAL.map((value) => `<option value="${value}" ${canonicalJobStatus(job.status) === value ? "selected" : ""}>${esc(JOB_STATUS_LABELS[value])}</option>`).join("")}</select></div>
        <div class="field"><label>投递时间</label><input type="datetime-local" name="applied_at" value="${esc(job.applied_at || "")}"></div>
        <div class="field"><label>下一步</label><input type="text" name="next_step" value="${esc(job.next_step || "")}"></div>
        <div class="field"><label>Offer 时间</label><input type="datetime-local" name="offer_at" value="${esc(job.offer_at || "")}"></div>
        <div class="field"><label>拒绝时间</label><input type="datetime-local" name="rejected_at" value="${esc(job.rejected_at || "")}"></div>
        <div class="field wide"><label>备注</label><textarea name="notes" rows="3">${esc(job.notes || "")}</textarea></div>
      </div>
      <div class="actions">
        <button class="btn btn-ghost" type="button" data-action="close-modal">取消</button>
        <button class="btn btn-primary" type="submit">保存</button>
      </div>
    </form>`,
  );
}

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
  state.wbAppraisalOpen = false;
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
        <button class="btn btn-outline appraisal-drawer-toggle" data-action="toggle-appraisal-drawer" aria-expanded="${state.wbAppraisalOpen}" aria-controls="workbench-appraisal">${state.wbAppraisalOpen ? "收起评估" : "查看评估"}</button>
        <button class="btn btn-ghost" data-action="back-workspace">换一个岗位</button>
      </div>
    </div>
    <div class="workbench-3col ${state.wbAppraisalOpen ? "is-appraisal-open" : ""}" data-workbench-layout>
      <div class="wb-mobile-tabs segmented" role="tablist" aria-label="工作台面板">
        <button type="button" class="segmented-button" data-action="set-wb-tab" data-wb-tab="controls" aria-selected="${state.wbMobilePane === "controls"}">调优</button>
        <button type="button" class="segmented-button" data-action="set-wb-tab" data-wb-tab="appraisal" aria-selected="${state.wbMobilePane === "appraisal"}">评估</button>
      </div>
      <div class="workbench-column workbench-controls ${state.wbMobilePane === "controls" ? "is-active" : ""}" data-wb-pane="controls">
        <details class="panel panel-card job-raw-jd" ${state.wbRawJdOpen ? "open" : ""}>
          <summary>岗位 JD</summary>
          <div class="pre raw-jd">${esc(job.jd_text)}</div>
        </details>
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
      </div>
      <div class="workbench-column workbench-diff" data-wb-pane="diff">
        <div class="panel panel-card panel--info" data-wb-result hidden></div>
        <div class="panel panel-card panel--success final-draft-panel" data-final-draft-panel hidden></div>
      </div>
      <div class="workbench-column workbench-appraisal ${state.wbMobilePane === "appraisal" ? "is-active" : ""}" id="workbench-appraisal" data-wb-pane="appraisal">
        <div class="panel panel-card jd-profile-panel" data-jd-profile-panel>
          <h3>JD 画像</h3>
          <div class="muted small">运行一次对齐分析后生成</div>
        </div>
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

async function refreshOptimizerFromJob(jobId) {
  await renderOptimizerCanvas($("#app"), jobId);
}

function startWbPolling(jobId, app = $("#app")) {
  stopWbPolling();
  state.wbPolling = { jobId, app, timer: window.setInterval(() => pollWbJob(jobId), 1000) };
  pollWbJob(jobId);
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
  const [settings, status] = await Promise.all([
    api("/api/settings"),
    api("/api/settings/status"),
  ]);
  state.settings = settings;
  const vocabulary = settings.classification_vocabulary;
  state.vocabulary = normalizeVocabulary(vocabulary);
  app.innerHTML = `
    <div class="page-header page-header--settings"><div><h2>设置</h2><div class="sub">内置默认配置可直接使用，按需调整后保存立即生效</div></div></div>
    <section class="panel panel-card settings-status">
      <div class="settings-status__head">
        <div>
          <h3>运行状态</h3>
          <div class="small muted">模型、API 与本地数据概览</div>
        </div>
        <span class="badge ${status.api_key_configured ? "badge-green" : "badge-amber"}">${status.api_key_configured ? "LLM 已配置" : "LLM 未配置"}</span>
      </div>
      <div class="settings-status__grid">
        <div><span>模型</span><strong>${esc(status.provider)} · ${esc(status.model)}</strong></div>
        <div><span>运行模式</span><strong>${status.personal_mode ? "个人模式" : "多租户模式"}</strong></div>
        <div><span>数据量</span><strong>简历 ${status.resume_count} · 岗位 ${status.job_count} · 投递 ${status.application_count}</strong></div>
      </div>
      <div class="row" style="margin-top:12px">
        <button class="btn btn-outline btn-sm" type="button" data-action="reset-settings">恢复默认设置</button>
        <button class="btn btn-ghost btn-sm" type="button" data-action="go-resumes">去简历中心</button>
        <button class="btn btn-ghost btn-sm" type="button" data-action="go-jobs">去岗位库</button>
      </div>
    </section>
    <div class="grid-2">
      <form class="panel panel-card" data-form="settings-llm">
        <h3>LLM 模型</h3>
        <div class="form-grid">
          <div class="field"><label>服务商</label>
            <select name="llm_provider">
              <option value="deepseek" ${status.provider === "deepseek" ? "selected" : ""}>DeepSeek</option>
              <option value="openrouter" ${status.provider === "openrouter" ? "selected" : ""}>OpenRouter</option>
              <option value="ollama" ${status.provider === "ollama" ? "selected" : ""}>Ollama</option>
            </select></div>
          <div class="field"><label>模型名称</label>
            <input type="text" name="llm_model" value="${esc(status.model)}" placeholder="例如 deepseek-chat"></div>
        </div>
        <div class="small muted">保存后立即生效，无需重启；API Key 仍从 .env 或环境变量读取。</div>
        <div class="row" style="margin-top:10px"><button class="btn btn-primary" type="submit">保存并切换</button></div>
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
    </div>`;
}

/* ------------------------------------------------------------------ */
/* Event delegation                                                    */
/* ------------------------------------------------------------------ */

function toggleAppraisalDrawer(button) {
  state.wbAppraisalOpen = !state.wbAppraisalOpen;
  const layout = $("[data-workbench-layout]");
  if (layout) layout.classList.toggle("is-appraisal-open", state.wbAppraisalOpen);
  document.body.classList.toggle("wb-appraisal-drawer-open", state.wbAppraisalOpen);
  if (button) {
    button.setAttribute("aria-expanded", String(state.wbAppraisalOpen));
    button.textContent = state.wbAppraisalOpen ? "收起评估" : "查看评估";
  }
}

function setWbMobilePane(button) {
  state.wbMobilePane = button.dataset.wbTab;
  $$("[data-wb-tab]").forEach((tab) =>
    tab.setAttribute("aria-selected", String(tab.dataset.wbTab === state.wbMobilePane)),
  );
  $$("[data-wb-pane='controls'], [data-wb-pane='appraisal']").forEach((pane) => {
    pane.classList.toggle("is-active", pane.dataset.wbPane === state.wbMobilePane);
  });
}

async function printTarget(kind) {
  const printNode = $("#print-root");
  if (!printNode) return;
  let title = "ResuAlign";
  let body = "";
  if (kind === "resume") {
    const resumeId = state.route && state.route.resumeId;
    let resume = null;
    if (resumeId) {
      try {
        resume = await api(`/api/master-resumes/${encodeURIComponent(resumeId)}`);
      } catch {
        /* keep empty resume */
      }
    }
    title = resume ? resume.title : "简历";
    body =
      `<h1>${esc(title)}</h1>` +
      `<div class="print-meta">${resume ? `更新于 ${formatDate(resume.updated_at)} · 当前版本 v${resume.current_version}` : ""}</div>` +
      `<div class="resume-doc">${renderMarkdown(resume ? resume.content : "")}</div>`;
  } else if (kind === "final-draft") {
    const draft = state.wbFinalDraft;
    const job = state.wbJob || {};
    title = job.title || "定稿简历";
    body =
      `<h1>${esc(title)}</h1>` +
      `<div class="print-meta">${draft ? `保存于 ${formatDate(draft.updated_at)} · 第 ${draft.version} 版` : ""}</div>` +
      `<div class="resume-doc" data-final-draft-panel>${renderMarkdown(draft ? draft.draft : "")}</div>`;
  } else if (kind === "workbench") {
    const job = state.wbJob || {};
    const session = activeSessionForExport() || {};
    const result = state.wbResult || {};
    const sections = (result.tailored_resume && result.tailored_resume.sections) || {};
    const aligned = Object.values(sections).join("\n\n");
    const fallbackDraft =
      state.wbFinalDraft && state.wbFinalDraft.draft
        ? state.wbFinalDraft.draft
        : (session.alignment && session.alignment.draft) || "";
    const matchScore =
      (result.eval_score && result.eval_score.jd_match_score) ||
      result.score ||
      (session.gap && session.gap.score) ||
      "-";
    title = `${job.title || (session.job && session.job.title) || "工作台"} - AI 对齐稿`;
    body =
      `<h1>${esc(title)}</h1>` +
      `<div class="print-meta">匹配度 ${matchScore}/100</div>` +
      `<div class="resume-doc">${renderMarkdown(aligned || fallbackDraft)}</div>`;
  } else if (kind === "diagnosis") {
    const resumeId = state.diagnosisResumeId || (state.route && state.route.resumeId);
    let content = "";
    if (resumeId) {
      try {
        const resume = await api(`/api/master-resumes/${encodeURIComponent(resumeId)}`);
        content = resume.content || "";
      } catch {
        /* keep diagnosis-only export */
      }
    }
    title = "简历诊断";
    body =
      `<h1>${esc(title)}</h1>` +
      `<div class="resume-doc">${renderMarkdown(buildDiagnosisMarkdown(content))}</div>`;
  }
  printNode.innerHTML = body;
  document.body.classList.add("is-printing");
  try {
    window.print();
  } finally {
    document.body.classList.remove("is-printing");
  }
}

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
  "open-job-detail": (button) => {
    const job = state.jobs.find((item) => item.job_id === button.dataset.id);
    if (job) openJobDetail(job);
  },
  "bulk-move-status": async () => {
    const selected = $$("[data-board-check]:checked").map(
      (input) => input.value,
    );
    const status = $("[data-board-bulk-status]").value;
    if (!selected.length || !status) {
      toast("请先选择岗位和目标状态", "error");
      return;
    }
    const body = await api("/api/jobs/bulk-status", {
      method: "POST",
      body: JSON.stringify({ job_ids: selected, status }),
    });
    toast(
      `批量移动完成：${body.updated} / ${body.total} 条`,
      body.updated === body.total ? "success" : "error",
    );
    render();
  },
  "regenerate-diff": () => regenerateDiff(),
  "goto-selected-job": () => {
    const select = $("[data-wb-job-select]");
    if (select && select.value) navigate("workspace", select.value);
  },
  "back-workspace": () => navigate("workspace"),
  "toggle-raw-jd": () => {
    state.wbRawJdOpen = !state.wbRawJdOpen;
    render();
  },
  "open-command-panel": () => openCommandPanel(),
  "close-command-panel": () => closeCommandPanel(),
  "back-to-jobs": () => navigate("jobs"),
  "go-resumes": () => navigate("resume"),
  "go-jobs": () => navigate("jobs"),
  "reset-settings": async () => {
    await api("/api/settings/reset", { method: "POST" });
    toast("已恢复默认设置", "success");
    render();
  },
  "analyze-jd": async () => {
    try {
      await analyzeActiveJd();
      toast("已开始解析 JD", "success");
    } catch (error) {
      toast(error.message || "JD 解析失败", "error");
    }
  },
  "open-optimizer": (button) => navigate("workspace", button.dataset.id),
  "accept-bullet": async (button) => {
    const jobId = button.dataset.id;
    const diffId = button.dataset.diffId;
    const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    const resumeId = job.workbench_resume_id;
    if (!resumeId) {
      toast("请先运行一次对齐以固定主简历", "error");
      return;
    }
    const resume = await api(`/api/master-resumes/${encodeURIComponent(resumeId)}`);
    const diffs = job.diffs || [];
    const accepted = diffs.filter((diff) => diff.diff_id === diffId);
    const indices = accepted.length
      ? [diffs.indexOf(accepted[0])]
      : [];
    if (!indices.length) {
      toast("该条建议不在当前对齐结果中", "error");
      return;
    }
    let draft = resume.content || "";
    const diff = accepted[0];
    if (diff.type === "modify" && diff.original && diff.proposed) {
      draft = draft.split(diff.original).join(diff.proposed);
    } else if (diff.type === "add" && diff.proposed) {
      draft = `${draft}\n${diff.proposed}`;
    } else if (diff.type === "remove" && diff.original) {
      draft = draft.split(diff.original).join("");
    }
    await api(`/api/jobs/${encodeURIComponent(jobId)}/final-draft`, {
      method: "POST",
      body: JSON.stringify({ draft }),
    });
    toast("已采纳该条优化", "success");
    await refreshOptimizerFromJob(jobId);
  },
  "reject-bullet": async (button) => {
    const jobId = button.dataset.id;
    const diffId = button.dataset.diffId;
    const app = $("#app");
    const card = $(`[data-diff-id="${CSS.escape(diffId)}"]`, app);
    if (card) {
      card.classList.add("is-rejected");
      card.querySelector("[data-diff-actions]").hidden = true;
      toast("已忽略该条建议", "info");
    }
  },
  "polish-bullet": async (button) => {
    const jobId = button.dataset.id;
    const diffId = button.dataset.diffId;
    const instruction = button.dataset.instruction || "quantified";
    button.disabled = true;
    button.textContent = "润色中...";
    try {
      const rewritten = await api(
        `/api/jobs/${encodeURIComponent(jobId)}/workbench/rewrite`,
        {
          method: "POST",
          body: JSON.stringify({ diff_id: diffId, instruction }),
        },
      );
      await refreshOptimizerFromJob(jobId);
      toast("该条已重新润色", "success");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
      button.textContent = "AI 润色";
    }
  },
  "apply-accepted-bullets": async (button) => {
    const jobId = button.dataset.id;
    const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    const resumeId = job.workbench_resume_id;
    const diffs = job.diffs || [];
    if (!resumeId || !diffs.length) {
      toast("没有可应用的对齐结果", "error");
      return;
    }
    const resume = await api(`/api/master-resumes/${encodeURIComponent(resumeId)}`);
    let draft = resume.content || "";
    for (const diff of diffs) {
      if (diff.type === "modify" && diff.original && diff.proposed) {
        draft = draft.split(diff.original).join(diff.proposed);
      } else if (diff.type === "add" && diff.proposed) {
        draft = `${draft}\n${diff.proposed}`;
      } else if (diff.type === "remove" && diff.original) {
        draft = draft.split(diff.original).join("");
      }
    }
    await api(`/api/jobs/${encodeURIComponent(jobId)}/final-draft`, {
      method: "POST",
      body: JSON.stringify({ draft }),
    });
    toast("已应用全部可采纳建议", "success");
    await refreshOptimizerFromJob(jobId);
  },
  "copy-align-markdown": () => copyAlignMarkdown(
    state.route.jobId,
    activeSessionForExport(),
  ),
  "export-align-markdown": () => exportAlignMarkdown(
    state.route.jobId,
    activeSessionForExport(),
  ),
  "export-align-pdf": () => printTarget("workbench"),
  "export-align-json": () => exportAlignJson(
    state.route.jobId,
    activeSessionForExport(),
  ),
  "toggle-theme": () => toggleTheme(),
  "toggle-appraisal-drawer": (button) => toggleAppraisalDrawer(button),
  "set-wb-tab": (button) => setWbMobilePane(button),
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
  "toggle-wb-view": (button) => toggleWbView(button),
  "accept-diffs": () => acceptSelectedDiffs(),
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
  "cancel-batch-align": async () => {
    if (!state.batchAlign) return;
    const batchId = state.batchAlign.batch_id;
    const result = await api(
      `/api/batch-align/${encodeURIComponent(batchId)}/cancel`,
      { method: "POST" },
    );
    stopBatchPolling();
    const batch = await api(`/api/batch-align/${encodeURIComponent(batchId)}`);
    state.batchAlign = batch;
    renderBatchResults(batch);
    const cancel = $("[data-batch-cancel]");
    if (cancel) cancel.hidden = true;
    toast(`已取消 ${result.canceled} 个排队任务`, "success");
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
  if (target.matches("[data-board-select-all]")) {
    $$("[data-board-check]").forEach(
      (input) => (input.checked = target.checked),
    );
    const count = target.checked ? $$("[data-board-check]").length : 0;
    const label = $("[data-board-selected-count]");
    if (label) label.textContent = `已选 ${count}`;
  }
  if (target.matches("[data-board-check]")) {
    const count = $$("[data-board-check]:checked").length;
    const label = $("[data-board-selected-count]");
    if (label) label.textContent = `已选 ${count}`;
  }
  if (target.matches("[data-board-status]")) {
    api("/api/kanban/bulk-status", {
      method: "POST",
      body: JSON.stringify({
        job_ids: [target.dataset.id],
        status: target.value,
        idempotency_key: `fe-select-${target.dataset.id}-${target.value}`,
      }),
    })
      .then(() => {
        toast("岗位状态已更新", "success");
        render();
      })
      .catch((error) => toast(error.message, "error"));
  }
  if (target.matches("[data-job-switcher]") && target.value) {
    navigate("workspace", target.value);
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
    case "command-panel": {
      const session = await confirmCommandPanel();
      if (session && session.session_id) {
        navigate("workspace", session.session_id);
      }
      break;
    }
    case "copilot-filter":
      state.filters = {
        job_function: data.job_function || "",
        seniority: data.seniority || "",
        status: data.status || "",
        search: data.search || "",
      };
      state.offset = 0;
      render();
      break;
    case "split-align": {
      const jobId = data.job_id;
      if (!data.master_resume_id) {
        toast("请先选择主简历", "error");
        return;
      }
      const result = await startAlignmentRun(
        jobId,
        data.master_resume_id,
        data.granularity || "medium",
        data.prompt_focus || "balanced",
      );
      toast(`对齐任务已排队：${result.job_id}`, "success");
      break;
    }
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
    case "job-detail-edit": {
      const payload = {
        status: data.status,
        applied_at: data.applied_at || null,
        next_step: data.next_step || null,
        notes: data.notes || null,
        offer_at: data.offer_at || null,
        rejected_at: data.rejected_at || null,
      };
      await api(`/api/jobs/${encodeURIComponent(data.job_id)}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      toast("岗位时间线已保存", "success");
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
    case "batch-align": {
      const jobIds = $$("[data-batch-check]:checked").map((input) => input.value);
      if (jobIds.length < 2 || jobIds.length > 5) {
        toast("请选择 2-5 个岗位", "error");
        return;
      }
      if (!data.master_resume_id) {
        toast("请选择主简历", "error");
        return;
      }
      const result = await api("/api/batch-align", {
        method: "POST",
        body: JSON.stringify({
          master_resume_id: data.master_resume_id,
          job_ids: jobIds,
          granularity: data.granularity || "fine",
          prompt_focus: "balanced",
          custom_prompt: data.custom_prompt || null,
        }),
      });
      state.batchAlign = result;
      const cancel = $("[data-batch-cancel]");
      if (cancel) cancel.hidden = false;
      startBatchPolling(result.batch_id);
      toast(`已排队 ${result.queued} 个岗位`, "success");
      break;
    }
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
      state.wbCompareView = "list";
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
    case "settings-llm": {
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          llm_provider: data.llm_provider,
          llm_model: data.llm_model,
        }),
      });
      toast("模型已切换，后续任务立即生效", "success");
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
  initTheme();
  initializeCommandPanel();
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
