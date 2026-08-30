/* Phase E 收口 —— 对齐入口静态契约回归测试。
 * 与 adr0033.test.mjs 同模式：直接读源码断言
 *   1) 卡片单岗对齐（align-job）走 /api/jobs/{id}/workbench + medium 粒度
 *   2) 看板「批量对齐」走矩阵接口 /api/batch-align + selector=pending
 *   3) 旧的逐条 workbench 循环实现已删除
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const mainSrc = readFileSync(
  join(root, "src/resualign/static/app/main.js"),
  "utf8",
);
const formatSrc = readFileSync(
  join(root, "src/resualign/static/app/format.js"),
  "utf8",
);

test("align-job posts to /api/jobs/{id}/workbench with medium granularity", () => {
  const handler = mainSrc.slice(mainSrc.indexOf('"align-job"'));
  assert.match(handler, /\/api\/jobs\/\$\{encodeURIComponent\(jobId\)\}\/workbench/);
  assert.match(handler, /granularity:\s*"medium"/);
  assert.match(handler, /\/api\/master-resumes\?limit=1/);
});

test("batch-align-pending posts to matrix /api/batch-align with selector=pending", () => {
  const handler = mainSrc.slice(mainSrc.indexOf('"batch-align-pending"'));
  assert.match(handler, /\/api\/batch-align/);
  assert.match(handler, /selector:\s*"pending"/);
  assert.doesNotMatch(handler, /for \(const job of pending\)/, "legacy per-job loop removed");
});

test("legacy per-job workbench loop is gone from batch-align-pending", () => {
  const handler = mainSrc.slice(mainSrc.indexOf('"batch-align-pending"'));
  assert.doesNotMatch(
    handler,
    /\/api\/jobs\/\$\{encodeURIComponent\(job\.job_id\)\}\/workbench/,
    "batch button must not enqueue jobs one by one",
  );
});

test("board card has a single boardAlignButton definition", () => {
  const matches = formatSrc.match(/function boardAlignButton\(job\)\s*\{/g) || [];
  assert.equal(matches.length, 1, "boardAlignButton must be defined exactly once");
  assert.match(formatSrc, /\$\{boardAlignButton\(job\)\}/, "boardCard calls boardAlignButton");
});
