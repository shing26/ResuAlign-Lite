/* Copilot board + Optimizer split canvas for the 2.0 workstation flow. */

import {
  $,
  $$,
  JOB_STATUS_CANONICAL,
  JOB_STATUS_LABELS,
  STAGE_LABELS,
  api,
  canonicalJobStatus,
  download,
  ensureVocabulary,
  esc,
  formatSalary,
  jobStatusLabel,
  state,
  toast,
} from "./events.js";
import {
  PROVENANCE_LABELS,
  alignProgressPercent,
  alignmentControls,
  boardCard,
  crawlStatusLine,
  diffCard,
  diffList,
  exportDock,
  jdProfileSummary,
  matchTone,
  radarHtml,
  renderGap,
  renderSkills,
  stageStepper,
} from "./format.js";

let activeSession = null;
let activeSessionUrl = null;
let activeJobId = null;
let activeEventAbort = null;
let activeEventTimer = 0;
let activePollTimer = 0;
let activePollJobId = null;
let fallbackPollTimer = 0;
let fallbackEtag = "";
let draggingJobId = null;
let alignmentStartedAt = 0;
let workbenchJobs = [];
let autoAnalyzedJd = false;
let canvasRenderHooks = [];

/* Render hooks let main.js attach extras (batch panel, etc.) after a
   canvas view is painted. Kept as a list so future views can register
   their own post-render work without touching this module. */
export function setCanvasRenderHook(fn) {
  if (typeof fn === "function") canvasRenderHooks.push(fn);
}

function renderSplitCanvas(app, session, resumes, jobs = workbenchJobs) {
  const job = (session && session.job) || {};
  const jd = (session && session.jd) || {};
  const gap = (session && session.gap) || {};
  const profile = jd.profile || {};
  const summary = jdProfileSummary(profile);
  const score = gap.score != null ? gap.score : job.match_score;
  const jobId = job.job_id || "";
  const previous = {
    resumeId: $("[data-form='split-align'] [name='master_resume_id']")?.value,
    granularity: $("[data-form='split-align'] [name='granularity']")?.value,
    focus: $("[data-form='split-align'] [name='prompt_focus']")?.value,
  };
  app.innerHTML = `
    <div class="split-canvas" data-surface-mode="optimizer">
      <div class="page-header page-header--workspace">
        <div>
          <button class="btn btn-ghost btn-sm" data-action="back-to-jobs">← 返回岗位库</button>
          <h2 style="margin-top:6px">${esc(job.title || "岗位工作台")}</h2>
          <div class="sub">${esc(job.company || "未知公司")} · ${esc(job.location || "未知城市")} · ${formatSalary(job)} · ${esc(jobStatusLabel(job.status))}</div>
        </div>
        <div class="row">
          <select class="workbench-job-switcher" data-job-switcher aria-label="切换岗位">
            ${jobs.map((item) => `<option value="${esc(item.job_id)}" ${item.job_id === jobId ? "selected" : ""}>${esc(item.title)}${item.company ? ` · ${esc(item.company)}` : ""}</option>`).join("")}
          </select>
          ${score != null ? `<span class="match-badge ${matchTone(score)}" data-match-badge>匹配 ${Math.round(score)}</span>` : ""}
          ${job.source_url ? `<a class="btn btn-outline btn-sm" href="${esc(job.source_url)}" target="_blank" rel="noopener">原岗位链接</a>` : ""}
        </div>
      </div>
      ${crawlStatusLine(session)}
      ${stageStepper(session)}
      <div class="split-layout">
        <section class="split-pane split-pane--jd" data-jd-canvas>
          <div class="split-pane__head">
            <div>
              <div class="split-section-title">JD 智能解析</div>
              <div class="small muted">${jd.status === "ready" ? "画像已就绪" : jd.status === "failed" ? `分析失败：${esc(jd.error || "")}` : "正在提取岗位画像..."}</div>
            </div>
            <div class="row">
              ${jd.status === "ready" ? `<button class="btn btn-ghost btn-sm" data-action="toggle-raw-jd" type="button">原文</button>` : ""}
              ${!jd.profile ? `<button class="btn btn-primary btn-sm" data-action="analyze-jd" type="button" ${jd.status === "queued" || jd.status === "running" ? "disabled" : ""}>${jd.status === "queued" || jd.status === "running" ? "解析中..." : jd.status === "failed" ? "重试解析" : "解析 JD"}</button>` : ""}
            </div>
          </div>
          ${jd.status === "ready" && summary ? `
            <div class="jd-summary" data-jd-summary>
              <div class="jd-summary__title">${esc(summary.title)}</div>
              <div class="row">${summary.seniority ? `<span class="badge badge-gray">${esc(summary.seniority)}</span>` : ""}${summary.education.length ? `<span class="badge badge-gray">${esc(summary.education.join(" / "))}</span>` : ""}</div>
              ${summary.summary ? `<div class="small jd-summary__text">${esc(String(summary.summary).slice(0, 220))}</div>` : ""}
            </div>` : jd.status === "failed" ? `<div class="jd-error" role="alert">无法完成岗位画像，可点击右上角重试。</div>` : `<div class="split-skeleton is-shimmer">解析中</div>`}
          <div class="split-bento">
            <div class="split-bento__cell">${renderSkills(profile)}</div>
            <div class="split-bento__cell">
              <div class="split-section-title">岗位差距</div>
              ${renderGap(gap.gap_report || gap)}
            </div>
          </div>
          <details class="raw-jd-details" data-raw-jd>
            <summary class="small">查看原始 JD</summary>
            <div class="pre raw-jd">${esc(job.jd_text || "")}</div>
          </details>
        </section>
        <section class="split-pane split-pane--resume" data-resume-canvas>
          <div class="split-pane__head">
            <div>
              <div class="split-section-title">简历对齐画布</div>
              <div class="small muted">逐条采纳 AI 改写建议，保留来源标记</div>
            </div>
          </div>
          ${alignmentControls(session, resumes, jobId)}
          ${exportDock(jobId, session)}
          <div class="split-pane__match">${score != null ? radarHtml(score) : `<div class="small muted" style="padding:10px 0">运行预分析后生成匹配雷达。</div>`}</div>
          <div class="split-diff-area">${diffList(session, jobId)}</div>
        </section>
      </div>
    </div>`;
  const form = $("[data-form='split-align']");
  if (form) {
    const resumeSelect = form.querySelector('[name="master_resume_id"]');
    const granularity = form.querySelector('[name="granularity"]');
    const focus = form.querySelector('[name="prompt_focus"]');
    if (previous.resumeId && resumeSelect) resumeSelect.value = previous.resumeId;
    if (previous.granularity && granularity) granularity.value = previous.granularity;
    if (previous.focus && focus) focus.value = previous.focus;
  }
}

export async function renderOptimizerCanvas(app, jobId) {
  stopOptimizerStreams();
  autoAnalyzedJd = false;
  workbenchJobs = await api("/api/jobs?limit=200");
  if (!jobId) {
    if (workbenchJobs.length) {
      const targetId = workbenchJobs[0].job_id;
      state.route = { name: "workspace", jobId: targetId };
      window.history.replaceState(
        null,
        "",
        `#/workspace/${encodeURIComponent(targetId)}`,
      );
      return renderOptimizerCanvas(app, targetId);
    }
    const resumes = await api("/api/master-resumes");
    app.innerHTML = `
      <div class="page-header page-header--workspace"><div><h2>单岗位工作台</h2>
        <div class="sub">从岗位库选择岗位，或使用顶部万能输入直接创建新岗位</div></div></div>
      <div class="panel panel-card">
        <div class="field"><label>选择岗位</label>
          <select data-wb-job-select>
            <option value="">${workbenchJobs.length ? "选择岗位..." : "岗位库为空，先粘贴一个 JD 吧"}</option>
            ${workbenchJobs.map((item) => `<option value="${esc(item.job_id)}">${esc(item.title)} · ${esc(item.company || "")}</option>`).join("")}
          </select></div>
        <div class="row" style="margin-top:10px">
          ${workbenchJobs.length ? '<button class="btn btn-primary" data-action="goto-selected-job">进入工作台</button>' : '<button class="btn btn-primary" data-action="open-command-panel">粘贴 JD / 链接</button>'}
        </div>
      </div>`;
    return;
  }
  const session = await loadSession(jobId);
  if (!session) {
    app.innerHTML = `<div class="panel panel-card"><h3>工作台会话不存在</h3><p class="muted">岗位可能已删除或会话已过期。</p><div class="row"><button class="btn btn-primary" data-action="back-to-jobs">返回岗位库</button></div></div>`;
    return;
  }
  activeSession = session;
  activeSessionUrl = session.meta && session.meta.event_url;
  activeJobId = (session.job && session.job.job_id) || jobId;
  state.wbJob = session.job || state.wbJob;
  const resumes = await api("/api/master-resumes");
  renderSplitCanvas(app, session, resumes, workbenchJobs);
  startPollingFallback(session);
  startEventStream(session);
  resumeAlignmentProgress();
  autoAnalyzeJd(session);
}

async function autoAnalyzeJd(session) {
  if (autoAnalyzedJd || !session || !session.session_id) return;
  const jd = session.jd || {};
  const job = session.job || {};
  if (
    jd.profile ||
    jd.status === "queued" ||
    jd.status === "running" ||
    jd.status === "failed" ||
    !(job.jd_text || "").trim()
  ) {
    return;
  }
  autoAnalyzedJd = true;
  try {
    await api(
      `/api/workbench/session/${encodeURIComponent(session.session_id)}/analyze`,
      { method: "POST" },
    );
    if (activeSession) {
      activeSession.jd = {
        ...(activeSession.jd || {}),
        status: "queued",
        error: null,
      };
      activeSession.gap = {
        ...(activeSession.gap || {}),
        status: "queued",
        error: null,
      };
      const app = $("#app");
      if (app) {
        const resumes = await api("/api/master-resumes");
        renderSplitCanvas(app, activeSession, resumes, workbenchJobs);
      }
    }
  } catch {
    /* keep the manual "解析 JD" button available for retry */
  }
}

async function loadSession(jobId) {
  try {
    const session = await api(`/api/workbench/session/${encodeURIComponent(jobId)}`);
    if (session && session.session_id) return session;
  } catch {
    /* fall through to workspace session */
  }
  try {
    return await api(`/api/workspace/session/${encodeURIComponent(jobId)}`);
  } catch {
    return null;
  }
}

function startEventStream(session) {
  if (!session || !session.meta || !session.meta.event_url) return;
  stopEventStream();
  const controller = new AbortController();
  activeEventAbort = controller;
  const url = session.meta.event_url.startsWith("http")
    ? session.meta.event_url
    : `${window.location.origin}${session.meta.event_url}`;
  const headers = state.token ? { Authorization: `Bearer ${state.token}` } : {};
  fetch(url, { headers, signal: controller.signal })
    .then(async (response) => {
      if (!response.ok || !response.body) return;
      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      let eventName = "message";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() || "";
        for (const block of blocks) {
          let data = "";
          for (const line of block.split("\n")) {
            if (line.startsWith("event:")) eventName = line.slice(6).trim();
            if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          if (data) {
            try {
              handleEvent(eventName, JSON.parse(data));
            } catch {
              /* skip malformed event */
            }
            eventName = "message";
          }
        }
      }
    })
    .catch((error) => {
      if (error.name !== "AbortError" && activeEventAbort === controller) {
        scheduleReconnect();
      }
    });
}

function startPollingFallback(session) {
  stopPollingFallback();
  if (!session || !session.session_id) return;
  fallbackEtag = (session.meta && session.meta.etag) || "";
  fallbackPollTimer = window.setInterval(() => pollSessionFallback(session.session_id), 2500);
  pollSessionFallback(session.session_id);
}

function stopPollingFallback() {
  if (fallbackPollTimer) {
    window.clearInterval(fallbackPollTimer);
    fallbackPollTimer = 0;
  }
  fallbackEtag = "";
}

async function pollSessionFallback(sessionId) {
  if (!fallbackPollTimer || !activeSession) return;
  try {
    const headers = state.token
      ? { Authorization: `Bearer ${state.token}` }
      : {};
    if (fallbackEtag) headers["If-None-Match"] = fallbackEtag;
    const response = await fetch(
      `/api/workbench/session/${encodeURIComponent(sessionId)}`,
      { headers },
    );
    if (response.status === 304) return;
    if (!response.ok) return;
    const updated = await response.json();
    const nextEtag = updated.meta && updated.meta.etag;
    if (nextEtag === fallbackEtag) return;
    fallbackEtag = nextEtag || "";
    activeSession = updated;
    const app = $("#app");
    if (app) {
      const resumes = await api("/api/master-resumes");
      renderSplitCanvas(app, activeSession, resumes, workbenchJobs);
    }
  } catch {
    /* keep the timer running; the next tick retries */
  }
}

function scheduleReconnect() {
  if (activeEventTimer) window.clearTimeout(activeEventTimer);
  activeEventTimer = window.setTimeout(() => {
    activeEventTimer = 0;
    if (activeSession && activeSession.meta && activeSession.meta.event_url) {
      startEventStream(activeSession);
    }
  }, 2500);
}

function stopEventStream() {
  if (activeEventAbort) activeEventAbort.abort();
  activeEventAbort = null;
  if (activeEventTimer) {
    window.clearTimeout(activeEventTimer);
    activeEventTimer = 0;
  }
}

function handleEvent(eventName, data) {
  if (!activeSession) return;
  if (eventName === "heartbeat") return;
  if (eventName === "crawl.status") {
    activeSession.crawl = { ...(activeSession.crawl || {}), ...data };
    if (data.job_id) {
      activeSession.job = { ...(activeSession.job || {}), job_id: data.job_id };
    }
  } else if (eventName === "job.stage") {
    if (data.job_id && (!activeSession.job || !activeSession.job.job_id)) {
      activeSession.job = { ...(activeSession.job || {}), job_id: data.job_id };
    }
    if (data.workbench) {
      activeSession.alignment = {
        ...(activeSession.alignment || {}),
        status: "running",
        stage: data.stage || "",
        message: data.message || "",
      };
    } else {
      activeSession.jd = {
        ...(activeSession.jd || {}),
        status: "queued",
        error: null,
      };
      activeSession.gap = {
        ...(activeSession.gap || {}),
        status: "queued",
        error: null,
      };
    }
  } else if (eventName === "job.gap_ready") {
    if (data.job_id) {
      activeSession.job = { ...(activeSession.job || {}), job_id: data.job_id };
    }
    activeSession.jd = {
      profile: data.jd_profile || null,
      status: "ready",
      error: null,
    };
    activeSession.gap = {
      status: data.status === "blocked" ? "blocked" : "ready",
      score: data.gap_report ? null : null,
      gap_report: data.gap_report || null,
      cache_hit: Boolean(data.cache_hit),
      error: null,
    };
    if (data.gap_report) {
      const missing = (data.gap_report.missing_keywords || []).length;
      activeSession.gap.score = missing ? Math.max(30, 100 - missing * 15) : 90;
    }
  } else if (eventName === "job.error") {
    activeSession.status = "failed";
    activeSession.error = data.error;
  } else if (eventName === "job.result") {
    if (data.job_id) {
      activeSession.job = { ...(activeSession.job || {}), job_id: data.job_id };
    }
    if (data.result) {
      activeSession.alignment = {
        status: "succeeded",
        stage: "done",
        diffs: data.result.diffs || [],
        invalid_diffs: data.result.invalid_diffs || [],
        draft: data.result.draft || null,
        eval_score: data.result.eval_score || null,
      };
    }
  }
  const app = $("#app");
  if (app) {
    api("/api/master-resumes")
      .then((resumes) =>
        renderSplitCanvas(app, activeSession, resumes, workbenchJobs),
      )
      .catch(() =>
        renderSplitCanvas(app, activeSession, [], workbenchJobs),
      );
  }
}

function stopOptimizerStreams() {
  stopEventStream();
  stopPollingFallback();
  if (activePollTimer) {
    window.clearInterval(activePollTimer);
    activePollTimer = 0;
  }
  activePollJobId = null;
  alignmentStartedAt = 0;
  activeSession = null;
  activeSessionUrl = null;
  activeJobId = null;
  autoAnalyzedJd = false;
}

async function resumeAlignmentProgress() {
  const job = activeSession && activeSession.job;
  const analysisId = job && job.workbench_job_id;
  if (!analysisId) return;
  if (
    activeSession.alignment &&
    activeSession.alignment.status === "succeeded"
  ) {
    return;
  }
  let snapshot;
  try {
    snapshot = await api(`/api/jobs/${encodeURIComponent(analysisId)}`);
  } catch {
    return;
  }
  if (["queued", "running"].includes(snapshot.status)) {
    activePollJobId = analysisId;
    alignmentStartedAt = Date.now();
    if (activePollTimer) window.clearInterval(activePollTimer);
    activePollTimer = window.setInterval(() => pollAlignmentJob(), 1000);
    pollAlignmentJob();
  }
}

export async function startAlignmentRun(jobId, resumeId, granularity, focus) {
  const result = await api(`/api/jobs/${encodeURIComponent(jobId)}/workbench`, {
    method: "POST",
    body: JSON.stringify({
      master_resume_id: resumeId,
      granularity: granularity || "medium",
      prompt_focus: focus || "balanced",
    }),
  });
  if (activeSession) {
    activeSession.alignment = {
      ...(activeSession.alignment || {}),
      status: "queued",
      stage: "queued",
      error: null,
    };
    const app = $("#app");
    if (app) {
      const resumes = await api("/api/master-resumes");
      renderSplitCanvas(app, activeSession, resumes, workbenchJobs);
    }
  }
  activePollJobId = result.job_id;
  alignmentStartedAt = Date.now();
  if (activePollTimer) window.clearInterval(activePollTimer);
  activePollTimer = window.setInterval(() => pollAlignmentJob(), 1000);
  pollAlignmentJob();
  return result;
}

export async function analyzeActiveJd() {
  const session = activeSession;
  if (!session || !session.session_id) return;
  const jd = session.jd || {};
  if (jd.status === "queued" || jd.status === "running" || jd.profile) return;
  await api(
    `/api/workbench/session/${encodeURIComponent(session.session_id)}/analyze`,
    { method: "POST" },
  );
  activeSession.jd = { ...jd, status: "queued", error: null };
  activeSession.gap = {
    ...(activeSession.gap || {}),
    status: "queued",
    error: null,
  };
  const app = $("#app");
  if (app) {
    renderSplitCanvas(
      app,
      activeSession,
      await api("/api/master-resumes"),
      workbenchJobs,
    );
  }
}

async function pollAlignmentJob() {
  const jobId = activePollJobId;
  if (!jobId) return;
  try {
    const snapshot = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    const app = $("#app");
    if (activeSession && app) {
      activeSession.alignment = {
        status: snapshot.status === "succeeded" ? "succeeded" : snapshot.status === "failed" ? "failed" : "running",
        stage: snapshot.stage || snapshot.status || "",
        error: snapshot.error || null,
        diffs: (snapshot.result && snapshot.result.diffs) || [],
        invalid_diffs: (snapshot.result && snapshot.result.invalid_diffs) || [],
        draft: (snapshot.result && snapshot.result.draft) || null,
        eval_score: (snapshot.result && snapshot.result.eval_score) || null,
      };
      if (["succeeded", "failed", "canceled"].includes(snapshot.status)) {
        stopAlignmentPoll();
        if (snapshot.status === "succeeded") {
          const reloadTarget =
            activeJobId ||
            activeSession.session_id ||
            (activeSession.job && activeSession.job.job_id);
          const session = await loadSession(reloadTarget);
          if (session) activeSession = session;
          activeJobId = (session.job && session.job.job_id) || activeJobId;
          const resumes = await api("/api/master-resumes");
          renderSplitCanvas(app, activeSession, resumes, workbenchJobs);
          toast("对齐分析完成", "success");
        } else {
          renderSplitCanvas(
            app,
            activeSession,
            await api("/api/master-resumes"),
            workbenchJobs,
          );
          toast(
            snapshot.error || `对齐任务：${snapshot.status}`,
            snapshot.status === "failed" ? "error" : "info",
          );
        }
        return;
      }
      const statusNode = $("[data-align-status]");
      const stageKey = snapshot.stage || snapshot.status || "";
      if (statusNode) {
        statusNode.textContent = `正在生成：${
          STAGE_LABELS[stageKey] || stageKey || "..."
        }`;
      }
      const stageNode = $("[data-align-stage]");
      if (stageNode) {
        stageNode.textContent = STAGE_LABELS[stageKey] || stageKey || "正在生成";
      }
      const fill = $(".align-progress__fill");
      if (fill) fill.style.width = `${alignProgressPercent(stageKey)}%`;
      const elapsed = $("[data-align-elapsed]");
      if (elapsed) {
        elapsed.textContent = alignmentStartedAt
          ? `${Math.round((Date.now() - alignmentStartedAt) / 1000)}s`
          : "";
      }
      const runButton = $("[data-align-run]");
      if (runButton) runButton.disabled = true;
    }
  } catch {
    stopAlignmentPoll();
  }
}

function stopAlignmentPoll() {
  if (activePollTimer) {
    window.clearInterval(activePollTimer);
    activePollTimer = 0;
  }
  activePollJobId = null;
  alignmentStartedAt = 0;
}

export function closeSplitCanvas() {
  stopOptimizerStreams();
}

export function activeSessionForExport() {
  return activeSession;
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

export async function renderCopilotBoard(app) {
  stopOptimizerStreams();
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
    <form class="panel panel-card filter-bar" data-form="copilot-filter">
      <div class="field"><label>关键词</label><input type="search" name="search" value="${esc(state.filters.search)}" placeholder="标题 / 公司 / JD"></div>
      <div class="field"><label>职能</label><select name="job_function"><option value="">全部</option>${vocabulary.job_functions.map((value) => `<option value="${esc(value)}" ${value === state.filters.job_function ? "selected" : ""}>${esc(value)}</option>`).join("")}</select></div>
      <div class="field"><label>级别</label><select name="seniority"><option value="">全部</option>${vocabulary.seniorities.map((value) => `<option value="${esc(value)}" ${value === state.filters.seniority ? "selected" : ""}>${esc(value)}</option>`).join("")}</select></div>
      <div class="field"><label>状态</label><select name="status"><option value="">全部</option>${statuses.map((value) => `<option value="${esc(value)}" ${value === state.filters.status ? "selected" : ""}>${esc(value)}</option>`).join("")}</select></div>
      <button class="btn btn-secondary" type="submit">筛选</button>
      <button class="btn btn-ghost" type="button" data-action="clear-filters">清空</button>
    </form>
    <div class="board-toolbar panel panel-card">
      <span class="small muted">拖拽卡片到目标列，或使用卡片内下拉菜单（键盘可达）。</span>
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

function bindBoardDrag(root) {
  $$("[data-board-drag]", root).forEach((card) => {
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
        renderCopilotBoard($("#app"));
      } catch (error) {
        toast(error.message, "error");
      }
    });
  });
}

export function copyAlignMarkdown(jobId, session) {
  const alignment = (session && session.alignment) || {};
  const job = (session && session.job) || {};
  const diffs = alignment.diffs || [];
  const lines = [
    `# ${job.title || "对齐简历"}`,
    "",
    `> 匹配度：${alignment.eval_score && alignment.eval_score.jd_match_score != null ? alignment.eval_score.jd_match_score : session && session.gap && session.gap.score != null ? session.gap.score : "-"}/100`,
    "",
    "## 对齐内容",
    "",
    alignment.draft || "（尚未生成定稿）",
    "",
    "## 修改建议",
    "",
    ...diffs.map(
      (diff, index) =>
        `${index + 1}. [${diff.type || "modify"}] ${diff.reason || ""}${diff.provenance_state ? `（${PROVENANCE_LABELS[diff.provenance_state] || diff.provenance_state}）` : ""}`,
    ),
  ];
  const text = lines.join("\n");
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(
      () => toast("Markdown 已复制", "success"),
      () => fallbackCopy(text),
    );
  } else {
    fallbackCopy(text);
  }
}

export function exportAlignMarkdown(jobId, session) {
  const alignment = (session && session.alignment) || {};
  const job = (session && session.job) || {};
  const diffs = alignment.diffs || [];
  const match =
    (alignment.eval_score && alignment.eval_score.jd_match_score) ||
    (session && session.gap && session.gap.score) ||
    "-";
  const content = [
    `# ${job.title || "对齐简历"}`,
    "",
    `> 匹配度：${match}/100`,
    "",
    "## 对齐内容",
    "",
    alignment.draft || "（尚未生成定稿）",
    "",
    "## 修改建议",
    "",
    ...diffs.map(
      (diff, index) =>
        `${index + 1}. [${diff.type || "modify"}] ${diff.reason || ""}${diff.provenance_state ? `（${PROVENANCE_LABELS[diff.provenance_state] || diff.provenance_state}）` : ""}`,
    ),
  ].join("\n");
  download(
    `resualign-${job.title || "job"}.md`,
    content,
    "text/markdown;charset=utf-8",
  );
}

function fallbackCopy(text) {
  const node = document.createElement("textarea");
  node.value = text;
  node.style.position = "fixed";
  node.style.opacity = "0";
  document.body.append(node);
  node.select();
  try {
    document.execCommand("copy");
    toast("Markdown 已复制", "success");
  } catch {
    toast("复制失败，请手动选择", "error");
  }
  node.remove();
}

export function exportAlignJson(jobId, session) {
  const job = (session && session.job) || {};
  download(
    `resualign-${job.title || "job"}.json`,
    JSON.stringify(session, null, 2),
    "application/json",
  );
}
