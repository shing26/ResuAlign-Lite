/* Apple Native Dashboard renderer (v2.0 shell).
   Pulls the real /api/dashboard payload and renders the unified
   Dashboard with the Apple card language. Keeps the #app mount point
   used by main.js routing. */
import { esc } from "./events.js";

function esc_attr(value) {
  return esc(String(value ?? ""));
}

export async function renderDashboard(container) {
  let kpi = { resumes: 0, jobs: 0, applied: 0, active_followups: 0 };
  let skillGaps = [];
  let quick = null;
  try {
    const res = await fetch("/api/dashboard");
    if (res.ok) {
      const data = await res.json();
      kpi = { ...kpi, ...(data.kpi || {}) };
      skillGaps = data.skill_gaps || [];
      quick = data.quick_continue || null;
    }
  } catch (error) {
    console.warn("Dashboard fallback data", error);
  }

  const maxCount = Math.max(
    1,
    ...skillGaps.map((gap) => Number(gap.count) || 0),
  );
  const appliedRate =
    kpi.jobs > 0 ? Math.round((kpi.applied / kpi.jobs) * 100) : 0;

  const kpiCards = `
    <div class="apple-card p-4 rounded-xl space-y-1">
      <div class="text-white/40 text-[11px] font-medium uppercase tracking-wider">基准简历数</div>
      <div class="text-2xl font-bold text-white font-mono flex items-center justify-between">
        <span>${esc_attr(kpi.resumes)} <span class="text-xs text-white/40 font-normal">份</span></span>
        <span class="text-xs text-applegreen bg-applegreen/10 px-2 py-0.5 rounded-full font-sans font-medium">主简历</span>
      </div>
      <p class="text-[11px] text-white/40">简历库总量</p>
    </div>
    <div class="apple-card p-4 rounded-xl space-y-1">
      <div class="text-white/40 text-[11px] font-medium uppercase tracking-wider">跟踪目标岗位</div>
      <div class="text-2xl font-bold text-white font-mono flex items-center justify-between">
        <span>${esc_attr(kpi.jobs)} <span class="text-xs text-white/40 font-normal">个</span></span>
        <span class="text-xs text-appleblue bg-appleblue/10 px-2 py-0.5 rounded-full font-sans font-medium">${esc_attr(kpi.applied)} 已投递</span>
      </div>
      <p class="text-[11px] text-white/40">投递转化 ${appliedRate}%</p>
    </div>
    <div class="apple-card p-4 rounded-xl space-y-1">
      <div class="text-white/40 text-[11px] font-medium uppercase tracking-wider">投递 / 面试 / Offer</div>
      <div class="text-2xl font-bold text-white font-mono flex items-center justify-between">
        <span>${esc_attr(kpi.applied)} <span class="text-xs text-white/40 font-normal">投递</span></span>
        <span class="text-xs text-appleamber bg-appleamber/10 px-2 py-0.5 rounded-full font-sans font-medium">${esc_attr(kpi.interview)} 面试</span>
      </div>
      <p class="text-[11px] text-white/40">Offer ${esc_attr(kpi.offer)} · 放弃 ${esc_attr(kpi.declined)}</p>
    </div>
    <div class="apple-card p-4 rounded-xl space-y-1">
      <div class="text-white/40 text-[11px] font-medium uppercase tracking-wider">待跟进事项</div>
      <div class="text-2xl font-bold text-appleamber font-mono flex items-center justify-between">
        <span>${esc_attr(kpi.active_followups)} <span class="text-xs text-white/40 font-normal">条</span></span>
        <span class="text-xs text-appleamber font-sans">48h 到期提醒</span>
      </div>
      <p class="text-[11px] text-white/40">面试 / 下一步到期跟踪</p>
    </div>`;

  const quickHtml = quick
    ? `
    <div class="p-4 rounded-xl bg-black/20 border border-white/[0.06] space-y-3">
      <div class="flex items-center justify-between">
        <div>
          <h4 class="font-bold text-white text-[14px]">${esc_attr(quick.title)}</h4>
          <p class="text-[11px] text-white/50">${esc_attr(quick.company || "未知公司")} · ${esc_attr(quick.alignment_status)}</p>
        </div>
        <span class="text-[11px] bg-appleamber/10 text-appleamber border border-appleamber/20 px-2.5 py-1 rounded-full font-mono">继续对齐</span>
      </div>
      <div class="flex items-center justify-between pt-1 text-[11px]">
        <span class="text-white/40">最近更新的待完成岗位</span>
        <a href="#/workspace/${esc_attr(quick.job_id)}" class="apple-press px-3.5 py-1.5 bg-appleblue text-white rounded-lg font-medium shadow-sm inline-block">继续治理对齐 ›</a>
      </div>
    </div>`
    : `
    <div class="p-4 rounded-xl bg-black/20 border border-white/[0.06] text-[12px] text-white/40">
      暂无待完成的对齐岗位，去岗位库导入一个新 JD 开始。
    </div>`;

  const gapHtml =
    skillGaps.length > 0
      ? skillGaps
          .map((gap) => {
            const count = Number(gap.count) || 0;
            const pct = Math.round((count / maxCount) * 100);
            const open = count > 0;
            return `
            <a href="#/workspace?skill=${encodeURIComponent(gap.skill || "")}"
               class="gap-action-card border ${open ? "border-applered/20 bg-applered/[0.04]" : "border-white/[0.04] bg-black/10"} p-2.5 rounded-lg cursor-pointer space-y-1.5 block group">
              <div class="flex justify-between text-[11.5px]">
                <span class="text-white font-medium ${open ? "group-hover:text-applered" : ""} transition flex items-center gap-1">
                  ${esc_attr(gap.skill)}
                  ${open ? '<span class="text-[10px] text-applered opacity-0 group-hover:opacity-100 transition">⚡ 点击进入专项补全</span>' : ""}
                </span>
                <span class="${open ? "text-applered font-bold" : "text-applegreen"} font-mono">
                  ${open ? `缺口 ${pct}% (${count} 岗位)` : "已覆盖"}
                </span>
              </div>
              <div class="w-full h-1.5 bg-black/40 rounded-full overflow-hidden">
                <div class="h-full ${open ? "bg-applered" : "bg-applegreen"} rounded-full" style="width: ${open ? pct : 100}%"></div>
              </div>
            </a>`;
          })
          .join("")
      : `<div class="text-[12px] text-white/40">暂无岗位缺口数据，导入 JD 后自动汇总。</div>`;

  container.innerHTML = `
    <div class="h-full p-6 overflow-y-auto space-y-6">
      <section class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">${kpiCards}</section>
      <section class="grid grid-cols-12 gap-6">
        <div class="col-span-12 lg:col-span-7 apple-card p-5 rounded-xl space-y-4">
          <div class="flex items-center justify-between border-b border-white/[0.08] pb-3">
            <div class="flex items-center space-x-2">
              <span class="text-base">⚡</span>
              <h3 class="font-bold text-white text-[14px]">最近对齐工作台 (Quick Continue)</h3>
            </div>
            <a href="#/workspace" class="text-[12px] text-appleblue hover:underline">进入完整工作台 ›</a>
          </div>
          ${quickHtml}
        </div>
        <div class="col-span-12 lg:col-span-5 apple-card p-5 rounded-xl space-y-4">
          <div class="flex items-center justify-between border-b border-white/[0.08] pb-3">
            <div class="flex items-center space-x-2">
              <span class="text-base">🎯</span>
              <h3 class="font-bold text-white text-[14px]">目标岗位高频硬技能缺口</h3>
            </div>
            <span class="text-[10px] text-appleblue bg-appleblue/10 px-2 py-0.5 rounded-full font-mono">点击直接生成改写</span>
          </div>
          <div class="space-y-3.5">${gapHtml}</div>
        </div>
      </section>
    </div>`;
}
