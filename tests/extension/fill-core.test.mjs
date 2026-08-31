import test from "node:test";
import assert from "node:assert/strict";
// happy-dom 安装在 tests/frontend/node_modules（前端测试的独立依赖树）
import { createRequire } from "node:module";
const require2 = createRequire(import.meta.url);
const { Window } = require2("../frontend/node_modules/happy-dom");

function newDoc() {
  const window = new Window();
  return window.document;
}

import {
  flattenProfile,
  inputContext,
  isFillable,
  matchEntry,
  nextEmptyInput,
  setNativeValue,
  fillAll,
} from "../../extension/fill-core.js";

const PROFILE = {
  basic: { name: "陈振成", phone: "138-0000-0000", email: "chen@example.com",
           id_number: "" },
  education: [{ school: "广东理工学院", major: "计算机科学与技术", degree: "本科",
                start: "2020", end: "2024" }],
  work: [{ company: "某电商", title: "后端", start: "2024", end: "2025",
           highlights: ["订单服务", "库存服务"] }],
  projects: [{ name: "Nexus", role: "", start: "", end: "", description: "AI 社区" }],
  skills: ["Java", "Redis"],
  summary: "五年后端经验",
};

test("flattenProfile 平铺基本/教育/工作/技能/长文本", () => {
  const entries = flattenProfile(PROFILE);
  const byLabel = Object.fromEntries(entries.map((e) => [e.label + "|" + e.value, e]));
  assert.ok(byLabel["姓名|陈振成"]);
  assert.ok(byLabel["学校|广东理工学院"]);
  assert.ok(byLabel["公司|某电商"]);
  assert.ok(byLabel["技能|Java"]);
  // 证件号为空不占条目（敏感字段用户手填）
  assert.ok(!entries.some((e) => e.label === "证件号"));
  const workContent = entries.find((e) => e.label === "工作内容");
  assert.equal(workContent.multiline, true);
  assert.match(workContent.value, /订单服务/);
  const summary = entries.find((e) => e.label === "自我描述");
  assert.equal(summary.value, "五年后端经验");
});

test("inputContext 聚合 placeholder/name/label 文本", () => {
  const doc = newDoc();
  const label = doc.createElement("label");
  label.setAttribute("for", "phone-input");
  label.textContent = "手机号码";
  const el = doc.createElement("input");
  el.id = "phone-input";
  el.setAttribute("placeholder", "请输入手机号");
  el.setAttribute("name", "phone");
  doc.body.append(label, el);
  const ctx = inputContext(el);
  assert.match(ctx, /手机/);
  assert.match(ctx, /phone/);
});

test("matchEntry 取最长 label 命中", () => {
  const entries = [
    { label: "学校", value: "A 校" },
    { label: "毕业学校", value: "B 校" },
  ];
  assert.equal(matchEntry("请填写毕业学校名称", entries).value, "B 校");
  assert.equal(matchEntry("完全无关的文本", entries), null);
  assert.equal(matchEntry("", entries), null);
});

test("setNativeValue 赋值并派发 input 事件", () => {
  const el = newDoc().createElement("input");
  let fired = 0;
  el.addEventListener("input", () => fired += 1);
  setNativeValue(el, "hello");
  assert.equal(el.value, "hello");
  assert.ok(fired >= 1);
});

test("isFillable 过滤隐藏/禁用/不可填类型", () => {
  const doc = newDoc();
  const text = doc.createElement("input");
  assert.equal(isFillable(text), true);
  const checkbox = doc.createElement("input");
  checkbox.type = "checkbox";
  assert.equal(isFillable(checkbox), false);
  const disabled = doc.createElement("input");
  disabled.disabled = true;
  assert.equal(isFillable(disabled), false);
  const hidden = doc.createElement("input");
  hidden.type = "hidden";
  assert.equal(isFillable(hidden), false);
  const area = doc.createElement("textarea");
  assert.equal(isFillable(area), true);
});

test("nextEmptyInput 依序跳转空输入框", () => {
  const doc = newDoc();
  doc.body.innerHTML = `
    <input id="a"><input id="b" value="已有内容"><input id="c"><input id="d">`;
  const first = nextEmptyInput(doc, null);
  assert.equal(first.id, "a");
  const second = nextEmptyInput(doc, doc.getElementById("a"));
  assert.equal(second.id, "c");
  // c 之后是 d；从 d 起回绕到 a
  const fourth = nextEmptyInput(doc, doc.getElementById("c"));
  assert.equal(fourth.id, "d");
  const wrap = nextEmptyInput(doc, doc.getElementById("d"));
  assert.equal(wrap.id, "a");
});

test("fillAll 按 label 匹配填充所有空框并计数", () => {
  const doc = newDoc();
  doc.body.innerHTML = `
    <input data-ctx placeholder="请输入姓名">
    <input data-ctx placeholder="手机号码">
    <input data-ctx placeholder="无关字段">`;
  const entries = [
    { label: "姓名", value: "陈振成" },
    { label: "电话", value: "138" },
  ];
  // inputContext 读 placeholder/name/label——"请输入姓名"含"姓名" ✓
  const count = fillAll(doc, entries);
  assert.equal(count, 1);
  assert.equal(doc.querySelector('input[placeholder="请输入姓名"]').value, "陈振成");
});
