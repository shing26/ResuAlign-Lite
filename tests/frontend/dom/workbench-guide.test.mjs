import test from "node:test";
import assert from "node:assert/strict";

/* Must be imported first: installs browser globals before events.js
 * evaluates (it reads localStorage at module scope). */
import "./happy-setup.mjs";

import { state } from "../../../src/resualign/static/app/events.js";
import {
  applyJobResultToSession,
  buildSessionFromJob,
  renderSplitCanvas,
} from "../../../src/resualign/static/app/split-canvas.js";

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
  assert.match(primary.textContent, /开始对齐/);
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

/* P0-1/P0-2: 失败横幅 = 分类徽标 + 阶段/耗时元信息，且不再自带第二个
   「重新运行对齐」按钮（收敛到顶栏单入口）；失败态同时抑制首次引导卡。 */
test("failed alignment renders classified banner with stage+elapsed and no inner rerun button", () => {
  document.body.innerHTML = '<div id="app-router-view"></div>';
  const bannerHtml = (() => {
    /* 直接复用 renderSplitCanvas 的失败对齐态：控制台上重新渲染一次 */
    state.route = { name: "workspace", jobId: "j2", resumeId: null };
    state.wbMobilePane = "controls";
    renderSplitCanvas(
      document.querySelector("#app-router-view"),
      {
        job: job({ job_id: "j2" }),
        jd: {},
        gap: {},
        alignment: {
          status: "failed",
          stage: "jd_analysis",
          elapsed_seconds: 166.2,
          error:
            "对齐分析在「JD 画像与差距分析」阶段失败：模型响应超时（本次耗时 166.2 秒），可尝试更换更快的模型或稍后重试",
          diffs: [],
        },
        meta: {},
      },
      [{ resume_id: "r1", title: "主简历", current_version: 1 }],
      [job({ job_id: "j2" })],
    );
    return document.querySelector("#app-router-view").innerHTML;
  })();
  assert.match(bannerHtml, /data-align-error-banner/);
  assert.match(bannerHtml, /data-align-error-kind="timeout"/);
  assert.match(bannerHtml, /模型响应超时（本次耗时 166\.2 秒）/);
  assert.match(bannerHtml, /本次耗时 2:46/);
  assert.doesNotMatch(bannerHtml, /data-resume-canvas-empty/, "failed state hides first-run guide");
  const banner = document.querySelector("[data-align-error-banner]");
  assert.ok(banner, "banner element rendered");
  assert.equal(
    banner.querySelectorAll('[data-action="run-alignment"]').length,
    0,
    "banner carries no inner rerun button (top-bar single entry)",
  );
  const topButton = document.querySelector('[data-action="run-alignment"]');
  assert.ok(topButton, "top-bar rerun button stays as the single entry");
  assert.match(topButton.textContent, /重新运行对齐/);
});

/* R5 P1-4（02-UID ③-4 + R2 合议 Q4）：移动端底栏动作条 —— 仅失败/取消/过期
   （可重试）与运行中常驻；idle/succeeded 不渲染底栏。底栏按钮与顶栏同款，
   ≤640px 时由 CSS 隐藏顶栏按钮避免同屏双入口。 */
test("failed alignment renders the mobile bottom action bar with the rerun button", () => {
  document.body.innerHTML = '<div id="app-router-view"></div>';
  state.route = { name: "workspace", jobId: "j3", resumeId: null };
  state.wbMobilePane = "controls";
  renderSplitCanvas(
    document.querySelector("#app-router-view"),
    {
      job: job({ job_id: "j3" }),
      jd: {},
      gap: {},
      alignment: {
        status: "failed",
        error: "模型响应超时",
        elapsed_seconds: 60,
        diffs: [],
      },
      meta: {},
    },
    [{ resume_id: "r1", title: "主简历", current_version: 1 }],
    [job({ job_id: "j3" })],
  );
  const view = document.querySelector(".workbench-view");
  assert.equal(
    view.getAttribute("data-mobile-action-bar"),
    "true",
    "failed state activates the mobile action bar",
  );
  const bar = document.querySelector("[data-wb-action-bar]");
  assert.ok(bar, "bottom action bar is rendered");
  const barButton = bar.querySelector('[data-action="run-alignment"]');
  assert.ok(barButton, "bar carries the rerun button");
  assert.match(barButton.textContent, /重新运行对齐/);
});

test("running alignment renders the bottom action bar with a busy button", () => {
  document.body.innerHTML = '<div id="app-router-view"></div>';
  state.route = { name: "workspace", jobId: "j4", resumeId: null };
  state.wbMobilePane = "controls";
  renderSplitCanvas(
    document.querySelector("#app-router-view"),
    {
      job: job({ job_id: "j4" }),
      jd: {},
      gap: {},
      alignment: { status: "running", diffs: [] },
      meta: {},
    },
    [{ resume_id: "r1", title: "主简历", current_version: 1 }],
    [job({ job_id: "j4" })],
  );
  assert.equal(
    document.querySelector(".workbench-view").getAttribute("data-mobile-action-bar"),
    "true",
  );
  const barButton = document.querySelector('[data-wb-action-bar] [data-action="run-alignment"]');
  assert.ok(barButton);
  assert.ok(barButton.disabled, "running bar button is disabled");
});

test("idle/succeeded workbench does not render the bottom action bar", () => {
  for (const status of ["idle", "succeeded"]) {
    document.body.innerHTML = '<div id="app-router-view"></div>';
    state.route = { name: "workspace", jobId: "j5", resumeId: null };
    state.wbMobilePane = "controls";
    renderSplitCanvas(
      document.querySelector("#app-router-view"),
      {
        job: job({ job_id: "j5", status: "applied" }),
        jd: {},
        gap: {},
        alignment: { status, diffs: [] },
        meta: {},
      },
      [{ resume_id: "r1", title: "主简历", current_version: 1 }],
      [job({ job_id: "j5", status: "applied" })],
    );
    assert.equal(
      document.querySelector(".workbench-view").getAttribute("data-mobile-action-bar"),
      null,
      `${status} must not reserve the bottom bar`,
    );
    assert.equal(document.querySelector("[data-wb-action-bar]"), null);
  }
});

test("job.result event preserves a no-safe terminal instead of forcing success", () => {
  const session = {
    job: job({ job_id: "j-live-safe" }),
    jd: {},
    gap: {
      gap_report: {
        missing_keywords: ["Kubernetes"],
        misaligned_emphasis: ["平台稳定性"],
      },
    },
    alignment: { status: "running", diffs: [] },
    meta: {},
  };
  applyJobResultToSession(session, {
    job_id: "j-live-safe",
    alignment: {
      status: "failed",
      reason: "no_safe_rewrite",
      error: "岗位要求 Kubernetes，但简历原文没有可逐字定位的证据。",
      notice: null,
      diffs: [],
      invalid_diffs: [],
      draft: null,
      eval_score: null,
    },
    result: { diffs: [], invalid_diffs: [] },
  });
  assert.equal(session.alignment.status, "failed");
  assert.equal(session.alignment.reason, "no_safe_rewrite");
  assert.equal(
    session.alignment.error,
    "岗位要求 Kubernetes，但简历原文没有可逐字定位的证据。",
  );
});

test("job.result event preserves a model failure instead of forcing success", () => {
  const session = {
    job: job({ job_id: "j-live-model" }),
    jd: {},
    gap: {},
    alignment: { status: "running", diffs: [] },
    meta: {},
  };
  applyJobResultToSession(session, {
    job_id: "j-live-model",
    alignment: {
      status: "failed",
      reason: "model_failed",
      error: "模型响应超时",
      notice: null,
      diffs: [],
      invalid_diffs: [],
      draft: null,
      eval_score: null,
    },
    result: { diffs: [], invalid_diffs: [] },
  });
  assert.equal(session.alignment.status, "failed");
  assert.equal(session.alignment.reason, "model_failed");
});

test("persisted terminal reasons survive refresh for all three outcomes", () => {
  const cases = [
    {
      reason: "no_safe_rewrite",
      status: "failed",
      error: "简历原文没有可逐字定位的证据。",
      needle: /无安全改写/,
      forbidden: /已对齐/,
    },
    {
      reason: "model_failed",
      status: "failed",
      error: "模型响应超时",
      needle: /模型失败|对齐失败/,
      forbidden: /已对齐/,
    },
    {
      reason: "no_gap",
      status: "succeeded",
      error: null,
      needle: /无需改写/,
      forbidden: /已对齐/,
    },
  ];
  for (const item of cases) {
    const session = buildSessionFromJob(
      job({
        job_id: `j-${item.reason}`,
        alignment_status: item.status,
        alignment_reason: item.reason,
        alignment_error: item.error,
        usable_diffs: 0,
        has_gap: item.reason !== "no_gap",
        gap_report:
          item.reason === "no_gap"
            ? { missing_keywords: [], misaligned_emphasis: [] }
            : { missing_keywords: ["Kubernetes"] },
        diffs: [],
        invalid_diffs: [],
      }),
    );
    document.body.innerHTML = '<div id="app-router-view"></div>';
    state.route = {
      name: "workspace",
      jobId: `j-${item.reason}`,
      resumeId: null,
    };
    state.wbMobilePane = "controls";
    renderSplitCanvas(
      document.querySelector("#app-router-view"),
      session,
      [{ resume_id: "r1", title: "主简历", current_version: 1 }],
      [session.job],
    );
    const html = document.querySelector("#app-router-view").innerHTML;
    assert.equal(session.alignment.reason, item.reason);
    assert.equal(session.alignment.error, item.error);
    assert.match(html, item.needle);
    assert.doesNotMatch(html, item.forbidden);
    assert.doesNotMatch(html, /no_output:/);
  }
});

function renderTerminal(jobId, alignment, gap = {}) {
  document.body.innerHTML = '<div id="app-router-view"></div>';
  const jobData = job({ job_id: jobId });
  state.route = { name: "workspace", jobId, resumeId: null };
  state.wbMobilePane = "controls";
  state.wbAcceptedBullets = {};
  renderSplitCanvas(
    document.querySelector("#app-router-view"),
    {
      job: jobData,
      jd: {},
      gap: { status: "ready", gap_report: gap, ...gap },
      alignment,
      meta: {},
    },
    [{ resume_id: "r1", title: "主简历", current_version: 1 }],
    [jobData],
  );
  return document.querySelector("#app-router-view");
}

test("no_safe_rewrite renders evidence explanation without green or generic failure", () => {
  const app = renderTerminal(
    "j-safe",
    {
      status: "failed",
      reason: "no_safe_rewrite",
      error: "岗位要求 Kubernetes，但简历原文没有可逐字定位的证据。",
      diffs: [],
      invalid_diffs: [],
    },
    {
      missing_keywords: ["Kubernetes"],
      misaligned_emphasis: ["平台稳定性"],
      gap_report: {
        missing_keywords: ["Kubernetes"],
        misaligned_emphasis: ["平台稳定性"],
      },
    },
  );
  const html = app.innerHTML;
  assert.match(html, /无安全改写/);
  assert.match(html, /原文依据不足/);
  assert.match(html, /Kubernetes/);
  assert.match(html, /未改写方向：平台稳定性/);
  assert.doesNotMatch(html, /已对齐|任务失败|no_output:/);
  assert.equal(document.querySelectorAll('[data-action="run-alignment"]').length, 0);
  assert.ok(
    document.querySelector(
      '[data-action="set-wb-tab-v3"][data-wb-tab-v3="inspector"]',
    ),
  );
  assert.equal(
    document.querySelectorAll("[data-export-dock] button[disabled]").length,
    3,
  );
});

test("model failure renders rerun and node-change guidance", () => {
  const app = renderTerminal("j-model", {
    status: "failed",
    reason: "model_failed",
    error: "模型响应超时",
    diffs: [
      {
        diff_id: "stale-1",
        type: "modify",
        original: "Built a service",
        proposed: "Built a faster service",
        provenance_state: "verified",
      },
    ],
    invalid_diffs: [],
  });
  assert.match(app.innerHTML, /对齐失败 · 超时/);
  assert.match(app.innerHTML, /模型响应超时/);
  assert.match(app.innerHTML, /换节点重试/);
  assert.doesNotMatch(app.innerHTML, /pill-success">已对齐|dot-success/);
  assert.match(
    document.querySelector('[data-action="run-alignment"]').textContent,
    /重新运行对齐/,
  );
});

test("true no-gap stays amber, says no rewrite, and disables unsaved export", () => {
  const app = renderTerminal("j-gap", {
    status: "succeeded",
    reason: "no_gap",
    notice: "当前岗位没有需要补足的明确缺口，简历无需改写。",
    draft: "未保存的候选稿",
    diffs: [],
    invalid_diffs: [],
  });
  assert.match(app.innerHTML, /无需改写/);
  assert.doesNotMatch(app.innerHTML, /已对齐/);
  assert.equal(
    document.querySelectorAll("[data-export-dock] button[disabled]").length,
    3,
  );
  assert.equal(document.querySelector("[data-action='run-alignment']"), null);
  assert.equal(document.querySelector("[data-align-run]"), null);
  const finalPanel = document.querySelector("[data-final-draft-panel]");
  assert.ok(!finalPanel || finalPanel.hidden);
});
