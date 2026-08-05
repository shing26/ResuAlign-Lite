import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildWbDetailHtml,
  inlineMarkdown,
  previewFor,
  renderAppraisalRadar,
  renderMarkdown,
  renderWbProvenance,
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

/* ------------------------------------------------------------------ */
/* renderWbProvenance                                                  */
/* ------------------------------------------------------------------ */

test("renderWbProvenance returns empty when no quote exists", () => {
  assert.equal(renderWbProvenance({}), "");
  assert.equal(renderWbProvenance({ provenance_quote: "" }), "");
});

test("renderWbProvenance renders quote with optional source span", () => {
  const html = renderWbProvenance({
    provenance_quote: "负责缓存优化",
    source_span: "L12-L14",
  });
  assert.match(html, /<blockquote class="provenance-quote">负责缓存优化 <span class="muted">L12-L14<\/span><\/blockquote>/);
  assert.doesNotMatch(renderWbProvenance({ provenance_quote: "x" }), /muted/);
});

/* ------------------------------------------------------------------ */
/* buildWbDetailHtml                                                   */
/* ------------------------------------------------------------------ */

test("buildWbDetailHtml renders four detail blocks with data", () => {
  const html = buildWbDetailHtml(
    {
      jd_profile: {
        must_have_skills: ["Python"],
        nice_to_have_skills: ["Redis"],
        soft_skills: ["沟通"],
        business_scenarios: ["高并发"],
        min_years_experience: 3,
        education_requirements: ["本科"],
      },
      gap_report: {
        missing_keywords: ["K8s"],
        misaligned_emphasis: ["前端"],
        strength_matches: ["Python"],
      },
      eval_score: {
        jd_match_score: 85,
        improvement: 12,
        hallucination_detected: false,
        gap_coverage: "80%",
        hallucination_details: [],
      },
    },
    [
      {
        type: "modify",
        provenance_quote: "来源句",
        source_span: "L3",
      },
    ],
  );
  assert.match(html, /<details class="wb-detail" open>/);
  assert.match(html, /必备技能/);
  assert.match(html, />Python<\/span>/);
  assert.match(html, /缺失关键词/);
  assert.match(html, />K8s</);
  assert.match(html, /JD 匹配 85/);
  assert.match(html, /幻觉 未检出/);
  assert.match(html, /Provenance 来源/);
  assert.match(html, /1\. modify/);
  assert.match(html, /来源句/);
});

test("buildWbDetailHtml handles empty result", () => {
  const html = buildWbDetailHtml({}, []);
  assert.match(html, /<span class="muted small">—<\/span>/);
  assert.match(html, /暂无来源引用/);
});

/* ------------------------------------------------------------------ */
/* renderAppraisalRadar                                                */
/* ------------------------------------------------------------------ */

test("renderAppraisalRadar returns empty when no components are present", () => {
  assert.equal(renderAppraisalRadar({}), "");
});

test("renderAppraisalRadar renders svg polygon with Chinese labels", () => {
  const html = renderAppraisalRadar({
    match: 80,
    salary: 60,
    hard_conditions: 50,
    quality: 90,
    commute: 70,
  });
  assert.match(html, /<svg class="radar-svg"/);
  assert.match(html, /class="radar-polygon"/);
  assert.match(html, />匹配</);
  assert.match(html, />薪资</);
  assert.match(html, /viewBox="0 0 180 180"/);
});

test("renderAppraisalRadar omits missing axes", () => {
  const html = renderAppraisalRadar({ match: 50 });
  assert.match(html, />匹配</);
  assert.doesNotMatch(html, />薪资</);
});
