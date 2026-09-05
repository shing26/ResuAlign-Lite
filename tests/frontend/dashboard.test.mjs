import { test } from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";

import {
  dashboardEmptyGuideHtml,
  dashboardKpiHtml,
  jobsEmptyGuideHtml,
  jobSelectOptionsHtml,
  matchJobSuggestions,
  parseHashValue,
  quickContinueHtml,
  renderJobSuggestionsHtml,
  skillGapHtml,
} from "../../src/resualign/static/app/format.js";

/* Parse a rendered HTML string and return its body element, so the DOM
 * structure produced by the pure builders can be asserted like the real
 * page after main.js injects them into #app. */
function bodyFrom(html) {
  const window = new Window();
  window.document.body.innerHTML = html;
  return window.document.body;
}

/* ------------------------------------------------------------------ */
/* parseHashValue: dashboard route                                     */
/* ------------------------------------------------------------------ */

test("parseHashValue resolves the dashboard route", () => {
  assert.equal(parseHashValue("#/dashboard").name, "dashboard");
  assert.equal(parseHashValue("#/dashboard").jobId, null);
});

test("parseHashValue tolerates a skill deep-link query on workspace", () => {
  const route = parseHashValue("#/workspace/j1?skill=K8s");
  assert.equal(route.name, "workspace");
  assert.equal(route.jobId, "j1");
  assert.equal(route.resumeId, null);
});

/* ------------------------------------------------------------------ */
/* dashboardKpiHtml (4 KPI cards)                                      */
/* ------------------------------------------------------------------ */

const kpi = {
  resumes: 3,
  jobs: 8,
  applied: 4,
  interview: 2,
  offer: 1,
  declined: 2,
};

test("dashboardKpiHtml renders three KPI cards with values", () => {
  const body = bodyFrom(dashboardKpiHtml(kpi));
  const grid = body.querySelector("[data-dashboard-kpis]");
  assert.ok(grid, "kpi grid is rendered");
  const cards = [...grid.querySelectorAll(".dashboard-kpi")];
  assert.equal(cards.length, 3);
  assert.equal(cards[0].querySelector(".dashboard-kpi__value").textContent, "3");
  assert.equal(cards[1].querySelector(".dashboard-kpi__value").textContent, "8");
  assert.equal(cards[2].querySelector(".dashboard-kpi__value").textContent, "4");
  assert.match(cards[0].querySelector(".dashboard-kpi__label").textContent, /主简历/);
  assert.match(cards[2].querySelector(".dashboard-kpi__label").textContent, /已投递/);
});

test("dashboardKpiHtml shows an applied conversion hint", () => {
  const body = bodyFrom(dashboardKpiHtml({ ...kpi, applied: 2, jobs: 8 }));
  const appliedCard = body.querySelector('[data-kpi="applied"]');
  assert.match(appliedCard.querySelector(".dashboard-kpi__hint").textContent, /25%/);
});

test("dashboardKpiHtml handles missing kpi gracefully", () => {
  const body = bodyFrom(dashboardKpiHtml(null));
  const cards = [...body.querySelectorAll(".dashboard-kpi")];
  assert.equal(cards.length, 3);
  assert.equal(cards[0].querySelector(".dashboard-kpi__value").textContent, "0");
});

test("dashboardKpiHtml coerces non-numeric values and never injects HTML", () => {
  const body = bodyFrom(
    dashboardKpiHtml({ resumes: "<script>alert(1)</script>" }),
  );
  const card = body.querySelector('[data-kpi="resumes"]');
  assert.equal(card.querySelector("script"), null);
  // 数值被 Number() 强制转换：非数字字符串 → 0，天然避免注入
  assert.equal(card.querySelector(".dashboard-kpi__value").textContent, "0");
});

test("dashboardEmptyGuideHtml renders only for a truly empty workspace", () => {
  const empty = bodyFrom(dashboardEmptyGuideHtml());
  assert.ok(empty.querySelector("[data-dashboard-empty]"));
  assert.equal(empty.querySelectorAll("a.btn").length, 2);
  assert.equal(empty.querySelector("a[href='#/resume']").textContent, "上传简历");
  assert.equal(empty.querySelector("a[href='#/jobs']").textContent, "导入 JD");
  assert.equal(
    bodyFrom(dashboardEmptyGuideHtml({ hasJobs: true })).querySelector("[data-dashboard-empty]"),
    null,
  );
  assert.equal(
    bodyFrom(dashboardEmptyGuideHtml({ hasResume: true })).querySelector("[data-dashboard-empty]"),
    null,
  );
});

test("jobsEmptyGuideHtml renders an actionable empty state", () => {
  const body = bodyFrom(jobsEmptyGuideHtml());
  const guide = body.querySelector("[data-jobs-empty]");
  assert.ok(guide);
  assert.match(guide.textContent, /还没有岗位/);
  assert.equal(guide.querySelector('[data-action="show-add-job"]').textContent, "粘贴 JD");
});

/* ------------------------------------------------------------------ */
/* skillGapHtml (horizontal heat bars)                                 */
/* ------------------------------------------------------------------ */

const gaps = [
  { skill: "K8s", count: 5 },
  { skill: "高并发", count: 3 },
  { skill: "Docker", count: 1 },
];

test("skillGapHtml renders a row per gap with proportional widths", () => {
  const body = bodyFrom(skillGapHtml(gaps));
  const rows = [...body.querySelectorAll("[data-skill-gaps] .skill-gap-row")];
  assert.equal(rows.length, 3);
  // widths relative to max=5: K8s 100%, 高并发 60%, Docker 20%
  assert.equal(rows[0].querySelector(".skill-gap-row__fill").style.width, "100%");
  assert.equal(rows[1].querySelector(".skill-gap-row__fill").style.width, "60%");
  assert.equal(rows[2].querySelector(".skill-gap-row__fill").style.width, "20%");
  assert.match(rows[2].querySelector(".skill-gap-row__count").textContent, /1 个岗位/);
});

test("skillGapHtml rows are clickable via goto-skill", () => {
  const body = bodyFrom(skillGapHtml(gaps));
  const first = body.querySelector(".skill-gap-row");
  assert.equal(first.getAttribute("data-action"), "goto-skill");
  assert.equal(first.getAttribute("data-skill"), "K8s");
});

test("skillGapHtml uses onSkillGapUrl for fallback deep links", () => {
  const body = bodyFrom(
    skillGapHtml(gaps, (skill) => `#/workspace?skill=${encodeURIComponent(skill)}`),
  );
  const first = body.querySelector(".skill-gap-row");
  assert.match(first.getAttribute("data-skill-url"), /#\/workspace\?skill=/);
  assert.equal(first.getAttribute("data-skill-url"), "#/workspace?skill=K8s");
});

test("skillGapHtml buckets heat tones by relative count", () => {
  const body = bodyFrom(
    skillGapHtml([
      { skill: "a", count: 5 },
      { skill: "b", count: 2 },
      { skill: "c", count: 0 },
    ]),
  );
  const fills = [...body.querySelectorAll(".skill-gap-row__fill")];
  assert.match(fills[0].className, /--hot/);
  assert.match(fills[1].className, /--warm/);
  assert.match(fills[2].className, /--cool/);
});

test("skillGapHtml renders an empty state for no gaps", () => {
  const body = bodyFrom(skillGapHtml([]));
  assert.match(body.querySelector("[data-skill-gaps]").textContent, /暂无技能缺口数据/);
});

test("skillGapHtml escapes skill names", () => {
  const body = bodyFrom(skillGapHtml([{ skill: "<img src=x onerror=1>", count: 2 }]));
  assert.equal(body.querySelector("img"), null);
  assert.match(body.querySelector(".skill-gap-row__name").innerHTML, /&lt;img/);
});

/* ------------------------------------------------------------------ */
/* quickContinueHtml (quick continue card)                             */
/* ------------------------------------------------------------------ */

const qc = {
  job_id: "j9",
  title: "后端工程师",
  company: "Acme",
  alignment_status: "succeeded",
  updated_at: 1780000000,
};

test("quickContinueHtml renders title, company, status and continue link", () => {
  const body = bodyFrom(quickContinueHtml(qc));
  const card = body.querySelector("[data-quick-continue]");
  assert.ok(card, "quick continue card is rendered");
  assert.match(card.textContent, /Acme/);
  assert.match(card.textContent, /已对齐/);
  assert.equal(card.querySelector(".quick-continue__title").textContent, "后端工程师");
  const link = card.querySelector("a");
  assert.equal(link.getAttribute("href"), "#/workspace/j9");
  assert.equal(link.textContent, "查看");
});

/* P1-3: failed/canceled/expired 卡带红警示 + 「上次失败 · 重新运行」+ 危险主按钮 */
test("quickContinueHtml marks failed/canceled/expired as retryable failure", () => {
  for (const status of ["failed", "canceled", "expired"]) {
    const body = bodyFrom(quickContinueHtml({ ...qc, alignment_status: status }));
    const card = body.querySelector("[data-quick-continue]");
    assert.match(card.className, /quick-continue--failed/, `${status} card is failed-styled`);
    assert.match(card.textContent, /上次失败 · 重新运行/);
    const link = card.querySelector("a");
    assert.match(link.className, /btn-danger-solid/);
    assert.match(link.textContent, /重新运行/);
    assert.equal(link.getAttribute("href"), `#/workspace/j9`);
  }
});

/* P1-3: running/queued 为「分析中」禁用加载态，不产生导航链接 */
test("quickContinueHtml renders running/queued as busy, disabled", () => {
  for (const status of ["running", "queued"]) {
    const body = bodyFrom(quickContinueHtml({ ...qc, alignment_status: status }));
    const card = body.querySelector("[data-quick-continue]");
    assert.match(card.textContent, /分析中/);
    const link = card.querySelector("a");
    assert.equal(link.getAttribute("href"), null, `${status} link must not navigate`);
    assert.equal(link.getAttribute("aria-disabled"), "true");
    assert.match(link.className, /is-loading/);
  }
});

/* P1-3: idle/pending 维持中性「待分析」+ 「继续」 */
test("quickContinueHtml keeps idle/pending neutral", () => {
  for (const status of ["idle", "pending", null]) {
    const body = bodyFrom(quickContinueHtml({ ...qc, alignment_status: status }));
    const card = body.querySelector("[data-quick-continue]");
    assert.match(card.textContent, /待分析/);
    const link = card.querySelector("a");
    assert.match(link.textContent, /继续/);
  }
});

test("quickContinueHtml returns empty for null or job-less payloads", () => {
  assert.equal(quickContinueHtml(null), "");
  assert.equal(quickContinueHtml({}), "");
  assert.equal(quickContinueHtml({ job_id: "" }), "");
});

test("quickContinueHtml passes unknown alignment status through", () => {
  const body = bodyFrom(quickContinueHtml({ ...qc, alignment_status: "weird" }));
  assert.match(body.querySelector("[data-quick-continue]").textContent, /weird/);
  const link = body.querySelector("a");
  assert.match(link.textContent, /继续/);
});

test("quickContinueHtml escapes user content", () => {
  const body = bodyFrom(
    quickContinueHtml({ ...qc, title: "<b>x</b>", company: '"><script>alert(1)</script>' }),
  );
  assert.equal(body.querySelector("script"), null);
  assert.match(body.querySelector(".quick-continue__title").innerHTML, /&lt;b&gt;/);
});

/* ------------------------------------------------------------------ */
/* matchJobSuggestions (⌘K 搜岗位匹配)                                  */
/* ------------------------------------------------------------------ */

const sampleJobs = [
  { job_id: "j1", title: "后端工程师", company: "Acme" },
  { job_id: "j2", title: "前端工程师", company: "Beta" },
  { job_id: "j3", title: "数据分析师", company: "Acme" },
];

test("matchJobSuggestions matches title and company case-insensitively", () => {
  const byCompany = matchJobSuggestions(sampleJobs, "ACME");
  assert.deepEqual(byCompany.map((job) => job.job_id), ["j1", "j3"]);
  const byTitle = matchJobSuggestions(sampleJobs, "前端");
  assert.deepEqual(byTitle.map((job) => job.job_id), ["j2"]);
});

test("matchJobSuggestions limits results and handles empty queries", () => {
  const many = Array.from({ length: 10 }, (_, i) => ({
    job_id: `j${i}`,
    title: `工程师 ${i}`,
  }));
  assert.equal(matchJobSuggestions(many, "工程师").length, 6);
  assert.deepEqual(matchJobSuggestions(sampleJobs, "   "), []);
  assert.deepEqual(matchJobSuggestions(sampleJobs, ""), []);
  assert.deepEqual(matchJobSuggestions(null, "x"), []);
});

/* ------------------------------------------------------------------ */
/* renderJobSuggestionsHtml (⌘K 建议下拉按钮)                           */
/* ------------------------------------------------------------------ */

test("renderJobSuggestionsHtml emits clickable suggestion buttons", () => {
  const body = bodyFrom(renderJobSuggestionsHtml(sampleJobs, "后端"));
  const buttons = [...body.querySelectorAll("[data-command-suggestion]")];
  assert.equal(buttons.length, 1);
  assert.equal(buttons[0].getAttribute("data-job-id"), "j1");
  assert.match(buttons[0].querySelector(".command-suggestion__title").textContent, /后端工程师/);
  assert.match(buttons[0].querySelector(".command-suggestion__meta").textContent, /Acme/);
});

test("renderJobSuggestionsHtml returns empty when nothing matches", () => {
  assert.equal(renderJobSuggestionsHtml(sampleJobs, "zzz"), "");
});

/* ------------------------------------------------------------------ */
/* jobSelectOptionsHtml (Header 岗位快速选择器)                         */
/* ------------------------------------------------------------------ */

test("jobSelectOptionsHtml builds options with placeholder and company suffix", () => {
  const html = jobSelectOptionsHtml(sampleJobs, "j2");
  const body = bodyFrom(`<select>${html}</select>`);
  const options = [...body.querySelectorAll("option")];
  assert.equal(options.length, 4);
  assert.equal(options[0].value, "");
  assert.equal(options[0].textContent, "选择岗位...");
  assert.equal(options[1].textContent, "后端工程师 · Acme");
  assert.ok(options[2].hasAttribute("selected"), "selectedId marks its option");
  assert.equal(options[2].value, "j2");
  assert.equal(options[3].value, "j3");
  assert.equal(options[3].hasAttribute("selected"), false);
});

test("jobSelectOptionsHtml escapes job fields and handles empty lists", () => {
  const body = bodyFrom(
    `<select>${jobSelectOptionsHtml([{ job_id: '"><img src=x>', title: "<b>x</b>", company: "A" }])}</select>`,
  );
  assert.equal(body.querySelector("img"), null);
  assert.equal(body.querySelectorAll("option").length, 2);
  assert.match(jobSelectOptionsHtml([]), /选择岗位\.\.\./);
});

test("parseHashValue resolves the review route (PM 反馈串台回归)", () => {
  assert.equal(parseHashValue("#/review").name, "review");
});
