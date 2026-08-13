/* Copilot board + Optimizer split canvas for the 2.0 workstation flow. */

import {
  APP_STATUS_LABELS,
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
  jobApplyLinkHtml,
  jobCompletenessBadge,
  renderGap,
  renderMatchBadge,
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
let activeAuxPane = "inspector";


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
  const alignment = (session && session.alignment) || {};
  const alignmentRunning =
    alignment.status === "running" || alignment.status === "queued";
  const diffs = Array.isArray(alignment.diffs) ? alignment.diffs : [];
  const acceptedIds = new Set((state.wbAcceptedBullets || {})[jobId] || []);
  const acceptedCount = diffs.filter(
    (diff) =>
      acceptedIds.has(diff.diff_id) || diff.provenance_state === "accepted",
  ).length;
  const pendingCount = Math.max(0, diffs.length - acceptedCount);
  const matchScore =
    (alignment.eval_score && alignment.eval_score.jd_match_score) ||
    gap.score ||
    job.match_score ||
    null;
  const requiredSkills = Array.isArray(profile.required_skills)
    ? profile.required_skills
    : [];
  const niceSkills = Array.isArray(profile.nice_to_have_skills)
    ? profile.nice_to_have_skills
    : [];
  const tagItems = [...requiredSkills.slice(0, 6), ...niceSkills.slice(0, 3)];
  const inspectorActive = activeAuxPane === "inspector" || state.wbMobilePane !== "diff";
  const livesheetActive = activeAuxPane === "livesheet" || state.wbMobilePane === "diff";
  const dutyText = String(
    (summary && summary.summary) || job.jd_text || "",
  ).trim().slice(0, 240);
  app.innerHTML = `
    <div class="view view-fit workbench-view" data-surface-mode="optimizer">
      ${crawlStatusLine(session)}
      <div class="wb-mobile-tabs" role="tablist" aria-label="工作台面板">
        <button type="button" class="segmented-button seg" data-action="set-wb-tab" data-wb-tab="controls" aria-selected="${state.wbMobilePane === "controls"}">调优</button>
        <button type="button" class="segmented-button seg" data-action="set-wb-tab" data-wb-tab="diff" aria-selected="${state.wbMobilePane === "diff"}">结果</button>
      </div>
      <div class="wb-context">
        <div class="wb-context-main">
          <div class="wb-context-title">
            <span class="context-kicker">目标岗位</span>
            <h2>${esc(job.title || "岗位工作台")}</h2>
            ${alignment.status === "succeeded" ? '<span class="pill pill-success">已对齐</span>' : ""}
          </div>
          <div class="wb-context-meta">${esc(job.company || "未知公司")} · ${esc(job.location || "未知城市")} · ${formatSalary(job)} · ${esc(jobStatusLabel(job.status))} · 匹配 ${matchScore == null ? "—" : `${esc(matchScore)} / 100`}</div>
          <div class="wb-tags">${tagItems.map((tag) => `<span class="tag">${esc(tag)}</span>`).join("")}</div>
        </div>
        <div class="wb-context-actions">
          <span class="status-line"><span class="dot dot-success" aria-hidden="true"></span>${esc(diffs.length)} 条改写建议 · ${esc(acceptedCount)} 已采纳 · ${esc(pendingCount)} 待采纳</span>
          <select class="input input-sm" data-job-switcher aria-label="切换岗位">
            ${jobs.map((item) => `<option value="${esc(item.job_id)}" ${item.job_id === jobId ? "selected" : ""}>${esc(item.title)}${item.company ? ` · ${esc(item.company)}` : ""}</option>`).join("")}
          </select>
          <div class="row">
            ${jobApplyLinkHtml(job)}
            <button class="btn btn-primary" type="button" data-action="record-application" data-id="${esc(jobId)}">记录投递</button>
            <button class="btn btn-primary" type="button" data-action="run-alignment" ${alignmentRunning ? "disabled" : ""}>${alignmentRunning ? "对齐生成中..." : "重新生成对齐"}</button>
          </div>
        </div>
      </div>
      <div class="wb-grid" data-split-layout>
        <section class="wb-main ${state.wbMobilePane === "diff" ? "is-active" : ""}" data-wb-pane="diff" data-diff-pane data-resume-canvas>
          <div class="wb-main-head">
            <div>
              <h2>简历对齐画布</h2>
              <p>逐条采纳 AI 精修建议，保留 Provenance 溯源标记</p>
            </div>
            <div class="toolbar-group">
              ${exportDock(jobId, session)}
              ${alignment.diffs && alignment.diffs.length ? `<button class="btn btn-ghost btn-sm" type="button" data-action="toggle-live-compare">并排对比</button>` : ""}
            </div>
          </div>
          <div class="align-summary">
            <div><span class="summary-score">${matchScore == null ? "—" : esc(matchScore)}</span><span class="summary-unit">/ 100</span></div>
            <div class="align-metrics">
              <div class="align-metric"><b>${esc(diffs.length)}</b><span>改写建议</span></div>
              <div class="align-metric"><b>${esc(acceptedCount)}</b><span>已采纳</span></div>
              <div class="align-metric"><b>${esc(pendingCount)}</b><span>待采纳</span></div>
              <div class="align-metric"><b>${alignment.eval_score && alignment.eval_score.hallucination_detected === false ? "通过" : alignment.eval_score && alignment.eval_score.hallucination_detected === true ? "风险" : "—"}</b><span>幻觉检测</span></div>
            </div>
          </div>
          <div class="panel panel--success final-draft-panel" data-final-draft-panel hidden></div>
          <div class="diff-list">${diffList(session, jobId)}</div>
        </section>
        <aside class="wb-aux">
          <div class="wb-tabs" role="tablist" aria-label="工作台辅助信息">
            <button type="button" class="wb-tab ${activeAuxPane === "inspector" ? "active" : ""}" data-action="set-wb-tab-v3" data-wb-tab-v3="inspector" aria-selected="${activeAuxPane === "inspector"}">JD Inspector</button>
            <button type="button" class="wb-tab ${activeAuxPane === "livesheet" ? "active" : ""}" data-action="set-wb-tab-v3" data-wb-tab-v3="livesheet" aria-selected="${activeAuxPane === "livesheet"}">Live Sheet</button>
          </div>
          <div class="wb-pane ${inspectorActive ? "active" : ""}" data-wb-pane="controls" data-inspector-pane data-jd-canvas>
            <section class="pane-section" data-jd-summary>
              <h3>岗位职责萃取</h3>
              ${dutyText ? `<p class="workbench-duty-text">${esc(dutyText)}</p>` : `<p class="small muted">岗位职责摘要生成中。</p>`}
            </section>
            <section class="pane-section">
              <h3>硬技能</h3>
              ${renderSkills(profile)}
            </section>
            <section class="pane-section workbench-gap">
              <h3>技能缺口</h3>
              ${pendingSkillFocus ? (highlightSkillGapHtml(gap.gap_report || gap, pendingSkillFocus) || "") : (renderGap(gap.gap_report || gap) || "")}
            </section>
            <details class="raw-jd" data-raw-jd>
              <summary>查看原始 JD</summary>
              <pre>${esc(job.jd_text || "")}</pre>
            </details>
            <details class="inspector-controls" data-inspector-controls ${state.wbControlsOpen ? "open" : ""}>
              <summary>对齐调优</summary>
              ${alignmentControls(session, resumes, jobId)}
            </details>
            <section class="pane-section applications-panel" data-applications-panel></section>
          </div>
          <div class="wb-pane ${livesheetActive ? "active" : ""}" data-wb-pane="livesheet" data-live-sheet-pane></div>
        </aside>
        <form data-form="wb-run" hidden aria-hidden="true">
          <input type="hidden" name="job_id" value="${jobId}">
          <input type="hidden" name="master_resume_id" value="">
          <input type="hidden" name="granularity" value="medium">
          <input type="hidden" name="prompt_focus" value="balanced">
          <input type="checkbox" name="run_eval" hidden>
        </form>
      </div>
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
  const inspectorControls = $("[data-inspector-controls]");
  if (inspectorControls) {
    inspectorControls.addEventListener("toggle", () => {
      state.wbControlsOpen = inspectorControls.open;
    });
  }
  const exportDockEl = $("[data-export-dock]");
  if (exportDockEl) {
    exportDockEl.open = Boolean(state.wbExportDockOpen);
    exportDockEl.addEventListener("toggle", () => {
      state.wbExportDockOpen = exportDockEl.open;
    });
  }
  renderCanvasExtras();
  /* Sprint 2 T2: 每次画布重绘都同步 Live Sheet（SSE job.result / poll 终态 /
   * 采纳后整画布刷新都会走到这里）。增量 patch 只发生在已填充的 live pane
   * 上（见 syncLiveSheetDraft）；全新画布的 body 为空，这里做整栏填充。 */
  mountLiveSheet(app, liveSheetDraft);
  app.querySelectorAll("[data-diff-id]").forEach((card) => {
    if (!acceptedIds.has(card.dataset.diffId)) return;
    card.classList.add("accepted");
    const actions = card.querySelector("[data-diff-actions]");
    if (actions) {
      actions.innerHTML = '<button type="button" class="btn btn-ghost btn-sm adopted" disabled>已采纳</button>';
    }
  });
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
          <div class="split-section-title">定稿 Live Sheet</div>
          <div class="small muted">实时同步</div>
        </div>
      </div>
      <div class="live-sheet__paper" data-live-sheet-paper>
        <div class="muted small">暂无定稿。运行对齐并采纳建议后，将实时预览最终简历。</div>
      </div>`;
  }
  return `
    <div class="split-pane__head">
      <div>
        <div class="split-section-title">定稿 Live Sheet</div>
        <div class="small muted">实时同步</div>
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

/* Re-render the final-draft panel after every canvas repaint (SSE events
 * replace #app.innerHTML wholesale, so the panel would otherwise fall back
 * to its placeholder state). */
function renderCanvasExtras() {
  const app = $("#app-router-view");
  if (!app) return;
  renderFinalDraftPanel(app);
  renderApplicationsPanel(app);
  /* T3: 每次画布重绘都尝试 ?skill= 深链定位；gap 未就绪时保持 pending。 */
  tryFocusSkill();
}

function renderApplicationsPanel(app) {
  const panel = $("[data-applications-panel]", app);
  if (!panel) return;
  const apps = Array.isArray(state.wbApplications)
    ? state.wbApplications
    : [];
  const resumes = Array.isArray(state.wbResumes) ? state.wbResumes : [];
  panel.innerHTML = `
    <details class="applications-panel__box" open>
      <summary>投递记录</summary>
      <form data-form="application-create">
        <div class="form-grid">
          <label class="field"><span>标题</span><input type="text" name="title" required placeholder="例如：Acme 后端"></label>
          <label class="field"><span>主简历</span><select name="master_resume_id" required><option value="">选择简历</option>${resumes.map((resume) => `<option value="${resume.resume_id}">${esc(resume.title)}</option>`).join("")}</select></label>
          <label class="field wide"><span>JD 文本</span><textarea name="jd_text" rows="3"></textarea></label>
          <label class="field wide"><span>JD 链接</span><input type="url" name="jd_url"></label>
        </div>
        <div class="row"><button class="btn btn-secondary btn-sm" type="submit">创建投递记录</button></div>
      </form>
      <div class="card-list motion-stagger">
        ${apps.map((item) => `
          <div class="card application-card card-base card-hover-soft">
            <div class="card-head">
              <div class="card-title">${esc(item.title)}</div>
              <span class="badge badge-gray">${esc(APP_STATUS_LABELS[item.status] || item.status)}</span>
            </div>
            <div class="card-meta">简历 v${esc(item.resume_version)} · 更新于 ${formatDate(item.updated_at)}</div>
            ${item.latest_job_id ? `<div class="small muted">最近任务：${esc(item.latest_job_id)}</div>` : ""}
            <div class="row">
              <select data-application-status data-id="${esc(item.application_id)}">
                ${Object.entries(APP_STATUS_LABELS).map(([value, label]) => `<option value="${value}" ${item.status === value ? "selected" : ""}>${esc(label)}</option>`).join("")}
              </select>
              <button class="btn btn-outline btn-sm" data-action="update-application-status" data-id="${esc(item.application_id)}">保存状态</button>
              <button class="btn btn-primary btn-sm" data-action="run-application" data-id="${esc(item.application_id)}">运行</button>
              <button class="btn btn-danger btn-sm" data-action="delete-application" data-id="${esc(item.application_id)}">删除</button>
            </div>
          </div>`).join("") || `<div class="muted small">还没有投递记录</div>`}
      </div>
    </details>`;
}

/* 定稿面板（与遗留 renderWorkspaceView 的 renderFinalDraftPanel 同构）。
 * 记录投递/导出等按钮复用 main.js 的 document 级 data-action 委托，
 * 无需在 live 画布内重复绑定（B5）。 */
function renderFinalDraftPanel(app) {
  const panel = $("[data-final-draft-panel]");
  if (!panel) return;
  const draft = state.wbFinalDraft;
  const job = state.wbJob || {};
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
      ${jobApplyLinkHtml(job)}
      <button class="btn btn-primary btn-sm" data-action="record-application" data-id="${esc(job.job_id || "")}">记录投递</button>
      <button class="btn btn-secondary btn-sm" data-action="export-final-draft">导出 PDF</button>
      <button class="btn btn-secondary btn-sm" data-action="export-final-draft-md">导出 Markdown</button>
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
    state.wbResumes = resumes;
    state.wbApplications = await api("/api/applications").catch(() => []);
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
      </div>
      <div data-applications-panel></div>`;
    renderApplicationsPanel(app);
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
      source_url: freshJob.source_url,
      jd_url: freshJob.jd_url,
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
  state.wbResumes = resumes;
  state.wbApplications = await api("/api/applications").catch(() => []);
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
    const session = await api(`/api/workspace/session/${encodeURIComponent(jobId)}`);
    if (session && session.session_id) return session;
  } catch {
    /* fall through to a direct workbench session id */
  }
  try {
    return await api(`/api/workbench/session/${encodeURIComponent(jobId)}`);
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
  const session = activeSession;
  const job = session && session.job;
  const analysisId = job && job.workbench_job_id;
  if (
    !analysisId ||
    (session &&
      typeof session.session_id === "string" &&
      session.session_id.startsWith("job:"))
  ) {
    return;
  }
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
  /* A fresh run must not compare against the previous run's original text,
     accepted indices, or accumulated draft. */
  state.wbOriginalContent = null;
  state.wbAcceptedIndices = null;
  if (state.wbWorkingDraft && state.wbWorkingDraft.jobId === jobId) {
    state.wbWorkingDraft = null;
  }
  if (state.wbAcceptedBullets) delete state.wbAcceptedBullets[jobId];
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

export function setWbAuxPane(pane) {
  if (pane !== "inspector" && pane !== "livesheet") return;
  activeAuxPane = pane;
  const app = $("#app-router-view");
  if (!app) return;
  app.querySelectorAll("[data-wb-tab-v3]").forEach((tab) => {
    const active = tab.dataset.wbTabV3 === pane;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  const inspector = app.querySelector("[data-inspector-pane]");
  const livesheet = app.querySelector("[data-live-sheet-pane]");
  if (inspector) inspector.classList.toggle("active", pane === "inspector");
  if (livesheet) livesheet.classList.toggle("active", pane === "livesheet");
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
