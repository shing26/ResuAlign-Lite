import test from "node:test";
import assert from "node:assert";
import { formFromHtml } from "../dom-helpers.mjs";

import {
  buildCostGuardPayload,
  evalDefaultFromForm,
  maskApiKey,
  validateCostGuardPayload,
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

test("cost guard form fields map to a numeric/null settings payload", () => {
  const form = formFromHtml(`
    <form data-form="settings-cost-guard">
      <input type="number" name="daily_llm_cap" value="10">
      <input type="number" name="llm_cost_per_1k_in" value="0.5">
      <input type="number" name="llm_cost_per_1k_out" value="">
    </form>`);
  const data = {};
  for (const name of [
    "daily_llm_cap",
    "llm_cost_per_1k_in",
    "llm_cost_per_1k_out",
  ]) {
    const node = form.querySelector(`[name="${name}"]`);
    data[name] = node ? node.value : "";
  }
  const payload = buildCostGuardPayload(data);
  assert.deepEqual(payload, {
    daily_llm_cap: 10,
    llm_cost_per_1k_in: 0.5,
    llm_cost_per_1k_out: null,
  });
  assert.equal(validateCostGuardPayload(payload).ok, true);
});
