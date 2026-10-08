/* 看板勾选必须镜像进批量面板的岗位列表。
 *
 * 背景（实测复现，2026-10-08）：看板复选框 `data-board-check` 只驱动 FAB 的
 * 「已选 N」计数，而表单提交只读面板自己的 `data-batch-check`
 * （main.js 的 batch-align 分支）。两套状态不同步的结果是：用户勾了 2 个岗位、
 * FAB 明明写着「已选 2」、点「开始批量对齐」却收到「请选择 2-5 个岗位」——
 * 用户可见的选择与表单真正读取的选择是两回事。
 *
 * 修法：所有「打开面板」的路径都走 openBatchPanel()，它先把看板选择镜像进
 * 列表（看板未勾选时不动列表，避免抹掉用户在面板里的选择）。
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const MAIN = readFileSync(
  join(here, "../../src/resualign/static/app/main.js"),
  "utf8",
);

test("存在 openBatchPanel，且它先同步看板选择再展开", () => {
  const fn = MAIN.match(/function openBatchPanel\(\)[\s\S]{0,260}?\n\}/);
  assert.ok(fn, "缺少 openBatchPanel helper");
  assert.match(fn[0], /syncBatchPanelFromBoard\(\)/, "展开前必须先同步选择");
  assert.match(fn[0], /hidden = false/, "openBatchPanel 必须展开面板");
});

test("syncBatchPanelFromBoard 从 data-board-check 读到 data-batch-check", () => {
  const fn = MAIN.match(
    /function syncBatchPanelFromBoard\(\)[\s\S]{0,420}?\n\}/,
  );
  assert.ok(fn, "缺少 syncBatchPanelFromBoard helper");
  assert.match(fn[0], /\[data-board-check\]:checked/, "必须读取看板选择");
  assert.match(fn[0], /\[data-batch-check\]/, "必须写入面板列表");
  assert.match(
    fn[0],
    /selected\.size === 0\)\s*return/,
    "看板未勾选时应保持面板现状，不抹掉用户已做的选择",
  );
});

test("所有展开面板的路径都走 openBatchPanel，不再各自 hidden=false", () => {
  /* 三个入口：FAB toggle、批量对齐（batch-align-pending）、查看最近一次批次。 */
  const rawUnhide = MAIN.match(/const panel = \$\("\[data-batch-wrap\]"\);\s*\n\s*if \(panel\) panel\.hidden = false;/g) || [];
  assert.equal(
    rawUnhide.length,
    0,
    "仍有绕过 openBatchPanel 的直接展开，会漏掉选择同步",
  );
  const toggle = MAIN.match(/"toggle-batch-panel"[\s\S]{0,320}?\n  \},/);
  assert.ok(toggle, "缺少 toggle-batch-panel");
  assert.match(toggle[0], /openBatchPanel\(\)/, "toggle 打开时应走 openBatchPanel");
});
