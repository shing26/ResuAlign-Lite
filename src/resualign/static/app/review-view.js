/* ResuAlign v3 投递复盘：本周投递节奏 + 阶段分布 + 行动清单 + 归因对比。
   全部数据来自 GET /api/review 的确定性聚合（零 LLM）。复盘不是新状态机：
   它消费既有时间线字段（applied_at / next_step_due_at / deadline /
   application_result），只做只读呈现。 */
import { alignmentStatusLabel, esc, jobStatusLabel, state } from "./events.js";

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
        </div>
      </div>`;
  }
  return `
    <div class="review-attr" data-review-attr-card>
      ${rateCell("已对齐", alignedTotal, toCount(attr.aligned_pass), attr.aligned_pass_rate)}
      ${rateCell("未对齐", unalignedTotal, toCount(attr.unaligned_pass), attr.unaligned_pass_rate)}
    </div>`;
}

export async function renderReviewView(container) {
  let payload = null;
  try {
    const response = await fetch("/api/review");
    if (response.ok) payload = await response.json();
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

  container.innerHTML = `
    <div class="view view-scroll dashboard-view">
      ${
        totalJobs
          ? ""
          : `<div class="panel main-pane"><div class="panel-body muted small">
              岗位库还是空的：先到「岗位库」用 Ctrl+K 粘贴 JD 或油猴插件录入岗位，
              投递并记录时间后，这里的节奏与复盘结论会自动生成。
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
              ${actionList(actions.overdue_next_steps, "没有逾期的跟进事项")}
            </div>
            <div class="review-action">
              <h3 class="review-action__title">临近截止 <span class="badge ${dueSoonCount ? "badge-amber" : "badge-gray"}">${dueSoonCount}</span></h3>
              ${actionList(actions.due_soon, "未来 7 天没有即将截止的岗位")}
            </div>
            <div class="review-action">
              <h3 class="review-action__title">超过 7 天无进展 <span class="badge ${staleCount ? "badge-amber" : "badge-gray"}">${staleCount}</span></h3>
              ${actionList(actions.stale_jobs, "没有长期停滞的岗位")}
            </div>
          </div>
        </section>
        <section class="panel main-pane" data-review-attribution>
          <div class="panel-head">
            <div><h2>对齐有效性</h2><p>投递结果归因对比——对齐是否真的提高过筛率</p></div>
          </div>
          <div class="panel-body">${attributionCard(payload.attribution)}</div>
        </section>
      </div>
    </div>`;
  state.route = state.route || {};
}
