import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Window } from "happy-dom";

import {
  LLM_ROLE_LABELS,
  roleBindingsPanelHtml,
  simpleLlmSetupHtml,
} from "../../src/resualign/static/app/format.js";

const here = dirname(fileURLToPath(import.meta.url));

function bodyFrom(html) {
  const window = new Window();
  window.document.body.innerHTML = html;
  return window.document.body;
}

const ROLES = ["diagnose", "profiler", "gap_analyzer", "editor", "evaluator"];
const NODES = [
  { node_id: "n1", name: "主 DeepSeek", provider: "deepseek", model: "deepseek-chat" },
  { node_id: "n2", name: "本地 Ollama", provider: "ollama", model: "qwen2.5:7b" },
];
const BINDINGS = { editor: "n1", evaluator: "n1", diagnose: "n2" };

/* ------------------------------------------------------------------ */
/* roleBindingsPanelHtml: 专家模式节点分工面板                            */
/* ------------------------------------------------------------------ */

test("roleBindingsPanelHtml renders one row per role with bound select", () => {
  const body = bodyFrom(roleBindingsPanelHtml(ROLES, NODES, BINDINGS));
  const rows = [...body.querySelectorAll("[data-role-binding-row]")];
  assert.equal(rows.length, 5);
  assert.deepEqual(
    rows.map((row) => row.querySelector("[data-role-select]").name),
    ROLES,
  );
  /* 每行角色中文标签 */
  assert.match(rows[0].textContent, /简历诊断/);
  assert.match(rows[3].textContent, /改写引擎/);
  /* 绑定态：editor=主节点选中，gap_analyzer=跟随主节点 */
  const editorSelect = rows[3].querySelector("[data-role-select]");
  assert.equal(editorSelect.value, "n1");
  const gapSelect = rows[2].querySelector("[data-role-select]");
  assert.equal(gapSelect.value, "", "unbound role follows the active node");
  /* 下拉选项：跟随主节点 + 每个节点 */
  const optionValues = [...editorSelect.querySelectorAll("option")].map(
    (o) => o.value,
  );
  assert.deepEqual(optionValues, ["", "n1", "n2"]);
  /* 三个预设按钮 */
  const presets = [...body.querySelectorAll("[data-action='role-preset']")];
  assert.deepEqual(
    presets.map((b) => b.dataset.preset),
    ["unified", "hybrid", "local"],
  );
  /* 表单走 settings-role-bindings 提交 */
  assert.ok(body.querySelector("[data-form='settings-role-bindings']"));
});

test("roleBindingsPanelHtml shows empty state without nodes", () => {
  const body = bodyFrom(roleBindingsPanelHtml(ROLES, [], BINDINGS));
  assert.ok(body.querySelector("[data-role-bindings-empty]"));
  assert.equal(body.querySelectorAll("[data-role-binding-row]").length, 0);
  assert.equal(body.querySelectorAll("[data-action='role-preset']").length, 0);
});

test("roleBindingsPanelHtml tolerates null payloads and unknown roles", () => {
  const body = bodyFrom(roleBindingsPanelHtml(null, NODES, null));
  const rows = [...body.querySelectorAll("[data-role-binding-row]")];
  assert.equal(rows.length, Object.keys(LLM_ROLE_LABELS).length, "falls back to built-in role order");
  const hostile = bodyFrom(
    roleBindingsPanelHtml(
      ["diagnose", "<b>x</b>"],
      [{ node_id: 'n"<i>', name: "<b>节点</b>", provider: "deepseek", model: "m" }],
      {},
    ),
  );
  assert.equal(hostile.querySelector("b, i"), null);
  assert.match(
    hostile.querySelector('[data-role-select]').querySelector("option:last-child").textContent,
    /<b>节点<\/b>/,
  );
});

test("simpleLlmSetupHtml points to expert mode for multi-node split", () => {
  const body = bodyFrom(simpleLlmSetupHtml(null, null));
  assert.match(body.textContent, /多节点分工（本地分析 \+ 云端写作）也在那里配置/);
});

/* ------------------------------------------------------------------ */
/* 源码级契约：main.js 接线                                             */
/* ------------------------------------------------------------------ */

test("main.js wires role-bindings fetch, form submit and presets", () => {
  const mainJs = readFileSync(
    join(here, "../../src/resualign/static/app/main.js"),
    "utf8",
  );
  assert.match(mainJs, /\/api\/settings\/role-bindings/, "GET wired into settings view");
  assert.match(mainJs, /case "settings-role-bindings":/, "form submit case exists");
  assert.match(mainJs, /"role-preset"/, "preset action exists");
  assert.match(mainJs, /role-bindings\/presets/, "preset POST endpoint");
  /* 面板只出现在专家模式分支内 */
  assert.match(mainJs, /roleBindingsPanelHtml\(/);
  assert.match(mainJs, /LLM_ROLE_LABELS/);
});
