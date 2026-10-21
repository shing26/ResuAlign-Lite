/* Skipped-row detail for import / job-table sync (#146).
 *
 * The backend already returns one message per skipped row. Rendering only the
 * created/skipped counters made "6 rows were already in the library" look
 * exactly like "6 real postings were dropped", which is how the #145 data loss
 * stayed invisible for a whole release: the titles were on the wire and
 * nothing ever put them on screen.
 *
 * Pure module (no DOM at import time) so it can be unit-tested directly,
 * mirroring settings-form.js / focus-trap.js.
 */

import { esc } from "./format.js";

/* Skips that are the *expected* outcome of a re-import rather than a problem.
 * Everything else is surfaced in the open, because it may name a posting the
 * user believes is in their library. */
export const ROUTINE_SKIP_RE =
  /Duplicate job already exists|没有新行|没有可导入的行|没有待导入/;

export function classifySkipMessages(messages) {
  const routine = [];
  const notable = [];
  for (const raw of messages || []) {
    const text = String(raw == null ? "" : raw).trim();
    if (!text) continue;
    (ROUTINE_SKIP_RE.test(text) ? routine : notable).push(text);
  }
  return { routine, notable };
}

function listHtml(items) {
  return (
    `<ul class="skip-detail__list">` +
    items.map((item) => `<li>${esc(item)}</li>`).join("") +
    `</ul>`
  );
}

export function skipDetailHtml(messages) {
  const { routine, notable } = classifySkipMessages(messages);
  if (!routine.length && !notable.length) return "";
  const parts = [];
  if (notable.length) {
    parts.push(
      `<div class="skip-detail__group skip-detail__group--warn">` +
        `<strong>${notable.length} 条需要留意</strong>` +
        listHtml(notable) +
        `</div>`,
    );
  }
  if (routine.length) {
    parts.push(
      `<details class="skip-detail__group">` +
        `<summary>${routine.length} 条已跳过（已在库中）</summary>` +
        listHtml(routine) +
        `</details>`,
    );
  }
  return parts.join("");
}

export function renderSkipDetail(node, messages) {
  if (!node) return 0;
  const { notable } = classifySkipMessages(messages);
  const html = skipDetailHtml(messages);
  node.classList.add("skip-detail");
  node.innerHTML = html;
  return notable.length;
}
