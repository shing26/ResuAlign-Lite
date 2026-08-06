import { $, api, esc, state } from "./events.js";
import { benchmarkSourceBadge, renderAppraisalRadar } from "./format.js";

export function renderJdProfilePanel() {
  const panel = $("[data-jd-profile-panel]");
  if (!panel) return;
  const profile = (state.wbResult && state.wbResult.jd_profile) || {};
  const chipList = (items) =>
    (items || []).map((item) => `<span class="chip">${esc(item)}</span>`).join("");
  if (!Object.keys(profile).length) {
    panel.innerHTML = `<h3>JD 画像</h3><div class="muted small">运行一次对齐分析后生成</div>`;
    return;
  }
  panel.innerHTML = `
    <h3>JD 画像</h3>
    <div class="jd-profile-summary">
      <div class="small muted">必备技能</div>
      <div class="chips">${chipList(profile.must_have_skills) || '<span class="muted small">—</span>'}</div>
      <div class="small muted">加分技能</div>
      <div class="chips">${chipList(profile.nice_to_have_skills) || '<span class="muted small">—</span>'}</div>
      <div class="small muted">业务场景</div>
      <div class="chips">${chipList(profile.business_scenarios) || '<span class="muted small">—</span>'}</div>
      <div class="small muted">年限 ${profile.min_years_experience ?? "—"} · 学历 ${chipList(profile.education_requirements) || "—"}</div>
    </div>`;
}

/* Body-only appraisal HTML (no <h3>: collapsible canvases keep the title
 * in their <summary>, classic panels get the <h3> from the filler). */
export function appraisalBodyHtml(appraisal) {
  const verdictClass =
    appraisal.verdict === "投递" ? "badge-green" : appraisal.verdict === "考虑" ? "badge-amber" : "badge-red";
  const ringClass =
    appraisal.score >= 80
      ? "score-ring--high"
      : appraisal.score >= 60
        ? "score-ring--mid"
        : "score-ring--low";
  const benchmark = benchmarkSourceBadge(appraisal);
  const radar = renderAppraisalRadar(appraisal.components || {});
  return `
      <div class="appraisal-score">
        <div class="score-ring ${ringClass}" style="--score:${appraisal.score}"><span>${Math.round(appraisal.score)}</span></div>
        <div>
          <span class="badge ${verdictClass}">${esc(appraisal.verdict)}</span>
          <div class="small muted" style="margin-top:4px">综合评分 ${appraisal.score} / 100</div>
        </div>
      </div>
      <div class="components">
        ${Object.entries(appraisal.components || {}).map(([key, value]) => `
          <div class="component-box"><div class="label">${esc(key)}</div><div class="value">${esc(value)}</div></div>`).join("")}
      </div>
      <div class="benchmark-source">
        <span class="badge ${benchmark.className}">${esc(benchmark.label)}</span>
        <span class="small muted">${esc(benchmark.detail)}</span>
      </div>
      ${radar ? `<div class="appraisal-radar">${radar}</div>` : ""}
      ${appraisal.conclusion ? `<div class="appraisal-conclusion">${esc(appraisal.conclusion)}</div>` : ""}
      <ul style="margin:10px 0 0 18px">${(appraisal.reasons || []).map((reason) => `<li class="small">${esc(reason)}</li>`).join("")}</ul>`;
}

/* Fill a [data-appraisal-panel] node. Collapsible canvases put the title
 * in <summary> and a [data-appraisal-body] placeholder inside; classic
 * panels keep their own <h3>. */
export function fillAppraisalPanel(panel, appraisal) {
  const body = panel.querySelector("[data-appraisal-body]");
  const html = appraisalBodyHtml(appraisal);
  if (body) {
    body.innerHTML = html;
    return;
  }
  panel.innerHTML = `<h3>投递价值评估</h3>${html}`;
}

function renderAppraisalError(panel, message) {
  const body = panel.querySelector("[data-appraisal-body]");
  const html = `<p class="muted">${esc(message)}</p>`;
  if (body) {
    body.innerHTML = html;
    return;
  }
  panel.innerHTML = `<h3>投递价值评估</h3>${html}`;
}

/* Render cached appraisal content without a network call. Returns true
 * when a cache entry for jobId exists (used by re-rendering canvases so
 * the panel survives SSE-driven repaints without hammering the API). */
export function renderAppraisalSync(panel, jobId) {
  if (!panel) return false;
  if (state.wbAppraisal && state.wbAppraisal.job_id === jobId) {
    fillAppraisalPanel(panel, state.wbAppraisal);
    return true;
  }
  return false;
}

export async function renderAppraisal(app) {
  const panel = $("[data-appraisal-panel]");
  if (!panel || !state.wbJob) return;
  renderJdProfilePanel();
  if (state.wbAppraisal && state.wbAppraisal.job_id === state.wbJob.job_id) {
    fillAppraisalPanel(panel, state.wbAppraisal);
    return;
  }
  try {
    const appraisal = await api(`/api/jobs/${encodeURIComponent(state.wbJob.job_id)}/appraisal`);
    state.wbAppraisal = { job_id: state.wbJob.job_id, ...appraisal };
    fillAppraisalPanel(panel, appraisal);
  } catch (error) {
    renderAppraisalError(panel, error.message);
  }
}
