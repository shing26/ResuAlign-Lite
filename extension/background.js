/* MV3 service worker：代理本地 API 请求（content script 的 fetch 受页面
 * origin 的 CORS 限制，background 在 host_permissions 授权下不受限）。 */

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "fetch-profile") {
    fetchProfiles(msg.server)
      .then((profiles) => sendResponse({ ok: true, profiles }))
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true; // 异步 sendResponse
  }
  return false;
});

async function fetchProfiles(server) {
  const base = String(server || "http://127.0.0.1:8000").replace(/\/+$/, "");
  const listRes = await fetch(`${base}/api/master-resumes`);
  if (!listRes.ok) throw new Error(`本地服务不可用（HTTP ${listRes.status}）`);
  const resumes = await listRes.json();
  if (!Array.isArray(resumes) || !resumes.length) {
    throw new Error("本地服务中还没有主简历，请先创建");
  }
  // 取最近更新的主简历的档案（GET 单查才带 profile 与 stale 标志）
  const latest = resumes[0];
  const detailRes = await fetch(
    `${base}/api/master-resumes/${encodeURIComponent(latest.resume_id)}`
  );
  if (!detailRes.ok) throw new Error(`档案获取失败（HTTP ${detailRes.status}）`);
  const detail = await detailRes.json();
  const profile = detail.profile;
  if (!profile || !profile.data) {
    throw new Error("该简历还没有结构化档案：请先在简历中心「生成档案」");
  }
  if (profile.stale) {
    console.warn("[ResuAlign] 档案已过期（简历内容在抽取后有改动）");
  }
  return [{ resumeId: latest.resume_id, title: latest.title, profile }];
}
