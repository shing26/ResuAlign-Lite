/* 多选复选框的指针目标不得小于 24px（WCAG 2.2 SC 2.5.8）。
 *
 * 背景（实测，2026-10-08）：`.board-check` 只有 `display:inline-flex`，
 * 未给 input/span 任何尺寸，标签盒等于浏览器默认复选框的约 13×13px。
 * 它是「批量对比 / 批量对齐」的唯一入口，却比周围任何控件都小。
 *
 * 修法：label 撑到 24px（触摸 32px），视觉尺寸不变 —— 只扩大热区。
 * 这里锁住最小尺寸，防止后续样式整理把它改回去。
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const STYLES = readFileSync(
  join(here, "../../src/resualign/static/styles.css"),
  "utf8",
).replace(/\/\*[\s\S]*?\*\//g, "");

const MIN_TARGET_PX = 24;

function boardCheckRule() {
  const rule = STYLES.match(/(?:^|\})\s*(\.board-check)\s*\{[^}]*\}/);
  assert.ok(rule, "未找到 .board-check 规则");
  return rule[0];
}

test(".board-check 的指针目标 ≥24px", () => {
  const rule = boardCheckRule();
  for (const prop of ["min-width", "min-height"]) {
    const m = rule.match(new RegExp(`${prop}\\s*:\\s*(\\d+(?:\\.\\d+)?)px`));
    assert.ok(m, `.board-check 缺少 ${prop}（热区会退回默认的约 13px）`);
    assert.ok(
      Number(m[1]) >= MIN_TARGET_PX,
      `${prop}=${m[1]}px 小于 WCAG 2.2 要求的 ${MIN_TARGET_PX}px`,
    );
  }
});

test("触摸设备（hover: none）热区再放宽一档", () => {
  const m = STYLES.match(
    /@media\s*\(hover:\s*none\)\s*\{[\s\S]{0,200}?\.board-check\s*\{[^}]*\}/,
  );
  assert.ok(m, "缺少 hover:none 下的 .board-check 尺寸放宽规则");
  const w = m[0].match(/min-width\s*:\s*(\d+(?:\.\d+)?)px/);
  assert.ok(w, "hover:none 分支缺少 min-width");
  assert.ok(
    Number(w[1]) > MIN_TARGET_PX,
    "触摸设备没有 hover 纠错机会，热区应大于桌面档",
  );
});
