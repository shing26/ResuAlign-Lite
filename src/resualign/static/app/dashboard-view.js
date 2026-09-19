/* ResuAlign v3 Dashboard: metric strip + quick continue + skill gaps.
   All values are derived from the live API, never hard-coded. */
import { alignmentStatusLabel, esc, formatDate, jobStatusLabel, state } from "./events.js";
import {
  atsHealthScoreLevel,
  atsHealthTone,
  dashboardEmptyGuideHtml,
  shortenGapPhrase,
  skillGapHtml,
} from "./format.js";
import { icon } from "./icons.js";

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

function scoreTone(score) {
  if (score == null) return "";
  const tone = atsHealthTone(score);
  return tone === "high" ? "ord-5" : tone === "mid" ? "ord-4" : "ord-1";
}

function jobStatusTone(status) {
  const canonical = String(status || "").toLowerCase();
  if (canonical === "offer") return "success";
  if (canonical === "interview") return "info";
  if (canonical === "withdrawn") return "danger";
  if (canonical === "applied") return "accent";
  return "neutral";
}

function syncRailFunnel(kpi) {
  const root = document.querySelector("[data-rail-funnel]");
  if (!root) return;
  const applied = document.querySelector("[data-rail-funnel-applied]");
  const interview = document.querySelector("[data-rail-funnel-interview]");
  if (applied) applied.textContent = toNumber(kpi.applied);
  if (interview) interview.textContent = toNumber(kpi.interview);
  root.hidden = false;
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
    },
    skill_gaps: [],
    quick_continue: null,
    quality: null,
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
  const resumeList = Array.isArray(resumes) ? resumes : [];

  /* #111 / ADR-0041 决定 5：「完成对齐」分子只数 usable≥1——零产出的
   * succeeded（无缺口型）不再虚增完成率，「100%」从制度上不可达。 */
  const jobUsable = (job) =>
    typeof job.usable_diffs === "number"
      ? job.usable_diffs
      : (job.diffs || []).length;
  const alignedCount = jobs.filter(
    (job) => job && job.alignment_status === "succeeded" && jobUsable(job) >= 1,
  ).length;
  const noGapCount = jobs.filter(
    (job) => job && job.alignment_status === "succeeded" && jobUsable(job) === 0,
  ).length;
  const completionRate =
    jobsTotal > 0 ? Math.round((alignedCount / jobsTotal) * 100) : 0;

  const currentResume = Array.isArray(resumes)
    ? resumes.find((resume) => resume && resume.latest_diagnosis) ||
      resumes[0] ||
      null
    : null;
  const diagnosis =
    (currentResume && currentResume.latest_diagnosis) ||
    (state.diagnosis &&
      currentResume &&
      currentResume.latest_diagnosis_job_id &&
      state.diagnosis.job_id === currentResume.latest_diagnosis_job_id
      ? diagnosisFromSnapshot(state.diagnosis)
      : null);
  const rawScore = diagnosis && Number(diagnosis.score);
  const atsScore =
    Number.isFinite(rawScore) && rawScore >= 0
      ? Math.round(Math.min(100, rawScore))
      : null;
  const emptyGuide = jobsTotal === 0 && resumeList.length === 0
    ? dashboardEmptyGuideHtml()
    : "";

  const quality = payload.quality || null;
  const atsTone = scoreTone(atsScore);
  const atsLabel = atsScore == null ? "未诊断" : atsHealthScoreLevel(atsScore);
  const atsMeter = atsScore == null
    ? ""
    : `<div class="metric-meter">
        <span class="meter ${atsTone}" role="img" aria-label="ATS 分数 ${escAttr(atsScore)} 分，${escAttr(atsLabel)}"><span class="meter__fill" style="width:${escAttr(atsScore)}%"></span></span>
        <span class="metric-meter__label">${escAttr(atsLabel)}</span>
      </div>`;
  const kpiCards = `
    <div class="metric-cell" data-kpi="jobs">
      <div class="metric-label">跟踪岗位</div>
      <div class="metric-value">${escAttr(jobsTotal)} <span>个</span></div>
      <div class="metric-counts">
        <a class="count-pair" href="#/jobs?status=applied" aria-label="查看已投递的 ${escAttr(applied)} 个岗位">
          <span class="dot metric-dot metric-dot--applied" aria-hidden="true"></span><span>已投递</span><span class="count-pair__value">${escAttr(applied)}</span>
        </a>
        <a class="count-pair" href="#/jobs?status=interview" aria-label="查看面试中的 ${escAttr(interview)} 个岗位">
          <span class="dot metric-dot metric-dot--interview" aria-hidden="true"></span><span>面试中</span><span class="count-pair__value">${escAttr(interview)}</span>
        </a>
        <a class="count-pair" href="#/jobs?status=offer" aria-label="查看已拿 Offer 的 ${escAttr(offer)} 个岗位">
          <span class="dot metric-dot metric-dot--offer" aria-hidden="true"></span><span>已拿 Offer</span><span class="count-pair__value">${escAttr(offer)}</span>
        </a>
        <a class="count-pair" href="#/jobs?status=withdrawn" aria-label="查看已放弃的 ${escAttr(declined)} 个岗位">
          <span class="dot metric-dot metric-dot--withdrawn" aria-hidden="true"></span><span>放弃</span><span class="count-pair__value">${escAttr(declined)}</span>
        </a>
      </div>
    </div>
    <div class="metric-cell" data-kpi="aligned">
      <div class="metric-label">已完成对齐</div>
      <div class="metric-value">${escAttr(alignedCount)} <span>/ ${escAttr(jobsTotal)}</span></div>
      <div class="metric-hint">完成率 ${escAttr(completionRate)}%${noGapCount ? ` · 无缺口 ${escAttr(noGapCount)}` : ""}</div>
    </div>
    <div class="metric-cell" data-kpi="ats">
      <div class="metric-label">主简历 ATS</div>
      <div class="metric-value">${atsScore == null ? "—" : escAttr(atsScore)}</div>
      ${atsMeter}
      <div class="metric-hint">${atsScore == null ? "未诊断" : `${escAttr(currentResume ? currentResume.title : "主简历")} · v${escAttr(currentResume ? currentResume.current_version : 1)}`}</div>
    </div>
    <div class="metric-cell" data-kpi="quality" ${quality ? "" : "hidden"}>
      <div class="metric-label">已优化条目</div>
      <div class="metric-value">${quality && quality.diffs_accepted != null ? `${escAttr(quality.diffs_accepted)}<span> 条</span>` : "—"}</div>
      <div class="metric-hint">${quality ? `近 ${escAttr(quality.window_days)} 天 · 定稿 ${escAttr(quality.saves)} 次 · 采纳 ${escAttr(quality.diffs_accepted)}/${escAttr(quality.diffs_total)} 条建议` : ""}</div>
    </div>`;

  const quick = payload.quick_continue || null;
  const qStatus = quick && quick.alignment_status;
  /* P1-3（03-AIE/01-GPM P1-3、02-UID ③-6）：快速继续卡消费 alignment_status
   * 分型渲染 —— failed/canceled/expired 必须红示失败，不能再看成「待分析」
   * 蓝主按钮（点进去才撞红横幅）。 */
  const qFailed = ["failed", "canceled", "expired"].includes(qStatus);
  const qBusy = ["running", "queued"].includes(qStatus);
  let quickRowClass = "";
  let quickBadgeClass = "pill-warn";
  let quickBadgeLabel = alignmentStatusLabel(qStatus);
  let quickBtnClass = "btn btn-primary btn-sm";
  let quickBtnLabel = "继续";
  let quickBtnExtra = "";
  if (qFailed) {
    quickRowClass = " quick-row--failed";
    quickBadgeClass = "badge badge-red";
    quickBadgeLabel = "上次失败 · 重新运行";
    quickBtnClass = "btn btn-danger-solid btn-sm";
    quickBtnLabel = "重新运行";
  } else if (qStatus === "succeeded") {
    quickBadgeClass = "badge badge-green";
    quickBadgeLabel = "已对齐";
    quickBtnClass = "btn btn-outline btn-sm";
    quickBtnLabel = "查看";
  } else if (qBusy) {
    quickBadgeClass = "badge badge-blue";
    quickBadgeLabel = "分析中";
    quickBtnClass = "btn btn-primary btn-sm is-loading";
    quickBtnLabel = "分析中";
    quickBtnExtra = ' aria-disabled="true"';
  }
  const quickHref = qBusy || !quick
    ? ""
    : `href="#/workspace/${encodeURIComponent(quick.job_id)}"`;
  const quickHtml = quick && quick.job_id
    ? `
      <div class="quick-row${quickRowClass}" data-quick-continue>
        <div class="quick-main">
          <div class="quick-title">${escAttr(quick.title || "未命名岗位")}</div>
          <div class="quick-meta">${escAttr(quick.company || "未知公司")} · ${escAttr(alignmentStatusLabel(quick.alignment_status))}</div>
        </div>
        <div class="quick-right">
          <span class="${quickBadgeClass}">${escAttr(quickBadgeLabel)}</span>
          <a class="${quickBtnClass}" ${quickHref}${quickBtnExtra}>${escAttr(quickBtnLabel)}</a>
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
  /* PM 评审（2026-09-01）颜色倒挂修复：高缺口=红（急需补），低缺口=中性。
   * 统一走 format.js skillGapHtml（原内联实现把峰值行标中性、低缺口全红），
   * 技能名沿用 shortenGapPhrase 截断。 */
  const normalizedGaps = gaps.map((gap) => ({
    ...gap,
    skill: shortenGapPhrase(gap.skill || "未命名技能"),
  }));
  const gapHtml = skillGapHtml(normalizedGaps, undefined, { variant: "table" });

  const recentJobs = jobs
    .filter((job) => job && job.job_id)
    /* PM 评审：与快速继续结构性重复——动态里跳过快速继续那条 */
    .filter((job) => job.job_id !== (quick && quick.job_id))
    .sort(
      (a, b) =>
        (Number(b.updated_at) || 0) - (Number(a.updated_at) || 0),
    )
    .slice(0, 3);
  const recentHtml = recentJobs.length
    ? recentJobs
        .map(
          (job) => `
            <tr>
              <td><a class="recent-job__title" href="#/workspace/${encodeURIComponent(job.job_id)}">${escAttr(job.title || "未命名岗位")}</a></td>
              <td><span class="badge pill-neutral"><span class="dot metric-dot metric-dot--${jobStatusTone(job.status)}" aria-hidden="true"></span>${escAttr(jobStatusLabel(job.status))}</span></td>
              <td class="is-num cell-muted">${escAttr(formatDate(job.updated_at))}</td>
              <td class="is-num"><a class="icon-btn recent-job__open" href="#/workspace/${encodeURIComponent(job.job_id)}" aria-label="打开 ${escAttr(job.title || "未命名岗位")} 的工作台">${icon("chevron-right", 16)}</a></td>
            </tr>`,
        )
        .join("")
    : `<tr><td colspan="4" class="recent-job--empty">暂无岗位动态</td></tr>`;

  syncRailFunnel(kpi);

  container.innerHTML = `
    <div class="view view-scroll dashboard-view">
      ${emptyGuide}
      <div class="metric-strip dashboard-strip" data-dashboard-kpis>${kpiCards}</div>
      <div class="dash-grid">
        <section class="panel dashboard-panel main-pane">
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
                <span class="small muted">最近 3 条 · 投递快照</span>
              </div>
              <div class="recent-jobs__list" data-dashboard-recent>
                <table class="data-table recent-table">
                  <thead>
                    <tr>
                      <th scope="col">岗位</th>
                      <th scope="col">状态</th>
                      <th scope="col" class="is-num">更新时间</th>
                      <th scope="col" aria-label="操作"></th>
                    </tr>
                  </thead>
                  <tbody>${recentHtml}</tbody>
                </table>
              </div>
            </div>
          </div>
        </section>
        <aside class="panel dashboard-panel aux-pane">
          <div class="panel-head">
            <div>
              <h2>技能缺口</h2>
              <p>目标岗位高频硬技能</p>
            </div>
          </div>
          <div class="panel-body panel-body--flush skill-gap-panel" data-skill-gaps>${gapHtml}</div>
        </aside>
      </div>
    </div>`;
}
