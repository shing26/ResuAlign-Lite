import { test } from "node:test";
import assert from "node:assert/strict";

import { recommendedJobsHtml } from "../../src/resualign/static/app/format.js";

const FORBIDDEN_COPY = ["向量", "相似度", "RAG", "embedding"];

function assertCopyClean(html) {
  for (const word of FORBIDDEN_COPY) {
    assert.ok(!html.includes(word), "用户可见文案不得出现 " + word);
  }
}

test("disabled payload renders a neutral hint and no crash", () => {
  const html = recommendedJobsHtml({ enabled: false, degraded: true, items: [] });
  assert.match(html, /未启用/);
  assertCopyClean(html);
});

test("degraded payload keeps items and explains the fallback", () => {
  const html = recommendedJobsHtml({
    enabled: true,
    degraded: true,
    reason: "index_empty",
    items: [
      {
        job_id: "job-1",
        title: "后端工程师",
        company: "示例公司",
        location: "深圳",
        job_function: "后端",
        score: 82,
        why: { semantic_percentile: 87, skill_hits: ["java", "redis"] },
      },
    ],
  });
  assert.match(html, /匹配分/);
  assert.match(html, /后端工程师/);
  assert.match(html, /匹配度分位 87/);
  assert.match(html, /有据技能：java、redis/);
  assertCopyClean(html);
});

test("job titles and skills are escaped", () => {
  const html = recommendedJobsHtml({
    enabled: true,
    degraded: false,
    items: [
      {
        job_id: "job-<1>",
        title: '<img src=x onerror="alert(1)">',
        company: "A&B",
        why: { semantic_percentile: 50, skill_hits: ["<b>"] },
      },
    ],
  });
  assert.ok(!html.includes("<img"));
  assert.match(html, /&lt;img/);
  assert.match(html, /A&amp;B/);
  assert.match(html, /&lt;b&gt;/);
  assertCopyClean(html);
});

test("links deep-link into the workbench by job id", () => {
  const html = recommendedJobsHtml({
    enabled: true,
    degraded: false,
    items: [{ job_id: "job-9", title: "T", why: {} }],
  });
  assert.match(html, /#\/workspace\?job_id=job-9/);
});

test("empty items renders a calm empty state", () => {
  const html = recommendedJobsHtml({ enabled: true, degraded: false, items: [] });
  assert.match(html, /暂无推荐/);
  assertCopyClean(html);
});
