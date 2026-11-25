/* P1 regression: a lane switch is a server-side filter. The first page holds
 * 500 rows and only two pending drafts; the server bucket holds 17. Clicking
 * 待定稿 must request `advance=pending_draft` and show all 17, not scan the
 * loaded page. */

import test from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";

const window = new Window({ url: "http://localhost:8012/#/jobs" });
globalThis.window = window;
globalThis.document = window.document;
globalThis.localStorage = window.localStorage;
globalThis.FormData = window.FormData;
globalThis.HTMLElement = window.HTMLElement;
globalThis.Element = window.Element;
globalThis.Node = window.Node;
globalThis.HTMLInputElement = window.HTMLInputElement;
globalThis.HTMLFormElement = window.HTMLFormElement;

document.body.innerHTML = `
  <div class="app-main">
    <main id="app-router-view"></main>
  </div>
  <div id="print-root"></div>
  <div id="toast-region"></div>
`;

function summaryJob(id, patch = {}) {
  return {
    job_id: id,
    title: `岗位 ${id}`,
    company: "示例公司",
    location: "上海",
    status: "draft",
    match_score: 60,
    jd_excerpt: "负责服务端开发与交付。",
    has_jd_profile: true,
    alignment_status: "idle",
    usable_diffs: 0,
    final_draft_version: 0,
    ...patch,
  };
}

const pending = (id) =>
  summaryJob(id, {
    alignment_status: "succeeded",
    usable_diffs: 1,
    match_score: 88,
  });

/* The loaded page: two pending drafts at the front, then 498 fillers. */
const PAGE_JOBS = [
  pending("p1"),
  pending("p2"),
  ...Array.from({ length: 498 }, (_, index) =>
    summaryJob(`f${index + 1}`, {
      alignment_status: index % 2 ? "failed" : "idle",
      jd_excerpt: index % 2 ? "" : "负责服务端开发与交付。",
    }),
  ),
];

/* Server bucket: two rows from the page + 15 rows beyond it. */
const LANE_JOBS = [
  pending("p1"),
  pending("p2"),
  ...Array.from({ length: 15 }, (_, index) => pending(`late${index + 1}`)),
];

/* The lane count is library-wide and larger than the 17-row fixture on
 * purpose: it keeps the cap label testable without a second dashboard fetch.
 * `laneRows` is mutated by the 7d case below; the mock reads both at call time. */
let pendingTotal = 600;
let laneRows = LANE_JOBS;

const calls = { jobs: [] };

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
  if (method === "GET" && url.startsWith("/api/settings")) {
    return jsonBody({
      classification_vocabulary: {
        job_functions: ["后端"],
        seniorities: ["初级"],
        statuses: ["未投递", "已投递"],
      },
    });
  }
  if (method === "GET" && url.startsWith("/api/dashboard")) {
    return jsonBody({
      kpi: { jobs: 503 },
      advance: {
        pending_draft: pendingTotal,
        unanalyzed: 100,
        unaligned: 200,
        failed: 186,
        finalized: 0,
      },
    });
  }
  if (method === "GET" && url.startsWith("/api/jobs?")) {
    calls.jobs.push(url);
    return jsonBody(url.includes("advance=pending_draft") ? laneRows : PAGE_JOBS);
  }
  if (method === "GET" && /^\/api\/jobs\/[^/?]+$/.test(url)) {
    const id = url.split("/")[3];
    return jsonBody(summaryJob(id));
  }
  if (
    method === "GET" &&
    (url.startsWith("/api/master-resumes") ||
      url.startsWith("/api/llm/nodes") ||
      url.startsWith("/api/automation/rules"))
  ) {
    return jsonBody([]);
  }
  return jsonBody({ detail: `no mock for ${method} ${url}` }, 404);
}

globalThis.fetch = mockFetch;

await import("../../../src/resualign/static/app/main.js");

async function waitFor(fn, label, timeoutMs = 4000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const value = fn();
    if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, 15));
  }
  throw new Error(`waitFor timeout: ${label}`);
}

const resultCount = () =>
  document.querySelector("[data-jh-result-count]")?.textContent || "";

test("lane switch requests the server bucket instead of scanning the page", async () => {
  await waitFor(() => document.querySelector('[data-jh-work="pending_draft"]'), "lane strip");
  await waitFor(() => resultCount().includes("500"), "first page painted");
  assert.ok(
    calls.jobs.some((url) => !url.includes("advance=")),
    "first load is unfiltered for the metric cards",
  );

  const button = document.querySelector('[data-jh-work="pending_draft"]');
  button.click();

  await waitFor(
    () => calls.jobs.some((url) => url.includes("advance=pending_draft")),
    "lane request carries advance",
  );
  await waitFor(() => resultCount().includes("17"), "all 17 lane rows painted");
  assert.equal(
    document.querySelectorAll("[data-jh-card]").length,
    17,
    "list renders every server row, including the 15 outside the first page",
  );
  assert.match(
    document.querySelector("[data-jh-metrics]")?.textContent || "",
    /503/,
    "metric cards keep the library-wide total",
  );
  assert.match(
    window.location.hash,
    /(?:^|[?&])advance=pending_draft(?:&|$)/,
    "the active lane is written to the URL",
  );
});

test("re-clicking the same lane does not refetch", async () => {
  const before = calls.jobs.filter((url) => url.includes("advance=")).length;
  document.querySelector('[data-jh-work="pending_draft"]').click();
  await new Promise((resolve) => setTimeout(resolve, 120));
  assert.equal(
    calls.jobs.filter((url) => url.includes("advance=")).length,
    before,
  );
});

test("switching back to 全部 reuses the loaded page", async () => {
  const before = calls.jobs.length;
  document.querySelector('[data-jh-work="all"]').click();
  await waitFor(() => resultCount().includes("500"), "all lanes restored");
  assert.equal(calls.jobs.length, before, "no request for the cached all view");
});

test("a lane over the 500-row cap says it is truncated", async () => {
  laneRows = Array.from({ length: 500 }, (_, index) =>
    pending(`big${index + 1}`),
  );
  window.location.hash = "#/jobs?advance=pending_draft";
  window.dispatchEvent(new window.Event("hashchange"));

  await waitFor(
    () => resultCount().includes("仅显示前 500 条"),
    "cap note rendered",
  );
  assert.match(resultCount(), /共 500 个岗位/);
  assert.ok(
    calls.jobs.some((url) => url.includes("advance=pending_draft")),
    "deep link resolves the lane server-side",
  );
});

test("a selected job keeps the lane in the URL and back restores it", async () => {
  const card = document.querySelector("[data-jh-job]");
  assert.ok(card, "a lane card is rendered");
  card.click();
  await waitFor(
    () =>
      window.location.hash.includes("job=") &&
      window.location.hash.includes("advance=pending_draft"),
    "job and lane share the URL",
  );
  assert.ok(
    document.querySelector("[data-jh-shell]").classList.contains("is-detail-open"),
    "detail opened for the selected job",
  );

  window.location.hash = "#/jobs?advance=pending_draft";
  /* Browser Back fires popstate first; that is the in-place lane restore path. */
  window.dispatchEvent(new window.Event("popstate"));
  await waitFor(
    () => {
      const shell = document.querySelector("[data-jh-shell]");
      return shell ? !shell.classList.contains("is-detail-open") : false;
    },
    "back to the lane closes the detail",
  );
  assert.match(resultCount(), /共 500 个岗位/);
  assert.match(window.location.hash, /advance=pending_draft/);
});
