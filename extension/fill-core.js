/* ResuAlign 回填扩展的核心纯函数（零依赖，ESM）。
 * content script 通过 chrome.runtime.getURL 动态 import 本文件；
 * node --test 直接 import 做单元测试。 */

/** 把结构化档案平铺为可填充条目：[{group, label, value}]。
 * 长文本（highlights/description）合并为多行文本，供 textarea 填充。 */
export function flattenProfile(profile) {
  const data = (profile && profile.data) || profile || {};
  const basic = data.basic || {};
  const out = [];
  const basicFields = [
    ["姓名", "name"], ["电话", "phone"], ["邮箱", "email"],
    ["性别", "gender"], ["出生日期", "birth"], ["所在地", "location"],
    ["证件号", "id_number"],
  ];
  for (const [label, key] of basicFields) {
    if (String(basic[key] || "").trim()) {
      out.push({ group: "基本信息", label, value: String(basic[key]).trim() });
    }
  }
  (data.education || []).forEach((e, i) => {
    const suffix = (data.education || []).length > 1 ? ` ${i + 1}` : "";
    if (String(e.school || "").trim()) {
      out.push({ group: `教育经历${suffix}`, label: "学校", value: String(e.school).trim() });
    }
    if (String(e.major || "").trim()) {
      out.push({ group: `教育经历${suffix}`, label: "专业", value: String(e.major).trim() });
    }
    if (String(e.degree || "").trim()) {
      out.push({ group: `教育经历${suffix}`, label: "学历", value: String(e.degree).trim() });
    }
    if (String(e.start || "").trim() && String(e.end || "").trim()) {
      out.push({
        group: `教育经历${suffix}`, label: "在校时间",
        value: `${String(e.start).trim()} - ${String(e.end).trim()}`,
      });
    }
  });
  (data.work || []).forEach((w, i) => {
    const suffix = (data.work || []).length > 1 ? ` ${i + 1}` : "";
    if (String(w.company || "").trim()) {
      out.push({ group: `工作经历${suffix}`, label: "公司", value: String(w.company).trim() });
    }
    if (String(w.title || "").trim()) {
      out.push({ group: `工作经历${suffix}`, label: "职位", value: String(w.title).trim() });
    }
    const highlights = (w.highlights || []).filter(Boolean).join("\n");
    if (highlights) {
      out.push({ group: `工作经历${suffix}`, label: "工作内容", value: highlights, multiline: true });
    }
  });
  (data.projects || []).forEach((prj, i) => {
    const suffix = (data.projects || []).length > 1 ? ` ${i + 1}` : "";
    if (String(prj.name || "").trim()) {
      out.push({ group: `项目经历${suffix}`, label: "项目名称", value: String(prj.name).trim() });
    }
    if (String(prj.description || "").trim()) {
      out.push({
        group: `项目经历${suffix}`, label: "项目描述",
        value: String(prj.description).trim(), multiline: true,
      });
    }
  });
  (data.skills || []).forEach((skill) => {
    if (String(skill || "").trim()) {
      out.push({ group: "技能", label: "技能", value: String(skill).trim() });
    }
  });
  if (String(data.summary || "").trim()) {
    out.push({ group: "自我描述", label: "自我描述", value: String(data.summary).trim(), multiline: true });
  }
  return out;
}

/** 提取一个输入元素可用来做字段匹配的上下文文本：
 * placeholder / name / id / aria-label / 关联 label 文本。 */
export function inputContext(el) {
  if (!el) return "";
  const parts = [];
  for (const attr of ["placeholder", "name", "id", "aria-label"]) {
    const v = el.getAttribute && el.getAttribute(attr);
    if (v) parts.push(String(v));
  }
  if (el.labels) {
    for (const label of el.labels) parts.push(label.textContent || "");
  }
  return parts.join(" ").toLowerCase();
}

/** 给定输入上下文，在条目里找最匹配的一条。先精确子串命中 label，
 * 再按命中长度取最长者；无命中返回 null。 */
export function matchEntry(contextText, entries) {
  if (!contextText) return null;
  let best = null;
  let bestLen = 0;
  for (const entry of entries) {
    const label = String(entry.label || "").toLowerCase();
    if (!label) continue;
    if (contextText.includes(label) && label.length > bestLen) {
      best = entry;
      bestLen = label.length;
    }
  }
  return best;
}

/** React/Vue 受控组件兼容赋值：走原型 setter 触发框架感知的 input 事件。 */
export function setNativeValue(el, value) {
  if (!el) return;
  if (el.isContentEditable) {
    el.textContent = value;
    el.dispatchEvent(new InputEvent("input", { bubbles: true }));
    return;
  }
  // 沿原型链查找 value setter：不引用浏览器全局类型（HTMLInputElement 等），
  // 使同一份代码可被 node DOM 测试与扩展环境共用。
  let setter = null;
  let proto = Object.getPrototypeOf(el);
  while (proto && !setter) {
    const descriptor = Object.getOwnPropertyDescriptor(proto, "value");
    if (descriptor && descriptor.set) setter = descriptor.set;
    proto = Object.getPrototypeOf(proto);
  }
  if (setter) {
    setter.call(el, value);
  } else {
    el.value = value;
  }
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

/** 是否可填充：可见的 input/textarea/contenteditable（select 由下拉逻辑处理）。 */
export function isFillable(el) {
  if (!el) return false;
  const tag = (el.tagName || "").toLowerCase();
  const editable =
    tag === "textarea" ||
    (tag === "input" && !["hidden", "checkbox", "radio", "file", "submit", "button"].includes(el.type)) ||
    (el.isContentEditable && el.getAttribute && el.getAttribute("contenteditable") !== "false");
  if (!editable) return false;
  if (el.disabled || el.readOnly) return false;
  const view = el.ownerDocument && el.ownerDocument.defaultView;
  if (view && view.getComputedStyle) {
    const style = view.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return false;
  }
  return true;
}

/** 跳到 root 中 current 之后的下一个空输入框；无 current 时取第一个。
 * 返回该元素或 null。 */
export function nextEmptyInput(root, current) {
  const all = Array.from((root || document).querySelectorAll("input, textarea, [contenteditable='true']"));
  const fillable = all.filter(isFillable);
  const empty = fillable.filter(
    (el) => el.isContentEditable ? !(el.textContent || "").trim() : !String(el.value || "").trim(),
  );
  if (!empty.length) return null;
  if (!current) return empty[0];
  const idx = fillable.indexOf(current);
  for (const el of empty) {
    if (fillable.indexOf(el) > idx) return el;
  }
  return empty[0];
}

/** 一键全填（期二预留，MVP 只做"当前聚焦框匹配填充"）：
 * 遍历 root 中所有可填元素，能匹配条目就填。返回填充数。 */
export function fillAll(root, entries) {
  let count = 0;
  const all = Array.from((root || document).querySelectorAll("input, textarea, [contenteditable='true']"));
  for (const el of all) {
    if (!isFillable(el)) continue;
    if (String(el.value || "").trim()) continue;
    const entry = matchEntry(inputContext(el), entries);
    if (entry) {
      setNativeValue(el, entry.value);
      count += 1;
    }
  }
  return count;
}
