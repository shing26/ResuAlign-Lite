/* ResuAlign v3 Dashboard: metric strip + quick continue + skill gaps.
   All values are derived from the live API, never hard-coded. */
import { esc, formatDate, jobStatusLabel, state } from "./events.js";

function escAttr(value) {
  return esc(String(value ?? ""));
}

function toNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 ? Math.round(n) : 0;
}

function diagnosisFromSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== "object") return null;
  const result = snapshot.result || {};
  return result.diagnosis || result || null;
}

export async function renderDashboard(container) {
  const defaults = {
    kpi: {
      resumes: 0,
      jobs: 0,
      applied: 0,
      interview: 0,
      offer: 0,
      declined: 0,
      active_followups: 0,
    },
    skill_gaps: [],
    quick_continue: null,
  };
  let payload = defaults;
  let jobs = [];
  let resumes = [];
  try {
    const [dashboardResponse, jobsResponse, resumesResponse] = await Promise.all([
      fetch("/api/dashboard"),
      fetch("/api/jobs?limit=500"),
      fetch("/api/master-resumes"),
    ]);
    if (dashboardResponse.ok) {
      payload = { ...defaults, ...(await dashboardResponse.json()) };
    }
    if (jobsResponse.ok) jobs = (await jobsResponse.json()) || [];
    if (resumesResponse.ok) resumes = (await resumesResponse.json()) || [];
  } catch (error) {
    console.warn("Dashboard fallback data", error);
  }

  const kpi = { ...defaults.kpi, ...(payload.kpi || {}) };
  const jobsTotal = toNumber(kpi.jobs) || jobs.length;
  const applied = toNumber(kpi.applied);
  const interview = toNumber(kpi.interview);
  const offer = toNumber(kpi.offer);
  const declined = toNumber(kpi.declined);
  const followups = toNumber(kpi.active_followups);

  const alignedCount = jobs.filter(
    (job) => job && job.alignment_status === "succeeded",
  ).length;
  const completionRate =
    jobsTotal > 0 ? Math.round((alignedCount / jobsTotal) * 100) : 0;

  const currentResume = Array.isArray(resumes) ? resumes[0] : null;
  const diagnosis =
    state.diagnosis &&
    currentResume &&
    currentResume.latest_diagnosis_job_id &&
    state.diagnosis.job_id === currentResume.latest_diagnosis_job_id
      ? diagnosisFromSnapshot(state.diagnosis)
      : null;
  const rawScore = diagnosis && Number(diagnosis.score);
  const atsScore =
    Number.isFinite(rawScore) && rawScore >= 0
      ? Math.round(Math.min(100, rawScore))
      : null;

  const kpiCards = `
    <div class="metric-cell" data-kpi="jobs">
      <div class="metric-label">跟踪岗位</div>
      <div class="metric-value">${escAttr(jobsTotal)} <span>个</span></div>
      <div class="metric-hint">已投递 ${escAttr(applied)} · 面试中 ${escAttr(interview)} · Offer ${escAttr(offer)} · 放弃 ${escAttr(declined)}</div>
    </div>
    <div class="metric-cell" data-kpi="aligned">
      <div class="metric-label">已完成对齐</div>
      <div class="metric-value">${escAttr(alignedCount)} <span>/ ${escAttr(jobsTotal)}</span></div>
      <div class="metric-hint">完成率 ${escAttr(completionRate)}%</div>
    </div>
    <div class="metric-cell" data-kpi="ats">
      <div class="metric-label">主简历 ATS</div>
      <div class="metric-value">${atsScore == null ? "—" : escAttr(atsScore)}</div>
      <div class="metric-hint">${atsScore == null ? "未诊断" : `${escAttr(currentResume ? currentResume.title : "主简历")} · v${escAttr(currentResume ? currentResume.current_version : 1)}`}</div>
    </div>
    <div class="metric-cell" data-kpi="followups">
      <div class="metric-label">待跟进</div>
      <div class="metric-value">${escAttr(followups)} <span>条</span></div>
      <div class="metric-hint">48h 内到期口径</div>
    </div>`;

  const quick = payload.quick_continue || null;
  const quickHtml = quick && quick.job_id
    ? `
      <div class="quick-row" data-quick-continue>
        <div class="quick-main">
          <div class="quick-title">${escAttr(quick.title || "未命名岗位")}</div>
          <div class="quick-meta">${escAttr(quick.company || "未知公司")} · ${escAttr(quick.alignment_status || "待分析")}</div>
        </div>
        <div class="quick-right">
          <span class="pill ${quick.alignment_status === "succeeded" ? "pill-success" : "pill-warn"}">${escAttr(quick.alignment_status || "待分析")}</span>
          <a class="btn btn-primary btn-sm" href="#/workspace/${encodeURIComponent(quick.job_id)}">继续对齐</a>
        </div>
      </div>`
    : `
      <div class="quick-row" data-quick-continue>
        <div class="quick-main">
          <div class="quick-title">暂无待继续的对齐任务</div>
          <div class="quick-meta">到岗位库粘贴 JD，或从完整工作台继续处理。</div>
        </div>
      </div>`;

  const gaps = Array.isArray(payload.skill_gaps) ? payload.skill_gaps : [];
  const maxCount = Math.max(1, ...gaps.map((gap) => Number(gap.count) || 0));
  const gapHtml = gaps.length
    ? gaps
        .map((gap) => {
          const count = Math.max(0, Number(gap.count) || 0);
          const pct = Math.round((count / maxCount) * 100);
          const peak = pct === 100;
          return `
            <button type="button" class="skill-row" data-action="goto-skill" data-skill="${escAttr(gap.skill || "")}">
              <span class="skill-main">
                <span class="skill-name">${escAttr(gap.skill || "未命名技能")}</span>
                <span class="skill-track"><span class="skill-fill${peak ? "" : " warn"}" style="width:${peak ? 100 : pct}%"></span></span>
              </span>
              <span class="skill-count${peak ? " peak" : " warn"}">${peak ? `需求最多 · ${count} 岗` : `${count} 岗`}</span>
            </button>`;
        })
        .join("")
    : `<div class="muted small" data-skill-gaps>暂无技能缺口数据</div>`;

  const recentJobs = jobs
    .filter((job) => job && job.job_id)
    .sort(
      (a, b) =>
        (Number(b.updated_at) || 0) - (Number(a.updated_at) || 0),
    )
    .slice(0, 3);
  const recentHtml = recentJobs.length
    ? recentJobs
        .map(
          (job) => `
            <a class="recent-job" href="#/workspace/${encodeURIComponent(job.job_id)}">
              <span class="recent-job__title">${escAttr(job.title || "未命名岗位")}</span>
              <span class="recent-job__meta">${escAttr(jobStatusLabel(job.status))} · ${escAttr(formatDate(job.updated_at))}</span>
            </a>`,
        )
        .join("")
    : `<div class="recent-job recent-job--empty">暂无岗位动态</div>`;

  container.innerHTML = `
    <div class="view view-scroll dashboard-view">
      <div class="metric-strip dashboard-strip" data-dashboard-kpis>${kpiCards}</div>
      <div class="dash-grid">
        <section class="panel main-pane">
          <div class="panel-head">
            <div>
              <h2>快速继续</h2>
              <p>最近更新的待完成对齐任务</p>
            </div>
            <a class="link" href="#/workspace">进入完整工作台</a>
          </div>
          <div class="panel-body">
            ${quickHtml}
            <div class="recent-jobs">
              <div class="recent-jobs__head">
                <h3>最近岗位动态</h3>
                <span class="small muted">最近 3 条 · 对齐快照</span>
              </div>
              <div class="recent-jobs__list" data-dashboard-recent>${recentHtml}</div>
            </div>
          </div>
        </section>
        <aside class="panel aux-pane">
          <div class="panel-head">
            <div>
              <h2>技能缺口</h2>
              <p>目标岗位高频硬技能</p>
            </div>
          </div>
          <div class="panel-body" data-skill-gaps>${gapHtml}</div>
        </aside>
      </div>
    </div>`;
}
