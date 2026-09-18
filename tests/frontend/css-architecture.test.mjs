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

function declarationsFor(css, selector, property) {
  const values = [];
  for (const match of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selectors = match[1]
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .split(",")
      .map((part) => part.replace(/\s+/g, " ").trim());
    if (!selectors.includes(selector)) continue;

    const declaration = match[2].match(
      new RegExp(`${property}\\s*:\\s*([^;{}]+)\\s*;`),
    );
    if (declaration) values.push(declaration[1].replace(/\s+/g, " ").trim());
  }
  return values;
}

test("business rules keep z-index on the canonical nine-step scale", () => {
  const businessCss = [
    "reset",
    "base",
    "components",
    "patterns",
    "utilities",
  ]
    .map((layer) => extractLayerText(CSS, layer))
    .join("\n");

  const raw = businessCss.match(/z-index\s*:\s*-?\d+\s*;/g) || [];
  assert.deepEqual(raw, []);
  assert.doesNotMatch(businessCss, /var\(--ra-z-/);

  const tokens = extractLayerText(CSS, "tokens");
  for (const name of [
    "below",
    "base",
    "sticky",
    "rail",
    "dropdown",
    "drawer",
    "modal",
    "popover",
    "toast",
  ]) {
    assert.match(tokens, new RegExp(`--z-${name}\\s*:`));
  }
});

test("z-index tokens preserve layering semantics", () => {
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
    [".toast-region", "--z-toast"],
    [".modal-backdrop", "--z-modal"],
    [".command-palette", "--z-modal"],
    [".app-rail", "--z-rail"],
    [".filter-pop", "--z-dropdown"],
    [".export-dock__menu", "--z-dropdown"],
    [".batch-fab", "--z-dropdown"],
    [".tabs--rail button:hover::after", "--z-popover"],
  ]);

  for (const [selector, token] of expected) {
    const values = declarationsFor(businessCss, selector, "z-index");
    assert.ok(values.length > 0, `missing z-index for ${selector}`);
    assert.ok(
      values.every((value) => value === `var(${token})`),
      `${selector} must use ${token}, got ${values.join(", ")}`,
    );
  }
});

test("B3b activates the canonical color namespace", () => {
  const tokens = extractLayerText(CSS, "tokens");
  assert.match(tokens, /--accent:\s*#0E7C8F/, "canonical light accent");
  assert.match(tokens, /B3 color cutover/, "legacy aliases resolve to canonical names");
  assert.match(tokens, /--primary:\s*var\(--accent\)/);
  assert.match(tokens, /--surface:\s*var\(--surface-1\)/);
  assert.match(tokens, /--border:\s*var\(--line\)/);
});

test("business rules contain no color literals", () => {
  const businessCss = [
    "reset",
    "base",
    "components",
    "patterns",
    "utilities",
    "overrides",
  ]
    .map((layer) => extractLayerText(CSS, layer))
    .join("\n")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/--[\w-]+\s*:\s*[^;]+;/g, "");

  const literals = businessCss.match(
    /#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|hsla?\([^)]*\)/g,
  ) || [];
  assert.deepEqual(literals, []);
});

test("live-sheet keeps its component-private dark-paper constants", () => {
  const businessCss = extractLayerText(CSS, "components");
  const liveSheet = businessCss.match(/\.live-sheet\s*{([^}]*)}/)?.[1] || "";

  assert.match(liveSheet, /--ls-bg:\s*#0d1420/);
  assert.match(liveSheet, /--ls-bg-2:\s*#111b2b/);
  assert.match(liveSheet, /--ls-ink:\s*#dbe4ef/);
  assert.match(liveSheet, /--ls-muted:\s*#8fa1b0/);
  assert.doesNotMatch(liveSheet, /--ls-bg-2:\s*var\(--/);
});

test("decorative dual-color gradients stay out of business rules", () => {
  const businessCss = [
    "reset",
    "base",
    "components",
    "patterns",
    "utilities",
    "overrides",
  ]
    .map((layer) => extractLayerText(CSS, layer))
    .join("\n");

  assert.doesNotMatch(
    businessCss,
    /linear-gradient\(\s*(?:135deg|90deg),\s*var\(--primary\),\s*var\(--teal\)/,
  );
  assert.doesNotMatch(
    businessCss,
    /linear-gradient\(\s*180deg,\s*var\(--workbench-bg-deep\)/,
  );
});

test("B4 native selects use one theme-aware self-drawn chevron", () => {
  const tokens = extractLayerText(CSS, "tokens");
  const businessCss = [
    "base",
    "components",
  ]
    .map((layer) => extractLayerText(CSS, layer))
    .join("\n");

  assert.match(tokens, /--select-chevron-light:\s*url\(/, "light chevron token");
  assert.match(tokens, /--select-chevron-dark:\s*url\(/, "dark chevron token");
  assert.match(
    tokens,
    /:root\[data-theme="dark"\][\s\S]*?--select-chevron:\s*var\(--select-chevron-dark\)/,
    "dark theme must swap the chevron token",
  );

  const appearance = declarationsFor(
    businessCss,
    ":root select:not([multiple])",
    "appearance",
  );
  const arrow = declarationsFor(
    businessCss,
    ":root select:not([multiple])",
    "background-image",
  );
  const position = declarationsFor(
    businessCss,
    ":root select:not([multiple])",
    "background-position",
  );

  assert.ok(appearance.includes("none"), "native appearance must be removed");
  assert.ok(arrow.includes("var(--select-chevron)"), "select must use the arrow token");
  assert.ok(
    position.includes("right var(--space-3) center"),
    "arrow must reserve the canonical right inset",
  );
});

test("B4 native controls keep select heights on the control scale", () => {
  const businessCss = [
    "base",
    "components",
  ]
    .map((layer) => extractLayerText(CSS, layer))
    .join("\n");

  for (const selector of [
    "select",
    ".board-sort select",
    ".board-status-select",
    ".header-job-select",
  ]) {
    const values = declarationsFor(businessCss, selector, "min-height");
    assert.ok(values.length > 0, `missing min-height for ${selector}`);
    assert.ok(
      values.every((value) => value.startsWith("var(--")),
      `${selector} must use a canonical height token, got ${values.join(", ")}`,
    );
  }
});

test("B4 native controls keep one outline focus ring", () => {
  const businessCss = [
    "base",
    "components",
  ]
    .map((layer) => extractLayerText(CSS, layer))
    .join("\n");

  assert.match(
    businessCss,
    /:root\s+:is\(input,\s*select,\s*textarea\):focus-visible[\s\S]*?outline:\s*var\(--focus-ring-outline\)/,
  );
  assert.match(
    businessCss,
    /outline-offset:\s*var\(--focus-ring-offset\)/,
  );
  assert.match(
    businessCss,
    /:root select option\s*\{[\s\S]*?color-scheme:\s*inherit/,
    "native option popup must inherit the active color scheme",
  );
});
