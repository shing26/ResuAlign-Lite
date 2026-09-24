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
function loadCollector(
  html,
  {
    server = "http://127.0.0.1:8000",
    token = "tok",
    url = "http://example.com/job/1",
  } = {},
) {
  const window = new Window({ url });
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

/* 真实 实习僧 详情页结构（2026-09-24 抓取自 inn_3d3blblhe54k）。
 * 刻意把 .con-job.job_city（地点块）放在 JD 容器之前，用来证明
 * 「.con-job 泛匹配」不会再抢到地点块。 */
const SHIXISENG_PAGE = `<!doctype html><html><head>
<title>java开发实习生实习招聘-华晟讯科技实习生招聘-实习僧</title></head><body>
<div class="job_header"><div class="new_job_name">java开发实习生</div>
<div class="job_money cutom_font">100-200/天</div></div>
<div class="job_msg">100-200/天 每周 5天 实习6个月 可转正</div>
<div class="com-name">华晟讯科技</div>
<div class="job_position">重庆</div>
<div class="con-job job_city">工作地点：
重庆市渝北区金开大道166号moco2栋21-11</div>
<div class="job-content"><div class="con-job"><div class="job_til">职位描述</div>
<div class="job_part"><div class="job_detail" style="white-space:pre-wrap">1.协助完成公司项目的开发工作
2.参与需求分析，参与人员完成模块开发
3.对开发过程中出现的bug及时解决并配合项目上线
任职资格
1.本科及以上学历，计算机、软件工程等相关专业，在校大学生优先
2.熟悉Java，熟悉多线程、分布式等
3.熟悉spring、Springmvc、SpringBoot等框架
4.了解http、https协议等，对接口开发有一定了解
5.良好的沟通能力、学习能力、团队合作精神
6.有上进心和良好的工作态度，严谨的逻辑思维能力
7.良好的英文阅读能力（英文文档）及证明能力
8.接受实习生转正优先考虑，外地工作者提供住宿</div></div></div></div>
</body></html>`;

const SHIXISENG_URL = "https://www.shixiseng.com/intern/inn_3d3blblhe54k";

/* 腾讯招聘详情页结构（2026-09-24 抓取自 jobdesc.html）：分享弹窗里有个
 * 「分享岗位」h1，会骗过朴素的标题抓取；JD 容器里也混着分享块。 */
const TENCENT_PAGE = `<!doctype html><html><head>
<title>岗位详情 | 腾讯招聘</title></head><body>
<div class="recruit-content"><div class="recruit-title jobdesc-content">
<div class="job-text-wrapper">
<span class="job-recruit-title">J3-UE5微恐射击-系统策划</span>
<span class="job-recruit-location">深圳</span></div>
<div class="recruit-content-right"><div class="recruit-share">
<span class="share-text">分享</span>
<div id="share-detail" class="share-list">
<div class="share-list-header"><h1>分享岗位</h1></div>
<h2 class="title">方式1:复制岗位链接</h2>
<h2 class="title">方式2:分享岗位海报</h2>
<p>手机扫描二维码分享</p></div></div></div></div>
<div class="recruit-detail">
<div class="duty-title">岗位职责</div>
<p>1.负责UE5微恐射击项目的系统策划与玩法设计，撰写策划案并推动落地实施，覆盖核心战斗、关卡与数值模块；</p>
<p>2.与程序、美术紧密协作，跟进功能开发与验收，持续打磨核心战斗体验，并对上线后的数据表现负责。</p>
<div class="duty-title">岗位要求</div>
<p>1.三年以上游戏策划经验，有射击或动作类项目完整上线经历，熟悉UE引擎工作流与版本迭代节奏；</p>
<p>2.具备良好的逻辑思维与沟通能力，能独立承担模块设计，并对玩法体验有自己的判断与追求。</p>
</div></div></body></html>`;

/* 网易社会招聘详情页结构（2026-09-24 抓取自 job-detail.html）：容器里
 * 带二维码分享块，标题在 .posi-name，地点与工时挤在一行。 */
const NETEASE_PAGE = `<!doctype html><html><head>
<title>职位详情 | 网易社会招聘</title></head><body>
<div class="m-job-detail m-job-detail-zh"><div class="job-detail-header-c">
<p class="posi-name">高级/资深视觉算法工程师（表情）</p>
<p class="posi-sc-name">全职&nbsp;&nbsp;|&nbsp;&nbsp;杭州市&nbsp;&nbsp;|&nbsp;&nbsp;2026-09-23 更新</p>
<div class="job-de-de-code"><canvas class="m-job-qr-code"></canvas>
<p class="text-c">微信扫码分享该职位</p></div></div>
<div class="job-detail-detail"><div class="job-de-de-left">
<p class="title">职位描述</p>
<div class="content">1、负责3D数字人相关业务的算法研发和落地工作，主导基于PyTorch等框架的高性能服务开发；
2、优化表情和动作算法在工程化落地中的性能表现，设计高吞吐、低延迟的表情与动作处理系统；
3、深入理解计算机视觉、多模态交互、人脸表情及人体动作相关算法原理，推动算法在业务场景中落地。</div>
</div></div></div></body></html>`;

/* 识别不出、但明显是岗位页：只出兜底的「抓取页面区域」入口。 */
const VAGUE_JOB_PAGE = `<!doctype html><html><head>
<title>某某科技 招聘</title></head><body>
<div class="wrap"><div class="col">
<p>岗位职责：负责平台服务端的功能开发与线上维护，配合产品完成需求评审、排期与上线验收，持续优化接口性能与稳定性。</p>
<p>团队介绍：我们是一支专注于企业服务的工程团队，方向覆盖账号体系、权限模型、计费结算与数据链路，服务于数十万企业客户。</p>
<p>办公环境：开放式工位，弹性上下班，提供免费三餐与健身房，园区班车覆盖主要地铁线路，工位配备双屏与外设自选额度。</p>
<p>成长路径：新人导师制，季度技术分享，鼓励参与开源项目并支持内部转岗与轮岗，每年有两次晋升评审机会与配套的调薪机制。</p>
<p>其他说明：本岗位面向有相关经验的同学，简历会在三个工作日内完成初筛并反馈结果；面试共三轮，均为线上进行，全程大约两周，录用后由专属 HR 跟进入职材料与背调安排。</p>
<p>联系方式：如有疑问可在工作日的十点到十八点之间联系招聘负责人，我们会尽量当天回复每一条咨询。</p>
</div></div>
</body></html>`;

/* 招聘列表页：有招聘信息但没有 JD 锚点，仍应提示可抓取。 */
const RECRUIT_LIST_PAGE = `<!doctype html><html><head>
<title>社会招聘 - 示例科技</title></head><body>
<div class="list">
<div class="row"><span>高级后端工程师</span><span>上海</span><span>30-50K</span></div>
<div class="row"><span>前端工程师</span><span>北京</span><span>25-40K</span></div>
<div class="row"><span>测试开发工程师</span><span>深圳</span><span>20-35K</span></div>
<div class="row"><span>产品经理</span><span>杭州</span><span>28-45K</span></div>
<div class="row"><span>数据分析师</span><span>成都</span><span>18-30K</span></div>
<p>共 12 个在招职位，欢迎投递简历，我们会在三个工作日内联系您，面试共两轮，全程线上进行。</p>
<p>福利待遇：五险一金、补充医疗、年度体检、弹性工作制与带薪年假，全职岗位均可参与年度调薪。</p>
</div></body></html>`;

/* 普通长文章：不该弹悬浮窗。 */
const ARTICLE_PAGE = `<!doctype html><html><head>
<title>如何挑选一台适合自己的笔记本电脑</title></head><body>
<article><p>选购笔记本时，屏幕、续航与散热是三个最关键的维度。屏幕要看分辨率与色域，
续航要看电池容量与整机功耗，散热则决定了长时间高负载下会不会降频。</p>
<p>如果你主要用来写代码，优先考虑内存容量与键盘手感，十六吉字节起步会更从容；
如果经常外出，重量与充电器体积就比极限性能更重要。</p>
<p>价格方面，同一档配置在不同渠道的差价可能达到百分之十五，促销节点通常集中在
电商大促期间，提前加购并对比历史价格能省下不少预算。</p>
<p>最后提醒一句：先想清楚自己的使用场景，再去对比参数表，否则很容易为用不到的性能买单。</p>
</article></body></html>`;

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
    assert.equal(
      payload.job_page_url,
      "http://example.com/job/1",
      "job_page_url must survive the local `location` binding (regression)",
    );
    assert.match(payload.jd_text, /岗位职责/);
    assert.doesNotMatch(payload.jd_text, /_ld_description/);
    assert.ok(!("_ld_description" in payload), "internal field is stripped");
    assert.ok(payload.jd_text.length >= 20, "JD text captured");
  });
});

/* ------------------------------------------------------------------ */
/* 实习僧详情页：specific 提取正确字段 + URL 查重键                      */
/* ------------------------------------------------------------------ */

test("shixiseng: specific payload extracts real site fields and page URL", () => {
  const window = loadCollector(SHIXISENG_PAGE, { url: SHIXISENG_URL });
  const payload = window.__RA_DEBUG.shixisengPayload();

  assert.equal(payload.site, "shixiseng");
  assert.equal(payload.title, "java开发实习生");
  assert.equal(payload.company, "华晟讯科技");
  assert.equal(payload.salary_text, "100-200/天");
  assert.equal(
    payload.location,
    "重庆市渝北区金开大道166号moco2栋21-11",
    "location label prefix is stripped",
  );
  assert.equal(payload.job_page_url, SHIXISENG_URL);
  assert.match(payload.jd_text, /任职资格/);
  assert.match(payload.jd_text, /SpringBoot/);
  assert.doesNotMatch(payload.jd_text, /工作地点/);
  assert.ok(payload.jd_text.length >= 200, "full JD body captured");
});

test("shixiseng: specific button posts the corrected payload", () => {
  const window = loadCollector(SHIXISENG_PAGE, { url: SHIXISENG_URL });
  const buttons = window.document.querySelectorAll("#ra-ingest-specific");
  assert.equal(buttons.length, 1, "specific button appears on detail pages");

  buttons[0].click();
  return waitForPost(window).then(() => {
    const payload = window.__RA_POSTS[0].payload;
    assert.equal(payload.site, "shixiseng");
    assert.equal(payload.title, "java开发实习生");
    assert.equal(payload.company, "华晟讯科技");
    assert.equal(payload.job_page_url, SHIXISENG_URL);
  });
});

/* ------------------------------------------------------------------ */
/* 实习僧详情页：通用 Agent 也能识别（修复前 agent 按钮为 0）            */
/* ------------------------------------------------------------------ */

test("shixiseng: generic agent detects the page and posts the JD body", () => {
  const window = loadCollector(SHIXISENG_PAGE, { url: SHIXISENG_URL });
  const buttons = window.document.querySelectorAll("#ra-ingest-agent");
  assert.equal(buttons.length, 1, "agent button now appears on shixiseng");

  const detected = window.__RA_DEBUG.detectAgentPage();
  assert.ok(detected, "detectAgentPage returns a payload");
  assert.equal(detected.title, "java开发实习生");
  assert.equal(detected.company, "华晟讯科技");
  assert.equal(detected._container_kind, "explicit");

  buttons[0].click();
  return waitForPost(window).then(() => {
    const payload = window.__RA_POSTS[0].payload;
    assert.equal(payload.site, "agent");
    assert.equal(payload.job_page_url, SHIXISENG_URL);
    assert.match(payload.jd_text, /任职资格/);
    assert.ok(!("_ld_description" in payload));
  });
});

/* ------------------------------------------------------------------ */
/* 官网招聘页（腾讯）：分享弹窗不能污染标题，也不能混进 JD              */
/* ------------------------------------------------------------------ */

test("careers: tencent-shaped page ignores the share popup", () => {
  const window = loadCollector(TENCENT_PAGE, {
    url: "https://careers.tencent.com/jobdesc.html?postId=1",
  });
  const payload = window.__RA_DEBUG.agentPayload();

  assert.equal(payload.title, "J3-UE5微恐射击-系统策划");
  assert.equal(payload.company, "腾讯", "company recovered from <title> suffix");
  assert.equal(payload.location, "深圳");
  assert.match(payload.jd_text, /岗位职责/);
  assert.match(payload.jd_text, /系统策划/);
  assert.doesNotMatch(payload.jd_text, /分享岗位|复制岗位链接|手机扫描二维码/);
  assert.equal(
    window.document.querySelectorAll("#ra-ingest-agent").length,
    1,
    "generic agent detects the page",
  );
});

/* ------------------------------------------------------------------ */
/* 官网招聘页（网易）：二维码分享块剔除，地点从拼接行里挑出来           */
/* ------------------------------------------------------------------ */

test("careers: netease-shaped page strips the QR block and splits location", () => {
  const window = loadCollector(NETEASE_PAGE, {
    url: "https://hr.163.com/job-detail.html?id=1",
  });
  const payload = window.__RA_DEBUG.agentPayload();

  assert.equal(payload.title, "高级/资深视觉算法工程师（表情）");
  assert.equal(payload.company, "网易");
  assert.equal(payload.location, "杭州市");
  assert.match(payload.jd_text, /3D数字人/);
  assert.doesNotMatch(payload.jd_text, /扫码|二维码/);
});

/* ------------------------------------------------------------------ */
/* 英文 ATS：<title> 里的「... at Company」用来补公司名                 */
/* ------------------------------------------------------------------ */

test("careers: english ATS title supplies the company name", () => {
  const window = loadCollector(PLAIN_PAGE, {
    url: "https://job-boards.greenhouse.io/gitlab/jobs/1",
  });
  window.document.title = "Job Application for AI Engineer at GitLab";
  assert.equal(window.__RA_DEBUG.companyFromSiteName(), "GitLab");
});

/* ------------------------------------------------------------------ */
/* 识别不出的岗位页：仍给「抓取页面区域」兜底入口                        */
/* ------------------------------------------------------------------ */

test("careers: unrecognized job page still offers the region picker", () => {
  const window = loadCollector(VAGUE_JOB_PAGE, {
    url: "https://jobs.example.com/opening/1",
  });
  assert.equal(
    window.document.querySelectorAll("#ra-ingest-agent").length,
    0,
    "auto-detection stays conservative",
  );
  assert.equal(
    window.document.querySelectorAll("#ra-pick-region").length,
    1,
    "region picker is offered as the fallback",
  );
});

/* ------------------------------------------------------------------ */
/* 区域抓取：点选任意元素即用其正文入库                                  */
/* ------------------------------------------------------------------ */

test("region picker ingests the clicked element's text", () => {
  const window = loadCollector(PLAIN_PAGE);
  window.__RA_DEBUG.startRegionPick();
  const target = window.document.createElement("div");
  target.textContent =
    "岗位职责：负责交易链路的后端服务设计与开发，任职要求：熟悉 Java 与分布式系统，" +
    "具备良好的沟通协作能力，能独立完成方案设计并推动落地。";
  window.document.body.appendChild(target);
  target.click();

  return waitForPost(window).then(() => {
    assert.equal(window.__RA_POSTS.length, 1, "one ingest POST");
    const payload = window.__RA_POSTS[0].payload;
    assert.equal(payload.site, "agent");
    assert.match(payload.jd_text, /负责交易链路的后端服务设计与开发/);
    assert.ok(!("_container_kind" in payload), "internal fields are stripped");
  });
});

/* ------------------------------------------------------------------ */
/* 有招聘信息但抓不出 JD 的页面：悬浮窗提示可抓取                        */
/* ------------------------------------------------------------------ */

test("recruit: listing page with no JD anchor still prompts to collect", () => {
  const window = loadCollector(RECRUIT_LIST_PAGE, {
    url: "https://jobs.example.com/social",
  });
  assert.equal(
    window.document.querySelectorAll("#ra-ingest-agent").length,
    0,
    "no confident JD container on a listing page",
  );
  assert.equal(
    window.document.querySelectorAll("#ra-ingest-page").length,
    1,
    "整页抓取入口出现",
  );
  assert.equal(window.document.querySelectorAll("#ra-pick-region").length, 1);
  assert.match(
    window.document.querySelector("#resualign-collector-float").innerText,
    /检测到招聘信息/,
    "悬浮窗给出明确提示",
  );
});

test("recruit: plain article page stays quiet", () => {
  const window = loadCollector(ARTICLE_PAGE, {
    url: "https://example.com/blog/laptop",
  });
  assert.equal(window.document.querySelectorAll("#ra-ingest-page").length, 0);
  assert.equal(window.document.querySelectorAll("#ra-pick-region").length, 0);
  assert.equal(window.document.querySelectorAll("#ra-ingest-agent").length, 0);
});

test("recruit: 抓取整页正文 ingests the page body", () => {
  const window = loadCollector(RECRUIT_LIST_PAGE, {
    url: "https://jobs.example.com/social",
  });
  window.document.querySelector("#ra-ingest-page").click();
  return waitForPost(window).then(() => {
    const payload = window.__RA_POSTS[0].payload;
    assert.equal(payload.site, "agent");
    assert.match(payload.jd_text, /高级后端工程师/);
    assert.match(payload.jd_text, /五险一金/);
    assert.doesNotMatch(
      payload.jd_text,
      /检测到招聘信息|抓取页面区域|抓取整页正文|连接自检/,
      "collector's own UI must not leak into the ingested text",
    );
  });
});

test("recruit: 隐藏 dismisses the float for the current page", () => {
  const window = loadCollector(RECRUIT_LIST_PAGE, {
    url: "https://jobs.example.com/social",
  });
  window.document.querySelector("#ra-dismiss-float").click();
  assert.equal(window.document.querySelectorAll("#ra-pick-region").length, 0);
  assert.equal(window.document.querySelectorAll("#ra-ingest-page").length, 0);
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
