import test from "node:test";
import assert from "node:assert";

import {
  evalDefaultFromForm,
  maskApiKey,
} from "../../../src/resualign/static/app/settings-form.js";

test("maskApiKey hides all but the first/last four characters", () => {
  assert.equal(maskApiKey(null), null);
  assert.equal(maskApiKey(""), null);
  assert.equal(maskApiKey("abc"), "••••");
  assert.equal(maskApiKey("sk-1234567890abcd"), "sk-1••••abcd");
  assert.equal(maskApiKey("sk-1234567890abcd").includes("1234567890"), false);
});

/* F1: 设置页「对齐评估」默认开关 —— 未勾选时浏览器 FormData 不含该字段，
 * 必须显式持久化 false；勾选时持久化 true。 */
test("evalDefaultFromForm maps checked to true and unchecked to false", () => {
  assert.equal(evalDefaultFromForm({ eval_default: "on" }), true);
  assert.equal(evalDefaultFromForm({ eval_default: true }), true);
  assert.equal(evalDefaultFromForm({}), false);
  assert.equal(evalDefaultFromForm({ eval_default: "off" }), false);
  assert.equal(evalDefaultFromForm(null), false);
});

