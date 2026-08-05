/* Pure formatting / state-derivation helpers shared by the browser ESM modules.
 *
 * This module MUST stay free of DOM/window/document/localStorage/fetch access
 * so it can be imported and unit-tested directly under Node
 * (see tests/frontend/*.test.mjs). Function bodies were moved from main.js /
 * events.js / split-canvas.js / diff-editor.js / appraisal-panel.js /
 * command-panel.js. Signatures and HTML output are covered by the node:test
 * suite; DOM-touching callers keep thin wrappers in their original modules.
 */

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

const ROUTE_NAMES = ["resume", "jobs", "workspace", "settings"];

export function parseHashValue(hash) {
  const value = String(hash || "").replace(/^#\/?/, "");
  const parts = value.split("/").filter(Boolean);
  if (parts[0] === "workspace" && parts[1]) {
    let jobId = parts[1];
    try {
      jobId = decodeURIComponent(jobId);
    } catch {
      /* keep raw value */
    }
    return { name: "workspace", jobId };
  }
  if (parts[0] === "resume" && parts[1]) {
    let resumeId = parts[1];
    try {
      resumeId = decodeURIComponent(resumeId);
    } catch {
      /* keep raw value */
    }
    return { name: "resume", jobId: null, resumeId };
  }
  const name = ROUTE_NAMES.includes(parts[0]) ? parts[0] : "resume";
  return { name, jobId: null, resumeId: null };
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
  return `
    <article class="diff-card ${invalid ? "diff-card--invalid" : ""}" data-diff-id="${esc(diffId)}" data-diff-index="${index}">
      <div class="diff-card__head">
        <div class="diff-card__type">
          <span class="badge ${invalid ? "badge-amber" : "badge-blue"}">${esc(typeLabel)}</span>
          <span class="small muted">${diff.confidence ? `置信度 ${esc(diff.confidence)}` : ""}</span>
        </div>
        <div class="provenance-badge provenance-badge--${esc(stateKey)}" data-provenance title="${esc(provenance)}">${esc(label)}</div>
      </div>
      <div class="diff-card__columns">
        <div class="diff-card__col diff-card__col--original">
          <div class="split-section-title">原文</div>
          <div class="diff-card__text" data-diff-original>${esc(diff.original || "")}</div>
        </div>
        <div class="diff-card__col diff-card__col--proposed">
          <div class="split-section-title">优化</div>
          <div class="diff-card__text" data-diff-proposed>${esc(diff.proposed || "")}</div>
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
        <div class="big">还没有对齐结果</div>
        <div class="small muted">选择一份主简历并运行对齐，AI 会逐条给出改写建议。</div>
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
        <button class="btn btn-primary" type="submit" data-align-run ${running ? "disabled" : ""}>${running ? "对齐运行中..." : "一键生成对齐简历"}</button>
        <button class="btn btn-ghost btn-sm" type="button" data-action="apply-accepted-bullets" data-id="${esc(jobId)}" ${!alignment.draft ? "disabled" : ""}>应用已采纳</button>
        <span class="small muted" data-align-status>${alignment.status === "succeeded" ? "已生成对齐版本" : alignment.status === "failed" ? `任务失败：${esc(alignment.error || "请重试")}` : alignment.status === "running" || alignment.status === "queued" ? "正在生成..." : ""}</span>
      </div>
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
    <div class="export-dock" data-export-dock>
      <span class="small muted">导出</span>
      <button class="btn btn-secondary btn-sm" type="button" data-action="copy-align-markdown" data-id="${esc(jobId)}">复制 Markdown</button>
      <button class="btn btn-secondary btn-sm" type="button" data-action="export-align-markdown" data-id="${esc(jobId)}">下载 Markdown</button>
      <button class="btn btn-secondary btn-sm" type="button" data-action="export-align-pdf" data-id="${esc(jobId)}">导出 PDF</button>
      <button class="btn btn-outline btn-sm" type="button" data-action="export-align-json" data-id="${esc(jobId)}">导出 JSON</button>
      ${alignment.draft ? `<span class="badge badge-green">已生成</span>` : ""}
    </div>`;
}

export function boardCard(job) {
  const canonical = canonicalJobStatus(job.status);
  const optionsHtml = JOB_STATUS_CANONICAL.map(
    (value) =>
      `<option value="${value}" ${canonical === value ? "selected" : ""}>${esc(JOB_STATUS_LABELS[value])}</option>`,
  ).join("");
  const match = job.match_score != null ? Math.round(job.match_score) : null;
  return `
    <article class="board-card copilot-card ${job.classification_pending ? "board-card--pending" : ""}" data-job-id="${job.job_id}" draggable="true" data-board-drag>
      <div class="board-card__top">
        ${match != null ? `<span class="match-badge ${matchTone(match)}" title="匹配度">${match}</span>` : `<span class="match-badge match-badge--empty" title="尚未分析">待分析</span>`}
        <button type="button" class="board-card__title" data-action="open-optimizer" data-id="${job.job_id}">${esc(job.title)}</button>
      </div>
      <div class="board-card__meta">${esc(job.company || "未知公司")} · ${esc(job.location || "未知城市")} · ${formatSalary(job)}</div>
      <div class="board-card__tags">
        <span class="badge badge-blue">${esc(job.job_function || "未分类")}</span>
        <span class="badge badge-gray">${esc(job.seniority || "未知")}</span>
        ${job.classification_pending ? '<span class="badge badge-amber badge-pending">分类待定</span>' : ""}
        ${job.alignment_status === "succeeded" ? '<span class="badge badge-green">已对齐</span>' : ""}
      </div>
      <div class="board-card__timeline">
        ${job.applied_at ? `<span class="small muted">投递 ${esc(job.applied_at)}</span>` : ""}
        ${job.next_step ? `<span class="small muted">下一步：${esc(job.next_step)}</span>` : ""}
      </div>
      <div class="row" style="margin-top:8px">
        <select class="board-status-select" data-board-status data-id="${job.job_id}" aria-label="移动状态">${optionsHtml}</select>
        <button class="btn btn-ghost btn-sm" data-action="open-optimizer" data-id="${job.job_id}">工作台</button>
        <button class="btn btn-danger btn-sm" data-action="delete-job" data-id="${job.job_id}">删除</button>
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
  return `
    <article class="board-card ${job.classification_pending ? "board-card--pending" : ""}" data-job-id="${job.job_id}">
      <div class="board-card__top">
        <label class="board-check"><input type="checkbox" data-board-check value="${job.job_id}" aria-label="选择 ${esc(job.title)}"><span></span></label>
        <button type="button" class="board-card__title" data-action="open-job-detail" data-id="${job.job_id}">${esc(job.title)}</button>
      </div>
      <div class="board-card__meta">${esc(job.company || "未知公司")} · ${esc(job.location || "未知城市")} · ${formatSalary(job)}</div>
      <div class="board-card__tags">
        <span class="badge badge-blue">${esc(job.job_function || "未分类")}</span>
        <span class="badge badge-gray">${esc(job.seniority || "未知")}</span>
        ${job.classification_pending ? '<span class="badge badge-amber badge-pending">分类待定</span>' : ""}
      </div>
      <div class="board-card__timeline">
        ${job.applied_at ? `<span class="small muted">投递 ${esc(job.applied_at)}</span>` : ""}
        ${job.next_step ? `<span class="small muted">下一步：${esc(job.next_step)}</span>` : ""}
      </div>
      <div class="row" style="margin-top:8px">
        <select class="board-status-select" data-board-status data-id="${job.job_id}" aria-label="移动状态">${statusOptions}</select>
        <button class="btn btn-ghost btn-sm" data-action="open-workspace" data-id="${job.job_id}">工作台</button>
        <button class="btn btn-ghost btn-sm" data-action="edit-job" data-id="${job.job_id}">编辑</button>
        <button class="btn btn-danger btn-sm" data-action="delete-job" data-id="${job.job_id}">删除</button>
      </div>
    </article>`;
}

/* ------------------------------------------------------------------ */
/* Appraisal panel: provenance / detail HTML, benchmark badge, radar   */
/* ------------------------------------------------------------------ */

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

/* Pure core of buildWbResultHtml: same HTML output, but the workbench
 * state (original content + compare view) is passed in explicitly. */
export function buildWbResultHtmlFrom(result, diffs, accepted, originalContent, compareView) {
  const sections = (result.tailored_resume || {}).sections || {};
  const optimizedText =
    Object.values(sections).join("\n\n") || result.tailored_resume || "";
  const originalText = originalContent || "";
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
  const proposedIndex = new Map();
  const removeIndex = new Map();
  diffs.forEach((diff, index) => {
    const orig = String(diff.original || "").trim();
    const prop = String(diff.proposed || "").trim();
    if (diff.type === "modify") {
      if (orig) modifyOriginal.add(orig);
      if (prop) modifyProposed.add(prop);
    }
    if (diff.type !== "remove" && prop) proposedIndex.set(prop, index);
    if (diff.type === "remove" && orig) removeIndex.set(orig, index);
  });
  const originalHtml =
    String(originalText)
      .split("\n")
      .map((line) => {
        const trimmed = line.trim();
        const changed = removedLines.has(trimmed) || modifyOriginal.has(trimmed);
        return `<div class="cmp-line ${changed ? "diff-remove" : ""}">${changed ? "−" : ""}${esc(line)}</div>`;
      })
      .join("") || '<div class="muted small">原版内容不可用</div>';
  const optimizedHtml =
    optimizedText
      .split("\n")
      .map((line) => {
        const trimmed = line.trim();
        if (!trimmed) return '<div class="cmp-line">&nbsp;</div>';
        const changed = addedLines.has(trimmed) || modifyProposed.has(trimmed);
        return `<div class="cmp-line ${changed ? "diff-add" : ""}">${changed ? "＋" : ""}${esc(line)}</div>`;
      })
      .join("") || '<div class="muted small">暂无优化内容</div>';
  const sideView = `
    <div class="cmp-grid cmp-grid--workbench">
      <section class="cmp-column-wrap"><h4>原版</h4><div class="cmp-column motion-stagger">${originalHtml}</div></section>
      <section class="cmp-column-wrap"><h4>优化版</h4><div class="cmp-column motion-stagger">${optimizedHtml}</div></section>
    </div>`;
  const diffCards = diffs
    .map(
      (diff, index) => `
      <div class="card diff-card card-base card-hover-soft">
        <div class="row" style="align-items:flex-start">
          <label class="cmp-check"><input type="checkbox" data-accept-diff="${index}" ${accepted.has(index) ? "" : "checked"} aria-label="采纳此条"><span class="small">采纳</span></label>
          <span class="badge badge-${diff.type === "add" ? "green" : diff.type === "remove" ? "red" : "blue"}">${esc(diff.type)}</span>
          <span class="small muted">${esc(diff.reason || "")} · ${esc(diff.confidence || "")}</span>
        </div>
        ${diff.type !== "add" ? `<div class="diff-line diff-remove">- ${esc(diff.original)}</div>` : ""}
        ${diff.type !== "remove" ? `<div class="diff-line diff-add">+ ${esc(diff.proposed)}</div>` : ""}
        ${renderWbProvenance(diff)}
        <div class="row" style="margin-top:8px">
          <button class="btn btn-secondary btn-sm" data-action="regenerate-diff" data-index="${index}">重新生成</button>
        </div>
      </div>`,
    )
    .join("");
  const score = result.score ?? "—";
  const ringClass =
    score >= 80
      ? "score-ring--high"
      : score >= 60
        ? "score-ring--mid"
        : "score-ring--low";
  return `
    <div class="wb-level">
      <div class="wb-score-row">
        <div class="score-ring ${ringClass}" style="--score:${esc(score)}"><span>${esc(score)}</span></div>
        <div>
          <span class="badge badge-green">已完成</span>
          <div class="small muted" style="margin-top:4px">总分 ${esc(score)} / 100 · ${esc(result.model || "—")} · ${esc(result.elapsed_seconds ?? 0)}s</div>
        </div>
      </div>
      <div class="row">
        <button class="btn btn-primary btn-sm" data-action="print-workbench">导出 PDF</button>
        <button class="btn btn-secondary btn-sm" data-action="export-markdown">导出 Markdown</button>
        <button class="btn btn-outline btn-sm" data-action="export-json">导出 JSON</button>
      </div>
    </div>
    <div class="segmented segmented-card" role="group" aria-label="结果视图">
      <button type="button" class="segmented-button" data-action="toggle-wb-view" data-wb-view="side" aria-pressed="${compareView === "side"}">并排对比</button>
      <button type="button" class="segmented-button" data-action="toggle-wb-view" data-wb-view="list" aria-pressed="${compareView === "list"}">修改列表</button>
    </div>
    ${compareView === "side" ? sideView : ""}
    <div class="wb-level">
      <h4>逐条修改（${diffs.length}）</h4>
      <div class="card-list motion-stagger">${diffCards || '<div class="muted small">无修改项</div>'}</div>
      <div class="row" style="margin-top:10px"><button class="btn btn-primary" data-action="accept-diffs">采纳选中修改</button></div>
    </div>
    <div class="wb-level">
      <h4>分析详情</h4>
      ${buildWbDetailHtml(result, diffs)}
    </div>
    <div data-accept-result></div>`;
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
