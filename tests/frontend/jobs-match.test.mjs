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
