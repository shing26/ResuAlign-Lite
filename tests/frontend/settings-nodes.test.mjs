import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { Window } from "happy-dom";

import {
  automationRuleTypeLabel,
  llmNodeCardHtml,
  llmNodeFormHtml,
  nodeTestResultHtml,
  roleTimeoutSummary,
  ruleFormHtml,
  ruleListHtml,
  settingsBentoHtml,
  settingsModeSwitchHtml,
  simpleLlmSetupHtml,
} from "../../src/resualign/static/app/format.js";
import {
  buildAutomationRulePayload,
  buildLlmNodePayload,
  validateAutomationRule,
  validateLlmNodePayload,
} from "../../src/resualign/static/app/settings-form.js";

/* Parse a rendered HTML string and return its body element, so the DOM
 * structure produced by the pure builders can be asserted exactly like
 * the real page would behave after main.js mounts them into #app. */
function bodyFrom(html) {
  const window = new Window();
  window.document.body.innerHTML = html;
  return window.document.body;
}

/* ------------------------------------------------------------------ */
/* settingsBentoHtml: Sprint 5 T1 概览卡                                */
/* ------------------------------------------------------------------ */

test("settingsBentoHtml renders four bento cards with defaults when empty", () => {
  const body = bodyFrom(settingsBentoHtml(null, null));
  const cards = [...body.querySelectorAll(".settings-bento__card")];
  assert.equal(cards.length, 4);

  const labels = cards.map((card) => card.querySelector(".settings-bento__label").textContent);
  assert.deepEqual(labels, ["活跃模型 ID", "架构模式", "超时护栏", "API 延迟"]);

  assert.equal(body.querySelector("[data-bento-model] .settings-bento__value").textContent, "—");
  assert.equal(body.querySelector("[data-bento-arch] .settings-bento__value").textContent, "本地 SQLite");
  assert.equal(body.querySelector("[data-bento-timeout] .settings-bento__value").textContent, "45–90 秒");
  assert.equal(body.querySelector("[data-bento-timeout] .settings-bento__hint").textContent, "按角色 · 并发: 1");
  assert.equal(body.querySelector("[data-bento-latency] .settings-bento__value").textContent, "—");
});

test("settingsBentoHtml shows active node, timeout guardrails and latency", () => {
  const node = { node_id: "n1", name: "主节点", provider: "deepseek", model: "deepseek-chat", is_active: true };
  const body = bodyFrom(settingsBentoHtml(node, 123));
  assert.equal(
    body.querySelector("[data-bento-model] .settings-bento__value").textContent,
    "deepseek · deepseek-chat",
  );
  assert.equal(body.querySelector("[data-bento-timeout] .settings-bento__value").textContent, "45–90 秒");
  assert.equal(body.querySelector("[data-bento-timeout] .settings-bento__hint").textContent, "按角色 · 并发: 1");
  assert.equal(body.querySelector("[data-bento-latency] .settings-bento__value").textContent, "123 ms");
});

test("settingsBentoHtml tolerates missing / non-array-ish counts", () => {
  const body = bodyFrom(settingsBentoHtml(null, null));
  assert.equal(body.querySelector("[data-bento-timeout] .settings-bento__value").textContent, "45–90 秒");
  const body2 = bodyFrom(settingsBentoHtml(null, "abc"));
  assert.equal(body2.querySelector("[data-bento-timeout] .settings-bento__value").textContent, "45–90 秒");
  assert.equal(body2.querySelector("[data-bento-latency] .settings-bento__value").textContent, "—");
});

test("settingsBentoHtml shows the runtime values the backend enforces", () => {
  const runtime = {
    worker_concurrency: 3,
    role_timeouts: { diagnose: 50, profiler: 80, editor: 100 },
  };
  const body = bodyFrom(settingsBentoHtml(null, null, runtime));
  assert.equal(body.querySelector("[data-bento-timeout] .settings-bento__value").textContent, "50–100 秒");
  assert.equal(body.querySelector("[data-bento-timeout] .settings-bento__hint").textContent, "按角色 · 并发: 3");
});

test("roleTimeoutSummary collapses a single value and rejects junk", () => {
  assert.equal(roleTimeoutSummary({ editor: 90 }), "90 秒");
  assert.equal(roleTimeoutSummary({}), "—");
  assert.equal(roleTimeoutSummary({ editor: "abc" }), "—");
  assert.equal(roleTimeoutSummary(null), "45–90 秒");
});

test("settingsBentoHtml escapes model/provider values", () => {
  const node = { node_id: "n1", provider: '<img src=x onerror=1>', model: "<b>x</b>", is_active: true };
  const body = bodyFrom(settingsBentoHtml(node, {}, null));
  assert.equal(body.querySelectorAll("img, b").length, 0);
  const value = body.querySelector("[data-bento-model] .settings-bento__value");
  assert.equal(value.textContent, '<img src=x onerror=1> · <b>x</b>');
});

/* ------------------------------------------------------------------ */
/* llmNodeCardHtml: Sprint 5 T2 节点卡                                  */
/* ------------------------------------------------------------------ */

const NODE = {
  node_id: "n1",
  name: "主 DeepSeek 节点",
  provider: "deepseek",
  model: "deepseek-chat",
  base_url: "https://api.deepseek.com/v1",
  api_key: "sk-1234567890abcd",
  is_active: true,
};

/* Base URL 自动识别：服务商下拉的完整清单（顺序即下拉渲染顺序）。 */
const EXPECTED_PROVIDERS = [
  "auto",
  "openai",
  "deepseek",
  "openrouter",
  "ollama",
  "nvidia",
  "siliconflow",
  "moonshot",
  "zhipu",
  "dashscope",
  "volcengine",
  "groq",
  "mistral",
  "together",
  "fireworks",
  "xai",
  "custom",
];

/* happy-dom 不解析 <option selected> 的默认选中项，纯 HTML 构建器只对
 * 正确的 option 打上 selected 属性——直接断言该属性更贴近真实契约。 */
function selectedProvider(form) {
  const option = form.querySelector('select[name="node_provider"] option[selected]');
  return option ? option.value : null;
}

test("llmNodeCardHtml renders active badge, masked key and test button", () => {
  const body = bodyFrom(llmNodeCardHtml(NODE, null));
  const card = body.querySelector("[data-llm-node-card]");
  assert.ok(card, "node card is rendered");
  assert.equal(card.dataset.nodeId, "n1");

  assert.ok(card.querySelector("[data-node-active-badge]"));
  assert.equal(card.querySelector("[data-node-active-badge]").textContent, "当前生效");
  assert.equal(card.querySelector(".llm-node-card__title").textContent, "主 DeepSeek 节点");
  assert.equal(card.querySelector('[data-action="llm-node-test"][data-id="n1"]').textContent, "测试连通性");
  assert.equal(card.querySelector('[data-action="llm-node-edit"][data-id="n1"]').textContent, "编辑");
  assert.equal(card.querySelector('[data-action="llm-node-delete"][data-id="n1"]').textContent, "删除");

  const key = card.querySelector(".llm-node-card__key").textContent;
  assert.ok(key.startsWith("sk-1"), "masked key keeps the first four chars");
  assert.ok(key.endsWith("abcd"), "masked key keeps the last four chars");
  assert.equal(key.includes("1234567890"), false, "middle of the key is hidden");
});

test("llmNodeCardHtml omits activate button for the active node", () => {
  const body = bodyFrom(llmNodeCardHtml(NODE, null));
  assert.equal(body.querySelectorAll('[data-action="llm-node-activate"]').length, 0);
});

test("llmNodeCardHtml shows activate button for inactive nodes and no active badge", () => {
  const inactive = { ...NODE, is_active: false };
  const body = bodyFrom(llmNodeCardHtml(inactive, null));
  const card = body.querySelector("[data-llm-node-card]");
  assert.ok(!card.querySelector("[data-node-active-badge]"));
  assert.ok(card.querySelector('[data-action="llm-node-activate"][data-id="n1"]'));
});

test("llmNodeCardHtml renders the last test result on the card", () => {
  const body = bodyFrom(
    llmNodeCardHtml(NODE, { ok: true, status: 200, latency_ms: 88, message: "连接成功" }),
  );
  const result = body.querySelector("[data-llm-node-test]");
  assert.ok(result);
  assert.match(result.textContent, /HTTP 200/);
  assert.match(result.textContent, /88 ms/);
  assert.match(result.textContent, /连接成功/);
});

test("llmNodeCardHtml shows auto-disabled badge (ticket #103) and suppresses stale health badge", () => {
  const body = bodyFrom(
    llmNodeCardHtml(
      { ...NODE, auto_disabled: true, consecutive_failures: 3, last_test_status: "timeout" },
      null,
    ),
  );
  const disabled = body.querySelector("[data-node-auto-disabled]");
  assert.ok(disabled, "auto-disabled badge rendered");
  assert.match(disabled.textContent, /已自动禁用/);
  assert.match(disabled.textContent, /连续失败 3 次/);
  assert.match(disabled.title, /测试连通性/);
  // The ambiguous "上次异常" health badge must yield to the breaker badge.
  assert.equal(body.querySelector(".badge-red"), null);
});

test("llmNodeCardHtml shows no breaker badge for a healthy node", () => {
  const body = bodyFrom(
    llmNodeCardHtml({ ...NODE, auto_disabled: false, consecutive_failures: 0 }, null),
  );
  assert.equal(body.querySelector("[data-node-auto-disabled]"), null);
});

test("llmNodeCardHtml escapes name / provider / model / base_url", () => {
  const hostile = {
    node_id: 'n<script>',
    name: '<b>节点</b>',
    provider: '<i>p</i>',
    model: '<u>m</u>',
    base_url: 'https://x/?q=<script>',
    api_key: null,
    is_active: false,
  };
  const body = bodyFrom(llmNodeCardHtml(hostile, null));
  assert.equal(body.querySelectorAll("script, b, i, u").length, 0);
  const card = body.querySelector("[data-llm-node-card]");
  assert.equal(card.dataset.nodeId, "n<script>", "dataset round-trips after escaping");
  assert.equal(card.querySelector(".llm-node-card__title").textContent, "<b>节点</b>");
});

test("llmNodeCardHtml renders 未配置 for a node without api_key", () => {
  const body = bodyFrom(llmNodeCardHtml({ ...NODE, api_key: null }, null));
  assert.match(body.querySelector(".llm-node-card__key").textContent, /未配置/);
});

test("llmNodeCardHtml tolerates a null node", () => {
  const body = bodyFrom(llmNodeCardHtml(null, null));
  const card = body.querySelector("[data-llm-node-card]");
  assert.ok(card);
  assert.equal(card.querySelector(".llm-node-card__title").textContent, "未命名节点");
});

/* ------------------------------------------------------------------ */
/* nodeTestResultHtml: Sprint 5 T2 测试结果                             */
/* ------------------------------------------------------------------ */

test("nodeTestResultHtml renders success with latency", () => {
  const body = bodyFrom(nodeTestResultHtml({ ok: true, status: 200, latency_ms: 120, message: "连接成功" }));
  const node = body.querySelector("[data-llm-node-test]");
  assert.ok(node);
  assert.equal(node.className.includes("form-success"), true);
  assert.equal(node.getAttribute("role"), "status");
  assert.match(node.textContent, /HTTP 200/);
  assert.match(node.textContent, /120 ms/);
  assert.match(node.textContent, /连接成功/);
});

test("nodeTestResultHtml renders failure reason without latency", () => {
  const body = bodyFrom(nodeTestResultHtml({ ok: false, status: 401, latency_ms: null, message: "认证失败：API Key 无效" }));
  const node = body.querySelector("[data-llm-node-test]");
  assert.ok(node);
  assert.equal(node.className.includes("form-error"), true);
  assert.equal(node.getAttribute("role"), "alert");
  assert.match(node.textContent, /HTTP 401/);
  assert.equal(node.textContent.includes("ms"), false);
  assert.match(node.textContent, /认证失败：API Key 无效/);
});

test("nodeTestResultHtml escapes provider messages", () => {
  const body = bodyFrom(nodeTestResultHtml({ ok: false, status: 500, latency_ms: null, message: '<script>alert("x")</script>' }));
  assert.equal(body.querySelector("script"), null);
  assert.match(body.querySelector("[data-llm-node-test]").textContent, /<script>/);
});

test("nodeTestResultHtml returns empty for missing result", () => {
  assert.equal(nodeTestResultHtml(null), "");
  assert.equal(nodeTestResultHtml(undefined), "");
  assert.equal(nodeTestResultHtml({}), "");
});

/* ------------------------------------------------------------------ */
/* llmNodeFormHtml: Sprint 5 T2 新增 / 编辑表单                          */
/* ------------------------------------------------------------------ */

test("llmNodeFormHtml renders an empty create form", () => {
  const body = bodyFrom(llmNodeFormHtml(null));
  const form = body.querySelector("[data-form='llm-node-form']");
  assert.ok(form);
  assert.equal(form.querySelector('input[name="node_id"]').value, "");
  assert.equal(form.querySelector('input[name="node_name"]').value, "");
  assert.deepEqual(
    [...form.querySelectorAll('select[name="node_provider"] option')].map((o) => o.value),
    EXPECTED_PROVIDERS,
  );
  assert.equal(form.querySelector('input[name="node_model"]').value, "");
  assert.equal(form.querySelector('input[name="node_base_url"]').value, "");
  assert.equal(form.querySelector('button[type="submit"]').textContent, "创建节点");
  assert.ok(form.querySelector('[data-action="close-modal"]'));
});

test("llmNodeFormHtml prefills an edit form and keeps the API key blank", () => {
  const body = bodyFrom(llmNodeFormHtml(NODE));
  const form = body.querySelector("[data-form='llm-node-form']");
  assert.equal(form.querySelector('input[name="node_id"]').value, "n1");
  assert.equal(form.querySelector('input[name="node_name"]').value, "主 DeepSeek 节点");
  assert.equal(selectedProvider(form), "deepseek");
  assert.equal(form.querySelector('input[name="node_model"]').value, "deepseek-chat");
  assert.equal(form.querySelector('input[name="node_base_url"]').value, "https://api.deepseek.com/v1");
  assert.equal(form.querySelector('input[name="node_api_key"]').value, "", "edit keeps key blank");
  assert.match(form.querySelector('input[name="node_api_key"]').getAttribute("placeholder"), /已保存/);
  assert.match(form.textContent, /已保存 Key：sk-1••••abcd/);
  assert.equal(form.querySelector('button[type="submit"]').textContent, "保存修改");
});

test("llmNodeFormHtml escapes prefilled values", () => {
  const body = bodyFrom(llmNodeFormHtml({ ...NODE, name: '<script>x</script>', model: '<b>m</b>' }));
  const form = body.querySelector("[data-form='llm-node-form']");
  assert.equal(body.querySelector("script, b"), null);
  assert.equal(form.querySelector('input[name="node_name"]').value, "<script>x</script>");
  assert.equal(form.querySelector('input[name="node_model"]').value, "<b>m</b>");
});

/* ------------------------------------------------------------------ */
/* ruleListHtml / ruleFormHtml: Sprint 5 T4 自动化规则                   */
/* ------------------------------------------------------------------ */

const RULES = [
  { rule_id: "r1", rule_type: "blacklist", value: "Acme 科技", label: "排除外包", enabled: true },
  { rule_id: "r2", rule_type: "city_whitelist", value: "上海,杭州", label: null, enabled: false },
  { rule_id: "r3", rule_type: "min_salary", value: "20", label: "低于 20k 拦截", enabled: true },
];

test("automationRuleTypeLabel maps the three rule types to Chinese labels", () => {
  assert.equal(automationRuleTypeLabel("blacklist"), "黑名单");
  assert.equal(automationRuleTypeLabel("city_whitelist"), "城市白名单");
  assert.equal(automationRuleTypeLabel("min_salary"), "最低薪资");
  assert.equal(automationRuleTypeLabel("unknown"), "unknown");
  assert.equal(automationRuleTypeLabel(""), "");
  assert.equal(automationRuleTypeLabel(null), "");
});

test("ruleListHtml renders one item per rule with type labels and delete", () => {
  const body = bodyFrom(ruleListHtml(RULES));
  const list = body.querySelector("[data-rule-list]");
  const items = [...list.querySelectorAll("[data-rule-item]")];
  assert.equal(items.length, 3);

  const badges = items.map((item) => item.querySelector(".badge").textContent);
  assert.deepEqual(badges, ["黑名单", "城市白名单", "最低薪资"]);

  assert.equal(items[0].querySelector(".rule-item__label").textContent, "排除外包");
  assert.equal(items[0].querySelector(".rule-item__value").textContent, "Acme 科技");
  assert.ok(items[0].querySelector('[data-action="automation-rule-delete"][data-id="r1"]'));

  /* enabled 开关：enabled=true checked，false 不 checked */
  assert.equal(items[0].querySelector('[data-rule-toggle][data-id="r1"]').checked, true);
  assert.equal(items[1].querySelector('[data-rule-toggle][data-id="r2"]').checked, false);
});

test("ruleListHtml omits the label block when label is empty", () => {
  const body = bodyFrom(ruleListHtml([RULES[1]]));
  const item = body.querySelector("[data-rule-item]");
  assert.equal(item.querySelectorAll(".rule-item__label").length, 0);
  assert.equal(item.querySelector(".rule-item__value").textContent, "上海,杭州");
});

test("ruleListHtml escapes rule value / label / id", () => {
  const hostile = {
    rule_id: 'r<script>',
    rule_type: "blacklist",
    value: '<b>v</b> & "x"',
    label: '<img src=x onerror=1>外包',
    enabled: true,
  };
  const body = bodyFrom(ruleListHtml([hostile]));
  assert.equal(body.querySelectorAll("script, b, img").length, 0);
  const item = body.querySelector("[data-rule-item]");
  assert.equal(item.dataset.ruleId, "r<script>");
  assert.equal(item.querySelector(".rule-item__value").textContent, '<b>v</b> & "x"');
  assert.equal(item.querySelector(".rule-item__label").textContent, '<img src=x onerror=1>外包');
});

test("ruleListHtml shows an empty state for no rules", () => {
  const body = bodyFrom(ruleListHtml([]));
  assert.ok(body.querySelector("[data-rule-empty]"));
  assert.equal(body.querySelectorAll("[data-rule-item]").length, 0);
  const body2 = bodyFrom(ruleListHtml(null));
  assert.ok(body2.querySelector("[data-rule-empty]"));
});

test("ruleFormHtml renders type dropdown, value/label inputs and actions", () => {
  const body = bodyFrom(ruleFormHtml());
  const form = body.querySelector("[data-form='automation-rule-form']");
  assert.ok(form);
  const typeOptions = [...form.querySelectorAll('select[name="rule_type"] option')].map((o) => o.value);
  /* Phase B: 城市白名单随爬虫退役从表单移除（DB 兼容保留，UI 不再暴露）。 */
  assert.deepEqual(typeOptions, ["blacklist", "min_salary"]);
  const value = form.querySelector('input[name="rule_value"]');
  assert.ok(value);
  assert.equal(value.hasAttribute("required"), true);
  assert.ok(form.querySelector('input[name="rule_label"]'));
  assert.equal(form.querySelector('button[type="submit"]').textContent, "新增规则");
  assert.ok(form.querySelector('[data-action="close-modal"]'));
});

/* ------------------------------------------------------------------ */
/* settings-form.js: 节点 / 规则 payload 构建与校验                       */
/* ------------------------------------------------------------------ */

test("buildLlmNodePayload maps node_* fields and trims values", () => {
  const payload = buildLlmNodePayload({
    node_name: "  主节点  ",
    node_provider: " deepseek ",
    node_model: " deepseek-chat ",
    node_base_url: " https://api.deepseek.com/v1 ",
    node_api_key: "  sk-abc  ",
  });
  assert.deepEqual(payload, {
    name: "主节点",
    provider: "deepseek",
    model: "deepseek-chat",
    base_url: "https://api.deepseek.com/v1",
    disable_thinking: false,
    api_key: "sk-abc",
  });
});

test("buildLlmNodePayload carries disable_thinking checkbox state", () => {
  const on = buildLlmNodePayload({
    node_name: "nvidia",
    node_provider: "openrouter",
    node_model: "meta/muse-glimmer-30b",
    node_disable_thinking: "on",
  });
  assert.equal(on.disable_thinking, true);
  const off = buildLlmNodePayload({
    node_name: "nvidia",
    node_provider: "openrouter",
    node_model: "meta/muse-glimmer-30b",
  });
  assert.equal(off.disable_thinking, false);
});

test("buildLlmNodePayload omits api_key and nulls base_url when blank", () => {
  const payload = buildLlmNodePayload({
    node_name: "n",
    node_provider: "ollama",
    node_model: "llama3",
    node_base_url: "   ",
    node_api_key: "",
  });
  assert.equal("api_key" in payload, false);
  assert.equal(payload.base_url, null);
});

test("validateLlmNodePayload requires name / provider / model", () => {
  assert.equal(validateLlmNodePayload({ name: "", provider: "deepseek", model: "m" }).ok, false);
  assert.equal(validateLlmNodePayload({ name: "n", provider: "", model: "m" }).ok, false);
  assert.equal(validateLlmNodePayload({ name: "n", provider: "deepseek", model: "" }).ok, false);
});

test("validateLlmNodePayload requires api_key on create unless ollama", () => {
  assert.equal(
    validateLlmNodePayload({ name: "n", provider: "deepseek", model: "m", api_key: "sk-x" }).ok,
    true,
  );
  const noKey = validateLlmNodePayload({ name: "n", provider: "deepseek", model: "m" });
  assert.equal(noKey.ok, false);
  assert.match(noKey.message, /API Key/);
  assert.equal(
    validateLlmNodePayload({ name: "n", provider: "ollama", model: "m" }).ok,
    true,
    "ollama local server may omit the key",
  );
});

test("validateLlmNodePayload skips the key requirement on edit", () => {
  const payload = { name: "n", provider: "deepseek", model: "m" };
  assert.equal(validateLlmNodePayload(payload, { isEdit: true }).ok, true);
});

test("buildAutomationRulePayload defaults type and omits empty label", () => {
  const payload = buildAutomationRulePayload({ rule_type: "blacklist", rule_value: "  Acme  ", rule_label: "" });
  assert.deepEqual(payload, { rule_type: "blacklist", value: "Acme", enabled: true });
  const withLabel = buildAutomationRulePayload({ rule_value: "x", rule_label: "备注" });
  assert.equal(withLabel.label, "备注");
  assert.equal(withLabel.rule_type, "blacklist");
});

test("validateAutomationRule requires a value and positive min_salary", () => {
  assert.equal(validateAutomationRule({ rule_type: "blacklist", value: "" }).ok, false);
  assert.equal(validateAutomationRule({ rule_type: "blacklist", value: "Acme" }).ok, true);
  const badSalary = validateAutomationRule({ rule_type: "min_salary", value: "abc" });
  assert.equal(badSalary.ok, false);
  assert.match(badSalary.message, /数字/);
  assert.equal(validateAutomationRule({ rule_type: "min_salary", value: "-5" }).ok, false);
  assert.equal(validateAutomationRule({ rule_type: "min_salary", value: "20" }).ok, true);
});

test("llmNodeCardHtml shows persisted health badge without fresh test result", () => {
  const healthy = llmNodeCardHtml(
    { ...NODE, is_active: false, last_test_status: "ok", last_test_at: 1788000000, last_test_latency_ms: 820 },
    null,
  );
  const okBody = bodyFrom(healthy);
  const okBadge = okBody.querySelector(".llm-node-card__head .badge-green:not([data-node-active-badge])");
  assert.ok(okBadge, "ok health renders a green badge");
  assert.match(okBadge.textContent, /连通正常/);

  const broken = bodyFrom(
    llmNodeCardHtml(
      { ...NODE, last_test_status: "http_402", last_test_at: 1788000000, last_test_latency_ms: 1200 },
      null,
    ),
  );
  const badBadge = broken.querySelector(".llm-node-card__head .badge-red");
  assert.ok(badBadge, "failure status renders a red badge");
  assert.match(badBadge.textContent, /上次异常/);
  assert.match(badBadge.title, /http_402/);

  /* 有本会话新鲜测试结果时不重复渲染持久徽标 */
  const fresh = bodyFrom(llmNodeCardHtml({ ...NODE, last_test_status: "ok" }, { ok: true, status: "ok", latency_ms: 5 }));
  assert.equal(fresh.querySelector(".llm-node-card__head .badge-red"), null);
});

/* ------------------------------------------------------------------ */
/* settingsModeSwitchHtml / simpleLlmSetupHtml: 新手体验简单模式          */
/* ------------------------------------------------------------------ */

const HERE = dirname(fileURLToPath(import.meta.url));

test("settingsModeSwitchHtml marks only the active mode", () => {
  const simple = bodyFrom(settingsModeSwitchHtml("simple"));
  assert.ok(simple.querySelector('[data-action="settings-mode-simple"].is-active'));
  assert.equal(simple.querySelector('[data-action="settings-mode-expert"].is-active'), null);
  assert.equal(simple.querySelector('[data-action="settings-mode-simple"]').getAttribute("aria-pressed"), "true");
  assert.equal(simple.querySelector('[data-action="settings-mode-expert"]').getAttribute("aria-pressed"), "false");

  const expert = bodyFrom(settingsModeSwitchHtml("expert"));
  assert.equal(expert.querySelector('[data-action="settings-mode-simple"].is-active'), null);
  assert.ok(expert.querySelector('[data-action="settings-mode-expert"].is-active'));
});

test("simpleLlmSetupHtml renders a create form without test button", () => {
  const body = bodyFrom(simpleLlmSetupHtml(null, null));
  const panel = body.querySelector("[data-simple-llm-panel]");
  assert.ok(panel, "simple panel is rendered");
  assert.equal(panel.hasAttribute("data-llm-node-card"), false, "create panel has no node to test");
  const form = body.querySelector("[data-form='simple-llm-form']");
  assert.equal(form.querySelector('input[name="node_id"]'), null, "create mode has no node_id");
  assert.equal(form.querySelector('input[name="node_name"]').value, "我的 AI 助手");
  assert.deepEqual(
    [...form.querySelectorAll('select[name="node_provider"] option')].map((o) => o.value),
    EXPECTED_PROVIDERS,
  );
  assert.equal(form.querySelector('button[type="submit"]').textContent, "启用 AI 助手");
  assert.equal(body.querySelector('[data-action="llm-node-test"]'), null, "no node yet, no test button");
  assert.equal(body.querySelector("[data-llm-node-test-result]").textContent.trim(), "");
});

test("simpleLlmSetupHtml prefills the edit form and keeps key blank", () => {
  const body = bodyFrom(simpleLlmSetupHtml({ ...NODE, disable_thinking: true }, { ok: true, status: 200, latency_ms: 90 }));
  const panel = body.querySelector("[data-simple-llm-panel]");
  assert.equal(panel.dataset.nodeId, "n1");
  assert.ok(panel.querySelector(".badge-green"), "active node shows the enabled badge");
  const form = body.querySelector("[data-form='simple-llm-form']");
  assert.equal(form.querySelector('input[name="node_id"]').value, "n1");
  assert.equal(form.querySelector('input[name="node_name"]').value, "主 DeepSeek 节点");
  assert.equal(form.querySelector('input[name="node_disable_thinking"]').value, "on", "disable_thinking is carried through");
  assert.equal(selectedProvider(form), "deepseek");
  assert.equal(form.querySelector('input[name="node_model"]').value, "deepseek-chat");
  assert.equal(form.querySelector('input[name="node_api_key"]').value, "", "edit keeps key blank");
  assert.match(form.querySelector('input[name="node_api_key"]').getAttribute("placeholder"), /已保存，留空保持不变/);
  assert.equal(form.querySelector('button[type="submit"]').textContent, "保存并启用");
  const testBtn = body.querySelector('[data-action="llm-node-test"]');
  assert.ok(testBtn, "edit mode exposes test connection");
  assert.equal(testBtn.dataset.id, "n1");
  assert.match(body.querySelector("[data-llm-node-test-result]").textContent, /90 ms/);
});

test("simpleLlmSetupHtml escapes prefilled values", () => {
  const body = bodyFrom(
    simpleLlmSetupHtml({ ...NODE, name: "<b>节点</b>", model: "<script>x</script>" }, null),
  );
  assert.equal(body.querySelector("script, b"), null);
  assert.equal(body.querySelector('input[name="node_name"]').value, "<b>节点</b>");
  assert.equal(body.querySelector('input[name="node_model"]').value, "<script>x</script>");
});

test("main.js wires the simple/expert mode switch and simple form submission", () => {
  const mainJs = readFileSync(join(HERE, "../../src/resualign/static/app/main.js"), "utf8");
  /* 双模式渲染门控：专家面板仅在 expert 模式输出 */
  assert.match(
    mainJs,
    /settingsMode === "expert" \? expertPanelsHtml : simpleLlmSetupHtml/,
    "settings view must gate expert panels behind the mode switch",
  );
  /* 模式解析：默认简单，「专家」为显式选择后即生效（无节点也允许——
   * 否则备用节点/Token 面板无处可达，E2E settings 流曾死锁于此） */
  assert.match(mainJs, /const settingsMode = readSettingsMode\(\);/);
  assert.doesNotMatch(mainJs, /hasNodes \? readSettingsMode\(\)/);
  /* 模式持久化与切换动作 */
  assert.match(mainJs, /"settings-mode-simple"/);
  assert.match(mainJs, /"settings-mode-expert"/);
  assert.match(mainJs, /"resualign\.settingsMode"/);
  /* 简单模式表单提交走节点 CRUD 复用路径 */
  assert.match(mainJs, /case "simple-llm-form":/);
});

/* ------------------------------------------------------------------ */
/* Base URL 自动识别：模型输入 + 「获取模型」按钮                        */
/* ------------------------------------------------------------------ */

test("llmNodeFormHtml exposes the fetch-models button and picker", () => {
  const body = bodyFrom(llmNodeFormHtml(null));
  const form = body.querySelector("[data-form='llm-node-form']");
  const button = form.querySelector('[data-action="llm-fetch-models"]');
  assert.ok(button, "expert node form wires the fetch-models button");
  assert.equal(button.getAttribute("type"), "button", "must not submit the form");
  const input = form.querySelector("input[name='node_model']");
  const listId = input.getAttribute("list");
  assert.ok(listId, "model input points at a datalist");
  const datalist = form.querySelector(`datalist#${listId}[data-llm-model-list]`);
  assert.ok(datalist, "matching datalist is present for the model input");
  assert.equal(input.dataset.llmModelInput, "", "model input carries the fetch hook");
  const picker = form.querySelector("[data-llm-model-picker]");
  assert.ok(picker, "a visible model picker is rendered next to the datalist");
  assert.ok(picker.hidden, "the picker stays hidden until models are fetched");
});

test("simpleLlmSetupHtml exposes the fetch-models button and picker", () => {
  const body = bodyFrom(simpleLlmSetupHtml(null, null));
  const form = body.querySelector("[data-form='simple-llm-form']");
  assert.ok(form.querySelector('[data-action="llm-fetch-models"]'));
  const input = form.querySelector("input[name='node_model']");
  const listId = input.getAttribute("list");
  assert.ok(form.querySelector(`datalist#${listId}[data-llm-model-list]`));
  assert.ok(form.querySelector("[data-llm-model-picker]"));
});

test("main.js wires the llm-fetch-models action to POST /api/llm/models", () => {
  const mainJs = readFileSync(join(HERE, "../../src/resualign/static/app/main.js"), "utf8");
  assert.match(mainJs, /"llm-fetch-models": async \(button\)/);
  assert.match(mainJs, /api\("\/api\/llm\/models", \{/);
  /* 403/网络错误走 toast，不静默失败 */
  assert.match(mainJs, /获取模型失败/);
  /* 拉回结果必须渲染成可点清单，而不是只塞进原生 datalist（点了没反应） */
  assert.match(mainJs, /\[data-llm-model-picker\]/);
  assert.match(mainJs, /data-action="llm-pick-model"/);
  assert.match(mainJs, /"llm-pick-model": \(button\)/);
  assert.match(
    mainJs,
    /input\.value = button\.dataset\.model/,
    "picking a model writes it back into the model input",
  );
});

/* 2026-09-24：设置页的「Guardrails」面板是写死展示（超时数字 40s 与后端
 * 实际 per-role 45–90s 不符），且「评估默认」勾选框没有 name / handler，
 * 点了不生效。真正生效的评估开关在节点卡片下方，故整块删除。 */
test("settings page no longer ships the decorative Guardrails panel", () => {
  const mainJs = readFileSync(join(HERE, "../../src/resualign/static/app/main.js"), "utf8");
  assert.doesNotMatch(mainJs, /data-guardrails-panel/);
  assert.doesNotMatch(mainJs, /<h2>Guardrails<\/h2>/);
  assert.doesNotMatch(mainJs, /超时熔断/);
  assert.doesNotMatch(
    mainJs,
    /<input type="checkbox" checked> 默认运行对齐评估/,
    "the dead eval checkbox must not come back",
  );
  /* 自动化规则是真功能，必须留在专家模式里 */
  assert.match(mainJs, /<h2>自动化规则<\/h2>/);
  /* 真开关仍在（settings-eval-default 表单） */
  assert.match(mainJs, /data-form="settings-eval-default"/);
});
