import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  LIVE_SHEET_PLACEHOLDER,
  highlightSkillGapHtml,
  liveSheetPatch,
  renderLiveSheetHtml,
} from "../../src/resualign/static/app/format.js";

/* ------------------------------------------------------------------ */
/* renderLiveSheetHtml                                                 */
/* ------------------------------------------------------------------ */

test("renderLiveSheetHtml renders the dark paper shell with placeholder for empty draft", () => {
  const html = renderLiveSheetHtml(null);
  assert.match(html, /data-live-sheet/);
  assert.match(html, /data-live-sheet-paper/);
  assert.match(html, />定稿预览</);
  assert.match(html, /采纳右侧提案后，此处实时预览定稿/);
  assert.doesNotMatch(html, /<h1|<p>|<ul>/);
  /* whitespace-only draft is treated as empty too */
  assert.equal(renderLiveSheetHtml("   ").includes(LIVE_SHEET_PLACEHOLDER), true);
});

test("renderLiveSheetHtml embeds renderMarkdown output for non-empty draft", () => {
  const html = renderLiveSheetHtml("# 张三\n\n负责后端开发\n- 技能A");
  assert.match(html, /<h1>张三<\/h1>/);
  assert.match(html, /<p>负责后端开发<\/p>/);
  assert.match(html, /<ul>/);
  assert.match(html, /<li>技能A<\/li>/);
  assert.doesNotMatch(html, /live-sheet__placeholder/);
});

test("renderLiveSheetHtml escapes markdown input", () => {
  const html = renderLiveSheetHtml("<script>alert(1)</script>");
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
});

/* ------------------------------------------------------------------ */
/* liveSheetPatch                                                      */
/* ------------------------------------------------------------------ */

test("liveSheetPatch returns { html, rows, addedLines } and marks new lines", () => {
  const patch = liveSheetPatch("A\nB", "A\nB\nC\nD");
  assert.deepEqual(Object.keys(patch).sort(), ["addedLines", "html", "rows"]);
  assert.deepEqual(patch.rows.map((row) => row.text), ["A", "B", "C", "D"]);
  assert.deepEqual(patch.rows.map((row) => row.added), [false, false, true, true]);
  assert.ok(patch.addedLines instanceof Set);
  assert.equal(patch.addedLines.size, 2);
  assert.ok(patch.addedLines.has(2));
  assert.ok(patch.addedLines.has(3));
  assert.match(patch.html, /live-sheet-line--added/);
  assert.match(patch.html, /data-live-line="2"/);
  assert.match(patch.html, />C<\/div>/);
});

test("liveSheetPatch reports no added lines for an unchanged draft", () => {
  const patch = liveSheetPatch("A\nB\nC", "A\nB\nC");
  assert.equal(patch.addedLines.size, 0);
  assert.equal(patch.rows.every((row) => !row.added), true);
  assert.equal(patch.rows.length, 3);
  assert.doesNotMatch(patch.html, /live-sheet-line--added/);
});

test("liveSheetPatch treats the first render as all-added and empty draft as placeholder", () => {
  const first = liveSheetPatch("", "X\nY");
  assert.deepEqual([...first.addedLines], [0, 1]);
  assert.match(first.html, /live-sheet-line--added/);
  const empty = liveSheetPatch("X", "");
  assert.deepEqual(empty.rows, []);
  assert.equal(empty.addedLines.size, 0);
  assert.match(empty.html, /采纳右侧提案后，此处实时预览定稿/);
});

test("liveSheetPatch skips blank lines and escapes row text", () => {
  const patch = liveSheetPatch("", "a\n\n<b>c");
  assert.deepEqual(patch.rows.map((row) => row.text), ["a", "<b>c"]);
  assert.deepEqual(patch.rows.map((row) => row.index), [0, 1]);
  assert.match(patch.html, /&lt;b&gt;c/);
  assert.doesNotMatch(patch.html, /<b>c<\/div>/);
});

/* ------------------------------------------------------------------ */
/* highlightSkillGapHtml                                               */
/* ------------------------------------------------------------------ */

test("highlightSkillGapHtml marks a matching item with data-match-skill + is-skill-match", () => {
  const html = highlightSkillGapHtml(
    {
      missing_keywords: ["K8s", "Docker"],
      strength_matches: ["Python"],
      misaligned_emphasis: ["前端"],
    },
    "k8s",
  );
  assert.match(html, /gap-group--missing/);
  assert.match(html, /gap-group--strength/);
  assert.match(html, /gap-group--warn/);
  assert.match(
    html,
    /<span class="gap-tag is-skill-match" data-match-skill>K8s<\/span>/,
  );
  assert.doesNotMatch(html, /data-match-skill>Docker</);
  assert.match(html, /gap-tag--ok">Python<\/span>/);
});

test("highlightSkillGapHtml matches case-insensitively across all gap groups", () => {
  const html = highlightSkillGapHtml(
    { missing_keywords: [], strength_matches: ["Python", "Go"], misaligned_emphasis: [] },
    "python",
  );
  assert.match(
    html,
    /<span class="gap-tag gap-tag--ok is-skill-match" data-match-skill>Python<\/span>/,
  );
  assert.doesNotMatch(html, /is-skill-match>Go</);
});

test("highlightSkillGapHtml adds no highlights when the skill misses", () => {
  const html = highlightSkillGapHtml(
    { missing_keywords: ["K8s"], strength_matches: [], misaligned_emphasis: [] },
    "Go",
  );
  assert.doesNotMatch(html, /is-skill-match/);
  assert.doesNotMatch(html, /data-match-skill/);
  assert.match(html, /<span class="gap-tag">K8s<\/span>/);
});

test("highlightSkillGapHtml tolerates null gap and blank skill", () => {
  assert.equal(highlightSkillGapHtml(null, "Go"), null);
  const blank = highlightSkillGapHtml({ missing_keywords: ["K8s"] }, "  ");
  assert.doesNotMatch(blank, /is-skill-match/);
  assert.match(highlightSkillGapHtml({}), /尚未生成差距报告/);
});

test("highlightSkillGapHtml escapes items and keeps the highlight marker", () => {
  const html = highlightSkillGapHtml({ missing_keywords: ["<script>"] }, "<script>");
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /data-match-skill/);
});

/* ------------------------------------------------------------------ */
/* 三栏布局静态断言（styles.css 存在性）                                  */
/* ------------------------------------------------------------------ */

const CSS_PATH = fileURLToPath(
  new URL("../../src/resualign/static/styles.css", import.meta.url),
);
const css = readFileSync(CSS_PATH, "utf8");

test("styles.css locks the three-column workbench grid at 22/48/30", () => {
  const layoutBlock = css.match(/\.split-layout\s*\{[\s\S]*?\}/);
  assert.ok(layoutBlock, "expected a .split-layout rule in styles.css");
  assert.match(layoutBlock[0], /grid-template-columns:\s*22%\s+48%\s+30%/);
});

test("styles.css exposes pane hooks, mobile collapse and live-sheet styles", () => {
  assert.match(css, /\[data-inspector-pane\]/);
  assert.match(css, /\[data-diff-pane\]/);
  assert.match(css, /\[data-live-sheet-pane\]/);
  assert.match(css, /@media \(max-width:\s*900px\)/);
  assert.match(css, /grid-template-columns:\s*1fr/);
  assert.match(css, /\.live-sheet/);
  assert.match(css, /\.live-sheet-line--added/);
  assert.match(css, /\.diff-card__actions \.btn/);
  assert.match(css, /\.diff-char-del/);
  assert.match(css, /\.diff-char-ins/);
});
