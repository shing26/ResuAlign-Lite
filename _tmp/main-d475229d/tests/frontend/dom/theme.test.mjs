import test from "node:test";
import assert from "node:assert/strict";

import "./happy-setup.mjs";

import {
  applyTheme,
  initTheme,
} from "../../../src/resualign/static/app/theme.js";

test("initTheme keeps the delivered dark class as the default theme", () => {
  document.documentElement.classList.add("dark");
  document.documentElement.dataset.theme = "";
  try {
    localStorage.removeItem("resualign_theme");
  } catch {
    /* storage can be unavailable in embedded contexts */
  }
  assert.equal(initTheme(), "dark");
  assert.equal(document.documentElement.dataset.theme, "dark");
  assert.ok(document.documentElement.classList.contains("dark"));
});

test("applyTheme keeps html.dark in sync with data-theme", () => {
  document.documentElement.classList.add("dark");
  applyTheme("light");
  assert.equal(document.documentElement.dataset.theme, "light");
  assert.ok(!document.documentElement.classList.contains("dark"));

  applyTheme("dark");
  assert.equal(document.documentElement.dataset.theme, "dark");
  assert.ok(document.documentElement.classList.contains("dark"));
});
