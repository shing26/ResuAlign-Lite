/* ADR-0045 icon source guard: functional SVGs come from one factory, and
 * button/link affordances do not fall back to platform emoji or glyphs. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const staticDir = join(root, "src/resualign/static");
const appDir = join(staticDir, "app");

function readStatic(name) {
  return readFileSync(join(staticDir, name), "utf8");
}

function readApp(name) {
  return readFileSync(join(appDir, name), "utf8");
}

test("icons.js is the only functional SVG source outside the empty-state illustration", () => {
  for (const name of readdirSync(appDir).filter((file) => file.endsWith(".js"))) {
    const svgCount = (readApp(name).match(/<svg\b/g) || []).length;
    if (name === "icons.js") {
      assert.ok(svgCount > 0, "icons.js must own the inline SVG factory output");
    } else if (name === "format.js") {
      assert.equal(svgCount, 1, "format.js keeps only the structural empty-state illustration");
    } else {
      assert.equal(svgCount, 0, `${name} must not inline functional SVG`);
    }
  }
});

test("B5 removes functional emoji and UI glyph stand-ins", () => {
  const sources = [
    readStatic("index.html"),
    ...readdirSync(appDir)
      .filter((file) => file.endsWith(".js"))
      .map(readApp),
  ].join("\n");
  const css = readStatic("styles.css");

  assert.doesNotMatch(sources, /[\u270F\uFE0F\u25D0\u2715]/,"no pencil/theme/modal emoji glyphs");
  assert.doesNotMatch(sources, /[×✕]/u, "no close glyphs");
  assert.doesNotMatch(sources, /[↻↗]/u, "no action arrows as button glyphs");
  assert.doesNotMatch(sources, /···/u, "no text more glyph");
  assert.doesNotMatch(sources, /[▾▸]/u, "no dropdown caret glyph");
  assert.doesNotMatch(css, /[\u270F\uFE0F\u25D0\u2715↻↗▾▸]/u, "CSS comments contain no functional glyphs");
});

test("B5 action affordances use the shared Lucide factory", () => {
  assert.match(readApp("format.js"), /icon\("pencil", 16\)/);
  assert.match(readApp("format.js"), /icon\("more-horizontal", 20\)/);
  assert.match(readApp("format.js"), /icon\("chevron-down", 16\)/);
  assert.match(readApp("format.js"), /icon\("arrow-right", 16, "workbench-guide__arrow"\)/);
  assert.match(readApp("format.js"), /icon\("rotate-ccw", 16\)/);
  assert.match(readApp("format.js"), /icon\("external-link", 16\)/);
  assert.match(readApp("events.js"), /icon\("x", 20\)/);
  assert.match(readApp("events.js"), /icon\("x", 16\)/);
  assert.match(readApp("theme.js"), /icon\(theme === "dark" \? "moon" : "sun", 16\)/);
  assert.match(readApp("kanban.js"), /icon\("chevron-down", 16\)/);
  assert.match(readApp("command-panel.js"), /icon\("chevron-right", 16\)/);
  assert.match(readStatic("index.html"), /data-theme-icon/);
});

test("icon factory exposes only the approved sizes", async () => {
  const { icon } = await import(pathToFileURL(join(appDir, "icons.js")).href);
  const svg = icon("check", 20);

  assert.match(svg, /viewBox="0 0 24 24"/);
  assert.match(svg, /class="ic ic--20"/);
  assert.match(svg, /data-icon="check"/);
  assert.throws(() => icon("not-an-icon", 16), /Unknown icon/);
  assert.throws(() => icon("check", 14), /Unsupported icon size/);
});
