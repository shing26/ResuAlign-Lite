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
/* U12: 薪资基准 + 投递评估权重                                          */
/* ------------------------------------------------------------------ */

/* 常用城市选项（新增薪资基准行的 datalist；城市可自由输入）。 */
export const SALARY_CITY_OPTIONS = [
  "北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京", "苏州",
  "西安", "重庆", "天津", "长沙", "郑州", "青岛", "大连", "宁波", "厦门",
  "合肥", "福州", "济南", "沈阳", "无锡", "东莞", "佛山",
];

/** datalist <option> HTML for the add-row city input. */
export function salaryCityOptions() {
  return SALARY_CITY_OPTIONS.map(
    (city) => `<option value="${escapeHtml(city)}">`,
  ).join("");
}

/** Render the editable salary-reference table rows.
 *
 * One <tr data-salary-row> per (job_function, city) with editable p50/p75
 * inputs. data-function / data-city are read back by salaryReferenceFromForm,
 * so row values round-trip without touching the backend schema.
 */
export function salaryReferenceRowsHtml(rows) {
  const list = Array.isArray(rows) ? rows : [];
  return list
    .map((row) => {
      const jobFunction = String((row && row.job_function) || "").trim();
      const city = String((row && row.city) || "").trim();
      if (!jobFunction || !city) return "";
      const p50 = row && row.p50 != null ? row.p50 : "";
      const p75 = row && row.p75 != null ? row.p75 : "";
      const label = `${jobFunction} ${city}`;
      return `<tr data-salary-row data-function="${escapeHtml(jobFunction)}" data-city="${escapeHtml(city)}">
        <td>${escapeHtml(jobFunction)}</td>
        <td>${escapeHtml(city)}</td>
        <td><input type="number" name="salary_p50" min="0" step="500" value="${escapeHtml(p50)}" aria-label="${escapeHtml(label)} p50"></td>
        <td><input type="number" name="salary_p75" min="0" step="500" value="${escapeHtml(p75)}" aria-label="${escapeHtml(label)} p75"></td>
        <td><button type="button" class="btn btn-ghost btn-sm" data-action="remove-salary-row" aria-label="删除 ${escapeHtml(label)}">删除</button></td>
      </tr>`;
    })
    .join("");
}

/** Read salary-reference rows back from the settings-salary form.
 *
 * `form` needs querySelectorAll('[data-salary-row]'); each row carries
 * data-function / data-city and input[name="salary_p50"] /
 * input[name="salary_p75"]. Non-numeric or empty cells become null so the
 * caller can surface a validation message instead of silently zeroing.
 */
export function salaryReferenceFromForm(form) {
  if (!form || typeof form.querySelectorAll !== "function") return { rows: [], invalid: [] };
  const rows = [];
  const invalid = [];
  form.querySelectorAll("[data-salary-row]").forEach((tr) => {
    const jobFunction = String(tr.dataset && tr.dataset.function || "").trim();
    const city = String(tr.dataset && tr.dataset.city || "").trim();
    if (!jobFunction || !city) return;
    const p50Raw = ((tr.querySelector('input[name="salary_p50"]') || {}).value || "").trim();
    const p75Raw = ((tr.querySelector('input[name="salary_p75"]') || {}).value || "").trim();
    const p50 = p50Raw === "" ? null : Number(p50Raw);
    const p75 = p75Raw === "" ? null : Number(p75Raw);
    if (!Number.isFinite(p50) || !Number.isFinite(p75)) {
      invalid.push({ job_function: jobFunction, city });
      rows.push({ job_function: jobFunction, city, p50, p75 });
      return;
    }
    rows.push({ job_function: jobFunction, city, p50, p75 });
  });
  return { rows, invalid };
}

/** Validate salary-reference rows before PUT. */
export function validateSalaryReference(rows) {
  const list = Array.isArray(rows) ? rows : [];
  if (!list.length) {
    return { ok: false, message: "薪资基准至少需要一行" };
  }
  for (const row of list) {
    if (!String((row && row.job_function) || "").trim() || !String((row && row.city) || "").trim()) {
      return { ok: false, message: "存在缺少职能或城市的行" };
    }
    const p50 = row && row.p50;
    const p75 = row && row.p75;
    if (!Number.isFinite(p50) || !Number.isFinite(p75) || p50 < 0 || p75 < 0) {
      return { ok: false, message: "p50 / p75 必须是大于等于 0 的数字" };
    }
  }
  return { ok: true, message: "" };
}

/** The four editable appraisal weight keys (match the backend DEFAULT_WEIGHTS). */
export const APPRAISAL_WEIGHT_KEYS = ["match", "salary", "hard_conditions", "quality"];

/** Default appraisal weights (mirror the backend DEFAULT_WEIGHTS). */
export const DEFAULT_APPRAISAL_WEIGHTS = {
  match: 40,
  salary: 30,
  hard_conditions: 20,
  quality: 10,
};

/** Backfill stored appraisal weights with defaults for the form display.
 * Older stores may only carry some keys; every missing key falls back to
 * DEFAULT_APPRAISAL_WEIGHTS so the form always shows all four inputs. */
export function normalizeAppraisalWeights(weights) {
  const source = weights && typeof weights === "object" ? weights : {};
  const out = {};
  for (const key of APPRAISAL_WEIGHT_KEYS) {
    const value = source[key];
    out[key] = value != null ? Number(value) : DEFAULT_APPRAISAL_WEIGHTS[key];
  }
  return out;
}

/** Build the appraisal_weights object for PUT /api/settings from form data
 * (weight_match / weight_salary / weight_hard_conditions / weight_quality).
 * Empty or non-numeric cells become null so validation can report them. */
export function appraisalWeightsPayload(data) {
  const weights = {};
  for (const key of APPRAISAL_WEIGHT_KEYS) {
    const raw = String((data && data[`weight_${key}`]) ?? "").trim();
    weights[key] = raw === "" ? null : Number(raw);
  }
  return weights;
}

/** Validate appraisal weights: every key numeric (>= 0) and the sum is 100. */
export function validateAppraisalWeights(weights) {
  const source = weights || {};
  const values = APPRAISAL_WEIGHT_KEYS.map((key) => source[key]);
  if (values.some((value) => value == null || !Number.isFinite(value) || value < 0)) {
    return { ok: false, message: "每个权重都必须是大于等于 0 的数字" };
  }
  const sum = values.reduce((acc, value) => acc + value, 0);
  if (Math.abs(sum - 100) > 1e-6) {
    return { ok: false, message: `权重合计必须为 100（当前为 ${sum}）` };
  }
  return { ok: true, message: "", sum };
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

