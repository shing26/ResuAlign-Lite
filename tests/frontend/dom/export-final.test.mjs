/* MVP-09: workbench export menu consumes the canonical export API.
 * Boots real main.js on a workspace job with a persisted final draft and
 * verifies PDF print HTML + Markdown/JSON downloads come from
 * POST /api/jobs/{job_id}/exports, not transient session state. */

import test from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";

const window = new Window({ url: "http://localhost:8011/#/workspace/j1" });
globalThis.window = window;
globalThis.document = window.document;
globalThis.localStorage = window.localStorage;
globalThis.FormData = window.FormData;
globalThis.HTMLElement = window.HTMLElement;
globalThis.Element = window.Element;
globalThis.Node = window.Node;
globalThis.HTMLInputElement = window.HTMLInputElement;
globalThis.HTMLFormElement = window.HTMLFormElement;
globalThis.HTMLAnchorElement = window.HTMLAnchorElement;
globalThis.MutationObserver = class MutationObserver {
  observe() {}
  disconnect() {}
};

document.body.innerHTML = `
  <div class="app-main">
    <main id="app-router-view"></main>
  </div>
  <div id="print-root"></div>
  <div id="toast-region"></div>
`;

const downloads = [];
const exportsCalls = [];
let printed = 0;

window.print = () => {
  printed += 1;
};
globalThis.Blob = class Blob {
  constructor(parts, options) {
    this.parts = parts;
    this.type = options && options.type;
  }
};
URL.createObjectURL = (blob) => {
  downloads.push({
    filename: null,
    content: blob.parts.join(""),
    type: blob.type,
  });
  return "blob:mock";
};
URL.revokeObjectURL = () => {};
window.HTMLAnchorElement.prototype.click = function click() {
  const last = downloads[downloads.length - 1];
  if (last) last.filename = this.download;
};

const JOB = {
  job_id: "j1",
  title: "后端工程师",
  company: "Acme",
  status: "applied",
  jd_text: "Python / FastAPI",
  final_draft: "# 定稿",
  final_draft_version: 1,
  model: "deepseek-chat",
  prompt_version: "engine.v1",
  diffs: [
    { diff_id: "d1", provenance_state: "accepted" },
    { diff_id: "d2", provenance_state: "verified" },
  ],
};

const EXPORT_BODY = {
  job_id: "j1",
  job_title: "后端工程师",
  format: "markdown",
  final_draft_version: 1,
  content: "# 定稿 canonical",
  filename: "resualign-后端工程师-v1.md",
  meta: {
    model: "deepseek-chat",
    prompt_version: "engine.v1",
  },
  accepted_diff_ids: ["d1"],
  /* Bug-03: 结构化导出字段（后端 JSON 分支新增） */
  sections: [
    { heading: "专业技能", content: "- Python\n- Go" },
    { heading: "工作经历", content: "后端开发" },
  ],
  skills: ["Python", "Go"],
};

function jsonBody(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

async function mockFetch(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const url = String(path);
  if (method === "GET" && url.startsWith("/api/auth/me")) {
    return jsonBody({ ok: true });
  }
  if (method === "GET" && url.startsWith("/api/jobs?limit=200")) {
    return jsonBody([JOB]);
  }
  if (method === "GET" && url.startsWith("/api/jobs?limit=100")) {
    return jsonBody([JOB]);
  }
  if (method === "GET" && url.startsWith("/api/jobs/")) {
    return jsonBody(JOB);
  }
  if (method === "GET" && url.startsWith("/api/master-resumes")) {
    return jsonBody([]);
  }
  if (method === "GET" && url.startsWith("/api/settings")) {
    return jsonBody({
      classification_vocabulary: {
        job_functions: ["后端", "前端"],
        seniorities: ["初级", "高级"],
        statuses: ["未投递", "已投递"],
      },
    });
  }
  if (method === "POST" && /\/api\/jobs\/[^/]+\/exports$/.test(url)) {
    const body = JSON.parse(String(options.body || "{}"));
    const format = body.format || "markdown";
    exportsCalls.push(format);
    /* Bug-03: JSON content 为去除 Markdown 标记的纯文本（后端同契约） */
    const jsonContent = format === "json" ? "定稿 canonical" : EXPORT_BODY.content;
    return jsonBody({ ...EXPORT_BODY, format, content: jsonContent, filename: EXPORT_BODY.filename.replace(".md", `.${format === "json" ? "json" : format === "pdf" ? "pdf" : "md"}`) });
  }
  return jsonBody({ detail: `no mock for ${method} ${url}` }, 404);
}
globalThis.fetch = mockFetch;

await import("../../../src/resualign/static/app/main.js");

async function waitFor(fn, label, timeoutMs = 3000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const value = fn();
    if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, 15));
  }
  throw new Error(`waitFor timeout: ${label}`);
}

test("workbench export dock enables final actions and shows final badge", async () => {
  await waitFor(
    () => document.querySelector("[data-export-dock]"),
    "export dock rendered",
  );
  assert.ok(document.querySelector("[data-export-final-badge]"));
  assert.equal(
    document.querySelectorAll("[data-export-dock] button[disabled]").length,
    0,
  );
  /* B2 双模式：有定稿时默认进入 A4 预览，源稿面板隐藏（由 A4 纸呈现）；
   * 切到「对照编辑」后原面板显示导出/记录投递等操作。 */
  const initialPanel = document.querySelector("[data-final-draft-panel]");
  assert.ok(initialPanel && initialPanel.hidden, "a4 preview hides the source draft panel");
  document.querySelector('[data-wb-view-mode="diff"]').click();
  await waitFor(
    () => {
      const p = document.querySelector("[data-final-draft-panel]");
      return p && !p.hidden;
    },
    "final draft panel shown after switching to diff mode",
  );
  const panel = document.querySelector("[data-final-draft-panel]");
  assert.ok(panel && !panel.hidden);
  assert.ok(panel.querySelector('[data-action="export-final-draft-json"]'));
  assert.match(panel.querySelector("[data-final-draft-meta]").textContent, /模型 deepseek-chat/);
  assert.match(panel.querySelector("[data-final-draft-meta]").textContent, /Prompt engine\.v1/);
  assert.match(panel.querySelector("[data-final-draft-meta]").textContent, /采纳 1 条/);
});

test("export Markdown downloads the canonical API content", async () => {
  document.querySelector('[data-action="export-final-draft-md"]').click();
  await waitFor(() => exportsCalls.length >= 1, "markdown export API");
  await waitFor(() => downloads.length >= 1, "markdown download");
  assert.equal(exportsCalls[0], "markdown");
  assert.equal(downloads[0].filename, "resualign-后端工程师-v1.md");
  assert.equal(downloads[0].content, "# 定稿 canonical");
});

test("export JSON downloads the canonical structured API content", async () => {
  document.querySelector('[data-action="export-final-draft-json"]').click();
  await waitFor(
    () => exportsCalls.filter((format) => format === "json").length >= 1,
    "json export API",
  );
  await waitFor(() => downloads.length >= 2, "json download");
  assert.match(downloads[1].filename, /\.json$/);
  /* Bug-03: JSON 下载的是整个结构化响应（JSON.stringify(body, null, 2)），
   * 而不是把 Markdown 字符串当 JSON 写出。 */
  const body = JSON.parse(downloads[1].content);
  assert.equal(body.job_id, "j1");
  assert.equal(body.format, "json");
  assert.equal(body.filename, "resualign-后端工程师-v1.json");
  assert.equal(body.content, "定稿 canonical");
  assert.equal(body.sections[0].heading, "专业技能");
  assert.deepEqual(body.skills, ["Python", "Go"]);
});

test("export PDF fills #print-root and calls print", async () => {
  document.querySelector('[data-action="export-final-draft"]').click();
  await waitFor(
    () => exportsCalls.filter((format) => format === "pdf").length >= 1,
    "pdf export API",
  );
  await waitFor(() => printed >= 1, "window.print called");
  assert.equal(
    document.querySelector("#print-root").innerHTML,
    "",
    "print root is cleared after printing",
  );
});
