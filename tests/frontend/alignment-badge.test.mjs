import { test } from "node:test";
import assert from "node:assert/strict";

import { alignmentBadgeHtml } from "../../src/resualign/static/app/format.js";

/* ADR-0041 决定 5 / ticket #111：succeeded 徽章不再是「已对齐」的同义词。
 * 三形态各有硬断言；机读前缀 no_output 不得泄漏进用户可见文案。 */

test("usable>=1 → 绿色已对齐", () => {
  const html = alignmentBadgeHtml({
    alignment_status: "succeeded",
    usable_diffs: 2,
    has_gap: true,
  });
  assert.match(html, /badge-green/);
  assert.match(html, /已对齐/);
});

test("usable=0 且无缺口 → 琥珀「无缺口 · 无需改写」，禁止「已对齐」", () => {
  const html = alignmentBadgeHtml({
    alignment_status: "succeeded",
    usable_diffs: 0,
    has_gap: false,
    alignment_reason: "no_gap",
  });
  assert.doesNotMatch(html, /已对齐/, "no-gap zero-output must NOT read 已对齐");
  assert.match(html, /无缺口 · 无需改写/);
  assert.match(html, /badge-amber/);
});

test("model failure → 红色可重试徽章，机读前缀不外泄", () => {
  const html = alignmentBadgeHtml({
    alignment_status: "failed",
    usable_diffs: 0,
    has_gap: true,
    alignment_reason: "model_failed",
    alignment_error:
      "该岗位存在能力/经验缺口，但本轮未产出任何可用改写建议",
  });
  assert.match(html, /badge-red/);
  assert.match(html, /模型失败/);
  assert.doesNotMatch(html, /no_output:/, "machine prefix must be stripped");
  assert.match(html, /缺口/, "human reason kept in tooltip");
});

test("no_safe_rewrite → 非绿色无安全改写徽章，不冒充模型失败", () => {
  const html = alignmentBadgeHtml({
    alignment_status: "failed",
    usable_diffs: 0,
    has_gap: true,
    alignment_reason: "no_safe_rewrite",
    alignment_error: "简历原文没有足够依据",
  });
  assert.match(html, /badge-amber/);
  assert.match(html, /无安全改写/);
  assert.doesNotMatch(html, /已对齐|模型失败|对齐失败/);
  assert.doesNotMatch(html, /no_output:/);
});

test("旧数据行（无分型字段）保持原双徽章语义", () => {
  const legacyHint = alignmentBadgeHtml({
    alignment_status: "succeeded",
    diffs: [],
    alignment_error: "改写阶段多次失败",
  });
  assert.match(legacyHint, /诊断完成 · 改写未产出/);
  const legacyPlain = alignmentBadgeHtml({
    alignment_status: "succeeded",
    diffs: [],
  });
  assert.match(legacyPlain, /无建议/);
  assert.doesNotMatch(legacyPlain, /已对齐/);
});
