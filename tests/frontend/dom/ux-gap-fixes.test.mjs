import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/* Must be imported first: installs browser globals before events.js
 * evaluates (it reads localStorage at module scope). */
import "./happy-setup.mjs";

import {
  recoverDiagnosis,
  renderDiagnosisResult,
  state,
} from "../../../src/resualign/static/app/events.js";
import { renderSplitCanvas } from "../../../src/resualign/static/app/split-canvas.js";

const appDir = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "..",
  "src/resualign/static/app",
);

function read(name) {
  return readFileSync(join(appDir, name), "utf8");
}

function diagnosisPanelHtml() {
  document.body.innerHTML = `
    <div data-diagnosis-panel>
      <span data-resume-band-status-text></span>
      <span data-diagnosis-meta></span>
      <div data-diagnosis-progress hidden></div>
      <div data-diagnosis-result hidden></div>
      <div data-diagnosis-error hidden></div>
      <button data-action="diagnose-resume"></button>
      <button data-action="export-diagnosis"></button>
      <button data-action="export-diagnosis-md"></button>
      <div data-ats-health-mount></div>
    </div>`;
}

test("source contracts keep the new UX gap fixes wired", () => {
  const kanban = read("kanban.js");
  assert.match(kanban, /stats\.total/, "kanban uses stats.total denominator");
  assert.doesNotMatch(kanban, /funnel\.total/, "funnel.total no longer used");

  const dashboard = read("dashboard-view.js");
  assert.match(dashboard, /currentResume\.latest_diagnosis/, "dashboard reads persisted diagnosis");

  const resumeCenter = read("resume-center.js");
  assert.match(resumeCenter, /data-resume-band-status-text/, "resume band status slot");

  const main = read("main.js");
  assert.match(main, /请先生成并保存定稿，再记录投递/, "record-application guards draft");

  const splitCanvas = read("split-canvas.js");
  assert.match(
    splitCanvas,
    /analysis-status/,
    "workbench reads analysis snapshots without 404 noise",
  );
  assert.match(splitCanvas, /reconcileAlignmentFailure/, "workbench reconciles failed jobs");
  assert.match(splitCanvas, /session\.alignment\.draft/, "guide recognizes session draft");

  const events = read("events.js");
  assert.match(
    events,
    /analysis-status/,
    "diagnosis reads analysis snapshots without 404 noise",
  );
});

test("renderDiagnosisResult syncs the resume band status", () => {
  diagnosisPanelHtml();
  renderDiagnosisResult({
    status: "succeeded",
    elapsed_seconds: 1,
    result: {
      diagnosis: {
        score: 73,
        skills: ["Java"],
        issues: [],
        suggestions: [],
        model: "test-model",
      },
    },
  });
  const band = document.querySelector("[data-resume-band-status-text]");
  assert.match(band.textContent, /73 分/);
});

test("recoverDiagnosis falls back to persisted snapshot when the job is gone", async () => {
  diagnosisPanelHtml();
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: false,
    status: 404,
    json: async () => ({ detail: "Job not found" }),
  });
  state.diagnosis = null;
  try {
    await recoverDiagnosis({
      resume_id: "r1",
      latest_diagnosis_job_id: "expired-job",
      latest_diagnosis: {
        score: 70,
        skills: ["Python"],
        issues: [],
        suggestions: [],
        model: "test-model",
      },
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
  const band = document.querySelector("[data-resume-band-status-text]");
  assert.match(band.textContent, /70 分/);
  assert.equal(
    document.querySelector("[data-diagnosis-result]").hidden,
    false,
  );
});

test("workbench guide renders from a session-only draft", () => {
  document.body.innerHTML = '<div id="app-router-view"></div>';
  const jobData = {
    job_id: "j1",
    title: "后端工程师",
    company: "Acme",
    location: "上海",
    status: "draft",
    jd_text: "Python / FastAPI",
  };
  state.wbResumes = [];
  state.wbMobilePane = "controls";
  state.wbControlsOpen = true;
  state.wbExportDockOpen = false;
  state.wbAcceptedBullets = {};
  renderSplitCanvas(
    document.querySelector("#app-router-view"),
    {
      job: jobData,
      jd: {},
      gap: {},
      alignment: { status: "succeeded", diffs: [], draft: "# 定稿" },
      meta: {},
    },
    [],
    [jobData],
  );
  const guide = document.querySelector("[data-workbench-guide]");
  assert.ok(guide, "guide renders when only the session carries a draft");
  assert.equal(guide.getAttribute("data-guide-current"), "record");
});
