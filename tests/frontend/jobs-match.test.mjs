import { test } from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";

import {
  boardCard,
  renderBoardCard,
} from "../../src/resualign/static/app/format.js";

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
