import { test } from "node:test";
import assert from "node:assert/strict";
import {
  inlineMarkdown,
  previewFor,
  renderMarkdown,
} from "../../src/resualign/static/app/format.js";

/* ------------------------------------------------------------------ */
/* inlineMarkdown                                                      */
/* ------------------------------------------------------------------ */

test("inlineMarkdown converts bold and code spans", () => {
  assert.equal(inlineMarkdown("**bold**"), "<strong>bold</strong>");
  assert.equal(inlineMarkdown("`code`"), "<code>code</code>");
  assert.equal(
    inlineMarkdown("**a** and `b`"),
    "<strong>a</strong> and <code>b</code>",
  );
});

test("inlineMarkdown leaves plain text untouched", () => {
  assert.equal(inlineMarkdown("plain"), "plain");
  assert.equal(inlineMarkdown(""), "");
});

/* ------------------------------------------------------------------ */
/* renderMarkdown                                                      */
/* ------------------------------------------------------------------ */

test("renderMarkdown renders headings of all levels", () => {
  assert.equal(renderMarkdown("# H1"), "<h1>H1</h1>");
  assert.equal(renderMarkdown("### H3"), "<h3>H3</h3>");
  assert.equal(renderMarkdown("###### H6"), "<h6>H6</h6>");
});

test("renderMarkdown renders list items into one ul", () => {
  assert.equal(renderMarkdown("- a\n- b"), "<ul><li>a</li><li>b</li></ul>");
  assert.equal(renderMarkdown("* a\n• b"), "<ul><li>a</li><li>b</li></ul>");
});

test("renderMarkdown renders paragraphs and closes lists on blank lines", () => {
  assert.equal(
    renderMarkdown("p1\n\n- a"),
    "<p>p1</p><ul><li>a</li></ul>",
  );
});

test("renderMarkdown applies inline formatting inside elements", () => {
  assert.equal(renderMarkdown("**x**"), "<p><strong>x</strong></p>");
  assert.equal(renderMarkdown("- **x**"), "<ul><li><strong>x</strong></li></ul>");
  assert.equal(renderMarkdown("# **x**"), "<h1><strong>x</strong></h1>");
});

test("renderMarkdown escapes HTML and returns empty for blank input", () => {
  assert.equal(renderMarkdown("<script>"), "<p>&lt;script&gt;</p>");
  assert.equal(renderMarkdown(""), "");
  assert.equal(renderMarkdown(null), "");
});

/* ------------------------------------------------------------------ */
/* previewFor (command panel)                                          */
/* ------------------------------------------------------------------ */

test("previewFor shows hint for empty input", () => {
  const html = previewFor("");
  assert.match(html, /command-preview--hint/);
});

test("previewFor shows URL preview for links", () => {
  const html = previewFor("https://example.com/job/1");
  assert.match(html, /command-preview--url/);
  assert.match(html, /badge-blue/);
  assert.match(html, /example\.com\/job\/1/);
});

test("previewFor shows text preview with char/line counts", () => {
  const html = previewFor("a\nb\nc");
  assert.match(html, /command-preview--text/);
  assert.match(html, /badge-teal/);
  assert.match(html, /5 字符 · 3 行/);
  assert.match(html, /<div>a<\/div>/);
});

test("previewFor truncates long text and escapes lines", () => {
  const lines = Array.from({ length: 8 }, (_, i) => `line ${i}`);
  const html = previewFor(lines.join("\n"));
  assert.match(html, /其余 3 行/);
  const escaped = previewFor("<b>");
  assert.match(escaped, /&lt;b&gt;/);
});
