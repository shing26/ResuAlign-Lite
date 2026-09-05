import { test } from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  APPLICATION_RESULT_LABELS,
  boardCard,
  jobTimelineFormHtml,
  renderBoardCard,
} from "../../src/resualign/static/app/format.js";

const appDir = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "src/resualign/static/app",
);

function read(name) {
  return readFileSync(join(appDir, name), "utf8");
}

function bodyFrom(html) {
  const window = new Window();
  window.document.body.innerHTML = html;
  return window.document.body;
}

const DETAIL_JOB = {
  job_id: "j1",
  title: "后端工程师",
  company: "Acme",
  location: "上海",
  status: "draft",
  match_score: 82.5,
  match_score_detail: {
    hard_skills: 90,
    scenario: 80,
    expression: 70,
    experience: 85,
    total: 82.5,
  },
  match_reason: "四维匹配 82.5 分，建议优先投递",
  match_reason_source: "fallback",
  match_stale: true,
};

test("boardCard renders four match dimensions with labels and values", () => {
  const body = bodyFrom(boardCard(DETAIL_JOB));
  const dims = [...body.querySelectorAll("[data-match-dimension]")];
  assert.equal(dims.length, 4);
  assert.deepEqual(
    dims.map((node) => node.dataset.matchDimension),
    ["hard_skills", "scenario", "expression", "experience"],
  );
  assert.equal(dims[0].textContent.includes("硬技能"), true);
  assert.equal(dims[0].textContent.includes("90"), true);
  assert.equal(dims[1].textContent.includes("场景"), true);
  assert.equal(dims[2].textContent.includes("表达"), true);
  assert.equal(dims[3].textContent.includes("经验"), true);
});

test("boardCard exposes total, reason source and stale recompute action", () => {
  const body = bodyFrom(boardCard(DETAIL_JOB));
  assert.equal(body.querySelector("[data-match-total]").textContent, "83");
  assert.match(
    body.querySelector("[data-match-reason]").textContent,
    /四维匹配 82\.5 分/,
  );
  assert.ok(body.querySelector('[data-match-source="fallback"]'));
  assert.ok(body.querySelector("[data-match-stale]"));
  assert.ok(
    body.querySelector(
      '[data-action="recompute-match"][data-id="j1"]',
    ),
  );
});

test("boardCard escapes match reason and dimension labels", () => {
  const hostile = {
    ...DETAIL_JOB,
    match_reason: '<script>alert(1)</script>',
    match_score_detail: {
      hard_skills: 1,
      scenario: 2,
      expression: 3,
      experience: 4,
    },
  };
  const body = bodyFrom(boardCard(hostile));
  assert.equal(body.querySelector("script"), null);
  assert.match(body.querySelector("[data-match-reason]").textContent, /<script>/);
});

test("boardCard shows legacy hint when only match_score exists", () => {
  const legacy = {
    ...DETAIL_JOB,
    match_score_detail: null,
    match_reason: null,
    match_stale: false,
  };
  const body = bodyFrom(boardCard(legacy));
  assert.ok(body.querySelector("[data-match-legacy]"));
  assert.equal(body.querySelector("[data-match-total]").textContent, "83");
  assert.equal(body.querySelectorAll("[data-match-dimension]").length, 0);
});

test("boardCard omits match block for unanalyzed jobs", () => {
  const body = bodyFrom(
    boardCard({
      ...DETAIL_JOB,
      match_score: null,
      match_score_detail: null,
      match_reason: null,
      match_stale: false,
    }),
  );
  assert.equal(body.querySelector("[data-match-block]"), null);
  assert.match(body.querySelector(".match-badge--empty").textContent, /待分析/);
});

test("renderBoardCard renders the same match block contract", () => {
  const body = bodyFrom(renderBoardCard(DETAIL_JOB));
  assert.equal(body.querySelectorAll("[data-match-dimension]").length, 4);
  assert.ok(body.querySelector("[data-match-total]"));
  assert.ok(body.querySelector("[data-match-stale]"));
  assert.ok(
    body.querySelector('[data-action="recompute-match"][data-id="j1"]'),
  );
});

/* P1-2：卡片状态下拉与筛选/编辑同源 —— 标签取自设置词表，恒为五个
 * canonical key（状态机完整）；词表缺项回退内建标签。 */
test("boardCard status dropdown follows the settings vocabulary labels", () => {
  const renamed = ["未投递", "已投递", "面试中", "已拿Offer", "放弃"];
  const body = bodyFrom(boardCard(DETAIL_JOB, renamed));
  const select = body.querySelector("[data-board-status]");
  const options = [...select.querySelectorAll("option")];
  assert.deepEqual(
    options.map((option) => option.value),
    ["draft", "applied", "interview", "offer", "withdrawn"],
    "values stay the canonical five (FSM intact)",
  );
  assert.deepEqual(
    options.map((option) => option.textContent),
    renamed,
    "labels are rendered from the settings vocabulary",
  );
  assert.equal(options[0].selected, true, "draft job selects the draft option");
});

test("boardCard status dropdown keeps all five options even for a subset vocabulary", () => {
  const subset = ["未投递", "已投递"]; /* 后端目前允许子集（Q1 约束未强制） */
  const body = bodyFrom(boardCard(DETAIL_JOB, subset));
  const options = [...body.querySelectorAll("[data-board-status] option")];
  assert.equal(options.length, 5, "subset vocabulary must not shrink the card dropdown");
  assert.deepEqual(options.map((option) => option.value), [
    "draft",
    "applied",
    "interview",
    "offer",
    "withdrawn",
  ]);
  assert.deepEqual(
    options.map((option) => option.textContent),
    ["未投递", "已投递", "面试中", "已拿Offer", "放弃"],
    "missing vocabulary entries fall back to built-in labels",
  );
});

test("boardCard status dropdown falls back to built-in statuses", () => {
  const body = bodyFrom(boardCard(DETAIL_JOB));
  const options = [...body.querySelectorAll("[data-board-status] option")];
  assert.equal(options.length, 5);
  assert.deepEqual(options.map((option) => option.value), [
    "draft",
    "applied",
    "interview",
    "offer",
    "withdrawn",
  ]);
});

test("renderBoardCard status dropdown follows the settings vocabulary", () => {
  const renamed = ["未投递", "已投递", "面试中", "已拿Offer", "放弃"];
  const body = bodyFrom(renderBoardCard(DETAIL_JOB, renamed));
  const options = [...body.querySelectorAll("[data-board-status] option")];
  assert.deepEqual(options.map((option) => option.value), [
    "draft",
    "applied",
    "interview",
    "offer",
    "withdrawn",
  ]);
  assert.deepEqual(options.map((option) => option.textContent), renamed);
});

test("match dimensions tolerate missing or invalid values", () => {
  const partial = {
    ...DETAIL_JOB,
    match_score_detail: {
      hard_skills: 45,
      scenario: "bad",
      expression: null,
      experience: 100,
    },
  };
  const body = bodyFrom(boardCard(partial));
  const dims = [...body.querySelectorAll("[data-match-dimension]")];
  assert.equal(dims[1].querySelector("b").textContent, "—");
  assert.equal(dims[1].querySelector(".match-dim__track i").style.width, "0%");
  assert.equal(dims[2].querySelector("b").textContent, "—");
  assert.equal(dims[3].querySelector("b").textContent, "100");
});

/* ------------------------------------------------------------------ */
/* Phase E: card align button by alignment_status                     */
/* ------------------------------------------------------------------ */

function makeAlignJob(overrides = {}) {
  return {
    job_id: "j-align",
    title: "Align Test",
    company: "TestCo",
    location: "北京",
    status: "draft",
    alignment_status: "idle",
    diffs: [],
    ...overrides,
  };
}

test("boardCard idle alignment_status shows 开始对齐 button", () => {
  const body = bodyFrom(boardCard(makeAlignJob()));
  const btn = body.querySelector(".board-card__align");
  assert.ok(btn, "idle job must have an align button");
  assert.equal(btn.textContent, "开始对齐");
  assert.equal(btn.dataset.action, "align-job");
});

test("boardCard failed alignment_status shows 重新对齐 button", () => {
  const body = bodyFrom(boardCard(makeAlignJob({ alignment_status: "failed" })));
  const btn = body.querySelector(".board-card__align");
  assert.ok(btn, "failed job must have an align button");
  assert.equal(btn.textContent, "重新对齐");
});

test("boardCard succeeded with zero diffs shows 重新对齐 button", () => {
  const body = bodyFrom(
    boardCard(makeAlignJob({ alignment_status: "succeeded", diffs: [] })),
  );
  const btn = body.querySelector(".board-card__align");
  assert.ok(btn, "succeeded+0 diff job must have an align button");
  assert.equal(btn.textContent, "重新对齐");
});

test("boardCard succeeded with diffs shows no align button", () => {
  const body = bodyFrom(
    boardCard(
      makeAlignJob({
        alignment_status: "succeeded",
        diffs: [{ original: "a", proposed: "b" }],
      }),
    ),
  );
  const btn = body.querySelector(".board-card__align");
  assert.equal(btn, null, "succeeded with diffs must have NO align button");
});

test("boardCard succeeded with zero diffs shows 无建议 badge", () => {
  const body = bodyFrom(
    boardCard(makeAlignJob({ alignment_status: "succeeded", diffs: [] })),
  );
  const badge = [...body.querySelectorAll(".badge-amber")].find((node) =>
    node.textContent.includes("无建议"),
  );
  assert.ok(badge, "succeeded+0 diff must show 无建议 badge");
});

test("renderBoardCard idle alignment_status shows 开始对齐 button", () => {
  const body = bodyFrom(renderBoardCard(makeAlignJob()));
  const btn = body.querySelector(".board-card__align");
  assert.ok(btn, "idle job must have an align button on renderBoardCard");
  assert.equal(btn.textContent, "开始对齐");
});

test("renderBoardCard failed alignment_status shows 重新对齐 button", () => {
  const body = bodyFrom(renderBoardCard(makeAlignJob({ alignment_status: "failed" })));
  const btn = body.querySelector(".board-card__align");
  assert.ok(btn, "failed job must have an align button on renderBoardCard");
  assert.equal(btn.textContent, "重新对齐");
});

test("renderBoardCard succeeded with zero diffs shows 重新对齐 button", () => {
  const body = bodyFrom(
    renderBoardCard(makeAlignJob({ alignment_status: "succeeded", diffs: [] })),
  );
  const btn = body.querySelector(".board-card__align");
  assert.ok(btn, "succeeded+0 diff job must have an align button on renderBoardCard");
  assert.equal(btn.textContent, "重新对齐");
});

test("renderBoardCard succeeded with diffs shows no align button", () => {
  const body = bodyFrom(
    renderBoardCard(
      makeAlignJob({
        alignment_status: "succeeded",
        diffs: [{ original: "a", proposed: "b" }],
      }),
    ),
  );
  const btn = body.querySelector(".board-card__align");
  assert.equal(
    btn,
    null,
    "succeeded with diffs must have NO align button on renderBoardCard",
  );
});

test("boardCard distinguishes degraded tailor from plain empty diffs", () => {
  const degraded = bodyFrom(
    boardCard({
      ...DETAIL_JOB,
      alignment_status: "succeeded",
      diffs: [],
      last_alignment_error: "改写阶段多次失败，本轮只产出诊断与缺口分析",
    }),
  );
  const amberTexts = (body) =>
    [...body.querySelectorAll(".board-card__tags .badge-amber")].map(
      (el) => el.textContent,
    );
  assert.ok(
    amberTexts(degraded).some((text) => /诊断完成 · 改写未产出/.test(text)),
    `degraded run shows the degraded badge, got: ${amberTexts(degraded)}`,
  );

  const plain = bodyFrom(
    boardCard({ ...DETAIL_JOB, alignment_status: "succeeded", diffs: [] }),
  );
  assert.ok(
    amberTexts(plain).some((text) => /无建议/.test(text)),
    "plain empty run still shows the generic badge",
  );
});


test("boardCard renders application result badge in timeline", () => {
  const body = bodyFrom(
    boardCard({ ...DETAIL_JOB, application_result: "screen_pass" }),
  );
  const badge = body.querySelector('.board-card__timeline .badge[title="投递结果归因"]');
  assert.ok(badge, "result badge renders in timeline");
  assert.equal(badge.textContent, APPLICATION_RESULT_LABELS.screen_pass);

  const none = bodyFrom(boardCard(DETAIL_JOB));
  assert.equal(
    none.querySelector('.board-card__timeline .badge[title="投递结果归因"]'),
    null,
    "no badge without attribution",
  );
});

test("jobTimelineFormHtml offers attribution select with current value", () => {
  const body = bodyFrom(jobTimelineFormHtml({ ...DETAIL_JOB, application_result: "ats_reject" }, []));
  const select = body.querySelector('select[name="application_result"]');
  assert.ok(select, "attribution select renders in detail form");
  const selected = [...select.options].find((o) => o.hasAttribute("selected"));
  assert.equal(selected.value, "ats_reject");
  assert.equal(selected.textContent, APPLICATION_RESULT_LABELS.ats_reject);
  assert.ok(
    [...select.options].some((o) => o.textContent === "暂无回音"),
    "all four attribution labels present",
  );
});

test("dashboard source contract wires quality adoption card", () => {
  const source = read("dashboard-view.js");
  assert.match(source, /payload\.quality/, "dashboard consumes quality payload");
  assert.match(source, /采纳率/, "adoption card exists");
  assert.match(source, /data-kpi="quality"/, "quality card is tagged");
});

test("boardCard renders deadline badge states", () => {
  const soon = new Date(Date.now() + 3 * 86400000).toISOString().slice(0, 10);
  const past = new Date(Date.now() - 3 * 86400000).toISOString().slice(0, 10);
  const later = new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10);

  const soonBody = bodyFrom(boardCard({ ...DETAIL_JOB, deadline: soon }));
  const soonBadge = [...soonBody.querySelectorAll(".board-card__timeline .badge")].find((el) =>
    /7 天内截止/.test(el.textContent),
  );
  assert.ok(soonBadge, "due-soon deadline renders amber badge");

  const pastBody = bodyFrom(boardCard({ ...DETAIL_JOB, deadline: past }));
  const pastBadge = [...pastBody.querySelectorAll(".board-card__timeline .badge")].find((el) =>
    /已截止/.test(el.textContent),
  );
  assert.ok(pastBadge, "expired deadline renders red badge");

  const laterBody = bodyFrom(boardCard({ ...DETAIL_JOB, deadline: later }));
  assert.equal(
    [...laterBody.querySelectorAll(".board-card__timeline .badge")].some((el) =>
      /7 天内截止|已截止/.test(el.textContent),
    ),
    false,
    "far-future deadline shows plain date badge, not warning",
  );

  const none = bodyFrom(boardCard(DETAIL_JOB));
  assert.equal(
    none.querySelector('[title^="截止"]'),
    null,
    "no deadline badge without deadline",
  );
});

test("review route and page are wired (source contract)", () => {
  const nav = read("../index.html");
  assert.match(nav, /data-route="review"/, "rail has review entry");
  const main = read("main.js");
  assert.match(main, /case "review":/, "route dispatch handles review");
  assert.match(main, /renderReviewView/, "review view is imported");
  const view = read("review-view.js");
  assert.match(view, /\/api\/review/, "review view consumes the endpoint");
  assert.match(view, /对齐有效性/, "attribution card exists");
  assert.match(view, /暂不展示比率/, "small-sample guard surfaced in UI");
});

test("quick-eval is wired through command palette (source contract)", () => {
  const palette = read("../index.html");
  assert.match(palette, /data-action="quick-eval"/, "palette has the eval button");
  assert.match(palette, /data-command-preview/, "preview node renders the result");
  const panel = read("command-panel.js");
  assert.match(panel, /\/api\/quick-eval/, "panel calls the eval endpoint");
  assert.match(panel, /state\.quickEval/, "panel stashes eval state for the CTA");
  assert.match(panel, /existing_job_id/, "duplicate JD deep-links instead of duplicating");
  const main = read("main.js");
  assert.match(main, /"quick-eval-adopt"/, "adopt action exists");
  assert.match(main, /runQuickEval/, "action wired to command-panel");
  const events = read("events.js");
  assert.match(events, /quickEval/, "state carries quickEval");
});

test("update-master-resume 原地反哺接线（source contract）", () => {
  const canvas = read("split-canvas.js");
  assert.match(canvas, /data-action="update-master-resume"/, "button wired in canvas");
  assert.match(canvas, /workbench_resume_id/, "guarded by pinned resume id");
  const main = read("main.js");
  assert.match(main, /"confirm-update-master"/, "confirm action exists");
  assert.match(main, /版本时间线/, "rollback affordance surfaced in modal copy");
});
