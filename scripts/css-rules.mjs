/* CSS 规则解析（结构债 Phase 2 共用，无第三方依赖）
 *
 * 输出每条规则的：选择器、声明 Map、原文偏移、上下文（@layer/@media/... 链）。
 * 注释替换为等长空格，保证 offset 与原文一致，便于安全回写。
 */

export function stripComments(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, (comment) => " ".repeat(comment.length));
}

export function parseRules(rawCss) {
  const text = stripComments(rawCss);
  const rules = [];
  const stack = []; // { prelude, preludeStart, bodyStart, kind: "at"|"rule" }
  let buffer = "";
  let bufferStart = 0;
  let inKeyframes = 0;

  const contextOf = (frames) =>
    frames
      .filter((frame) => frame.kind === "at")
      .map((frame) => frame.prelude)
      .join(" > ");

  for (let index = 0; index < text.length; index += 1) {
    const ch = text[index];
    if (ch === "{") {
      const prelude = buffer.trim().replace(/\s+/g, " ");
      const leading = buffer.length - buffer.trimStart().length;
      const preludeStart = bufferStart + leading;
      const isAt = prelude.startsWith("@");
      if (isAt && prelude.startsWith("@keyframes")) inKeyframes += 1;
      stack.push({
        prelude,
        preludeStart,
        bodyStart: index + 1,
        kind: isAt ? "at" : "rule",
      });
      buffer = "";
      bufferStart = index + 1;
      continue;
    }
    if (ch === "}") {
      const frame = stack.pop();
      if (frame && frame.kind === "at" && frame.prelude.startsWith("@keyframes")) {
        inKeyframes = Math.max(0, inKeyframes - 1);
      }
      if (frame && frame.kind === "rule" && !inKeyframes) {
        const props = new Map();
        for (const decl of text.slice(frame.bodyStart, index).split(";")) {
          const trimmed = decl.trim();
          if (!trimmed) continue;
          const colon = trimmed.indexOf(":");
          if (colon < 0) continue;
          const name = trimmed.slice(0, colon).trim();
          if (!name || name.startsWith("--") || name.includes("{") || name.includes("}")) {
            continue;
          }
          props.set(name, trimmed.slice(colon + 1).trim());
        }
        if (props.size > 0) {
          rules.push({
            selector: frame.prelude,
            props,
            bodyStart: frame.bodyStart,
            start: frame.preludeStart,
            end: index,
            context: contextOf(stack),
          });
        }
      }
      buffer = "";
      bufferStart = index + 1;
      continue;
    }
    if (ch === ";") {
      buffer = "";
      bufferStart = index + 1;
      continue;
    }
    buffer += ch;
  }
  return rules;
}

/** 同一上下文内的重复选择器分组：key = context||selector */
export function groupByContextSelector(rules) {
  const groups = new Map();
  for (const rule of rules) {
    const key = `${rule.context}||${rule.selector}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(rule);
  }
  return groups;
}
