/* ResuAlign 网申回填 content script：
 * 右下角悬浮按钮 → 侧边栏（Shadow DOM）→ 逐字段点击填充 / 跳下一个 / 一键全填。
 * 数据经 background 从本地 ResuAlign 服务拉取，全程不过第三方服务器。 */

let sidebarHost = null;
let entries = [];

async function loadCore() {
  const url = chrome.runtime.getURL("fill-core.js");
  return import(url);
}

async function loadProfiles() {
  const config = await chrome.storage.local.get(["server"]);
  const response = await chrome.runtime.sendMessage({
    type: "fetch-profile",
    server: config.server || "http://127.0.0.1:8000",
  });
  if (!response || !response.ok) {
    throw new Error((response && response.error) || "档案获取失败");
  }
  const core = await loadCore();
  entries = response.profiles.flatMap((p) => core.flattenProfile(p.profile));
  return { core, stale: response.profiles.some((p) => p.profile.stale) };
}

function buildSidebar(core) {
  if (sidebarHost) return;
  sidebarHost = document.createElement("div");
  sidebarHost.id = "ra-autofill-host";
  const shadow = sidebarHost.attachShadow({ mode: "open" });

  const style = document.createElement("style");
  style.textContent = `
    .ra-fab { position: fixed; right: 18px; bottom: 18px; z-index: 2147483600;
      width: 44px; height: 44px; border-radius: 50%; border: 0; cursor: pointer;
      background: #4f46e5; color: #fff; font-size: 12px; font-weight: 600;
      box-shadow: 0 4px 14px rgba(0,0,0,.25); }
    .ra-sidebar { position: fixed; right: 18px; bottom: 70px; z-index: 2147483600;
      width: 280px; max-height: 60vh; overflow-y: auto; background: #fff;
      border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px;
      box-shadow: 0 10px 30px rgba(0,0,0,.18); font: 13px/1.5 system-ui, sans-serif; color: #0f172a; }
    .ra-sidebar h3 { margin: 0 0 6px; font-size: 14px; }
    .ra-tip { margin: 0 0 8px; color: #64748b; font-size: 12px; }
    .ra-group { font-weight: 600; margin: 8px 0 4px; color: #4f46e5; font-size: 12px; }
    .ra-entry { display: flex; justify-content: space-between; gap: 6px; width: 100%;
      border: 1px solid #e2e8f0; background: #f8fafc; border-radius: 6px;
      padding: 5px 8px; margin-bottom: 4px; cursor: pointer; text-align: left;
      font: inherit; }
    .ra-entry:hover { background: #eef2ff; }
    .ra-entry .ra-label { font-weight: 500; }
    .ra-entry .ra-value { color: #64748b; max-width: 130px; overflow: hidden;
      text-overflow: ellipsis; white-space: nowrap; }
    .ra-actions { display: flex; gap: 6px; margin-top: 8px; }
    .ra-actions button { flex: 1; padding: 6px; border: 1px solid #e2e8f0;
      border-radius: 6px; background: #fff; cursor: pointer; font: inherit; }
    .ra-actions .ra-fill-all { background: #4f46e5; color: #fff; border-color: #4f46e5; }
    .ra-status { margin-top: 6px; font-size: 12px; color: #059669; min-height: 16px; }
    .ra-error { color: #dc2626; }
    .ra-close { float: right; border: 0; background: none; cursor: pointer; font-size: 14px; }
  `;
  shadow.appendChild(style);

  const panel = document.createElement("div");
  panel.className = "ra-sidebar";
  panel.innerHTML = `
    <button class="ra-close" data-ra="close" title="收起">✕</button>
    <h3>ResuAlign 回填</h3>
    <p class="ra-tip">先点击网页上的输入框，再点下面的字段填入。</p>
    <div data-ra="entries"></div>
    <div class="ra-actions">
      <button data-ra="next">跳下一个空框</button>
      <button data-ra="fill-all" class="ra-fill-all">一键全填（实验）</button>
    </div>
    <div class="ra-status" data-ra="status"></div>
  `;
  shadow.appendChild(panel);

  const fab = document.createElement("button");
  fab.className = "ra-fab";
  fab.textContent = "回填";
  fab.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
  });
  shadow.appendChild(fab);
  panel.hidden = true;
  document.documentElement.appendChild(sidebarHost);

  const status = (text, isError) => {
    const node = shadow.querySelector('[data-ra="status"]');
    node.textContent = text;
    node.className = `ra-status${isError ? " ra-error" : ""}`;
  };

  shadow.querySelector('[data-ra="close"]').addEventListener("click", () => {
    panel.hidden = true;
  });

  // 分组渲染条目
  const mount = shadow.querySelector('[data-ra="entries"]');
  let lastGroup = "";
  for (const entry of entries) {
    if (entry.group !== lastGroup) {
      lastGroup = entry.group;
      const head = document.createElement("div");
      head.className = "ra-group";
      head.textContent = entry.group;
      mount.appendChild(head);
    }
    const btn = document.createElement("button");
    btn.className = "ra-entry";
    btn.innerHTML = `<span class="ra-label">${escapeHtml(entry.label)}</span><span class="ra-value">${escapeHtml(entry.value)}</span>`;
    btn.addEventListener("click", () => {
      const target = document.activeElement && core.isFillable(document.activeElement)
        ? document.activeElement
        : core.nextEmptyInput(document, null);
      if (!target) {
        status("页面上没有可填写的输入框", true);
        return;
      }
      core.setNativeValue(target, entry.value);
      status(`已填入：${entry.label}`);
    });
    mount.appendChild(btn);
  }

  shadow.querySelector('[data-ra="next"]').addEventListener("click", () => {
    const next = core.nextEmptyInput(document, document.activeElement);
    if (next) {
      next.focus();
      next.scrollIntoView({ block: "center" });
      status("已定位到下一个空框");
    } else {
      status("没有更多空输入框", true);
    }
  });

  shadow.querySelector('[data-ra="fill-all"]').addEventListener("click", () => {
    const count = core.fillAll(document, entries);
    status(count ? `已填 ${count} 个字段（请逐项核对）` : "没有匹配到字段", !count);
  });
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = String(text ?? "");
  return div.innerHTML;
}

async function toggle() {
  if (sidebarHost) {
    const panel = sidebarHost.shadowRoot.querySelector(".ra-sidebar");
    panel.hidden = !panel.hidden;
    return;
  }
  buildSidebar({});
  const panel = sidebarHost.shadowRoot.querySelector(".ra-sidebar");
  const mount = sidebarHost.shadowRoot.querySelector('[data-ra="entries"]');
  mount.innerHTML = '<p class="ra-tip">正在从本地 ResuAlign 服务拉取档案…</p>';
  try {
    const { core, stale } = await loadProfiles();
    // 重建侧边栏（含真实条目）
    sidebarHost.remove();
    sidebarHost = null;
    buildSidebar(core);
    const statusNode = sidebarHost.shadowRoot.querySelector('[data-ra="status"]');
    statusNode.textContent = stale
      ? "档案已过期（简历内容有改动），建议回简历中心重新生成"
      : `已加载 ${entries.length} 个字段`;
    sidebarHost.shadowRoot.querySelector(".ra-sidebar").hidden = false;
  } catch (error) {
    mount.innerHTML = `<p class="ra-tip ra-error">${escapeHtml(error.message)}</p>`;
    panel.hidden = false;
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "toggle-sidebar") {
    toggle().then(() => sendResponse({ ok: true }));
    return true;
  }
  return false;
});
