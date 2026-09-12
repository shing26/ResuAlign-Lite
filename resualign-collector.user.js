// ==UserScript==
// @name         ResuAlign Local Collector
// @namespace    https://127.0.0.1:8000/
// @version      0.2.0
// @description  划词 / 实习僧 / 通用岗位页智能提取——一键摄入 ResuAlign（本地工作台）
// @author       ResuAlign
// @match        http://*/*
// @match        https://*/*
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_xmlhttpRequest
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

  function shixisengPayload() {
    const title =
      firstText([
        ".job-title",
        "[class*='job-title']",
        "[class*='position-name']",
        "h1",
      ]) || document.title;
    const company = firstText([
      ".company-name",
      "[class*='company-name']",
      "[class*='company'] a",
      "[class*='recruiter']",
    ]);
    const location = firstText([
      "[class*='job-location']",
      "[class*='location']",
      "[class*='address']",
      "[class*='city']",
    ]);
    const salary = firstText([
      "[class*='job-salary']",
      "[class*='salary']",
      "[class*='compensation']",
    ]);
    let jdText = "";
    const jdNode = document.querySelector(
      ".job-detail-content, .job-detail__content, .job-description, " +
        ".job-intro, .detail-content, [class*='job-detail']",
    );
    if (jdNode) jdText = jdNode.innerText.trim();
    if (!jdText || jdText.length < 50) {
      const fallback =
        document.querySelector("main, .container, #app, .page") ||
        document.body;
      jdText = fallback.innerText.replace(/\n{3,}/g, "\n\n").trim();
    }
    return {
      title,
      company,
      location,
      salary_text: salary,
      job_page_url: location.href,
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
    /(岗位职责|任职要求|职位描述|工作职责|岗位要求|职位要求|Job Description|Responsibilities|Requirements|What you['’]ll do|About the role)/i;
  const SALARY_RE =
    /(\d+\s*[-–~至]\s*\d+\s*(K|k|万|元)|￥\s*\d+|月薪|薪资待遇)/;
  const EXP_RE = /(\d+\s*[-–~至]?\s*\d*\s*年(以上|工作经验)?|\d+\s*\+\s*years?)/i;
  const EXPAND_TEXT_RE =
    /^(展开全文|查看更多|展开全部|展开剩余|展开|显示全文|更多|Show more|Show More|Read more)$/;

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
    return bestScore >= 60 ? best : null;
  }

  /** JD 容器：显式 class 优先，其次锚点容器，兜底 main/article。 */
  function findJdContainer() {
    const explicit = document.querySelector(
      ".job-detail-content, .job-detail__content, .job-description, " +
        ".job-detail, .job-intro, .detail-content, .position-desc, " +
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
    if (scoreJobText(fallback.innerText || "") >= 60) {
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
    const jdText = (container ? container.innerText : "")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
    const title =
      (ld && ld.title) ||
      firstText([
        "[class*='job-title']",
        "[class*='position-name']",
        "h1",
      ]) ||
      document.title;
    const org = ld && ld.hiringOrganization;
    const company =
      (org && (typeof org === "string" ? org : org.name)) ||
      firstText(["[class*='company-name']", "[class*='company'] a", "[class*='company']"]) ||
      "";
    const location = firstText([
      "[class*='job-location']",
      "[class*='location']",
      "[class*='address']",
      "[class*='city']",
    ]);
    let salary = firstText([
      "[class*='job-salary']",
      "[class*='salary']",
      "[class*='compensation']",
    ]);
    if (!salary && jdText) {
      const inBody = jdText.match(SALARY_RE);
      if (inBody) salary = inBody[0];
    }
    return {
      title: String(title || document.title).trim(),
      company: String(company || "").trim(),
      location: String(location || "").trim(),
      salary_text: String(salary || "").trim(),
      job_page_url: location.href,
      jd_text: jdText.slice(0, MAX_JD_LENGTH),
      site: "agent",
      _ld_description: ld && ld.description ? String(ld.description) : "",
      _container_kind: (container && container.__raKind) || "none",
    };
  }

  /** 页面是否值得出「一键提取」按钮：JD 文本足够长即认为可信。 */
  function detectAgentPage() {
    try {
      const payload = agentPayload();
      const text = payload.jd_text || payload._ld_description || "";
      /* 显式 class 容器（.job-detail 等）本身就是强信号：≥80 字即信任；
       * 启发式容器走综合评分（≥60）或长文本（≥300）。 */
      const trusted =
        scoreJobText(text) >= 60 ||
        text.length >= 300 ||
        (payload._container_kind === "explicit" && text.length >= 80);
      return trusted ? payload : null;
    } catch {
      return null;
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
    if (specific || universal || agent) {
      setFloatButtons(agent + specific + universal);
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
      '<div style="margin-top:12px;display:flex;gap:8px;justify-content:flex-end">' +
      '<button id="ra-config-cancel" type="button" style="padding:6px 10px;border:1px solid #d5dde7;background:#fff;border-radius:4px;cursor:pointer">关闭</button>' +
      '<button id="ra-config-save" type="button" style="padding:6px 10px;background:#2563eb;color:#fff;border:0;border-radius:4px;cursor:pointer">保存</button>' +
      "</div></div>";
    document.body.appendChild(configModal);
    ignoreSelection = true;
    const serverInput = configModal.querySelector("#ra-server");
    const tokenInput = configModal.querySelector("#ra-token");
    serverInput.focus();
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
            "摄入失败：无法连接本地服务（请确认服务已启动、地址与端口正确）",
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
    if (isShixisengDetail()) {
      updateFloat();
    }
    /* 通用岗位页 Agent：加载即检测；SPA 站点通过劫持 pushState/
     * replaceState + popstate/hashchange 感知路由变化（不引入轮询
     * timer，油猴在所有标签页常驻，timer 成本必须为零）。 */
    agentPayloadCached = detectAgentPage();
    if (agentPayloadCached || isShixisengDetail()) {
      updateFloat();
    }
    let lastHref = location.href;
    const onUrlChange = () => {
      if (location.href === lastHref) return;
      lastHref = location.href;
      selectedText = "";
      agentPayloadCached = detectAgentPage();
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
    const observer = new MutationObserver(() => {
      if (mutationTimer) return;
      mutationTimer = window.setTimeout(() => {
        mutationTimer = null;
        const previous = agentPayloadCached ? agentPayloadCached.jd_text : "";
        agentPayloadCached = detectAgentPage();
        if ((agentPayloadCached ? agentPayloadCached.jd_text : "") !== previous) {
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
      findJdContainer,
      scoreJobText,
      jsonLdJobPosting,
      expandJobContainer,
    };
  }

  start();
})();
