/* Universal command palette: paste JD text or a JD URL, confirm, open Optimizer. */

import { $, api, esc, toast } from "./events.js";

const URL_RE = /^https?:\/\/[^\s]+$/i;

export function isJdUrl(value) {
  return URL_RE.test(String(value || "").trim());
}

function previewFor(value) {
  const trimmed = String(value || "").trim();
  if (!trimmed) {
    return `<div class="command-preview command-preview--hint">粘贴 JD 文本或输入 JD 链接，确认后自动建库并预分析。</div>`;
  }
  if (isJdUrl(trimmed)) {
    return `
      <div class="command-preview command-preview--url">
        <div class="command-preview__head">
          <span class="badge badge-blue">JD 链接</span>
          <span class="small muted">将抓取岗位内容并自动入库存档</span>
        </div>
        <div class="command-preview__line">${esc(trimmed)}</div>
      </div>`;
  }
  const lines = trimmed.split(/\r?\n/).filter(Boolean);
  const previewLines = lines.slice(0, 5);
  return `
    <div class="command-preview command-preview--text">
      <div class="command-preview__head">
        <span class="badge badge-teal">JD 文本</span>
        <span class="small muted">${trimmed.length} 字符 · ${lines.length} 行</span>
      </div>
      <div class="command-preview__body">${previewLines.map((line) => `<div>${esc(line)}</div>`).join("")}${lines.length > 5 ? `<div class="small muted">… 其余 ${lines.length - 5} 行</div>` : ""}</div>
    </div>`;
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
    window.setTimeout(() => input.focus(), 0);
  }
}

export function closeCommandPanel() {
  const palette = $("[data-command-palette]");
  if (!palette) return;
  palette.hidden = true;
  document.body.classList.remove("command-palette-open");
  const input = $("[data-command-input]");
  if (input) input.blur();
}

export function initializeCommandPanel() {
  const input = $("[data-command-input]");
  if (input) {
    input.addEventListener("input", () => setPreview(input.value));
    input.addEventListener("paste", () => {
      window.setTimeout(() => setPreview(input.value), 0);
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
    });
  }
  const palette = $("[data-command-palette]");
  if (palette) {
    palette.addEventListener("click", (event) => {
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
    const body = isJdUrl(value)
      ? { jd_url: value }
      : { raw_jd: value };
    const session = await api("/api/workbench/session/init", {
      method: "POST",
      body: JSON.stringify(body),
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
