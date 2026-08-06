/* Settings page pure helpers.
 *
 * Kept DOM-free so the settings form logic (masking, payload building,
 * test-result rendering) is unit-testable in node/happy-dom without
 * importing main.js. main.js imports these functions for the LLM form.
 */

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch],
  );
}

/** Mask a saved API key for display: sk-abc1234 -> sk-a••••1234. */
export function maskApiKey(apiKey) {
  if (!apiKey) return null;
  if (apiKey.length <= 8) return "••••";
  return `${apiKey.slice(0, 4)}••••${apiKey.slice(-4)}`;
}

/** Build the PUT /api/settings llm payload from settings-form field data.
 *
 * - provider/model are sent as typed (empty model clears the stored model)
 * - api_key is sent only when non-empty, so a blank field keeps the stored
 *   key instead of wiping it
 * - base_url is sent as typed; empty clears the stored override
 */
export function buildSettingsLlmPayload(data) {
  const llm = { provider: data.llm_provider || null };
  llm.model = (data.llm_model || "").trim() || null;
  if ((data.llm_api_key || "").trim()) {
    llm.api_key = data.llm_api_key.trim();
  }
  llm.base_url = (data.llm_base_url || "").trim() || null;
  return llm;
}

/** Build the POST /api/settings/test-connection payload from form data.
 *
 * Only non-empty fields are sent; empty fields fall back to the persisted
 * store / .env server-side, mirroring the real pipeline resolution.
 */
export function buildTestConnectionPayload(data) {
  const payload = {};
  if (data.llm_provider) payload.provider = data.llm_provider;
  if ((data.llm_model || "").trim()) payload.model = data.llm_model.trim();
  if ((data.llm_api_key || "").trim()) payload.api_key = data.llm_api_key.trim();
  if ((data.llm_base_url || "").trim()) payload.base_url = data.llm_base_url.trim();
  return payload;
}

/** Render the test-connection result into an accessible status block. */
export function testConnectionResultHtml(body) {
  if (!body || typeof body.ok !== "boolean") {
    return '<div class="form-error" role="alert">测试无响应，请稍后重试</div>';
  }
  const cls = body.ok ? "form-success" : "form-error";
  const role = body.ok ? "status" : "alert";
  return `<div class="${cls}" role="${role}">${escapeHtml(body.message || "")}</div>`;
}

/** Hint text under the API key field showing what the backend will use. */
export function apiKeyFieldHint(savedMaskedKey) {
  return savedMaskedKey
    ? `已保存 Key：${escapeHtml(savedMaskedKey)}；留空则保持不变。`
    : "未保存 Key：将使用 .env 或环境变量中的配置。";
}
