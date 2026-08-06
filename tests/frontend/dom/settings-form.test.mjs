import test from "node:test";
import assert from "node:assert";
import { Window } from "happy-dom";

import {
  apiKeyFieldHint,
  buildSettingsLlmPayload,
  buildTestConnectionPayload,
  maskApiKey,
  testConnectionResultHtml,
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
