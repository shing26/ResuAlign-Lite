import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ONBOARDING_STEPS,
  dueReminders,
  onboardingSteps,
  parseNextStepDate,
  reminderDueLabel,
  reminderWhen,
  renderOnboardingCard,
  renderReminderBanner,
  renderReminderStrip,
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
/* dueReminders                                                       */
/* ------------------------------------------------------------------ */

const NOW = new Date(2026, 7, 10, 12, 0, 0); /* 2026-08-10 12:00 local */

function job(id, nextStep) {
  return {
    job_id: id,
    title: `岗位 ${id}`,
    next_step: nextStep,
    status: "interview",
  };
}

test("dueReminders flags overdue and within-48h next steps", () => {
  const reminders = dueReminders(
    [
      job("a", "2026-08-09 10:00"), /* overdue ~26h */
      job("b", "2026-08-11 09:00"), /* in ~21h */
      job("c", "2026-08-12 11:59"), /* just under 48h */
      job("d", "2026-08-12 12:01"), /* just over 48h -> excluded */
      job("e", "2026-08-20 09:00"), /* far future -> excluded */
    ],
    NOW,
  );
  assert.deepEqual(
    reminders.map((r) => r.job.job_id),
    ["a", "b", "c"],
  );
  const [a, b, c] = reminders;
  assert.equal(a.overdue, true);
  assert.equal(a.hoursUntil, -26);
  assert.equal(b.overdue, false);
  assert.equal(b.hoursUntil, 21);
  assert.equal(c.overdue, false);
});

test("dueReminders skips jobs without next_step or without a date", () => {
  const reminders = dueReminders(
    [
      job("no-text", null),
      job("empty", ""),
      job("plain-text", "等 HR 通知"),
      job("due", "2026-08-10 18:00"),
    ],
    NOW,
  );
  assert.deepEqual(
    reminders.map((r) => r.job.job_id),
    ["due"],
  );
});

test("dueReminders sorts most urgent (earliest due) first", () => {
  const reminders = dueReminders(
    [
      job("later", "2026-08-11 10:00"),
      job("earlier", "2026-08-10 09:00"),
      job("middle", "2026-08-10 20:00"),
    ],
    NOW,
  );
  assert.deepEqual(
    reminders.map((r) => r.job.job_id),
    ["earlier", "middle", "later"],
  );
});

test("dueReminders tolerates null/undefined/non-array input", () => {
  assert.deepEqual(dueReminders(null, NOW), []);
  assert.deepEqual(dueReminders(undefined, NOW), []);
  assert.deepEqual(dueReminders("nope", NOW), []);
  assert.deepEqual(dueReminders([null, 42], NOW), []);
});

test("dueReminders accepts a timestamp string as now", () => {
  const reminders = dueReminders(
    [job("a", "2026-08-10 13:00")],
    NOW.toISOString(),
  );
  assert.equal(reminders.length, 1);
});

test("dueReminders ignores terminal and draft jobs even with next_step", () => {
  const reminders = dueReminders(
    [
      { job_id: "offer", title: "offer", status: "offer", next_step: "2026-08-09 10:00" },
      { job_id: "withdrawn", title: "withdrawn", status: "withdrawn", next_step_due_at: "2026-08-09 10:00" },
      { job_id: "draft", title: "draft", status: "draft", next_step_due_at: "2026-08-09 10:00" },
      { job_id: "active", title: "active", status: "interview", next_step_due_at: "2026-08-09 10:00" },
    ],
    NOW,
  );
  assert.deepEqual(reminders.map((r) => r.job.job_id), ["active"]);
});

/* F6: 结构化 next_step_due_at 优先于 next_step 自由文本正则 */
test("dueReminders prefers structured next_step_due_at over free text", () => {
  /* 自由文本无日期、结构化字段有日期 → 提醒来自结构化字段 */
  const fromStructured = dueReminders(
    [
      {
        job_id: "a",
        title: "岗位 a",
        status: "interview",
        next_step: "等 HR 通知",
        next_step_due_at: "2026-08-11 09:00",
      },
    ],
    NOW,
  );
  assert.equal(fromStructured.length, 1);
  assert.equal(fromStructured[0].dueAt.getHours(), 9);

  /* 两者都有日期但冲突 → 以结构化字段为准（不回退到自由文本） */
  const conflict = dueReminders(
    [
      {
        job_id: "b",
        title: "岗位 b",
        status: "interview",
        next_step: "2026-08-09 10:00", /* 已过期，会被旧逻辑命中 */
        next_step_due_at: "2026-08-20 10:00", /* 48h 外 → 不应提醒 */
      },
    ],
    NOW,
  );
  assert.deepEqual(conflict, []);

  /* 结构化字段为空 → 回退自由文本正则（保留旧行为） */
  const fallback = dueReminders(
    [
      {
        job_id: "c",
        title: "岗位 c",
        status: "interview",
        next_step: "面试 2026-08-10 18:00",
        next_step_due_at: "",
      },
    ],
    NOW,
  );
  assert.equal(fallback.length, 1);
  assert.equal(fallback[0].dueAt.getDate(), 10);
});

test("dueReminders carries the interview stage on reminders", () => {
  const reminders = dueReminders(
    [
      {
        job_id: "a",
        title: "岗位 a",
        status: "interview",
        next_step: "二面",
        next_step_due_at: "2026-08-11 09:00",
        interview_stage: "二面",
      },
      {
        job_id: "b",
        title: "岗位 b",
        status: "interview",
        next_step: "2026-08-11 10:00",
        next_step_due_at: "2026-08-11 10:00",
        interview_stage: null,
      },
    ],
    NOW,
  );
  assert.equal(reminders[0].stage, "二面");
  assert.equal(reminders[1].stage, null);
});

test("reminderWhen formats stage + local due time, or time only", () => {
  const withStage = dueReminders(
    [
      {
        job_id: "a",
        title: "岗位 a",
        status: "applied",
        next_step_due_at: "2026-08-10 15:00",
        interview_stage: "二面",
      },
    ],
    NOW,
  );
  assert.equal(reminderWhen(withStage[0]), "二面 · 8/10 15:00");

  const timeOnly = dueReminders(
    [
      {
        job_id: "b",
        title: "岗位 b",
        status: "interview",
        next_step: "2026-08-09 15:00",
      },
    ],
    NOW,
  );
  assert.equal(reminderWhen(timeOnly[0]), "8/9 15:00");

  assert.equal(reminderWhen(null), "");
  assert.equal(reminderWhen({}), "");
});

/* ------------------------------------------------------------------ */
/* reminderDueLabel                                                   */
/* ------------------------------------------------------------------ */

test("reminderDueLabel renders overdue and upcoming labels", () => {
  assert.equal(
    reminderDueLabel({ overdue: true, hoursUntil: -5 }),
    "已过期 5h",
  );
  assert.equal(
    reminderDueLabel({ overdue: true, hoursUntil: -26 }),
    "已过期 26h",
  );
  assert.equal(reminderDueLabel({ overdue: false, hoursUntil: 1 }), "1h 内到期");
  assert.equal(reminderDueLabel({ overdue: false, hoursUntil: 21 }), "21h 内到期");
  assert.equal(reminderDueLabel(null), "");
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

/* ------------------------------------------------------------------ */
/* renderReminderStrip / renderReminderBanner                          */
/* ------------------------------------------------------------------ */

test("renderReminderStrip returns empty string without reminders", () => {
  assert.equal(renderReminderStrip([]), "");
  assert.equal(renderReminderStrip(null), "");
});

test("renderReminderStrip renders amber badges linking to the workspace", () => {
  const reminders = dueReminders(
    [
      job("j1", "2026-08-09 10:00"),
      job("j2", "2026-08-11 09:00"),
    ],
    NOW,
  );
  const html = renderReminderStrip(reminders);
  assert.match(html, /data-reminder-strip/);
  assert.match(html, /待跟进 2/);
  assert.match(html, /class="badge badge-amber"/);
  assert.match(html, /href="#\/workspace\/j1"/);
  assert.match(html, /href="#\/workspace\/j2"/);
  assert.match(html, /data-action="open-job-followup" data-id="j1"/);
  assert.match(html, /data-action="open-job-followup" data-id="j2"/);
  assert.match(html, /岗位 j1 · 8\/9 10:00 · 已过期 26h/);
  assert.match(html, /岗位 j2 · 8\/11 09:00 · 21h 内到期/);
  assert.match(html, /title="2026-08-09 10:00"/); /* raw next_step as tooltip */
});

test("renderReminderStrip escapes titles and encodes job ids", () => {
  const reminders = dueReminders(
    [
      {
        job_id: "a b",
        title: "<A&B>",
        status: "interview",
        next_step: "2026-08-10 13:00",
      },
    ],
    NOW,
  );
  const html = renderReminderStrip(reminders);
  assert.ok(!html.includes("<A&B>"));
  assert.ok(html.includes("&lt;A&amp;B&gt;"));
  assert.ok(html.includes("#/workspace/a%20b"));
});

test("renderReminderBanner returns empty string without a reminder", () => {
  assert.equal(renderReminderBanner(null), "");
  assert.equal(renderReminderBanner(undefined), "");
});

test("renderReminderBanner renders the active job follow-up line", () => {
  const reminders = dueReminders([job("j9", "2026-08-09 15:00 二面")], NOW);
  const html = renderReminderBanner(reminders[0]);
  assert.match(html, /data-reminder-banner/);
  assert.match(html, /面试跟进/);
  assert.match(html, /「岗位 j9」已过期 21h：8\/9 15:00/);
  assert.match(html, /data-action="open-job-followup" data-id="j9"/);
});

test("renderReminderBanner shows structured stage + due time", () => {
  const reminders = dueReminders(
    [
      {
        job_id: "j9",
        title: "岗位 j9",
        status: "interview",
        next_step: "等 HR 通知",
        next_step_due_at: "2026-08-10 18:00",
        interview_stage: "二面",
      },
    ],
    NOW,
  );
  const html = renderReminderBanner(reminders[0]);
  assert.match(html, /「岗位 j9」6h 内到期：二面 · 8\/10 18:00/);
});
