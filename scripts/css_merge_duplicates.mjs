#!/usr/bin/env node
/* 结构债 Phase 2：删除「完全被后续同选择器规则覆盖」的冗余规则（安全子集）。
 *
 * 判定：同一上下文（同一 @layer + 同一组 @media 嵌套）里选择器相同、特异性
 * 相同；若一条规则声明的每个属性都在后面同上下文同选择器的规则里又声明过，
 * 它的每个属性值都已被后者覆盖，删除不改变最终胜出者。
 *
 * 为什么不做「拼接合并」：试过把剩余重复规则合并到最后一条，20 张视觉基线
 * 出现 14%–32% 的移动端回归——原因是声明被移动到最后一条的位置后，会越过
 * 夹在中间的 @media 覆盖（层/媒体上下文不同，但同选择器），级联结果改变。
 * 正确的下一步是「按属性保留各自原位置」的合并（Phase 2b），这里不做。
 *
 * 用法：
 *   node scripts/css_merge_duplicates.mjs            # dry-run 报告
 *   node scripts/css_merge_duplicates.mjs --write    # 写回 styles.css
 */
import { readFileSync, writeFileSync } from "node:fs";
import { groupByContextSelector, parseRules } from "./css-rules.mjs";

const CSS_PATH = "src/resualign/static/styles.css";
const args = process.argv.slice(2);
const write = args.includes("--write");

const raw = readFileSync(CSS_PATH, "utf8");
const rules = parseRules(raw);
const groups = groupByContextSelector(rules);

const redundant = [];
let sameContextDuplicates = 0;
let duplicateGroups = 0;

for (const group of groups.values()) {
  if (group.length < 2) continue;
  duplicateGroups += 1;
  sameContextDuplicates += group.length - 1;

  const coveredFlags = group.map((_rule, index) => {
    if (index === group.length - 1) return false;
    const laterProps = new Set();
    for (let later = index + 1; later < group.length; later += 1) {
      for (const prop of group[later].props.keys()) laterProps.add(prop);
    }
    return [...group[index].props.keys()].every((prop) => laterProps.has(prop));
  });
  for (const [index, rule] of group.entries()) {
    if (coveredFlags[index]) redundant.push(rule);
  }
}

console.log(
  `rules: ${rules.length}; same-context duplicate groups: ${duplicateGroups}; ` +
    `duplicate defs: ${sameContextDuplicates}; redundant removable: ${redundant.length}`,
);

if (!write) {
  console.log("dry-run：加 --write 执行（只做安全删除）");
  process.exit(0);
}

const edits = [];
for (const rule of redundant) {
  edits.push({ start: rule.start, end: rule.end + 1, text: "" });
}

/* 同一位置可能同时被「删规则」和「替换规则体」命中（不会，bodyStart 在 start 之后），
 * 但仍按 start 降序、同 start 时先处理较大的 end，避免偏移错乱。 */
edits.sort((a, b) => b.start - a.start || b.end - a.end);
let output = raw;
for (const edit of edits) {
  output = output.slice(0, edit.start) + edit.text + output.slice(edit.end);
}
/* 合并/删除可能把某个 @media 清空。空 at-rule 块没有效果，但会触发
 * 「css has no empty rule bodies」门禁，顺手删掉（反复多轮处理嵌套）。 */
let previous;
do {
  previous = output;
  output = output.replace(/@(media|supports)[^{}]*\{\s*\}/g, "");
} while (output !== previous);
output = output.replace(/\n{3,}/g, "\n\n");
writeFileSync(CSS_PATH, output, "utf8");
console.log(`applied ${edits.length} edits (write done)`);
