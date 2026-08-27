import test from "node:test";
import assert from "node:assert";
import { Window } from "happy-dom";

import {
  applyJdParseError,
  applyJdParseResult,
  jdParseErrorHtml,
} from "../../../src/resualign/static/app/format.js";
import { formFromHtml, jobCreateFormHtml, stubFetch } from "../dom-helpers.mjs";

test("applyJdParseResult fills empty fields from a successful parse", () => {
  const form = formFromHtml(jobCreateFormHtml());
  const summary = applyJdParseResult(form, {
    title: "后端工程师",
    jd_text: "Python + FastAPI，15-25K",
    company: "Acme Inc",
    city: "上海",
    source_url: "https://example.com/jobs/1",
    salary_min: 15000,
    salary_max: 25000,
    salary_currency: "CNY",
  });

  assert.equal(form.querySelector('[name="title"]').value, "后端工程师");
  assert.equal(form.querySelector('[name="jd_text"]').value, "Python + FastAPI，15-25K");
  assert.equal(form.querySelector('[name="company"]').value, "Acme Inc");
  assert.equal(form.querySelector('[name="location"]').value, "上海");
  assert.equal(form.querySelector('[name="source_url"]').value, "https://example.com/jobs/1");
  assert.equal(form.querySelector('[name="salary_min"]').value, "15000");
  assert.equal(form.querySelector('[name="salary_max"]').value, "25000");
  assert.equal(form.querySelector('[name="salary_currency"]').value, "CNY");
  assert.deepEqual(summary, {
    title: true,
    jd_text: true,
    company: true,
    location: true,
    source_url: true,
    salary_min: true,
    salary_max: true,
    salary_currency: true,
  });
});

test("applyJdParseResult never overwrites user-typed values", () => {
  const form = formFromHtml(
    jobCreateFormHtml({
      title: "我手填的标题",
      salary_min: "30000",
      salary_currency: "USD",
    }),
  );
  const summary = applyJdParseResult(form, {
    title: "解析出的标题",
    jd_text: "JD 文本",
    salary_min: 15000,
    salary_max: 25000,
    salary_currency: "CNY",
  });

  assert.equal(form.querySelector('[name="title"]').value, "我手填的标题");
  assert.equal(form.querySelector('[name="salary_min"]').value, "30000");
  assert.equal(form.querySelector('[name="salary_currency"]').value, "USD");
  assert.equal(form.querySelector('[name="salary_max"]').value, "25000");
  assert.deepEqual(summary, {
    title: false,
    jd_text: true,
    company: false,
    location: false,
    source_url: false,
    salary_min: false,
    salary_max: true,
    salary_currency: false,
  });
});

test("applyJdParseResult skips null/empty parse values", () => {
  const form = formFromHtml(jobCreateFormHtml());
  const summary = applyJdParseResult(form, {
    title: null,
    jd_text: "",
    company: undefined,
    salary_min: null,
    salary_max: null,
    salary_currency: "",
  });

  assert.equal(form.querySelector('[name="title"]').value, "");
  assert.equal(form.querySelector('[name="jd_text"]').value, "");
  assert.deepEqual(summary, {
    title: false,
    jd_text: false,
    company: false,
    location: false,
    source_url: false,
    salary_min: false,
    salary_max: false,
    salary_currency: false,
  });
});

test("jdParseErrorHtml renders reason, action and retry buttons", () => {
  const html = jdParseErrorHtml({
    reason: "该站点需要登录或权限",
    action: "请改用粘贴 JD 或更换链接重试",
  });
  assert.match(html, /解析失败/);
  assert.match(html, /该站点需要登录或权限/);
  assert.match(html, /请改用粘贴 JD 或更换链接重试/);
  assert.match(html, /data-action="use-paste-mode"/);
  assert.match(html, /data-action="retry-parse-jd"/);
});

test("jdParseErrorHtml falls back to default copy without detail", () => {
  const html = jdParseErrorHtml(undefined);
  assert.match(html, /未能从该链接提取岗位内容/);
  assert.match(html, /改用粘贴 JD/);
});

test("applyJdParseError marks the status area on failure", () => {
  const window = new Window();
  const document = window.document;
  document.body.innerHTML = '<div data-jd-parse-status></div>';
  const status = document.querySelector("[data-jd-parse-status]");

  applyJdParseError(status, { reason: "timeout", action: "稍后重试" });

  assert.match(status.className, /form-error/);
  assert.equal(status.getAttribute("role"), "alert");
  assert.match(status.innerHTML, /timeout/);
  assert.match(status.innerHTML, /稍后重试/);
  assert.match(status.innerHTML, /data-action="retry-parse-jd"/);
});

test("stubFetch lets a window serve scripted responses", async () => {
  const window = stubFetch(new Window(), async (input) => {
    assert.equal(input, "/api/jobs/parse-jd");
    return {
      ok: false,
      status: 502,
      json: async () => ({ detail: { reason: "no_content" } }),
    };
  });

  const response = await window.fetch("/api/jobs/parse-jd");
  assert.equal(response.ok, false);
  assert.equal(response.status, 502);
  assert.deepEqual(await response.json(), { detail: { reason: "no_content" } });
});
