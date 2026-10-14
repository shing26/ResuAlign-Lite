/* #146: 「两条轮询路径的 errors 渲染」必须有测试。
 *
 * skip-detail.test.mjs 只覆盖了纯模块的分类与 HTML 生成。但 #146 的 bug
 * 不在纯函数里 —— 后端早就逐行返回 errors，前端只渲染计数。真正会坏的是
 * 接线：两条轮询路径各自把 errors 喂给哪个容器。
 *
 *   粘贴 CSV 导入 → [data-import-detail]
 *   岗位表同步   → [data-job-table-detail]
 *
 * 这两条路径在 main.js 里各有一份轮询回调，任何一条漏掉 renderSkipDetail
 * 都只会表现为「计数变了、明细不出现」，纯函数测试照样全绿。
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { Window } from "happy-dom";

import { renderSkipDetail } from "../../src/resualign/static/app/skip-detail.js";

const here = dirname(fileURLToPath(import.meta.url));
const MAIN = readFileSync(
  join(here, "../../src/resualign/static/app/main.js"),
  "utf8",
);

const MISSING_JD = "数分实习生: 缺少 JD 正文（WorkBuddy 补齐后会自动导入）";
const DUPLICATE = "AI 实习生 - 后端开发: Duplicate job already exists";

function detailNode(selector) {
  const window = new Window();
  window.document.body.innerHTML =
    `<form data-form="job-import"><div ${selector}></div></form>`;
  return window.document.querySelector(`[${selector}]`);
}

test("#146: 粘贴 CSV 导入路径的 [data-import-detail] 渲染缺 JD 行", () => {
  const node = detailNode("data-import-detail");
  renderSkipDetail(node, [MISSING_JD]);
  assert.ok(node.innerHTML.length > 0, "导入路径的明细容器不能是空的");
  assert.match(node.textContent, /缺少 JD 正文/);
  assert.match(node.textContent, /数分实习生/);
});

test("#146: 岗位表同步路径的 [data-job-table-detail] 渲染同样的明细", () => {
  const node = detailNode("data-job-table-detail");
  renderSkipDetail(node, [MISSING_JD, DUPLICATE]);
  assert.ok(node.innerHTML.length > 0, "同步路径的明细容器不能是空的");
  assert.match(node.textContent, /缺少 JD 正文/);
  // 真问题常开显示，正常重复折叠 —— 计数与明细必须能对上。
  assert.match(node.textContent, /已跳过|已在库中/);
});

test("#146: 两条轮询路径都调用了 renderSkipDetail", () => {
  // 岗位表同步的轮询回调
  const syncPoll = MAIN.match(/"sync-job-table":[\s\S]*?\n  "preanalyze-pending":/);
  assert.ok(syncPoll, "sync-job-table action not found");
  assert.match(
    syncPoll[0],
    /renderSkipDetail\(\s*document\.querySelector\("\[data-job-table-detail\]"\)/,
    "岗位表同步的轮询回调必须把 errors 喂给 [data-job-table-detail]",
  );

  // 粘贴 CSV 导入的轮询回调
  const importPoll = MAIN.match(
    /async function submitImport[\s\S]*?\r?\n}\r?\n/,
  );
  assert.ok(importPoll, "submitImport not found");
  assert.match(
    importPoll[0],
    /renderSkipDetail\(\s*document\.querySelector\("\[data-import-detail\]"\)/,
    "导入的轮询回调必须把 errors 喂给 [data-import-detail]",
  );
});

test("#146: 空 errors 不留下误导性的容器内容", () => {
  const node = detailNode("data-import-detail");
  renderSkipDetail(node, []);
  assert.equal(node.innerHTML.trim(), "");
});
