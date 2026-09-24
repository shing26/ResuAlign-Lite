// ==UserScript==
// @name         ResuAlign Local Collector
// @namespace    https://127.0.0.1:8000/
// @version      0.3.1
// @description  划词 / 实习僧 / 通用岗位页智能提取——一键摄入 ResuAlign（本地工作台）
// @author       ResuAlign
// @match        http://*/*
// @match        https://*/*
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_xmlhttpRequest
// @grant        GM_registerMenuCommand
// @connect      127.0.0.1
// @connect      localhost
// @run-at       document-idle
// ==/UserScript==

/* ResuAlign V4 客户端摄入器（ADR-0028）。
 *
 * Specific 模式先适配实习僧（shixiseng.com）岗位详情页；Universal 模式
 * 监听 window.getSelection()，划词后通过右下角浮层把选区 JD 发给
 * POST /api/jobs/local-ingest。服务地址与 Token 存于 GM_setValue。
 */
(function () {
  "use strict";

  const DEFAULT_SERVER = "http://127.0.0.1:8000";
  const SERVER_KEY = "ra_server";
  const TOKEN_KEY = "ra_token";
  const MAX_JD_LENGTH = 100000;

  let configModal = null;
  let floatBox = null;
  let selectedText = "";
  let lastFeedbackText = "";
  let ignoreSelection = false;

  function loadConfig() {
    return {
      server: String(GM_getValue(SERVER_KEY, "") || "").trim(),
      token: String(GM_getValue(TOKEN_KEY, "") || "").trim(),
    };
  }

  function saveConfig(server, token) {
    GM_setValue(SERVER_KEY, String(server || "").trim());
    GM_setValue(TOKEN_KEY, String(token || "").trim());
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(
      /[&<>"']/g,
      (ch) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[ch],
    );
  }

  function escapeAttr(value) {
    return escapeHtml(value).replace(/`/g, "&#96;");
  }

  function isShixiseng() {
    return /(^|\.)shixiseng\.com$/i.test(location.hostname);
  }

  function isShixisengDetail() {
    return (
      isShixiseng() &&
      (/\/intern\//i.test(location.pathname) ||
        /\/job\//i.test(location.pathname))
    );
  }

  function firstText(selectors) {
    for (const selector of selectors) {
      const node = document.querySelector(selector);
      const value = node && node.innerText.trim();
      if (value) return value;
    }
    return "";
  }

  /* ---------------------------------------------------------------- */
  /* 通用清洗：官网招聘页的 DOM 五花八门，但「UI 杂音」高度重复。       */
  /* 下面这组工具负责：识别杂音文案、剥掉弹窗/二维码/分享块、          */
  /* 从 <title> 反推岗位名与公司名。所有函数均为纯函数。               */
  /* ---------------------------------------------------------------- */

  /** 页面级杂音文案（分享弹窗、二维码、导航、面包屑等）。 */
  const CHROME_LINE_RE =
    /^(分享|分享岗位|分享职位|收藏|举报|打印|返回|返回顶部|首页|登录|注册|关闭|复制|点击复制|方式\s*[12１２]|手机扫描二维码分享|微信扫码分享该职位|扫码分享|扫码查看|二维码|慎防招聘诈骗|招贤纳士|职位详情|岗位详情|职位列表|岗位列表|相关职位|相似职位|热门职位|更多职位|申请职位|立即申请|投递简历|展开|收起)$/;

  /** 页面级杂音容器（分享/二维码/弹窗/推荐/页脚/导航）。 */
  const CHROME_SELECTOR = [
    "#resualign-collector-float",
    "#resualign-collector-config",
    "#resualign-collector-picker",
    "[class*='share']",
    "[id*='share']",
    "[class*='qrcode']",
    "[class*='qr-code']",
    "[class*='qr_code']",
    "[class*='popover']",
    "[class*='popup']",
    "[class*='dialog']",
    "[class*='modal']",
    "[class*='breadcrumb']",
    "[class*='recommend']",
    "[class*='related']",
    "[class*='hot-job']",
    "[class*='hotjob']",
    "nav",
    "header",
    "footer",
    "script",
    "style",
    "noscript",
  ].join(",");

  /** 文案级杂音判定：空串、纯 UI 词、扫码/分享句都算杂音。 */
  function isChromeText(value) {
    const text = String(value || "").replace(/\s+/g, "").trim();
    if (!text) return true;
    if (CHROME_LINE_RE.test(text)) return true;
    if (/扫码|二维码|分享该职位|复制岗位链接|慎防招聘诈骗/.test(text)) {
      return true;
    }
    if (/^(更新于|发布于|点击了解|浏览\d|已有\d)/.test(text)) return true;
    return false;
  }

  /** 取第一个「不像 UI 杂音」的候选；逐个匹配节点，跳过弹窗标题。 */
  function firstMeaningfulText(selectors) {
    for (const selector of selectors) {
      for (const node of document.querySelectorAll(selector)) {
        const value = (node.innerText || "").trim();
        if (value && !isChromeText(value)) return value;
      }
    }
    return "";
  }

  /** JSON-LD 的 description 常带 HTML 标签：转成纯文本再入库。 */
  function stripHtml(value) {
    const text = String(value || "");
    if (!/[<>&]/.test(text)) return text.trim();
    const holder = document.createElement("div");
    holder.innerHTML = text.replace(
      /<(br|\/p|\/div|\/li|\/h[1-6])\s*\/?>/gi,
      "\n",
    );
    return (holder.textContent || "")
      .replace(/\u00a0/g, " ")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  /** 读容器正文：递归遍历（不依赖 TreeWalker 的浏览器差异），
   *  跳过杂音容器与杂音行，保留换行结构。 */
  function containerText(node) {
    if (!node) return "";
    const parts = [];
    const visit = (element) => {
      for (const child of element.childNodes) {
        if (child.nodeType === 3) {
          const value = (child.textContent || "")
            .replace(/\u00a0/g, " ")
            .replace(/[ \t]+/g, " ")
            .replace(/\n{3,}/g, "\n\n")
            .trim();
          if (value && !isChromeText(value)) parts.push(value);
          continue;
        }
        if (child.nodeType !== 1) continue;
        let chrome = false;
        try {
          chrome = child.matches(CHROME_SELECTOR);
        } catch {
          chrome = false;
        }
        if (!chrome) visit(child);
      }
    };
    visit(node);
    return parts.join("\n").replace(/\n{3,}/g, "\n\n").trim();
  }

  /** <title> 兜底：切掉站点后缀，跳过「职位详情」这类页面名。 */
  function titleFromDocument() {
    const raw = String(document.title || "").trim();
    if (!raw) return "";
    const parts = raw
      .split(/[|｜\-–—_·]/)
      .map((part) => part.trim())
      .filter(Boolean);
    for (const part of parts) {
      if (isChromeText(part)) continue;
      if (/招聘|人才|官网|jobs?|careers?|hiring/i.test(part)) continue;
      if (part.length < 2 || part.length > 60) continue;
      return part;
    }
    return raw;
  }

  /** 公司名兜底：官网招聘页的 <title> 尾段通常就是公司名。 */
  function companyFromSiteName() {
    const og = document.querySelector('meta[property="og:site_name"]');
    const ogName = og && String(og.getAttribute("content") || "").trim();
    if (ogName && !isChromeText(ogName)) return ogName;
    const rawTitle = String(document.title || "");
    /* 英文 ATS 常见「Job Application for X at Y」：尾段就是公司名。 */
    const at = rawTitle.match(/(?:\bat\b|@)\s*([^|｜\-–—]{2,40})\s*$/i);
    if (at && !isChromeText(at[1])) return at[1].trim();
    const parts = rawTitle
      .split(/[|｜\-–—_·]/)
      .map((part) => part.trim())
      .filter(Boolean);
    for (const part of parts) {
      if (!/招聘|人才|官网|jobs?|careers?|hiring/i.test(part)) continue;
      const stripped = part
        .replace(/[（(].*?[)）]/g, "")
        .replace(/(社会|校园|实习生?|海外|全球)?招聘.*$/i, "")
        .replace(/(人才|官网|jobs?|careers?|hiring).*$/i, "")
        .trim();
      if (stripped.length >= 2 && stripped.length <= 30) return stripped;
    }
    return "";
  }

  /** 去掉站点标签前缀（如「工作地点：」）并压缩空白，避免把字段名当值。 */
  function cleanLocation(value) {
    let text = String(value || "")
      .replace(
        /^\s*(工作地点|工作地址|地点|地址|城市|Location)\s*[:：]\s*/i,
        "",
      )
      .replace(/\u00a0/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    /* 「全职 | 杭州市 | 2026-09-23 更新」这类拼接串：挑出像地点的段。 */
    if (/[|｜]/.test(text)) {
      const parts = text
        .split(/[|｜]/)
        .map((part) => part.trim())
        .filter(Boolean);
      const located = parts.find((part) =>
        /市|区|县|省|路|号|Remote|remote|北京|上海|深圳|广州|杭州|成都|武汉|南京|西安/.test(
          part,
        ),
      );
      text = located || parts[0] || text;
    }
    return text.replace(/\s*(更新|发布|刷新)$/, "").trim();
  }

  function shixisengPayload() {
    const title =
      firstText([
        ".new_job_name",
        ".job-title",
        "[class*='job-title']",
        "[class*='position-name']",
        "h1",
      ]) || document.title;
    const company = firstText([
      ".com-name",
      ".company-name",
      "[class*='company-name']",
      "[class*='company'] a",
      "[class*='recruiter']",
    ]);
    const jobLocation = cleanLocation(
      firstText([
        ".job_city",
        "[class*='job-location']",
        "[class*='location']",
        "[class*='address']",
        "[class*='city']",
      ]),
    );
    const salary = firstText([
      ".job_money",
      "[class*='job-salary']",
      "[class*='salary']",
      "[class*='compensation']",
    ]);
    let jdText = "";
    const jdNode = document.querySelector(
      ".con-job .job_detail, .job_detail, .job-detail-content, " +
        ".job-detail__content, .job-description, .job-intro, " +
        ".detail-content, [class*='job-detail']",
    );
    if (jdNode) jdText = containerText(jdNode);
    if (!jdText || jdText.length < 50) {
      const fallback =
        document.querySelector("main, .container, #app, .page") ||
        document.body;
      jdText = fallback.innerText.replace(/\n{3,}/g, "\n\n").trim();
    }
    return {
      title,
      company,
      location: jobLocation,
      salary_text: salary,
      job_page_url: window.location.href,
      jd_text: jdText.slice(0, MAX_JD_LENGTH),
      site: "shixiseng",
    };
  }

  /* ---------------------------------------------------------------- */
  /* 通用岗位页 Agent（0.2.0）：纯 DOM 启发式 + JSON-LD，零 LLM 调用。  */
  /* 目标：把「用户划词」升级为「页面加载即识别，一键提取」。JD 的      */
  /* LLM 结构化分类仍由后端 local-ingest 负责，浏览器端不重复智能。      */
  /* ---------------------------------------------------------------- */

  const JD_ANCHOR_RE =
    /(岗位职责|工作职责|职责描述|职位描述|岗位描述|职位职责|任职要求|任职资格|岗位要求|职位要求|应聘要求|工作要求|工作内容|我们希望你|你需要做|你将会做|你会做什么|加分项|Job Description|Responsibilities|Requirements|Qualifications|About the role|What you['’]ll do|Who you are|Your role)/i;
  const SALARY_RE =
    /(\d+\s*[-–~至]\s*\d+\s*(K|k|万|元)|￥\s*\d+|月薪|年薪|日薪|薪资待遇|薪酬)/;
  const EXP_RE = /(\d+\s*[-–~至]?\s*\d*\s*年(以上|工作经验)?|\d+\s*\+\s*years?)/i;
  const EXPAND_TEXT_RE =
    /^(展开全文|查看更多|展开全部|展开剩余|展开|显示全文|更多|Show more|Show More|Read more)$/;

  /* 招聘语境信号：按类别命中，命中类别越多越像「有招聘信息的页面」。
   * 单靠「招聘」两个字太容易误报，所以要求多类同时出现。 */
  const RECRUIT_SIGNAL_RES = [
    /招聘|招募|招人|求职|应聘|内推|急招/i,
    /职位|岗位|职务/i,
    /职责|任职|资格|要求|工作内容|岗位描述|职位描述/i,
    /简历|投递|申请|面试|入职|录用|offer/i,
    /薪资|月薪|年薪|日薪|待遇|福利|五险一金|双休|转正|试用期|补贴/i,
    /实习|全职|兼职|校招|社招|应届/i,
    /\b(hiring|recruit\w*|job|career\w*|opening|vacanc\w*|position)\b/i,
    /\b(responsibilit\w*|requirement\w*|qualification\w*|what you.ll do|who you are)\b/i,
    /\b(apply|application|resume|cv|interview|onboard\w*)\b/i,
    /\b(salary|compensation|benefits|equity|bonus|perks)\b/i,
    /\b(internship|full[- ]time|part[- ]time|contractor|remote)\b/i,
  ];

  const RECRUIT_META_RE =
    /招聘|招募|人才|求职|应聘|职位|岗位|job|career|position|opening|vacanc|recruit|hiring|apply|talent/i;

  /** 读 JSON-LD（schema.org/JobPosting）——招聘站最可靠的结构化来源。 */
  function jsonLdJobPosting() {
    for (const node of document.querySelectorAll(
      'script[type="application/ld+json"]',
    )) {
      let data;
      try {
        data = JSON.parse(node.textContent || "");
      } catch {
        continue;
      }
      const roots = Array.isArray(data) ? data : [data];
      for (const root of roots) {
        const entries =
          root && Array.isArray(root["@graph"]) ? root["@graph"] : [root];
        for (const entry of entries) {
          if (entry && String(entry["@type"] || "") === "JobPosting") {
            return entry;
          }
        }
      }
    }
    return null;
  }

  /** 给一个元素打岗位内容分：越长、锚点/薪资/经验特征越多，分越高。 */
  function scoreJobText(text) {
    if (!text || text.length < 80) return 0;
    /* 长度每 10 字 1 分（40 封顶）；锚点词（岗位职责/任职要求…）每个
     * 15 分（45 封顶）——双锚点是岗位页最强信号。 */
    let score = Math.min(40, Math.round(text.length / 10));
    const anchors = text.match(new RegExp(JD_ANCHOR_RE.source, "gi")) || [];
    score += Math.min(45, anchors.length * 15);
    if (SALARY_RE.test(text)) score += 15;
    if (EXP_RE.test(text)) score += 15;
    return score;
  }

  /** 统计 JD 锚点词出现次数（岗位职责/任职要求/职位描述…）。 */
  function countAnchors(text) {
    return (
      String(text || "").match(new RegExp(JD_ANCHOR_RE.source, "gi")) || []
    ).length;
  }

  /** 关键词锚点（岗位职责/任职要求…）向上找最小公共容器。 */
  function containerFromAnchors() {
    const walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_ELEMENT,
    );
    let best = null;
    let bestScore = 0;
    for (
      let node = walker.nextNode();
      node;
      node = walker.nextNode()
    ) {
      const own = (node.childNodes.length &&
        [...node.childNodes]
          .filter((child) => child.nodeType === 3)
          .map((child) => child.textContent)
          .join(" ")) || "";
      if (!JD_ANCHOR_RE.test(own)) continue;
      let parent = node.parentElement;
      for (let hop = 0; parent && hop < 6; hop += 1) {
        const score = scoreJobText(parent.innerText || "");
        if (score > bestScore) {
          best = parent;
          bestScore = score;
        }
        parent = parent.parentElement;
      }
    }
    /* 双锚点（如「岗位职责」+「任职要求」）本身就是强信号，不必再靠字数。 */
    const strong =
      bestScore >= 60 ||
      (best &&
        countAnchors(best.innerText || "") >= 2 &&
        (best.innerText || "").length >= 120);
    return strong ? best : null;
  }

  /** JD 容器：显式 class 优先，其次锚点容器，兜底 main/article。 */
  function findJdContainer() {
    const explicit = document.querySelector(
      ".con-job .job_detail, .job_detail, .job-detail-content, " +
        ".job-detail__content, .job-description, .job-detail, " +
        ".job-intro, .detail-content, .position-desc, " +
        "[class*='job-detail'], [class*='job-desc'], [class*='position-desc']",
    );
    /* 显式 class 是强信号：命中且有内容即信任，不按字数分数丢弃。 */
    if (explicit && (explicit.innerText || "").trim().length >= 40) {
      explicit.__raKind = "explicit";
      return explicit;
    }
    const candidates = [explicit, containerFromAnchors()].filter(Boolean);
    let best = null;
    let bestScore = 0;
    for (const node of candidates) {
      const score = scoreJobText(node.innerText || "");
      if (score > bestScore) {
        best = node;
        bestScore = score;
      }
    }
    if (best) {
      best.__raKind = "anchors";
      return best;
    }
    const fallback =
      document.querySelector("main, article, .container, #app, .page") ||
      document.body;
    /* 整页兜底比显式容器弱得多：长页面靠字数就能拿到 40 分，所以这里
     * 额外要求至少 3 个 JD 锚点，避免门户/资讯首页被误判成岗位页。 */
    const fallbackText = containerText(fallback);
    if (countAnchors(fallbackText) >= 3 && scoreJobText(fallbackText) >= 60) {
      fallback.__raKind = "fallback";
      return fallback;
    }
    return null;
  }

  /** 展开折叠 + 触发懒加载（尽力而为，不报错——SPA 行为各异）。 */
  async function expandJobContainer(container) {
    const clickables = [...container.querySelectorAll("button, a, span, div")]
      .filter((node) => {
        const label = (node.innerText || "").trim();
        if (label.length > 12) return false;
        if (EXPAND_TEXT_RE.test(label)) return true;
        const cls = String(node.className || "");
        return /expand|unfold|show-more|collapse/i.test(cls) && label;
      })
      .slice(0, 4);
    for (const node of clickables) {
      try {
        node.click();
      } catch {
        /* 站点行为各异，失败忽略 */
      }
      await new Promise((resolve) => setTimeout(resolve, 150));
    }
    if (container.scrollHeight > container.clientHeight + 40) {
      container.scrollTop = container.scrollHeight;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    window.scrollTo(0, document.body.scrollHeight);
    await new Promise((resolve) => setTimeout(resolve, 250));
  }

  /** 汇总 Agent payload：JSON-LD 字段优先，启发式补齐 JD 正文。 */
  function agentPayload() {
    const ld = jsonLdJobPosting();
    const container = findJdContainer();
    const ldDesc = ld && ld.description ? stripHtml(ld.description) : "";
    let jdText = containerText(container);
    /* JSON-LD 描述通常比启发式容器更干净：容器明显偏短时改用结构化描述。 */
    if (ldDesc && jdText.length < 80 && ldDesc.length > jdText.length) {
      jdText = ldDesc;
    }
    const title =
      (ld && ld.title ? String(ld.title).trim() : "") ||
      firstMeaningfulText([
        ".job-recruit-title",
        ".posi-name",
        ".new_job_name",
        "[class*='jobName']",
        "[class*='job-name']",
        "[class*='positionName']",
        "[class*='position-name']",
        "[class*='jobTitle']",
        "[class*='job-title']",
        "[class*='recruit-title']",
        "h1",
      ]) ||
      titleFromDocument();
    const org = ld && ld.hiringOrganization;
    const company =
      (org && (typeof org === "string" ? org : org.name)) ||
      firstMeaningfulText([
        ".com-name",
        "[class*='company-name']",
        "[class*='company'] a",
        "[class*='company']",
      ]) ||
      companyFromSiteName() ||
      "";
    const jobLocation = cleanLocation(
      firstText([
        ".job_city",
        ".job-recruit-location",
        ".posi-sc-name",
        "[class*='job-location']",
        "[class*='location']",
        "[class*='address']",
        "[class*='city']",
      ]),
    );
    let salary = firstText([
      ".job_money",
      "[class*='job-salary']",
      "[class*='salary']",
      "[class*='compensation']",
    ]);
    if (!salary && jdText) {
      const inBody = jdText.match(SALARY_RE);
      if (inBody) salary = inBody[0];
    }
    return {
      title: String(title || titleFromDocument() || document.title).trim(),
      company: String(company || "").trim(),
      location: String(jobLocation || "").trim(),
      salary_text: String(salary || "").trim(),
      job_page_url: window.location.href,
      jd_text: jdText.slice(0, MAX_JD_LENGTH),
      site: "agent",
      _ld_description: ldDesc,
      _container_kind: (container && container.__raKind) || "none",
    };
  }

  /** 页面是否值得出「一键提取」按钮：JD 文本足够长即认为可信。 */
  function detectAgentPage() {
    try {
      const payload = agentPayload();
      const text = payload.jd_text || payload._ld_description || "";
      /* JSON-LD JobPosting 是结构化事实源：有描述就信任，不再看分数。 */
      if ((payload._ld_description || "").length >= 40) return payload;
      /* 显式 class 容器（.job-detail 等）本身就是强信号：≥80 字即信任；
       * 启发式容器走综合评分（≥60）或长文本（≥300）。 */
      const trusted =
        scoreJobText(text) >= 60 ||
        text.length >= 300 ||
        (countAnchors(text) >= 2 && text.length >= 120) ||
        (payload._container_kind === "explicit" && text.length >= 80);
      return trusted ? payload : null;
    } catch {
      return null;
    }
  }

  /* ---------------------------------------------------------------- */
  /* 手动区域抓取（0.3.0）：官网招聘页的 DOM 长尾太长，自动识别不可能  */
  /* 覆盖全部。这个模式让用户点选页面上任意一块作为 JD 正文——        */
  /* 只要页面上看得见，就能抓，不再依赖启发式命中。                    */
  /* ---------------------------------------------------------------- */

  let pickerCleanup = null;

  function startRegionPick() {
    if (pickerCleanup) return;
    const overlay = document.createElement("div");
    overlay.id = "resualign-collector-picker";
    overlay.style.cssText =
      "position:fixed;z-index:2147483645;pointer-events:none;" +
      "border:2px solid #2563eb;background:rgba(37,99,235,.12);" +
      "border-radius:4px;box-sizing:border-box;";
    const hint = document.createElement("div");
    hint.style.cssText =
      "position:fixed;left:50%;top:16px;transform:translateX(-50%);" +
      "z-index:2147483647;background:#111827;color:#fff;" +
      "font:13px/1.5 system-ui,sans-serif;padding:8px 14px;" +
      "border-radius:6px;pointer-events:none;max-width:90vw;";
    hint.textContent = "点击要抓取的岗位正文区域 · 按 Esc 取消";
    document.body.appendChild(overlay);
    document.body.appendChild(hint);

    const cleanup = () => {
      overlay.remove();
      hint.remove();
      document.removeEventListener("mousemove", onMove, true);
      document.removeEventListener("click", onClick, true);
      document.removeEventListener("keydown", onKey, true);
      pickerCleanup = null;
    };
    const onMove = (event) => {
      const target = event.target;
      if (!target || target === overlay || target === hint) return;
      const rect = target.getBoundingClientRect();
      overlay.style.left = rect.left + "px";
      overlay.style.top = rect.top + "px";
      overlay.style.width = rect.width + "px";
      overlay.style.height = rect.height + "px";
    };
    const onKey = (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      cleanup();
      setFeedback("已取消区域抓取", "info");
    };
    const onClick = (event) => {
      event.preventDefault();
      event.stopPropagation();
      const target = event.target;
      cleanup();
      const text = containerText(target);
      if (!text || text.length < 20) {
        setFeedback("这块区域没抓到正文，换一个更大的区域再试", "error");
        return;
      }
      const payload = { ...agentPayload() };
      delete payload._ld_description;
      delete payload._container_kind;
      payload.site = "agent";
      payload.jd_text = text.slice(0, MAX_JD_LENGTH);
      ingest(payload);
    };
    document.addEventListener("mousemove", onMove, true);
    document.addEventListener("click", onClick, true);
    document.addEventListener("keydown", onKey, true);
    pickerCleanup = cleanup;
  }

  /** 命中多少类招聘语境信号。 */
  function recruitSignalCount(text) {
    const sample = String(text || "");
    let hits = 0;
    for (const re of RECRUIT_SIGNAL_RES) {
      if (re.test(sample)) hits += 1;
    }
    return hits;
  }

  function metaContent(name) {
    const node =
      document.querySelector(`meta[property="${name}"]`) ||
      document.querySelector(`meta[name="${name}"]`);
    return node ? String(node.getAttribute("content") || "") : "";
  }

  /** 标题 / URL / meta 里的招聘线索（便宜，不触发布局）。 */
  function recruitmentMetaHint() {
    return RECRUIT_META_RE.test(
      [
        document.title,
        location.hostname,
        location.pathname,
        metaContent("description"),
        metaContent("og:title"),
        metaContent("og:description"),
      ].join(" "),
    );
  }

  /** 采样页面正文：带节点/字数预算，避免在超大页面上做全量遍历。 */
  function pageTextSample(maxChars, maxNodes) {
    const parts = [];
    let length = 0;
    let visited = 0;
    const stack = [document.body];
    while (stack.length) {
      const element = stack.pop();
      if (!element) continue;
      for (const child of element.childNodes) {
        visited += 1;
        if (visited > maxNodes || length > maxChars) break;
        if (child.nodeType === 3) {
          const value = (child.textContent || "").trim();
          if (value) {
            parts.push(value);
            length += value.length;
          }
          continue;
        }
        if (child.nodeType !== 1) continue;
        let chrome = false;
        try {
          chrome = child.matches(CHROME_SELECTOR);
        } catch {
          chrome = false;
        }
        if (!chrome) stack.push(child);
      }
      if (visited > maxNodes || length > maxChars) break;
    }
    return parts.join("\n").slice(0, maxChars);
  }

  /** 招聘信号：页面像不像「有招聘信息」。识别不出 JD 容器时也提示抓取。 */
  function looksLikeJobPage() {
    try {
      if (!document.body) return false;
      const sample = pageTextSample(30000, 3000);
      if (sample.length < 120) return false;
      const anchors = countAnchors(sample);
      const signals = recruitSignalCount(sample);
      /* 双锚点（岗位职责 + 任职要求）本身就是招聘页的强证据。 */
      if (anchors >= 2) return true;
      if (anchors >= 1 && signals >= 2) return true;
      /* 没有锚点时，要求多类信号 + 标题/URL 也像招聘页，避免误报。 */
      if (!recruitmentMetaHint()) return false;
      return signals >= 2;
    } catch {
      return false;
    }
  }

  function ensureFloatBox() {
    if (floatBox && document.body.contains(floatBox)) return floatBox;
    floatBox = document.createElement("div");
    floatBox.id = "resualign-collector-float";
    floatBox.style.cssText =
      "position:fixed;right:16px;bottom:16px;z-index:2147483646;" +
      "display:flex;flex-direction:column;gap:8px;align-items:stretch;" +
      "font:13px/1.5 system-ui,sans-serif;max-width:min(340px,92vw);";
    floatBox.addEventListener("mousedown", () => {
      ignoreSelection = true;
      setTimeout(() => {
        ignoreSelection = false;
      }, 200);
    });
    document.body.appendChild(floatBox);
    return floatBox;
  }

  let agentPayloadCached = null;
  let jobPageHint = false;
  let floatDismissed = false;

  function setFloatButtons(html) {
    const box = ensureFloatBox();
    let mount = box.querySelector("[data-ra-buttons]");
    if (!mount) {
      mount = document.createElement("div");
      mount.setAttribute("data-ra-buttons", "");
      mount.style.cssText =
        "display:flex;flex-direction:column;gap:6px;align-items:stretch;";
      box.appendChild(mount);
    }
    mount.innerHTML = html;
    const specific = mount.querySelector("#ra-ingest-specific");
    if (specific) {
      specific.addEventListener("click", () => {
        specific.disabled = true;
        ingest(shixisengPayload()).finally(() => {
          specific.disabled = false;
        });
      });
    }
    const agent = mount.querySelector("#ra-ingest-agent");
    if (agent) {
      agent.addEventListener("click", async () => {
        agent.disabled = true;
        agent.textContent = "提取中…";
        try {
          let payload = agentPayloadCached;
          if (!payload) payload = detectAgentPage();
          if (payload) {
            await expandJobContainer(
              findJdContainer() || document.body,
            );
            payload = agentPayload();
            const clean = { ...payload };
            delete clean._ld_description;
            await ingest(clean);
          }
        } finally {
          agent.disabled = false;
          agent.textContent = "一键提取岗位";
        }
      });
    }
    const universal = mount.querySelector("#ra-ingest-selection");
    if (universal) {
      universal.addEventListener("click", () => {
        universal.disabled = true;
        ingest({
          title: document.title,
          company: "",
          location: "",
          salary_text: "",
          job_page_url: location.href,
          jd_text: selectedText.slice(0, MAX_JD_LENGTH),
          site: "universal",
        }).finally(() => {
          universal.disabled = false;
        });
      });
    }
    const settings = mount.querySelector("#ra-open-config");
    if (settings) {
      settings.addEventListener("click", () => {
        showConfigModal();
      });
    }
    const pick = mount.querySelector("#ra-pick-region");
    if (pick) {
      pick.addEventListener("click", () => {
        startRegionPick();
      });
    }
    const page = mount.querySelector("#ra-ingest-page");
    if (page) {
      page.addEventListener("click", async () => {
        page.disabled = true;
        page.textContent = "提取中…";
        try {
          const payload = { ...agentPayload() };
          delete payload._ld_description;
          delete payload._container_kind;
          payload.site = "agent";
          payload.jd_text = containerText(document.body).slice(
            0,
            MAX_JD_LENGTH,
          );
          await ingest(payload);
        } finally {
          page.disabled = false;
          page.textContent = "抓取整页正文";
        }
      });
    }
    const dismiss = mount.querySelector("#ra-dismiss-float");
    if (dismiss) {
      dismiss.addEventListener("click", () => {
        floatDismissed = true;
        updateFloat();
      });
    }
  }

  function setFeedback(message, kind) {
    const box = ensureFloatBox();
    let feedback = box.querySelector("[data-ra-feedback]");
    if (!feedback) {
      feedback = document.createElement("div");
      feedback.setAttribute("data-ra-feedback", "");
      feedback.style.cssText =
        "background:#fff;color:#111;border:1px solid #d5dde7;" +
        "border-radius:6px;padding:8px 10px;box-shadow:0 4px 14px rgba(0,0,0,.16);";
      box.appendChild(feedback);
    }
    const text = String(message || "");
    feedback.innerHTML = text;
    feedback.style.borderLeft =
      kind === "error"
        ? "3px solid #dc2626"
        : kind === "info"
          ? "3px solid #f59e0b"
          : "3px solid #16a34a";
    if (text !== lastFeedbackText) {
      lastFeedbackText = text;
      window.clearTimeout(feedback._timer);
      feedback._timer = window.setTimeout(() => {
        if (feedback.isConnected) feedback.remove();
        lastFeedbackText = "";
      }, 10000);
    }
  }

  function updateFloat() {
    if (floatDismissed) {
      if (floatBox) {
        const mount = floatBox.querySelector("[data-ra-buttons]");
        if (mount) mount.innerHTML = "";
      }
      return;
    }
    const specific = isShixisengDetail()
      ? '<button id="ra-ingest-specific" type="button" style="' +
        "background:#2563eb;color:#fff;border:0;border-radius:6px;" +
        'padding:9px 12px;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.16)">' +
        "摄入岗位</button>"
      : "";
    const agent = agentPayloadCached
      ? '<button id="ra-ingest-agent" type="button" style="' +
        "background:#2563eb;color:#fff;border:0;border-radius:6px;" +
        'padding:9px 12px;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.16)">' +
        "一键提取岗位</button>"
      : "";
    const universal = selectedText
      ? '<button id="ra-ingest-selection" type="button" style="' +
        "background:#0f766e;color:#fff;border:0;border-radius:6px;" +
        'padding:9px 12px;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.16)">' +
        "摄入选区 JD</button>"
      : "";
    const settings =
      '<button id="ra-open-config" type="button" style="' +
      "background:#fff;color:#334155;border:1px solid #cbd5e1;" +
      'border-radius:6px;padding:5px 10px;cursor:pointer;font-size:12px">' +
      "设置 / 连接自检</button>";
    const pick =
      '<button id="ra-pick-region" type="button" style="' +
      "background:#fff;color:#334155;border:1px solid #cbd5e1;" +
      'border-radius:6px;padding:5px 10px;cursor:pointer;font-size:12px">' +
      "抓取页面区域</button>";
    const page =
      '<button id="ra-ingest-page" type="button" style="' +
      "background:#2563eb;color:#fff;border:0;border-radius:6px;" +
      'padding:9px 12px;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.16)">' +
      "抓取整页正文</button>";
    const notice =
      '<div style="background:#111827;color:#fff;font-size:12px;' +
      'padding:6px 10px;border-radius:6px;text-align:center">' +
      "检测到招聘信息 · 可抓取</div>";
    const dismiss =
      '<button id="ra-dismiss-float" type="button" title="本页不再提示" ' +
      'style="background:transparent;color:#64748b;border:0;cursor:pointer;' +
      'font-size:12px;padding:2px 6px;align-self:flex-end">隐藏</button>';
    if (specific || universal || agent) {
      setFloatButtons(agent + specific + universal + pick + settings + dismiss);
    } else if (jobPageHint) {
      setFloatButtons(notice + page + pick + settings + dismiss);
    } else if (floatBox) {
      const mount = floatBox.querySelector("[data-ra-buttons]");
      if (mount) mount.innerHTML = "";
    }
  }

  function selectionInsideOwnUi(selection) {
    if (!selection || !selection.anchorNode) return false;
    const node =
      selection.anchorNode.nodeType === 1
        ? selection.anchorNode
        : selection.anchorNode.parentElement;
    return Boolean(
      node &&
        node.closest(
          "#resualign-collector-float, #resualign-collector-config",
        ),
    );
  }

  function handleSelectionChange() {
    if (ignoreSelection) return;
    const selection = window.getSelection();
    const text = selection ? selection.toString().trim() : "";
    if (
      text &&
      text.length >= 20 &&
      !selectionInsideOwnUi(selection)
    ) {
      selectedText = text;
      updateFloat();
    } else if (!text) {
      selectedText = "";
      updateFloat();
    }
  }

  function removeConfigModal() {
    if (configModal && configModal.isConnected) configModal.remove();
    configModal = null;
  }

  function showConfigModal(notice) {
    removeConfigModal();
    const config = loadConfig();
    configModal = document.createElement("div");
    configModal.id = "resualign-collector-config";
    configModal.style.cssText =
      "position:fixed;inset:0;z-index:2147483647;display:flex;" +
      "align-items:center;justify-content:center;" +
      "background:rgba(0,0,0,.45);font:13px/1.5 system-ui,sans-serif;";
    configModal.innerHTML =
      '<div style="background:#fff;color:#111;width:min(420px,92vw);' +
      'border-radius:8px;padding:18px;box-shadow:0 10px 30px rgba(0,0,0,.25);box-sizing:border-box">' +
      '<h2 style="margin:0 0 10px;font-size:16px">ResuAlign 摄入配置</h2>' +
      (notice
        ? '<p style="color:#c0392b;margin:0 0 10px">' +
          escapeHtml(notice) +
          "</p>"
        : "") +
      '<label style="display:block;margin:8px 0 4px">服务地址</label>' +
      '<input id="ra-server" value="' +
      escapeAttr(config.server || DEFAULT_SERVER) +
      '" style="width:100%;padding:7px;box-sizing:border-box" ' +
      'placeholder="http://127.0.0.1:8000">' +
      '<label style="display:block;margin:8px 0 4px">Local Ingest Token</label>' +
      '<input id="ra-token" type="password" value="' +
      escapeAttr(config.token) +
      '" style="width:100%;padding:7px;box-sizing:border-box" ' +
      'placeholder="系统设置页 → 本地摄入 Token → 复制">' +
      '<p style="margin:8px 0 0;color:#5f6f7d">默认服务地址 ' +
      escapeHtml(DEFAULT_SERVER) +
      "；本地端口变更时直接改服务地址，无需改脚本。</p>" +
      '<p id="ra-selftest-result" style="margin:8px 0 0;color:#5f6f7d">' +
      "先点「连接自检」确认服务可达，再保存——" +
      "自检不通时摄入也会静默失败。</p>" +
      '<div style="margin-top:12px;display:flex;gap:8px;justify-content:flex-end">' +
      '<button id="ra-config-selftest" type="button" style="margin-right:auto;padding:6px 10px;border:1px solid #cbd5e1;background:#f8fafc;border-radius:4px;cursor:pointer">连接自检</button>' +
      '<button id="ra-config-cancel" type="button" style="padding:6px 10px;border:1px solid #d5dde7;background:#fff;border-radius:4px;cursor:pointer">关闭</button>' +
      '<button id="ra-config-save" type="button" style="padding:6px 10px;background:#2563eb;color:#fff;border:0;border-radius:4px;cursor:pointer">保存</button>' +
      "</div></div>";
    document.body.appendChild(configModal);
    ignoreSelection = true;
    const serverInput = configModal.querySelector("#ra-server");
    const tokenInput = configModal.querySelector("#ra-token");
    serverInput.focus();
    const selfTestOut = configModal.querySelector("#ra-selftest-result");
    configModal
      .querySelector("#ra-config-selftest")
      .addEventListener("click", () => {
        const server = (
          serverInput.value.trim() || DEFAULT_SERVER
        ).replace(/\/+$/, "");
        selfTestOut.style.color = "#5f6f7d";
        selfTestOut.textContent = "自检中…";
        GM_xmlhttpRequest({
          method: "GET",
          url: server + "/health",
          timeout: 8000,
          onload: (response) => {
            if (response.status >= 200 && response.status < 300) {
              selfTestOut.style.color = "#15803d";
              selfTestOut.textContent = tokenInput.value.trim()
                ? "服务可达 ✓ 保存后即可摄入。"
                : "服务可达 ✓ 还差 Token：到系统设置页复制后填入。";
            } else {
              selfTestOut.style.color = "#b45309";
              selfTestOut.textContent =
                "服务返回 HTTP " + response.status + "，请核对服务地址与端口。";
            }
          },
          onerror: () => {
            selfTestOut.style.color = "#b91c1c";
            selfTestOut.textContent =
              "连不上服务。两种可能：①ResuAlign 未启动；②被浏览器「本地网络访问」" +
              "或油猴 127.0.0.1 授权拦截（详见安装文档）。";
          },
          ontimeout: () => {
            selfTestOut.style.color = "#b91c1c";
            selfTestOut.textContent = "自检超时：本地服务无响应。";
          },
        });
      });
    configModal.querySelector("#ra-config-save").addEventListener("click", () => {
      const server = serverInput.value.trim();
      const token = tokenInput.value.trim();
      if (!server || !token) {
        serverInput.style.borderColor = !server ? "#dc2626" : "";
        tokenInput.style.borderColor = !token ? "#dc2626" : "";
        return;
      }
      saveConfig(server, token);
      removeConfigModal();
      setTimeout(() => {
        ignoreSelection = false;
      }, 200);
      setFeedback("配置已保存，可以开始摄入", "ok");
    });
    configModal.querySelector("#ra-config-cancel").addEventListener("click", () => {
      removeConfigModal();
      setTimeout(() => {
        ignoreSelection = false;
      }, 200);
    });
  }

  async function ingest(payload) {
    const config = loadConfig();
    if (!config.server || !config.token) {
      showConfigModal("请先配置服务地址与 Token");
      return;
    }
    setFeedback("摄入中…", "info");
    /* GM_xmlhttpRequest 而非页面级 fetch：油猴运行在任意外部招聘网站
     * 页面上，fetch 跨源带自定义 token 头会被浏览器 CORS 预检掐死
     * （服务端即便配置了 CORS 也依赖其正确性）；GM_xmlhttpRequest 由
     * 扩展进程发起，天然绕过同源策略。 */
    const url = config.server.replace(/\/+$/, "") + "/api/jobs/local-ingest";
    return await new Promise((resolve) => {
      GM_xmlhttpRequest({
        method: "POST",
        url,
        headers: {
          "Content-Type": "application/json",
          "X-ResuAlign-Token": config.token,
        },
        data: JSON.stringify(payload),
        timeout: 15000,
        onload: (response) => {
          let body = {};
          try {
            body = JSON.parse(response.responseText || "{}");
          } catch {
            /* keep default body */
          }
          if (response.status < 200 || response.status >= 300) {
            if (response.status === 401) {
              GM_setValue(TOKEN_KEY, "");
              setFeedback(
                "Token 无效或已重置：请在系统设置页重新复制",
                "error",
              );
              showConfigModal("Token 无效或已重置，请粘贴新 Token");
              resolve(false);
              return;
            }
            const detail = body.detail || {};
            const reason =
              typeof detail === "string"
                ? detail
                : detail.reason ||
                  detail.action ||
                  response.statusText ||
                  "HTTP " + response.status;
            setFeedback("摄入失败：" + reason, "error");
            resolve(false);
            return;
          }
          const created = body.status === "created";
          const link = body.job_id
            ? '<a href="' +
              escapeAttr(config.server) +
              "/#/workspace/" +
              encodeURIComponent(body.job_id) +
              '" target="_blank" rel="noopener" style="color:#2563eb;margin-left:6px">去工作台</a>'
            : "";
          setFeedback(
            (created ? "已入库" : "已在岗位库") + link,
            created ? "ok" : "info",
          );
          resolve(true);
        },
        onerror: () => {
          setFeedback(
            "摄入失败：请求没能到达本地服务。请先确认 ResuAlign 已启动、" +
              "地址端口正确；若仍失败，是浏览器「本地网络访问」或油猴 " +
              "127.0.0.1 授权把请求拦住了（点「设置 / 连接自检」排查）。",
            "error",
          );
          resolve(false);
        },
        ontimeout: () => {
          setFeedback("摄入失败：本地服务响应超时", "error");
          resolve(false);
        },
      });
    });
  }

  function start() {
    document.addEventListener("selectionchange", handleSelectionChange);
    document.addEventListener("mouseup", handleSelectionChange);
    if (typeof GM_registerMenuCommand === "function") {
      GM_registerMenuCommand("ResuAlign：抓取页面区域", startRegionPick);
      GM_registerMenuCommand("ResuAlign：设置 / 连接自检", () => {
        showConfigModal();
      });
    }
    if (isShixisengDetail()) {
      updateFloat();
    }
    /* 通用岗位页 Agent：加载即检测；SPA 站点通过劫持 pushState/
     * replaceState + popstate/hashchange 感知路由变化（不引入轮询
     * timer，油猴在所有标签页常驻，timer 成本必须为零）。 */
    agentPayloadCached = detectAgentPage();
    jobPageHint = agentPayloadCached ? false : looksLikeJobPage();
    if (agentPayloadCached || jobPageHint || isShixisengDetail()) {
      updateFloat();
    }
    let lastHref = location.href;
    const onUrlChange = () => {
      if (location.href === lastHref) return;
      lastHref = location.href;
      selectedText = "";
      floatDismissed = false;
      agentPayloadCached = detectAgentPage();
      jobPageHint = agentPayloadCached ? false : looksLikeJobPage();
      updateFloat();
    };
    for (const method of ["pushState", "replaceState"]) {
      const original = history[method];
      if (typeof original !== "function") continue;
      history[method] = function (...args) {
        const result = original.apply(this, args);
        onUrlChange();
        return result;
      };
    }
    window.addEventListener("popstate", onUrlChange);
    window.addEventListener("hashchange", onUrlChange);
    /* 展开/懒加载类 DOM 变化不改变 URL：MutationObserver 防抖重检
     * （JD 正文常在用户点击「展开全文」后才完整出现）。 */
    let mutationTimer = null;
    let lastHintAt = 0;
    const observer = new MutationObserver(() => {
      if (mutationTimer) return;
      mutationTimer = window.setTimeout(() => {
        mutationTimer = null;
        const previous = agentPayloadCached ? agentPayloadCached.jd_text : "";
        const previousHint = jobPageHint;
        agentPayloadCached = detectAgentPage();
        if (agentPayloadCached) {
          jobPageHint = false;
        } else if (Date.now() - lastHintAt > 2000) {
          /* 招聘信号扫描最多每 2s 一次：SPA 频繁变更时不重复付这份成本。 */
          lastHintAt = Date.now();
          jobPageHint = looksLikeJobPage();
        }
        if (
          (agentPayloadCached ? agentPayloadCached.jd_text : "") !== previous ||
          jobPageHint !== previousHint
        ) {
          updateFloat();
        }
      }, 500);
    });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    const config = loadConfig();
    if (!config.server || !config.token) {
      showConfigModal();
    }
  }

  /* 只读调试/测试出口：暴露纯检测函数（不改变任何页面行为），
   * 供 node:test（happy-dom）与控制台诊断直接调用。 */
  if (typeof window !== "undefined") {
    window.__RA_DEBUG = {
      detectAgentPage,
      agentPayload,
      shixisengPayload,
      containerText,
      cleanLocation,
      titleFromDocument,
      companyFromSiteName,
      isChromeText,
      looksLikeJobPage,
      recruitSignalCount,
      recruitmentMetaHint,
      pageTextSample,
      startRegionPick,
      findJdContainer,
      scoreJobText,
      jsonLdJobPosting,
      expandJobContainer,
    };
  }

  start();
})();
