/* ResuAlign v3 Dashboard: metric strip + quick continue + skill gaps.
   All values are derived from the live API, never hard-coded. */
import { alignmentStatusLabel, esc, formatDate, jobStatusLabel, state } from "./events.js";
import {
  alignmentOutcomeKind,
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
  /* D4（2026-10-22 审计）：「已完成对齐」是全量口径、「已优化条目」是近 7 天口径，
   * 原来只有后者标了时间窗，两个数字并排像自相矛盾（22 对齐却 0 产出）。
   * 这里把两个口径都写明；quality.diffs_total===0 时不再输出「采纳 0/0 条建议」
   * 这种除零文案（读起来像 bug），改成「近 N 天暂无建议记录」。 */
  const qualityHint = (() => {
    if (!quality) return "";
    const days = toNumber(quality.window_days) || 7;
    const saves = toNumber(quality.saves);
    const total = toNumber(quality.diffs_total);
    if (total === 0) {
      return `近 ${days} 天暂无建议记录${saves ? ` · 定稿 ${saves} 次` : ""}`;
    }
    const accepted = toNumber(quality.diffs_accepted);
    return `近 ${days} 天 · 定稿 ${saves} 次 · 采纳 ${accepted}/${total} 条建议`;
  })();
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
      <div class="metric-value"><a class="metric-link" href="#/jobs" title="打开岗位库，用「工作状态」筛选已对齐" aria-label="打开岗位库查看已对齐的岗位">${escAttr(alignedCount)} <span>/ ${escAttr(jobsTotal)}</span></a></div>
      <div class="metric-hint">全量口径 · 完成率 ${escAttr(completionRate)}%<br>有可用改写的岗位 / 全部岗位${noGapCount ? ` · 无缺口 ${escAttr(noGapCount)}` : ""}</div>
    </div>
    <div class="metric-cell" data-kpi="ats">
      <div class="metric-label">主简历 ATS</div>
      <div class="metric-value"><a class="metric-link" href="#/resume/list" title="打开简历中心查看诊断" aria-label="打开简历中心查看 ATS 诊断">${atsScore == null ? "—" : escAttr(atsScore)}</a></div>
      ${atsMeter}
      <div class="metric-hint">${atsScore == null ? "未诊断" : `${escAttr(currentResume ? currentResume.title : "主简历")} · v${escAttr(currentResume ? currentResume.current_version : 1)}`}</div>
    </div>
    <div class="metric-cell" data-kpi="quality" ${quality ? "" : "hidden"}>
      <div class="metric-label">已优化条目</div>
      <div class="metric-value"><a class="metric-link" href="#/resume/list" title="打开简历中心查看优化记录" aria-label="打开简历中心查看已优化条目">${quality && quality.diffs_accepted != null ? `${escAttr(quality.diffs_accepted)}<span> 条</span>` : "—"}</a></div>
      <div class="metric-hint">${qualityHint}</div>
    </div>`;

  const quick = payload.quick_continue || null;
  const qStatus = quick && quick.alignment_status;
  /* P1-3（03-AIE/01-GPM P1-3、02-UID ③-6）：快速继续卡消费 alignment_status
   * 分型渲染 —— failed/canceled/expired 必须红示失败，不能再看成「待分析」
   * 蓝主按钮（点进去才撞红横幅）。 */
  const qFailed = ["failed", "canceled", "expired"].includes(qStatus);
  const qBusy = ["running", "queued"].includes(qStatus);
  const qKind = quick ? alignmentOutcomeKind(quick) : "";
  const qStatusLabel =
    qKind === "no_safe_rewrite"
      ? "无安全改写"
      : qKind === "no_gap"
        ? "无需改写"
        : alignmentStatusLabel(qStatus);
  let quickRowClass = "";
  let quickBadgeClass = "pill-warn";
  let quickBadgeLabel = alignmentStatusLabel(qStatus);
  let quickBtnClass = "btn btn-primary btn-sm";
  let quickBtnLabel = "继续";
  let quickBtnExtra = "";
  if (qFailed && qKind === "no_safe_rewrite") {
    quickBadgeClass = "badge badge-amber";
    quickBadgeLabel = "无安全改写 · 查看证据";
    quickBtnClass = "btn btn-outline btn-sm";
    quickBtnLabel = "查看证据";
  } else if (qFailed) {
    quickRowClass = " quick-row--failed";
    quickBadgeClass = "badge badge-red";
    quickBadgeLabel = "上次失败 · 重新运行";
    quickBtnClass = "btn btn-danger-solid btn-sm";
    quickBtnLabel = "重新运行";
    /* Module 5: show failure_detail (with code) when available. */
    if (quick.failure_detail) {
      quickBadgeLabel = `上次失败 · 对齐未完成`;
    }
  } else if (qStatus === "succeeded" && qKind === "no_gap") {
    quickBadgeClass = "badge badge-amber";
    quickBadgeLabel = "无需改写";
    quickBtnClass = "btn btn-outline btn-sm";
    quickBtnLabel = "查看";
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
          <div class="quick-meta">${escAttr(quick.company || "未知公司")} · ${escAttr(qStatusLabel)}</div>
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
  /* D6（2026-10-22 审计）：原「技能缺口」只给全库需求频次，既不说「我缺什么」
   * 也不给下一步（接口契约只有 {skill,count}，前端拿不到 covered 字段）。
   * 短期纯前端方案：改叫「岗位高频技能」（数据确实来自全库岗位画像），
   * 底部给一条主 CTA，把「看数字」接到工作台的「拿主简历对比」动作上。 */
  const skillCtaHref =
    quick && quick.job_id
      ? `#/workspace/${encodeURIComponent(quick.job_id)}`
      : "#/workspace";
  /* gapHtml 自带 data-skill-gaps，外层保留同名容器（事件委托/测试都认它）。
   * 无数据时 format.js 返回纯文本空态，用非 flush 的 panel-body 才有内边距。 */
  const gapPanelClass = normalizedGaps.length
    ? "panel-body panel-body--flush skill-gap-panel"
    : "panel-body skill-gap-panel";

  /* D7（2026-10-23，审计 D7）：星座图口径 —— 原来纯按 updated_at 排序，唯一一条
     已投递岗位会被挤出前 5，漏斗有进展却永远不出现。现在把「有投递进展」的岗位
     固定排在动态顶部（同组内仍按更新时间倒序），其余按更新时间。 */
  const reachedStatuses = new Set(["applied", "interview", "offer"]);
  const reached = (job) => reachedStatuses.has(String(job.status || "").toLowerCase());
  const recentJobs = jobs
    .filter((job) => job && job.job_id)
    /* PM 评审：与快速继续结构性重复——动态里跳过快速继续那条 */
    .filter((job) => job.job_id !== (quick && quick.job_id))
    .sort((a, b) => {
      const aReached = reached(a) ? 1 : 0;
      const bReached = reached(b) ? 1 : 0;
      if (aReached !== bReached) return bReached - aReached;
      return (Number(b.updated_at) || 0) - (Number(a.updated_at) || 0);
    })
    /* 2026-10-22（审计 D3/D8）：原来固定 3 条，左卡底部空 135px 且没有
     * 「看全部」出口；改为 5 条 + 表头出口，把空白变成内容。 */
    .slice(0, 5);
  const recentHtml = recentJobs.length
    ? recentJobs
        .map(
          (job) => `
            <tr>
              <td class="recent-job__cell"><a class="recent-job__title" href="#/workspace/${encodeURIComponent(job.job_id)}" title="${escAttr(job.title || "未命名岗位")}">${escAttr(job.title || "未命名岗位")}</a></td>
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
                <a class="link" href="#/jobs">查看全部 ${escAttr(kpi.jobs || 0)} 个岗位 →</a>
              </div>
              <div class="recent-jobs__list" data-dashboard-recent>
                <table class="data-table recent-table">
                  <colgroup>
                    <col>
                    <col class="recent-table__col-status">
                    <col class="recent-table__col-time">
                    <col class="recent-table__col-action">
                  </colgroup>
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
              <h2>岗位高频技能</h2>
              <p>${escAttr(jobsTotal)} 个岗位里被要求最多的硬技能</p>
            </div>
          </div>
          <div class="${gapPanelClass}" data-skill-gaps>${gapHtml}</div>
          <div class="panel-body">
            <a class="btn btn-secondary btn-sm" href="${escAttr(skillCtaHref)}" data-skill-gap-cta>拿主简历对比一次 →</a>
          </div>
        </aside>
      </div>
    </div>`;
}
