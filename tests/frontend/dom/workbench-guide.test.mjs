import test from "node:test";
import assert from "node:assert/strict";

/* Must be imported first: installs browser globals before events.js
 * evaluates (it reads localStorage at module scope). */
import "./happy-setup.mjs";

import { state } from "../../../src/resualign/static/app/events.js";
import { renderSplitCanvas } from "../../../src/resualign/static/app/split-canvas.js";

function job(overrides = {}) {
  return {
    job_id: "j1",
    title: "后端工程师",
    company: "Acme",
    location: "上海",
    status: "draft",
    jd_text: "Python / FastAPI",
    ...overrides,
  };
}

function render(app, jobData, resumes = []) {
  state.route = { name: "workspace", jobId: jobData.job_id, resumeId: null };
  state.wbResumes = resumes;
  state.wbMobilePane = "controls";
  state.wbControlsOpen = true;
  state.wbExportDockOpen = false;
  state.wbAcceptedBullets = {};
  renderSplitCanvas(
    app,
    {
      job: jobData,
      jd: {},
      gap: {},
      alignment: { status: "idle", diffs: [] },
      meta: {},
    },
    resumes,
    [jobData],
  );
  return app;
}

test("workbench guide renders after final draft and points to record", () => {
  document.body.innerHTML = '<div id="app-router-view"></div>';
  const app = render(
    document.querySelector("#app-router-view"),
    job({ final_draft: "# 定稿" }),
  );
  const guide = app.querySelector("[data-workbench-guide]");
  assert.ok(guide, "guide strip renders with a final draft");
  assert.equal(guide.getAttribute("data-guide-current"), "record");
  assert.ok(
    app.querySelector('[data-action="record-application"][data-id="j1"]'),
    "guide reuses record-application",
  );
  const primary = app.querySelector('[data-action="go-resumes"]');
  assert.ok(primary, "primary button becomes create resume without resumes");
  assert.match(primary.textContent, /先创建主简历/);
});

test("workbench guide advances to follow-up and restores alignment button", () => {
  document.body.innerHTML = '<div id="app-router-view"></div>';
  const app = render(
    document.querySelector("#app-router-view"),
    job({
      status: "applied",
      applied_at: "2026-08-14",
      final_draft: "# 定稿",
    }),
    [{ resume_id: "r1", title: "主简历", current_version: 1 }],
  );
  const guide = app.querySelector("[data-workbench-guide]");
  assert.equal(guide.getAttribute("data-guide-current"), "followup");
  assert.ok(
    app.querySelector('[data-action="open-job-followup"][data-id="j1"]'),
    "guide reuses open-job-followup after record",
  );
  const primary = app.querySelector('[data-action="run-alignment"]');
  assert.ok(primary, "alignment button returns when resumes exist");
  assert.match(primary.textContent, /重新生成对齐/);
});

test("workbench guide completes after follow-up is arranged", () => {
  document.body.innerHTML = '<div id="app-router-view"></div>';
  const app = render(
    document.querySelector("#app-router-view"),
    job({
      status: "interview",
      applied_at: "2026-08-14",
      final_draft: "# 定稿",
      next_step_due_at: "2026-08-20T10:00",
      interview_stage: "二面",
    }),
    [{ resume_id: "r1", title: "主简历", current_version: 1 }],
  );
  assert.equal(
    app
      .querySelector("[data-workbench-guide]")
      .getAttribute("data-guide-current"),
    "",
  );
  assert.equal(
    app.querySelectorAll("[data-workbench-guide] .workbench-guide__actions button")
      .length,
    0,
  );
});
