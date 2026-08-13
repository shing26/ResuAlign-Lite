/* Pure formatting / state-derivation helpers shared by the browser ESM modules.
 *
 * This module MUST stay free of DOM/window/document/localStorage/fetch access
 * so it can be imported and unit-tested directly under Node
 * (see tests/frontend/*.test.mjs). Function bodies were moved from main.js /
 * events.js / split-canvas.js / diff-editor.js /
 * command-panel.js. Signatures and HTML output are covered by the node:test
 * suite; DOM-touching callers keep thin wrappers in their original modules.
 */

/* Sprint 5: 复用 settings-form.js 的掩码纯函数（maskApiKey），该模块无
 * DOM/fetch 依赖且不 import 本模块，不会产生循环依赖。 */
import { maskApiKey } from "./settings-form.js";

/* ------------------------------------------------------------------ */
/* HTML escaping                                                       */
/* ------------------------------------------------------------------ */

export function esc(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char],
  );
}

/* ------------------------------------------------------------------ */
/* Job status / classification vocabulary                              */
/* ------------------------------------------------------------------ */

export const JOB_FUNCTIONS = [
  "后端", "前端", "算法", "数据", "测试", "运维",
  "产品", "设计", "运营", "销售", "其他",
];
export const SENIORITIES = ["初级", "中级", "高级", "资深", "未知"];
export const JOB_STATUSES = ["未投递", "已投递", "面试中", "已拿Offer", "放弃"];
export const JOB_STATUS_CANONICAL = ["draft", "applied", "interview", "offer", "withdrawn"];
export const JOB_STATUS_ALIASES = {
  "未投递": "draft",
  "已投递": "applied",
  "面试中": "interview",
  "已拿Offer": "offer",
  "放弃": "withdrawn",
};
export const JOB_STATUS_LABELS = {
  draft: "未投递",
  applied: "已投递",
  interview: "面试中",
  offer: "已拿Offer",
  withdrawn: "放弃",
};

export const DEFAULT_VOCABULARY = {
  job_functions: JOB_FUNCTIONS,
  seniorities: SENIORITIES,
  statuses: JOB_STATUSES,
};

export function canonicalJobStatus(status) {
  const value = String(status || "").trim();
  return JOB_STATUS_ALIASES[value] || value;
}

export function jobStatusRank(status) {
  return JOB_STATUS_CANONICAL.indexOf(canonicalJobStatus(status));
}

export function isBackwardJobStatus(current, target) {
  const from = jobStatusRank(current);
  const to = jobStatusRank(target);
  return from >= 0 && to >= 0 && to < from;
}

export function jobStatusLabel(status) {
  const canonical = canonicalJobStatus(status);
  return JOB_STATUS_LABELS[canonical] || canonical;
}

export function normalizeVocabularyList(values, fallback) {
  if (!Array.isArray(values)) return [...fallback];
  const cleaned = values
    .map((value) => String(value ?? "").trim())
    .filter(Boolean);
  return cleaned.length ? cleaned : [...fallback];
}

export function normalizeVocabulary(vocabulary) {
  const source = vocabulary && typeof vocabulary === "object" ? vocabulary : {};
  return {
    job_functions: normalizeVocabularyList(source.job_functions, JOB_FUNCTIONS),
    seniorities: normalizeVocabularyList(source.seniorities, SENIORITIES),
    statuses: normalizeVocabularyList(source.statuses, JOB_STATUSES),
  };
}

/* ------------------------------------------------------------------ */
/* Date / salary / option formatting                                   */
/* ------------------------------------------------------------------ */

export function formatDate(timestamp) {
  if (!timestamp) return "—";
  const date = new Date(timestamp * 1000);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
    date.getDate(),
  ).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(
    date.getMinutes(),
  ).padStart(2, "0")}`;
}

export function formatSalary(job) {
  const min = job.salary_min;
  const max = job.salary_max;
  const unit = job.salary_currency || "CNY";
  if (min == null && max == null) return "薪资面议";
  if (min != null && max != null) return `${min / 1000}-${max / 1000}K`;
  return `${(min ?? max) / 1000}K`;
}

export function options(values, selected) {
  return values
    .map(
      (value) =>
        `<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${esc(value)}</option>`,
    )
    .join("");
}

/* ------------------------------------------------------------------ */
/* Markdown rendering                                                  */
/* ------------------------------------------------------------------ */

export function inlineMarkdown(text) {
  return text
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

export function renderMarkdown(text) {
  const html = [];
  let listOpen = false;
  const closeList = () => {
    if (listOpen) {
      html.push("</ul>");
      listOpen = false;
    }
  };
  for (const raw of String(text || "").split("\n")) {
    const line = esc(raw);
    const trimmed = line.trim();
    if (!trimmed) {
      closeList();
      continue;
    }
    const heading = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      closeList();
      const level = heading[1].length;
      html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    const listItem = trimmed.match(/^[-*•]\s+(.*)$/);
    if (listItem) {
      if (!listOpen) {
        html.push("<ul>");
        listOpen = true;
      }
      html.push(`<li>${inlineMarkdown(listItem[1])}</li>`);
      continue;
    }
    closeList();
    html.push(`<p>${inlineMarkdown(trimmed)}</p>`);
  }
  closeList();
  return html.join("");
}

/* Pure core of buildDiagnosisMarkdown: given the diagnosis object and a
 * document title, produce the Markdown export text. */
export function buildDiagnosisMarkdownFrom(diagnosis, title, originalContent = "") {
  const lines = [
    `# ${title}`,
    "",
    `> 诊断分：${diagnosis.score ?? "—"} / 100 · 模型：${diagnosis.model || "未知"}`,
    "",
  ];
  if ((diagnosis.skills || []).length) {
    lines.push(
      "## 技能",
      "",
      ...diagnosis.skills.map((skill) => `- ${skill}`),
      "",
    );
  }
  if ((diagnosis.issues || []).length) {
    lines.push(
      "## 问题",
      "",
      ...diagnosis.issues.map((issue) => `- ${issue}`),
      "",
    );
  }
  if ((diagnosis.suggestions || []).length) {
    lines.push(
      "## 优化建议",
      "",
      ...diagnosis.suggestions.map((item) => `- ${item}`),
      "",
    );
  }
  if (originalContent) {
    lines.push("## 原始简历", "", originalContent, "");
  }
  return lines.join("\n");
}

/* ------------------------------------------------------------------ */
/* Hash routing                                                        */
/* ------------------------------------------------------------------ */

const ROUTE_NAMES = ["resume", "resumes", "jobs", "workspace", "settings", "dashboard"];

export function parseHashValue(hash) {
  const value = String(hash || "").replace(/^#\/?/, "");
  /* Query params let flows deep-link into a view with context, e.g.
   * "#/workspace/<jobId>?resume=<id>" pre-selects the master resume
   * dropdown on the optimizer canvas (F4). */
  const [pathPart, queryPart] = value.split("?");
  const query = new URLSearchParams(queryPart || "");
  const resumeFromQuery = query.get("resume") || null;
  const parts = (pathPart || "").split("/").filter(Boolean);
  if (parts[0] === "workspace" && parts[1]) {
    let jobId = parts[1];
    try {
      jobId = decodeURIComponent(jobId);
    } catch {
      /* keep raw value */
    }
    return { name: "workspace", jobId, resumeId: resumeFromQuery };
  }
  /* #/workspace?job_id=X（或 ?id=X）也进入工作台：蓝图的显式路由契约 */
  if (parts[0] === "workspace") {
    const jobFromQuery = query.get("job_id") || query.get("id") || null;
    return { name: "workspace", jobId: jobFromQuery, resumeId: resumeFromQuery };
  }
  if ((parts[0] === "resume" || parts[0] === "resumes") && parts[1]) {
    let resumeId = parts[1];
    try {
      resumeId = decodeURIComponent(resumeId);
    } catch {
      /* keep raw value */
    }
    return { name: "resume", jobId: null, resumeId };
  }
  /* "resumes" 是 "resume" 的复数路由别名（蓝图契约 #/resumes） */
  const name = ROUTE_NAMES.includes(parts[0]) ? parts[0] : "resume";
  return { name: name === "resumes" ? "resume" : name, jobId: null, resumeId: resumeFromQuery };
}

/* ------------------------------------------------------------------ */
/* Import text parsing (JSON array or CSV)                             */
/* ------------------------------------------------------------------ */

export function parseImportText(text, filename) {
  const trimmed = text.trim();
  if (!trimmed) return [];
  if (trimmed.startsWith("[") || filename.endsWith(".json")) {
    try {
      const parsed = JSON.parse(trimmed);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }
  const lines = trimmed.split(/\r?\n/).filter(Boolean);
  if (!lines.length) return [];
  const headers = lines[0].split(",").map((header) => header.trim());
  return lines.slice(1).map((line) => {
    const values = line.split(",").map((value) => value.trim());
    const row = {};
    headers.forEach((header, index) => {
      if (header) row[header] = values[index] || "";
    });
    return row;
  });
}

/* ------------------------------------------------------------------ */
/* Line diff                                                           */
/* ------------------------------------------------------------------ */

export function lineDiff(original, proposed) {
  const originalLines = String(original || "").split("\n");
  const proposedLines = String(proposed || "").split("\n");
  const oldSet = new Set(originalLines.map((line) => line.trim()));
  const newSet = new Set(proposedLines.map((line) => line.trim()));
  const rows = [];
  for (const line of originalLines) {
    const trimmed = line.trim();
    if (trimmed && !newSet.has(trimmed)) rows.push({ type: "remove", text: line });
  }
  for (const line of proposedLines) {
    const trimmed = line.trim();
    if (trimmed && !oldSet.has(trimmed)) rows.push({ type: "add", text: line });
  }
  return rows;
}

/* ------------------------------------------------------------------ */
/* Split canvas: match tone / stage derivation / HTML builders         */
/* ------------------------------------------------------------------ */

export const ALIGN_STAGE_PERCENT = {
  queued: 5,
  running: 10,
  diagnose: 20,
  jd_profile: 40,
  jd_analysis: 45,
  gap_analysis: 60,
  tailoring: 85,
  evaluation: 95,
  succeeded: 100,
};

export const STAGE_STEPS = [
  { key: "crawl", label: "抓取" },
  { key: "classify", label: "分类" },
  { key: "profile", label: "JD 画像" },
  { key: "gap", label: "差距" },
  { key: "align", label: "对齐" },
];

export const PROVENANCE_LABELS = {
  verified: "来源已验证",
  ambiguous: "来源待核对",
  missing: "缺少来源",
  pending_review: "待人工复核",
};

/* Shared stage labels (also re-exported by events.js for progress bars). */
export const STAGE_LABELS = {
  queued: "排队中",
  running: "运行中",
  diagnose: "诊断简历",
  jd_profile: "提取JD画像",
  jd_analysis: "提取JD画像与差距分析",
  gap_analysis: "差距分析",
  tailoring: "AI 改写简历",
  evaluation: "LLM 评估",
};

export function matchTone(score) {
  if (score == null) return "";
  if (score >= 80) return "match--high";
  if (score >= 60) return "match--mid";
  return "match--low";
}

export function alignProgressPercent(stage) {
  const key = String(stage || "");
  if (ALIGN_STAGE_PERCENT[key] != null) return ALIGN_STAGE_PERCENT[key];
  return key ? 55 : 8;
}

export function jdProfileSummary(profile) {
  if (!profile) return null;
  const title =
    profile.job_title || profile.title || profile.job_function || "目标岗位";
  const seniority = profile.seniority || profile.experience_level || "";
  const education = profile.education_requirements || [];
  const summary = profile.summary || profile.business_scene || "";
  return { title, seniority, education, summary };
}

export function stageProgress(session) {
  const crawl = (session && session.crawl) || {};
  const jd = (session && session.jd) || {};
  const gap = (session && session.gap) || {};
  const alignment = (session && session.alignment) || {};
  const done = new Set();
  if (crawl.status === "succeeded" || crawl.status === "idle") done.add("crawl");
  if (jd.status === "ready") done.add("classify");
  if (jd.status === "ready") done.add("profile");
  if (gap.status === "ready" || gap.status === "blocked") done.add("gap");
  if (alignment.status === "succeeded") done.add("align");
  return STAGE_STEPS.map((step) => ({
    ...step,
    active:
      !done.has(step.key) &&
      ((step.key === "crawl" && ["queued", "fetching", "parsing", "classifying"].includes(crawl.status)) ||
        (step.key === "classify" && jd.status === "queued") ||
        (step.key === "profile" && jd.status === "queued") ||
        (step.key === "gap" && gap.status === "queued")),
    done: done.has(step.key),
  }));
}

export function renderSkills(profile) {
  const required = profile.required_skills || profile.must_have_skills || [];
  const nice = profile.nice_to_have || profile.nice_to_have_skills || [];
  return `
    <div class="jd-skill-block">
      <div class="split-section-title">硬技能</div>
      <div class="chips">${required.length ? required.map((skill) => `<span class="chip chip--required">${esc(skill)}</span>`).join("") : `<span class="small muted">暂无提取结果</span>`}</div>
      ${nice.length ? `<div class="split-section-title split-section-title--soft">加分技能</div><div class="chips">${nice.map((skill) => `<span class="chip">${esc(skill)}</span>`).join("")}</div>` : ""}
    </div>`;
}

export function renderGap(gap) {
  if (!gap) return null;
  const missing = gap.missing_keywords || [];
  const strengths = gap.strength_matches || [];
  const misaligned = gap.misaligned_emphasis || [];
  const blocks = [];
  if (missing.length) {
    blocks.push(`
      <div class="gap-group gap-group--missing">
        <div class="split-section-title">差距项</div>
        <div class="gap-tags">${missing.map((item) => `<span class="gap-tag">${esc(item)}</span>`).join("")}</div>
      </div>`);
  }
  if (strengths.length) {
    blocks.push(`
      <div class="gap-group gap-group--strength">
        <div class="split-section-title">已有匹配</div>
        <div class="gap-tags">${strengths.map((item) => `<span class="gap-tag gap-tag--ok">${esc(item)}</span>`).join("")}</div>
      </div>`);
  }
  if (misaligned.length) {
    blocks.push(`
      <div class="gap-group gap-group--warn">
        <div class="split-section-title">错位强调</div>
        <div class="gap-tags">${misaligned.map((item) => `<span class="gap-tag gap-tag--warn">${esc(item)}</span>`).join("")}</div>
      </div>`);
  }
  if (!blocks.length) {
    blocks.push(`<div class="small muted">尚未生成差距报告</div>`);
  }
  return blocks.join("");
}

export function radarHtml(score) {
  const value = Math.max(0, Math.min(100, Number(score) || 0));
  const dims = [
    { label: "硬技能", weight: value },
    { label: "经验", weight: Math.max(20, Math.min(100, value * 0.9 + 10)) },
    { label: "场景", weight: Math.max(20, Math.min(100, value * 0.85 + 15)) },
    { label: "表达", weight: Math.max(20, Math.min(100, value * 0.8 + 20)) },
  ];
  const cx = 100;
  const cy = 100;
  const radius = 72;
  const points = dims.map((dim, index) => {
    const angle = -Math.PI / 2 + (index * 2 * Math.PI) / dims.length;
    return {
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
    };
  });
  const polygon = points
    .map((point, index) => {
      const weight = (dims[index].weight || 0) / 100;
      const x = cx + (point.x - cx) * weight;
      const y = cy + (point.y - cy) * weight;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const grid = [0.33, 0.66, 1]
    .map((scale) =>
      points
        .map((point) => {
          const x = cx + (point.x - cx) * scale;
          const y = cy + (point.y - cy) * scale;
          return `${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .join(" "),
    )
    .map(
      (points) =>
        `<polygon class="radar-grid" points="${points}" fill="none"></polygon>`,
    )
    .join("");
  return `
    <div class="split-radar" data-match-radar>
      <svg viewBox="0 0 200 200" role="img" aria-label="岗位匹配雷达">
        ${grid}
        ${points
          .map(
            (point, index) =>
              `<line class="radar-axis-line" x1="${cx}" y1="${cy}" x2="${point.x}" y2="${point.y}"></line>`,
          )
          .join("")}
        <polygon class="radar-fill" points="${polygon}"></polygon>
        ${points
          .map(
            (point, index) =>
              `<circle class="radar-dot" cx="${cx + (point.x - cx) * ((dims[index].weight || 0) / 100)}" cy="${cy + (point.y - cy) * ((dims[index].weight || 0) / 100)}" r="3"></circle>`,
          )
          .join("")}
      </svg>
      <div class="split-radar__score"><strong>${Math.round(value)}</strong><span>/100</span></div>
      <div class="split-radar__legend">${dims.map((dim) => `<span>${esc(dim.label)}</span>`).join("")}</div>
    </div>`;
}

export function stageStepper(session) {
  const steps = stageProgress(session);
  return `
    <div class="split-stepper" data-split-stepper>
      ${steps
        .map(
          (step) => `
        <div class="split-step ${step.done ? "is-done" : ""} ${step.active ? "is-active" : ""}">
          <span class="split-step__dot" aria-hidden="true"></span>
          <span class="split-step__label">${esc(step.label)}</span>
        </div>`,
        )
        .join("")}
    </div>`;
}

export function crawlStatusLine(session) {
  const crawl = (session && session.crawl) || {};
  const status = crawl.status || "idle";
  if (status === "idle") return "";
  const map = {
    queued: "排队抓取中...",
    fetching: "正在抓取岗位页面...",
    parsing: "正在解析岗位内容...",
    classifying: "正在分类岗位...",
    succeeded: "岗位抓取完成",
    failed: "抓取失败",
  };
  const message = crawl.error ? esc(crawl.error) : "";
  return `
    <div class="crawl-status crawl-status--${esc(status)}" data-crawl-status>
      <span class="crawl-status__dot" aria-hidden="true"></span>
      <span>${map[status] || status}${message ? `：${message}` : ""}</span>
    </div>`;
}

export function diffCard(diff, index, jobId) {
  const diffId = diff.diff_id || `diff-${index}`;
  const type = diff.type || "modify";
  const provenance = diff.provenance || diff.provenance_quote || "";
  const stateKey = diff.provenance_state || "pending_review";
  const label = PROVENANCE_LABELS[stateKey] || "来源待核对";
  const invalid = type === "add" && !String(provenance || "").trim();
  const typeLabel = { modify: "改写", add: "新增", remove: "删除" }[type] || "改写";
  const originalText = diff.original || "";
  const proposedText = diff.proposed || "";
  /* #17: modify diffs get character-level marks inside the card's 原文/优化
   * blocks (diff-char-del on the original side, diff-char-ins on the
   * proposed side); add/remove diffs have no counterpart so they stay plain.
   * Card-level interactions (采纳/忽略/润色) are untouched. */
  const originalHtml =
    type === "modify" && proposedText
      ? renderInlineDiffSide(originalText, proposedText, "original")
      : esc(originalText);
  const proposedHtml =
    type === "modify" && originalText
      ? renderInlineDiffSide(originalText, proposedText, "proposed")
      : esc(proposedText);
  return `
    <article class="diff-card ${invalid ? "diff-card--invalid" : ""}" data-diff-id="${esc(diffId)}" data-diff-index="${index}">
      <div class="diff-card__head">
        <div class="diff-card__type">
          <span class="badge ${invalid ? "badge-amber" : "badge-blue"}">${esc(typeLabel)}</span>
          ${diffSectionBadge(diff)}
          <span class="small muted">${diff.confidence ? `置信度 ${esc(diff.confidence)}` : ""}</span>
        </div>
        <div class="provenance-badge provenance-badge--${esc(stateKey)}" data-provenance title="${esc(provenance)}">${esc(label)}</div>
      </div>
      <div class="diff-card__columns">
        <div class="diff-card__col diff-card__col--original">
          <div class="split-section-title">原文</div>
          <div class="diff-card__text" data-diff-original>${originalHtml}</div>
        </div>
        <div class="diff-card__col diff-card__col--proposed">
          <div class="split-section-title">优化</div>
          <div class="diff-card__text" data-diff-proposed>${proposedHtml}</div>
        </div>
      </div>
      ${diff.reason ? `<div class="diff-card__reason" data-diff-reason>${esc(diff.reason)}</div>` : ""}
      ${provenance ? `<div class="provenance-quote">${esc(provenance)}</div>` : ""}
      ${invalid ? `<div class="diff-card__warning" role="alert">该条为无来源新增，已作为硬门禁拦截，不可直接采纳。</div>` : ""}
      <div class="diff-card__actions" data-diff-actions>
        ${invalid ? "" : `<button class="btn btn-primary btn-sm" data-action="accept-bullet" data-id="${esc(jobId)}" data-diff-id="${esc(diffId)}">采纳</button>`}
        <button class="btn btn-ghost btn-sm" data-action="reject-bullet" data-id="${esc(jobId)}" data-diff-id="${esc(diffId)}">忽略</button>
        <button class="btn btn-secondary btn-sm" data-action="polish-bullet" data-id="${esc(jobId)}" data-diff-id="${esc(diffId)}" data-instruction="quantified">AI 润色</button>
      </div>
    </article>`;
}

export function diffList(session, jobId) {
  const alignment = (session && session.alignment) || {};
  const diffs = alignment.diffs || [];
  const invalid = alignment.invalid_diffs || [];
  const cards = [...diffs, ...invalid]
    .map((diff, index) => diffCard(diff, index, jobId))
    .join("");
  if (!cards) {
    return `
      <div class="resume-empty" data-resume-canvas-empty>
        <div class="resume-empty__title">还没有对齐结果</div>
        <ol class="resume-empty__steps">
          <li>在左侧「对齐调优」选择主简历</li>
          <li>点击右侧顶部「重新生成对齐」</li>
          <li>逐条采纳建议并保存定稿</li>
        </ol>
        <button class="btn btn-primary btn-sm" type="button" data-action="run-alignment">开始对齐</button>
      </div>`;
  }
  return `<div class="diff-card-list" data-diff-list>${cards}</div>`;
}

export function alignmentControls(session, resumes, jobId) {
  const alignment = (session && session.alignment) || {};
  const selected = session && session.resume && session.resume.selected_resume_id;
  const optionsHtml = resumes
    .map(
      (resume) =>
        `<option value="${esc(resume.resume_id)}" ${resume.resume_id === selected ? "selected" : ""}>${esc(resume.title)}（v${resume.current_version}）</option>`,
    )
    .join("");
  const running = alignment.status === "running" || alignment.status === "queued";
  const failed = alignment.status === "failed";
  return `
    <form class="align-form" data-form="split-align">
      <input type="hidden" name="job_id" value="${esc(jobId)}">
      <div class="align-form__row">
        <label class="field" style="flex:1;min-width:0">
          <span class="small">主简历</span>
          <select name="master_resume_id" required>
            <option value="">${resumes.length ? "选择简历..." : "请先到简历中心创建主简历"}</option>
            ${optionsHtml}
          </select>
        </label>
        <label class="field">
          <span class="small">粒度</span>
          <select name="granularity">
            <option value="fine">微调</option>
            <option value="medium" selected>重构</option>
            <option value="coarse">重塑</option>
          </select>
        </label>
        <label class="field">
          <span class="small">聚焦</span>
          <select name="prompt_focus">
            <option value="balanced" selected>均衡</option>
            <option value="quantified">量化数据</option>
            <option value="skills">技能匹配</option>
          </select>
        </label>
      </div>
      <div class="align-form__row">
        <button class="btn btn-primary" type="submit" data-align-run ${running ? "disabled" : ""}>${running ? "对齐运行中..." : failed ? "重新运行对齐" : "一键生成对齐简历"}</button>
        <button class="btn btn-outline btn-sm" type="button" data-action="cancel-align-job" ${running ? "" : "hidden"}>取消任务</button>
        <button class="btn btn-ghost btn-sm" type="button" data-action="apply-accepted-bullets" data-id="${esc(jobId)}" ${!alignment.draft ? "disabled" : ""}>应用已采纳</button>
        <span class="small muted" data-align-status>${alignment.status === "succeeded" ? "已生成对齐版本" : alignment.status === "failed" ? `任务失败：${esc(alignment.error || "请重试")}` : alignment.status === "running" || alignment.status === "queued" ? "正在生成..." : ""}</span>
      </div>
      <label class="eval-option">
        <input type="checkbox" name="run_eval">
        <span>本次运行评估（幻觉检测 / JD 匹配分）</span>
      </label>
      <div class="small muted" style="margin:-4px 0 6px">每任务额外一次 LLM 调用；不勾选则按设置页默认执行。</div>
      ${running ? `
      <div class="align-progress" data-align-progress role="status" aria-live="polite">
        <div class="align-progress__track"><div class="align-progress__fill" style="width:${alignProgressPercent(alignment.stage)}%"></div></div>
        <div class="align-progress__meta">
          <span data-align-stage>${esc(STAGE_LABELS[alignment.stage] || alignment.stage || "正在生成")}</span>
          <span class="small muted" data-align-elapsed></span>
        </div>
      </div>` : ""}
    </form>`;
}

export function exportDock(jobId, session) {
  const alignment = (session && session.alignment) || {};
  return `
    <details class="export-dock" data-export-dock>
      <summary class="btn btn-secondary btn-sm export-dock__trigger">导出 ▾</summary>
      <div class="export-dock__menu">
        <button class="btn btn-secondary btn-sm" type="button" data-action="copy-align-markdown" data-id="${esc(jobId)}">复制 Markdown</button>
        <button class="btn btn-secondary btn-sm" type="button" data-action="export-align-markdown" data-id="${esc(jobId)}">下载 Markdown</button>
        <button class="btn btn-secondary btn-sm" type="button" data-action="export-align-pdf" data-id="${esc(jobId)}">导出 PDF</button>
        <button class="btn btn-outline btn-sm" type="button" data-action="export-align-json" data-id="${esc(jobId)}">导出 JSON</button>
        ${alignment.draft ? `<span class="badge badge-green">已生成</span>` : ""}
      </div>
    </details>`;
}

function boardMoreMenu(job) {
  const id = esc(job.job_id);
  return `
    <details class="board-more" aria-label="更多操作">
      <summary class="board-more__trigger" aria-label="更多操作" title="更多操作">···</summary>
      <div class="board-more__menu">
        <button class="btn btn-ghost btn-sm" type="button" data-action="open-job-timeline" data-id="${id}">详情</button>
        <button class="btn btn-ghost btn-sm" type="button" data-action="edit-job" data-id="${id}">编辑</button>
        <button class="btn btn-danger btn-sm" type="button" data-action="delete-job" data-id="${id}">删除</button>
      </div>
    </details>`;
}

export function boardCard(job) {
  const canonical = canonicalJobStatus(job.status);
  const optionsHtml = JOB_STATUS_CANONICAL.map(
    (value) =>
      `<option value="${value}" ${canonical === value ? "selected" : ""}>${esc(JOB_STATUS_LABELS[value])}</option>`,
  ).join("");
  const match = job.match_score != null ? Math.round(job.match_score) : null;
  /* #F10: job.match_score persists the last workbench eval result, so the
   * badge title discloses the score origin instead of a bare "匹配度". */
  const matchTitle = match != null ? "匹配度 · 来自对齐评估" : "尚未分析";
  return `
    <article class="board-card copilot-card ${job.classification_pending ? "board-card--pending" : ""}" data-job-id="${job.job_id}" draggable="true" data-board-drag>
      <div class="board-card__top">
        <label class="board-check"><input type="checkbox" data-board-check value="${job.job_id}" aria-label="选择 ${esc(job.title)}"><span></span></label>
        ${match != null ? `<span class="match-badge ${matchTone(match)}" title="${matchTitle}">${match}</span>` : `<span class="match-badge match-badge--empty" title="${matchTitle}">待分析</span>`}
        <button type="button" class="board-card__title" data-action="open-optimizer" data-id="${job.job_id}">${esc(job.title)}</button>
        ${boardMoreMenu(job)}
      </div>
      <div class="board-card__meta">${esc(job.company || "未知公司")} · ${esc(job.location || "未知城市")} · ${formatSalary(job)}</div>
      <div class="board-card__tags">
        <span class="badge badge-blue">${esc(job.job_function || "未分类")}</span>
        <span class="badge badge-gray">${esc(job.seniority || "未知")}</span>
        ${jobCompletenessBadge(job)}
        ${job.classification_pending ? `<button type="button" class="badge badge-amber badge-pending" data-action="reclassify-job" data-id="${esc(job.job_id)}" aria-label="重新分类">分类待定</button>` : ""}
        ${job.alignment_status === "succeeded" ? '<span class="badge badge-green">已对齐</span>' : ""}
      </div>
      <div class="board-card__timeline">
        ${job.final_draft_version ? `<span class="badge badge-green">已定稿 v${job.final_draft_version}</span>` : ""}
        ${job.applied_at ? `<span class="small muted">投递 ${esc(job.applied_at)}</span>` : ""}
        ${job.next_step ? `<span class="small muted">下一步：${esc(job.next_step)}</span>` : ""}
      </div>
      ${jobSourceUrl(job) ? `<div class="board-card__links">${jobApplyLinkHtml(job)}</div>` : ""}
      <div class="row" style="margin-top:8px">
        <select class="board-status-select" data-board-status data-id="${job.job_id}" aria-label="移动状态">${optionsHtml}</select>
        <button class="btn btn-ghost btn-sm board-card__primary" data-action="open-optimizer" data-id="${job.job_id}">工作台</button>
      </div>
    </article>`;
}

/* ------------------------------------------------------------------ */
/* Workbench board card (jobs view)                                    */
/* ------------------------------------------------------------------ */

export function renderBoardCard(job) {
  const canonical = canonicalJobStatus(job.status);
  const statusOptions = JOB_STATUS_CANONICAL.map(
    (value) =>
      `<option value="${value}" ${canonical === value ? "selected" : ""}>${esc(JOB_STATUS_LABELS[value])}</option>`,
  ).join("");
  const match = job.match_score != null ? Math.round(job.match_score) : null;
  const matchTitle = match != null ? "匹配度 · 来自对齐评估" : "尚未分析";
  return `
    <article class="board-card ${job.classification_pending ? "board-card--pending" : ""}" data-job-id="${job.job_id}">
      <div class="board-card__top">
        <label class="board-check"><input type="checkbox" data-board-check value="${job.job_id}" aria-label="选择 ${esc(job.title)}"><span></span></label>
        ${match != null ? `<span class="match-badge ${matchTone(match)}" title="${matchTitle}">${match}</span>` : `<span class="match-badge match-badge--empty" title="${matchTitle}">待分析</span>`}
        <button type="button" class="board-card__title" data-action="open-job-timeline" data-id="${job.job_id}">${esc(job.title)}</button>
        ${boardMoreMenu(job)}
      </div>
      <div class="board-card__meta">${esc(job.company || "未知公司")} · ${esc(job.location || "未知城市")} · ${formatSalary(job)}</div>
      <div class="board-card__tags">
        <span class="badge badge-blue">${esc(job.job_function || "未分类")}</span>
        <span class="badge badge-gray">${esc(job.seniority || "未知")}</span>
        ${jobCompletenessBadge(job)}
        ${job.classification_pending ? `<button type="button" class="badge badge-amber badge-pending" data-action="reclassify-job" data-id="${esc(job.job_id)}" aria-label="重新分类">分类待定</button>` : ""}
      </div>
      <div class="board-card__timeline">
        ${job.final_draft_version ? `<span class="badge badge-green">已定稿 v${job.final_draft_version}</span>` : ""}
        ${job.applied_at ? `<span class="small muted">投递 ${esc(job.applied_at)}</span>` : ""}
        ${job.next_step ? `<span class="small muted">下一步：${esc(job.next_step)}</span>` : ""}
      </div>
      ${jobSourceUrl(job) ? `<div class="board-card__links">${jobApplyLinkHtml(job)}</div>` : ""}
      <div class="row" style="margin-top:8px">
        <select class="board-status-select" data-board-status data-id="${job.job_id}" aria-label="移动状态">${statusOptions}</select>
        <button class="btn btn-ghost btn-sm board-card__primary" data-action="open-workspace" data-id="${job.job_id}">工作台</button>
      </div>
    </article>`;
}

/* ------------------------------------------------------------------ */
/* Batch alignment panel + result matrix                               */
/* ------------------------------------------------------------------ */

export function batchPanelHtml(jobs, resumes) {
  const jobOptions = jobs
    .map(
      (job) =>
        `<label class="batch-job-option"><input type="checkbox" name="job_ids" value="${esc(job.job_id)}" data-batch-check> <span>${esc(job.title)} · ${esc(job.company || "")}</span></label>`,
    )
    .join("");
  const resumeOptions = resumes
    .map(
      (resume) =>
        `<option value="${esc(resume.resume_id)}">${esc(resume.title)}（v${resume.current_version}）</option>`,
    )
    .join("");
  return `
    <form data-form="batch-align" data-batch-panel>
      <div class="form-grid">
        <div class="field"><label>主简历</label><select name="master_resume_id" required>
          <option value="">${resumes.length ? "选择简历..." : "先到简历中心创建主简历"}</option>${resumeOptions}</select></div>
        <div class="field"><label>对齐粒度</label><select name="granularity">
          <option value="fine">微调</option><option value="medium">重构</option><option value="coarse">重写</option>
        </select></div>
        <div class="field wide"><label>选择 2-5 个岗位</label>
          <div class="batch-job-list">${jobOptions || '<div class="muted small">岗位库为空</div>'}</div></div>
        <div class="field wide"><label>自定义补充要求（可选）</label>
          <textarea name="custom_prompt" rows="2" placeholder="例如：强调高并发缓存场景"></textarea></div>
      </div>
      <div class="row">
        <button class="btn btn-primary" type="submit">开始批量对齐</button>
        <button class="btn btn-danger" type="button" data-action="cancel-batch-align" data-batch-cancel hidden>取消排队</button>
        <span class="small muted" data-batch-status></span>
      </div>
      <div class="row" style="margin-top:8px">
        <button class="btn btn-ghost btn-sm" type="button" data-action="show-last-batch">查看最近一次批次</button>
        <span class="small muted">后端暂无批次列表接口，仅保留当前会话最近一次结果</span>
      </div>
      <div data-batch-results></div>
    </form>`;
}

export function renderBatchMatrixHtml(batch) {
  const rows = batch.rows || [];
  const hasSummary = rows.some((row) => row.summary);
  const batchStatusBadge = (row) => {
    const label = `${row.title || row.job_id}: ${row.status}`;
    if (row.status === "failed" || row.status === "canceled") {
      return `<span class="badge badge-red" data-batch-failed title="${esc(row.error || "模型响应异常，请检查 LLM 配置后重试")}">${esc(label)}</span>`;
    }
    return `<span class="badge badge-pending">${esc(label)}</span>`;
  };
  if (!hasSummary) {
    return `<div class="batch-progress">${rows.map(batchStatusBadge).join("")}</div>`;
  }
  const barColor = (score) =>
    score >= 75 ? "var(--success)" : score >= 55 ? "var(--warning)" : "var(--danger)";
  const bars = rows
    .filter((row) => row.summary && row.summary.score != null)
    .map((row) => {
      const score = Math.max(0, Math.min(100, Number(row.summary.score) || 0));
      const title = row.title || row.job_id || "未命名岗位";
      return `<div class="batch-bar" data-batch-bar style="display:grid;grid-template-columns:minmax(120px,1fr) minmax(120px,2fr) 40px;gap:10px;align-items:center">
        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(title)}">${esc(title)}${row.company ? `<span class="small muted"> · ${esc(row.company)}</span>` : ""}</span>
        <div style="background:var(--surface-2);border-radius:6px;height:10px;overflow:hidden" data-batch-bar-track>
          <div data-batch-bar-fill style="width:${score}%;height:100%;background:${barColor(score)};border-radius:6px;transition:width .4s ease"></div>
        </div>
        <span data-batch-bar-score style="text-align:right;font-variant-numeric:tabular-nums">${esc(score)}</span>
      </div>`;
    })
    .join("");
  const gapColumns = rows
    .map((row) => {
      const summary = row.summary || {};
      const gaps = (summary.key_gaps || []).slice(0, 5);
      const title = row.title || row.job_id || "未命名岗位";
      return `<div class="batch-gap-col" data-batch-gap-col>
        <div class="small" style="font-weight:600;margin-bottom:6px">${esc(title)}${row.company ? `<span class="small muted"> · ${esc(row.company)}</span>` : ""}</div>
        ${gaps.length ? `<div class="chips" style="display:flex;flex-wrap:wrap;gap:6px">${gaps.map((gap) => `<span class="gap-tag gap-tag--warn" data-batch-gap>${esc(gap)}</span>`).join("")}</div>` : `<span class="small muted">暂无缺口数据</span>`}
      </div>`;
    })
    .join("");
  const tableRows = rows
    .map((row) => {
      const summary = row.summary || {};
      const score = summary.score;
      const verdict =
        score == null ? "—" : score >= 75 ? "投递" : score >= 55 ? "考虑" : "放弃";
      const statusCell =
        row.status === "failed" || row.status === "canceled"
          ? `<span class="badge badge-red" data-batch-failed title="${esc(row.error || "模型响应异常，请检查 LLM 配置后重试")}">${esc(row.status)}</span>`
          : esc(summary.next_step || row.status);
      return `<tr>
        <td>${esc(row.title || row.job_id)}</td>
        <td>${esc(score ?? "—")}</td>
        <td>${esc((summary.key_gaps || []).slice(0, 3).join("、") || "—")}</td>
        <td>${esc(verdict)}</td>
        <td>${statusCell}</td>
        <td><a class="btn btn-ghost btn-sm" href="#/workspace/${encodeURIComponent(row.job_id)}">打开工作台</a></td>
      </tr>`;
    })
    .join("");
  return `<div class="split-section-title">匹配分对比</div>
    <div class="batch-bars" data-batch-bars>${bars || '<div class="small muted">暂无已完成岗位</div>'}</div>
    <div class="split-section-title" style="margin-top:12px">关键缺口对比</div>
    <div class="batch-gaps" data-batch-gaps style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px">${gapColumns}</div>
    <div class="row" style="margin-top:12px">
      <button class="btn btn-outline btn-sm" type="button" data-action="export-batch-csv">导出对比 CSV</button>
    </div>
    <div class="table-wrap"><table class="data batch-matrix">
      <thead><tr><th>岗位</th><th>分数</th><th>关键缺口</th><th>结论</th><th>下一步</th><th>操作</th></tr></thead>
      <tbody>${tableRows}</tbody></table></div>`;
}

/* Line-level + character-level side-by-side compare grid (原版 | 优化版).
 *
 * Shared by the live canvas 并排对比 modal (#17): line-level semantics are
 * kept (diff-remove / diff-add for whole-line changes); modified lines use
 * diff-modify and additionally mark the changed characters inline
 * (diff-char-del / diff-char-ins). Every line is addressable via data-line
 * (0-based) + a visible 1-based .cmp-line-num. */
export function buildCmpSideHtml(originalText, optimizedText, diffs) {
  const diffRows = lineDiff(originalText, optimizedText);
  const removedLines = new Set(
    diffRows
      .filter((row) => row.type === "remove")
      .map((row) => row.text.trim()),
  );
  const addedLines = new Set(
    diffRows
      .filter((row) => row.type === "add")
      .map((row) => row.text.trim()),
  );
  const modifyOriginal = new Set();
  const modifyProposed = new Set();
  /* Trimmed modify pairs so modified lines can carry character-level
   * marks: trimmed original -> proposed text, and the reverse. */
  const modifyPairOriginal = new Map();
  const modifyPairProposed = new Map();
  (diffs || []).forEach((diff) => {
    const orig = String(diff.original || "").trim();
    const prop = String(diff.proposed || "").trim();
    if (diff.type === "modify") {
      if (orig) modifyOriginal.add(orig);
      if (prop) modifyProposed.add(prop);
      if (orig && prop) {
        modifyPairOriginal.set(orig, prop);
        modifyPairProposed.set(prop, orig);
      }
    }
  });
  const originalHtml =
    String(originalText)
      .split("\n")
      .map((line, index) => {
        const trimmed = line.trim();
        if (modifyOriginal.has(trimmed)) {
          const proposed = modifyPairOriginal.get(trimmed);
          const content = proposed
            ? renderInlineDiffSide(line, proposed, "original")
            : esc(line);
          return cmpLineHtml(index, "diff-modify", "", content);
        }
        if (removedLines.has(trimmed)) {
          return cmpLineHtml(index, "diff-remove", "−", esc(line));
        }
        return cmpLineHtml(index, "", "", esc(line));
      })
      .join("") || '<div class="muted small">原版内容不可用</div>';
  const optimizedHtml =
    String(optimizedText)
      .split("\n")
      .map((line, index) => {
        const trimmed = line.trim();
        if (!trimmed) return cmpLineHtml(index, "", "", "&nbsp;");
        if (modifyProposed.has(trimmed)) {
          const original = modifyPairProposed.get(trimmed);
          const content = original
            ? renderInlineDiffSide(original, line, "proposed")
            : esc(line);
          return cmpLineHtml(index, "diff-modify", "", content);
        }
        if (addedLines.has(trimmed)) {
          return cmpLineHtml(index, "diff-add", "＋", esc(line));
        }
        return cmpLineHtml(index, "", "", esc(line));
      })
      .join("") || '<div class="muted small">暂无优化内容</div>';
  return `
    <div class="cmp-grid cmp-grid--workbench">
      <section class="cmp-column-wrap"><h4>原版</h4><div class="cmp-column motion-stagger">${originalHtml}</div></section>
      <section class="cmp-column-wrap"><h4>优化版</h4><div class="cmp-column motion-stagger">${optimizedHtml}</div></section>
    </div>`;
}

/* ------------------------------------------------------------------ */
/* Command panel: URL detection / preview HTML                         */
/* ------------------------------------------------------------------ */

const URL_RE = /^https?:\/\/[^\s]+$/i;

export function isJdUrl(value) {
  return URL_RE.test(String(value || "").trim());
}

export function previewFor(value) {
  const trimmed = String(value || "").trim();
  if (!trimmed) {
    return `<div class="command-preview command-preview--hint">粘贴 JD 文本或输入 JD 链接，确认后自动建库并预分析。</div>`;
  }
  if (isJdUrl(trimmed)) {
    return `
      <div class="command-preview command-preview--url">
        <div class="command-preview__head">
          <span class="badge badge-blue">JD 链接</span>
          <span class="small muted">将抓取岗位内容并自动入库存档</span>
        </div>
        <div class="command-preview__line">${esc(trimmed)}</div>
      </div>`;
  }
  const lines = trimmed.split(/\r?\n/).filter(Boolean);
  const previewLines = lines.slice(0, 5);
  return `
    <div class="command-preview command-preview--text">
      <div class="command-preview__head">
        <span class="badge badge-teal">JD 文本</span>
        <span class="small muted">${trimmed.length} 字符 · ${lines.length} 行</span>
      </div>
      <div class="command-preview__body">${previewLines.map((line) => `<div>${esc(line)}</div>`).join("")}${lines.length > 5 ? `<div class="small muted">… 其余 ${lines.length - 5} 行</div>` : ""}</div>
    </div>`;
}

/* ------------------------------------------------------------------ */
/* JD parse form filling + error HTML (DOM-tested)                     */
/* ------------------------------------------------------------------ */

/**
 * Fill the job-create form fields from a parse-jd response, only where
 * the user has not typed anything yet. Returns a per-field summary of
 * what was filled.
 */
export function applyJdParseResult(form, parsed) {
  const summary = {};
  const field = (name) => form.querySelector(`[name="${name}"]`);
  const fillText = (name, value) => {
    const input = field(name);
    const ok = Boolean(
      input &&
        !(input.value || "").trim() &&
        value != null &&
        String(value).trim() !== "",
    );
    if (ok) input.value = value;
    summary[name] = ok;
    return ok;
  };
  fillText("title", parsed.title);
  fillText("jd_text", parsed.jd_text);
  fillText("company", parsed.company);
  fillText("location", parsed.city);
  fillText("source_url", parsed.source_url);

  const min = field("salary_min");
  const fillMin = Boolean(min && min.value === "" && parsed.salary_min != null);
  if (fillMin) min.value = parsed.salary_min;
  summary.salary_min = fillMin;

  const max = field("salary_max");
  const fillMax = Boolean(max && max.value === "" && parsed.salary_max != null);
  if (fillMax) max.value = parsed.salary_max;
  summary.salary_max = fillMax;

  const cur = field("salary_currency");
  const fillCur = Boolean(
    cur && !(cur.value || "").trim() && parsed.salary_currency,
  );
  if (fillCur) cur.value = parsed.salary_currency;
  summary.salary_currency = fillCur;

  return summary;
}

/** Error state HTML for the JD parse status area. */
export function jdParseErrorHtml(detail) {
  const reason =
    detail && detail.reason ? detail.reason : "未能从该链接提取岗位内容";
  const action =
    detail && detail.action ? detail.action : "可改用粘贴 JD 或稍后重试";
  return `
    <div class="jd-parse-error-text"><strong>解析失败</strong>：${esc(reason)}，${esc(action)}</div>
    <div class="row">
      <button class="btn btn-secondary btn-sm" type="button" data-action="use-paste-mode">改用粘贴 JD</button>
      <button class="btn btn-ghost btn-sm" type="button" data-action="retry-parse-jd">重新解析</button>
    </div>`;
}

/** Apply the JD parse failure state to the status area element. */
export function applyJdParseError(status, detail) {
  status.className = "jd-parse-status form-error";
  status.setAttribute("role", "alert");
  status.innerHTML = jdParseErrorHtml(detail);
}

/* ------------------------------------------------------------------ */
/* Job library stats + CSV export + whole-library backup (DOM-tested)  */
/* ------------------------------------------------------------------ */

/* Funnel semantics (documented for the acceptance tests):
 * - total      = every library job
 * - 投递/总数  = jobs that reached submission (applied + interview + offer) / total
 * - 面试/投递  = jobs that reached interview (interview + offer) / submission count
 * - Offer/面试 = jobs that reached offer (offer) / interview count
 * Stages are derived from historical peak evidence (ADR-0027): offer_at,
 * then applied_at, then the current canonical status. A withdrawn job with
 * applied_at or offer_at keeps its historical funnel segment; the five-state
 * counts still show the current status. Any zero denominator yields null,
 * which the UI renders as "—". */
export function funnelPercent(numerator, denominator) {
  const bottom = Number(denominator);
  if (!Number.isFinite(bottom) || bottom <= 0) return null;
  return Math.round((Number(numerator) / bottom) * 100);
}

export function jobFunnelStage(job) {
  if (!job || typeof job !== "object") return "";
  const stages = ["draft", "applied", "interview", "offer"];
  let peak = stages.indexOf(canonicalJobStatus(job.status));
  if (peak < 0) peak = 0;
  if (job.applied_at) peak = Math.max(peak, 1);
  if (job.offer_at) peak = Math.max(peak, 3);
  return stages[peak] || "";
}

export function computeJobStats(jobs) {
  const list = Array.isArray(jobs) ? jobs : [];
  const counts = { draft: 0, applied: 0, interview: 0, offer: 0, withdrawn: 0 };
  for (const job of list) {
    const key = canonicalJobStatus(job.status);
    if (key in counts) counts[key] += 1;
  }
  const peak = { applied: 0, interview: 0, offer: 0 };
  for (const job of list) {
    const stage = jobFunnelStage(job);
    if (stage === "offer") peak.offer += 1;
    if (stage === "interview" || stage === "offer") peak.interview += 1;
    if (stage === "applied" || stage === "interview" || stage === "offer") {
      peak.applied += 1;
    }
  }
  const applied = peak.applied;
  const interview = peak.interview;
  const offer = peak.offer;
  const total = list.length;
  return {
    total,
    counts,
    funnel: {
      applied,
      interview,
      offer,
      applyRate: funnelPercent(applied, total),
      interviewRate: funnelPercent(interview, applied),
      offerRate: funnelPercent(offer, interview),
    },
  };
}

export function renderJobStatsHtml(stats) {
  const data = stats || computeJobStats([]);
  const counts = data.counts || {};
  const funnel = data.funnel || {};
  const percent = (value) => (value == null ? "—" : `${value}%`);
  const dot = (key) =>
    `<span class="board-dot board-dot--${key}" aria-hidden="true"></span>`;
  const countChips = JOB_STATUS_CANONICAL.map(
    (key) =>
      `<span class="badge board-stats-chip">${dot(key)}${esc(JOB_STATUS_LABELS[key])}<strong data-stat-count="${key}">${counts[key] ?? 0}</strong></span>`,
  ).join("");
  /* Sprint 4 T2: 漏斗三段复用 S1 Dashboard KPI 视觉语言 —— 语义色顶条 +
   * 圆角卡（info/warning/success），与 dashboard-kpi 卡贯通。 */
  const funnelCards = [
    { key: "applyRate", label: "添加→投递", tone: "info", hint: "已投递及以上阶段 ÷ 岗位总数" },
    { key: "interviewRate", label: "投递→面试", tone: "warning", hint: "进入面试及以上阶段 ÷ 已投递" },
    { key: "offerRate", label: "面试→Offer", tone: "success", hint: "拿到 Offer ÷ 进入面试" },
  ]
    .map(
      (card) => `
        <div class="board-stats-card board-stats-card--${card.tone}" title="${esc(card.hint)}">
          <span class="board-stats-card__label">${card.label}</span>
          <strong class="board-stats-card__rate" data-stat-rate="${card.key}">${percent(funnel[card.key])}</strong>
        </div>`,
    )
    .join("");
  return `
    <div class="board-stats" data-board-stats role="group" aria-label="求职漏斗统计">
      <div class="board-stats__counts" data-board-stats-counts>${countChips}</div>
      <span class="board-stats__divider" aria-hidden="true"></span>
      <div class="board-stats__funnel" data-board-stats-funnel>
        <span class="small muted board-stats__label">转化</span>
        ${funnelCards}
      </div>
    </div>`;
}

/* CSV export helpers (RFC 4180-ish: quote fields containing , " CR or LF;
 * embedded quotes are doubled). Output carries a UTF-8 BOM so Excel opens
 * the Chinese columns correctly. */

export function csvEscape(value) {
  const text = value == null ? "" : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export const JOB_CSV_HEADERS = ["岗位", "公司", "城市", "薪资", "状态", "匹配分", "定稿版本"];

export function jobsToCsv(jobs) {
  const rows = (Array.isArray(jobs) ? jobs : []).map((job) => [
    job.title || "",
    job.company || "",
    job.location || "",
    formatSalary(job),
    jobStatusLabel(job.status),
    job.match_score != null ? String(Math.round(job.match_score)) : "",
    job.final_draft_version != null ? String(job.final_draft_version) : "",
  ]);
  const lines = [JOB_CSV_HEADERS, ...rows].map((row) => row.map(csvEscape).join(","));
  return `\uFEFF${lines.join("\r\n")}`;
}

export const BATCH_CSV_HEADERS = ["岗位", "公司", "匹配分", "关键缺口", "结论", "下一步"];

export function batchRowsToCsv(batch) {
  const rows = ((batch && batch.rows) || []).map((row) => {
    const summary = row.summary || {};
    const score = summary.score;
    const verdict =
      score == null ? "" : score >= 75 ? "投递" : score >= 55 ? "考虑" : "放弃";
    return [
      row.title || row.job_id || "",
      row.company || "",
      score != null ? String(score) : "",
      (summary.key_gaps || []).join("；"),
      verdict,
      summary.next_step || row.status || "",
    ];
  });
  const lines = [BATCH_CSV_HEADERS, ...rows].map((row) => row.map(csvEscape).join(","));
  return `\uFEFF${lines.join("\r\n")}`;
}

/* Whole-library JSON backup: the payload embeds machine-usable restore
 * steps so the file itself documents how to recover (script steps below
 * mirror the real POST /api/jobs/import contract). */

export const BACKUP_RESTORE_STEPS = [
  "1. 备份：岗位库 →「整库备份 JSON」下载全部岗位；「导出 CSV」可作明细备份。",
  "2. 还原 JSON：调用 POST /api/jobs/import，body 为 {\"jobs\": <备份中的 jobs 数组>}，重复岗位自动跳过。PowerShell 示例：",
  "   $body = Get-Content resualign-jobs-backup.json -Raw | ConvertFrom-Json;",
  "   $payload = @{ jobs = $body.jobs } | ConvertTo-Json -Depth 8;",
  "   Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/jobs/import -ContentType 'application/json' -Body $payload",
  "3. 还原 CSV：岗位库 →「批量导入」粘贴导出的 CSV 内容（列顺序：岗位,公司,城市,薪资,状态,匹配分,定稿版本）。",
  "4. 还原只重建岗位基础字段；匹配分/定稿版本等派生字段不会自动重算，可在工作台对关键岗位重新运行预分析。",
];

export function backupRestoreGuide() {
  return ["# 整库备份与还原", "", ...BACKUP_RESTORE_STEPS].join("\n");
}

export function buildJobsBackup(jobs) {
  const list = Array.isArray(jobs) ? jobs : [];
  return {
    app: "ResuAlign-Lite",
    type: "jobs-backup",
    version: 1,
    exported_at: new Date().toISOString(),
    count: list.length,
    restore_steps: [...BACKUP_RESTORE_STEPS],
    jobs: list,
  };
}

/* ------------------------------------------------------------------ */
/* Inline (token/character-level) diff                                 */
/* ------------------------------------------------------------------ */

/* Tokenization for inline diffs: each CJK character is its own token,
 * ASCII runs (words/numbers/underscores) stay one token, whitespace runs
 * and any other single character are tokens too. This keeps the LCS
 * table small while still highlighting single-character edits in Chinese
 * resumes (e.g. "负责系统开发" -> "负责高并发系统开发" marks 高并发). */
const INLINE_TOKEN_RE = /[\u4e00-\u9fff]|[A-Za-z0-9_]+|\s+|./g;

export function tokenizeInline(text) {
  return String(text ?? "").match(INLINE_TOKEN_RE) || [];
}

/* Longest common subsequence over inline tokens. Returns aligned
 * segments: { type: "same" | "del" | "ins", text } where "del" tokens
 * exist only in the original and "ins" only in the proposed. Consecutive
 * segments of the same type are merged so callers get one span per
 * changed word. Identical inputs yield a single "same" segment. */
export function inlineDiff(original, proposed) {
  const a = tokenizeInline(original);
  const b = tokenizeInline(proposed);
  const m = a.length;
  const n = b.length;
  const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[i][j] =
        a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const segments = [];
  let i = 0;
  let j = 0;
  while (i < m && j < n) {
    if (a[i] === b[j]) {
      segments.push({ type: "same", text: a[i] });
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      segments.push({ type: "del", text: a[i] });
      i += 1;
    } else {
      segments.push({ type: "ins", text: b[j] });
      j += 1;
    }
  }
  while (i < m) segments.push({ type: "del", text: a[i++] });
  while (j < n) segments.push({ type: "ins", text: b[j++] });
  const merged = [];
  for (const segment of segments) {
    const last = merged[merged.length - 1];
    if (last && last.type === segment.type) last.text += segment.text;
    else merged.push({ type: segment.type, text: segment.text });
  }
  return merged;
}

/* Render one side of an inline diff as escaped HTML:
 * - side "original" keeps same + del segments (the deleted characters),
 * - side "proposed" keeps same + ins segments (the inserted characters).
 * Unchanged text stays plain, so only the actually changed words receive
 * .diff-char-del / .diff-char-ins spans. */
export function renderInlineDiffSide(original, proposed, side) {
  return inlineDiff(original, proposed)
    .filter((segment) =>
      side === "original" ? segment.type !== "ins" : segment.type !== "del",
    )
    .map((segment) => {
      if (segment.type === "del") {
        return `<span class="diff-char-del">${esc(segment.text)}</span>`;
      }
      if (segment.type === "ins") {
        return `<span class="diff-char-ins">${esc(segment.text)}</span>`;
      }
      return esc(segment.text);
    })
    .join("");
}

/* One addressable .cmp-line row. data-line carries the 0-based index
 * (stable for programmatic anchoring), the visible number is 1-based.
 * `content` must already be escaped (plain esc() or renderInlineDiffSide). */
export function cmpLineHtml(lineIndex, className = "", prefix = "", content = "") {
  const classes = `cmp-line${className ? ` ${className}` : ""}`;
  return `<div class="${classes}" data-line="${lineIndex}"><span class="cmp-line-num">${lineIndex + 1}</span>${prefix}${content}</div>`;
}

/* ------------------------------------------------------------------ */
/* #11 New-user onboarding steps + next-step due reminders (pure)      */
/* ------------------------------------------------------------------ */
/* DOM-free helpers for the three-step onboarding card (岗位库空态) and
 * the interview/follow-up reminders (岗位库 + 工作台). Callers in main.js
 * own the DOM mounting; these functions only derive state and build HTML.
 */

/* 三步引导定义。isDone 接收 { resumes, jobs } 上下文，返回该步是否已完成。
 * skipped 由调用方从 localStorage 传入（每步可跳过，跳过即不再展示）。 */
export const ONBOARDING_STEPS = [
  {
    key: "resume",
    order: 1,
    title: "创建主简历",
    body: "在简历中心录入工作经历与项目亮点，作为所有对齐稿的底稿。",
    actionLabel: "去创建主简历",
    href: "#/resume",
    action: "",
    isDone: ({ resumes }) => resumes.length > 0,
  },
  {
    key: "jd",
    order: 2,
    title: "粘贴首个 JD",
    body: "用顶部输入框粘贴岗位描述或链接，自动建库并预分析 JD 画像。",
    actionLabel: "粘贴 JD / 链接",
    href: "",
    action: "open-command-panel",
    isDone: ({ jobs }) => jobs.length > 0,
  },
  {
    key: "align",
    order: 3,
    title: "跑首次对齐",
    body: "进入岗位工作台选择主简历，点击「一键生成对齐简历」，逐条采纳 AI 改写建议。",
    actionLabel: "打开工作台",
    href: "#/workspace",
    action: "",
    isDone: ({ jobs }) =>
      jobs.some(
        (job) =>
          job &&
          (job.alignment_status === "succeeded" || job.final_draft_version != null),
      ),
  },
];

export function onboardingSteps(input = {}) {
  const { resumes = [], jobs = [], skipped = [] } = input || {};
  const ctx = {
    resumes: Array.isArray(resumes) ? resumes : [],
    jobs: Array.isArray(jobs) ? jobs : [],
  };
  const skippedSet = new Set(Array.isArray(skipped) ? skipped : []);
  return ONBOARDING_STEPS.filter(
    (step) => !step.isDone(ctx) && !skippedSet.has(step.key),
  ).map((step) => ({
    key: step.key,
    order: step.order,
    title: step.title,
    body: step.body,
    actionLabel: step.actionLabel,
    href: step.href,
    action: step.action,
  }));
}

/* 从 next_step 自由文本中解析本地时间日期（时间线弹窗的 datetime-local
 * 语义：无时区 -> 本地时间）。支持：
 *   "2026-08-10" / "2026-8-10 14:30" / "2026-08-10T14:30:00" 及前后缀文字
 * 解析不到日期返回 null（纯文本“等通知”之类不产生提醒）。 */
export function parseNextStepDate(text) {
  const value = String(text || "").trim();
  if (!value) return null;
  const match = value.match(
    /(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[T\s](\d{1,2}):(\d{2})(?::(\d{2}))?)?/,
  );
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = match[4] != null ? Number(match[4]) : 0;
  const minute = match[5] != null ? Number(match[5]) : 0;
  const second = match[6] != null ? Number(match[6]) : 0;
  const date = new Date(year, month - 1, day, hour, minute, second);
  if (
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day
  ) {
    return null; /* impossible date (e.g. 2026-02-31) rolls over -> reject */
  }
  return date;
}

export const REMINDER_WINDOW_MS = 48 * 60 * 60 * 1000; /* 48h */

/* 到期提醒：优先读结构化的 next_step_due_at（时间线弹窗的 datetime-local
 * 字段），其次回退到 next_step 自由文本里的日期正则；均无日期则跳过。
 * 只对已投递/面试中生效：已拿Offer/放弃即使保留 next_step 也不再提醒。
 * 返回按紧迫度升序（最早到期在前）的列表：
 * { job, dueAt, overdue, hoursUntil, stage }——stage 为面试阶段（可能为空）。 */
export function dueReminders(jobs, now = new Date()) {
  const ref = now instanceof Date ? now : new Date(now);
  const list = Array.isArray(jobs) ? jobs : [];
  const reminders = [];
  for (const job of list) {
    if (!job || typeof job !== "object") continue;
    const status = canonicalJobStatus(job.status);
    if (status !== "applied" && status !== "interview") continue;
    const structured = String(job.next_step_due_at || "").trim();
    const text = String(job.next_step || "").trim();
    if (!structured && !text) continue;
    const dueAt = parseNextStepDate(structured || text);
    if (!dueAt) continue;
    const diffMs = dueAt.getTime() - ref.getTime();
    if (diffMs > REMINDER_WINDOW_MS) continue;
    reminders.push({
      job,
      dueAt,
      overdue: diffMs < 0,
      hoursUntil: Math.ceil(diffMs / (60 * 60 * 1000)),
      stage: (job.interview_stage || "").trim() || null,
    });
  }
  reminders.sort((a, b) => a.dueAt.getTime() - b.dueAt.getTime());
  return reminders;
}

/* 提醒的“何时”文案：面试阶段徽章 + 本地到期时间，如“二面 · 8/10 15:00”。
 * 没有阶段或时间时返回空串（调用方回退到 next_step 原文）。 */
export function reminderWhen(reminder) {
  if (!reminder || !reminder.dueAt) return "";
  const date = reminder.dueAt;
  const pad = (n) => String(n).padStart(2, "0");
  const when = `${date.getMonth() + 1}/${date.getDate()} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  return reminder.stage ? `${reminder.stage} · ${when}` : when;
}

export function reminderDueLabel(reminder) {
  if (!reminder) return "";
  if (reminder.overdue) return `已过期 ${Math.abs(reminder.hoursUntil)}h`;
  return reminder.hoursUntil <= 1 ? "1h 内到期" : `${reminder.hoursUntil}h 内到期`;
}

/* 引导卡 HTML；没有剩余步骤时返回空字符串（调用方不应挂载）。 */
export function renderOnboardingCard(steps) {
  if (!steps || !steps.length) return "";
  const items = steps
    .map(
      (step) => `
        <li class="onboarding-step" data-step="${esc(step.key)}">
          <span class="onboarding-step__index" aria-hidden="true">${Number(step.order) || "·"}</span>
          <div class="onboarding-step__title">${esc(step.title)}</div>
          <div class="onboarding-step__body">${esc(step.body)}</div>
          <div class="onboarding-step__actions">
            ${step.href
              ? `<a class="btn btn-primary btn-sm" href="${esc(step.href)}">${esc(step.actionLabel)}</a>`
              : `<button class="btn btn-primary btn-sm" type="button" data-action="${esc(step.action)}">${esc(step.actionLabel)}</button>`}
            <button class="btn btn-ghost btn-sm" type="button" data-action="skip-onboarding-step" data-step="${esc(step.key)}">跳过</button>
          </div>
        </li>`,
    )
    .join("");
  return `
    <section class="onboarding-card" data-onboarding-card role="region" aria-label="新用户三步引导">
      <div class="onboarding-card__head">
        <div>
          <div class="onboarding-card__title">三步上手 ResuAlign</div>
          <div class="small muted">建主简历 → 粘贴 JD → 跑首次对齐，先完成最小闭环</div>
        </div>
        <span class="badge badge-amber badge-pending">新手引导</span>
      </div>
      <ol class="onboarding-steps">${items}</ol>
    </section>`;
}

/* 岗位库顶部提醒条；无到期岗位返回空字符串。 */
export function renderReminderStrip(reminders) {
  if (!reminders || !reminders.length) return "";
  const items = reminders
    .map((reminder) => {
      const job = reminder.job || {};
      const when = reminderWhen(reminder);
      return `<a class="badge badge-amber" href="#/workspace/${encodeURIComponent(job.job_id || "")}" title="${esc(job.next_step || "")}">${esc(job.title || job.job_id || "未命名岗位")} · ${esc(when || job.next_step || "")} · ${esc(reminderDueLabel(reminder))}</a>`;
    })
    .join("");
  return `
    <div class="reminder-strip" data-reminder-strip role="status" aria-label="面试跟进提醒">
      <span class="reminder-strip__label">待跟进 ${reminders.length}</span>
      ${items}
    </div>`;
}

/* 工作台单岗位提醒横幅；无到期提醒返回空字符串。 */
export function renderReminderBanner(reminder) {
  if (!reminder) return "";
  const job = reminder.job || {};
  const when = reminderWhen(reminder);
  return `
    <div class="reminder-banner" data-reminder-banner role="status" aria-label="面试跟进提醒">
      <span class="reminder-strip__label">面试跟进</span>
      <span>「${esc(job.title || job.job_id || "该岗位")}」${esc(reminderDueLabel(reminder))}：${esc(when || job.next_step || "")}</span>
    </div>`;
}

/* ------------------------------------------------------------------ */
/* U7 采纳语义：diff 应用纯函数（split-canvas 单条采纳 / 应用已采纳）    */
/* ------------------------------------------------------------------ */
/* 应用单条 diff 到草稿。与后端 _apply_diffs 的语义保持一致：
 * modify 全量替换 original -> proposed；add 追加行；remove 移除行。 */

export function applyDiffToDraft(draft, diff) {
  const base = String(draft ?? "");
  if (!diff || typeof diff !== "object") return base;
  if (diff.type === "modify" && diff.original && diff.proposed) {
    return base.split(diff.original).join(diff.proposed);
  }
  if (diff.type === "add" && diff.proposed) {
    return `${base}\n${diff.proposed}`;
  }
  if (diff.type === "remove" && diff.original) {
    return base.split(diff.original).join("");
  }
  return base;
}

/* diffCard 使用的可寻址 id：优先 diff_id，缺省回退到 `diff-<index>`，
 * 保证采纳按钮携带的 data-diff-id 与集合判定一致。 */
export function diffAcceptedKey(diff, index) {
  return (diff && diff.diff_id) || `diff-${index}`;
}

/* 只把 acceptedIds 命中的 diff 应用到草稿上（按原顺序）。 */
export function applyAcceptedDiffsToDraft(draft, diffs, acceptedIds) {
  const accepted = new Set(acceptedIds || []);
  let out = String(draft ?? "");
  for (let index = 0; index < (diffs || []).length; index += 1) {
    const diff = diffs[index];
    if (!accepted.has(diffAcceptedKey(diff, index))) continue;
    out = applyDiffToDraft(out, diff);
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* F10/U11 匹配度来源标注（纯）                                        */
/* ------------------------------------------------------------------ */
/* 工作台徽章取分优先级：对齐评估（eval_score.jd_match_score）→ 差距分析
 * （gap.score）→ 岗位持久化匹配分（job.match_score，后端写自最近一次
 * 工作台 eval）。来源文案随徽章 title + 旁注展示。 */

export function matchBadgeInfo(session, job) {
  const alignment = (session && session.alignment) || {};
  const evalScore = alignment.eval_score || {};
  const gap = (session && session.gap) || {};
  if (evalScore.jd_match_score != null) {
    return { score: Number(evalScore.jd_match_score), source: "来自对齐评估" };
  }
  if (gap.score != null) {
    return { score: Number(gap.score), source: "来自差距分析" };
  }
  if (job && job.match_score != null) {
    return { score: Number(job.match_score), source: "来自对齐评估" };
  }
  return { score: null, source: "" };
}

export function renderMatchBadge(session, job) {
  const { score, source } = matchBadgeInfo(session, job);
  if (score == null) return "";
  return `<span class="match-badge ${matchTone(score)}" data-match-badge title="${esc(source)}">匹配 ${Math.round(score)}</span>${source ? `<span class="small muted" data-match-source>${esc(source)}</span>` : ""}`;
}

/* ------------------------------------------------------------------ */
/* F6/U10 时间线弹窗与编辑弹窗表单 HTML（纯，供 main.js 挂到 modal）     */
/* ------------------------------------------------------------------ */

export const INTERVIEW_STAGES = ["一面", "二面", "HR面", "谈薪", "笔试", "其他"];

export function jobSourceUrl(job) {
  if (!job || typeof job !== "object") return "";
  return String(job.source_url || job.jd_url || "").trim();
}

export function jobApplyLinkHtml(job) {
  const url = jobSourceUrl(job);
  if (url) {
    return `<button type="button" class="btn btn-secondary btn-sm" data-action="open-source-url" data-url="${esc(url)}">去投递 ↗</button>`;
  }
  return `<button type="button" class="btn btn-ghost btn-sm" data-action="open-job-detail" data-id="${esc(job && job.job_id ? job.job_id : "")}">补链接</button>`;
}

/* 岗位详情/时间线弹窗表单。next_step_due_at 为 datetime-local（本地时间，
 * 无时区，与 parseNextStepDate 语义一致）；interview_stage 值域含“无”。 */
export function jobTimelineFormHtml(job) {
  const statusOptions = JOB_STATUS_CANONICAL.map(
    (value) =>
      `<option value="${value}" ${canonicalJobStatus(job.status) === value ? "selected" : ""}>${esc(JOB_STATUS_LABELS[value])}</option>`,
  ).join("");
  const stageOptions = `<option value="" ${job.interview_stage ? "" : "selected"}>无</option>${INTERVIEW_STAGES.map(
    (stage) =>
      `<option value="${esc(stage)}" ${job.interview_stage === stage ? "selected" : ""}>${esc(stage)}</option>`,
  ).join("")}`;
  return `<form data-form="job-detail-edit">
      <input type="hidden" name="job_id" value="${esc(job.job_id)}">
      <div class="form-grid">
        <div class="field wide"><label>JD 原文链接</label>
          <div class="row">
            <input type="url" name="source_url" value="${esc(jobSourceUrl(job))}" placeholder="https://...">
            ${jobSourceUrl(job) ? `<button type="button" class="btn btn-secondary btn-sm" data-action="open-source-url" data-url="${esc(jobSourceUrl(job))}">去投递 ↗</button>` : ""}
          </div>
        </div>
        <div class="field"><label>状态</label><select name="status">${statusOptions}</select></div>
        <div class="field"><label>投递时间</label><input type="datetime-local" name="applied_at" value="${esc(job.applied_at || "")}"></div>
        <div class="field"><label>下一步</label><input type="text" name="next_step" value="${esc(job.next_step || "")}"></div>
        <div class="field"><label>到期时间</label><input type="datetime-local" name="next_step_due_at" value="${esc(job.next_step_due_at || "")}"></div>
        <div class="field"><label>面试阶段</label><select name="interview_stage">${stageOptions}</select></div>
        <div class="field"><label>Offer 时间</label><input type="datetime-local" name="offer_at" value="${esc(job.offer_at || "")}"></div>
        <div class="field"><label>拒绝时间</label><input type="datetime-local" name="rejected_at" value="${esc(job.rejected_at || "")}"></div>
        <div class="field wide"><label>备注</label><textarea name="notes" rows="3">${esc(job.notes || "")}</textarea></div>
      </div>
      <div class="actions">
        <button class="btn btn-primary btn-sm" type="button" data-action="record-application" data-id="${esc(job.job_id)}">记录投递</button>
        <button class="btn btn-ghost" type="button" data-action="close-modal">取消</button>
        <button class="btn btn-primary" type="submit">保存</button>
      </div>
    </form>`;
}

/* 编辑岗位弹窗表单。vocabulary 需含 statuses / job_functions / seniorities
 * 列表（由调用方从 events.js vocabularyList 传入，保持本模块无 DOM 依赖）。 */
export function jobEditFormHtml(job, vocabulary = {}) {
  const statusOptions = options(vocabulary.statuses || JOB_STATUSES, job.status);
  const functionOptions =
    `<option value="">未分类</option>${options(vocabulary.job_functions || JOB_FUNCTIONS, job.job_function || "")}`;
  const seniorityOptions =
    `<option value="">未知</option>${options(vocabulary.seniorities || SENIORITIES, job.seniority || "")}`;
  return `<form data-form="job-edit">
      <input type="hidden" name="job_id" value="${esc(job.job_id)}">
      <div class="form-grid">
        <div class="field"><label>标题</label><input type="text" name="title" value="${esc(job.title)}"></div>
        <div class="field"><label>公司</label><input type="text" name="company" value="${esc(job.company || "")}"></div>
        <div class="field"><label>城市</label><input type="text" name="location" value="${esc(job.location || "")}"></div>
        <div class="field"><label>状态</label><select name="status">${statusOptions}</select></div>
        <div class="field"><label>职能</label><select name="job_function">${functionOptions}</select></div>
        <div class="field"><label>级别</label><select name="seniority">${seniorityOptions}</select></div>
        <div class="field"><label>最低薪资（月，元）</label><input type="number" name="salary_min" value="${job.salary_min ?? ""}"></div>
        <div class="field"><label>最高薪资（月，元）</label><input type="number" name="salary_max" value="${job.salary_max ?? ""}"></div>
        <div class="field wide"><label>技术标签（逗号分隔）</label><input type="text" name="tech_tags" value="${esc((job.tech_tags || []).join(", "))}"></div>
        <div class="field wide"><label>JD 文本</label><textarea name="jd_text" rows="8">${esc(job.jd_text)}</textarea></div>
      </div>
      <div class="actions"><button class="btn btn-ghost" type="button" data-action="close-modal">取消</button>
        <button class="btn btn-secondary" type="button" data-action="reclassify-job" data-id="${esc(job.job_id)}">重新分类</button>
        <button class="btn btn-primary" type="submit">保存</button></div>
    </form>`;
}

/* ------------------------------------------------------------------ */
/* B7 采集数据完整性 + U5 耗时格式化（纯）                              */
/* ------------------------------------------------------------------ */

/** 岗位采集完整性：返回缺失字段列表（title / company / salary）。
 *  salary 只要 min/max 任一存在即视为完整（面议岗位常见缺一界）。 */
export function jobCompleteness(job) {
  const j = job || {};
  const missing = [];
  if (!String(j.title || "").trim()) missing.push("title");
  if (!String(j.company || "").trim()) missing.push("company");
  if (j.salary_min == null && j.salary_max == null) missing.push("salary");
  return missing;
}

/** JD 文本是否为抓取失败残留（整页 JSON/HTML）。
 *  - 以 `{`/`[` 开头视为整页 JSON（如页面内嵌配置）
 *  - 含大量 <script> 标签视为整页 HTML
 *  - pageConfig/__NEXT_DATA__ 等 SPA 内嵌特征配合 HTML 结构视为整页
 */
export function isJunkJd(jdText) {
  const text = String(jdText || "").trim();
  if (!text) return false;
  if (/^\s*[{\[]/.test(text)) return true;
  const scriptTags = (text.match(/<script[\s>]/gi) || []).length;
  if (scriptTags >= 3) return true;
  if (
    /pageConfig|__NEXT_DATA__|__INITIAL_STATE__|application\/json/i.test(text) &&
    /<html|<!doctype|<head/i.test(text)
  ) {
    return true;
  }
  return false;
}

/** 岗位卡片完整性徽章：抓取失败优先显示「抓取失败，可重试」，
 *  缺关键字段显示「待补全」（title 说明缺什么）。完整返回空串。 */
export function jobCompletenessBadge(job) {
  if (isJunkJd(job && job.jd_text)) {
    return '<span class="badge badge-amber" title="JD 文本疑似整页 HTML/JSON，抓取可能失败">抓取失败，可重试</span>';
  }
  const missing = jobCompleteness(job);
  if (!missing.length) return "";
  const labels = { title: "标题", company: "公司", salary: "薪资" };
  const detail = missing.map((key) => labels[key] || key).join("、");
  return `<span class="badge badge-amber" title="缺少：${esc(detail)}">待补全</span>`;
}

/** 已用时长格式化：<60s 显示「Xs」，之后显示「分:秒」。 */
export function formatElapsed(ms) {
  const totalSeconds = Math.max(0, Math.floor((Number(ms) || 0) / 1000));
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

/** Eval 评分是否真实运行过（存在任一评估结果字段）。 */
export function hasEvalResult(evalScore) {
  const score = evalScore || {};
  return (
    score.jd_match_score != null ||
    score.improvement != null ||
    score.hallucination_detected != null ||
    score.gap_coverage != null
  );
}

/** 工作台 per-run 评估开关：勾选传 true，不勾选不传（None 回退全局默认）。 */
export function runEvalFromForm(data) {
  const value = data && data.run_eval;
  return value === "on" || value === true ? true : undefined;
}

/* ------------------------------------------------------------------ */
/* #17 Live workbench: side-by-side compare from a live session        */
/* ------------------------------------------------------------------ */
/* The live canvas keeps the per-card 采纳/忽略/润色 interactions in
 * diffList(); this builds the read-only 并排对比 view with buildCmpSideHtml
 * from the session's alignment draft + diffs. */

export function buildLiveCompareHtml(session, originalContent) {
  const alignment = (session && session.alignment) || {};
  const optimizedText = alignment.draft || "";
  const diffs = alignment.diffs || [];
  return buildCmpSideHtml(originalContent || "", optimizedText, diffs);
}

/* ------------------------------------------------------------------ */
/* T3: diff section badge（与后端 DiffItem.section 契约，字符串，可空）  */
/* ------------------------------------------------------------------ */
/* 后端将为 DiffItem 增加可选 `section` 字段（如「工作经历」「项目经历」）
 * 标识该条建议所属的简历区块。section 为空时不渲染任何节点；非空时在
 * diffCard 头部 type 徽章旁渲染一个小徽章（.diff-card__section），
 * diffList 经由 diffCard 自动透传。 */
export function diffSectionBadge(diff) {
  const section = diff && diff.section;
  if (section == null || String(section).trim() === "") return "";
  return `<span class="badge badge-gray diff-card__section">${esc(String(section).trim())}</span>`;
}

/* ------------------------------------------------------------------ */
/* Sprint 1 Dashboard: KPI cards / skill-gap heat bars / quick continue */
/* ------------------------------------------------------------------ */
/* Pure HTML builders for the `#/dashboard` view. Callers in main.js own
 * the GET /api/dashboard fetch and mount these strings into #app; every
 * builder stays DOM-free so it can be unit-tested under Node.
 * Contract (shared with the backend agent):
 *   GET /api/dashboard -> {
 *     kpi: { resumes, jobs, applied, interview, offer, declined, active_followups },
 *     skill_gaps: [{ skill, count } ...],
 *     quick_continue: { job_id, title, company, alignment_status, updated_at } | null
 *   }
 */

/* 4 大 KPI 卡。applied 卡带投递转化提示（占岗位比例）。 */
export function dashboardKpiHtml(kpi = {}) {
  const data = kpi && typeof kpi === "object" ? kpi : {};
  const resumes = Math.max(0, Number(data.resumes) || 0);
  const jobs = Math.max(0, Number(data.jobs) || 0);
  const applied = Math.max(0, Number(data.applied) || 0);
  const followups = Math.max(0, Number(data.active_followups) || 0);
  const applyRate = jobs > 0 ? Math.round((applied / jobs) * 100) : null;
  const cards = [
    { key: "resumes", label: "主简历", value: resumes, tone: "info", hint: "可用的主简历底稿" },
    { key: "jobs", label: "岗位", value: jobs, tone: "teal", hint: "岗位库总数" },
    { key: "applied", label: "已投递", value: applied, tone: "success", hint: applyRate != null ? `占岗位 ${applyRate}%` : "暂无岗位可计算转化" },
    { key: "followups", label: "待跟进", value: followups, tone: "warning", hint: "需要安排下一步" },
  ];
  return `
    <div class="dashboard-kpi-grid" data-dashboard-kpis>
      ${cards
        .map(
          (card) => `
        <div class="dashboard-kpi dashboard-kpi--${card.tone}" data-kpi="${card.key}">
          <div class="dashboard-kpi__label">${esc(card.label)}</div>
          <div class="dashboard-kpi__value">${esc(card.value)}</div>
          <div class="dashboard-kpi__hint">${esc(card.hint)}</div>
        </div>`,
        )
        .join("")}
    </div>`;
}

/* 技能缺口热力图：横向热力条，宽度按 count / max 比例，颜色按相对强度
 * 梯度（cool=info / warm=warning / hot=danger，全部走现有语义 token）。
 * 每条渲染为 data-action="goto-skill" + data-skill 的可点击按钮；
 * onSkillGapUrl(skill) 若提供则额外写入 data-skill-url 兜底深链。 */
export function skillGapHtml(gaps, onSkillGapUrl) {
  const list = Array.isArray(gaps)
    ? gaps.filter((gap) => gap && String(gap.skill || "").trim())
    : [];
  if (!list.length) {
    return `<div class="muted small" data-skill-gaps>暂无技能缺口数据</div>`;
  }
  const max = Math.max(...list.map((gap) => Number(gap.count) || 0));
  const rows = list
    .map((gap) => {
      const skill = String(gap.skill);
      const count = Math.max(0, Number(gap.count) || 0);
      const ratio = max > 0 ? count / max : 0;
      const width = max > 0 ? Math.max(2, Math.round(ratio * 100)) : 0;
      const tone = ratio >= 0.66 ? "hot" : ratio >= 0.33 ? "warm" : "cool";
      const url =
        typeof onSkillGapUrl === "function" ? onSkillGapUrl(skill) : "";
      const urlAttr = url ? ` data-skill-url="${esc(url)}"` : "";
      return `
      <button type="button" class="skill-gap-row" data-action="goto-skill" data-skill="${esc(skill)}"${urlAttr}>
        <span class="skill-gap-row__name">${esc(skill)}</span>
        <span class="skill-gap-row__track" aria-hidden="true">
          <span class="skill-gap-row__fill skill-gap-row__fill--${tone}" style="width:${width}%"></span>
        </span>
        <span class="skill-gap-row__count">${count} 个岗位</span>
      </button>`;
    })
    .join("");
  return `<div class="skill-gap-list" data-skill-gaps>${rows}</div>`;
}

/* Quick Continue 卡：最近工作的岗位快照 + 「继续」入口。quick_continue
 * 为 null / 缺 job_id 时返回空串（调用方直接注入，无节点则什么都不显示）。 */
const ALIGNMENT_STATUS_LABELS = {
  succeeded: "已对齐",
  running: "分析中",
  queued: "排队中",
  failed: "分析失败",
  idle: "待分析",
  pending: "待分析",
};

export function quickContinueHtml(qc) {
  if (!qc || typeof qc !== "object" || !qc.job_id) return "";
  const status = ALIGNMENT_STATUS_LABELS[qc.alignment_status]
    || (qc.alignment_status ? String(qc.alignment_status) : "待分析");
  return `
    <section class="panel panel-card quick-continue" data-quick-continue>
      <div class="quick-continue__head">
        <span class="badge badge-teal">继续上次</span>
        <span class="small muted">更新于 ${formatDate(qc.updated_at)}</span>
      </div>
      <div class="quick-continue__title">${esc(qc.title)}</div>
      <div class="quick-continue__meta">${esc(qc.company || "未知公司")} · <span class="quick-continue__status">${esc(status)}</span></div>
      <div class="quick-continue__actions">
        <a class="btn btn-primary btn-sm" href="#/workspace/${encodeURIComponent(qc.job_id)}">继续</a>
      </div>
    </section>`;
}

/* ------------------------------------------------------------------ */
/* Sprint 1 Header job quick selector + ⌘K job search (pure)           */
/* ------------------------------------------------------------------ */

/* Header 岗位下拉的 option 列表。placeholder 恒为「选择岗位...」，其余每
 * 条为 `<option value="job_id">标题 · 公司</option>`；selectedId 匹配时
 * 标记 selected。 */
export function jobSelectOptionsHtml(jobs, selectedId = "") {
  const list = Array.isArray(jobs) ? jobs : [];
  const selected = String(selectedId || "");
  const options = list
    .map((job) => {
      const id = job && job.job_id;
      if (!id) return "";
      return `<option value="${esc(id)}" ${String(id) === selected ? "selected" : ""}>${esc(job.title || "未命名岗位")}${job.company ? ` · ${esc(job.company)}` : ""}</option>`;
    })
    .join("");
  return `<option value="">选择岗位...</option>${options}`;
}

/* ⌘K「搜岗位」匹配：按标题 / 公司做不区分大小写的子串过滤，最多 limit 条。
 * 空查询或非数组输入返回 []。 */
export function matchJobSuggestions(jobs, query, limit = 6) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) return [];
  const list = Array.isArray(jobs) ? jobs : [];
  const max = Math.max(1, Number(limit) || 1);
  return list
    .filter(
      (job) =>
        job &&
        (String(job.title || "").toLowerCase().includes(q) ||
          String(job.company || "").toLowerCase().includes(q)),
    )
    .slice(0, max);
}

/* ⌘K 建议下拉的按钮 HTML；无匹配返回空串。data-job-id 供点击/回车跳转。 */
export function renderJobSuggestionsHtml(jobs, query) {
  const matches = matchJobSuggestions(jobs, query);
  if (!matches.length) return "";
  return matches
    .map(
      (job) => `
      <button type="button" class="command-suggestion" data-command-suggestion data-job-id="${esc(job.job_id)}">
        <span class="command-suggestion__title">${esc(job.title || "未命名岗位")}</span>
        ${job.company ? `<span class="command-suggestion__meta">${esc(job.company)}</span>` : ""}
      </button>`,
    )
    .join("");
}

/* ------------------------------------------------------------------ */
/* Sprint 2: 三栏工作台 Live Sheet（右栏定稿实时预览，纯函数）            */
/* ------------------------------------------------------------------ */
/* 供 split-canvas.js（并行 Agent A）消费的三个纯函数 + 占位文案常量：
 *  - renderLiveSheetHtml(draft)        挂载初始渲染：纸张容器 + renderMarkdown
 *  - liveSheetPatch(prevDraft, newDraft)  增量 patch：行级 rows + addedLines + html
 *  - highlightSkillGapHtml(gapItems, skill)  技能命中高亮（?skill 定位用）
 * 本模块保持 DOM-free，可在 Node 下直接单测（tests/frontend/live-sheet.test.mjs）。
 *
 * 契约（Agent A 消费约定）：
 *  - renderLiveSheetHtml 返回可直接挂进 [data-live-sheet-pane] 的完整容器
 *    `<section class="live-sheet" data-live-sheet>`，正文在
 *    `[data-live-sheet-paper]` 内（空草稿为占位文案，非空为 renderMarkdown）。
 *  - liveSheetPatch 返回 { html, rows, addedLines }：
 *      * rows       —— newDraft 的非空行数组 [{ index, text, added }]，
 *                      index 为行序号（0 起，DOM 增量按此对齐）；
 *      * addedLines —— Set<number>，相对 prevDraft 新增的行序号；
 *      * html       —— 完整行渲染（含 live-sheet-line--added 高亮），
 *                      可直接替换 [data-live-sheet-paper] 的 innerHTML。
 *    Agent A 推荐做法：按 rows 序号对齐已有 DOM 行，缺的追加、多的移除，
 *    对 addedLines 中的行加 class「live-sheet-line--added」并滚动到可视区。
 *  - highlightSkillGapHtml 复用 renderGap 的 gap 结构
 *    { missing_keywords, strength_matches, misaligned_emphasis }，命中项输出
 *    class「is-skill-match」+ 属性「data-match-skill」，未命中不输出。
 */

export const LIVE_SHEET_PLACEHOLDER = "采纳右侧提案后，此处实时预览定稿";

/** 空草稿时纸张正文的占位 HTML（renderLiveSheetHtml / liveSheetPatch 共用）。 */
function liveSheetPlaceholderHtml() {
  return `<div class="live-sheet__placeholder">${LIVE_SHEET_PLACEHOLDER}</div>`;
}

export function renderLiveSheetHtml(draft) {
  const hasContent = Boolean(String(draft ?? "").trim());
  const body = hasContent
    ? renderMarkdown(draft)
    : liveSheetPlaceholderHtml();
  const meta = hasContent
    ? `${String(draft ?? "").split(/\r?\n/).filter((line) => line.trim()).length} 行`
    : "空草稿";
  return `
    <section class="live-sheet" data-live-sheet>
      <div class="live-sheet__head">
        <span class="live-sheet__title">定稿 Live Sheet</span>
        <span class="live-sheet__meta" data-live-sheet-meta title="${esc(meta)}">实时同步</span>
      </div>
      <div class="live-sheet__paper" data-live-sheet-paper>${body}</div>
    </section>`;
}

export function liveSheetPatch(prevDraft, newDraft) {
  const nextLines = String(newDraft ?? "").split("\n");
  /* 复用 lineDiff 的 add 行识别“相对 prevDraft 新增的 trim 文本”，
   * 与现有 lineDiff 语义保持一致（忽略空行、按 trim 比较）。 */
  const addedTrimmed = new Set(
    lineDiff(prevDraft, newDraft)
      .filter((row) => row.type === "add")
      .map((row) => row.text.trim()),
  );
  const rows = [];
  for (const raw of nextLines) {
    const text = raw.trim();
    if (!text) continue;
    rows.push({ index: rows.length, text, added: addedTrimmed.has(text) });
  }
  const addedLines = new Set(rows.filter((row) => row.added).map((row) => row.index));
  const html = rows.length
    ? rows
        .map(
          (row) =>
            `<div class="live-sheet-line${row.added ? " live-sheet-line--added" : ""}" data-live-line="${row.index}">${esc(row.text)}</div>`,
        )
        .join("")
    : liveSheetPlaceholderHtml();
  return { html, rows, addedLines };
}

export function highlightSkillGapHtml(gapItems, skill) {
  if (!gapItems) return null;
  const needle = String(skill ?? "").trim().toLowerCase();
  const isHit = (item) =>
    needle.length > 0 && String(item ?? "").toLowerCase().includes(needle);
  const tag = (item, extraClass = "") => {
    const hit = isHit(item);
    const cls = `gap-tag${extraClass ? ` ${extraClass}` : ""}${hit ? " is-skill-match" : ""}`;
    return `<span class="${cls}"${hit ? " data-match-skill" : ""}>${esc(item)}</span>`;
  };
  const missing = gapItems.missing_keywords || [];
  const strengths = gapItems.strength_matches || [];
  const misaligned = gapItems.misaligned_emphasis || [];
  const blocks = [];
  if (missing.length) {
    blocks.push(`
      <div class="gap-group gap-group--missing">
        <div class="split-section-title">差距项</div>
        <div class="gap-tags">${missing.map((item) => tag(item)).join("")}</div>
      </div>`);
  }
  if (strengths.length) {
    blocks.push(`
      <div class="gap-group gap-group--strength">
        <div class="split-section-title">已有匹配</div>
        <div class="gap-tags">${strengths.map((item) => tag(item, "gap-tag--ok")).join("")}</div>
      </div>`);
  }
  if (misaligned.length) {
    blocks.push(`
      <div class="gap-group gap-group--warn">
        <div class="split-section-title">错位强调</div>
        <div class="gap-tags">${misaligned.map((item) => tag(item, "gap-tag--warn")).join("")}</div>
      </div>`);
  }
  if (!blocks.length) {
    blocks.push(`<div class="small muted">尚未生成差距报告</div>`);
  }
  return blocks.join("");
}

/* ------------------------------------------------------------------ */
/* Sprint 3: Pipeline + Blocker（抓取结果文案 / 阻断列表 / 微标）          */
/* ------------------------------------------------------------------ */
/* 与后端并行实现的契约（本模块保持 DOM-free，可在 Node 下单测）：
 *   POST /api/jobs/fetch-url {url}
 *     -> { status:'created'|'duplicate'|'blocked'|'rule_rejected',
 *          job_id?, blocker_id?, reason? }
 *   GET  /api/blockers?status=pending
 *     -> [{ blocker_id, job_id, url, title, reason, category, status, created_at }]
 */

export const FETCH_URL_STATUS_MESSAGES = {
  created: "岗位已抓取",
  duplicate: "已存在相同岗位",
  blocked: "已加入阻断队列",
  rule_rejected: "规则拦截",
};

/** fetch-url 提交结果的 toast 文案。blocked / rule_rejected 会带上后端
 *  reason（若提供）；未知状态回退为「抓取结果：<status>」。 */
export function fetchUrlResultMessage(status, reason) {
  const key = String(status || "");
  const reasonText = String(reason || "").trim();
  if (key === "blocked" || key === "rule_rejected") {
    return reasonText
      ? `${FETCH_URL_STATUS_MESSAGES[key] || key}：${reasonText}`
      : FETCH_URL_STATUS_MESSAGES[key] || key;
  }
  return FETCH_URL_STATUS_MESSAGES[key] || `抓取结果：${key || "未知"}`;
}

/** 阻断队列列表 HTML（showModal 内容）。每条含 URL / title / category /
 *  reason / created_at，以及「忽略」「手动补全」两个操作与补全表单；
 *  URL / title / reason / category / blocker_id 全部经 esc 转义。 */
export function blockerListHtml(blockers) {
  const list = Array.isArray(blockers) ? blockers : [];
  if (!list.length) {
    return `<div class="blocker-list" data-blocker-list><div class="muted small" data-blocker-empty>暂无待处理的阻断</div></div>`;
  }
  const items = list
    .map((blocker) => {
      const id = esc(blocker && blocker.blocker_id);
      const url = esc(blocker && blocker.url);
      const title = esc((blocker && blocker.title) || "未命名岗位");
      const reason = esc(blocker && blocker.reason);
      const category = esc(blocker && blocker.category);
      const time = formatDate(blocker && blocker.created_at);
      return `
      <article class="blocker-item" data-blocker-item data-blocker-id="${id}">
        <div class="blocker-item__head">
          <span class="badge badge-amber">待处理</span>
          <span class="small muted">${time}</span>
        </div>
        <div class="blocker-item__title">${title}</div>
        <div class="blocker-item__meta">${url}${category ? ` · ${category}` : ""}</div>
        ${reason ? `<div class="blocker-item__reason">${reason}</div>` : ""}
        <div class="blocker-item__actions">
          <button type="button" class="btn btn-outline btn-sm" data-action="ignore-blocker" data-id="${id}">忽略</button>
          <button type="button" class="btn btn-secondary btn-sm" data-action="toggle-blocker-resolve" data-id="${id}">手动补全</button>
        </div>
        <form class="blocker-resolve" data-form="blocker-resolve" data-id="${id}" hidden>
          <input type="hidden" name="blocker_id" value="${id}">
          <textarea name="manual_text" rows="5" placeholder="粘贴该岗位 JD 文本，手动补全后入库存档"></textarea>
          <div class="row" style="margin-top:8px">
            <button class="btn btn-primary btn-sm" type="submit">提交补全</button>
            <button class="btn btn-ghost btn-sm" type="button" data-action="cancel-blocker-resolve" data-id="${id}">取消</button>
          </div>
        </form>
      </article>`;
    })
    .join("");
  return `<div class="blocker-list" data-blocker-list>${items}</div>`;
}

/** 阻断微标 HTML（数字 badge + 闪烁动画由 CSS 提供）。pending 为 0 / 负数 /
 *  缺失时返回空串，调用方不挂载任何节点。 */
export function blockerCountBadge(count) {
  const n = Math.max(0, Number(count) || 0);
  if (n <= 0) return "";
  return `<button type="button" class="blocker-badge" data-action="open-blockers" title="有 ${n} 条抓取阻断待处理" aria-label="打开抓取阻断队列：${n} 条待处理">阻断 <span class="blocker-badge__count">${n}</span></button>`;
}

/* ------------------------------------------------------------------ */
/* Sprint 4: Resume Center（ATS 健康度卡 + 版本时间线，纯函数）           */
/* ------------------------------------------------------------------ */
/* 数据源契约（与 events.js renderDiagnosisResult / recoverDiagnosis 对齐）：
 *   state.diagnosis = { job_id, status, result: { diagnosis } }
 *   diagnosis 对象含 score / skills / issues / suggestions / model。
 * 版本列表来自 GET /api/master-resumes/{id} 的内嵌字段 versions：
 *   [{ version, content, created_at }]（按 version ASC）。
 */

/** ATS 健康度分级：≥85 优秀 / ≥70 良好 / <70 待提升。 */
export function atsHealthScoreLevel(score) {
  if (score >= 85) return "优秀";
  if (score >= 70) return "良好";
  return "待提升";
}

/** ATS 卡片视觉 tone：high / mid / low，对应 --success / --warning / --danger。 */
export function atsHealthTone(score) {
  if (score == null) return "low";
  if (score >= 85) return "high";
  if (score >= 70) return "mid";
  return "low";
}

/** 简历诊断摘要卡。传入 diagnosis 对象（result.diagnosis || result）。
 * 空诊断（无 score / skills / issues / suggestions）渲染「尚未诊断」占位。 */
export function atsHealthCardHtml(diagnosis) {
  const data = diagnosis && typeof diagnosis === "object" ? diagnosis : {};
  const rawScore = Number(data.score);
  const score = Number.isFinite(rawScore)
    ? Math.max(0, Math.min(100, rawScore))
    : null;
  const skills = Array.isArray(data.skills)
    ? data.skills.map((item) => String(item ?? "")).filter(Boolean)
    : [];
  const issues = Array.isArray(data.issues)
    ? data.issues.map((item) => String(item ?? "")).filter(Boolean)
    : [];
  const suggestions = Array.isArray(data.suggestions)
    ? data.suggestions.map((item) => String(item ?? "")).filter(Boolean)
    : [];
  const isEmpty =
    score == null && !skills.length && !issues.length && !suggestions.length;
  if (isEmpty) {
    return `
      <div class="ats-health ats-health--empty" data-ats-health>
        <div class="ats-health__score"><span class="ats-health__value" data-ats-score>—</span><span class="ats-health__unit">/100</span></div>
        <span class="badge badge-gray" data-ats-level>尚未诊断</span>
        <div class="small muted ats-health__empty-hint">运行一次简历诊断即可获得 ATS 健康度评分、优势高光与改进建议。</div>
      </div>`;
  }
  const level = score == null ? "待提升" : atsHealthScoreLevel(score);
  const levelClass =
    score == null
      ? "badge-gray"
      : score >= 85
        ? "badge-green"
        : score >= 70
          ? "badge-amber"
          : "badge-red";
  const tone = atsHealthTone(score);
  /* 优势高光：issues 里无（无问题）则展示 skills；改进建议取 issues / suggestions
   * 前 3 条（优先 issues，缺省回退 suggestions）。 */
  const highlights = issues.length ? [] : skills;
  const improvements = (issues.length ? issues : suggestions).slice(0, 3);
  return `
    <div class="ats-health ats-health--${tone}" data-ats-health>
      <div class="ats-health__score"><span class="ats-health__value" data-ats-score>${score ?? "—"}</span><span class="ats-health__unit">/100</span></div>
      <div class="ats-health__level"><span class="badge ${levelClass}" data-ats-level>${esc(level)}</span><span class="small muted">ATS 健康度</span></div>
      ${highlights.length ? `
      <div class="ats-health__section" data-ats-highlights>
        <h4>优势高光</h4>
        <div class="chips">${highlights.slice(0, 4).map((item) => `<span class="chip">${esc(item)}</span>`).join("")}</div>
      </div>` : ""}
      ${improvements.length ? `
      <div class="ats-health__section" data-ats-improvements>
        <h4>改进建议</h4>
        <ul class="ats-health__list">${improvements.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>
      </div>` : ""}
    </div>`;
}

/** 相邻版本变更摘要：取 lineDiff 前 2 行（+/- 前缀）；无差异 →「内容更新」；
 *  无前版 → 以 add 行占位（"+ 初始版本"，与其它新增行前缀一致）。
 *  超过 60 字符截断。返回原始文本，转义发生在渲染处。 */
export function versionChangeSummary(previous, version) {
  const rows = previous
    ? lineDiff(previous.content, version.content).slice(0, 2)
    : [{ type: "add", text: "初始版本" }];
  if (!rows.length) return "内容更新";
  const text = rows
    .map((row) => `${row.type === "add" ? "+" : "-"} ${String(row.text).trim()}`)
    .join("；");
  return text.length > 60 ? `${text.slice(0, 60)}…` : text;
}

/** 版本时间线（竖线）：每条 vN + 创建时间 + 变更摘要 + 当前标记；非当前版本
 *  提供「预览」（data-action=preview-version）与「回滚」（rollback-resume）。
 *  resumeId 用于回滚按钮的 data-id。 */
export function versionTimelineHtml(versions, currentVersion, resumeId = "") {
  const list = Array.isArray(versions) ? versions : [];
  if (!list.length) {
    return `<div class="version-timeline" data-version-timeline><div class="muted small">暂无版本</div></div>`;
  }
  const items = list
    .map((version, index) => {
      const current = Number(version.version) === Number(currentVersion);
      const summary = versionChangeSummary(list[index - 1], version);
      return `
    <div class="version-timeline-item${current ? " is-current" : ""}" data-version-item data-version="${esc(version.version)}">
      <div class="version-timeline__dot" aria-hidden="true"></div>
      <div class="version-timeline__body">
        <div class="version-timeline__head">
          <span class="version-timeline__no">v${esc(version.version)}</span>
          ${current ? '<span class="badge badge-green" data-version-current>当前</span>' : ""}
          <span class="small muted">${formatDate(version.created_at)}</span>
        </div>
        <div class="version-timeline__summary" data-version-summary>${esc(summary)}</div>
        ${current ? "" : `
        <div class="version-timeline__actions">
          <button type="button" class="btn btn-outline btn-sm" data-action="preview-version" data-version="${esc(version.version)}">预览</button>
          <button type="button" class="btn btn-ghost btn-sm" data-action="rollback-resume" data-id="${esc(resumeId)}" data-version="${esc(version.version)}">回滚</button>
        </div>`}
      </div>
    </div>`;
    })
    .join("");
  return `<div class="version-timeline" data-version-timeline>${items}</div>`;
}

/* ------------------------------------------------------------------ */
/* Sprint 5: 系统设置全量升级 —— Bento 概览 / LLM 节点 / 自动化规则（纯）   */
/* ------------------------------------------------------------------ */
/* 本模块保持 DOM-free，可在 Node 下单测。契约（与后端 agent 并行对齐）：
 *   GET  /api/llm/nodes -> [{node_id, name, provider, base_url, model,
 *                            api_key(masked), is_active, created_at}]
 *   POST /api/llm/nodes {name, provider, base_url, api_key, model} -> 201
 *   PUT  /api/llm/nodes/{id}（api_key 省略则保留已存 key）-> 200
 *   DELETE /api/llm/nodes/{id} -> 204
 *   POST /api/llm/nodes/{id}/activate -> 200
 *   POST /api/llm/nodes/{id}/test -> {ok, status, latency_ms, message}
 *   GET/POST/DELETE /api/automation/rules（Sprint 3 已有）
 *     rule: {rule_id, rule_type(blacklist|city_whitelist|min_salary),
 *            value, label, enabled}
 * Guardrails：后端 Read Timeout 40s + 并发额度 1（只读展示）。
 */

export const LLM_NODE_PROVIDERS = ["deepseek", "openrouter", "ollama"];

export const LLM_NODE_PROVIDER_LABELS = {
  deepseek: "DeepSeek",
  openrouter: "OpenRouter",
  ollama: "Ollama",
};

export const AUTOMATION_RULE_TYPE_LABELS = {
  blacklist: "黑名单",
  city_whitelist: "城市白名单",
  min_salary: "最低薪资",
};

/** 规则类型的展示标签；未知类型原样返回。 */
export function automationRuleTypeLabel(ruleType) {
  return AUTOMATION_RULE_TYPE_LABELS[ruleType] || String(ruleType || "");
}

export const GUARDRAIL_READ_TIMEOUT_S = 40;
export const GUARDRAIL_CONCURRENCY = 1;

/* --- T1: Hero Bento 概览 --- */
/* 4 列 Bento 卡：活跃模型 ID / 架构模式 / Timeout 护栏 / API 延迟。
 * activeNode 为 GET /api/llm/nodes 中 is_active 的节点（可为 null）；
 * latency 为最近一次节点 test 的 latency_ms（null 表示尚未测试）；
 * Timeout 护栏沿用后端 Read Timeout 40s + 并发额度 1 契约。 */
export function settingsBentoHtml(activeNode, latency) {
  const node = activeNode && typeof activeNode === "object" ? activeNode : null;
  const model = node && String(node.model || "").trim() ? String(node.model) : "—";
  const provider = node && String(node.provider || "").trim() ? String(node.provider) : "";
  const activeLabel = provider ? `${provider} · ${model}` : model;
  const latencyNum =
    latency == null || latency === "" ? NaN : Number(latency);
  const hasLatency = Number.isFinite(latencyNum) && latencyNum >= 0;
  const latencyText = hasLatency ? `${Math.round(latencyNum)} ms` : "—";
  return `
    <section class="settings-bento metric-strip settings-status" data-settings-bento aria-label="系统概览">
      <div class="settings-bento__card metric-cell settings-bento__card--model" data-bento-model>
        <span class="settings-bento__label">活跃模型 ID</span>
        <strong class="settings-bento__value">${esc(activeLabel)}</strong>
        <span class="settings-bento__hint">${node ? "当前生效的 LLM 节点" : "未配置生效节点"}</span>
      </div>
      <div class="settings-bento__card metric-cell" data-bento-arch>
        <span class="settings-bento__label">架构模式</span>
        <strong class="settings-bento__value">本地 SQLite</strong>
        <span class="settings-bento__hint">单机部署，数据全部落本地</span>
      </div>
      <div class="settings-bento__card metric-cell settings-bento__card--timeout" data-bento-timeout>
        <span class="settings-bento__label">Timeout 护栏</span>
        <strong class="settings-bento__value">${GUARDRAIL_READ_TIMEOUT_S} 秒</strong>
        <span class="settings-bento__hint">并发: ${GUARDRAIL_CONCURRENCY}</span>
      </div>
      <div class="settings-bento__card metric-cell" data-bento-latency>
        <span class="settings-bento__label">API 延迟</span>
        <strong class="settings-bento__value">${esc(latencyText)}</strong>
        <span class="settings-bento__hint">${hasLatency ? "最近一次节点连通测试" : "尚未测试，可点节点卡「测试连通性」"}</span>
      </div>
    </section>`;
}

/* --- T2: LLM 节点卡 + 表单 + 测试结果 --- */

/** 节点测试结果块。result 为 {ok, status, latency_ms, message}；
 *  无结果（null/undefined/缺 ok 布尔）返回空串，调用方不挂载任何节点。
 *  HTTP status + latency 优先展示，message 兜底说明。 */
export function nodeTestResultHtml(result) {
  if (!result || typeof result !== "object" || typeof result.ok !== "boolean") {
    return "";
  }
  const ok = Boolean(result.ok);
  const statusRaw = String(result.status ?? "").trim();
  const latencyNum =
    result.latency_ms == null || result.latency_ms === ""
      ? NaN
      : Number(result.latency_ms);
  const hasLatency = Number.isFinite(latencyNum) && latencyNum >= 0;
  const message = String(result.message || "").trim();
  const parts = [];
  if (statusRaw) parts.push(`HTTP ${statusRaw}`);
  if (hasLatency) parts.push(`${Math.round(latencyNum)} ms`);
  const meta = parts.length ? `<strong>${parts.join(" · ")}</strong>` : "";
  const cls = ok ? "form-success" : "form-error";
  const role = ok ? "status" : "alert";
  return `<div class="${cls}" role="${role}" data-llm-node-test>${meta}${meta && message ? " " : ""}${message ? esc(message) : ""}</div>`;
}

/** 单张 LLM 节点卡。node.api_key 来自后端（已掩码），此处仍经 maskApiKey
 *  防御一次，保证明文 key 也不会泄漏。lastTest 为该节点的最近测试结果。 */
export function llmNodeCardHtml(node, lastTest) {
  const n = node && typeof node === "object" ? node : {};
  const nodeId = String(n.node_id || "");
  const active = Boolean(n.is_active);
  const name = String(n.name || "").trim() || "未命名节点";
  const provider = String(n.provider || "").trim() || "—";
  const model = String(n.model || "").trim() || "—";
  const baseUrl = String(n.base_url || "").trim();
  const maskedKey = maskApiKey(n.api_key);
  const testResult = lastTest ? nodeTestResultHtml(lastTest) : "";
  return `
    <article class="llm-node-card${active ? " is-active" : ""}" data-llm-node-card data-node-id="${esc(nodeId)}">
      <div class="llm-node-card__head">
        <div class="llm-node-card__title">${esc(name)}</div>
        ${active ? '<span class="badge badge-green" data-node-active-badge>当前生效</span>' : ""}
      </div>
      <dl class="llm-node-card__meta">
        <div><dt>服务商</dt><dd>${esc(provider)}</dd></div>
        <div><dt>模型</dt><dd>${esc(model)}</dd></div>
        ${baseUrl ? `<div><dt>Base URL</dt><dd>${esc(baseUrl)}</dd></div>` : ""}
        <div><dt>API Key</dt><dd class="llm-node-card__key">${maskedKey ? esc(maskedKey) : '<span class="muted">未配置</span>'}</dd></div>
      </dl>
      <div class="llm-node-card__actions">
        <button type="button" class="btn btn-outline btn-sm" data-action="llm-node-test" data-id="${esc(nodeId)}">测试连通性</button>
        ${active ? "" : `<button type="button" class="btn btn-outline btn-sm" data-action="llm-node-activate" data-id="${esc(nodeId)}">设为当前生效</button>`}
        <button type="button" class="btn btn-ghost btn-sm" data-action="llm-node-edit" data-id="${esc(nodeId)}">编辑</button>
        <button type="button" class="btn btn-danger btn-sm" data-action="llm-node-delete" data-id="${esc(nodeId)}">删除</button>
      </div>
      <div class="llm-node-card__test" data-llm-node-test-result>${testResult}</div>
    </article>`;
}

/** LLM 节点新增/编辑 Modal 表单。node 为 null 表示新增；编辑时预填字段，
 *  API Key 输入框留空表示保持不变（占位文案提示已保存掩码）。 */
export function llmNodeFormHtml(node) {
  const n = node && typeof node === "object" ? node : {};
  const nodeId = String(n.node_id || "");
  const name = String(n.name || "");
  const provider = String(n.provider || "deepseek");
  const model = String(n.model || "");
  const baseUrl = String(n.base_url || "");
  const hasKey = Boolean(n.api_key);
  const providerOptions = LLM_NODE_PROVIDERS.map(
    (value) =>
      `<option value="${esc(value)}" ${provider === value ? "selected" : ""}>${esc(LLM_NODE_PROVIDER_LABELS[value] || value)}</option>`,
  ).join("");
  return `<form data-form="llm-node-form">
      <input type="hidden" name="node_id" value="${esc(nodeId)}">
      <div class="form-grid">
        <div class="field"><label>节点名称</label>
          <input type="text" name="node_name" required maxlength="80" value="${esc(name)}" placeholder="例如：主 DeepSeek 节点"></div>
        <div class="field"><label>服务商</label>
          <select name="node_provider">${providerOptions}</select></div>
        <div class="field"><label>模型名称</label>
          <input type="text" name="node_model" required value="${esc(model)}" placeholder="例如 deepseek-chat"></div>
        <div class="field"><label>Base URL（可选）</label>
          <input type="text" name="node_base_url" value="${esc(baseUrl)}" placeholder="留空使用服务商默认地址"></div>
        <div class="field wide"><label>API Key${nodeId ? "（编辑留空保持不变）" : ""}</label>
          <input type="password" name="node_api_key" autocomplete="new-password" value="" placeholder="${hasKey ? "已保存，留空保持不变" : "输入 API Key（Ollama 可留空）"}">
          ${hasKey ? `<div class="small muted">已保存 Key：${esc(maskApiKey(n.api_key))}</div>` : ""}</div>
      </div>
      <div class="actions">
        <button class="btn btn-ghost" type="button" data-action="close-modal">取消</button>
        <button class="btn btn-primary" type="submit">${nodeId ? "保存修改" : "创建节点"}</button>
      </div>
    </form>`;
}

/* --- T4: 自动化规则列表 + 新增表单 --- */

/** 规则列表。每条渲染类型中文标签 + value + label + enabled 开关 + 删除。
 *  开关为 checkbox（data-rule-toggle），change 事件由 main.js 委托 PUT。 */
export function ruleListHtml(rules) {
  const list = Array.isArray(rules) ? rules : [];
  if (!list.length) {
    return `
      <div class="rule-list" data-rule-list>
        <div class="rule-empty" data-rule-empty>
          <span class="rule-empty__plus" aria-hidden="true">＋</span>
          <span class="rule-empty__copy">新增规则 · 拦截外包/单休岗位</span>
          <button class="btn btn-outline btn-sm" type="button" data-action="automation-rule-add">新增规则</button>
        </div>
      </div>`;
  }
  const items = list
    .map((rule) => {
      const id = esc(rule && rule.rule_id);
      const ruleType = String((rule && rule.rule_type) || "").trim();
      const typeLabel = esc(automationRuleTypeLabel(ruleType));
      const value = esc((rule && rule.value) || "");
      const label = rule && rule.label ? esc(String(rule.label)) : "";
      const enabled = Boolean(rule && rule.enabled);
      const tone = ruleType === "blacklist" ? "badge-red" : ruleType === "city_whitelist" ? "badge-blue" : "badge-amber";
      return `
    <article class="rule-item" data-rule-item data-rule-id="${id}">
      <div class="rule-item__head">
        <span class="badge ${tone}">${typeLabel}</span>
        <label class="rule-toggle">
          <input type="checkbox" data-rule-toggle data-id="${id}" ${enabled ? "checked" : ""} aria-label="${enabled ? "停用规则" : "启用规则"}">
          <span class="rule-toggle__track" aria-hidden="true"></span>
          <span class="small muted">${enabled ? "启用" : "停用"}</span>
        </label>
      </div>
      ${label ? `<div class="rule-item__label">${label}</div>` : ""}
      <div class="rule-item__value">${value}</div>
      <div class="rule-item__actions">
        <button type="button" class="btn btn-danger btn-sm" data-action="automation-rule-delete" data-id="${id}">删除</button>
      </div>
    </article>`;
    })
    .join("");
  return `<div class="rule-list" data-rule-list>${items}</div>`;
}

/** 自动化规则新增 Modal 表单（type 下拉 + value 输入 + label）。 */
export function ruleFormHtml() {
  return `<form data-form="automation-rule-form">
      <div class="form-grid">
        <div class="field"><label>规则类型</label>
          <select name="rule_type">
            <option value="blacklist">黑名单（拦截公司名/关键词）</option>
            <option value="city_whitelist">城市白名单（仅抓取这些城市）</option>
            <option value="min_salary">最低薪资（低于则拦截，单位：千元/月）</option>
          </select></div>
        <div class="field"><label>规则值</label>
          <input type="text" name="rule_value" required maxlength="2000" placeholder="例如：Acme 科技 / 上海,杭州 / 20"></div>
        <div class="field wide"><label>备注标签（可选）</label>
          <input type="text" name="rule_label" maxlength="200" placeholder="例如：排除外包公司"></div>
      </div>
      <div class="actions">
        <button class="btn btn-ghost" type="button" data-action="close-modal">取消</button>
        <button class="btn btn-primary" type="submit">新增规则</button>
      </div>
    </form>`;
}

