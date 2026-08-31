/* Universal command palette: paste JD text or a JD URL, confirm, open Optimizer.
 *
 * Sprint 1 (T3) adds a "搜岗位" mode: while typing, matching job titles /
 * companies are listed as suggestions in the palette; Enter (on input or a
 * focused suggestion) / click jumps to that job's workspace. The original
 * paste-JD/URL flow is unchanged — when suggestions are hidden, Enter still
 * submits the form and creates an analysis session. */

import { $, $$, api, esc, state, toast } from "./events.js";
import { isJdUrl, previewFor, renderJobSuggestionsHtml } from "./format.js";

let jobsCache = null;

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
  const container = suggestionsContainer();
  if (container) {
    container.hidden = true;
    container.innerHTML = "";
  }
  const preview = $("[data-command-preview]");
  if (preview) preview.hidden = false;
}

async function updateSuggestions(value) {
  const container = suggestionsContainer();
  if (!container) return;
  const trimmed = String(value || "").trim();
  /* 多行文本 / URL 显然是 JD 内容，不进入搜岗位模式。 */
  if (!trimmed || isJdUrl(trimmed) || trimmed.includes("\n")) {
    clearSuggestions();
    return;
  }
  const jobs = await loadSuggestionJobs();
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
      'input, button, select, textarea, [tabindex]:not([tabindex="-1"])',
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
  palette.hidden = false;
  document.body.classList.add("command-palette-open");
  const input = $("[data-command-input]");
  if (input) {
    input.value = "";
    setPreview("");
    clearSuggestions();
    window.setTimeout(() => input.focus(), 0);
  }
}

export function closeCommandPanel() {
  const palette = $("[data-command-palette]");
  if (!palette) return;
  palette.hidden = true;
  document.body.classList.remove("command-palette-open");
  clearSuggestions();
  const input = $("[data-command-input]");
  if (input) input.blur();
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
      if (event.target === palette) closeCommandPanel();
    });
    palette.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeCommandPanel();
      }
      trapPaletteFocus(event);
    });
  }
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      openCommandPanel();
    }
  });
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
          '<a class="btn btn-outline btn-sm" href="#/workspace/' + encodeURIComponent(body.existing_job_id) + '" data-action="close-command-panel">查看该岗位 →</a>';
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
