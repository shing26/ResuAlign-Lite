/* #146: 导入 / 岗位表同步的跳过明细必须真的渲染到界面上。
 *
 * 后端早就逐行返回 errors，前端只渲染计数，于是「6 行已在库中」与
 * 「6 个真实岗位被丢弃」在界面上完全同形，#145 的数据丢失因此隐形。
 */
import test from "node:test";
import assert from "node:assert";

import {
  classifySkipMessages,
  skipDetailHtml,
} from "../../src/resualign/static/app/skip-detail.js";

const DUPLICATE = "AI 实习生 - 后端开发: Duplicate job already exists";
const MISSING_JD =
  "数分实习生: 缺少 JD 正文（WorkBuddy 补齐后会自动导入）";

test("a re-import reports only duplicates and stays collapsed", () => {
  const { routine, notable } = classifySkipMessages([DUPLICATE, DUPLICATE]);
  assert.equal(routine.length, 2);
  assert.equal(notable.length, 0);

  const html = skipDetailHtml([DUPLICATE]);
  assert.match(html, /<details class="skip-detail__group">/);
  assert.match(html, /1 条已跳过（已在库中）/);
  assert.doesNotMatch(html, /skip-detail__group--warn/);
});

test("rows that did not land are surfaced in the open, not folded away", () => {
  const { routine, notable } = classifySkipMessages([DUPLICATE, MISSING_JD]);
  assert.equal(routine.length, 1);
  assert.equal(notable.length, 1);

  const html = skipDetailHtml([DUPLICATE, MISSING_JD]);
  assert.match(html, /skip-detail__group--warn/);
  assert.match(html, /1 条需要留意/);
  // The warn group is not a <details>, so it cannot start collapsed.
  assert.match(html, /<div class="skip-detail__group skip-detail__group--warn">/);
  assert.match(html, /数分实习生/);
});

test("every skipped row is named, so none can vanish silently", () => {
  const messages = [DUPLICATE, MISSING_JD, "Java 开发实习生: LLMResponseError: timeout"];
  const html = skipDetailHtml(messages);
  for (const message of messages) {
    assert.ok(html.includes(message.split(":")[0]), `缺少 ${message}`);
  }
  assert.match(html, /LLMResponseError/);
});

test("empty and blank input render nothing at all", () => {
  assert.equal(skipDetailHtml([]), "");
  assert.equal(skipDetailHtml(null), "");
  assert.equal(skipDetailHtml(undefined), "");
  assert.equal(skipDetailHtml(["", "   ", null]), "");
});

test("row titles are escaped, not injected as markup", () => {
  const html = skipDetailHtml(["<img src=x onerror=alert(1)>: boom"]);
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
});

