import { Window } from "happy-dom";

/**
 * Build a happy-dom document from HTML, mirroring the real job-create
 * form structure used by applyJdParseResult.
 */
export function jobCreateFormHtml(overrides = {}) {
  const title = overrides.title ?? "";
  const jdText = overrides.jd_text ?? "";
  const company = overrides.company ?? "";
  const location = overrides.location ?? "";
  const sourceUrl = overrides.source_url ?? "";
  const salaryMin = overrides.salary_min ?? "";
  const salaryMax = overrides.salary_max ?? "";
  const currency = overrides.salary_currency ?? "";
  return `
    <form data-form="job-create">
      <input type="text" name="title" value="${title}">
      <input type="text" name="company" value="${company}">
      <input type="text" name="location" value="${location}">
      <input type="url" name="source_url" value="${sourceUrl}">
      <input type="number" name="salary_min" value="${salaryMin}">
      <input type="number" name="salary_max" value="${salaryMax}">
      <input type="text" name="salary_currency" value="${currency}">
      <textarea name="jd_text">${jdText}</textarea>
      <div data-jd-parse-status></div>
    </form>`;
}

export function formFromHtml(html) {
  const window = new Window();
  const document = window.document;
  document.body.innerHTML = html;
  return document.querySelector("form");
}

/**
 * Install a fetch stub on a happy-dom window. `handler` receives
 * (input, options) and returns a Response-like object with `ok`,
 * `status` and `json()`.
 */
export function stubFetch(window, handler) {
  window.fetch = async (input, options) => handler(input, options);
  return window;
}
