import { test } from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";

import {
  automationRuleTypeLabel,
  costGuardPanelHtml,
  llmNodeCardHtml,
  llmNodeFormHtml,
  nodeTestResultHtml,
  reminderSettingsPanelHtml,
  ruleFormHtml,
  ruleListHtml,
  settingsBentoHtml,
  todayViewHtml,
} from "../../src/resualign/static/app/format.js";
import {
  buildAutomationRulePayload,
  buildCostGuardPayload,
  buildLlmNodePayload,
  buildReminderPayload,
  validateAutomationRule,
  validateCostGuardPayload,
  validateLlmNodePayload,
  validateReminderPayload,
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
  assert.deepEqual(labels, ["活跃模型 ID", "架构模式", "Timeout 护栏", "API 延迟"]);

  assert.equal(body.querySelector("[data-bento-model] .settings-bento__value").textContent, "—");
  assert.equal(body.querySelector("[data-bento-arch] .settings-bento__value").textContent, "本地 SQLite");
  assert.equal(body.querySelector("[data-bento-timeout] .settings-bento__value").textContent, "40 秒");
  assert.equal(body.querySelector("[data-bento-timeout] .settings-bento__hint").textContent, "并发: 1");
  assert.equal(body.querySelector("[data-bento-latency] .settings-bento__value").textContent, "—");
});

test("settingsBentoHtml shows active node, timeout guardrails and latency", () => {
  const node = { node_id: "n1", name: "主节点", provider: "deepseek", model: "deepseek-chat", is_active: true };
  const body = bodyFrom(settingsBentoHtml(node, 123));
  assert.equal(
    body.querySelector("[data-bento-model] .settings-bento__value").textContent,
    "deepseek · deepseek-chat",
  );
  assert.equal(body.querySelector("[data-bento-timeout] .settings-bento__value").textContent, "40 秒");
  assert.equal(body.querySelector("[data-bento-timeout] .settings-bento__hint").textContent, "并发: 1");
  assert.equal(body.querySelector("[data-bento-latency] .settings-bento__value").textContent, "123 ms");
});

test("settingsBentoHtml tolerates missing / non-array-ish counts", () => {
  const body = bodyFrom(settingsBentoHtml(null, null));
  assert.equal(body.querySelector("[data-bento-timeout] .settings-bento__value").textContent, "40 秒");
  const body2 = bodyFrom(settingsBentoHtml(null, "abc"));
  assert.equal(body2.querySelector("[data-bento-timeout] .settings-bento__value").textContent, "40 秒");
  assert.equal(body2.querySelector("[data-bento-latency] .settings-bento__value").textContent, "—");
});

test("settingsBentoHtml escapes model/provider values", () => {
  const node = { node_id: "n1", provider: '<img src=x onerror=1>', model: "<b>x</b>", is_active: true };
  const body = bodyFrom(settingsBentoHtml(node, {}, null));
  assert.equal(body.querySelectorAll("img, b").length, 0);
  const value = body.querySelector("[data-bento-model] .settings-bento__value");
  assert.equal(value.textContent, '<img src=x onerror=1> · <b>x</b>');
});

/* ------------------------------------------------------------------ */
/* costGuardPanelHtml: MVP-10 成本护栏面板                              */
/* ------------------------------------------------------------------ */

test("costGuardPanelHtml renders live usage and blocked state", () => {
  const settings = {
    daily_llm_cap: 5,
    llm_cost_per_1k_in: 0.5,
    llm_cost_per_1k_out: 1.5,
  };
  const daily = {
    calls: 6,
    cap: 5,
    estimated_cost: 12.34,
    blocked: true,
    remaining: 0,
  };
  const body = bodyFrom(costGuardPanelHtml(settings, daily));
  assert.equal(body.querySelector("[data-daily-calls]").textContent, "6");
  assert.equal(body.querySelector("[data-daily-cap]").textContent, "5");
  assert.equal(body.querySelector("[data-daily-remaining]").textContent, "0");
  assert.match(body.querySelector("[data-daily-cost]").textContent, /12\.3400/);
  assert.ok(body.querySelector("[data-cost-blocked]"));
  assert.equal(body.querySelector("[data-cost-status]").dataset.costBlocked, "true");
});

test("costGuardPanelHtml shows unlimited when cap is null", () => {
  const body = bodyFrom(costGuardPanelHtml({}, { calls: 0, cap: null }));
  assert.equal(body.querySelector("[data-daily-cap]").textContent, "不限制");
  assert.equal(body.querySelector("[data-daily-remaining]").textContent, "—");
  assert.equal(body.querySelector("[data-cost-status]").dataset.costBlocked, "false");
});

test("costGuardPanelHtml escapes hostile values", () => {
  const body = bodyFrom(
    costGuardPanelHtml(
      { daily_llm_cap: "<script>1</script>" },
      { cap: "<b>9</b>", estimated_cost: "<i>x</i>" },
    ),
  );
  assert.equal(body.querySelector("script, b, i"), null);
  assert.equal(body.querySelector("[data-daily-cap]").textContent, "<b>9</b>");
});

test("buildCostGuardPayload maps blank fields to null and numbers otherwise", () => {
  assert.deepEqual(
    buildCostGuardPayload({
      daily_llm_cap: " 12 ",
      llm_cost_per_1k_in: "0.5",
      llm_cost_per_1k_out: "",
    }),
    { daily_llm_cap: 12, llm_cost_per_1k_in: 0.5, llm_cost_per_1k_out: null },
  );
  assert.deepEqual(buildCostGuardPayload({}), {
    daily_llm_cap: null,
    llm_cost_per_1k_in: null,
    llm_cost_per_1k_out: null,
  });
});

test("validateCostGuardPayload rejects negative and non-finite values", () => {
  assert.deepEqual(
    validateCostGuardPayload({ daily_llm_cap: 1, llm_cost_per_1k_in: 0.2 }),
    { ok: true, message: "" },
  );
  assert.equal(validateCostGuardPayload({ daily_llm_cap: -1 }).ok, false);
  assert.equal(validateCostGuardPayload({ llm_cost_per_1k_out: Number.NaN }).ok, false);
});

/* ------------------------------------------------------------------ */
/* MVP-08: 今日待办视图 + 提醒设置面板                                  */
/* ------------------------------------------------------------------ */

test("todayViewHtml renders reminders with workspace links and follow-up actions", () => {
  const body = bodyFrom(
    todayViewHtml([
      {
        job_id: "j1",
        title: "后端工程师",
        company: "Acme",
        status_canonical: "interview",
        interview_stage: "二面",
        next_step: "准备系统设计题",
        next_step_due_at: "2026-08-10 18:00",
        overdue: true,
      },
      {
        job_id: "j2",
        title: "前端工程师",
        company: "Beta",
        status_canonical: "applied",
        next_step_due_at: "2026-08-10 20:00",
        overdue: false,
      },
    ]),
  );
  assert.equal(body.querySelector("[data-today-count]").textContent, "2 条");
  const rows = [...body.querySelectorAll("[data-today-item]")];
  assert.equal(rows.length, 2);
  assert.equal(rows[0].querySelector("a").getAttribute("href"), "#/workspace/j1");
  assert.match(rows[0].textContent, /二面/);
  assert.match(rows[0].querySelector("[data-today-due]").textContent, /已过期/);
  assert.deepEqual(
    [...body.querySelectorAll('[data-action="open-job-followup"]')].map(
      (node) => node.dataset.id,
    ),
    ["j1", "j2"],
  );
});

test("todayViewHtml renders an empty state without reminders", () => {
  const body = bodyFrom(todayViewHtml([]));
  assert.ok(body.querySelector("[data-today-empty]"));
  assert.equal(body.querySelector("[data-today-count]").textContent, "0 条");
  assert.equal(body.querySelectorAll("[data-today-item]").length, 0);
});

test("todayViewHtml escapes user content", () => {
  const body = bodyFrom(
    todayViewHtml([
      {
        job_id: "<img src=x>",
        title: "<script>alert(1)</script>",
        company: "<b>Acme</b>",
        next_step: "onerror=1",
      },
    ]),
  );
  assert.equal(body.querySelectorAll("script, img, b").length, 0);
  assert.match(body.textContent, /alert\(1\)/);
});

test("reminderSettingsPanelHtml shows masked channel status and editable SMTP fields", () => {
  const settings = {
    reminder: {
      enabled: true,
      provider: "feishu",
      smtp_host: "smtp.example.com",
      smtp_port: 465,
      smtp_user: "user",
      smtp_from: "from@example.com",
      smtp_to: "to@example.com",
    },
  };
  const status = {
    webhook_url_configured: false,
    webhook_secret_configured: true,
    smtp_configured: true,
    smtp_password_configured: true,
  };
  const body = bodyFrom(reminderSettingsPanelHtml(settings, status));
  assert.equal(body.querySelector("[data-reminder-enabled]").textContent.trim(), "已开启");
  assert.equal(body.querySelector("[data-reminder-webhook-status]").textContent, "未配置（环境变量）");
  assert.equal(body.querySelector("[data-reminder-smtp-status]").textContent, "已配置");
  assert.equal(
    body.querySelector('[data-form="settings-reminder"] select[name="provider"] option[value="feishu"]').selected,
    true,
  );
  assert.equal(body.querySelector('input[name="smtp_host"]').value, "smtp.example.com");
  assert.equal(body.querySelector('input[name="smtp_port"]').value, "465");
  assert.equal(body.querySelector('input[name="smtp_user"]').value, "user");
  assert.equal(body.querySelector('input[name="smtp_to"]').value, "to@example.com");
  assert.equal(
    body.querySelector('[data-form="settings-reminder"] input[name="auto_followup_reminder"]').checked,
    true,
  );
  assert.equal(body.querySelectorAll('input[type="password"]').length, 0);
});

test("reminderSettingsPanelHtml defaults to generic and closed", () => {
  const body = bodyFrom(reminderSettingsPanelHtml({ reminder: {} }, {}));
  assert.equal(body.querySelector("[data-reminder-enabled]").textContent.trim(), "已关闭");
  assert.equal(body.querySelector('[data-form="settings-reminder"] select[name="provider"]').value, "generic");
});

test("buildReminderPayload maps form fields and never includes secrets", () => {
  const payload = buildReminderPayload({
    enabled: "on",
    auto_followup_reminder: "on",
    provider: "wecom",
    smtp_host: " smtp.example.com ",
    smtp_port: "587",
    smtp_user: "user",
    smtp_from: "from@example.com",
    smtp_to: "to@example.com",
  });
  assert.deepEqual(payload, {
    reminder: {
      enabled: true,
      auto_followup_reminder: true,
      provider: "wecom",
      smtp_host: "smtp.example.com",
      smtp_port: 587,
      smtp_user: "user",
      smtp_from: "from@example.com",
      smtp_to: "to@example.com",
    },
  });
  assert.equal("webhook_url" in payload.reminder, false);
  assert.equal("smtp_password" in payload.reminder, false);
});

test("buildReminderPayload clears blank SMTP fields and validates port", () => {
  const payload = buildReminderPayload({ enabled: "", provider: "", smtp_port: "" });
  assert.equal(payload.reminder.enabled, false);
  assert.equal(payload.reminder.provider, "generic");
  assert.equal(payload.reminder.smtp_host, null);
  assert.equal(payload.reminder.smtp_port, null);
  assert.equal(validateReminderPayload(payload).ok, true);
  const bad = buildReminderPayload({ provider: "generic", smtp_port: "70000" });
  assert.equal(validateReminderPayload(bad).ok, false);
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
    ["deepseek", "openrouter", "ollama"],
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
  assert.equal(form.querySelector('select[name="node_provider"]').value, "deepseek");
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
  assert.deepEqual(typeOptions, ["blacklist", "city_whitelist", "min_salary"]);
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
    api_key: "sk-abc",
  });
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
