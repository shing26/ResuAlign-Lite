import test from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";

import {
  dueReminders,
  onboardingSteps,
  renderOnboardingCard,
  renderReminderBanner,
  renderReminderStrip,
} from "../../../src/resualign/static/app/format.js";

/* Parse a rendered HTML string and return its body element, so the DOM
 * structure produced by the pure builders can be asserted exactly like
 * the real page would behave after mountOnboarding / mountReminders. */
function bodyFrom(html) {
  const window = new Window();
  window.document.body.innerHTML = html;
  return window.document.body;
}

const NOW = new Date(2026, 7, 10, 12, 0, 0);

test("onboarding card DOM: one li per step, each with skip button", () => {
  const steps = onboardingSteps({ resumes: [], jobs: [], skipped: [] });
  const body = bodyFrom(renderOnboardingCard(steps));
  const card = body.querySelector("[data-onboarding-card]");
  assert.ok(card, "card is rendered");
  assert.equal(card.querySelectorAll(".onboarding-step").length, 3);
  assert.equal(card.querySelectorAll('[data-action="skip-onboarding-step"]').length, 3);
  const stepsByKey = card.querySelectorAll("li[data-step]");
  assert.deepEqual(
    [...stepsByKey].map((node) => node.dataset.step),
    ["resume", "jd", "align"],
  );
  const resumeLink = card.querySelector('[data-step="resume"] a.btn-primary');
  assert.ok(resumeLink);
  assert.equal(resumeLink.getAttribute("href"), "#/resume");
  const jdButton = card.querySelector('[data-step="jd"] button[data-action="open-command-panel"]');
  assert.ok(jdButton);
  const badge = card.querySelector(".badge.badge-amber.badge-pending");
  assert.equal(badge.textContent, "新手引导");
});

test("onboarding card DOM: partial progress keeps remaining steps numbered", () => {
  const steps = onboardingSteps({ resumes: [{ resume_id: "r1" }], jobs: [], skipped: [] });
  const body = bodyFrom(renderOnboardingCard(steps));
  const indexes = [...body.querySelectorAll(".onboarding-step__index")].map(
    (node) => node.textContent,
  );
  assert.deepEqual(indexes, ["2", "3"]);
});

test("reminder strip DOM: badges link to workspace and carry due labels", () => {
  const reminders = dueReminders(
    [
      {
        job_id: "j1",
        title: "后端开发",
        status: "interview",
        next_step: "2026-08-09 10:00 二面",
      },
      {
        job_id: "j2",
        title: "前端开发",
        status: "interview",
        next_step: "2026-08-11 09:00",
      },
    ],
    NOW,
  );
  const body = bodyFrom(renderReminderStrip(reminders));
  const strip = body.querySelector("[data-reminder-strip]");
  assert.ok(strip);
  assert.equal(strip.getAttribute("role"), "status");
  assert.equal(strip.querySelector(".reminder-strip__label").textContent, "待跟进 2");
  const links = [...strip.querySelectorAll("a.badge")];
  assert.equal(links.length, 2);
  assert.equal(links[0].getAttribute("href"), "#/workspace/j1");
  assert.equal(links[0].textContent, "后端开发 · 8/9 10:00 · 已过期 26h");
  assert.equal(links[0].getAttribute("title"), "2026-08-09 10:00 二面");
  assert.equal(links[1].textContent, "前端开发 · 8/11 09:00 · 21h 内到期");
  const followups = [...strip.querySelectorAll('[data-action="open-job-followup"]')];
  assert.equal(followups.length, 2);
  assert.deepEqual(
    followups.map((node) => node.dataset.id),
    ["j1", "j2"],
  );
});

test("reminder strip DOM: structured fields render stage badge with due time", () => {
  const reminders = dueReminders(
    [
      {
        job_id: "j3",
        title: "数据工程师",
        status: "interview",
        next_step: "等 HR 通知",
        next_step_due_at: "2026-08-10 18:00",
        interview_stage: "二面",
      },
    ],
    NOW,
  );
  assert.equal(reminders.length, 1);
  assert.equal(reminders[0].stage, "二面");
  const body = bodyFrom(renderReminderStrip(reminders));
  const link = body.querySelector("a.badge");
  assert.equal(link.textContent, "数据工程师 · 二面 · 8/10 18:00 · 6h 内到期");
});

test("reminder banner DOM: shows active job follow-up", () => {
  const reminders = dueReminders(
    [
      {
        job_id: "j9",
        title: "算法工程师",
        status: "interview",
        next_step: "2026-08-09 15:00 三面",
      },
    ],
    NOW,
  );
  const body = bodyFrom(renderReminderBanner(reminders[0]));
  const banner = body.querySelector("[data-reminder-banner]");
  assert.ok(banner);
  assert.ok(banner.textContent.includes("算法工程师"));
  assert.ok(banner.textContent.includes("已过期 21h"));
  assert.ok(banner.textContent.includes("8/9 15:00"));
  assert.equal(
    banner.querySelector('[data-action="open-job-followup"]').dataset.id,
    "j9",
  );
});

test("reminder banner DOM: structured stage shows as 阶段 · 到期时间", () => {
  const reminders = dueReminders(
    [
      {
        job_id: "j9",
        title: "算法工程师",
        status: "interview",
        next_step: "准备系统设计",
        next_step_due_at: "2026-08-11 14:00",
        interview_stage: "HR面",
      },
    ],
    NOW,
  );
  const body = bodyFrom(renderReminderBanner(reminders[0]));
  const banner = body.querySelector("[data-reminder-banner]");
  assert.ok(banner.textContent.includes("HR面 · 8/11 14:00"));
});

test("reminder strip DOM: terminal jobs produce no reminders", () => {
  const reminders = dueReminders(
    [
      {
        job_id: "j-offer",
        title: "已拿Offer",
        status: "offer",
        next_step_due_at: "2026-08-09 10:00",
      },
      {
        job_id: "j-withdrawn",
        title: "放弃",
        status: "withdrawn",
        next_step: "2026-08-09 10:00",
      },
    ],
    NOW,
  );
  assert.deepEqual(reminders, []);
  assert.equal(renderReminderStrip(reminders), "");
});
