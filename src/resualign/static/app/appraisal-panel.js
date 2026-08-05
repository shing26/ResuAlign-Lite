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

export async function renderAppraisal(app) {
  const panel = $("[data-appraisal-panel]");
  if (!panel || !state.wbJob) return;
  renderJdProfilePanel();
  try {
    const appraisal = await api(`/api/jobs/${encodeURIComponent(state.wbJob.job_id)}/appraisal`);
    state.wbAppraisal = { job_id: state.wbJob.job_id, ...appraisal };
    const verdictClass =
      appraisal.verdict === "投递" ? "badge-green" : appraisal.verdict === "考虑" ? "badge-amber" : "badge-red";
    const ringClass =
      appraisal.score >= 80
        ? "score-ring--high"
        : appraisal.score >= 60
          ? "score-ring--mid"
          : "score-ring--low";
    const benchmark = benchmarkSourceBadge(appraisal);
    panel.innerHTML = `
      <h3>投递价值评估</h3>
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
      <ul style="margin:10px 0 0 18px">${(appraisal.reasons || []).map((reason) => `<li class="small">${esc(reason)}</li>`).join("")}</ul>`;

    const radarBox = document.createElement("div");
    radarBox.className = "appraisal-radar";
    radarBox.innerHTML = renderAppraisalRadar(appraisal.components || {});
    const conclusion = document.createElement("div");
    conclusion.className = "appraisal-conclusion";
    conclusion.textContent = appraisal.conclusion || "";
    const reasonsList = panel.querySelector("ul");
    panel.insertBefore(radarBox, reasonsList);
    panel.insertBefore(conclusion, reasonsList);
  } catch (error) {
    panel.innerHTML = `<h3>投递价值评估</h3><p class="muted">${esc(error.message)}</p>`;
  }
}
