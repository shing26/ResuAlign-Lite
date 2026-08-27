import test from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";

import {
  onboardingSteps,
  renderOnboardingCard,
} from "../../../src/resualign/static/app/format.js";

/* Parse a rendered HTML string and return its body element, so the DOM
 * structure produced by the pure builders can be asserted exactly like
 * the real page would behave after mountOnboarding. */
function bodyFrom(html) {
  const window = new Window();
  window.document.body.innerHTML = html;
  return window.document.body;
}

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