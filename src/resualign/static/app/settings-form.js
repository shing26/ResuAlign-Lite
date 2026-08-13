/* Settings page pure helpers.
 *
 * Kept DOM-free so the settings form logic (masking, payload building,
 * test-result rendering) is unit-testable in node/happy-dom without
 * importing main.js. main.js imports these functions for the LLM form.
 * The U12 salary-table helpers accept a happy-dom (or real) <form> that
 * supports querySelectorAll, so parsing stays testable in node.
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

/** Build the eval_default boolean for PUT /api/settings.
 *
 * The global default must always be persisted explicitly: false when the
 * checkbox is unchecked (browser FormData omits it), true when checked.
 */
export function evalDefaultFromForm(data) {
  const value = data && data.eval_default;
  return value === "on" || value === true;
}

/* ------------------------------------------------------------------ */
/* Sprint 5: LLM 节点 + 自动化规则表单（纯函数）                          */
/* ------------------------------------------------------------------ */
/* 与 format.js 的 llmNodeFormHtml / ruleFormHtml 配套：main.js 在表单
 * submit 时读取字段，经本模块构建 payload 并校验后再调 API。 */

/** Build the POST/PUT /api/llm/nodes payload from the node form data.
 *
 * - name / provider / model 按 trim 后原样发送（必填，由校验兜底）
 * - base_url 空白转 null（清除已存覆盖）
 * - api_key 仅在非空时发送：编辑时留空保留后端已存 key（掩码不回传）
 */
export function buildLlmNodePayload(data) {
  const source = data || {};
  const payload = {
    name: String(source.node_name || "").trim(),
    provider: String(source.node_provider || "").trim(),
    model: String(source.node_model || "").trim(),
    base_url: String(source.node_base_url || "").trim() || null,
  };
  const apiKey = String(source.node_api_key || "").trim();
  if (apiKey) payload.api_key = apiKey;
  return payload;
}

/** Validate a built LLM node payload before POST/PUT.
 *
 * - name / provider / model 必填
 * - 新增（isEdit=false）时 api_key 必填，除非 provider 为 ollama（本地服务）
 */
export function validateLlmNodePayload(payload, options = {}) {
  const opts = options || {};
  if (!String((payload && payload.name) || "").trim()) {
    return { ok: false, message: "请填写节点名称" };
  }
  if (!String((payload && payload.provider) || "").trim()) {
    return { ok: false, message: "请选择服务商" };
  }
  if (!String((payload && payload.model) || "").trim()) {
    return { ok: false, message: "请填写模型名称" };
  }
  if (
    !opts.isEdit &&
    !String((payload && payload.api_key) || "").trim() &&
    String((payload && payload.provider) || "") !== "ollama"
  ) {
    return { ok: false, message: "请填写 API Key（Ollama 本地服务可留空）" };
  }
  return { ok: true, message: "" };
}

/** Build the POST /api/automation/rules payload from the rule form data.
 *  label 为空时不发送（后端存 NULL）；enabled 恒为 true（新增即启用）。 */
export function buildAutomationRulePayload(data) {
  const source = data || {};
  const value = String(source.rule_value || "").trim();
  const label = String(source.rule_label || "").trim();
  const payload = {
    rule_type: String(source.rule_type || "").trim() || "blacklist",
    value,
    enabled: true,
  };
  if (label) payload.label = label;
  return payload;
}

/** Validate an automation rule payload. min_salary 的值必须是正数
 *  （单位千元/月，与后端 _validate_min_salary_value 语义一致）。 */
export function validateAutomationRule(payload) {
  const source = payload || {};
  if (!String(source.value || "").trim()) {
    return { ok: false, message: "请填写规则值" };
  }
  if (String(source.rule_type || "") === "min_salary") {
    const amount = Number(source.value);
    if (!Number.isFinite(amount) || amount <= 0) {
      return { ok: false, message: "最低薪资规则的值必须是大于 0 的数字（单位：千元/月）" };
    }
  }
  return { ok: true, message: "" };
}
