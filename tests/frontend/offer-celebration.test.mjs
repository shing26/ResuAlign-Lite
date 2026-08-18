import test from "node:test";
import assert from "node:assert/strict";
import { offerCelebrationHtml } from "../../src/resualign/static/app/format.js";

test("offerCelebrationHtml renders for offer status", () => {
  const html = offerCelebrationHtml({
    title: "后端工程师",
    company: "Acme",
    status: "offer",
  });
  assert.match(html, /data-offer-celebration/);
  assert.match(html, /OFFER/);
  assert.match(html, /后端工程师/);
  assert.match(html, /Acme/);
});

test("offerCelebrationHtml accepts legacy Chinese status", () => {
  const html = offerCelebrationHtml({ status: "已拿Offer" });
  assert.match(html, /data-offer-celebration/);
});

test("offerCelebrationHtml returns empty for non-offer jobs", () => {
  assert.equal(offerCelebrationHtml({ status: "applied" }), "");
  assert.equal(offerCelebrationHtml(null), "");
});

test("offerCelebrationHtml escapes job content", () => {
  const html = offerCelebrationHtml({
    title: "<script>alert(1)</script>",
    status: "offer",
  });
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("&lt;script&gt;"));
});
