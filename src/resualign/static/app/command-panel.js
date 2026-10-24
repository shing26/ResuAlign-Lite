/* Universal command palette: paste JD text or a JD URL, confirm, open Optimizer.
 *
 * Sprint 1 (T3) adds a "搜岗位" mode: while typing, matching job titles /
 * companies are listed as suggestions in the palette; Enter (on input or a
 * focused suggestion) / click jumps to that job's workspace. The original
 * paste-JD/URL flow is unchanged — when suggestions are hidden, Enter still
 * submits the form and creates an analysis session.
 *
 * SH-01 (2026-10-22 审计)：空输入时渲染默认命令列表（去往 / 动作 / 最近岗位），
 * 用户打开 Ctrl+K 就能看到「这里能做什么」，而不是只看到一行「粘贴 JD」提示；
 * 输入后才切回搜岗位 / JD 预览。同时补上顶栏占位符里一直写着、但从未实现的
 * "/" 快捷键（非输入态聚焦打开面板）。 */

import { $, $$, api, esc, state, toast } from "./events.js";
import { closeOverlaySurface, openOverlaySurface } from "./events.js";
import { isJdUrl, previewFor, renderJobSuggestionsHtml } from "./format.js";
import { icon } from "./icons.js";

let jobsCache = null;

/* SH-01：默认命令注册表。
 *
 * 「去往」的 hash 逐个对着 main.js::handleRoute 的 switch 分支核过
 * （dashboard / workspace / review / jobs / resume / settings）——路由表改了
 * 这里要同步，否则会多出一条「点进去落到驾驶舱默认分支」的死链。
 *
 * 「动作」只写 main.js::actions 里真实存在的键：main.js 的 document 委托按
 * actions[key] 查表，写错只会静默无反应，不会报错。岗位库专用动作
 * （新建岗位 / 批量导入）直接操作岗位库表单挂载点，在别的页面执行会抛
 * TypeError，所以点击时先切到岗位库、等挂载点出现后再点真按钮
 * （见 runScopedAction）。 */
const ROUTE_COMMANDS = [
  { route: "dashboard", hash: "#/dashboard", label: "驾驶舱", iconName: "gauge" },
  { route: "review", hash: "#/review", label: "投递复盘", iconName: "clipboard-list" },
  { route: "workspace", hash: "#/workspace", label: "工作台", iconName: "columns" },
  { route: "jobs", hash: "#/jobs", label: "岗位库", iconName: "briefcase" },
  { route: "resume", hash: "#/resume", label: "简历中心", iconName: "file-text" },
  { route: "settings", hash: "#/settings", label: "系统设置", iconName: "settings" },
];

/* 岗位库专用动作：在别的路由执行会因为找不到表单挂载点而抛错。 */
const JOBS_SCOPE_ACTIONS = new Set(["show-add-job", "show-import"]);

const RECENT_JOBS_LIMIT = 5;

/* 默认列表是异步渲染的（最近岗位要等一次接口）；序号用于作废迟到的那一次，
 * 否则「打开 → 立刻输入 → 搜索结果」会被慢返回的默认列表覆盖回去。 */
let commandListSeq = 0;

function isDarkTheme() {
  return document.documentElement.dataset.theme === "dark";
}

/* 动作清单按主题动态生成：切主题那一行的图标/文案指向「切换之后」的状态，
 * 比固定的太阳图标更不容易误读。 */
function actionCommands() {
  const dark = isDarkTheme();
  return [
    { action: "show-add-job", label: "新建岗位", iconName: "briefcase" },
    { action: "show-import", label: "批量导入", iconName: "file-text" },
    { action: "new-resume", label: "新建主简历", iconName: "pencil" },
    {
      action: "toggle-theme",
      label: dark ? "切换到浅色主题" : "切换到深色主题",
      iconName: dark ? "sun" : "moon",
    },
  ];
}

function commandRowIcon(name) {
  return `<span class="command-row__icon" data-command-icon="${esc(name)}" aria-hidden="true">${icon(name, 16)}</span>`;
}

function commandGroupHtml(key, title, rows) {
  if (!rows) return "";
  return `<div class="command-group" data-command-group="${esc(key)}">
      <div class="command-group__title">${esc(title)}</div>
      <div class="command-group__list">${rows}</div>
    </div>`;
}

function routeCommandRowsHtml() {
  return ROUTE_COMMANDS.map(
    ({ route, hash, label, iconName }) => `
      <a class="command-row" data-command-route="${esc(route)}" href="${esc(hash)}">
        ${commandRowIcon(iconName)}
        <span class="command-row__label">${esc(label)}</span>
      </a>`,
  ).join("");
}

function actionCommandRowsHtml() {
  return actionCommands()
    .map(
      ({ action, label, iconName }) => `
      <button class="command-row" type="button" data-action="${esc(action)}">
        ${commandRowIcon(iconName)}
        <span class="command-row__label">${esc(label)}</span>
      </button>`,
    )
    .join("");
}

function recentJobRowsHtml(jobs) {
  return (Array.isArray(jobs) ? jobs : [])
    .filter((job) => job && job.job_id)
    .slice(0, RECENT_JOBS_LIMIT)
    .map(
      (job) => `
      <a class="command-row" data-command-recent href="#/workspace/${esc(encodeURIComponent(job.job_id))}">
        ${commandRowIcon("briefcase")}
        <span class="command-row__label">${esc(job.title || "未命名岗位")}</span>
        ${job.company ? `<span class="command-row__meta">${esc(job.company)}</span>` : ""}
      </a>`,
    )
    .join("");
}

function isJobsRoute() {
  return String(window.location.hash || "").startsWith("#/jobs");
}

/* 岗位库专用动作：先切路由，再等工具栏与表单挂载点都渲染出来，最后点真按钮。
 * 用轮询而不是固定延时：岗位库渲染要等一次词表请求，慢机器上固定延时会点空。
 * 最多等 3s，超时静默放弃（不把内部技术错误弹给用户）。 */
function runScopedAction(actionName) {
  window.location.hash = "#/jobs";
  const startedAt = Date.now();
  const timer = window.setInterval(() => {
    const mounted =
      actionName === "show-import"
        ? document.querySelector('[data-form="job-import"]')
        : document.querySelector('[data-form="job-create"]');
    const target = mounted
      ? document.querySelector(`[data-action="${actionName}"]`)
      : null;
    if (target) {
      window.clearInterval(timer);
      target.click();
      return;
    }
    if (Date.now() - startedAt > 3000) window.clearInterval(timer);
  }, 60);
}

async function loadSuggestionJobs() {
  if (Array.isArray(jobsCache)) return jobsCache;
  try {
    const jobs = await api("/api/jobs?limit=100");
    jobsCache = Array.isArray(jobs) ? jobs : [];
  } catch {
    jobsCache = [];
  }
  return jobsCache;
}

function suggestionsContainer() {
  return $("[data-command-suggestions]");
}

function clearSuggestions() {
  commandListSeq += 1;
  const container = suggestionsContainer();
  if (container) {
    container.hidden = true;
    container.innerHTML = "";
  }
  const preview = $("[data-command-preview]");
  if (preview) preview.hidden = false;
}

/* 默认命令列表：前两组同步渲染（打开即有内容），「最近岗位」等接口回来再追加。
 * 最近岗位拉取失败时 loadSuggestionJobs 兜底成 []，只保留前两组、不抛错。 */
async function renderCommandGroups() {
  const container = suggestionsContainer();
  if (!container) return;
  const seq = ++commandListSeq;
  container.innerHTML =
    commandGroupHtml("routes", "去往", routeCommandRowsHtml()) +
    commandGroupHtml("actions", "动作", actionCommandRowsHtml());
  container.hidden = false;
  const preview = $("[data-command-preview]");
  if (preview) preview.hidden = true;
  const jobs = await loadSuggestionJobs();
  if (seq !== commandListSeq || container.hidden) return;
  const recent = recentJobRowsHtml(jobs);
  if (recent) {
    container.insertAdjacentHTML(
      "beforeend",
      commandGroupHtml("recent", "最近岗位", recent),
    );
  }
}

async function updateSuggestions(value) {
  const container = suggestionsContainer();
  if (!container) return;
  const trimmed = String(value || "").trim();
  /* 空输入 = 默认命令列表（SH-01）；一旦输入字符才回到「搜岗位 / JD 预览」。 */
  if (!trimmed) {
    await renderCommandGroups();
    return;
  }
  /* 搜索/预览接管后，作废可能还在飞行中的默认列表渲染，避免迟到覆盖。 */
  const seq = ++commandListSeq;
  /* 多行文本 / URL 显然是 JD 内容，不进入搜岗位模式。 */
  if (isJdUrl(trimmed) || trimmed.includes("\n")) {
    clearSuggestions();
    return;
  }
  const jobs = await loadSuggestionJobs();
  /* 输入可能在等接口期间被清空/改掉：让更晚的那次渲染（默认列表或新搜索）
   * 说话，别让这次迟到的搜索结果覆盖它。 */
  if (seq !== commandListSeq) return;
  const html = renderJobSuggestionsHtml(jobs, trimmed);
  if (!html) {
    clearSuggestions();
    return;
  }
  container.innerHTML = html;
  container.hidden = false;
  const preview = $("[data-command-preview]");
  if (preview) preview.hidden = true;
}

/* Enter 落在哪个建议上：优先当前聚焦的建议，否则第一条。 */
function activeSuggestion() {
  const items = $$("[data-command-suggestion]");
  if (!items.length) return null;
  return items.find((node) => node === document.activeElement) || items[0];
}

function goToSuggestion(suggestion) {
  if (!suggestion || !suggestion.dataset.jobId) return;
  const jobId = suggestion.dataset.jobId;
  closeCommandPanel();
  window.location.hash = `#/workspace/${encodeURIComponent(jobId)}`;
}

function setPreview(value) {
  const node = $("[data-command-preview]");
  const confirm = $("[data-command-confirm]");
  if (node) node.innerHTML = previewFor(value);
  if (confirm) confirm.disabled = !String(value || "").trim();
}

function paletteFocusables() {
  const dialog = $("[data-command-palette] .command-palette__dialog");
  if (!dialog) return [];
  return [
    ...dialog.querySelectorAll(
      'input, textarea, select, button, a[href], [tabindex]:not([tabindex="-1"])',
    ),
  ].filter((node) => !node.disabled && node.offsetParent !== null);
}

function trapPaletteFocus(event) {
  if (event.key !== "Tab") return;
  const items = paletteFocusables();
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function movePaletteFocus(direction) {
  const items = paletteFocusables();
  if (!items.length) return;
  const index = items.indexOf(document.activeElement);
  const next = index === -1 ? 0 : (index + direction + items.length) % items.length;
  items[next].focus();
}

export function openCommandPanel() {
  const palette = $("[data-command-palette]");
  if (!palette) return;
  const wasHidden = palette.hidden;
  palette.hidden = false;
  document.body.classList.add("command-palette-open");
  /* SH-09 后续：首开时记录触发元素并隔离背景（与 showModal 同一套
   * inert/焦点机制）；已开时的重复调用不覆盖原触发元素。 */
  if (wasHidden) openOverlaySurface();
  const input = $("[data-command-input]");
  if (input) {
    input.value = "";
    setPreview("");
  }
  /* 打开即给「这里能做什么」：默认命令列表同步出前两组，最近岗位异步补。 */
  void renderCommandGroups();
  if (input) window.setTimeout(() => input.focus(), 0);
}

export function closeCommandPanel() {
  const palette = $("[data-command-palette]");
  /* 已关闭时纯 no-op：不让防御性的关闭调用抢走用户当前焦点。 */
  if (!palette || palette.hidden) return;
  palette.hidden = true;
  document.body.classList.remove("command-palette-open");
  clearSuggestions();
  const input = $("[data-command-input]");
  if (input) input.blur();
  /* SH-09 后续：解除背景 inert 并把焦点还给触发元素（触发元素被重渲染
   * 替换时回退路由容器；延后一拍等本轮 JS 结束，与 showModal 同款）。 */
  closeOverlaySurface();
  /* 每次关闭后失效岗位缓存，下次打开 ⌘K 重新拉取最新岗位列表。 */
  jobsCache = null;
}

export function initializeCommandPanel() {
  const input = $("[data-command-input]");
  if (input) {
    input.addEventListener("input", () => {
      setPreview(input.value);
      updateSuggestions(input.value);
    });
    input.addEventListener("paste", () => {
      window.setTimeout(() => {
        setPreview(input.value);
        updateSuggestions(input.value);
      }, 0);
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeCommandPanel();
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        movePaletteFocus(1);
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        movePaletteFocus(-1);
      }
      /* 搜岗位模式：有建议时回车跳到岗位工作台；无建议则走 JD 确认。 */
      if (event.key === "Enter") {
        const suggestion = activeSuggestion();
        if (suggestion) {
          event.preventDefault();
          goToSuggestion(suggestion);
        } else if (!event.shiftKey) {
          /* textarea keeps Enter for newlines unless this is the submit
           * gesture; preserve the old single-line Enter behavior. */
          event.preventDefault();
          const form = $("[data-form='command-panel']");
          if (form) {
            if (typeof form.requestSubmit === "function") {
              form.requestSubmit();
            } else {
              form.dispatchEvent(
                new window.Event("submit", {
                  bubbles: true,
                  cancelable: true,
                }),
              );
            }
          }
        }
      }
    });
  }
  const palette = $("[data-command-palette]");
  if (palette) {
    palette.addEventListener("click", (event) => {
      const suggestion = event.target.closest("[data-command-suggestion]");
      if (suggestion) {
        goToSuggestion(suggestion);
        return;
      }
      /* SH-01 默认命令行：先收起面板，再决定这一下交给谁。
       * - 路由 / 最近岗位是 <a href>，收起后放行默认跳转（hashchange 会重渲染）；
       * - 普通动作是 <button data-action>，收起后放行冒泡到 main.js 的
       *   document 委托（那边按 actions[key] 查表执行）；
       * - 岗位库专用动作在别的页面会因为没有表单挂载点而报错，所以这里
       *   stopPropagation + 先切路由，等挂载点就绪再点真按钮。 */
      const row = event.target.closest(".command-row");
      if (row) {
        const actionName = row.dataset.action;
        closeCommandPanel();
        if (
          actionName &&
          JOBS_SCOPE_ACTIONS.has(actionName) &&
          !isJobsRoute()
        ) {
          event.stopPropagation();
          runScopedAction(actionName);
        }
        return;
      }
      if (event.target === palette) closeCommandPanel();
    });
    palette.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeCommandPanel();
      }
      /* Enter 触发当前聚焦的命令行：button/anchor 的原生行为会自己发 click，
       * 但这里统一拦下再 click()，避免和「聚焦项被移走」的时序问题打架。 */
      if (
        event.key === "Enter" &&
        document.activeElement &&
        typeof document.activeElement.matches === "function" &&
        document.activeElement.matches(".command-row")
      ) {
        event.preventDefault();
        document.activeElement.click();
        return;
      }
      trapPaletteFocus(event);
    });
  }
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      openCommandPanel();
      return;
    }
    /* SH-01：占位符一直写着「/」，但快捷键从未实现过。现在真绑上：
     * 只在非输入态、无修饰键时响应——输入框里的斜杠是正常字符；
     * 面板已打开时也不重新初始化（会清掉用户刚输入的内容）。 */
    if (
      event.key === "/" &&
      !event.metaKey &&
      !event.ctrlKey &&
      !event.altKey &&
      !event.defaultPrevented &&
      !isTypingTarget(event.target) &&
      !isPaletteOpen()
    ) {
      event.preventDefault();
      openCommandPanel();
    }
  });
}

function isPaletteOpen() {
  const palette = $("[data-command-palette]");
  return Boolean(palette && !palette.hidden);
}

function isTypingTarget(target) {
  if (!target || typeof target.closest !== "function") return false;
  return Boolean(
    target.closest(
      'input, textarea, select, [contenteditable=""], [contenteditable="true"]',
    ),
  );
}

/* 快速评估：粘贴 JD → 规则打分（零 LLM，秒出）。结果渲染在 palette 的
 * preview 区，附「一键入库并对齐」CTA（main.js 的 quick-eval-adopt）。
 * 状态存 state.quickEval，CTA 从那里取 JD 与简历 id（JD 文本不放 data 属性）。 */
export async function runQuickEval() {
  const input = $("[data-command-input]");
  const jdText = input ? String(input.value || "").trim() : "";
  if (jdText.length < 30) {
    toast("JD 文本太短，至少 30 个字符", "error");
    return;
  }
  const preview = $("[data-command-preview]");
  if (preview) {
    preview.innerHTML =
      '<div class="form-success" role="status">规则评估中（零 LLM，秒出）…</div>';
  }
  try {
    let resumeId = state.quickEvalResumeId || null;
    if (!resumeId) {
      const resumes = await api("/api/master-resumes");
      const list = Array.isArray(resumes) ? resumes : [];
      resumeId = list.length ? list[0].resume_id : null;
      state.quickEvalResumeId = resumeId;
    }
    const body = await api("/api/quick-eval", {
      method: "POST",
      body: JSON.stringify({ jd_text: jdText, master_resume_id: resumeId }),
    });
    if (body.existing_job_id) {
      state.quickEval = { jd_text: jdText, master_resume_id: resumeId, existing_job_id: body.existing_job_id };
      if (preview) {
        preview.innerHTML =
          '<div class="form-error" role="alert">该 JD 已在岗位库中。</div>' +
          '<a class="btn btn-outline btn-sm" href="#/workspace/' + encodeURIComponent(body.existing_job_id) + '" data-action="close-command-panel">查看该岗位 ' + icon("chevron-right", 16) + '</a>';
      }
      return;
    }
    state.quickEval = { jd_text: jdText, master_resume_id: resumeId, existing_job_id: null };
    const ev = body.evaluation || {};
    const coverage = ev.keyword_coverage;
    const coverageText = coverage
      ? `关键词覆盖 ${coverage.matched}/${coverage.required}` +
        (coverage.missing && coverage.missing.length ? `（缺 ${esc(coverage.missing.slice(0, 3).join("、"))}）` : "")
      : "JD 未提取到必备技能";
    const missing = ev.missing_top || [];
    if (preview) {
      preview.innerHTML = `
        <div class="form-success" role="status">
          <strong>规则匹配分：${esc(ev.total == null ? "—" : ev.total)} / 100</strong>
          <span>${esc(ev.recommendation || "")}</span>
          <span>${esc(coverageText)}</span>
          ${missing.length ? `<span>主要缺口：${esc(missing.join("、"))}</span>` : ""}
          <span class="small muted">规则打分仅供参考；深度对齐（STAR 改写 + 评估）请入库后在工作台运行。</span>
        </div>
        <button type="button" class="btn btn-primary btn-sm" data-action="quick-eval-adopt">值得投？一键入库并对齐</button>`;
    }
  } catch (error) {
    if (preview) {
      preview.innerHTML = `<div class="form-error" role="alert">${esc(error.message)}</div>`;
    }
    toast(error.message, "error");
  }
}

export async function confirmCommandPanel() {
  const input = $("[data-command-input]");
  const value = input ? String(input.value || "").trim() : "";
  if (!value) return null;
  const confirm = $("[data-command-confirm]");
  const original = confirm ? confirm.textContent : "";
  if (confirm) {
    confirm.disabled = true;
    confirm.textContent = "正在创建会话...";
  }
  try {
    /* 后端已不再抓取 JD 链接（crawler 退役，Phase 2 收口）：URL 输入不再
     * 发送 jd_url（会撞 422），改为引导用户用油猴插件或粘贴 JD 文本。 */
    if (isJdUrl(value)) {
      closeCommandPanel();
      toast(
        "岗位链接需用浏览器油猴插件一键入库，或直接粘贴 JD 文本",
        "info",
      );
      return null;
    }
    const session = await api("/api/workbench/session/init", {
      method: "POST",
      body: JSON.stringify({ raw_jd: value }),
    });
    closeCommandPanel();
    toast("岗位已入库，正在预分析", "success");
    return session;
  } finally {
    if (confirm) {
      confirm.disabled = false;
      confirm.textContent = original;
    }
  }
}
