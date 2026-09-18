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

function extractLayerText(css, layerName) {
  const marker = new RegExp(`@layer\\s+${layerName}\\s*\\{`, "g");
  const bodies = [];
  let match;
  while ((match = marker.exec(css))) {
    const start = match.index + match[0].length - 1;
    let depth = 0;
    let end = -1;
    for (let i = start; i < css.length; i += 1) {
      if (css[i] === "{") depth += 1;
      if (css[i] === "}") {
        depth -= 1;
        if (depth === 0) {
          end = i;
          break;
        }
      }
    }
    assert.notEqual(end, -1, `layer ${layerName} must be closed`);
    bodies.push(css.slice(start + 1, end));
    marker.lastIndex = end + 1;
  }
  return bodies.join("\n");
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

test("business rules keep the canonical eight-step font scale", () => {
  const canvases = [
    "reset",
    "base",
    "components",
    "patterns",
    "utilities",
  ];
  const raw = canvases
    .map((layer) => extractLayerText(CSS, layer))
    .join("\n")
    .match(/font-size\s*:\s*[0-9]+(?:\.[0-9]+)?(?:px|rem)\s*;/g);
  assert.equal(raw, null);

  const tokens = extractLayerText(CSS, "tokens");
  for (const name of [
    "2xs",
    "xs",
    "sm",
    "base",
    "lg",
    "xl",
    "2xl",
    "3xl",
  ]) {
    assert.match(tokens, new RegExp(`--text-${name}\\s*:`));
  }
});

test("business rules keep spacing on the canonical 4px grid", () => {
  const canvases = [
    "reset",
    "base",
    "components",
    "patterns",
    "utilities",
  ];
  const spacing = canvases
    .map((layer) => extractLayerText(CSS, layer))
    .join("\n")
    .match(
      /(?:margin(?:-(?:top|right|bottom|left))?|padding(?:-(?:top|right|bottom|left))?|gap|row-gap|column-gap)\s*:\s*[^;{}]+;/g,
    ) || [];

  const allowed = new Set(["0", "0px", "-0px", "1px", "-1px"]);
  const disallowed = spacing.filter((declaration) => {
    const dimensions = declaration.match(/-?\d+(?:\.\d+)?(?:px|rem)\b/g) || [];
    return dimensions.some((value) => !allowed.has(value));
  });
  assert.deepEqual(disallowed, []);

  const tokens = extractLayerText(CSS, "tokens");
  for (const name of [
    "space-1",
    "space-2",
    "space-3",
    "space-4",
    "space-5",
    "space-6",
    "space-8",
    "space-10",
    "space-12",
    "space-16",
  ]) {
    assert.match(tokens, new RegExp(`--${name}\\s*:`));
  }
});

test("business rules keep radius on the canonical seven-step scale", () => {
  const canvases = [
    "reset",
    "base",
    "components",
    "patterns",
    "utilities",
  ];
  const radii = canvases
    .map((layer) => extractLayerText(CSS, layer))
    .join("\n")
    .match(/border-radius\s*:\s*[^;{}]+;/g) || [];

  const disallowed = radii.filter((declaration) =>
    /(?:\d+(?:\.\d+)?(?:px|rem)|--radius-(?:4|6|8)\b|--ra-radius-)/.test(
      declaration,
    ),
  );
  assert.deepEqual(disallowed, []);

  const tokens = extractLayerText(CSS, "tokens");
  for (const name of ["xs", "sm", "md", "lg", "xl", "2xl", "pill"]) {
    assert.match(tokens, new RegExp(`--radius-${name}\\s*:`));
  }
});

test("radius tokens preserve component semantics", () => {
  const businessCss = [
    "reset",
    "base",
    "components",
    "patterns",
    "utilities",
  ]
    .map((layer) => extractLayerText(CSS, layer))
    .join("\n");

  const expected = new Map([
    [".icon-btn", "--radius-md"],
    [".card", "--radius-lg"],
    [".board-column", "--radius-lg"],
    [".settings-bento__card", "--radius-lg"],
    [".live-sheet-line", "--radius-sm"],
    [".panel", "--radius-xl"],
    [".drawer", "--radius-xl"],
    [".modal", "--radius-2xl"],
    [".export-dock__menu", "--radius-lg"],
  ]);

  for (const [selector, token] of expected) {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const rule = businessCss.match(
      new RegExp(
        `(?:^|,)\\s*${escaped}\\s*(?:,[^{}]*)?\\{([^}]*)\\}`,
        "ms",
      ),
    );
    assert.ok(rule, `missing rule for ${selector}`);
    assert.match(rule[1], new RegExp(`border-radius\\s*:\\s*var\\(${token}\\)\\s*;`));
  }
});

function shadowRules(css) {
  const rules = [];
  for (const match of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selector = match[1]
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/\s+/g, " ")
      .trim();
    if (!selector || selector.startsWith("@")) continue;
    for (const declaration of match[2].matchAll(
      /box-shadow\s*:\s*([^;{}]+)\s*;/g,
    )) {
      rules.push({
        selector,
        value: declaration[1].replace(/\s+/g, " ").trim(),
      });
    }
  }
  return rules;
}

test("business rules keep shadow on the canonical four-step scale", () => {
  const businessCss = [
    "reset",
    "base",
    "components",
    "patterns",
    "utilities",
  ]
    .map((layer) => extractLayerText(CSS, layer))
    .join("\n");

  const allowedFloatingSelector =
    /(?:^|,\s*)\.(?:inline-suggestion__paper|toast|offer-celebration__card|command-palette__dialog|command-panel|filter-pop|opt-bubble|export-dock__menu|toolbar-more__menu|board-more__menu)$|\.modal(?!-)(?:\s|$)|\.board-card\.is-dragging$|\.tabs--rail button:hover::after$/;
  const canonicalShadow = /var\(--shadow-(popover|modal|toast|drag)\)/;
  const focusRing = /var\(--(?:ra-)?focus(?:-ring|-ring-error)?\)/;
  const nonFloatingRing = /^(?:inset\b|0 0 0\b)/;
  const disallowed = shadowRules(businessCss).filter(({ selector, value }) => {
    if (/^(?:none|var\(--shadow-none\))$/.test(value)) return false;
    if (canonicalShadow.test(value)) {
      return !allowedFloatingSelector.test(selector);
    }
    if (focusRing.test(value)) return false;
    return !nonFloatingRing.test(value);
  });

  assert.deepEqual(
    disallowed,
    [],
    `non-canonical business box-shadow declarations: ${JSON.stringify(
      disallowed,
      null,
      2,
    )}`,
  );
});

test("business rules do not use legacy card or alias shadow tokens", () => {
  const businessCss = [
    "reset",
    "base",
    "components",
    "patterns",
    "utilities",
  ]
    .map((layer) => extractLayerText(CSS, layer))
    .join("\n");

  assert.doesNotMatch(
    businessCss,
    /var\(--shadow(?:-\d|-(?:sm|inset))?(?=\s*[,)])/,
  );
  assert.doesNotMatch(businessCss, /var\(--(?:card-shadow-|ra-shadow-card)/);
});

test("shadow tokens publish four floating steps plus none", () => {
  const tokens = extractLayerText(CSS, "tokens");
  for (const name of [
    "none",
    "popover",
    "modal",
    "toast",
    "drag",
  ]) {
    assert.match(tokens, new RegExp(`--shadow-${name}\\s*:`));
  }
});
