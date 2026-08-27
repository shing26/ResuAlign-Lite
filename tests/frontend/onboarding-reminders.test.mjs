import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ONBOARDING_STEPS,
  onboardingSteps,
  parseNextStepDate,
  renderOnboardingCard,
} from "../../src/resualign/static/app/format.js";

/* ------------------------------------------------------------------ */
/* parseNextStepDate                                                  */
/* ------------------------------------------------------------------ */

test("parseNextStepDate parses ISO/space datetime as local time", () => {
  const iso = parseNextStepDate("2026-08-10T14:30");
  assert.ok(iso instanceof Date);
  assert.equal(iso.getFullYear(), 2026);
  assert.equal(iso.getMonth(), 7); /* 0-based August */
  assert.equal(iso.getDate(), 10);
  assert.equal(iso.getHours(), 14);
  assert.equal(iso.getMinutes(), 30);

  const spaced = parseNextStepDate("2026-08-10 14:30 二面");
  assert.equal(spaced.getFullYear(), 2026);
  assert.equal(spaced.getHours(), 14);

  const withSeconds = parseNextStepDate("2026-8-5T09:05:00 电话面试");
  assert.equal(withSeconds.getMonth(), 7);
  assert.equal(withSeconds.getDate(), 5);
  assert.equal(withSeconds.getSeconds(), 0);
});

test("parseNextStepDate treats date-only as local midnight (no UTC drift)", () => {
  const dateOnly = parseNextStepDate("2026-08-10");
  assert.equal(dateOnly.getHours(), 0);
  assert.equal(dateOnly.getDate(), 10);
  /* Regression guard: new Date("2026-08-10") would be UTC midnight and
     shift the day in negative-offset timezones. */
  assert.equal(
    new Date(2026, 7, 10).getTime(),
    dateOnly.getTime(),
  );
});

test("parseNextStepDate supports slash separators and leading text", () => {
  const slash = parseNextStepDate("面试 2026/08/12");
  assert.equal(slash.getDate(), 12);
});

test("parseNextStepDate rejects non-date and impossible dates", () => {
  assert.equal(parseNextStepDate(""), null);
  assert.equal(parseNextStepDate("   "), null);
  assert.equal(parseNextStepDate(null), null);
  assert.equal(parseNextStepDate(undefined), null);
  assert.equal(parseNextStepDate("等 HR 通知"), null);
  assert.equal(parseNextStepDate("尽快联系"), null);
  assert.equal(parseNextStepDate("2026-02-31"), null); /* rolls over */
  assert.equal(parseNextStepDate("2026-13-01"), null); /* month 13 rolls over */
  assert.equal(parseNextStepDate("20-08-10"), null); /* short year rejected */
});

/* ------------------------------------------------------------------ */
/* onboardingSteps                                                    */
/* ------------------------------------------------------------------ */

test("onboardingSteps returns all three steps for a brand-new user", () => {
  const steps = onboardingSteps({ resumes: [], jobs: [], skipped: [] });
  assert.deepEqual(
    steps.map((s) => s.key),
    ["resume", "jd", "align"],
  );
  assert.deepEqual(
    steps.map((s) => s.order),
    [1, 2, 3],
  );
});

test("onboardingSteps marks resume done when a master resume exists", () => {
  const steps = onboardingSteps({
    resumes: [{ resume_id: "r1" }],
    jobs: [],
    skipped: [],
  });
  assert.deepEqual(
    steps.map((s) => s.key),
    ["jd", "align"],
  );
});

test("onboardingSteps marks jd done when jobs exist", () => {
  const steps = onboardingSteps({
    resumes: [],
    jobs: [{ job_id: "j1" }],
    skipped: [],
  });
  assert.deepEqual(
    steps.map((s) => s.key),
    ["resume", "align"],
  );
});

test("onboardingSteps marks align done on succeeded alignment or final draft", () => {
  const byStatus = onboardingSteps({
    resumes: [],
    jobs: [{ job_id: "j1", alignment_status: "succeeded" }],
  });
  assert.ok(!byStatus.some((s) => s.key === "align"));

  const byDraft = onboardingSteps({
    resumes: [],
    jobs: [{ job_id: "j1", final_draft_version: 2 }],
  });
  assert.ok(!byDraft.some((s) => s.key === "align"));

  const notYet = onboardingSteps({
    resumes: [],
    jobs: [{ job_id: "j1", alignment_status: "queued" }],
  });
  assert.ok(notYet.some((s) => s.key === "align"));
});

test("onboardingSteps hides skipped steps and returns [] when all done", () => {
  const steps = onboardingSteps({
    resumes: [{ resume_id: "r1" }],
    jobs: [{ job_id: "j1" }],
    skipped: ["align"],
  });
  assert.deepEqual(steps, []);

  const skippedJd = onboardingSteps({
    resumes: [],
    jobs: [],
    skipped: ["resume", "jd"],
  });
  assert.deepEqual(
    skippedJd.map((s) => s.key),
    ["align"],
  );
});

test("onboardingSteps tolerates malformed input", () => {
  assert.equal(onboardingSteps(null).length, 3);
  assert.equal(onboardingSteps({}).length, 3);
  assert.equal(onboardingSteps({ resumes: "x", jobs: 42, skipped: "x" }).length, 3);
  /* resumes=[{}] + jobs=[{}] -> first two steps done, align still pending */
  assert.equal(onboardingSteps({ resumes: [{}], jobs: [{}], skipped: ["nope"] }).length, 1);
});

test("ONBOARDING_STEPS definition is complete and ordered", () => {
  assert.deepEqual(
    ONBOARDING_STEPS.map((s) => s.key),
    ["resume", "jd", "align"],
  );
  for (const step of ONBOARDING_STEPS) {
    assert.ok(step.title);
    assert.ok(step.body);
    assert.ok(step.actionLabel);
    assert.equal(typeof step.isDone, "function");
    assert.ok(step.href || step.action);
  }
});

/* ------------------------------------------------------------------ */
/* renderOnboardingCard                                               */
/* ------------------------------------------------------------------ */

test("renderOnboardingCard returns empty string when no steps remain", () => {
  assert.equal(renderOnboardingCard([]), "");
  assert.equal(renderOnboardingCard(null), "");
  assert.equal(renderOnboardingCard(undefined), "");
});

test("renderOnboardingCard renders steps with actions and skip buttons", () => {
  const steps = onboardingSteps({ resumes: [], jobs: [], skipped: [] });
  const html = renderOnboardingCard(steps);
  assert.match(html, /data-onboarding-card/);
  assert.match(html, /三步上手 ResuAlign/);
  assert.match(html, /badge-amber badge-pending/);
  for (const step of steps) {
    assert.match(html, new RegExp(`data-step="${step.key}"`));
    assert.match(html, new RegExp(`>${step.order}<`)); /* step index badge */
    assert.match(html, new RegExp(`data-action="skip-onboarding-step" data-step="${step.key}"`));
  }
  /* step 1 navigates to resume route, step 2 opens the command panel */
  assert.match(html, /href="#\/resume"/);
  assert.match(html, /data-action="open-command-panel"/);
  assert.match(html, /href="#\/workspace"/);
});

test("renderOnboardingCard escapes user-provided titles", () => {
  const steps = [{ key: "resume", order: 1, title: "<b>恶意</b>", body: "x", actionLabel: "去", href: "#/resume", action: "" }];
  const html = renderOnboardingCard(steps);
  assert.ok(!html.includes("<b>恶意</b>"));
  assert.ok(html.includes("&lt;b&gt;恶意&lt;/b&gt;"));
});
