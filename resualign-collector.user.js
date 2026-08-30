// ==UserScript==
// @name         ResuAlign Local Collector
// @namespace    https://127.0.0.1:8000/
// @version      0.1.0
// @description  划词 / 实习僧岗位详情一键摄入 ResuAlign（本地工作台）
// @author       ResuAlign
// @match        http://*/*
// @match        https://*/*
// @grant        GM_setValue
// @grant        GM_getValue
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
    const universal = selectedText
      ? '<button id="ra-ingest-selection" type="button" style="' +
        "background:#0f766e;color:#fff;border:0;border-radius:6px;" +
        'padding:9px 12px;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.16)">' +
        "摄入选区 JD</button>"
      : "";
    if (specific || universal) {
      setFloatButtons(specific + universal);
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
      'placeholder="http://127.0.0.1:8011">' +
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
    try {
      const response = await fetch(
        config.server.replace(/\/+$/, "") + "/api/jobs/local-ingest",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-ResuAlign-Token": config.token,
          },
          body: JSON.stringify(payload),
        },
      );
      let body = {};
      try {
        body = await response.json();
      } catch {
        /* keep default body */
      }
      if (!response.ok) {
        if (response.status === 401) {
          GM_setValue(TOKEN_KEY, "");
          setFeedback(
            "Token 无效或已重置：请在系统设置页重新复制",
            "error",
          );
          showConfigModal("Token 无效或已重置，请粘贴新 Token");
          return;
        }
        const detail = body.detail || {};
        const reason =
          typeof detail === "string"
            ? detail
            : detail.reason || detail.action || response.statusText;
        setFeedback("摄入失败：" + reason, "error");
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
    } catch (error) {
      setFeedback(
        "摄入失败：" + (error && error.message ? error.message : error) +
          "（请确认服务已启动）",
        "error",
      );
    }
  }

  function start() {
    document.addEventListener("selectionchange", handleSelectionChange);
    document.addEventListener("mouseup", handleSelectionChange);
    if (isShixisengDetail()) {
      updateFloat();
    }
    const config = loadConfig();
    if (!config.server || !config.token) {
      showConfigModal();
    }
  }

  start();
})();
