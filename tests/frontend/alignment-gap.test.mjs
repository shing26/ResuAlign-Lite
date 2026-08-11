/* v2.0 增量对齐：折叠筛选 Toolbar 与简历双态编辑的 DOM 契约测试。
 * 与 imports-check.mjs 同模式 —— 直接读源码断言渲染模板保留的
 * data-* 契约，确保未来重构不会静默丢掉这两个已恢复的功能。
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const appDir = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "src/resualign/static/app",
);

function read(name) {
  return readFileSync(join(appDir, name), "utf8");
}

/* ------------------------------------------------------------------ */
/* kanban.js 折叠筛选 Toolbar                                          */
/* ------------------------------------------------------------------ */

test("kanban.js renders the collapsible filter toolbar (job-filter form)", () => {
  const src = read("kanban.js");
  assert.match(src, /data-board-filter/, "collapsible filter container");
  assert.match(src, /data-form="job-filter"/, "reuses the existing filter handler");
  /* 四维筛选字段必须齐备（关键词/职能/级别/状态） */
  assert.match(src, /name="search"/);
  assert.match(src, /name="job_function"/);
  assert.match(src, /name="seniority"/);
  assert.match(src, /name="status"/);
  /* 清除按钮复用既有 clear-filters action */
  assert.match(src, /data-action="clear-filters"/);
});

test("styles.css styles the collapsible filter toolbar", () => {
  const css = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "..", "..", "src/resualign/static/styles.css"),
    "utf8",
  );
  assert.match(css, /\.board-filter\s*\{/);
  assert.match(css, /\.board-filter__summary\s*\{/);
  assert.match(css, /\.board-filter__form\s*\{/);
  assert.match(css, /\.board-filter\[open\]/, "expanded state hook");
});

/* ------------------------------------------------------------------ */
/* resume-center.js 双态编辑                                           */
/* ------------------------------------------------------------------ */

test("resume-center.js keeps the inline source editor (dual-mode editing)", () => {
  const src = read("resume-center.js");
  assert.match(src, /data-resume-inline-edit/, "hidden inline form");
  assert.match(
    src,
    /data-form="resume-edit"/,
    "inline save reuses the existing resume-edit submit handler",
  );
  assert.match(src, /data-action="toggle-resume-inline-edit"/, "toggle into source mode");
  assert.match(src, /data-action="cancel-resume-inline-edit"/, "cancel restores the view");
  assert.match(src, /name="content"/, "markdown textarea field");
});

test("main.js wires the dual-mode edit actions", () => {
  const src = read("main.js");
  assert.match(src, /"toggle-resume-inline-edit"/);
  assert.match(src, /"cancel-resume-inline-edit"/);
});

test("styles.css styles the inline source editor", () => {
  const css = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "..", "..", "src/resualign/static/styles.css"),
    "utf8",
  );
  assert.match(css, /\.resume-inline-edit\s*\{/);
  assert.match(css, /body\.resume-inline-editing/, "view hidden while editing");
});
