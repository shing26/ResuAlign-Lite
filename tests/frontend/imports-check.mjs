import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const dir = join(root, "src/resualign/static/app");
const files = readdirSync(dir).filter((f) => f.endsWith(".js"));

const exports = new Map();
for (const f of files) {
  const src = readFileSync(join(dir, f), "utf8");
  const names = new Set();
  for (const m of src.matchAll(/export\s+(?:async\s+)?(?:function|const|class)\s+([$\w]+)/g)) names.add(m[1]);
  for (const m of src.matchAll(/export\s*\{([^}]+)\}/g)) {
    for (const n of m[1].split(",")) {
      const clean = n.trim().split(/\s+as\s+/).pop();
      if (clean) names.add(clean);
    }
  }
  for (const m of src.matchAll(/export\s*\{([^}]+)\}\s*from/g)) {
    for (const n of m[1].split(",")) {
      const clean = n.trim().split(/\s+as\s+/).pop();
      if (clean) names.add(clean);
    }
  }
  for (const m of src.matchAll(/export\s+\*\s*from/g)) names.add("*");
  exports.set(f, names);
}

let failures = 0;
for (const f of files) {
  const src = readFileSync(join(dir, f), "utf8");
  for (const m of src.matchAll(/from\s+"\.\/(\w+)\.js"/g)) {
    const dep = `${m[1]}.js`;
    if (!exports.has(dep)) {
      console.log(`MISSING MODULE: ${f} imports ./${dep}`);
      failures++;
      continue;
    }
    const local = src.slice(Math.max(0, m.index - 600), m.index);
    const importMatch = [...local.matchAll(/import\s*\{([^}]+)\}/g)].pop();
    if (!importMatch) continue;
    for (const n of importMatch[1].split(",")) {
      const name = n.trim().split(/\s+as\s+/).pop();
      if (name && !exports.get(dep).has(name) && !exports.get(dep).has("*")) {
        console.log(`MISSING EXPORT: ${f} imports '${name}' from ./${m[1]}.js`);
        failures++;
      }
    }
  }
}

console.log(failures === 0 ? "import graph OK" : `${failures} import errors`);
process.exit(failures === 0 ? 0 : 1);
