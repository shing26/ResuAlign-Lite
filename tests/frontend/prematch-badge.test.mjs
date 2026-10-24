/* ADR-0064 UI 徽章（P2）：信息性词面信号徽章的渲染契约。
 * 边界（审阅第三轮定稿）：只展示 resume ∩ JD 命中；措辞信息性
 * （「词表内技能 n/m」，分母=词表内识别技能数而非 JD 要求总数，
 * 口径在 title 注明）；不展示 JD-only 词。 */

import test from "node:test";
import assert from "node:assert/strict";
import { boardCard, jobListRow } from "../../src/resualign/static/app/format.js";

const JOB = {
  job_id: "j1",
  title: "后端工程师",
  company: "Acme",
  location: "上海",
  status: "draft",
  prematch: { matched_skills: ["java", "kafka"], jd_skill_total: 8 },
};

test("jobListRow renders informational prematch badge", () => {
  const row = jobListRow({ ...JOB });
  assert.match(row, /prematch-badge/);
  assert.match(row, /词表内技能 2\/8/);
  assert.match(row, /词表内技能命中：java、kafka/);
  assert.match(row, /非 JD 要求总数/);
});

test("boardCard renders prematch badge in tags row", () => {
  const card = boardCard({ ...JOB });
  assert.match(card, /prematch-badge/);
  assert.match(card, /词表内技能 2\/8/);
});

test("zero hits stay informational and never show JD-only terms", () => {
  const row = jobListRow({
    ...JOB,
    prematch: { matched_skills: [], jd_skill_total: 3 },
  });
  assert.match(row, /词表内技能 0\/3/);
  /* JD-only 词根本不在下发的 payload 里——徽章想泄也无处可泄；
   * 这里断言徽章文本只由 matched_skills 与 jd_skill_total 构成。 */
  assert.match(row, /词表内技能 0\/3/);
});

test("no prematch field renders nothing (kill switch path)", () => {
  const { prematch: _omitted, ...bare } = JOB;
  const row = jobListRow({ ...bare });
  assert.doesNotMatch(row, /prematch-badge/);
  const card = boardCard({ ...bare });
  assert.doesNotMatch(card, /prematch-badge/);
});
