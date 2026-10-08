/* 批量对齐面板：必须有面板自带的关闭入口，且作用域选择器不能是死类。
 *
 * 背景（实测复现，2026-10-08）：岗位库工具栏的「批量对齐」点下去后，面板
 * 展开、批次已排队，但面板里没有任何关闭/返回入口 —— 唯一能收起它的
 * toggle 按钮挂在 FAB 上，而 FAB 只在「已选 >0」时显示
 * （main.js updateBatchSelection）。取消勾选或批次跑完后 FAB 消失，
 * 面板仍可见 → 用户被困在面板里。
 *
 * 同一次复现还暴露了放大器：styles.css 用 `.batch-panel .batch-job-list`
 * 给岗位列表加 max-height/overflow，但元素的实际类名是 `batch-panel-wrap`
 * —— 选择器从未命中，155 个岗位把面板撑到首屏之外，连「开始批量对齐」
 * 都在折叠线以下。两条断言分别钉住这两个面。
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { batchPanelHtml } from "../../src/resualign/static/app/format.js";

const here = dirname(fileURLToPath(import.meta.url));
const read = (p) => readFileSync(join(here, p), "utf8");

const MAIN = read("../../src/resualign/static/app/main.js");
const STYLES = read("../../src/resualign/static/styles.css");

const JOBS = [
  { job_id: "j1", title: "后端工程师", company: "某公司" },
  { job_id: "j2", title: "前端工程师", company: "某公司" },
];
const RESUMES = [{ resume_id: "r1", title: "主简历", current_version: 1 }];

test("批量对齐面板自带关闭入口（不依赖 FAB 的选择状态）", () => {
  const html = batchPanelHtml(JOBS, RESUMES);
  assert.match(
    html,
    /data-action="close-batch-panel"/,
    "面板必须提供一个 data-action=close-batch-panel 的关闭/返回入口",
  );
  /* 关闭入口要在 panel-head 里（首屏可见），不能塞在会被长列表推下去的位置。 */
  const head = html.match(/<div class="panel-head">[\s\S]*?<\/div>\s*<\/div>/);
  assert.ok(head, "面板缺少 panel-head 结构");
  assert.match(
    head[0],
    /close-batch-panel/,
    "关闭入口必须位于 panel-head 内，否则会被岗位列表顶出首屏",
  );
});

test("close-batch-panel 动作已接线", () => {
  assert.match(
    MAIN,
    /"close-batch-panel"\s*:/,
    "main.js 的 actions 表里必须有 close-batch-panel",
  );
});

test("面板作用域选择器不是死类（.batch-job-list 的高度约束真的命中）", () => {
  /* 取出 main.js 里给包裹层设置的 className，逐类断言 CSS 用的是其中之一。 */
  const className = MAIN.match(/wrap\.className\s*=\s*"([^"]+)"/);
  assert.ok(className, "未找到批量面板包裹层的 className 赋值");
  const classes = className[1].split(/\s+/).filter(Boolean);
  assert.ok(classes.includes("batch-panel-wrap"), "包裹层类名应为 batch-panel-wrap");

  const scoped = STYLES.match(/\.(batch-[\w-]+)\s+\.batch-job-list\s*\{/g) || [];
  assert.ok(scoped.length > 0, "styles.css 缺少 .batch-job-list 的作用域规则");
  for (const rule of scoped) {
    const cls = rule.match(/\.(batch-[\w-]+)/)[1];
    assert.ok(
      classes.includes(cls),
      `styles.css 用了 .${cls} 作用域，但包裹层实际类名是 [${classes.join(", ")}] —— 死选择器，高度约束不会生效`,
    );
  }
});
