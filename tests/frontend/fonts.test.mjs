import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const staticDir = join(root, "src/resualign/static");
const fontsDir = join(staticDir, "fonts");
const stylesCss = readFileSync(join(staticDir, "styles.css"), "utf8");

const ASSETS = [
  {
    name: "inter-latin-wght-normal.woff2",
    sha256: "3100e775e8616cd2611beecfa23a4263d7037586789b43f035236a2e6fbd4c62",
  },
  {
    name: "jetbrains-mono-latin-wght-normal.woff2",
    sha256: "18be452724bfdc236c074ca94a249a7f41a86752c7d04ab258ce9ed5651f6a7e",
  },
  {
    name: "LICENSE-Inter.txt",
    sha256: "5b9321a4298cfeb6b34354164a1c3afc3db114569984c502b9b35d988fd58c57",
  },
  {
    name: "LICENSE-JetBrainsMono.txt",
    sha256: "b2fe5e8987594e9ffd1d2ca52a2f5d73eb8335243893c5d6254b5ad69269591d",
  },
];

function sha256(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function extractLayerText(css, layerName) {
  const marker = new RegExp(`@layer\\s+${layerName}\\s*\\{`, "g");
  const match = marker.exec(css);
  assert.ok(match, `missing @layer ${layerName}`);
  const start = match.index + match[0].length - 1;
  let depth = 0;
  for (let i = start; i < css.length; i += 1) {
    if (css[i] === "{") depth += 1;
    if (css[i] === "}") {
      depth -= 1;
      if (depth === 0) return css.slice(start + 1, i);
    }
  }
  assert.fail(`unclosed @layer ${layerName}`);
}

test("B8 vendors local font binaries with pinned hashes", () => {
  for (const asset of ASSETS) {
    assert.equal(
      sha256(join(fontsDir, asset.name)),
      asset.sha256,
      `${asset.name} must match the reviewed asset`,
    );
  }
  assert.match(
    readFileSync(join(fontsDir, "inter-latin-wght-normal.woff2")).subarray(0, 4).toString("ascii"),
    /^wOF2$/,
  );
  assert.match(
    readFileSync(join(fontsDir, "jetbrains-mono-latin-wght-normal.woff2"))
      .subarray(0, 4)
      .toString("ascii"),
    /^wOF2$/,
  );
});

test("B8 selects the vendored variable fonts before system fallbacks", () => {
  const tokens = extractLayerText(stylesCss, "tokens");
  assert.match(tokens, /--font-ui:\s*"Inter Variable",/);
  assert.match(tokens, /--font-mono:\s*"JetBrains Mono",/);
  assert.match(tokens, /--font-num:\s*"JetBrains Mono",\s*"Inter Variable",/);
});

test("B8 registers only local text fonts in the tokens layer", () => {
  const tokens = extractLayerText(stylesCss, "tokens");
  const faces = [...tokens.matchAll(/@font-face\s*\{([\s\S]*?)\}/g)].map(
    (match) => match[1],
  );
  assert.equal(faces.length, 2, "exactly two approved text font faces");

  const inter = faces.find((face) => /font-family:\s*"Inter Variable"/.test(face));
  assert.ok(inter, "Inter Variable face");
  assert.match(inter, /font-display:\s*swap/);
  assert.match(inter, /font-weight:\s*100 900/);
  assert.match(
    inter,
    /url\("\/static\/fonts\/inter-latin-wght-normal\.woff2"\)/,
  );

  const mono = faces.find((face) => /font-family:\s*"JetBrains Mono"/.test(face));
  assert.ok(mono, "JetBrains Mono face");
  assert.match(mono, /font-display:\s*swap/);
  assert.match(mono, /font-weight:\s*100 800/);
  assert.match(
    mono,
    /url\("\/static\/fonts\/jetbrains-mono-latin-wght-normal\.woff2"\)/,
  );

  assert.doesNotMatch(stylesCss, /@import\s+url\(/i);
  assert.doesNotMatch(
    stylesCss,
    /url\(\s*["']?https?:\/\/[^)"']+\.(?:woff2?|ttf|otf)/i,
  );
});

test("B8 ships the SIL Open Font License for both families", () => {
  for (const name of ["LICENSE-Inter.txt", "LICENSE-JetBrainsMono.txt"]) {
    const license = readFileSync(join(fontsDir, name), "utf8");
    assert.match(license, /SIL OPEN FONT LICENSE Version 1\.1/);
    assert.match(license, /Copyright 2020 The .+ Project Authors/);
  }
});
