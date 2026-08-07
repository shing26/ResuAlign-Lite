import test from "node:test";
import assert from "node:assert";
import { Window } from "happy-dom";

import {
  apiKeyFieldHint,
  appraisalWeightsPayload,
  buildSettingsLlmPayload,
  buildTestConnectionPayload,
  evalDefaultFromForm,
  maskApiKey,
  normalizeAppraisalWeights,
  salaryCityOptions,
  salaryReferenceFromForm,
  salaryReferenceRowsHtml,
  testConnectionResultHtml,
  validateAppraisalWeights,
  validateSalaryReference,
} from "../../../src/resualign/static/app/settings-form.js";
import { formFromHtml } from "../dom-helpers.mjs";

/** Mirrors the real settings-llm form field names in main.js. */
function settingsLlmFormHtml(overrides = {}) {
  const provider = overrides.provider ?? "deepseek";
  const model = overrides.model ?? "";
  const apiKey = overrides.api_key ?? "";
  const baseUrl = overrides.base_url ?? "";
  return `
    <form data-form="settings-llm">
      <select name="llm_provider">
        <option value="deepseek" ${provider === "deepseek" ? "selected" : ""}>DeepSeek</option>
        <option value="openrouter" ${provider === "openrouter" ? "selected" : ""}>OpenRouter</option>
        <option value="ollama" ${provider === "ollama" ? "selected" : ""}>Ollama</option>
      </select>
      <input type="text" name="llm_model" value="${model}">
      <input type="password" name="llm_api_key" value="${apiKey}">
      <input type="text" name="llm_base_url" value="${baseUrl}">
    </form>`;
}

function formDataFrom(form) {
  // Mirror what the browser's `new FormData(form)` produces for the four
  // settings-llm fields (undici FormData rejects DOM forms in node).
  const data = {};
  for (const name of ["llm_provider", "llm_model", "llm_api_key", "llm_base_url"]) {
    const node = form.querySelector(`[name="${name}"]`);
    data[name] = node ? node.value : "";
  }
  return data;
}

test("maskApiKey hides all but the first/last four characters", () => {
  assert.equal(maskApiKey(null), null);
  assert.equal(maskApiKey(""), null);
  assert.equal(maskApiKey("abc"), "••••");
  assert.equal(maskApiKey("sk-1234567890abcd"), "sk-1••••abcd");
  assert.equal(maskApiKey("sk-1234567890abcd").includes("1234567890"), false);
});

test("buildSettingsLlmPayload sends provider/model and trims values", () => {
  const form = formFromHtml(
    settingsLlmFormHtml({ model: "  deepseek-chat  ", api_key: "  sk-abc  " }),
  );
  const llm = buildSettingsLlmPayload(formDataFrom(form));
  assert.deepEqual(llm, {
    provider: "deepseek",
    model: "deepseek-chat",
    api_key: "sk-abc",
    base_url: null,
  });
});

test("buildSettingsLlmPayload omits api_key when the field is blank", () => {
  const form = formFromHtml(settingsLlmFormHtml({ model: "m", api_key: "   " }));
  const llm = buildSettingsLlmPayload(formDataFrom(form));
  assert.equal("api_key" in llm, false);
});

test("buildSettingsLlmPayload clears model/base_url with null when blank", () => {
  const form = formFromHtml(settingsLlmFormHtml());
  const llm = buildSettingsLlmPayload(formDataFrom(form));
  assert.equal(llm.model, null);
  assert.equal(llm.base_url, null);
});

test("buildTestConnectionPayload only sends non-empty fields", () => {
  const form = formFromHtml(
    settingsLlmFormHtml({ provider: "openrouter", api_key: "sk-x" }),
  );
  const payload = buildTestConnectionPayload(formDataFrom(form));
  assert.deepEqual(payload, { provider: "openrouter", api_key: "sk-x" });
});

test("testConnectionResultHtml renders success and failure states", () => {
  const ok = testConnectionResultHtml({ ok: true, message: "连接成功" });
  assert.match(ok, /form-success/);
  assert.match(ok, /role="status"/);
  assert.match(ok, /连接成功/);

  const bad = testConnectionResultHtml({
    ok: false,
    message: "认证失败：API Key 无效",
  });
  assert.match(bad, /form-error/);
  assert.match(bad, /role="alert"/);
  assert.match(bad, /认证失败：API Key 无效/);
});

test("testConnectionResultHtml escapes provider messages", () => {
  const html = testConnectionResultHtml({
    ok: false,
    message: '<script>alert("x")</script>',
  });
  assert.equal(html.includes("<script>"), false);
  assert.match(html, /&lt;script&gt;/);
});

test("testConnectionResultHtml handles missing response", () => {
  const html = testConnectionResultHtml(undefined);
  assert.match(html, /form-error/);
  assert.match(html, /测试无响应/);
});

test("apiKeyFieldHint shows saved key or .env fallback copy", () => {
  assert.match(apiKeyFieldHint("sk-a••••1234"), /已保存 Key：sk-a••••1234/);
  assert.match(apiKeyFieldHint("sk-a••••1234"), /留空则保持不变/);
  assert.match(apiKeyFieldHint(null), /\.env 或环境变量/);
});

test("apiKeyFieldHint escapes masked key markup", () => {
  const hint = apiKeyFieldHint("<b>k</b>");
  assert.equal(hint.includes("<b>k</b>"), false);
  assert.match(hint, /&lt;b&gt;/);
});

test("settings form renders with a happy-dom Window like the real page", () => {
  const window = new Window();
  const document = window.document;
  document.body.innerHTML = settingsLlmFormHtml({
    provider: "ollama",
    model: "llama3",
  });
  const form = document.querySelector("[data-form='settings-llm']");
  const options = [...form.querySelectorAll('[name="llm_provider"] option')].map(
    (option) => option.value,
  );
  assert.deepEqual(options, ["deepseek", "openrouter", "ollama"]);
  assert.equal(form.querySelector('[name="llm_model"]').value, "llama3");
  // Value assignment round-trips through the form the same way the real
  // page reads it on submit (selection state itself is browser-parsed).
  const select = form.querySelector('[name="llm_provider"]');
  select.value = "ollama";
  assert.equal(select.value, "ollama");
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

/* ------------------------------------------------------------------ */
/* U12: 薪资基准表格（渲染 / 解析 / 校验）                               */
/* ------------------------------------------------------------------ */

function salaryFormHtml(rows) {
  return `<form data-form="settings-salary">
    <table><tbody data-salary-rows>${salaryReferenceRowsHtml(rows)}</tbody></table>
  </form>`;
}

const SALARY_ROWS = [
  { job_function: "后端", city: "北京", p50: 32000, p75: 48000 },
  { job_function: "前端", city: "上海", p50: 27000, p75: 40000 },
];

test("salaryReferenceRowsHtml renders editable rows with data attrs", () => {
  const html = salaryReferenceRowsHtml(SALARY_ROWS);
  assert.match(html, /data-salary-row data-function="后端" data-city="北京"/);
  assert.match(html, /data-salary-row data-function="前端" data-city="上海"/);
  assert.match(html, /name="salary_p50" min="0" step="500" value="32000"/);
  assert.match(html, /name="salary_p75" min="0" step="500" value="40000"/);
  assert.match(html, /data-action="remove-salary-row"/);
  assert.equal(salaryReferenceRowsHtml([]), "");
  assert.equal(salaryReferenceRowsHtml(null), "");
});

test("salaryReferenceRowsHtml escapes function/city values", () => {
  const html = salaryReferenceRowsHtml([
    { job_function: '<script>', city: '"x"', p50: 1, p75: 2 },
  ]);
  assert.equal(html.includes("<script>"), false);
  assert.match(html, /&lt;script&gt;/);
});

test("salaryReferenceFromForm round-trips editable rows", () => {
  const form = formFromHtml(salaryFormHtml(SALARY_ROWS));
  const { rows, invalid } = salaryReferenceFromForm(form);
  assert.equal(invalid.length, 0);
  assert.deepEqual(rows, SALARY_ROWS);
});

test("salaryReferenceFromForm flags empty and non-numeric cells", () => {
  const form = formFromHtml(`
    <form data-form="settings-salary">
      <table><tbody data-salary-rows>
        <tr data-salary-row data-function="后端" data-city="北京">
          <td>后端</td><td>北京</td>
          <td><input name="salary_p50" value=""></td>
          <td><input name="salary_p75" value="abc"></td>
        </tr>
      </tbody></table>
    </form>`);
  const { rows, invalid } = salaryReferenceFromForm(form);
  assert.equal(rows.length, 1);
  assert.equal(invalid.length, 1);
  assert.deepEqual(invalid[0], { job_function: "后端", city: "北京" });
});

test("salaryReferenceFromForm tolerates a null form", () => {
  const { rows, invalid } = salaryReferenceFromForm(null);
  assert.deepEqual(rows, []);
  assert.deepEqual(invalid, []);
});

test("validateSalaryReference accepts valid rows and rejects bad input", () => {
  assert.equal(validateSalaryReference(SALARY_ROWS).ok, true);
  assert.equal(validateSalaryReference([]).ok, false);
  assert.equal(validateSalaryReference(null).ok, false);
  assert.equal(
    validateSalaryReference([
      { job_function: "后端", city: "北京", p50: "x", p75: 2 },
    ]).ok,
    false,
  );
  assert.equal(
    validateSalaryReference([
      { job_function: "", city: "北京", p50: 1, p75: 2 },
    ]).ok,
    false,
  );
  assert.equal(
    validateSalaryReference([
      { job_function: "后端", city: "北京", p50: -5, p75: 2 },
    ]).ok,
    false,
  );
});

test("salaryCityOptions renders datalist options for common cities", () => {
  const html = salaryCityOptions();
  assert.match(html, /<option value="北京">/);
  assert.match(html, /<option value="杭州">/);
  assert.equal((html.match(/<option value="/g) || []).length > 10, true);
});

/* ------------------------------------------------------------------ */
/* U12: 投递评估权重（载荷构建 / 校验）                                  */
/* ------------------------------------------------------------------ */

function weightsFormHtml(weights) {
  return `<form data-form="settings-weights">
    <input type="number" name="weight_match" value="${weights.match}">
    <input type="number" name="weight_salary" value="${weights.salary}">
    <input type="number" name="weight_hard_conditions" value="${weights.hard_conditions}">
    <input type="number" name="weight_quality" value="${weights.quality}">
  </form>`;
}

function weightsDataFrom(form) {
  const data = {};
  for (const key of [
    "weight_match",
    "weight_salary",
    "weight_hard_conditions",
    "weight_quality",
  ]) {
    const node = form.querySelector(`[name="${key}"]`);
    data[key] = node ? node.value : "";
  }
  return data;
}

test("appraisalWeightsPayload maps weight_* fields to backend keys", () => {
  assert.deepEqual(
    appraisalWeightsPayload({
      weight_match: "40",
      weight_salary: "30",
      weight_hard_conditions: "20",
      weight_quality: "10",
    }),
    { match: 40, salary: 30, hard_conditions: 20, quality: 10 },
  );
});

test("normalizeAppraisalWeights backfills missing keys with defaults", () => {
  assert.deepEqual(
    normalizeAppraisalWeights({ match: 60 }),
    { match: 60, salary: 30, hard_conditions: 20, quality: 10 },
  );
  assert.deepEqual(
    normalizeAppraisalWeights(null),
    { match: 40, salary: 30, hard_conditions: 20, quality: 10 },
  );
  assert.deepEqual(
    normalizeAppraisalWeights({ match: "45", salary: "25", hard_conditions: "20", quality: "10" }),
    { match: 45, salary: 25, hard_conditions: 20, quality: 10 },
  );
});

test("appraisalWeightsPayload nulls empty and missing cells", () => {
  assert.deepEqual(appraisalWeightsPayload({}), {
    match: null,
    salary: null,
    hard_conditions: null,
    quality: null,
  });
  assert.deepEqual(
    appraisalWeightsPayload({
      weight_match: "40",
      weight_salary: "",
      weight_hard_conditions: "  ",
      weight_quality: "abc",
    }),
    { match: 40, salary: null, hard_conditions: null, quality: Number("abc") },
  );
});

test("weights form round-trips through appraisalWeightsPayload", () => {
  const form = formFromHtml(
    weightsFormHtml({ match: 40, salary: 30, hard_conditions: 20, quality: 10 }),
  );
  assert.deepEqual(appraisalWeightsPayload(weightsDataFrom(form)), {
    match: 40,
    salary: 30,
    hard_conditions: 20,
    quality: 10,
  });
});

test("validateAppraisalWeights requires numbers summing to 100", () => {
  assert.equal(
    validateAppraisalWeights({ match: 40, salary: 30, hard_conditions: 20, quality: 10 }).ok,
    true,
  );
  const wrongSum = validateAppraisalWeights({
    match: 50,
    salary: 30,
    hard_conditions: 20,
    quality: 10,
  });
  assert.equal(wrongSum.ok, false);
  assert.match(wrongSum.message, /100/);
  const nonNumeric = validateAppraisalWeights({
    match: null,
    salary: 30,
    hard_conditions: 20,
    quality: 10,
  });
  assert.equal(nonNumeric.ok, false);
  assert.equal(validateAppraisalWeights(null).ok, false);
  const negative = validateAppraisalWeights({
    match: -1,
    salary: 30,
    hard_conditions: 20,
    quality: 51,
  });
  assert.equal(negative.ok, false);
});
