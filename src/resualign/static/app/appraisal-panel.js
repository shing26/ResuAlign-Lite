import { $, api, esc, state } from "./events.js";

export function renderWbProvenance(diff) {
  const quote = diff.provenance_quote || diff.provenance || "";
  const span = diff.source_span ? ` <span class="muted">${esc(diff.source_span)}</span>` : "";
  return quote
    ? `<blockquote class="provenance-quote">${esc(quote)}${span}</blockquote>`
    : "";
}

export function buildWbDetailHtml(result, diffs) {
  const jdProfile = result.jd_profile || {};
  const gapReport = result.gap_report || {};
  const evalScore = result.eval_score || {};
  const chipList = (items) =>
    (items || []).map((item) => `<span class="chip">${esc(item)}</span>`).join("");
  const listItems = (items) =>
    (items || []).map((item) => `<li class="small">${esc(item)}</li>`).join("");
  const provenanceRows = diffs
    .map((diff, index) => {
      const quote = diff.provenance_quote || diff.provenance || "";
      const span = diff.source_span ? ` <span class="muted">${esc(diff.source_span)}</span>` : "";
      return `<li class="small"><strong>${index + 1}. ${esc(diff.type)}</strong> ${esc(quote || "无来源引用")}${span}</li>`;
    })
    .join("");
  return `
    <details class="wb-detail" open>
      <summary>JD 画像</summary>
      <div class="wb-detail__body">
        <div class="small muted">必备技能</div><div class="chips">${chipList(jdProfile.must_have_skills) || '<span class="muted small">—</span>'}</div>
        <div class="small muted">加分技能</div><div class="chips">${chipList(jdProfile.nice_to_have_skills) || '<span class="muted small">—</span>'}</div>
        <div class="small muted">软技能</div><div class="chips">${chipList(jdProfile.soft_skills) || '<span class="muted small">—</span>'}</div>
        <div class="small muted">业务场景</div><div class="chips">${chipList(jdProfile.business_scenarios) || '<span class="muted small">—</span>'}</div>
        <div class="small muted">年限 ${jdProfile.min_years_experience ?? "—"} · 学历 ${chipList(jdProfile.education_requirements) || "—"}</div>
      </div>
    </details>
    <details class="wb-detail">
      <summary>差距报告</summary>
      <div class="wb-detail__body">
        <div class="small muted">缺失关键词</div><ul style="margin:4px 0 0 18px">${listItems(gapReport.missing_keywords) || '<span class="muted small">—</span>'}</ul>
        <div class="small muted">错位强调</div><ul style="margin:4px 0 0 18px">${listItems(gapReport.misaligned_emphasis) || '<span class="muted small">—</span>'}</ul>
        <div class="small muted">优势匹配</div><ul style="margin:4px 0 0 18px">${listItems(gapReport.strength_matches) || '<span class="muted small">—</span>'}</ul>
      </div>
    </details>
    <details class="wb-detail">
      <summary>Eval 评分</summary>
      <div class="wb-detail__body">
        <div class="row">
          <span class="badge badge-blue">JD 匹配 ${evalScore.jd_match_score ?? "—"}</span>
          <span class="badge badge-teal">提升 ${evalScore.improvement ?? "—"}</span>
          <span class="badge ${evalScore.hallucination_detected ? "badge-red" : "badge-green"}">幻觉 ${evalScore.hallucination_detected ? "检出" : "未检出"}</span>
          <span class="badge badge-gray">覆盖率 ${evalScore.gap_coverage ?? "—"}</span>
        </div>
        <ul style="margin:8px 0 0 18px">${listItems(evalScore.hallucination_details)}</ul>
      </div>
    </details>
    <details class="wb-detail">
      <summary>Provenance 来源</summary>
      <ul style="margin:4px 0 0 18px">${provenanceRows || '<li class="small muted">暂无来源引用</li>'}</ul>
    </details>`;
}

export function benchmarkSourceBadge(appraisal) {
  const source = appraisal.benchmark_source || "暂无基准";
  const city = appraisal.city_normalized;
  if (source === "设置表（城市）") {
    return {
      className: "badge-teal",
      label: city ? `设置表（${city}）` : "设置表（城市）",
      detail: city
        ? `基准来源：设置表（城市） · 城市归一化：${city}`
        : "基准来源：设置表（城市）",
    };
  }
  if (source === "库内同类中位") {
    return {
      className: "badge-gray",
      label: "库内同类中位",
      detail: "基准来源：库内同类中位",
    };
  }
  return {
    className: "badge-amber",
    label: "暂无基准，中性处理",
    detail: "基准来源：暂无基准",
  };
}

export function renderAppraisalRadar(components) {
  const keys = ["match", "salary", "hard_conditions", "quality", "commute"].filter(
    (key) => components[key] != null,
  );
  if (!keys.length) return "";
  const size = 180;
  const center = size / 2;
  const radius = 68;
  const angle = (index) => -Math.PI / 2 + (index * 2 * Math.PI) / keys.length;
  const point = (value, index) => {
    const ratio = Math.max(0, Math.min(100, Number(value) || 0)) / 100;
    const x = center + radius * ratio * Math.cos(angle(index));
    const y = center + radius * ratio * Math.sin(angle(index));
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  };
  const labels = {
    match: "匹配",
    salary: "薪资",
    hard_conditions: "条件",
    quality: "质量",
    commute: "通勤",
  };
  const axes = keys
    .map((key, index) => {
      const [x, y] = point(100, index).split(",");
      return `<line x1="${center}" y1="${center}" x2="${x}" y2="${y}" class="radar-axis"></line>`;
    })
    .join("");
  const polygon = keys.map((key, index) => point(components[key], index)).join(" ");
  const dots = keys
    .map((key, index) => {
      const [x, y] = point(components[key], index).split(",");
      return `<circle cx="${x}" cy="${y}" r="3" class="radar-dot"></circle>`;
    })
    .join("");
  const text = keys
    .map((key, index) => {
      const [x, y] = point(112, index).split(",");
      return `<text x="${x}" y="${y}" class="radar-label">${esc(labels[key] || key)}</text>`;
    })
    .join("");
  return `<svg class="radar-svg" viewBox="0 0 ${size} ${size}" role="img" aria-label="Appraisal radar">${axes}${polygon ? `<polygon points="${polygon}" class="radar-polygon"></polygon>` : ""}${dots}${text}</svg>`;
}

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
