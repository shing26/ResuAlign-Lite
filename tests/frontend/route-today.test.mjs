/* #152: #/today 是死路由 —— URL 停在今日待办，页面却是 default 分支的
 * 驾驶舱。v3 重做把「今日待办」从导航移除了，但 format.js 的
 * ROUTE_NAMES 留着 "today"，于是 parseHashValue 把它「认下来」，
 * handleRoute 却根本没有对应视图，只能落进 default。
 *
 * 修法：ROUTE_NAMES 摘掉 today，handleRoute 补一条显式重定向，
 * 并用 replaceState 把 URL 一起纠正。
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const read = (name) =>
  readFileSync(join(here, "../../src/resualign/static/app", name), "utf8");

/* 仓库是 CRLF，正则一律用 \r?\n，别写死 \n。 */
const formatSrc = read("format.js");
const mainSrc = read("main.js");

const routeNames = () => {
  const names = formatSrc.match(/const ROUTE_NAMES = \[([^\]]*)\]/);
  assert.ok(names, "ROUTE_NAMES declaration not found");
  return names[1]
    .split(",")
    .map((item) => item.trim().replace(/^["']|["']$/g, ""))
    .filter(Boolean);
};

test("#152: ROUTE_NAMES no longer claims a route nobody renders", () => {
  assert.ok(
    !routeNames().includes("today"),
    "today must not be a known route name",
  );
});

test("#152: #/today redirects to the dashboard and corrects the URL", () => {
  const todayCase = mainSrc.match(/case "today":[\s\S]*?break;/);
  assert.ok(todayCase, "handleRoute must handle 'today' explicitly");
  assert.match(
    todayCase[0],
    /replaceState\([^)]*#\/dashboard/,
    "the redirect must rewrite the hash, not just render another view",
  );
  assert.match(todayCase[0], /renderDashboard\(/);
});

test("#152: every ROUTE_NAMES entry has a case in handleRoute", () => {
  const switchBody = mainSrc.match(/async function handleRoute[\s\S]*?\r?\n}\r?\n/);
  assert.ok(switchBody, "handleRoute not found");
  for (const route of routeNames()) {
    // 'resumes' shares the 'resume' case, so accept either spelling.
    const handled =
      switchBody[0].includes(`case "${route}":`) ||
      (route === "resumes" && switchBody[0].includes('case "resume":'));
    assert.ok(
      handled,
      `ROUTE_NAMES lists "${route}" but handleRoute has no case for it`,
    );
  }
});
