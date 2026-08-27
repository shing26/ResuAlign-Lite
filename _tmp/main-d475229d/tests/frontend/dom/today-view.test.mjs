/* MVP-08: real main.js boots on #/today, renders API reminders and the
 * reminder settings panel, and submits the reminder form via PUT. */

import test from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";

const window = new Window({ url: "http://localhost:8011/#/today" });
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

const reminders = [
  {
    job_id: "j1",
    title: "后端工程师",
    company: "Acme",
    status_canonical: "interview",
    interview_stage: "二面",
    next_step: "准备系统设计题",
    next_step_due_at: "2026-08-10 18:00",
    overdue: true,
  },
];

const calls = { reminders: 0, settings: [], settingsPut: [] };

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
  if (method === "GET" && url.startsWith("/api/reminders?scope=today")) {
    calls.reminders += 1;
    return jsonBody({ items: reminders });
  }
  if (method === "GET" && url.startsWith("/api/settings/status")) {
    return jsonBody({
      api_key_configured: true,
      daily: { calls: 0, estimated_cost: 0, cap: null, blocked: false },
      reminder: {
        enabled: true,
        provider: "feishu",
        webhook_url_configured: false,
        webhook_secret_configured: true,
        smtp_configured: false,
        smtp_password_configured: true,
        interval_seconds: 30,
      },
    });
  }
  if (method === "GET" && url.startsWith("/api/settings")) {
    calls.settings.push(url);
    return jsonBody({
      classification_vocabulary: {
        job_functions: ["后端", "前端"],
        seniorities: ["初级", "高级"],
        statuses: ["未投递", "已投递"],
      },
      reminder: {
        enabled: true,
        provider: "feishu",
        smtp_host: "smtp.example.com",
        smtp_port: 465,
        smtp_user: "user",
        smtp_from: "from@example.com",
        smtp_to: "to@example.com",
      },
    });
  }
  if (method === "PUT" && url.startsWith("/api/settings")) {
    calls.settingsPut.push({
      url,
      body: options.body ? JSON.parse(String(options.body)) : null,
    });
    return jsonBody({ ok: true });
  }
  if (method === "GET" && url.startsWith("/api/llm/nodes")) {
    return jsonBody([]);
  }
  if (method === "GET" && url.startsWith("/api/automation/rules")) {
    return jsonBody([]);
  }
  if (method === "GET" && url.startsWith("/api/master-resumes")) {
    return jsonBody([]);
  }
  if (method === "GET" && url.startsWith("/api/blockers")) {
    return jsonBody([]);
  }
  if (method === "GET" && url.startsWith("/api/jobs")) {
    return jsonBody([]);
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

test("#/today renders reminder rows from the API", async () => {
  await waitFor(
    () => document.querySelector("[data-today-item]"),
    "today reminder rendered",
  );
  assert.equal(calls.reminders, 1);
  assert.equal(document.querySelector("[data-today-count]").textContent, "1 条");
  const row = document.querySelector("[data-today-item]");
  assert.equal(row.dataset.jobId, "j1");
  assert.equal(
    row.querySelector("a").getAttribute("href"),
    "#/workspace/j1",
  );
  assert.ok(
    row.querySelector('[data-action="open-job-followup"][data-id="j1"]'),
  );
  assert.match(row.querySelector("[data-today-due]").textContent, /已过期/);
});

test("settings route renders the reminder panel and PUTs the payload", async () => {
  window.location.hash = "#/settings";
  window.dispatchEvent(new window.Event("hashchange"));
  await waitFor(
    () => document.querySelector("[data-reminder-settings-panel]"),
    "reminder settings panel rendered",
  );
  const panel = document.querySelector("[data-reminder-settings-panel]");
  assert.equal(panel.querySelector("[data-reminder-enabled]").textContent.trim(), "已开启");
  assert.equal(panel.querySelector('[data-form="settings-reminder"] input[name="smtp_host"]').value, "smtp.example.com");
  const form = panel.querySelector('[data-form="settings-reminder"]');
  form.querySelector('input[name="enabled"]').checked = false;
  form.querySelector('input[name="smtp_port"]').value = "587";
  form.dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
  await waitFor(
    () => calls.settingsPut.length >= 1,
    "reminder settings PUT",
  );
  assert.deepEqual(calls.settingsPut[0].body, {
    reminder: {
      enabled: false,
      auto_followup_reminder: true,
      provider: "feishu",
      smtp_host: "smtp.example.com",
      smtp_port: 587,
      smtp_user: "user",
      smtp_from: "from@example.com",
      smtp_to: "to@example.com",
    },
  });
});
