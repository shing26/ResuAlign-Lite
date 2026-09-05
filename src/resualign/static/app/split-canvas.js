/* Copilot board + Optimizer split canvas for the 2.0 workstation flow. */

import {
  $,
  STAGE_LABELS,
  api,
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
  diffCard,
  diffList,
  exportDock,
  formatElapsed,
  highlightSkillGapHtml,
  jdProfileSummary,
  jobApplyLinkHtml,
  jobCompletenessBadge,
  renderGap,
  renderA4PaperHtml,
  renderMatchBadge,
  renderSkills,
  stageStepper,
  workbenchProgressPipelineHtml,
  workbenchGuideHtml,
  workbenchPrimaryButtonHtml,
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

/* P0-1: 对齐失败分类 —— 后端 jobs.py 已按超时/格式/空内容/限流/auth 分类产出
 * 文案，这里按文案特征再打一个简短类别徽标；横幅同时展示后端快照带来的
 * 阶段与本次耗时（analysis-status 的 stage / elapsed_seconds）。 */
const ALIGN_FAILURE_KINDS = {
  timeout: "超时",
  format: "内容格式异常",
  empty: "返回为空",
  auth: "模型配置",
  ratelimit: "服务限流",
  expired: "任务已过期",
  canceled: "任务已取消",
  other: "任务失败",
};

function alignmentFailureKind(message, status) {
  const text = String(message || "").toLowerCase();
  if (status === "expired" || text.includes("过期")) return "expired";
  if (status === "canceled" || text.includes("取消")) return "canceled";
  if (/(timeout|timed out|超时)/.test(text)) return "timeout";
  if (/(expecting value|not a json|invalid json|schema|failed validation|格式异常|无法解析)/.test(text)) return "format";
  if (/(empty|返回为空)/.test(text)) return "empty";
  if (/(429|rate limit|限流|繁忙)/.test(text)) return "ratelimit";
  if (/(401|403|api key|unauthorized|无效或缺少权限|无效或缺失)/.test(text)) return "auth";
  return "other";
}

/* P0-2: 失败/取消/过期横幅只承担「讲清失败原因」职责，不再放第二个
 * 「重新运行对齐」按钮 —— 重试收敛到顶栏危险级单入口（workbenchPrimaryButtonHtml）。 */
function workbenchAlignmentErrorBanner(alignment) {
  const status = alignment && alignment.status;
  if (!["failed", "canceled", "expired"].includes(status)) return "";
  const errorText = (alignment && alignment.error) || "对齐任务失败，请重新运行";
  const kind = alignmentFailureKind(errorText, status);
  const meta = [];
  if (alignment.stage && alignment.stage !== status) {
    meta.push(`阶段：${STAGE_LABELS[alignment.stage] || alignment.stage}`);
  }
  const elapsedSecs = Number(alignment.elapsed_seconds);
  if (Number.isFinite(elapsedSecs) && elapsedSecs > 0) {
    meta.push(`本次耗时 ${formatElapsed(Math.round(elapsedSecs * 1000))}`);
  }
  return (
    `<div class="align-error-banner" role="alert" data-align-error-banner data-align-error-kind="${esc(kind)}">` +
    `<strong>对齐失败 · ${esc(ALIGN_FAILURE_KINDS[kind] || "任务失败")}</strong>` +
    `<span>${esc(errorText)}</span>` +
    (meta.length ? `<span class="align-error-meta">${esc(meta.join(" · "))}</span>` : "") +
    `<button class="btn btn-outline btn-sm" type="button" data-action="show-node-picker">换节点重试</button>` +
    `</div>`
  );
}

/* 空结果告警（2026-08-30 诊断 P0-C）：对齐 succeeded 但 0 条建议时，
 * 此前与真正成功的渲染完全一致 —— 用户读到的是「跑完了却什么都没有」。
 * 后端 alignment.notice 命名两种空形态（门禁拦截 / 模型未产出结构化建议）。 */
function workbenchAlignmentNoticeBanner(alignment) {
  const notice = alignment && alignment.notice;
  if (!notice) return "";
  return (
    `<div class="align-error-banner align-notice-banner" role="status" data-align-notice-banner>` +
    `<strong>对齐完成 · 无可用建议</strong>` +
    `<span>${esc(notice)}</span>` +
    `</div>`
  );
}


export function renderSplitCanvas(app, session, resumes, jobs = workbenchJobs) {
  /* A workspace render started before a route change may resolve after the
     new view is mounted; never let a stale workbench repaint another route. */
  if (!state.route || state.route.name !== "workspace") return;
  const job = (session && session.job) || {};
  const jd = (session && session.jd) || {};
  const gap = (session && session.gap) || {};
  const profile = jd.profile || {};
  const summary = jdProfileSummary(profile);
  const jobId = job.job_id || "";
  /* Mirror the legacy workbench contract so renderFinalDraftPanel /
     record-application work identically on the live canvas. */
  const sessionDraft = (session && session.alignment && session.alignment.draft) || null;
  state.wbFinalDraft = job.final_draft
    ? {
        draft: job.final_draft,
        version: job.final_draft_version || 1,
        updated_at: job.final_draft_updated_at,
      }
    : sessionDraft
      ? {
          draft: sessionDraft,
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
  if (jobId) {
    const persistedAccepted = (Array.isArray(job.diffs) ? job.diffs : [])
      .filter((diff) => diff && diff.provenance_state === "accepted")
      .map((diff) => diff.diff_id)
      .filter(Boolean);
    if (persistedAccepted.length) {
      const merged = new Set((state.wbAcceptedBullets || {})[jobId] || []);
      persistedAccepted.forEach((id) => merged.add(id));
      state.wbAcceptedBullets = {
        ...(state.wbAcceptedBullets || {}),
        [jobId]: [...merged],
      };
    }
  }
  const acceptedIds = new Set((state.wbAcceptedBullets || {})[jobId] || []);
  const acceptedCount = diffs.filter(
    (diff) =>
      acceptedIds.has(diff.diff_id) || diff.provenance_state === "accepted",
  ).length;
  const pendingCount = Math.max(0, diffs.length - acceptedCount);
  /* UX 走查 2026-08-28：provenance 硬门禁拦截的建议卡（invalid_diffs）也会
     渲染在建议面板里，但头部计数此前只统计有效 diffs——出现「0 条改写建议」
     与面板里 N 张待复核卡的口径分裂。这里并入同一行，措辞与 provenance
     pill 的「建议复核」保持同一叫法（ADR-0033 §7 术语统一）。 */
  const invalidCount = Array.isArray(alignment.invalid_diffs)
    ? alignment.invalid_diffs.length
    : 0;
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
  const suggestActive = activeAuxPane === "suggest";
  const controlsActive = activeAuxPane === "controls";
  const hasGuideDraft = Boolean(
    job.final_draft ||
      (session && session.alignment && session.alignment.draft),
  );
  if (state.wbViewMode !== "a4" && state.wbViewMode !== "diff") {
    state.wbViewMode = hasGuideDraft ? "a4" : "diff";
  }
  const viewMode = state.wbViewMode === "a4" ? "a4" : "diff";
  const dutyText = String(
    (summary && summary.summary) || job.jd_text || "",
  ).trim().slice(0, 240);
  /* R5 P1-4（02-UID ③-4 + R2 合议 Q4）：移动端底栏动作条仅在「必须行动」
   * 态常驻 —— 失败/取消/过期（可重试）或 运行中；idle/succeeded 不占底栏。
   * ≤640px 时底栏接管主按钮（顶栏同款按钮隐藏，保持 P0-2 单入口）。 */
  const barActive =
    alignmentRunning ||
    ["failed", "canceled", "expired"].includes(alignment.status);
  app.innerHTML = `
    <div class="view view-fit workbench-view" data-surface-mode="optimizer"${barActive ? ' data-mobile-action-bar="true"' : ""}>
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
          <span class="status-line"><span class="dot dot-success" aria-hidden="true"></span>${esc(diffs.length)} 条改写建议${invalidCount ? ` · ${esc(invalidCount)} 条建议复核` : ""} · ${esc(acceptedCount)} 已采纳 · ${esc(pendingCount)} 待采纳</span>
          <select class="input input-sm" data-job-switcher aria-label="切换岗位">
            ${jobs.map((item) => `<option value="${esc(item.job_id)}" ${item.job_id === jobId ? "selected" : ""}>${esc(item.title)}${item.company ? ` · ${esc(item.company)}` : ""}</option>`).join("")}
          </select>
          <div class="row">
            ${jobApplyLinkHtml(job)}
            <button class="btn btn-secondary" type="button" data-action="record-application" data-id="${esc(jobId)}">记录投递</button>
            ${workbenchPrimaryButtonHtml(resumes, alignmentRunning, alignment)}
          </div>
        </div>
      </div>
      ${workbenchAlignmentErrorBanner(alignment)}
      <div data-wb-node-picker></div>
      ${workbenchAlignmentNoticeBanner(alignment)}
      ${workbenchGuideHtml(job, hasGuideDraft)}
      <div class="wb-grid" data-split-layout>
        <section class="wb-main ${state.wbMobilePane === "diff" ? "is-active" : ""}" data-wb-pane="diff" data-diff-pane data-resume-canvas>
          <div class="wb-main-head">
            <div>
              <h2>简历精修</h2>
              <p>${viewMode === "a4" ? "以 A4 纸预览定稿，建议集中在右侧处理" : "逐条采纳 AI 精修建议，每条建议都可追溯来源"}</p>
            </div>
            <div class="toolbar-group">
              <div class="wb-view-toggle" role="group" aria-label="工作台显示模式">
                <button type="button" class="wb-view-toggle__btn ${viewMode === "diff" ? "active" : ""}" data-action="set-wb-view-mode" data-wb-view-mode="diff" aria-pressed="${viewMode === "diff"}">对照编辑</button>
                <button type="button" class="wb-view-toggle__btn ${viewMode === "a4" ? "active" : ""}" data-action="set-wb-view-mode" data-wb-view-mode="a4" aria-pressed="${viewMode === "a4"}">A4 预览</button>
              </div>
              ${exportDock(jobId, job)}
              ${viewMode === "diff" && alignment.diffs && alignment.diffs.length ? `<button class="btn btn-ghost btn-sm" type="button" data-action="toggle-live-compare">对比视图</button>` : ""}
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
          ${viewMode === "a4" ? `<div class="a4-wrap" data-a4-wrap>${renderA4PaperHtml(liveSheetDraft)}</div>` : `<div class="diff-list">${diffList(session, jobId)}</div>`}
        </section>
        <aside class="wb-aux">
          ${workbenchProgressPipelineHtml(session)}
          <div class="wb-tabs" role="tablist" aria-label="工作台辅助信息">
            ${viewMode === "a4" ? `<button type="button" class="wb-tab ${suggestActive ? "active" : ""}" data-action="set-wb-tab-v3" data-wb-tab-v3="suggest" aria-selected="${suggestActive}">建议</button>` : ""}
            <button type="button" class="wb-tab ${inspectorActive ? "active" : ""}" data-action="set-wb-tab-v3" data-wb-tab-v3="inspector" aria-selected="${inspectorActive}">岗位分析</button>
            <button type="button" class="wb-tab ${livesheetActive ? "active" : ""}" data-action="set-wb-tab-v3" data-wb-tab-v3="livesheet" aria-selected="${livesheetActive}">面试记录</button>
            <button type="button" class="wb-tab ${controlsActive ? "active" : ""}" data-action="set-wb-tab-v3" data-wb-tab-v3="controls" aria-selected="${controlsActive}">优化设置</button>
          </div>
          ${viewMode === "a4" ? `<div class="wb-pane ${suggestActive ? "active" : ""}" data-wb-pane="suggest" data-wb-aux-pane="suggest" data-suggest-pane>
            <div class="suggest-pane__head"><h3>改写建议</h3><span class="small muted">采纳后将自动应用到定稿</span></div>
            ${diffList(session, jobId)}
          </div>` : ""}
          <div class="wb-pane ${inspectorActive ? "active" : ""}" data-wb-pane="controls" data-wb-aux-pane="inspector" data-inspector-pane data-jd-canvas>
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
          </div>
          <div class="wb-pane ${controlsActive ? "active" : ""}" data-wb-pane="controls-opt" data-wb-aux-pane="controls" data-controls-pane>
            <section class="pane-section pane-section--controls">
              <div class="pane-section__head"><h3>优化设置</h3><span class="small muted">主简历与对齐参数</span></div>
              ${alignmentControls(session, resumes, jobId)}
            </section>
          </div>
          <div class="wb-pane ${livesheetActive ? "active" : ""}" data-wb-pane="livesheet" data-wb-aux-pane="livesheet" data-live-sheet-pane></div>
        </aside>
        <form data-form="wb-run" hidden aria-hidden="true">
          <input type="hidden" name="job_id" value="${jobId}">
          <input type="hidden" name="master_resume_id" value="">
          <input type="hidden" name="granularity" value="medium">
          <input type="hidden" name="prompt_focus" value="balanced">
          <input type="checkbox" name="run_eval" hidden>
        </form>
      </div>
      ${barActive ? `<div class="wb-action-bar" data-wb-action-bar>${workbenchPrimaryButtonHtml(resumes, alignmentRunning, alignment)}</div>` : ""}
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
  const job = state.wbJob || {};
  if (!draft || !draft.draft || state.wbViewMode === "a4") {
    panel.hidden = true;
    panel.innerHTML = "";
    return;
  }
  panel.hidden = false;
  const acceptedDiffCount = (Array.isArray(job.diffs) ? job.diffs : []).filter(
    (diff) => diff && diff.provenance_state === "accepted",
  ).length;
  const metaRows = [
    job.model ? `模型 ${esc(job.model)}` : "",
    job.prompt_version ? `Prompt ${esc(job.prompt_version)}` : "",
    draft.updated_at ? `保存 ${formatDate(draft.updated_at)}` : "",
    acceptedDiffCount ? `采纳 ${acceptedDiffCount} 条` : "",
  ].filter(Boolean).map((item) => `<span>${item}</span>`).join("");
  panel.innerHTML = `
    <div class="final-draft-head">
      <div>
        <h3>定稿简历</h3>
        <div class="draft-meta">
          <span class="badge badge-green" data-final-version>已定稿 v${draft.version}</span>
          <span class="small muted">第 ${draft.version} 版</span>
          <span class="final-draft-meta" data-final-draft-meta>${metaRows}</span>
        </div>
      </div>
    </div>
    <div class="pre draft-preview">${esc(draft.draft)}</div>
    <div class="row final-draft-actions">
      ${jobApplyLinkHtml(job)}
      <button class="btn btn-primary btn-sm" data-action="record-application" data-id="${esc(job.job_id || "")}">记录投递</button>
      <button class="btn btn-secondary btn-sm" data-action="export-final-draft">导出 PDF</button>
      <button class="btn btn-secondary btn-sm" data-action="export-final-draft-md">导出 Markdown</button>
      <button class="btn btn-secondary btn-sm" data-action="export-final-draft-json">导出 JSON</button>
      <button class="btn btn-secondary btn-sm" data-action="save-as-new-resume">另存为新主简历</button>
      ${(job.workbench_resume_id || "").trim() ? '<button class="btn btn-secondary btn-sm" data-action="update-master-resume">更新到主简历</button>' : ""}
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
      draft: job.draft || job.final_draft || null,
      eval_score: job.eval_score || null,
    },
    meta: {},
  };
}

async function reconcileAlignmentFailure(session) {
  const job = (session && session.job) || {};
  if (!job || job.alignment_status === "succeeded") return session;
  const workbenchJobId = job.workbench_job_id;
  if (!workbenchJobId) return session;
  try {
    const snapshot = await api(
      `/api/jobs/${encodeURIComponent(workbenchJobId)}/analysis-status`,
    );
    const terminalStatus =
      snapshot.status === "expired" ? "failed" : snapshot.status;
    if (terminalStatus === "failed" || terminalStatus === "canceled") {
      const detail =
        snapshot.error ||
        (snapshot.status === "expired"
          ? "上次对齐任务已过期（服务重启或任务清理），结果未保留，请重新生成"
          : "对齐任务失败，请重试");
      session.alignment = {
        ...(session.alignment || {}),
        status: terminalStatus,
        stage: snapshot.status === "expired" ? "" : snapshot.stage || "",
        error: detail,
      };
      /* Bug-09: 失败绝不静默——toast 立即提示，随后的 render 会带持久错误条。 */
      toast(String(detail).slice(0, 300), "error");
    }
  } catch {
    session.alignment = {
      ...(session.alignment || {}),
      status: "failed",
      stage: "",
      error: "上次对齐任务已过期（服务重启或任务清理），结果未保留，请重新生成",
    };
  }
  return session;
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
      toast("已自动打开最近岗位，可在工作台右上角切换", "info");
      return renderOptimizerCanvas(app, targetId);
    }
    const resumes = await api("/api/master-resumes");
    state.wbResumes = resumes;
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
    `;
    return;
  }
  const existing = workbenchJobs.find((item) => item.job_id === jobId);
  if (!existing) {
    /* A genuinely stale/removed job id: go back to the Dashboard instead of
       probing session routes that can only 404 for a missing job. */
    toast("岗位不存在，已返回驾驶舱", "info");
    window.location.hash = "#/dashboard";
    return;
  }
  let session = await loadSession(jobId);
  if (!session) {
    /* The job exists but has no workbench session (e.g. created via the
     * API / import). Rehydrate the three-pane canvas from the persisted
     * analysis product (jd_profile / gap_report / diffs) instead of
     * bouncing the user back to the Dashboard. */
    session = buildSessionFromJob(existing);
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
      status: freshJob.status,
      applied_at: freshJob.applied_at,
      offer_at: freshJob.offer_at,
      rejected_at: freshJob.rejected_at,
      next_step: freshJob.next_step,
      next_step_due_at: freshJob.next_step_due_at,
      interview_stage: freshJob.interview_stage,
      final_draft: freshJob.final_draft,
      final_draft_version: freshJob.final_draft_version,
      final_draft_updated_at: freshJob.final_draft_updated_at,
      workbench_job_id: freshJob.workbench_job_id,
      diffs: freshJob.diffs,
      invalid_diffs: freshJob.invalid_diffs,
      draft: freshJob.draft,
    };
  }
  session = await reconcileAlignmentFailure(session);
  activeSession = session;
  activeSessionUrl = session.meta && session.meta.event_url;
  activeJobId = (session.job && session.job.job_id) || jobId;
  state.wbJob = session.job || state.wbJob;
  const resumes = await api("/api/master-resumes");
  state.wbResumes = resumes;
  renderSplitCanvas(app, session, resumes, workbenchJobs);
  const terminalAlignment = isTerminalAlignment(session);
  if (terminalAlignment) {
    stopWorkbenchLiveChannels();
  } else {
    startPollingFallback(session);
    startEventStream(session);
    resumeAlignmentProgress();
    autoAnalyzeJd(session);
  }
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
    return await api(`/api/workspace/session/${encodeURIComponent(jobId)}`);
  } catch {
    return null;
  }
}

function startEventStream(session) {
  if (!session || !session.meta || !session.meta.event_url) return;
  if (isTerminalAlignment(session)) {
    stopEventStream();
    return;
  }
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
  if (isTerminalAlignment(session)) {
    return;
  }
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

function isTerminalAlignment(session) {
  return ["failed", "canceled", "succeeded"].includes(
    session && session.alignment && session.alignment.status,
  );
}

function stopWorkbenchLiveChannels() {
  stopAlignmentPoll();
  stopPollingFallback();
  stopEventStream();
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
    /* Route changes stop the poller while a request is in flight; a stale
       response must not repaint the new route with the workbench canvas. */
    if (!fallbackPollTimer || !activeSession) return;
    if (response.status === 304) return;
    if (!response.ok) return;
    const updated = await response.json();
    if (!fallbackPollTimer || !activeSession) return;
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
    if (app && activeSession.session_id === sessionId) {
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
  if (eventName === "job.stage") {
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
    snapshot = await api(
      `/api/jobs/${encodeURIComponent(analysisId)}/analysis-status`,
    );
  } catch {
    /* The pinned analysis job was cleaned up (TTL). Keep the canvas open
     * with the persisted data and let the user rerun alignment; never
     * bounce a valid job's workspace back to the Dashboard. */
    stopAlignmentPoll();
    return;
  }
  if (snapshot.status === "expired") {
    setAlignmentTerminal({
      status: "failed",
      error: "上次对齐任务已过期（服务重启或任务清理），结果未保留，请重新生成",
    });
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
  stopWorkbenchLiveChannels();
  alignmentReconciled = true;
  if (!activeSession) return;
  const status = snapshot.status === "canceled" ? "canceled" : "failed";
  activeSession.alignment = {
    ...(activeSession.alignment || {}),
    status,
    stage: snapshot.stage || status,
    error:
      snapshot.error ||
      (status === "canceled" ? "对齐任务已取消" : "对齐任务失败，请重新运行"),
    elapsed_seconds: Number(snapshot.elapsed_seconds) || 0,
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
    snapshot = await api(
      `/api/jobs/${encodeURIComponent(jobId)}/analysis-status`,
    );
  } catch {
    stopAlignmentPoll();
    window.location.hash = "#/dashboard";
    return;
  }
  if (snapshot.status === "expired") {
    setAlignmentTerminal({
      status: "failed",
      error: "上次对齐任务已过期（服务重启或任务清理），结果未保留，请重新生成",
    });
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
     to idle so the workspace is not stuck with a disabled run button. The
     task still finishes in the background and its result is persisted. */
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
  toast("任务将继续在后台完成，结果仍会保存；已停止本地等待", "info");
}

export async function startAlignmentRun(jobId, resumeId, granularity, focus, runEval) {
  if (!jobId) {
    throw new Error("岗位上下文尚未就绪，请刷新后重试");
  }
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
    const snapshot = await api(
      `/api/jobs/${encodeURIComponent(jobId)}/analysis-status`,
    );
    const app = $("#app-router-view");
    if (activeSession && app) {
      const resolvedStatus =
        snapshot.status === "expired" ? "failed" : snapshot.status;
      activeSession.alignment = {
        status: resolvedStatus === "succeeded" ? "succeeded" : resolvedStatus === "failed" ? "failed" : "running",
        stage: snapshot.stage || snapshot.status || "",
        error:
          snapshot.error ||
          (snapshot.status === "expired"
            ? "上次对齐任务已过期（服务重启或任务清理），结果未保留，请重新生成"
            : null),
        elapsed_seconds: Number(snapshot.elapsed_seconds) || 0,
        diffs: (snapshot.result && snapshot.result.diffs) || [],
        invalid_diffs: (snapshot.result && snapshot.result.invalid_diffs) || [],
        draft: (snapshot.result && snapshot.result.draft) || activeSession.alignment?.draft || null,
        eval_score: (snapshot.result && snapshot.result.eval_score) || null,
      };
      if (
        ["succeeded", "failed", "canceled", "expired"].includes(
          snapshot.status,
        )
      ) {
        stopWorkbenchLiveChannels();
        alignmentReconciled = true;
        if (resolvedStatus === "succeeded") {
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
            activeSession.alignment.error ||
              `对齐任务：${resolvedStatus}`,
            resolvedStatus === "failed" ? "error" : "info",
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

const WB_AUX_PANES = ["suggest", "inspector", "livesheet", "controls"];

export function setWbAuxPane(pane) {
  if (!WB_AUX_PANES.includes(pane)) return;
  activeAuxPane = pane;
  const app = $("#app-router-view");
  if (!app) return;
  app.querySelectorAll("[data-wb-tab-v3]").forEach((tab) => {
    const active = tab.dataset.wbTabV3 === pane;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  app.querySelectorAll("[data-wb-aux-pane]").forEach((node) => {
    node.classList.toggle("active", node.dataset.wbAuxPane === pane);
  });
}

/* 工作台主区显示模式：diff=对照编辑（diff list 在 main），
 * a4=A4 纸预览（diff list 移入右栏「建议」tab，避免 DOM 重复）。 */
export function setWbViewMode(mode) {
  if (mode !== "diff" && mode !== "a4") return;
  state.wbViewMode = mode;
  const app = $("#app-router-view");
  if (!app || !state.route || state.route.name !== "workspace") return;
  /* 已有活跃会话且简历列表已加载时只重排现有画布：renderOptimizerCanvas 会
   * 整画布重挂载并经 stopOptimizerStreams 杀掉在跑对齐的轮询/SSE，再以
   * session store 的旧终态重绘——对齐进行中切视图会让画布永远停在旧结果
   * （2026-08-27 CI mobile 冒烟复现）。wbResumes 未就绪时退回整挂载，
   * 避免 workbenchPrimaryButtonHtml 拿到空列表渲染出错误的「无简历」态。 */
  if (activeSession && state.wbResumes && state.wbResumes.length) {
    renderSplitCanvas(app, activeSession, state.wbResumes, workbenchJobs);
    return;
  }
  renderOptimizerCanvas(app, activeJobId || (state.route && state.route.jobId) || "");
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
