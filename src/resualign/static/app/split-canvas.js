/* Copilot board + Optimizer split canvas for the 2.0 workstation flow. */

import {
  $,
  STAGE_LABELS,
  api,
  download,
  esc,
  formatDate,
  formatSalary,
  jobStatusLabel,
  state,
  toast,
} from "./events.js";
import {
  PROVENANCE_LABELS,
  alignProgressPercent,
  alignmentControls,
  crawlStatusLine,
  diffCard,
  diffList,
  exportDock,
  formatElapsed,
  highlightSkillGapHtml,
  jdProfileSummary,
  jobCompletenessBadge,
  renderGap,
  renderMatchBadge,
  renderSkills,
  stageStepper,
} from "./format.js";
import { renderAppraisal, renderAppraisalSync } from "./appraisal-panel.js";

let activeSession = null;
let activeSessionUrl = null;
let activeJobId = null;
let activeEventAbort = null;
let activeEventTimer = 0;
let activePollTimer = 0;
let activePollJobId = null;
let fallbackPollTimer = 0;
let fallbackEtag = "";
let alignmentStartedAt = 0;
let workbenchJobs = [];
let autoAnalyzedJd = false;
/* #B4: once the alignment state has been reconciled against the real job
   (terminal status, expired job, or poll terminal), late replayed SSE
   events must not flip the session back to a phantom "running" state. */
let alignmentReconciled = false;

/* Sprint 2 Live Sheet: last draft rendered into [data-live-sheet-pane].
   Used to compute an incremental patch (liveSheetPatch) so accepting a
   bullet updates only the changed lines instead of re-rendering the pane.
   Contract with format.js (agent B, already landed):
   - renderLiveSheetHtml(draft) -> full innerHTML for [data-live-sheet-pane]
     (head + a <div class="live-sheet__paper" data-live-sheet-paper> container;
     non-empty draft renders markdown via renderMarkdown).
   - liveSheetPatch(prevDraft, newDraft) -> { html, rows, addedLines }:
       * rows       —— [{ index, text, added }] non-empty lines by index;
       * addedLines —— Set<number> line indices added vs prevDraft;
       * html       —— full line-row rendering (live-sheet-line--added marks
                       added lines), ready to replace [data-live-sheet-paper].
     Applied by applyLiveSheetPatch: align existing [data-live-line] rows by
     index (add missing / drop removed / update changed text only) when the
     paper already uses the line-row structure, else replace with patch.html;
     added lines get a flash highlight + scroll into view. */
let liveSheetPrevDraft = null;
let liveSheetApiPromise = null;
/* Sprint 2 T3: skill deep-link (#/workspace/<id>?skill=X) pending focus.
   Kept until the gap list actually contains a matching item (the gap may
   arrive via SSE after the first paint). */
let pendingSkillFocus = null;


function renderSplitCanvas(app, session, resumes, jobs = workbenchJobs) {
  const job = (session && session.job) || {};
  const jd = (session && session.jd) || {};
  const gap = (session && session.gap) || {};
  const profile = jd.profile || {};
  const summary = jdProfileSummary(profile);
  const jobId = job.job_id || "";
  /* Mirror the legacy workbench contract so renderFinalDraftPanel /
     record-application work identically on the live canvas. */
  state.wbFinalDraft = job.final_draft
    ? {
        draft: job.final_draft,
        version: job.final_draft_version || 1,
        updated_at: job.final_draft_updated_at,
      }
    : null;
  const previous = {
    resumeId: $("[data-form='split-align'] [name='master_resume_id']")?.value,
    granularity: $("[data-form='split-align'] [name='granularity']")?.value,
    focus: $("[data-form='split-align'] [name='prompt_focus']")?.value,
  };
  const liveSheetDraft =
    (state.wbFinalDraft && state.wbFinalDraft.draft) ||
    (session && session.alignment && session.alignment.draft) ||
    null;
  app.innerHTML = `
    <div class="split-canvas" data-surface-mode="optimizer">
      <div class="page-header page-header--workspace">
        <div>
          <button class="btn btn-ghost btn-sm" data-action="back-to-jobs">← 返回岗位库</button>
          <h2 style="margin-top:6px">${esc(job.title || "岗位工作台")}</h2>
          <div class="sub">${esc(job.company || "未知公司")} · ${esc(job.location || "未知城市")} · ${formatSalary(job)} · ${esc(jobStatusLabel(job.status))} ${jobCompletenessBadge(job)}</div>
        </div>
        <div class="row">
          <select class="workbench-job-switcher" data-job-switcher aria-label="切换岗位">
            ${jobs.map((item) => `<option value="${esc(item.job_id)}" ${item.job_id === jobId ? "selected" : ""}>${esc(item.title)}${item.company ? ` · ${esc(item.company)}` : ""}</option>`).join("")}
          </select>
          ${renderMatchBadge(session, job)}
          ${job.source_url ? `<a class="btn btn-outline btn-sm" href="${esc(job.source_url)}" target="_blank" rel="noopener">原岗位链接</a>` : ""}
        </div>
      </div>
      ${crawlStatusLine(session)}
      ${stageStepper(session)}
      <div class="wb-mobile-tabs segmented" role="tablist" aria-label="工作台面板">
        <button type="button" class="segmented-button" data-action="set-wb-tab" data-wb-tab="controls" aria-selected="${state.wbMobilePane === "controls"}">调优</button>
        <button type="button" class="segmented-button" data-action="set-wb-tab" data-wb-tab="diff" aria-selected="${state.wbMobilePane === "diff"}">结果</button>
        <button type="button" class="segmented-button" data-action="set-wb-tab" data-wb-tab="appraisal" aria-selected="${state.wbMobilePane === "appraisal"}">评估</button>
      </div>
      <!-- Sprint 2 三栏 Workbench：22% Inspector / 48% Visual Diff / 30% Live Sheet。
           列宽由 styles.css 的 .split-layout grid-template-columns 控制（B），
           本模板只声明 data-* 结构标记。移动端（<=900px）单列堆叠由 B 的媒体查询处理。 -->
      <div class="split-layout" data-split-layout>
        <section class="split-pane split-pane--jd ${state.wbMobilePane === "controls" ? "is-active" : ""}" data-wb-pane="controls" data-inspector-pane data-jd-canvas>
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
              ${pendingSkillFocus ? (highlightSkillGapHtml(gap.gap_report || gap, pendingSkillFocus) || "") : (renderGap(gap.gap_report || gap) || "")}
            </div>
          </div>
          <details class="raw-jd-details" data-raw-jd>
            <summary class="small">查看原始 JD</summary>
            <div class="pre raw-jd">${esc(job.jd_text || "")}</div>
          </details>
          <div class="inspector-controls" data-inspector-controls>
            ${alignmentControls(session, resumes, jobId)}
          </div>
        </section>
        <section class="split-pane split-pane--resume split-pane--diff ${state.wbMobilePane === "diff" ? "is-active" : ""}" data-wb-pane="diff" data-diff-pane data-resume-canvas>
          <div class="split-pane__head">
            <div>
              <div class="split-section-title">简历对齐画布</div>
              <div class="small muted">逐条采纳 AI 改写建议，保留来源标记</div>
            </div>
            ${((session && session.alignment && session.alignment.diffs) || []).length ? `<button class="btn btn-ghost btn-sm" type="button" data-action="toggle-live-compare">并排对比</button>` : ""}
          </div>
          ${exportDock(jobId, session)}
          <div class="panel panel-card panel--success final-draft-panel" data-final-draft-panel hidden></div>
          <div class="split-diff-area">${diffList(session, jobId)}</div>
        </section>
        <section class="split-pane split-pane--livesheet" data-live-sheet-pane>
          <div class="split-pane__head">
            <div>
              <div class="split-section-title">实时定稿预览</div>
              <div class="small muted">采纳建议后，此处实时增量更新</div>
            </div>
          </div>
          <div class="live-sheet__paper" data-live-sheet-paper></div>
        </section>
      </div>
      <details class="panel panel-card panel--info appraisal-panel split-appraisal ${state.wbMobilePane === "appraisal" ? "is-active" : ""}" data-wb-pane="appraisal" data-appraisal-panel open>
        <summary>投递价值评估</summary>
        <div class="appraisal-body" data-appraisal-body>
          <div class="muted small">运行一次对齐分析后生成</div>
        </div>
      </details>
    </div>`;
  const form = $("[data-form='split-align']");
  if (form) {
    const resumeSelect = form.querySelector('[name="master_resume_id"]');
    const granularity = form.querySelector('[name="granularity"]');
    const focus = form.querySelector('[name="prompt_focus"]');
    if (previous.resumeId && resumeSelect) resumeSelect.value = previous.resumeId;
    else if (resumeSelect && state.route && state.route.resumeId) {
      /* F4: 深链 #/workspace[/<jobId>]?resume=<id> 预选主简历（用户在画布
       * 上手动切换后 previous.resumeId 优先，不再覆盖用户选择）。 */
      const match = resumes.find(
        (item) => item.resume_id === state.route.resumeId,
      );
      if (match) resumeSelect.value = match.resume_id;
    }
    if (previous.granularity && granularity) granularity.value = previous.granularity;
    if (previous.focus && focus) focus.value = previous.focus;
  }
  renderCanvasExtras();
  /* Sprint 2 T2: 每次画布重绘都同步 Live Sheet（SSE job.result / poll 终态 /
   * 采纳后整画布刷新都会走到这里）。增量 patch 只发生在已填充的 live pane
   * 上（见 syncLiveSheetDraft）；全新画布的 body 为空，这里做整栏填充。 */
  mountLiveSheet(app, liveSheetDraft);
}

/* ------------------------------------------------------------------ */
/* Sprint 2 Live Sheet（实时定稿预览右栏）                              */
/* ------------------------------------------------------------------ */

/* B 契约的懒加载：format.js 由并行 agent B 提供 renderLiveSheetHtml /
 * liveSheetPatch；未合入时用本地 fallback（纯 pre 预览），保证功能可用。
 * 用动态 import 而非静态 import，避免在 B 合入前 imports-check 报缺失导出。 */
function loadLiveSheetApi() {
  if (!liveSheetApiPromise) {
    liveSheetApiPromise = import("./format.js")
      .then((mod) => ({
        renderLiveSheetHtml:
          typeof mod.renderLiveSheetHtml === "function"
            ? mod.renderLiveSheetHtml
            : fallbackLiveSheetHtml,
        liveSheetPatch:
          typeof mod.liveSheetPatch === "function" ? mod.liveSheetPatch : null,
      }))
      .catch(() => ({
        renderLiveSheetHtml: fallbackLiveSheetHtml,
        liveSheetPatch: null,
      }));
  }
  return liveSheetApiPromise;
}

/* 兜底渲染（B 未提供 renderLiveSheetHtml 时）：与契约同构——pane 头部 +
 * [data-live-sheet-paper] 容器，保证 applyLiveSheetPatch 能定位 paper。 */
function fallbackLiveSheetHtml(draft) {
  if (!draft) {
    return `
      <div class="split-pane__head">
        <div>
          <div class="split-section-title">实时定稿预览</div>
          <div class="small muted">采纳建议后，此处实时增量更新</div>
        </div>
      </div>
      <div class="live-sheet__paper" data-live-sheet-paper>
        <div class="muted small">暂无定稿。运行对齐并采纳建议后，将实时预览最终简历。</div>
      </div>`;
  }
  return `
    <div class="split-pane__head">
      <div>
        <div class="split-section-title">实时定稿预览</div>
        <div class="small muted">采纳建议后，此处实时增量更新</div>
      </div>
    </div>
    <div class="live-sheet__paper" data-live-sheet-paper>
      <div class="pre draft-preview">${esc(draft)}</div>
    </div>`;
}

/* 把画布重绘后的空 live pane 填上内容。fresh paper（无行节点）→ 整栏填充；
 * 已填充的 live pane 走 syncLiveSheetDraft 的增量路径。 */
async function mountLiveSheet(app, nextDraft) {
  const pane = $("[data-live-sheet-pane]", app);
  if (!pane) return;
  const api = await loadLiveSheetApi();
  pane.innerHTML = api.renderLiveSheetHtml(nextDraft);
  liveSheetPrevDraft = nextDraft;
}

/* main.js 采纳/应用采纳后调用：对已填充的 [data-live-sheet-pane] 做 DOM
 * 增量更新（按 data-live-line 对齐行、只 patch 变化行 + 高亮新增行），
 * 不整栏重渲染。prevDraft 为 null、draft 未变化或 patch API 缺失时回退为
 * 整栏填充。B 的 liveSheetPatch 返回 { html, rows, addedLines }（见
 * applyLiveSheetPatch）。 */
export async function syncLiveSheetDraft(newDraft, prevDraft) {
  const pane = $("[data-live-sheet-pane]");
  if (!pane) return false;
  /* 未变化：不动 DOM（含首次两者都为 null 的空草稿态）。 */
  if (prevDraft === newDraft) return true;
  const api = await loadLiveSheetApi();
  if (prevDraft !== null && api.liveSheetPatch) {
    const patch = api.liveSheetPatch(prevDraft, newDraft);
    if (patch && applyLiveSheetPatch(pane, patch)) {
      liveSheetPrevDraft = newDraft;
      return true;
    }
  }
  pane.innerHTML = api.renderLiveSheetHtml(newDraft);
  liveSheetPrevDraft = newDraft;
  return true;
}

/* 当前已渲染的 Live Sheet 草稿（采纳流程用它记录 prevDraft）。 */
export function getLiveSheetDraft() {
  return liveSheetPrevDraft;
}

/* 应用 B 的 liveSheetPatch 增量结果 { html, rows, addedLines }：
 * - rows —— [{ index, text, added }]，非空行按 index 排序；
 * - addedLines —— Set<number>，相对 prevDraft 新增的行序号；
 * - html —— 完整行渲染（含 live-sheet-line--added 高亮），可直接替换
 *   [data-live-sheet-paper] 的 innerHTML（B 契约推荐做法）。
 * 策略：paper 已是行结构（data-live-line）时按 rows 序号对齐增量更新
 * （缺的追加、多的移除、文本变化只改该行）；否则（renderLiveSheetHtml
 * 输出的是 markdown 元素）用 html 替换 paper。最后对 added 行加 flash
 * 高亮并滚动到可视区。 */
function applyLiveSheetPatch(pane, patch) {
  const paper = pane.querySelector("[data-live-sheet-paper]");
  if (!paper || !patch) return false;
  const rows = Array.isArray(patch.rows) ? patch.rows : null;
  const html = typeof patch.html === "string" ? patch.html : "";
  const added =
    patch.addedLines instanceof Set ? patch.addedLines : new Set();
  const hasLineRows = paper.querySelector("[data-live-line]") != null;
  if (rows && hasLineRows) {
    const byIndex = new Map(rows.map((row) => [row.index, row]));
    const existing = new Map();
    paper.querySelectorAll("[data-live-line]").forEach((el) => {
      existing.set(Number(el.dataset.liveLine), el);
    });
    /* 移除已不存在的行 */
    for (const [index, el] of existing) {
      if (!byIndex.has(index)) el.remove();
    }
    /* 倒序 upsert：确保新行按 index 顺序插入正确位置 */
    let anchor = null;
    for (let i = rows.length - 1; i >= 0; i--) {
      const row = rows[i];
      let el = existing.get(row.index);
      if (!el) {
        el = document.createElement("div");
        el.className = "live-sheet-line";
        el.setAttribute("data-live-line", String(row.index));
        paper.insertBefore(el, anchor);
      } else if (el.textContent !== row.text) {
        el.textContent = row.text;
      }
      el.classList.toggle("live-sheet-line--added", Boolean(row.added));
      anchor = el;
    }
  } else if (html) {
    paper.innerHTML = html;
  } else {
    return false;
  }
  flashLiveSheetLines(paper);
  if (added.size) {
    const firstAdded = Math.min(...added);
    const el = paper.querySelector(`[data-live-line="${firstAdded}"]`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  return true;
}

/* 新增/变化行加短暂 flash 高亮（3s 后移除；持久高亮 live-sheet-line--added
 * 由 B 在 styles.css 提供）。 */
function flashLiveSheetLines(paper) {
  if (!paper) return;
  paper.querySelectorAll(".live-sheet-line--added").forEach((el) => {
    el.classList.add("live-sheet-line--flash");
  });
  window.setTimeout(() => {
    paper.querySelectorAll(".live-sheet-line--flash").forEach((el) =>
      el.classList.remove("live-sheet-line--flash"),
    );
  }, 3000);
}

/* ------------------------------------------------------------------ */
/* Sprint 2 T3: ?skill= 深链 → Inspector 差距区高亮定位                  */
/* ------------------------------------------------------------------ */

/* 解析 #/workspace/<jobId>?skill=X 的 skill 参数（本地解析，不依赖
 * format.js 的 parseHashValue 是否扩展——参考 state.route.resumeId 的
 * 解析方式，但 skill 由本模块直接读取 location.hash）。 */
function parseSkillFromHash(hash) {
  const value = String(hash || "").replace(/^#\/?/, "");
  const [, queryPart] = value.split("?");
  const query = new URLSearchParams(queryPart || "");
  return query.get("skill") || null;
}

/* 在 Inspector 的差距区定位含该技能的缺口项：模板渲染时已通过 B 的
 * highlightSkillGapHtml 打了 data-match-skill / is-skill-match 标记（当
 * pendingSkillFocus 存在时）；此处做 scrollIntoView + 短暂 flash，并兜底
 * 直接扫 .gap-tag 补标记（幂等）。未命中（gap 尚未就绪）时保持 pending，
 * 随画布重绘重试（renderCanvasExtras）。 */
function tryFocusSkill() {
  if (!pendingSkillFocus) return;
  const skill = pendingSkillFocus;
  const pane = $("[data-inspector-pane]");
  if (!pane) return;
  let matched = pane.querySelector("[data-match-skill]") != null;
  if (!matched) {
    const skillLower = skill.toLowerCase();
    pane.querySelectorAll(".gap-tag").forEach((node) => {
      const text = String(node.textContent || "").trim().toLowerCase();
      if (text === skillLower || text.includes(skillLower)) {
        node.setAttribute("data-match-skill", skill);
        node.classList.add("is-skill-match");
        matched = true;
      }
    });
  }
  if (!matched) return;
  const first = pane.querySelector("[data-match-skill]");
  if (first) {
    first.scrollIntoView({ behavior: "smooth", block: "center" });
    first.classList.add("is-skill-flash");
    /* B 的 styles.css 会为 [data-match-skill] / .is-skill-match 提供持久样式；
     * 这里再加一次短暂内联高亮，保证 B 未合入时冒烟也能肉眼可见。 */
    const prevOutline = first.style.outline;
    const prevBackground = first.style.backgroundColor;
    first.style.outline = "2px solid #f59e0b";
    first.style.backgroundColor = "rgba(245, 158, 11, 0.18)";
    window.setTimeout(() => {
      first.classList.remove("is-skill-flash");
      first.style.outline = prevOutline;
      first.style.backgroundColor = prevBackground;
    }, 4000);
  }
  pendingSkillFocus = null;
}

/* Re-render the cached appraisal body and the final-draft panel after
 * every canvas repaint (SSE events replace #app.innerHTML wholesale, so
 * the panels would otherwise fall back to their placeholder states). */
function renderCanvasExtras() {
  const app = $("#app-router-view");
  if (!app) return;
  renderFinalDraftPanel(app);
  const appraisalPanel = $("[data-appraisal-panel]", app);
  if (appraisalPanel && activeJobId) renderAppraisalSync(appraisalPanel, activeJobId);
  /* T3: 每次画布重绘都尝试 ?skill= 深链定位；gap 未就绪时保持 pending。 */
  tryFocusSkill();
}

/* 定稿面板（与遗留 renderWorkspaceView 的 renderFinalDraftPanel 同构）。
 * 记录投递/导出等按钮复用 main.js 的 document 级 data-action 委托，
 * 无需在 live 画布内重复绑定（B5）。 */
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
      <button class="btn btn-primary btn-sm" data-action="record-application">记录投递</button>
      <button class="btn btn-outline btn-sm" data-action="export-final-draft">导出 PDF</button>
      <button class="btn btn-outline btn-sm" data-action="export-final-draft-md">导出 Markdown</button>
      <button class="btn btn-secondary btn-sm" data-action="save-as-new-resume">另存为新主简历</button>
    </div>`;
}

/* Rehydrate a minimal three-pane session from a persisted library job
   (no live workbench session exists for API/import-created jobs). */
function buildSessionFromJob(job) {
  const profile = job.jd_profile || null;
  return {
    job,
    jd: {
      status: profile ? "ready" : "idle",
      profile,
      summary: job.jd_summary || null,
      error: null,
    },
    gap: job.gap_report || {},
    alignment: {
      status:
        job.alignment_status === "succeeded" ? "succeeded" : "idle",
      stage: job.alignment_status === "succeeded" ? "done" : "",
      error: null,
      diffs: job.diffs || [],
      invalid_diffs: job.invalid_diffs || [],
      draft: job.final_draft || null,
      eval_score: job.eval_score || null,
    },
    meta: {},
  };
}

export async function renderOptimizerCanvas(app, jobId) {
  stopOptimizerStreams();
  /* T3: 解析 #/workspace/<jobId>?skill=X 深链；renderSplitCanvas 重绘后由
   * tryFocusSkill 在 Inspector 差距区高亮定位。 */
  pendingSkillFocus = parseSkillFromHash(window.location.hash);
  autoAnalyzedJd = false;
  workbenchJobs = await api("/api/jobs?limit=200");
  if (!jobId) {    if (workbenchJobs.length) {
      const targetId = workbenchJobs[0].job_id;
      const resumeId = state.route && state.route.resumeId;
      state.route = { name: "workspace", jobId: targetId, resumeId };
      window.history.replaceState(
        null,
        "",
        resumeId
          ? `#/workspace/${encodeURIComponent(targetId)}?resume=${encodeURIComponent(resumeId)}`
          : `#/workspace/${encodeURIComponent(targetId)}`,
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
  let session = await loadSession(jobId);
  if (!session) {
    const existing = workbenchJobs.find((item) => item.job_id === jobId);
    if (existing) {
      /* The job exists but has no workbench session (e.g. created via the
       * API / import). Rehydrate the three-pane canvas from the persisted
       * analysis product (jd_profile / gap_report / diffs) instead of
       * bouncing the user back to the Dashboard. */
      session = buildSessionFromJob(existing);
    } else {
      /* A genuinely stale/removed job id: quietly return to Dashboard. */
      window.location.hash = "#/dashboard";
      return;
    }
  }
  /* #B5: the session job snapshot can be stale (created before the last
     final-draft save); refresh the draft fields from the fresh job list
     so the live canvas renders the current 定稿 + 记录投递 button. */
  const freshJob = workbenchJobs.find((item) => item.job_id === jobId);
  if (freshJob && session.job) {
    session.job = {
      ...session.job,
      final_draft: freshJob.final_draft,
      final_draft_version: freshJob.final_draft_version,
      final_draft_updated_at: freshJob.final_draft_updated_at,
    };
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
  /* 投递价值评估挂到 live 工作台（#B5）：首次进入按需拉取，
     之后的画布重绘由 renderCanvasExtras 用缓存填充，不再重复请求。 */
  renderAppraisal(app);
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
      const app = $("#app-router-view");
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
    /* #B4: the store session never mirrors frontend event interpretation
       of alignment (its alignment stays idle), and any session update
       (e.g. autoAnalyzeJd) bumps the etag. A poll must therefore not let
       a stale "idle" alignment resurrect a locally reconciled terminal
       task (failed/canceled/succeeded). */
    if (
      activeSession &&
      activeSession.alignment &&
      ["failed", "canceled", "succeeded"].includes(
        activeSession.alignment.status,
      ) &&
      updated.alignment &&
      !["failed", "canceled", "succeeded"].includes(updated.alignment.status)
    ) {
      updated.alignment = { ...updated.alignment, ...activeSession.alignment };
    }
    activeSession = updated;
    const app = $("#app-router-view");
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
      if (alignmentReconciled) return;
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
        draft: data.result.draft || activeSession.alignment?.draft || null,
        eval_score: data.result.eval_score || null,
      };
    }
  }
  const app = $("#app-router-view");
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
  alignmentReconciled = false;
  activeSession = null;
  activeSessionUrl = null;
  activeJobId = null;
  autoAnalyzedJd = false;
  pendingSkillFocus = null;
  liveSheetPrevDraft = null;
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
    /* The pinned analysis job was cleaned up (TTL). Keep the canvas open
     * with the persisted data and let the user rerun alignment; never
     * bounce a valid job's workspace back to the Dashboard. */
    stopAlignmentPoll();
    return;
  }
  if (snapshot.status === "failed" || snapshot.status === "canceled") {
    /* Terminal job: surface the failure instead of replaying "running". */
    setAlignmentTerminal(snapshot);
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

/* Reset the alignment state to a terminal status (failed/canceled) and
 * repaint, so the run button becomes usable again ("重新运行对齐"). */
function setAlignmentTerminal(snapshot) {
  stopAlignmentPoll();
  alignmentReconciled = true;
  if (!activeSession) return;
  const status = snapshot.status === "canceled" ? "canceled" : "failed";
  activeSession.alignment = {
    ...(activeSession.alignment || {}),
    status,
    stage: status,
    error:
      snapshot.error ||
      (status === "canceled" ? "对齐任务已取消" : "对齐任务失败，请重新运行"),
    diffs: (snapshot.result && snapshot.result.diffs) || [],
    invalid_diffs: (snapshot.result && snapshot.result.invalid_diffs) || [],
    draft: (snapshot.result && snapshot.result.draft) || activeSession.alignment?.draft || null,
    eval_score: (snapshot.result && snapshot.result.eval_score) || null,
  };
  rerenderActiveCanvas();
  toast(
    status === "canceled"
      ? "对齐任务已取消"
      : "对齐任务失败或已过期，可重新运行",
    status === "canceled" ? "info" : "error",
  );
}

async function rerenderActiveCanvas() {
  if (!activeSession) return;
  const app = $("#app-router-view");
  if (!app) return;
  let resumes = [];
  try {
    resumes = await api("/api/master-resumes");
  } catch {
    /* keep the empty list; the canvas still renders */
  }
  renderSplitCanvas(app, activeSession, resumes, workbenchJobs);
}

/* Cancel the active alignment task. Backend cancel only applies to queued
 * jobs; for running jobs we stop the local wait and release the form so
 * the user can retry (#B4). */
export async function cancelActiveAlignment() {
  const jobId = activePollJobId;
  if (!jobId) {
    toast("当前没有可取消的对齐任务", "error");
    return;
  }
  let snapshot;
  try {
    snapshot = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
  } catch {
    stopAlignmentPoll();
    window.location.hash = "#/dashboard";
    return;
  }
  if (!["queued", "running"].includes(snapshot.status)) {
    toast("当前没有可取消的对齐任务", "error");
    return;
  }
  if (snapshot.status === "queued") {
    try {
      await api(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {
        method: "POST",
      });
      setAlignmentTerminal({ status: "canceled", error: null });
      toast("对齐任务已取消", "success");
    } catch (error) {
      toast(error.message, "error");
    }
    return;
  }
  /* running: cancel is a no-op server-side; stop local waiting and reset
     to idle so the workspace is not stuck with a disabled run button. */
  stopAlignmentPoll();
  alignmentReconciled = false;
  if (activeSession) {
    activeSession.alignment = {
      ...(activeSession.alignment || {}),
      status: "idle",
      stage: "",
      error: null,
    };
    rerenderActiveCanvas();
  }
  toast("任务运行中无法中断，已停止本地等待", "info");
}

export async function startAlignmentRun(jobId, resumeId, granularity, focus, runEval) {
  const payload = {
    master_resume_id: resumeId,
    granularity: granularity || "medium",
    prompt_focus: focus || "balanced",
  };
  /* F1: per-run 评估开关，勾选传 true，不勾选不传（None 回退全局默认）。 */
  if (runEval !== undefined) payload.run_eval = runEval;
  const result = await api(`/api/jobs/${encodeURIComponent(jobId)}/workbench`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  alignmentReconciled = false;
  if (activeSession) {
    activeSession.alignment = {
      ...(activeSession.alignment || {}),
      status: "queued",
      stage: "queued",
      error: null,
    };
    const app = $("#app-router-view");
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
  const app = $("#app-router-view");
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
    const app = $("#app-router-view");
    if (activeSession && app) {
      activeSession.alignment = {
        status: snapshot.status === "succeeded" ? "succeeded" : snapshot.status === "failed" ? "failed" : "running",
        stage: snapshot.stage || snapshot.status || "",
        error: snapshot.error || null,
        diffs: (snapshot.result && snapshot.result.diffs) || [],
        invalid_diffs: (snapshot.result && snapshot.result.invalid_diffs) || [],
        draft: (snapshot.result && snapshot.result.draft) || activeSession.alignment?.draft || null,
        eval_score: (snapshot.result && snapshot.result.eval_score) || null,
      };
      if (["succeeded", "failed", "canceled"].includes(snapshot.status)) {
        stopAlignmentPoll();
        alignmentReconciled = true;
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
        elapsed.textContent = formatElapsed(
          alignmentStartedAt ? Date.now() - alignmentStartedAt : 0,
        );
      }
      const runButton = $("[data-align-run]");
      if (runButton) runButton.disabled = true;
    }
  } catch {
    /* #B4: a poll failure mid-flight must not leave the workspace stuck
     * in "running" with no recovery path. */
    stopAlignmentPoll();
    alignmentReconciled = true;
    if (activeSession) {
      activeSession.alignment = {
        ...(activeSession.alignment || {}),
        status: "failed",
        stage: "failed",
        error: "对齐任务查询失败，请重试",
      };
      rerenderActiveCanvas();
    }
    toast("对齐任务查询失败，请重试", "error");
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
