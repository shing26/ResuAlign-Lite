/* ResuAlign v3 投递复盘：本周投递节奏 + 阶段分布 + 行动清单 + 归因对比。
   全部数据来自 GET /api/review 的确定性聚合（零 LLM）。复盘不是新状态机：
   它消费既有时间线字段（applied_at / next_step_due_at / deadline /
   application_result），只做只读呈现。 */
import { alignmentStatusLabel, esc, jobStatusLabel, state, toast } from "./events.js";
import { APPLICATION_RESULT_LABELS } from "./format.js";

function escAttr(value) {
  return esc(String(value ?? ""));
}

const STAGE_ORDER = ["draft", "applied", "interview", "offer", "withdrawn"];

function paceBars(weekPace) {
  const days = Array.isArray(weekPace) ? weekPace : [];
  const max = Math.max(1, ...days.map((d) => toCount(d.count)));
  return days
    .map((d) => {
      const count = toCount(d.count);
      const pct = Math.round((count / max) * 100);
      const label = String(d.date || "").slice(5);
      return `
        <div class="review-pace__col" title="${escAttr(d.date)} · 投递 ${count} 次">
          <div class="review-pace__bar${count ? "" : " is-empty"}" style="height:${Math.max(pct, count ? 12 : 4)}%"></div>
          <span class="review-pace__count">${count || ""}</span>
          <span class="review-pace__day">${escAttr(label)}</span>
        </div>`;
    })
    .join("");
}

function toCount(value) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? Math.round(n) : 0;
}

function stageChips(distribution) {
  const dist = distribution && typeof distribution === "object" ? distribution : {};
  return STAGE_ORDER.map((stage) => {
    const count = toCount(dist[stage]);
    return `
      <div class="review-stage__item${count ? "" : " is-zero"}" data-review-stage="${escAttr(stage)}">
        <span class="review-stage__count">${count}</span>
        <span class="review-stage__label">${escAttr(jobStatusLabel(stage))}</span>
      </div>`;
  }).join("");
}

function actionList(jobs, emptyText) {
  const rows = Array.isArray(jobs) ? jobs : [];
  if (!rows.length) {
    return `<div class="review-action__empty muted small">${escAttr(emptyText)}</div>`;
  }
  return rows
    .map(
      (job) => `
      <a class="review-action__row" href="#/workspace/${encodeURIComponent(job.job_id || "")}">
        <strong>${escAttr(job.title || "未命名岗位")}</strong>
        <span class="small muted">${escAttr(job.company || "")}</span>
        <span class="small">${jobStatusLabel(job.status)}${
          job.next_step ? ` · 下一步 ${escAttr(job.next_step)}` : ""
        }${job.next_step_due_at ? `（${escAttr(String(job.next_step_due_at).slice(0, 10))}）` : ""}${
          job.deadline ? ` · 截止 ${escAttr(String(job.deadline).slice(0, 10))}` : ""
        }</span>
      </a>`,
    )
    .join("");
}

function attributionCard(attribution) {
  const attr = attribution && typeof attribution === "object" ? attribution : {};
  const minSample = Number(attr.min_sample) || 3;
  const rateCell = (label, total, pass, rate) => {
    const hasRate = rate != null;
    return `
      <div class="review-attr__cell" data-review-attr="${escAttr(label)}">
        <div class="review-attr__rate">${hasRate ? `${Math.round(Number(rate) * 100)}<span>%</span>` : "—"}</div>
        <div class="metric-hint">${escAttr(label)} · ${escAttr(pass)}/${escAttr(total)} 过筛${
          hasRate ? "" : `（样本 < ${minSample}，暂不展示比率）`
        }</div>
      </div>`;
  };
  const alignedTotal = toCount(attr.aligned_total);
  const unalignedTotal = toCount(attr.unaligned_total);
  if (!alignedTotal && !unalignedTotal) {
    return `
      <div class="review-attr" data-review-attr-card>
        <div class="review-attr__empty muted small">
          暂无投递结果归因数据。在岗位详情里给已投递的岗位标注「投递结果归因」，
          积累后这里会对比<b>对齐过 vs 未对齐</b>简历的过筛率——对齐是否有效的直接证据。
          <div class="review-attr__empty-cta">
            <a class="btn btn-outline btn-sm" href="#/jobs">去岗位库标注</a>
          </div>
        </div>
      </div>`;
  }
  return `
    <div class="review-attr" data-review-attr-card>
      ${rateCell("已对齐", alignedTotal, toCount(attr.aligned_pass), attr.aligned_pass_rate)}
      ${rateCell("未对齐", unalignedTotal, toCount(attr.unaligned_pass), attr.unaligned_pass_rate)}
    </div>`;
}

/* 复盘冷启动（2026-09-10）：快速标注卡。列出近 14 天已投递但未标注归因的
 * 岗位，下拉选择即走既有 PATCH /api/jobs/{id}（全字段可选，部分更新有先例）。
 * 无待标注岗位时整卡隐藏，不占空间。 */
const ANNOTATE_WINDOW_DAYS = 14;
const ANNOTATE_MAX_ROWS = 8;

export function pendingAnnotateJobs(jobs, now = Date.now()) {
  const list = Array.isArray(jobs) ? jobs : [];
  const windowMs = ANNOTATE_WINDOW_DAYS * 86400000;
  return list
    .filter(
      (job) =>
        job &&
        job.job_id &&
        !job.application_result &&
        ["applied", "interview", "offer", "withdrawn"].includes(
          String(job.status || ""),
        ),
    )
    .map((job) => ({
      job,
      appliedAt: Date.parse(job.applied_at || job.updated_at || ""),
    }))
    .filter(({ appliedAt }) => Number.isFinite(appliedAt) && now - appliedAt <= windowMs)
    .sort((a, b) => b.appliedAt - a.appliedAt);
}

export function quickAnnotateHtml(rows, totalCount) {
  const options = Object.entries(APPLICATION_RESULT_LABELS)
    .map(
      ([value, label]) =>
        `<option value="${escAttr(value)}">${escAttr(label)}</option>`,
    )
    .join("");
  return `
    <div class="review-annotate" data-review-annotate>
      <h3 class="review-action__title">最近投递待标注 <span class="badge badge-amber">${escAttr(totalCount)}</span></h3>
      <p class="small muted">选择投递结果，下方「对齐有效性」会立即计入对比——样本够时直接看到对齐有没有提高过筛率。</p>
      <div class="review-annotate__list" data-annotate-list>
        ${rows
          .map(
            (job) => `
          <div class="review-annotate__row" data-annotate-row data-job-id="${escAttr(job.job_id)}">
            <div class="review-annotate__main">
              <strong>${escAttr(job.title || "未命名岗位")}</strong>
              <span class="small muted">${escAttr(job.company || "")} · 投递于 ${escAttr(String(job.applied_at || job.updated_at || "").slice(0, 10))}</span>
            </div>
            <select class="review-annotate__select" data-annotate-select aria-label="标注「${escAttr(job.title || "未命名岗位")}」的投递结果">
              <option value="">选择结果…</option>
              ${options}
            </select>
          </div>`,
          )
          .join("")}
      </div>
      ${totalCount > rows.length ? `<p class="small muted">仅显示最近 ${escAttr(rows.length)} 条，其余可在岗位库逐条标注。</p>` : ""}
    </div>`;
}

export async function renderReviewView(container) {
  let payload = null;
  let jobs = [];
  try {
    const [reviewResponse, jobsResponse] = await Promise.all([
      fetch("/api/review"),
      fetch("/api/jobs?limit=500"),
    ]);
    if (reviewResponse.ok) payload = await reviewResponse.json();
    if (jobsResponse.ok) jobs = (await jobsResponse.json()) || [];
  } catch (error) {
    console.warn("Review fetch failed", error);
  }

  if (!payload) {
    container.innerHTML = `
      <div class="view view-scroll dashboard-view">
        <div class="panel main-pane">
          <div class="panel-head"><div><h2>投递复盘</h2><p>聚合数据暂不可用</p></div></div>
          <div class="panel-body muted small">复盘数据加载失败，请确认服务可用后刷新。</div>
        </div>
      </div>`;
    return;
  }

  const actions = payload.actions || {};
  const overdueCount = (actions.overdue_next_steps || []).length;
  const staleCount = (actions.stale_jobs || []).length;
  const dueSoonCount = (actions.due_soon || []).length;
  const totalJobs = Object.values(payload.stage_distribution || {}).reduce(
    (sum, n) => sum + toCount(n),
    0,
  );
  const annotatePending = pendingAnnotateJobs(jobs);
  const annotateHtml = annotatePending.length
    ? quickAnnotateHtml(
        annotatePending.slice(0, ANNOTATE_MAX_ROWS).map(({ job }) => job),
        annotatePending.length,
      )
    : "";

  container.innerHTML = `
    <div class="view view-scroll dashboard-view">
      ${
        totalJobs
          ? ""
          : `<div class="panel main-pane"><div class="panel-body muted small">
              岗位库还是空的：先到「岗位库」用 Ctrl+K 粘贴 JD 或油猴插件录入岗位，
              投递并记录时间后，这里的节奏与复盘结论会自动生成。
              <div class="review-attr__empty-cta">
                <a class="btn btn-primary btn-sm" href="#/jobs">去岗位库录入</a>
              </div>
            </div></div>`
      }
      <div class="dash-grid">
        <section class="panel main-pane" data-review-pace>
          <div class="panel-head">
            <div><h2>本周投递节奏</h2><p>近 7 天按日投递次数——避免集中补投后忘记跟进</p></div>
            <span class="small muted">截至 ${escAttr(payload.generated_at || "")}</span>
          </div>
          <div class="panel-body">
            <div class="review-pace">${paceBars(payload.week_pace)}</div>
            <div class="review-stages" data-review-stages>${stageChips(payload.stage_distribution)}</div>
          </div>
        </section>
        <section class="panel main-pane" data-review-actions>
          <div class="panel-head"><div><h2>需要处理</h2><p>按优先级排序的复盘动作</p></div></div>
          <div class="panel-body">
            <div class="review-action">
              <h3 class="review-action__title">下一步已逾期 <span class="badge ${overdueCount ? "badge-red" : "badge-gray"}">${overdueCount}</span></h3>
              ${actionList(actions.overdue_next_steps, "没有逾期的跟进事项 · 给岗位设置「下一步跟进时间」，逾期会在这里提醒")}
            </div>
            <div class="review-action">
              <h3 class="review-action__title">临近截止 <span class="badge ${dueSoonCount ? "badge-amber" : "badge-gray"}">${dueSoonCount}</span></h3>
              ${actionList(actions.due_soon, "未来 7 天没有即将截止的岗位 · 给岗位补充截止日期可提前提醒")}
            </div>
            <div class="review-action">
              <h3 class="review-action__title">超过 7 天无进展 <span class="badge ${staleCount ? "badge-amber" : "badge-gray"}">${staleCount}</span></h3>
              ${actionList(actions.stale_jobs, "没有长期停滞的岗位 · 投递 7 天仍无进展的岗位会出现在这里")}
            </div>
          </div>
        </section>
        <section class="panel main-pane" data-review-attribution>
          <div class="panel-head">
            <div><h2>对齐有效性</h2><p>投递结果归因对比——对齐是否真的提高过筛率</p></div>
          </div>
          <div class="panel-body">
            ${annotateHtml}
            ${attributionCard(payload.attribution)}
          </div>
        </section>
      </div>
    </div>`;

  /* 快速标注：change 委托在本次渲染的容器内，选中即 PATCH 既有归因字段，
   * 成功后整视图重渲染（归因对比即时计入，标注卡随余量收缩）。 */
  const annotateList = container.querySelector("[data-annotate-list]");
  if (annotateList) {
    annotateList.addEventListener("change", async (event) => {
      const select = event.target.closest("[data-annotate-select]");
      if (!select || !select.value) return;
      const row = select.closest("[data-annotate-row]");
      const jobId = row && row.dataset.jobId;
      if (!jobId) return;
      select.disabled = true;
      try {
        const response = await fetch(
          `/api/jobs/${encodeURIComponent(jobId)}`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ application_result: select.value }),
          },
        );
        if (!response.ok) {
          const detail = await response.json().catch(() => ({}));
          throw new Error(detail.detail || `标注失败（HTTP ${response.status}）`);
        }
        toast("投递结果已标注", "success");
        renderReviewView(container);
      } catch (error) {
        select.disabled = false;
        toast(error.message || "标注失败，请重试", "error");
      }
    });
  }
  state.route = state.route || {};
}
