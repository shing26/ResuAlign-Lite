/* Runtime helpers, modal handling, and progress/polling events. */

import {
  focusInitial,
  isFocusable,
  lockBodyScroll,
  trapTabKey,
  unlockBodyScroll,
} from "./focus-trap.js";
import {
  DEFAULT_VOCABULARY,
  STAGE_LABELS,
  alignmentStatusLabel,
  atsHealthCardHtml,
  atsHealthScoreLevel,
  atsHealthTone,
  buildDiagnosisMarkdownFrom,
  esc,
  formatElapsed,
  isBackwardJobStatus,
  jobTerminalConfirmFormHtml,
  jobStatusLabel,
  jobStatusRank,
  normalizeVocabulary,
  normalizeVocabularyList,
  optimizeActionsHtml,
  optimizeModuleHtml,
  optimizeOverviewHtml,
  renderBatchMatrixHtml,
} from "./format.js";
import { API_CACHE_TTL, apiCache } from "./cache-manager.js";
import { icon } from "./icons.js";

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
  alignmentStatusLabel,
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

export const STAGE_WEIGHTS = {
  queued: 0.05,
  running: 0.1,
  diagnose: 0.2,
  jd_profile: 0.4,
  jd_analysis: 0.45,
  gap_analysis: 0.6,
  tailoring: 0.85,
  evaluation: 0.95,
  /* 简历优化（xzjobs 式）：overview 本地即时完成，polishing 为逐模块 LLM 阶段 */
  overview: 0.15,
  polishing: 0.7,
  succeeded: 1,
};

export const state = {
  route: { name: "resume", jobId: null },
  resumes: [],
  jobs: [],
  filters: {
    job_function: "",
    seniority: "",
    status: "",
    search: "",
    sort: "updated_at_desc",
  },
  offset: 0,
  limit: 20,
  wbJob: null,
  wbResumes: [],
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
  /* 快速评估（Ctrl+K）：JD 文本/主简历/已有岗位，跨 action 传递 */
  quickEval: null,
  quickEvalResumeId: null,
  wbAcceptedBullets: {},
  diagnosis: null,
  diagnosisPolling: null,
  diagnosisResumeId: null,
  /* AI 优化（xzjobs 式模块化润色）：optimizeJob = 任务快照；
   * optimizeJobResumeId = 任务所属简历（跨简历导航不串数据）；
   * optimizeModules = result.modules；optimizeAccepted 以模块位置为键。 */
  optimizeJob: null,
  optimizePolling: null,
  optimizeResumeId: null,
  optimizeJobResumeId: null,
  optimizeModules: [],
  optimizeAccepted: {},
  optimizeJdText: "",
  settings: null,
  vocabulary: null,
  applicationSnapshots: {},
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
  /* B6③（2026-09-06 走查 #83）：同一事件里 toast 出现两条——对相同文案
   * 在短窗口内去重，无论上游触发几次。 */
  const last = region.lastElementChild;
  if (
    last &&
    last.dataset.text === message &&
    Date.now() - Number(last.dataset.at || 0) < 500
  ) {
    return;
  }
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.dataset.text = message;
  node.dataset.at = String(Date.now());
  const text = document.createElement("span");
  text.textContent = message;
  const close = document.createElement("button");
  close.type = "button";
  close.setAttribute("aria-label", "关闭提示");
  close.innerHTML = icon("x", 16);
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
  const method = (options.method || "GET").toUpperCase();
  if (method === "GET" && options.cacheKey) {
    const cached = apiCache.get(options.cacheKey);
    if (cached !== undefined) return cached;
  }
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
    /* SH-10（2026-10-23）：#100 错误契约在 body 顶层带 request_id，这里透传到
     * Error 上，全局错误面板才能显示「请求 ID」供日志排查。 */
    try {
      const body = await response.clone().json();
      if (body && body.request_id) error.requestId = String(body.request_id);
    } catch {
      /* 非 JSON 错误体（网关等）忽略 */
    }
    throw error;
  }
  if (response.status === 204) return null;
  const data = await response.json();
  if (method === "GET" && options.cacheKey) {
    apiCache.set(options.cacheKey, data, options.ttl || API_CACHE_TTL);
  }
  return data;
}

/* SH-09（2026-10-23）：对话框可达性。
 *
 * 背景隔离：打开时给 #app-router-view / .app-rail / .topbar 加 inert，
 * Tab 和读屏都进不去背景。原来只有遮罩挡鼠标 + keydown 里的 trapTabKey
 * 在 Tab 时把焦点拽回来，读屏仍能读、程序 focus 仍能落进去。浏览器不支持
 * inert 时退化成 aria-hidden="true"（关闭时按原值还原，不留副作用）。
 *
 * 焦点恢复：原来只记录 activeElement，但弹窗里的动作（保存/删除/确认）经常
 * 触发 render()，触发按钮在关闭时已经被重绘替换，restoreFocus 会静默失败，
 * activeElement 掉到 <body>，键盘用户再按 Tab 只能从页面开头重走。现在：
 * 1) 关闭后的恢复动作延后一拍执行，等调用方同步的重绘落完再判断目标是否
 *    还 isConnected；
 * 2) 目标失效（或不可聚焦）时回退到当前路由容器 #app-router-view（临时
 *    tabindex=-1），保证 activeElement 不是 body、下一次 Tab 从本页继续。 */
const MODAL_BACKGROUND_SELECTORS = ["#app-router-view", ".app-rail", ".topbar"];
const MODAL_FOCUS_FALLBACK_ID = "app-router-view";

let modalReturnFocus = null;
let modalKeydownHandler = null;
/* [{ node, mode: "inert"|"aria-hidden", previous }]，关闭时逐条还原。 */
let modalBackgroundState = [];
let modalFocusTimer = null;
/* 递增令牌：期间又开了新弹窗时，旧弹窗的延迟恢复不能抢焦点。 */
let modalFocusToken = 0;

function setModalBackgroundInert() {
  clearModalBackgroundInert();
  MODAL_BACKGROUND_SELECTORS.forEach((selector) => {
    $$(selector).forEach((node) => {
      if (!node || !node.isConnected) return;
      /* 原生 inert 同时拦截 Tab、点击与读屏；不支持时才退而求其次用
         aria-hidden（只对读屏生效，Tab 仍由 trapTabKey 兜底）。 */
      if ("inert" in node) {
        const previous = node.inert;
        node.inert = true;
        modalBackgroundState.push({ node, mode: "inert", previous });
      } else {
        const previous = node.getAttribute("aria-hidden");
        node.setAttribute("aria-hidden", "true");
        modalBackgroundState.push({ node, mode: "aria-hidden", previous });
      }
    });
  });
}

function clearModalBackgroundInert() {
  modalBackgroundState.forEach(({ node, mode, previous }) => {
    if (!node || !node.isConnected) return;
    if (mode === "inert") {
      node.inert = Boolean(previous);
      return;
    }
    if (previous == null) node.removeAttribute("aria-hidden");
    else node.setAttribute("aria-hidden", previous);
  });
  modalBackgroundState = [];
}

function recordModalReturnFocus() {
  const active = document.activeElement;
  /* body / documentElement 没有可恢复的位置——记住它们等于关闭后什么都没做，
     不如置 null 让关闭逻辑走「回退到路由容器」。 */
  if (
    !(active instanceof HTMLElement) ||
    active === document.body ||
    active === document.documentElement
  ) {
    modalReturnFocus = null;
    return;
  }
  modalReturnFocus = active;
}

function focusRouteFallback() {
  const main = document.getElementById(MODAL_FOCUS_FALLBACK_ID);
  if (!main) return;
  /* 容器本身不在 Tab 序列里；临时 tabindex=-1 让它能接程序焦点，
     下一次 Tab 从本页第一个可交互元素继续。 */
  if (!main.hasAttribute("tabindex")) main.setAttribute("tabindex", "-1");
  main.focus({ preventScroll: true });
}

function restoreModalFocus(returnTo) {
  const target =
    returnTo && returnTo.isConnected && typeof returnTo.focus === "function"
      ? returnTo
      : null;
  if (target) {
    target.focus({ preventScroll: true });
    /* disabled/hidden 的按钮 focus() 会被浏览器忽略，兜底再确认一次。 */
    if (document.activeElement === target) return;
  }
  focusRouteFallback();
}

/* 延后一拍再恢复：closeModal() 之后调用方常同步执行 render()，它一上来就
 * 替换 #app-router-view 的 innerHTML，若在关闭瞬间 focus 触发按钮，紧接着
 * 就被冲掉、焦点落回 body。等本轮 JS 结束再判断 isConnected 才能正确回退。 */
function scheduleModalFocusRestore(returnTo) {
  modalFocusToken += 1;
  const token = modalFocusToken;
  if (modalFocusTimer !== null) window.clearTimeout(modalFocusTimer);
  modalFocusTimer = window.setTimeout(() => {
    modalFocusTimer = null;
    if (token !== modalFocusToken) return;
    restoreModalFocus(returnTo);
  }, 0);
}

/* restoreFocus=false 用于「换弹窗」：旧弹窗的触发元素要留给新弹窗关闭时
 * 归还，不能在中途先还一次。 */
function dismissModal({ restoreFocus = true } = {}) {
  const backdrop = $(".modal-backdrop");
  /* 没有任何弹窗在开时 closeModal() 应当是纯 no-op：不能让防御性的关闭调用
     把焦点从用户当前位置挪走。 */
  const hadOpenModal = Boolean(backdrop) || modalKeydownHandler !== null;
  if (backdrop) backdrop.remove();
  if (modalKeydownHandler) {
    document.removeEventListener("keydown", modalKeydownHandler);
    modalKeydownHandler = null;
  }
  unlockBodyScroll(document.body);
  /* 先解除背景 inert 再恢复焦点：焦点目标通常就在 #app-router-view 里，
     inert 未清时 focus() 会被浏览器忽略。 */
  clearModalBackgroundInert();
  /* 作废尚未执行的延迟焦点恢复：快速「关一个再开一个」时，旧的恢复动作
     不能在 0ms 后把焦点抢到新弹窗背后。 */
  modalFocusToken += 1;
  if (modalFocusTimer !== null) {
    window.clearTimeout(modalFocusTimer);
    modalFocusTimer = null;
  }
  if (!restoreFocus) return;
  const returnTo = modalReturnFocus;
  modalReturnFocus = null;
  if (!hadOpenModal) return;
  scheduleModalFocusRestore(returnTo);
}

export function showModal(title, bodyHtml, options = {}) {
  /* 叠弹窗（详情 → 确认删除之类）：换掉旧的但不要把焦点先还给旧触发按钮，
     否则新弹窗打开后焦点会短暂落到背景里；旧弹窗记录的原触发元素保留，
     等最后一个弹窗关闭时再归还。 */
  const replacing = Boolean($(".modal-backdrop"));
  dismissModal({ restoreFocus: false });
  if (!replacing) recordModalReturnFocus();
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  if (options.className) backdrop.classList.add(options.className);
  backdrop.setAttribute("role", "dialog");
  backdrop.setAttribute("aria-modal", "true");
  backdrop.setAttribute("aria-label", title);
  const closeBtn = options.closeBtn
    ? `<button type="button" class="modal-close" data-action="close-modal" aria-label="关闭">${icon("x", 20)}</button>`
    : "";
  backdrop.innerHTML = `<div class="modal"><h3>${esc(title)}</h3>${closeBtn}${bodyHtml}</div>`;
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) closeModal();
  });
  document.body.append(backdrop);
  setModalBackgroundInert();
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
  /* 初始焦点：显式 [autofocus] 优先（表单弹窗常把 autofocus 放在首个输入框），
     否则沿用 focusInitial 的第一个可交互元素。 */
  window.setTimeout(() => {
    const autofocus = backdrop.querySelector("[autofocus]");
    if (autofocus && isFocusable(autofocus)) {
      autofocus.focus();
      return;
    }
    focusInitial(backdrop);
  }, 0);
}

export function closeModal() {
  const pending = pendingStatusTransition;
  pendingStatusTransition = null;
  dismissModal();
  if (pending && typeof pending.onCancel === "function") {
    pending.onCancel();
  }
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
  closeModal();
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
  state.diagnosisResumeId = resume.resume_id || state.diagnosisResumeId;
  const fallback = resume.latest_diagnosis;
  if (jobId) {
    let snapshot;
    try {
      snapshot = await api(
        `/api/jobs/${encodeURIComponent(jobId)}/analysis-status`,
      );
    } catch {
      if (fallback) {
        state.diagnosis = {
          job_id: jobId,
          status: "succeeded",
          elapsed_seconds: fallback.elapsed_seconds || 0,
          result: { diagnosis: fallback },
        };
        renderDiagnosisResult(state.diagnosis);
      } else {
        renderDiagnosisIdle();
      }
      return;
    }
    state.diagnosis = { job_id: jobId, ...snapshot };
    if (snapshot.status === "succeeded") {
      renderDiagnosisResult(snapshot);
    } else if (snapshot.status === "failed" || snapshot.status === "canceled") {
      renderDiagnosisError(snapshot);
    } else if (snapshot.status === "expired") {
      renderDiagnosisIdle();
    } else {
      renderDiagnosisProgress(snapshot);
      startDiagnosisPolling(jobId, resume.resume_id);
    }
    return;
  }
  if (fallback) {
    state.diagnosis = {
      job_id: "",
      status: "succeeded",
      elapsed_seconds: fallback.elapsed_seconds || 0,
      result: { diagnosis: fallback },
    };
    renderDiagnosisResult(state.diagnosis);
  } else {
    renderDiagnosisIdle();
  }
}

function syncResumeBandStatus(text) {
  const node = $("[data-resume-band-status-text]");
  if (node) node.textContent = text;
}

/* RS-02（2026-10-22 审计）：全页只保留页头一个诊断主 CTA。
 * 诊断卡、结果行、失败区都不再各自生成「诊断/重新诊断」按钮，避免同一屏
 * 出现两三个同名付费动作（用户不知道该点哪个，误触还要花模型调用）。
 * 因此这里统一改页头按钮文案与可用态；找不到节点时静默跳过，
 * 不做任何 panel 内已删除节点的查询。 */
function syncBandDiagnoseCta(label, busy) {
  const cta = $("[data-action='diagnose-resume']");
  if (!cta) return;
  cta.disabled = Boolean(busy);
  cta.textContent = label;
  cta.classList.toggle("is-loading", Boolean(busy));
}

/* 无诊断时给一行「先点哪里」的提示；有结果/进度中则不显示。 */
function syncDiagnosisHint(visible) {
  const hint = $("[data-diagnosis-hint]");
  if (hint) hint.hidden = !visible;
}

/* 诊断报告导出（MD / PDF）收在页头「导出」下拉菜单里：没有诊断结果时隐藏，
 * 避免菜单里出现点了没反应的空入口。 */
function setBandDiagnosisExportsHidden(hidden) {
  $$(
    ".resume-band [data-action='export-diagnosis'], .resume-band [data-action='export-diagnosis-md']",
  ).forEach((node) => {
    node.hidden = hidden;
  });
}

/* RS-03（移动端 ATS 摘要）：≤900px 时首屏要能看到「能不能投」。
 * 摘要卡 markup 由本模块产出、resume-center.js 复用同一函数；显示/隐藏
 * 完全交给 CSS（桌面隐藏、窄屏显示），这里不写任何媒体查询。
 * 与 atsHealthCardHtml 同口径：有 issues 用 issues，否则回退 suggestions。
 * 没有诊断结果时整卡带 hidden：此时卡内只有「尚未诊断」占位，留着反而和上面
 * 那行「还没有诊断，点右上角…」重复；诊断完成后由 syncAtsSummary 换掉。 */
export function atsSummaryHtml(diagnosis) {
  const data = diagnosis && typeof diagnosis === "object" ? diagnosis : {};
  const rawScore = Number(data.score);
  const score = Number.isFinite(rawScore)
    ? Math.max(0, Math.min(100, rawScore))
    : null;
  const toList = (value) =>
    Array.isArray(value)
      ? value.map((item) => String(item ?? "")).filter(Boolean)
      : [];
  const issues = toList(data.issues);
  const suggestions = toList(data.suggestions);
  const improvements = (issues.length ? issues : suggestions).slice(0, 2);
  const level = score == null ? "尚未诊断" : atsHealthScoreLevel(score);
  return `
    <div class="resume-ats-summary" data-ats-summary${score == null ? " hidden" : ""}>
      <div class="resume-ats-summary__head">
        <span class="resume-ats-summary__score" data-ats-summary-score>${score ?? "—"}</span>
        <span class="resume-ats-summary__label" data-ats-summary-level>${esc(level)} · ATS 健康度</span>
      </div>
      ${
        improvements.length
          ? `<ul class="resume-ats-summary__list" data-ats-summary-improvements>${improvements
              .map((item) => `<li>${esc(item)}</li>`)
              .join("")}</ul>`
          : `<p class="small muted" data-ats-summary-hint>${
              score == null
                ? "诊断后这里显示 ATS 分数与 2 条改进建议"
                : "本次诊断未给出改进建议"
            }</p>`
      }
      ${
        score == null
          ? ""
          : '<button class="btn btn-ghost btn-sm" type="button" data-action="ats-summary-jump">查看完整 ATS 建议</button>'
      }
    </div>`;
}

/* 诊断完成/失败后整块重渲染摘要卡，保证移动端摘要与右栏 ATS 卡同源。
 * 用 outerHTML 替换整卡：innerHTML 会把新卡嵌进旧卡里，移动端出现双层边框。 */
function syncAtsSummary(diagnosis) {
  const root = $("[data-ats-summary]");
  if (!root) return;
  root.outerHTML = atsSummaryHtml(diagnosis);
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
    const snapshot = await api(
      `/api/jobs/${encodeURIComponent(jobId)}/analysis-status`,
    );
    if (!state.diagnosisPolling || state.diagnosisPolling.jobId !== jobId) return;
    renderDiagnosisProgress(snapshot);
    if (
      ["succeeded", "failed", "canceled", "expired"].includes(
        snapshot.status,
      )
    ) {
      stopDiagnosisPolling();
      state.diagnosis = { job_id: jobId, ...snapshot };
      if (snapshot.status === "succeeded") {
        renderDiagnosisResult(snapshot);
        toast(`简历诊断完成，得分 ${snapshot.result && snapshot.result.diagnosis ? snapshot.result.diagnosis.score : snapshot.result ? snapshot.result.score : ""}`, "success");
      } else if (snapshot.status === "expired") {
        renderDiagnosisIdle();
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
  syncResumeBandStatus("最近诊断：尚未诊断");
  /* 无诊断：页头 CTA 回到「诊断简历」，卡内给一行「先点哪里」提示。 */
  syncBandDiagnoseCta("诊断简历", false);
  syncDiagnosisHint(true);
  syncAtsSummary(null);
  setBandDiagnosisExportsHidden(true);
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
  /* Sprint 4 T3: 空闲态把右侧 ATS 卡重置为占位。 */
  const atsNode = $("[data-ats-health-mount]");
  if (atsNode) atsNode.innerHTML = atsHealthCardHtml(null);
}

export function renderDiagnosisProgress(snapshot) {
  const panel = $("[data-diagnosis-panel]");
  if (!panel) return;
  /* 诊断中：页头 CTA 置灰并显示进度文案（重载恢复轮询时也保持同一状态）。 */
  syncBandDiagnoseCta("诊断中...", true);
  syncDiagnosisHint(false);
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
}

export function renderDiagnosisResult(snapshot) {
  const panel = $("[data-diagnosis-panel]");
  if (!panel) return;
  const result = snapshot.result || {};
  const diagnosis = result.diagnosis || result;
  const score = Math.max(0, Math.min(100, Number(diagnosis.score) || 0));
  syncResumeBandStatus(`最近诊断：${score} 分`);
  /* 完成态：页头 CTA 变成「重新诊断」，卡内提示收起。 */
  syncBandDiagnoseCta("重新诊断", false);
  syncDiagnosisHint(false);
  syncAtsSummary(diagnosis);
  setBandDiagnosisExportsHidden(false);
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
  const target = $("[data-diagnosis-result]", panel);
  if (target) {
    target.hidden = false;
    /* 结果行不再重复大分数，也不再放第二个「重新诊断」：
     * ① 分数已经在页头状态行 + 右栏 ATS 卡大字各出现一次，这里再写一遍就是
     *    审计里「85 分说了六遍」的那类重复；
     * ② 诊断入口全页只有一个（页头），同屏两个同名付费 CTA 会让人无从下手。
     * 等级与右栏共用 atsHealthScoreLevel / atsHealthTone，避免 80 vs 85
     * 两套阈值在同一屏给出互相矛盾的结论。 */
    const level = atsHealthScoreLevel(score);
    const tone = atsHealthTone(score);
    const levelClass =
      tone === "high" ? "badge-green" : tone === "mid" ? "badge-amber" : "badge-red";
    target.innerHTML = `
    <div class="diagnosis-banner__result">
      <span class="badge ${levelClass}">${esc(level)}</span>
      <span class="small muted">诊断完成 · 改进建议见 ATS 健康度</span>
      <span class="diagnosis-banner__actions">
        <button class="btn btn-outline btn-sm" data-action="diagnosis-to-align" data-id="${state.diagnosisResumeId || ""}">去对齐</button>
      </span>
    </div>`;
  }
  /* Sprint 4 T3: 诊断完成同步刷新右侧 ATS 健康度卡。 */
  const atsNode = $("[data-ats-health-mount]");
  if (atsNode) atsNode.innerHTML = atsHealthCardHtml(diagnosis);
}

export function renderDiagnosisError(snapshot) {
  const panel = $("[data-diagnosis-panel]");
  if (!panel) return;
  syncResumeBandStatus(
    `最近诊断：${snapshot.status === "canceled" ? "已取消" : "失败"}`,
  );
  /* 失败态不留第二个重试按钮：重试就是页头那个唯一的「重新诊断」。 */
  syncBandDiagnoseCta("重新诊断", false);
  syncDiagnosisHint(true);
  syncAtsSummary(null);
  setBandDiagnosisExportsHidden(true);
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
      <div class="small muted" style="margin-top:6px">可点右上角「重新诊断」重试。</div>`;
  }
  /* Sprint 4 T3: 失败态清空右侧 ATS 卡，避免展示过期结果。 */
  const atsNode = $("[data-ats-health-mount]");
  if (atsNode) atsNode.innerHTML = atsHealthCardHtml(null);
}

/* ------------------------------------------------------------------ */
/* Resume optimizer（xzjobs 式模块化润色）: polling + panel renders     */
/* ------------------------------------------------------------------ */

export function startOptimizePolling(jobId, resumeId) {
  stopOptimizePolling();
  state.optimizeResumeId = resumeId || state.optimizeResumeId;
  state.optimizePolling = { jobId };
  startPolling("optimize", () => pollOptimizeJob(jobId), 1000);
}

export function stopOptimizePolling() {
  stopPolling("optimize");
  state.optimizePolling = null;
}

export async function pollOptimizeJob(jobId) {
  if (!state.optimizePolling || state.optimizePolling.jobId !== jobId) return;
  try {
    const snapshot = await api(
      `/api/jobs/${encodeURIComponent(jobId)}/analysis-status`,
    );
    if (!state.optimizePolling || state.optimizePolling.jobId !== jobId) return;
    renderOptimizeProgress(snapshot);
    if (
      ["succeeded", "failed", "canceled", "expired"].includes(
        snapshot.status,
      )
    ) {
      stopOptimizePolling();
      state.optimizeJob = { job_id: jobId, ...snapshot };
      if (snapshot.status === "succeeded") {
        state.optimizeModules =
          (snapshot.result && snapshot.result.modules) || [];
        renderOptimizeResult(snapshot);
        const overview = (snapshot.result && snapshot.result.overview) || {};
        toast(
          `整体分析完成（${overview.score != null ? `${overview.score} 分` : "已生成"}），模块润色已逐条返回`,
          "success",
        );
      } else if (snapshot.status === "expired") {
        renderOptimizeIdle();
      } else {
        renderOptimizeError(snapshot);
      }
    }
  } catch (error) {
    stopOptimizePolling();
    renderOptimizeError({ status: "failed", error: error.message });
  }
}

export function recoverOptimization(resume) {
  const resumeId = resume && resume.resume_id;
  const job = state.optimizeJob;
  if (!resumeId || !job || state.optimizeJobResumeId !== resumeId) {
    renderOptimizeIdle();
    return;
  }
  state.optimizeResumeId = resumeId;
  if (job.status === "succeeded") {
    state.optimizeModules =
      (job.result && job.result.modules) || state.optimizeModules || [];
    renderOptimizeResult(job);
  } else if (job.status === "failed" || job.status === "canceled") {
    renderOptimizeError(job);
  } else if (job.status === "expired") {
    renderOptimizeIdle();
  } else {
    renderOptimizeProgress(job);
    startOptimizePolling(job.job_id, resumeId);
  }
}

export function renderOptimizeIdle() {
  const panel = $("[data-optimize-panel]");
  if (!panel) return;
  const meta = $("[data-optimize-meta]", panel);
  if (meta) meta.textContent = "尚未运行";
  const progress = $("[data-optimize-progress]", panel);
  if (progress) progress.hidden = true;
  const result = $("[data-optimize-result]", panel);
  if (result) {
    result.hidden = true;
    result.innerHTML = "";
  }
  const error = $("[data-optimize-error]", panel);
  if (error) {
    error.hidden = true;
    error.innerHTML = "";
  }
  const runBtn = $("[data-action='optimize-resume']", panel);
  if (runBtn) {
    runBtn.disabled = false;
    runBtn.textContent = "运行 AI 优化";
    runBtn.classList.remove("is-loading");
  }
  const cancel = $("[data-action='cancel-optimize']", panel);
  if (cancel) cancel.hidden = true;
}

export function renderOptimizeProgress(snapshot) {
  const panel = $("[data-optimize-panel]");
  if (!panel) return;
  /* 面板默认折叠（不占版面）；一旦有进行中的任务就自动展开，免得用户
   * 看不到进度。 */
  if (panel.open !== undefined) panel.open = true;
  const progress = $("[data-optimize-progress]", panel);
  if (progress) progress.hidden = false;
  const result = $("[data-optimize-result]", panel);
  if (result) result.hidden = true;
  const error = $("[data-optimize-error]", panel);
  if (error) {
    error.hidden = true;
    error.innerHTML = "";
  }
  const meta = $("[data-optimize-meta]", panel);
  if (meta) {
    meta.textContent =
      snapshot.message ||
      (snapshot.status === "queued" ? "排队中..." : "优化进行中...");
  }
  const fill = $("[data-optimize-fill]", panel);
  const stage = $("[data-optimize-stage]", panel);
  const elapsed = $("[data-optimize-elapsed]", panel);
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
  const cancel = $("[data-action='cancel-optimize']", panel);
  if (cancel) {
    cancel.hidden =
      snapshot.status !== "queued" && snapshot.status !== "running";
  }
  const runBtn = $("[data-action='optimize-resume']", panel);
  if (runBtn) {
    runBtn.disabled = true;
    runBtn.textContent = "优化中...";
    runBtn.classList.add("is-loading");
  }
}

export function renderOptimizeResult(snapshot) {
  const panel = $("[data-optimize-panel]");
  if (!panel) return;
  if (panel.open !== undefined) panel.open = true;
  const result = snapshot.result || {};
  const overview = result.overview || {};
  const modules = Array.isArray(result.modules) ? result.modules : [];
  const meta = $("[data-optimize-meta]", panel);
  if (meta) {
    const llmPart = result.llm_used && result.model ? ` · 模型 ${result.model}` : "";
    meta.textContent = `最近优化 · 用时 ${snapshot.elapsed_seconds || result.elapsed_seconds || 0}s${llmPart}`;
  }
  const progress = $("[data-optimize-progress]", panel);
  if (progress) progress.hidden = true;
  const error = $("[data-optimize-error]", panel);
  if (error) {
    error.hidden = true;
    error.innerHTML = "";
  }
  const runBtn = $("[data-action='optimize-resume']", panel);
  if (runBtn) {
    runBtn.disabled = false;
    runBtn.textContent = "运行 AI 优化";
    runBtn.classList.remove("is-loading");
  }
  const cancel = $("[data-action='cancel-optimize']", panel);
  if (cancel) cancel.hidden = true;
  const target = $("[data-optimize-result]", panel);
  if (!target) return;
  target.hidden = false;
  target.innerHTML = `
    ${optimizeOverviewHtml(overview)}
    ${optimizeActionsHtml(modules, state.optimizeAccepted || {})}
    <div class="optimize-modules" data-optimize-modules></div>
    ${result.note ? `<div class="small muted">${esc(result.note)}</div>` : ""}
  `;
  renderOptimizeModuleList();
}

export function renderOptimizeError(snapshot) {
  const panel = $("[data-optimize-panel]");
  if (!panel) return;
  if (panel.open !== undefined) panel.open = true;
  const meta = $("[data-optimize-meta]", panel);
  if (meta) {
    meta.textContent =
      snapshot.status === "canceled"
        ? "最近一次优化已取消"
        : "最近一次优化失败";
  }
  const progress = $("[data-optimize-progress]", panel);
  if (progress) progress.hidden = true;
  const result = $("[data-optimize-result]", panel);
  if (result) {
    result.hidden = true;
    result.innerHTML = "";
  }
  const error = $("[data-optimize-error]", panel);
  if (error) {
    error.hidden = false;
    error.setAttribute("role", "alert");
    error.innerHTML = `
      <div><strong>${snapshot.status === "canceled" ? "优化已取消" : "优化失败"}</strong>：${esc(snapshot.error || "优化任务暂时失败，请重试")}</div>`;
  }
  const runBtn = $("[data-action='optimize-resume']", panel);
  if (runBtn) {
    runBtn.disabled = false;
    runBtn.textContent = "运行 AI 优化";
    runBtn.classList.remove("is-loading");
  }
  const cancel = $("[data-action='cancel-optimize']", panel);
  if (cancel) cancel.hidden = true;
}

export function renderOptimizeModuleList() {
  const container = $("[data-optimize-modules]");
  if (!container) return;
  const modules = state.optimizeModules || [];
  const accepted = state.optimizeAccepted || {};
  container.innerHTML = modules.length
    ? modules
        .map((item, key) =>
          optimizeModuleHtml(item, key, Boolean(accepted[String(key)])),
        )
        .join("")
    : `<div class="small muted">未识别到项目经历/工作经历模块，跳过逐项润色。</div>`;
}

export function refreshOptimizePanel() {
  renderOptimizeModuleList();
  const actionsNode = $("[data-optimize-actions]");
  if (actionsNode) {
    actionsNode.innerHTML = optimizeActionsHtml(
      state.optimizeModules || [],
      state.optimizeAccepted || {},
    );
  }
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
    const hasQueued = batch.rows.some((row) => row.status === "queued");
    const hasRunning = batch.rows.some((row) => row.status === "running");
    if (batch.summary.completed === batch.summary.total) {
      stopBatchPolling();
    }
    const cancel = $("[data-batch-cancel]");
    if (
      cancel &&
      (batch.summary.completed === batch.summary.total || (!hasQueued && hasRunning))
    ) {
      cancel.hidden = true;
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

