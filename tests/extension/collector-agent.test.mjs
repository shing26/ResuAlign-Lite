import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
// happy-dom 安装在 tests/frontend/node_modules（前端测试的独立依赖树）
import { createRequire } from "node:module";
const require2 = createRequire(import.meta.url);
const { Window } = require2("../frontend/node_modules/happy-dom");

const here = dirname(fileURLToPath(import.meta.url));
const USERSCRIPT = readFileSync(
  join(here, "../../resualign-collector.user.js"),
  "utf8",
);

/** 构造一个带 GM 桩的 happy-dom 页面并加载 userscript。
 *  GM_xmlhttpRequest 桩把每次摄入 payload 记进 window.__RA_POSTS，
 *  并回 200 created（不发起真实网络）。 */
function loadCollector(html, { server = "http://127.0.0.1:8000", token = "tok" } = {}) {
  const window = new Window({ url: "http://example.com/job/1" });
  window.__GM = {};
  window.GM_setValue = (k, v) => {
    window.__GM[k] = String(v);
  };
  window.GM_getValue = (k, d) => (k in window.__GM ? window.__GM[k] : d);
  window.__RA_POSTS = [];
  window.GM_xmlhttpRequest = (opts) => {
    window.__RA_POSTS.push({
      url: opts.url,
      token: (opts.headers || {})["X-ResuAlign-Token"],
      payload: JSON.parse(opts.data || "{}"),
    });
    setTimeout(() => {
      if (opts.onload) {
        opts.onload({
          status: 200,
          responseText: JSON.stringify({ status: "created", job_id: "j-test" }),
        });
      }
    }, 0);
  };
  window.document.write(html);
  window.GM_setValue("ra_server", server);
  window.GM_setValue("ra_token", token);
  window.eval(USERSCRIPT);
  return window;
}

/** 点击后轮询等待 ingest POST 落入 __RA_POSTS（expand 流程有 ~800ms 延时）。 */
async function waitForPost(window) {
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline && window.__RA_POSTS.length === 0) {
    await new Promise((r) => setTimeout(r, 100));
  }
}


const JSONLD_PAGE = `<!doctype html><html><head><title>Python 后端 - 招聘</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting",
"title":"Python 后端开发工程师","hiringOrganization":{"name":"示例科技"},
"jobLocation":{"address":{"addressLocality":"上海"}},"description":"负责高并发后端服务"}</script>
</head><body><h1>Python 后端开发工程师</h1>
<div class="company-name">示例科技</div>
<div class="job-salary">20-35K·16薪</div>
<div class="job-detail">岗位职责：负责高并发后端服务的设计、开发与治理，参与核心交易链路的架构演进，
持续优化接口性能与稳定性。任职要求：熟悉 Python 与 FastAPI 框架，有 Redis 缓存、消息队列与
分布式系统实战经验，5 年以上工作经验，本科及以上学历；具备良好的沟通协作能力与技术热情，
能独立完成方案设计并推动落地，有大型电商平台经验者优先考虑。</div>
</body></html>`;

const HEURISTIC_PAGE = `<!doctype html><html><head><title>某公司招聘</title></head><body>
<main><h2>Java 服务端工程师</h2><div class="company">某互联网公司</div>
<p>薪资 25-40K·15薪，要求 3-5 年工作经验。</p>
<button class="expand-btn">展开全文</button>
<div id="detail" class="detail-content" style="display:none">占位</div>
<div class="job-body">岗位职责：负责订单与库存微服务的设计与迭代。任职要求：熟悉 Java/Spring
Cloud，有高并发、分布式事务经验，能独立完成方案设计与落地，具备良好沟通能力，本科及以上学历，
有大型电商平台经验优先，团队协作氛围好，期待你的加入与我们一起成长进步。</div>
</main></body></html>`;

const PLAIN_PAGE = `<!doctype html><html><head><title>购物车 - 示例商城</title></head>
<body><h1>购物车</h1><p>商品 A ¥100，商品 B ¥200，合计 ¥300。</p></body></html>`;

/* ------------------------------------------------------------------ */
/* JSON-LD 岗位页：加载即出「一键提取岗位」，payload 字段正确             */
/* ------------------------------------------------------------------ */

test("agent: JSON-LD job page surfaces the one-click button and posts a clean payload", () => {
  const window = loadCollector(JSONLD_PAGE);
  const buttons = window.document.querySelectorAll("#ra-ingest-agent");
  assert.equal(buttons.length, 1, "agent button appears on job pages");

  buttons[0].click();
  return waitForPost(window).then(() => {
    assert.equal(window.__RA_POSTS.length, 1, "one ingest POST");
    const post = window.__RA_POSTS[0];
    assert.equal(post.url, "http://127.0.0.1:8000/api/jobs/local-ingest");
    assert.equal(post.token, "tok");
    const payload = post.payload;
    assert.equal(payload.site, "agent");
    assert.equal(payload.title, "Python 后端开发工程师");
    assert.equal(payload.company, "示例科技");
    assert.match(payload.jd_text, /岗位职责/);
    assert.doesNotMatch(payload.jd_text, /_ld_description/);
    assert.ok(!("_ld_description" in payload), "internal field is stripped");
    assert.ok(payload.jd_text.length >= 20, "JD text captured");
  });
});

/* ------------------------------------------------------------------ */
/* 启发式页面：展开折叠后提取完整 JD 正文                                */
/* ------------------------------------------------------------------ */

test("agent: heuristic page without JSON-LD is detected via anchors and expanded", () => {
  const window = loadCollector(HEURISTIC_PAGE);
  const buttons = window.document.querySelectorAll("#ra-ingest-agent");
  assert.equal(buttons.length, 1, "heuristic detection works without JSON-LD");

  buttons[0].click();
  return waitForPost(window).then(() => {
    const post = window.__RA_POSTS[0];
    assert.equal(post.payload.site, "agent");
    assert.match(post.payload.jd_text, /岗位职责/);
    assert.match(post.payload.jd_text, /期待你的加入/, "expand-all clicked first");
    assert.ok(post.payload.salary_text.includes("25-40K"), "salary captured");
  });
});

/* ------------------------------------------------------------------ */
/* 非岗位页：不出按钮、不误报                                            */
/* ------------------------------------------------------------------ */

test("agent: plain non-job pages get no button", () => {
  const window = loadCollector(PLAIN_PAGE);
  assert.equal(window.document.querySelectorAll("#ra-ingest-agent").length, 0);
  assert.equal(window.__RA_POSTS.length, 0);
});

/* ------------------------------------------------------------------ */
/* SPA 导航：pushState 进入岗位页后补出按钮                              */
/* ------------------------------------------------------------------ */

test("agent: pushState navigation re-runs detection (SPA support)", () => {
  const window = loadCollector(PLAIN_PAGE);
  assert.equal(window.document.querySelectorAll("#ra-ingest-agent").length, 0);

  window.document.body.innerHTML = JSONLD_PAGE.replace(
    /^<!doctype html><html><head><title>[^<]*<\/title>/,
    "",
  ).replace(/<\/head>|<\/body>|<\/html>|<head>|<body>/g, "");
  window.history.pushState({}, "", "/job/42");
  return new Promise((resolve) => setTimeout(resolve, 30)).then(() => {
    assert.equal(
      window.document.querySelectorAll("#ra-ingest-agent").length,
      1,
      "button appears after SPA navigation to a job page",
    );
  });
});
