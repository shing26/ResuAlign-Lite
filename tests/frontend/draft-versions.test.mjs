import { test } from "node:test";
import assert from "node:assert/strict";

import {
  draftDiffHtml,
  draftVersionsHtml,
} from "../../src/resualign/static/app/format.js";

test("versions list marks the current version and offers diff/rollback", () => {
  const html = draftVersionsHtml({
    current_version: 2,
    versions: [
      {
        version: 1,
        sha256: "a".repeat(64),
        chars: 120,
        created_at: 1700000000,
        source: "save",
        accepted_diff_ids: [],
      },
      {
        version: 2,
        sha256: "b".repeat(64),
        chars: 130,
        created_at: 1700000100,
        source: "rollback",
        source_version: 1,
        accepted_diff_ids: ["d1"],
      },
    ],
  });
  assert.match(html, /v2 当前/);
  assert.match(html, /回滚自 v1/);
  assert.match(html, /sha aaaaaaaaaa/);
  assert.match(html, /data-action="draft-version-diff" data-version="2" data-against="1"/);
  assert.equal(html.split('data-action="draft-version-rollback"').length - 1, 1);
});

test("empty version list renders a calm hint", () => {
  const html = draftVersionsHtml({ current_version: 0, versions: [] });
  assert.match(html, /还没有定稿版本/);
});

test("diff renders +/- markers and escapes content", () => {
  const html = draftDiffHtml({
    from_version: 1,
    to_version: 2,
    diff: ["--- v1", "+++ v2", "-旧行 <b>", "+新行", " 上下文"],
  });
  assert.match(html, /-旧行 &lt;b&gt;/);
  assert.match(html, /\+新行/);
  assert.doesNotMatch(html, /<b>/);
});

test("empty diff says the two versions are identical", () => {
  assert.match(draftDiffHtml({ diff: [] }), /两版内容一致/);
});
