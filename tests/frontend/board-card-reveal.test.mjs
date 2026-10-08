/* 岗位卡详情展开：必须由显式动作驱动，不得由 hover/focus 改变卡片高度。
 *
 * 背景（实测复现，2026-10-08）：`.board-card__reveal` 原本在
 * `.board-card:hover` / `:focus-within` 时 display:none → flex，卡片长高
 * 约 187px，把同列**下方所有卡片整体下推**。鼠标从一张卡移向下一张时，
 * 上一张收回、下一张上跳，落点已经不在复选框上 —— 事件日志显示点击命中
 * `ARTICLE.board-card` 而非 `INPUT`，多选复选框频繁点不中。
 *
 * 修法：展开只认 `[data-revealed="true"]`（由卡头 chevron 按钮切换），
 * hover 仅做视觉强调。这里锁死三条：选择器不含 hover/focus、卡片有切换
 * 入口、动作已接线。
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { boardCard } from "../../src/resualign/static/app/format.js";

const here = dirname(fileURLToPath(import.meta.url));
const read = (p) => readFileSync(join(here, p), "utf8");

const STYLES = read("../../src/resualign/static/styles.css").replace(
  /\/\*[\s\S]*?\*\//g,
  "",
);
const MAIN = read("../../src/resualign/static/app/main.js");

test("详情展开规则只认 data-revealed，不含 hover/focus-within", () => {
  const rule = STYLES.match(
    /[^{}]*\.board-card__reveal\s*\{[^}]*display:\s*flex[^}]*\}/,
  );
  assert.ok(rule, "未找到 .board-card__reveal 的展开规则");
  const selector = rule[0].slice(0, rule[0].indexOf("{"));
  assert.match(
    selector,
    /\[data-revealed="true"\]/,
    "展开必须由 data-revealed 驱动",
  );
  assert.doesNotMatch(
    selector,
    /:hover/,
    "hover 展开会把同列下方卡片整体下推，指针目标在移动中跳动（F2）",
  );
  assert.doesNotMatch(
    selector,
    /:focus-within/,
    "focus-within 同样在点击复选框时触发位移（F2）",
  );
});

test("岗位卡有显式展开入口，且默认收起", () => {
  const html = boardCard({
    job_id: "j1",
    title: "后端工程师",
    company: "某公司",
    status: "draft",
  });
  assert.match(
    html,
    /data-action="toggle-card-reveal"/,
    "岗位卡必须提供显式展开入口",
  );
  assert.match(html, /aria-expanded="false"/, "展开入口默认应为收起态");
  assert.match(html, /class="board-card__reveal"/, "详情区仍应存在");
});

test("toggle-card-reveal 动作已接线并切换 data-revealed", () => {
  const idx = MAIN.indexOf('"toggle-card-reveal"');
  assert.ok(idx > -1, "main.js 的 actions 表里必须有 toggle-card-reveal");
  const chunk = MAIN.slice(idx, idx + 600);
  assert.match(chunk, /data-revealed/, "动作必须切换 data-revealed");
  assert.match(chunk, /closest\("\.board-card"\)/, "动作必须作用于所属卡片");
});
