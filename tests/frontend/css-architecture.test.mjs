/* B1b architecture guards: fail if the layered stylesheet drifts back into
 * unlayered override waves or reintroduces scattered !important rules. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const CSS = readFileSync(
  join(here, "../../src/resualign/static/styles.css"),
  "utf8",
);

function indexesOf(regex) {
  return [...CSS.matchAll(regex)].map((match) => match.index ?? 0);
}

test("css declares the canonical eight-layer order exactly once", () => {
  const matches = CSS.match(
    /^@layer\s+reset,\s*tokens,\s*base,\s*layout,\s*components,\s*patterns,\s*utilities,\s*overrides;/gm,
  ) || [];
  assert.equal(matches.length, 1);
});

test("css has a single tokens layer host", () => {
  const matches = CSS.match(/^@layer tokens\s*\{/gm) || [];
  assert.equal(matches.length, 1);
});

test("css keeps exactly one !important exceptional rule", () => {
  const important = CSS.match(/!important/g) || [];
  assert.equal(important.length, 1);
  assert.match(
    CSS,
    /(?:^|\n)\[hidden\]\s*\{\s*display:\s*none\s*!important;\s*\}/,
  );
});

test("legacy print and reduced-motion compatibility lives in overrides", () => {
  const overrides = CSS.lastIndexOf("@layer overrides {");
  assert.ok(overrides > 0, "overrides layer must exist");

  const printIndexes = indexesOf(/@media print/g);
  const motionIndexes = indexesOf(/@media \(prefers-reduced-motion: reduce\)/g);

  assert.ok(printIndexes.length > 0);
  assert.ok(printIndexes.every((index) => index > overrides));
  assert.ok(motionIndexes.filter((index) => index > overrides).length >= 5);
});
