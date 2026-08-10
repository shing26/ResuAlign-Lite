import { test } from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";

import {
  formatDate,
  versionChangeSummary,
  versionTimelineHtml,
} from "../../../src/resualign/static/app/format.js";

function docFromHtml(html) {
  const window = new Window();
  window.document.body.innerHTML = html;
  return window.document;
}

/* ------------------------------------------------------------------ */
/* versionTimelineHtml (resume center version timeline)               */
/* ------------------------------------------------------------------ */

const ts1 = 1700000000;
const ts2 = 1700086400;
const versions = [
  { version: 1, content: "# Python Developer", created_at: ts1 },
  { version: 2, content: "# Python Developer\n\nFastAPI.", created_at: ts2 },
];

test("versionTimelineHtml renders one timeline item per version", () => {
  const doc = docFromHtml(versionTimelineHtml(versions, 2, "r1"));
  const timeline = doc.querySelector("[data-version-timeline]");
  assert.ok(timeline);
  const items = doc.querySelectorAll("[data-version-item]");
  assert.equal(items.length, 2);
  assert.equal(items[0].getAttribute("data-version"), "1");
  assert.equal(items[1].getAttribute("data-version"), "2");
  assert.match(items[0].textContent, /v1/);
  assert.match(items[1].textContent, /v2/);
  assert.match(items[0].textContent, new RegExp(formatDate(ts1)));
  assert.match(items[1].textContent, new RegExp(formatDate(ts2)));
});

test("versionTimelineHtml marks the current version and hides its actions", () => {
  const doc = docFromHtml(versionTimelineHtml(versions, 2, "r1"));
  const items = doc.querySelectorAll("[data-version-item]");
  assert.equal(items[1].classList.contains("is-current"), true);
  assert.equal(items[0].classList.contains("is-current"), false);
  assert.ok(items[1].querySelector("[data-version-current]"));
  assert.equal(items[0].querySelector("[data-version-current]"), null);
  // Current version has no preview/rollback actions.
  assert.equal(items[1].querySelector('[data-action="preview-version"]'), null);
  assert.equal(items[1].querySelector('[data-action="rollback-resume"]'), null);
});

test("versionTimelineHtml gives non-current versions preview and rollback actions", () => {
  const doc = docFromHtml(versionTimelineHtml(versions, 2, "r1"));
  const nonCurrent = doc.querySelector('[data-version-item][data-version="1"]');
  const preview = nonCurrent.querySelector('[data-action="preview-version"]');
  const rollback = nonCurrent.querySelector('[data-action="rollback-resume"]');
  assert.ok(preview);
  assert.equal(preview.getAttribute("data-version"), "1");
  assert.ok(rollback);
  assert.equal(rollback.getAttribute("data-version"), "1");
  assert.equal(rollback.getAttribute("data-id"), "r1");
});

test("versionTimelineHtml renders the empty placeholder when no versions exist", () => {
  const doc = docFromHtml(versionTimelineHtml([], 1));
  assert.match(doc.querySelector("[data-version-timeline]").textContent, /暂无版本/);
  assert.equal(doc.querySelectorAll("[data-version-item]").length, 0);
});

/* ------------------------------------------------------------------ */
/* versionChangeSummary (adjacent version diff digest)                */
/* ------------------------------------------------------------------ */

test("versionChangeSummary labels the first version as initial", () => {
  // Contract: the placeholder row is emitted as an add row, so the digest
  // carries the same "+ " prefix as every other added line.
  assert.equal(versionChangeSummary(null, versions[0]), "+ 初始版本");
  assert.equal(versionChangeSummary(undefined, versions[0]), "+ 初始版本");
});

test("versionChangeSummary shows plus/minus lines from the adjacent diff", () => {
  const summary = versionChangeSummary(versions[0], versions[1]);
  assert.match(summary, /\+ FastAPI\./);
  const removed = versionChangeSummary(
    { content: "# Python Developer\n\nOld line." },
    { content: "# Python Developer\n\nNew line." },
  );
  assert.match(removed, /- Old line\./);
  assert.match(removed, /\+ New line\./);
});

test("versionChangeSummary falls back to generic text when content is unchanged", () => {
  assert.equal(
    versionChangeSummary({ content: "same" }, { content: "same" }),
    "内容更新",
  );
});

test("versionChangeSummary truncates long summaries at 60 characters", () => {
  const long = "x".repeat(100);
  const summary = versionChangeSummary(
    { content: "old" },
    { content: long },
  );
  assert.ok(summary.endsWith("…"));
  assert.ok(summary.length <= 61);
});

test("versionChangeSummary returns a raw text digest (escaping happens at render)", () => {
  const summary = versionChangeSummary(
    { content: "old" },
    { content: "<script>alert(1)</script>" },
  );
  assert.match(summary, /<script>alert\(1\)<\/script>/);
});

test("versionTimelineHtml escapes the summary inside the timeline", () => {
  const hostile = [
    { version: 1, content: "old", created_at: ts1 },
    { version: 2, content: "<script>alert(1)</script>", created_at: ts2 },
  ];
  const doc = docFromHtml(versionTimelineHtml(hostile, 2, "r1"));
  // The second timeline item carries the hostile diff summary.
  const summary = doc.querySelectorAll("[data-version-summary]")[1];
  assert.equal(summary.querySelector("script"), null);
  assert.match(summary.innerHTML, /&lt;script&gt;/);
});
