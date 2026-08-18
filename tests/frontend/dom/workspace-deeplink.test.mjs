import test from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";

const window = new Window({ url: "http://localhost:8011/#/workspace/missing-job" });
globalThis.window = window;
globalThis.document = window.document;
globalThis.localStorage = window.localStorage;
globalThis.HTMLElement = window.HTMLElement;
globalThis.Element = window.Element;
globalThis.Node = window.Node;
globalThis.HTMLInputElement = window.HTMLInputElement;
globalThis.HTMLFormElement = window.HTMLFormElement;

document.body.innerHTML = `
  <main id="app-router-view"></main>
  <div id="toast-region"></div>
`;

const calls = [];

function jsonBody(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

async function mockFetch(path) {
  const url = String(path);
  calls.push(url);
  if (url.startsWith("/api/jobs?limit=200")) {
    return jsonBody([]);
  }
  return jsonBody({ detail: `no mock for ${url}` }, 404);
}

globalThis.fetch = mockFetch;

const { renderOptimizerCanvas, renderSplitCanvas } = await import(
  "../../../src/resualign/static/app/split-canvas.js"
);
const { state } = await import(
  "../../../src/resualign/static/app/events.js"
);

test("invalid workspace deep link redirects to dashboard without session 404s", async () => {
  await renderOptimizerCanvas(
    document.querySelector("#app-router-view"),
    "missing-job",
  );

  assert.equal(window.location.hash, "#/dashboard");
  assert.match(
    document.querySelector("#toast-region").textContent,
    /岗位不存在，已返回驾驶舱/,
  );
  assert.ok(
    calls.some((url) => url.startsWith("/api/jobs?limit=200")),
    "workbench job list is loaded before resolving the deep link",
  );
  assert.ok(
    !calls.some((url) => url.includes("/api/workspace/session/")),
    "invalid deep link must not probe /api/workspace/session/",
  );
  assert.ok(
    !calls.some((url) => url.includes("/api/workbench/session/")),
    "invalid deep link must not probe /api/workbench/session/",
  );
});

test("renderSplitCanvas is a no-op after leaving the workspace route", () => {
  document.body.innerHTML = `
    <div id="app-router-view">
      <div data-current-route="jobs">岗位库</div>
    </div>
  `;
  state.route = { name: "jobs", jobId: null, resumeId: null };
  renderSplitCanvas(
    document.querySelector("#app-router-view"),
    {
      job: { job_id: "j1", title: "后端工程师" },
      jd: {},
      gap: {},
      alignment: { status: "idle", diffs: [] },
      meta: {},
    },
    [],
    [],
  );
  assert.ok(
    document.querySelector('[data-current-route="jobs"]'),
    "jobs view must not be replaced by a stale workbench render",
  );
});
