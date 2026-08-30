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

/* Attribute-safe alias kept near esc so inline HTML builders can document
 * that values are going inside double-quoted attributes, not element text. */
export function escAttr(value) {
  return esc(value);
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

/* P1-2: 岗位卡状态下拉与筛选/编辑同源 —— 标签取自设置词表
 * （vocabularyList("statuses")），不再硬编码渲染 JOB_STATUS_LABELS。
 * 实现为「按 canonical 合并」：词表每项是内建五态的中文标签，按
 * JOB_STATUS_ALIASES 归并到 canonical；option 恒为五个 canonical key
 * （保证状态机完整与后端 _validate_status 校验），词表缺项/子集/新增
 * 标签回退内建标签（设置侧「仅改名不增删」约束尚未在后端强制——子集
 * 目前可通过校验，故不能逐字渲染词表，否则会把五态缩成子集）。 */
export function jobStatusOptionsHtml(statuses, selectedCanonical) {
  const labelByCanonical = {};
  if (Array.isArray(statuses)) {
    for (const label of statuses) {
      const key = JOB_STATUS_ALIASES[label] || null;
      if (key) labelByCanonical[key] = label;
    }
  }
  return JOB_STATUS_CANONICAL.map((value) => {
    const label = labelByCanonical[value] || JOB_STATUS_LABELS[value];
    return `<option value="${esc(value)}" ${selectedCanonical === value ? "selected" : ""}>${esc(label)}</option>`;
  }).join("");
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
export function renderA4PaperHtml(draft = "") {
  const text = String(draft || "").trim();
  if (!text) {
    return `<div class="a4-paper a4-paper--empty" data-a4-paper role="article" aria-label="A4 定稿预览">
      <div class="a4-paper__empty">
        <div class="a4-paper__empty-title">还没有定稿简历</div>
        <p class="small muted">运行对齐并采纳建议后，这里会以 A4 纸样式预览定稿。</p>
      </div>
    </div>`;
  }
  return `<div class="a4-paper" data-a4-paper role="article" aria-label="A4 定稿预览">
    <div class="a4-paper__doc resume-doc">${renderMarkdown(text)}</div>
  </div>`;
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

const ROUTE_NAMES = ["resume", "resumes", "jobs", "workspace", "settings", "dashboard", "today"];

/* UX 走查 P1-A（2026-08-28）：裸 #/resumes 归一化为列表哨兵，与
 * #/resume/list 等价出列表；#/resume/<id> 才进单份档案。 */
export const RESUME_LIST_SENTINEL = "list";

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
  /* "resumes" 是 "resume" 的复数路由别名（蓝图契约 #/resumes）：裸 #/resumes
     归一化为列表哨兵（UX 走查 P1-A）。带 id 的路径已在上方分支返回。 */
  if (parts[0] === "resumes") {
    return { name: "resume", jobId: null, resumeId: RESUME_LIST_SENTINEL };
  }
  const name = ROUTE_NAMES.includes(parts[0]) ? parts[0] : "resume";
  return { name, jobId: null, resumeId: resumeFromQuery };
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

/* Ordered, line-level LCS diff used by the document-polishing inline view.
 * `lineDiff` above is intentionally kept as the cheaper set-based helper for
 * backwards-compatible callers; this variant preserves line order so inserted
 * and removed lines do not get flattened to the end of the document. */
function lineDiffOrdered(original, proposed) {
  const originalLines = String(original || "").split("\n");
  const proposedLines = String(proposed || "").split("\n");
  const m = originalLines.length;
  const n = proposedLines.length;
  const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));

  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[i][j] =
        originalLines[i] === proposedLines[j]
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const rows = [];
  let i = 0;
  let j = 0;
  while (i < m && j < n) {
    if (originalLines[i] === proposedLines[j]) {
      rows.push({ type: "same", text: originalLines[i] });
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      rows.push({ type: "remove", text: originalLines[i] });
      i += 1;
    } else {
      rows.push({ type: "add", text: proposedLines[j] });
      j += 1;
    }
  }
  while (i < m) rows.push({ type: "remove", text: originalLines[i++] });
  while (j < n) rows.push({ type: "add", text: proposedLines[j++] });
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
  { key: "classify", label: "分类" },
  { key: "profile", label: "JD 画像" },
  { key: "gap", label: "差距" },
  { key: "align", label: "对齐" },
];

export const PROVENANCE_LABELS = {
  verified: "高可信",
  ambiguous: "建议复核",
  missing: "待确认",
  pending_review: "建议复核",
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
  /* 简历优化（xzjobs 式）：overview = 本地整体分析，polishing = 模块润色 */
  overview: "整体分析",
  polishing: "模块化润色",
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
  const jd = (session && session.jd) || {};
  const gap = (session && session.gap) || {};
  const alignment = (session && session.alignment) || {};
  const done = new Set();
  if (jd.status === "ready") done.add("classify");
  if (jd.status === "ready") done.add("profile");
  if (gap.status === "ready" || gap.status === "blocked") done.add("gap");
  if (alignment.status === "succeeded") done.add("align");
  return STAGE_STEPS.map((step) => ({
    ...step,
    active:
      !done.has(step.key) &&
      ((step.key === "classify" && jd.status === "queued") ||
        (step.key === "profile" && jd.status === "queued") ||
        (step.key === "gap" && gap.status === "queued")),
    done: done.has(step.key),
  }));
}

/* Compact, live micro-pipeline for the workbench aux drawer. It reads the
 * same SSE-updated session state as the main canvas, so no second polling
 * channel or backend schema change is required. */
export function workbenchProgressPipelineHtml(session) {
  const jd = (session && session.jd) || {};
  const gap = (session && session.gap) || {};
  const alignment = (session && session.alignment) || {};

  const profile = jd.profile || {};
  const requiredSkills = Array.isArray(profile.must_have_skills)
    ? profile.must_have_skills
    : Array.isArray(profile.required_skills)
      ? profile.required_skills
      : [];
  const niceSkills = Array.isArray(profile.nice_to_have_skills)
    ? profile.nice_to_have_skills
    : [];
  const scenarios = Array.isArray(profile.business_scenarios)
    ? profile.business_scenarios
    : [];
  const missingGaps = (gap.gap_report && gap.gap_report.missing_keywords) || [];
  const diffs = alignment.diffs || [];

  const alignmentRunning = ["queued", "running"].includes(alignment.status);
  const liveMessage = alignmentRunning
    ? alignment.message || ""
    : alignment.status === "succeeded"
      ? "简历对齐已完成"
      : "";

  const steps = [
    {
      key: "profile",
      label: "JD 画像",
      detail:
        requiredSkills.length || niceSkills.length || scenarios.length
          ? `已萃取 ${requiredSkills.length + niceSkills.length} 项技能 · ${scenarios.length} 类场景`
          : "",
      done: jd.status === "ready" && Boolean(jd.profile),
      active: ["queued", "running"].includes(jd.status),
    },
    {
      key: "gap",
      label: "差距分析",
      detail: missingGaps.length
        ? `已定位 ${missingGaps.length} 处能力缺口`
        : "",
      done: ["ready", "blocked"].includes(gap.status),
      active: gap.status === "queued" || gap.status === "running",
    },
    {
      key: "tailor",
      label: "STAR 精修",
      detail: diffs.length ? `已生成 ${diffs.length} 条精修建议` : "",
      done: alignment.status === "succeeded",
      active: ["queued", "running"].includes(alignment.status),
    },
  ];

  return `
    <div class="workbench-live-progress" data-workbench-live-progress aria-live="polite">
      ${liveMessage ? `<div class="workbench-live-progress__message" data-workbench-live-progress-message>${esc(liveMessage)}</div>` : ""}
      ${steps
        .map(
          (step) => `
        <div class="workbench-live-progress__step ${step.done ? "is-done" : ""} ${step.active ? "is-active" : ""}" data-progress-step="${esc(step.key)}">
          <span class="workbench-live-progress__dot" aria-hidden="true">${step.done ? ICON_PROGRESS_CHECK : step.active ? "…" : "·"}</span>
          <div class="workbench-live-progress__copy">
            <span class="workbench-live-progress__label">${esc(step.label)}</span>
            ${step.detail ? `<span class="workbench-live-progress__detail">${esc(step.detail)}</span>` : ""}
          </div>
        </div>`,
        )
        .join("")}
    </div>`;
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

/* UX 走查 P2-A（2026-08-28）：简历列表卡不再渲染整份 Markdown（160px 滚动盒
 * 扫描成本过高），改为首段纯文本摘要 + 全文字数提示。 */
export function resumeListPreview(content, max = 120) {
  const raw = String(content || "");
  const firstParagraph =
    raw
      .split(/\n{2,}/)
      .map((part) => part.trim())
      .find((part) => part && !part.startsWith("#")) || "";
  const flat = firstParagraph.replace(/\s+/g, " ").trim();
  const preview = flat.length > max ? `${flat.slice(0, max)}…` : flat;
  const totalChars = raw.replace(/\s+/g, "").length;
  if (!preview) return `（暂无内容 · 共 ${totalChars} 字）`;
  return totalChars > max ? `${preview}（全文约 ${totalChars} 字）` : preview;
}

/* UX 走查 P2-B（2026-08-28）：LLM 抽取的缺口项可能是整句长文（如基线报告的
 * 第 7 项一整句），直接渲染成巨型 tag。展示层统一短语化截断（完整原文保留
 * 在 title 提示里），不改动数据层。 */
const GAP_PHRASE_MAX = 40;

export function shortenGapPhrase(text, max = GAP_PHRASE_MAX) {
  const flat = String(text || "").replace(/\s+/g, " ").trim();
  if (flat.length <= max) return flat;
  return `${flat.slice(0, max)}…`;
}

export function renderGap(gap) {
  if (!gap) return null;
  const missing = gap.missing_keywords || [];
  const strengths = gap.strength_matches || [];
  const misaligned = gap.misaligned_emphasis || [];
  const gapTag = (item, extra = "") =>
    `<span class="gap-tag${extra}" title="${esc(item)}">${esc(shortenGapPhrase(item))}</span>`;
  const blocks = [];
  if (missing.length) {
    blocks.push(`
      <div class="gap-group gap-group--missing">
        <div class="split-section-title">差距项</div>
        <div class="gap-tags">${missing.map((item) => gapTag(item)).join("")}</div>
      </div>`);
  }
  if (strengths.length) {
    blocks.push(`
      <div class="gap-group gap-group--strength">
        <div class="split-section-title">已有匹配</div>
        <div class="gap-tags">${strengths.map((item) => gapTag(item, " gap-tag--ok")).join("")}</div>
      </div>`);
  }
  if (misaligned.length) {
    blocks.push(`
      <div class="gap-group gap-group--warn">
        <div class="split-section-title">错位强调</div>
        <div class="gap-tags">${misaligned.map((item) => gapTag(item, " gap-tag--warn")).join("")}</div>
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

/* ADR-0033 决策9：emoji 全部替换为 16px 线性 SVG 图标（紧凑场景用 --sm 变体）。 */
const ICON_CHECK = '<svg class="ic ic--sm" viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m3 8.5 3.2 3L13 4.5"/></svg>';
const ICON_X = '<svg class="ic ic--sm" viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m4 4 8 8"/><path d="m12 4-8 8"/></svg>';
const ICON_WARN = '<svg class="ic" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2.2 14.3 13H1.7L8 2.2z"/><path d="M8 6.3v3.2"/><path d="M8 11.6v.1"/></svg>';
const ICON_PROGRESS_CHECK = '<svg viewBox="0 0 16 16" width="10" height="10" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m3 8.5 3.2 3L13 4.5"/></svg>';

/* 来源徽标内联图标：verified=盾牌，其余=警示三角。 */
function provenanceBadgeIcon(stateKey) {
  if (stateKey === "verified") {
    return '<svg class="provenance-icon" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 1.8 13 3.6v4.1c0 3.2-2.1 5.6-5 6.5-2.9-.9-5-3.3-5-6.5V3.6L8 1.8z"/><path d="m5.8 8 1.5 1.5 2.9-3"/></svg>';
  }
  return '<svg class="provenance-icon" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2.2 14.3 13H1.7L8 2.2z"/><path d="M8 6.3v3.2"/><path d="M8 11.6v.1"/></svg>';
}

export function diffCard(diff, index, jobId) {
  const diffId = diff.diff_id || `diff-${index}`;
  const type = diff.type || "modify";
  const provenance = diff.provenance || diff.provenance_quote || "";
  const stateKey = diff.provenance_state || "pending_review";
  const label = PROVENANCE_LABELS[stateKey] || "来源待核对";
  const noProvenance = !String(provenance || "").trim();
  const invalid =
    stateKey === "missing" ||
    (type === "add" && noProvenance && stateKey !== "verified");
  const invalidWarning = invalid
    ? type === "add" && noProvenance
      ? "该条为无来源新增，已作为硬门禁拦截，待人工复核。"
      : "缺少来源，已作为硬门禁拦截，待人工复核。"
    : "";
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
        <span class="provenance-badge provenance-badge--${esc(stateKey)}" data-provenance title="${esc(provenance)}">${provenanceBadgeIcon(stateKey)}<span>${esc(label)}</span></span>
      </div>
      <div class="diff-card__columns">
        <div class="diff-card__col diff-card__col--original">
          <div class="split-section-title">原文</div>
          <div class="diff-card__text" data-diff-original>${originalHtml}</div>
        </div>
        <div class="diff-card__col diff-card__col--proposed">
          <div class="split-section-title">建议修改</div>
          <div class="diff-card__text" data-diff-proposed>${proposedHtml}</div>
        </div>
      </div>
      ${diff.reason ? `<div class="diff-card__reason" data-diff-reason>${esc(diff.reason)}</div>` : ""}
      ${provenance ? `<div class="provenance-quote">${esc(provenance)}</div>` : ""}
      ${invalidWarning ? `<div class="diff-card__warning" role="alert">${esc(invalidWarning)}</div>` : ""}
      <div class="diff-card__actions" data-diff-actions>
        ${invalid ? "" : `<button class="btn btn-primary btn-sm" data-action="accept-bullet" data-id="${esc(jobId)}" data-diff-id="${esc(diffId)}">${ICON_CHECK} 采纳</button>`}
        <button class="btn btn-ghost btn-sm" data-action="reject-bullet" data-id="${esc(jobId)}" data-diff-id="${esc(diffId)}">${ICON_X} 跳过</button>
        <button class="btn btn-secondary btn-sm" data-action="polish-bullet" data-id="${esc(jobId)}" data-diff-id="${esc(diffId)}" data-instruction="quantified">${invalid ? "↻ 重试此条" : "AI 润色"}</button>
        ${invalid ? "" : `<button class="btn btn-ghost btn-sm" data-action="toggle-bullet-edit" data-id="${esc(jobId)}" data-diff-id="${esc(diffId)}">✏️ 编辑</button>`}
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
    /* P0-2: 失败/取消/过期态不再渲染「还没有对齐结果」首次引导卡 —— 失败反馈
     * 收敛到顶部错误横幅 + 顶栏危险级「重新运行对齐」单入口，避免同屏 3 个
     * 对齐入口、2 套标签（2026-08-25 走查实测的失败态三入口问题）。 */
    if (["failed", "canceled", "expired"].includes(alignment.status)) {
      return '<div class="diff-card-list" data-diff-list></div>';
    }
    return `
      <div class="resume-empty" data-resume-canvas-empty>
        <div class="resume-empty__title">还没有对齐结果</div>
        <ol class="resume-empty__steps">
          <li>在右侧「优化设置」中选择主简历</li>
          <li>点击上方「开始对齐」开始分析</li>
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
        <button class="btn btn-outline btn-sm" type="button" data-action="cancel-align-job" ${running ? "" : "hidden"}>${alignment.status === "queued" ? "取消任务" : "停止等待"}</button>
        <button class="btn btn-ghost btn-sm" type="button" data-action="apply-accepted-bullets" data-id="${esc(jobId)}" ${!alignment.draft ? "disabled" : ""}>应用已${ICON_CHECK} 采纳</button>
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

export function exportDock(jobId, job = {}) {
  const hasFinal = Boolean(job && job.final_draft);
  const hasDraft = Boolean(
    job && (job.final_draft || job.draft || (job.alignment && job.alignment.draft)),
  );
  const finalDisabled = hasFinal ? "" : " disabled title=\"请先保存定稿\"";
  const statusBadge = hasFinal
    ? `<span class="badge badge-green" data-export-final-badge>已定稿 v${Number(job.final_draft_version) || 1}</span>`
    : hasDraft
      ? '<span class="badge badge-amber" data-export-draft-badge>草稿</span>'
      : "";
  return `
    <details class="export-dock" data-export-dock>
      <summary class="btn btn-secondary btn-sm export-dock__trigger">导出 ▾</summary>
      <div class="export-dock__menu">
        <button class="btn btn-secondary btn-sm" type="button" data-action="export-final-draft" data-id="${esc(jobId)}"${finalDisabled}>导出 PDF</button>
        <button class="btn btn-secondary btn-sm" type="button" data-action="export-final-draft-md" data-id="${esc(jobId)}"${finalDisabled}>导出 Markdown</button>
        <button class="btn btn-outline btn-sm" type="button" data-action="export-final-draft-json" data-id="${esc(jobId)}"${finalDisabled}>导出 JSON</button>
        ${statusBadge}
        ${hasDraft && !hasFinal ? '<span class="small muted" data-export-final-hint>请先保存定稿</span>' : ""}
      </div>
    </details>`;
}

function boardMoreMenu(job) {
  const id = esc(job.job_id);
  return `
    <details class="board-more" aria-label="更多操作">
      <summary class="board-more__trigger" aria-label="更多操作" title="更多操作">···</summary>
      <div class="board-more__menu">
        <button class="btn btn-ghost btn-sm" type="button" data-action="open-job-followup" data-id="${id}">安排跟进</button>
        <button class="btn btn-ghost btn-sm" type="button" data-action="open-job-timeline" data-id="${id}">详情</button>
        <button class="btn btn-ghost btn-sm" type="button" data-action="edit-job" data-id="${id}">编辑</button>
        <button class="btn btn-danger btn-sm" type="button" data-action="delete-job" data-id="${id}">删除</button>
      </div>
    </details>`;
}

const MATCH_DIMENSIONS = [
  { key: "hard_skills", label: "硬技能" },
  { key: "scenario", label: "场景" },
  { key: "expression", label: "表达" },
  { key: "experience", label: "经验" },
];

function matchDimensionHtml(detail) {
  return MATCH_DIMENSIONS.map(({ key, label }) => {
    const raw = detail[key];
    const num = raw == null || raw === "" ? Number.NaN : Number(raw);
    const value = Number.isFinite(num) ? Math.round(Math.max(0, Math.min(100, num))) : null;
    const width = value == null ? 0 : value;
    return `
      <div class="match-dim" data-match-dimension="${key}">
        <span>${label}</span>
        <div class="match-dim__track"><i style="width:${width}%"></i></div>
        <b>${value == null ? "—" : value}</b>
      </div>`;
  }).join("");
}

function boardMatchBlock(job) {
  const detail = job.match_score_detail;
  const match = job.match_score != null ? Math.round(job.match_score) : null;
  const reason = String(job.match_reason || "").trim();
  const source = job.match_reason_source;
  const stale = job.match_stale === true;
  const hasDetail = detail && typeof detail === "object";
  if (!hasDetail && match == null && !reason && !stale) return "";
  const parts = [];
  if (hasDetail) {
    parts.push(`<div class="board-match__dims">${matchDimensionHtml(detail)}</div>`);
  } else if (match != null) {
    parts.push('<div class="board-match__legacy" data-match-legacy>旧版匹配分</div>');
  }
  parts.push(`
    <div class="board-match__reason" data-match-reason>
      <span>${esc(reason || "暂无推荐理由")}</span>
      ${source === "fallback" ? '<span class="badge badge-gray" data-match-source="fallback">规则理由</span>' : source === "llm" ? '<span class="badge badge-blue" data-match-source="llm">AI 理由</span>' : ""}
    </div>`);
  if (stale) {
    parts.push(`
      <div class="board-match__stale">
        <span class="badge badge-amber" data-match-stale title="岗位或主简历已变化，需重新评分">匹配已过期</span>
        <button type="button" class="btn btn-outline btn-sm" data-action="recompute-match" data-id="${esc(job.job_id)}">重新评分</button>
      </div>`);
  }
  return `<div class="board-match" data-match-block>${parts.join("")}</div>`;
}

export function boardCard(job, statuses = null) {
  const canonical = canonicalJobStatus(job.status);
  const optionsHtml = jobStatusOptionsHtml(statuses, canonical);
  const match = job.match_score != null ? Math.round(job.match_score) : null;
  /* #F10: job.match_score persists the last workbench eval result, so the
   * badge title discloses the score origin instead of a bare "匹配度". */
  const matchTitle = match != null ? "匹配度 · 来自 AI 评估" : "尚未分析";
  return `
    <article class="board-card copilot-card ${job.classification_pending ? "board-card--pending" : ""}" data-job-id="${job.job_id}" draggable="true" data-board-drag>
      <div class="board-card__top">
        <label class="board-check"><input type="checkbox" data-board-check value="${job.job_id}" aria-label="选择 ${esc(job.title)}"><span></span></label>
        ${match != null ? `<span class="match-badge ${matchTone(match)}" data-match-total title="${matchTitle}">${match}</span>` : `<span class="match-badge match-badge--empty" title="${matchTitle}">待分析</span>`}
        <button type="button" class="board-card__title" data-action="open-optimizer" data-id="${job.job_id}">${esc(job.title)}</button>
        ${boardMoreMenu(job)}
      </div>
      <div class="board-card__meta">${esc(job.company || "未知公司")} · ${esc(job.location || "未知城市")} · ${formatSalary(job)}</div>
      ${boardMatchBlock(job)}
      <div class="board-card__tags">
        <span class="badge badge-blue">${esc(job.job_function || "未分类")}</span>
        <span class="badge badge-gray">${esc(job.seniority || "未知")}</span>
        ${jobCompletenessBadge(job)}
        ${job.classification_pending ? `<button type="button" class="badge badge-amber badge-pending" data-action="reclassify-job" data-id="${esc(job.job_id)}" aria-label="重新分类">分类待定</button>` : ""}
        ${job.alignment_status === "succeeded" ? '<span class="badge badge-green">已对齐</span>' : ""}
        ${job.alignment_status === "failed" ? `<span class="badge badge-red" title="${esc(job.last_alignment_error || "对齐失败，请到工作台重新运行")}">对齐失败</span>` : ""}
        ${job.alignment_status === "succeeded" && !(job.diffs || []).length ? '<span class="badge badge-amber" title="本次对齐未产出修改建议，可到工作台重新运行">无建议</span>' : ""}
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

export function renderBoardCard(job, statuses = null) {
  const canonical = canonicalJobStatus(job.status);
  const statusOptions = jobStatusOptionsHtml(statuses, canonical);
  const match = job.match_score != null ? Math.round(job.match_score) : null;
  const matchTitle = match != null ? "匹配度 · 来自 AI 评估" : "尚未分析";
  return `
    <article class="board-card ${job.classification_pending ? "board-card--pending" : ""}" data-job-id="${job.job_id}">
      <div class="board-card__top">
        <label class="board-check"><input type="checkbox" data-board-check value="${job.job_id}" aria-label="选择 ${esc(job.title)}"><span></span></label>
        ${match != null ? `<span class="match-badge ${matchTone(match)}" data-match-total title="${matchTitle}">${match}</span>` : `<span class="match-badge match-badge--empty" title="${matchTitle}">待分析</span>`}
        <button type="button" class="board-card__title" data-action="open-job-timeline" data-id="${job.job_id}">${esc(job.title)}</button>
        ${boardMoreMenu(job)}
      </div>
      <div class="board-card__meta">${esc(job.company || "未知公司")} · ${esc(job.location || "未知城市")} · ${formatSalary(job)}</div>
      ${boardMatchBlock(job)}
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
 * Shared by the live canvas 对比视图 modal (#17): line-level semantics are
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

/**
 * 文档润色范式：把左右分栏对比压成单文档的内联建议流。
 * 删除内容灰化划掉，新增内容用品牌淡蓝底，修改内容在建议侧标蓝。
 * 保留 data-line 可寻址语义供测试和辅助面板使用。
 */
export function buildInlineSuggestionHtml(originalText, optimizedText, diffs) {
  const diffItems = Array.isArray(diffs) ? diffs : [];
  const sourceText = String(originalText || "");
  const targetText = String(optimizedText || "");

  if (!sourceText.trim() && !targetText.trim() && !diffItems.length) {
    return `
      <div class="inline-suggestion" data-inline-suggestion>
        <div class="muted small">暂无文档内容。请先运行一次优化生成建议。</div>
      </div>`;
  }

  const modifyByOriginal = new Map();
  const modifyByProposed = new Map();
  const removeByOriginal = new Map();
  const addByProposed = new Map();

  diffItems.forEach((diff, index) => {
    const original = String(diff.original || "").trim();
    const proposed = String(diff.proposed || "").trim();
    const meta = {
      diffId: String(diff.diff_id || `inline-diff-${index}`),
      reason: diff.reason || "",
      provenance: diff.provenance || diff.provenance_quote || "",
      confidence: diff.confidence != null ? String(diff.confidence) : "",
    };

    if (diff.type === "modify" && original && proposed) {
      if (!modifyByOriginal.has(original)) modifyByOriginal.set(original, []);
      if (!modifyByProposed.has(proposed)) modifyByProposed.set(proposed, []);
      modifyByOriginal.get(original).push({ proposed, ...meta });
      modifyByProposed.get(proposed).push({ original, ...meta });
    } else if (diff.type === "remove" && original) {
      removeByOriginal.set(original, meta);
    } else if (diff.type === "add" && proposed) {
      addByProposed.set(proposed, meta);
    }
  });

  const segments = lineDiffOrdered(sourceText, targetText);
  const html = [];
  let index = 0;

  const pushPlain = (text) => {
    const content = text === "" ? "&nbsp;" : esc(text);
    html.push(
      `<div class="inline-suggestion__line" data-inline-line="${index}">${content}</div>`,
    );
    index += 1;
  };

  const pushSuggestion = (type, original, proposed, meta) => {
    const data = meta
      ? `${type === "modify"
          ? `data-diff-original="${escAttr(original)}" data-diff-proposed="${escAttr(proposed)}"`
          : ""} data-diff-id="${escAttr(meta.diffId)}" data-reason="${escAttr(meta.reason)}" data-provenance="${escAttr(meta.provenance)}" data-confidence="${escAttr(meta.confidence)}"`
      : "";
    const content =
      type === "modify"
        ? renderInlineCombined(original, proposed)
        : type === "remove"
          ? esc(original)
          : esc(proposed);
    html.push(
      `<div class="inline-suggestion__line inline-suggestion__line--${type}" data-inline-line="${index}" data-inline-suggestion type="${type}" ${data}>${content}</div>`,
    );
    index += 1;
  };

  for (let pos = 0; pos < segments.length; pos++) {
    const row = segments[pos];
    if (row.type === "same") {
      pushPlain(row.text);
      continue;
    }

    if (row.type === "remove" && segments[pos + 1] && segments[pos + 1].type === "add") {
      const original = row.text;
      const proposed = segments[pos + 1].text;
      const trimmedOriginal = original.trim();
      const trimmedProposed = proposed.trim();
      const candidates = modifyByOriginal.get(trimmedOriginal) || [];
      const match = candidates.find((item) => item.proposed === trimmedProposed);
      if (match) {
        pushSuggestion("modify", original, proposed, match);
        pos += 1;
        continue;
      }
    }

    if (row.type === "remove") {
      const meta = removeByOriginal.get(row.text.trim());
      pushSuggestion("remove", row.text, "", meta);
      continue;
    }

    const meta = addByProposed.get(row.text.trim());
    pushSuggestion("add", "", row.text, meta);
  }

  const body =
    html.join("") ||
    `<div class="muted small">暂无文档内容。请先运行一次优化生成建议。</div>`;

  return `
    <div class="inline-suggestion" data-inline-suggestion>
      <div class="inline-suggestion__paper motion-stagger">${body}</div>
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
          <span class="small muted">后端不抓取链接：请粘贴 JD 文本，或用油猴插件入库</span>
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

/* Render both sides of an inline diff in one document line. Deleted tokens
 * stay struck through, inserted tokens get the brand-blue suggestion wash; the
 * unchanged surrounding text remains plain. */
export function renderInlineCombined(original, proposed) {
  return inlineDiff(original, proposed)
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
/* #11 New-user onboarding steps (pure)                                */
/* ------------------------------------------------------------------ */
/* DOM-free helpers for the three-step onboarding card (岗位库空态)。
 * Callers in main.js own the DOM mounting; these functions only derive
 * state and build HTML.
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

/* #26: 工作台定稿后的投递闭环引导。final_draft 生成后显示三步，
 * 记录投递完成前进到安排跟进；终态或已安排跟进视为全部完成。 */
export function workbenchGuideSteps(job, hasDraft = false) {
  const status = canonicalJobStatus(job && job.status);
  const applied = ["applied", "interview", "offer", "withdrawn"].includes(
    status,
  );
  const followedUp = Boolean(
    job &&
      (job.next_step_due_at || job.next_step || job.interview_stage),
  );
  const terminal = status === "offer" || status === "withdrawn";
  const savedDraft = Boolean(job && job.final_draft);
  return [
    {
      key: "draft",
      label: savedDraft ? "已生成定稿" : "已生成草稿",
      done: savedDraft,
    },
    { key: "record", label: "记录投递", done: applied },
    { key: "followup", label: "安排跟进", done: followedUp || terminal },
  ];
}

export function workbenchGuideHtml(job, hasDraft = false) {
  if (!job || !(job.final_draft || hasDraft)) return "";
  const steps = workbenchGuideSteps(job, hasDraft);
  const current = steps.find((step) => !step.done);
  const currentKey = current ? current.key : "";
  const action =
    currentKey === "record"
      ? `<button class="btn btn-primary btn-sm" type="button" data-action="record-application" data-id="${esc(job.job_id || "")}">记录投递</button>`
      : currentKey === "followup"
        ? `<button class="btn btn-primary btn-sm" type="button" data-action="open-job-followup" data-id="${esc(job.job_id || "")}">安排跟进</button>`
        : "";
  return `
    <div class="workbench-guide" data-workbench-guide data-guide-current="${esc(currentKey)}" role="region" aria-label="投递闭环引导">
      <div class="workbench-guide__steps">
        ${steps
          .map(
            (step, index) => `
          <span class="workbench-guide__step ${step.done ? "is-done" : ""} ${step.key === currentKey ? "is-current" : ""}" data-guide-step="${esc(step.key)}">${esc(step.label)}</span>
          ${index < steps.length - 1 ? '<span class="workbench-guide__arrow" aria-hidden="true">→</span>' : ""}`,
          )
          .join("")}
      </div>
      ${action ? `<div class="workbench-guide__actions">${action}</div>` : ""}
    </div>`;
}

export function workbenchPrimaryButtonHtml(
  resumes,
  alignmentRunning = false,
  alignment = null,
) {
  const hasResumes = Array.isArray(resumes) && resumes.length > 0;
  /* P0-2: 失败/取消/过期统一走危险级「重新运行对齐」单入口（顶栏）。 */
  const failed = Boolean(
    alignment &&
      ["failed", "canceled", "expired"].includes(alignment.status),
  );
  /* P0-2: 全站统一动词 —— 「开始优化」→「开始对齐」。 */
  let label = hasResumes ? "开始对齐" : "先创建主简历";
  let extraClass = "";
  if (hasResumes && alignmentRunning) {
    label = "对齐生成中...";
  } else if (hasResumes && failed) {
    /* Bug-09: 失败后主按钮给出明确的重试入口与警示样式。 */
    label = "重新运行对齐";
    /* R2 合议：失败态危险操作与「确认删除」同级，升级为红实底白字（btn-danger-solid）。 */
    extraClass = " btn-danger-solid";
  }
  return `<button class="btn btn-primary${extraClass}" type="button" data-action="${hasResumes ? "run-alignment" : "go-resumes"}" ${hasResumes && alignmentRunning ? "disabled" : ""}>${esc(label)}</button>`;
}

export function offerCelebrationHtml(job) {
  const status = canonicalJobStatus(job && job.status);
  if (status !== "offer") return "";
  const title = esc((job && job.title) || "你拿到了 Offer");
  const company = job && job.company ? ` · ${esc(job.company)}` : "";
  const colors = ["#f43f5e", "#f59e0b", "#10b981", "#3b82f6", "#a855f7"];
  const pieces = Array.from(
    { length: 28 },
    (_, i) =>
      `<span class="confetti confetti--${i % 6}" ` +
      `style="--d:${(i * 97) % 1200}ms;--x:${(i * 13) % 100}%;` +
      `--delay:${(i % 7) * 80}ms;--c:${colors[i % colors.length]}"` +
      `></span>`,
  ).join("");
  return (
    `<div class="offer-celebration" data-offer-celebration>` +
    `<div class="offer-celebration__confetti">${pieces}</div>` +
    `<div class="offer-celebration__card">` +
    `<strong>OFFER</strong><span>${title}${company}</span>` +
    `</div></div>`
  );
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
    return { score: Number(evalScore.jd_match_score), source: "来自 AI 评估" };
  }
  if (gap.score != null) {
    return { score: Number(gap.score), source: "来自能力分析" };
  }
  if (job && job.match_score != null) {
    return { score: Number(job.match_score), source: "来自 AI 评估" };
  }
  return { score: null, source: "" };
}

export function renderMatchBadge(session, job) {
  const { score, source } = matchBadgeInfo(session, job);
  if (score == null) return "";
  return `<span class="match-badge ${matchTone(score)}" data-match-badge title="${esc(source)}"><svg class="match-badge__icon" viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 1.8 13 3.6v4.1c0 3.2-2.1 5.6-5 6.5-2.9-.9-5-3.3-5-6.5V3.6L8 1.8z"/><path d="m5.8 8 1.5 1.5 2.9-3"/></svg>匹配 ${Math.round(score)}</span>${source ? `<span class="small muted" data-match-source>${esc(source)}</span>` : ""}`;
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

const SUBMITTED_JOB_STATUSES = new Set([
  "applied",
  "interview",
  "offer",
  "withdrawn",
]);

/* 岗位详情抽屉的投递快照区。created_at DESC 由后端排序；无快照的存量
 * 已投递岗位降级展示当前 final_draft，并明确标注“早期投递版本”。 */
export function applicationSnapshotsHtml(job, snapshots = []) {
  const items = (Array.isArray(snapshots) ? snapshots : [])
    .map((snapshot) => {
      const score =
        snapshot.match_score != null ? Math.round(snapshot.match_score) : "—";
      const appliedAt =
        snapshot.applied_at || formatDate(snapshot.created_at);
      return `<div class="snapshot-item" data-snapshot-item data-snapshot-id="${esc(snapshot.snapshot_id)}">
        <div class="snapshot-item__head">
          <strong>第 ${esc(snapshot.version_index)} 版投递快照</strong>
          <span class="small muted">${esc(appliedAt)}</span>
        </div>
        <div class="snapshot-item__meta">匹配度 ${esc(score)}${snapshot.master_resume_id ? ` · 主简历 ${esc(snapshot.master_resume_id)}` : ""}</div>
        <div class="row">
          <button type="button" class="btn btn-secondary btn-sm" data-action="open-snapshot" data-id="${esc(snapshot.snapshot_id)}">查看 Markdown</button>
          <button type="button" class="btn btn-ghost btn-sm" data-action="export-snapshot-md" data-id="${esc(snapshot.snapshot_id)}">下载 Markdown</button>
          <button type="button" class="btn btn-ghost btn-sm" data-action="export-snapshot-pdf" data-id="${esc(snapshot.snapshot_id)}">导出 PDF</button>
        </div>
      </div>`;
    })
    .join("");
  if (items) {
    return `${interviewCheatSheetHtml(job)}<div class="snapshot-section"><h4>投递快照</h4><div class="snapshot-list">${items}</div></div>`;
  }
  const canonical = canonicalJobStatus(job && job.status);
  if (
    SUBMITTED_JOB_STATUSES.has(canonical) &&
    job &&
    (job.final_draft || "").trim()
  ) {
    return `${interviewCheatSheetHtml(job)}<div class="snapshot-section snapshot-section--legacy" data-legacy-snapshot>
      <h4>投递快照</h4>
      <div class="snapshot-item snapshot-item--legacy">
        <p class="legacy-warning">${ICON_WARN} 早期投递版本（未生成不可篡改快照）</p>
        <p class="small muted">岗位已投递但尚无不可篡改快照，以下为当前 final_draft。</p>
        <div class="row">
          <button type="button" class="btn btn-secondary btn-sm" data-action="view-legacy-draft" data-id="${esc(job.job_id)}">查看当前定稿 Markdown</button>
          <button type="button" class="btn btn-ghost btn-sm" data-action="export-legacy-draft-md" data-id="${esc(job.job_id)}">下载 Markdown</button>
          <button type="button" class="btn btn-ghost btn-sm" data-action="export-legacy-draft-pdf" data-id="${esc(job.job_id)}">导出 PDF</button>
        </div>
      </div>
    </div>`;
  }
  return "";
}


/* ADR-0033 决策5：投递快照右侧抽屉正文。开发版带匹配度 pill、固化时间、
 * 防深挖卡与定稿正文预览；无快照的存量投递（entry.legacyDraft）降级为
 * legacy 形态，仍可下载/导出当前 final_draft。 */
export function snapshotDrawerHtml(snapshot, entry = {}) {
  const job = entry.job || {};
  const jobId = entry.jobId || (job && job.job_id) || "";
  const legacyDraft = (entry && entry.legacyDraft) || "";
  const isLegacy = !snapshot;
  const draft = isLegacy ? legacyDraft : snapshot.final_draft || "";
  const score =
    !isLegacy && snapshot.match_score != null
      ? Math.round(snapshot.match_score)
      : null;
  const createdAt =
    !isLegacy && snapshot.created_at != null
      ? formatDate(snapshot.created_at)
      : "";
  const meta = isLegacy
    ? ""
    : `${createdAt ? `固化时间 ${createdAt}` : snapshot.applied_at ? `投递时间 ${snapshot.applied_at}` : ""}${snapshot.version_index != null ? ` · 版本 v${esc(snapshot.version_index)}` : ""}`.trim();
  const cheatsheet = interviewCheatSheetHtml(job);
  const cheatsheetBlock = cheatsheet
    ? `<div class="snapshot-drawer__cheatsheet">${cheatsheet}</div>`
    : "";
  const actions = isLegacy
    ? `<div class="snapshot-drawer__actions">
        <button type="button" class="btn btn-secondary btn-sm" data-action="export-legacy-draft-md" data-id="${esc(jobId)}">下载 Markdown</button>
        <button type="button" class="btn btn-primary btn-sm" data-action="export-legacy-draft-pdf" data-id="${esc(jobId)}">导出 PDF</button>
      </div>`
    : `<div class="snapshot-drawer__actions">
        <button type="button" class="btn btn-secondary btn-sm" data-action="export-snapshot-md" data-id="${esc(snapshot.snapshot_id)}">下载 Markdown</button>
        <button type="button" class="btn btn-primary btn-sm" data-action="export-snapshot-pdf" data-id="${esc(snapshot.snapshot_id)}">导出 PDF</button>
      </div>`;
  if (isLegacy) {
    return `<div class="snapshot-drawer" data-snapshot-drawer data-snapshot-legacy>
      <p class="legacy-warning">${ICON_WARN} 早期投递版本（未生成不可篡改快照）</p>
      <p class="small muted">岗位已投递但尚无不可篡改快照，以下为当前 final_draft。</p>
      ${actions}
      ${cheatsheetBlock}
      <div class="snapshot-drawer__preview">
        <div class="snapshot-drawer__preview-title">定稿正文（预览）</div>
        <div class="resume-doc">${renderMarkdown(draft)}</div>
      </div>
    </div>`;
  }
  const matchPill =
    score != null
      ? `<span class="snapshot-drawer__match" data-snapshot-match>投递时匹配度 ${score} 分</span>`
      : `<span class="snapshot-drawer__match is-muted" data-snapshot-match>投递时匹配度 —</span>`;
  return `<div class="snapshot-drawer" data-snapshot-drawer>
    <div class="snapshot-drawer__meta">
      ${matchPill}
      ${meta ? `<span class="small muted" data-snapshot-meta>${esc(meta)}</span>` : ""}
    </div>
    ${actions}
    ${cheatsheetBlock}
    <div class="snapshot-drawer__preview">
      <div class="snapshot-drawer__preview-title">投递快照正文（预览）</div>
      <div class="resume-doc" data-snapshot-draft>${renderMarkdown(draft)}</div>
    </div>
  </div>`;
}

/* 面试防深挖清单：从已保存的 JD 画像、差距报告和高置信 diff 中确定性提炼。
 * 不构造新的经历事实，只把“高频追问”和“两句话应答 SOP”交给用户。 */
export function interviewCheatSheetHtml(job = {}) {
  const jdProfile = job.jd_profile || {};
  const gap = job.gap_report || {};
  const diffs = Array.isArray(job.diffs) ? job.diffs : [];
  const evalScore = job.eval_score || {};
  const questions = [];

  const strongDiffs = diffs
    .filter((diff) => diff && (diff.type === "modify" || diff.type === "add"))
    .filter((diff) => String(diff.confidence) === "high" || String(diff.reason || "").includes("指标"))
    .slice(0, 3);
  strongDiffs.forEach((diff) => {
    const topic =
      String(diff.proposed || diff.reason || diff.original || "这段经历")
        .replace(/\[待人工确认[^\]]*\]/g, "")
        .trim() || "这段经历";
    questions.push({
      type: "改写",
      question: `关于「${topic}」，你的具体分工、数据口径和业务收益是什么？`,
      sop: "先给结论，再说“我用了什么方法、承担哪段、最终对哪项业务指标带来什么变化”。数字没有就讲量级，不要编。",
    });
  });

  const missingKeywords = Array.isArray(gap.missing_keywords)
    ? gap.missing_keywords.slice(0, 2)
    : [];
  missingKeywords.forEach((keyword) => {
    questions.push({
      type: "JD 匹配",
      question: `JD 明确要求 ${String(keyword || "这项能力")}，你在真实项目里是如何落地的？`,
      sop: "用一句话点明技术/业务背景，再用一句话补上结果和风险控制；没做过的部分要先承认边界，不要把听说写成亲自做过。",
    });
  });

  const scenarios = Array.isArray(jdProfile.business_scenarios)
    ? jdProfile.business_scenarios.slice(0, 2)
    : [];
  scenarios.forEach((scenario) => {
    questions.push({
      type: "业务场景",
      question: `这个岗位很关注 ${String(scenario || "业务场景")}，你的方案如何支撑它？`,
      sop: "先用一个可感知的结果证明针对性，再说清你做了什么取舍；避免只堆技术名词而不说收益。",
    });
  });

  if (
    !questions.length &&
    !diffs.length &&
    !((gap.missing_keywords || []).length) &&
    !((jdProfile.business_scenarios || []).length)
  ) {
    return "";
  }

  const hallucinationWarning =
    evalScore && evalScore.hallucination_detected
      ? `<div class="cheatsheet__warning">${ICON_WARN} 检测到待复核内容，面试前请先回到工作台核对数字与来源。</div>`
      : "";

  return `
    <section class="cheatsheet" data-interview-cheatsheet>
      <div class="cheatsheet__head">
        <div>
          <h4>面试防深挖清单</h4>
          <p>每条都先点结论，再用事实接住追问。</p>
        </div>
      </div>
      ${hallucinationWarning}
      <div class="cheatsheet__list">
        ${questions
          .map(
            (item) => `
          <div class="cheatsheet__item">
            <span class="badge badge-gray">${esc(item.type)}</span>
            <strong>${esc(item.question)}</strong>
            <div class="cheatsheet__sop">${esc(item.sop)}</div>
          </div>`,
          )
          .join("")}
      </div>
    </section>`;
}

/* Bug-11: datetime-local 赋值必须为 yyyy-MM-ddTHH:mm；date-only 值补
 * T00:00，空值保持空串，避免浏览器控制台 format 警告。 */
function toDateTimeInputValue(value) {
  const text = String(value ?? "");
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? `${text}T00:00` : text;
}

/* 岗位详情/时间线弹窗表单。next_step_due_at 为 datetime-local（本地时间，
 * 无时区，与 parseNextStepDate 语义一致）；interview_stage 值域含“无”。 */
export function jobTimelineFormHtml(job, snapshots = []) {
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
        <div class="field"><label>投递时间</label><input type="datetime-local" name="applied_at" value="${esc(toDateTimeInputValue(job.applied_at))}"></div>
        <div class="field"><label>下一步</label><input type="text" name="next_step" value="${esc(job.next_step || "")}"></div>
        <div class="field"><label>到期时间</label><input type="datetime-local" name="next_step_due_at" value="${esc(toDateTimeInputValue(job.next_step_due_at))}"></div>
        <div class="field"><label>面试阶段</label><select name="interview_stage">${stageOptions}</select></div>
        <div class="field"><label>Offer 时间</label><input type="datetime-local" name="offer_at" value="${esc(toDateTimeInputValue(job.offer_at))}"></div>
        <div class="field"><label>放弃日期</label><input type="datetime-local" name="rejected_at" value="${esc(toDateTimeInputValue(job.rejected_at))}"></div>
        <div class="field wide"><label>备注</label><textarea name="notes" rows="3">${esc(job.notes || "")}</textarea></div>
      </div>
      ${applicationSnapshotsHtml(job, snapshots)}
      <div class="actions">
        <button class="btn btn-primary btn-sm" type="button" data-action="record-application" data-id="${esc(job.job_id)}">记录投递</button>
        <button class="btn btn-ghost" type="button" data-action="close-modal">取消</button>
        <button class="btn btn-primary" type="submit">保存</button>
      </div>
    </form>`;
}

/* 安排跟进快捷弹窗。状态默认保持已投递/面试中，其余状态默认面试中；
 * 无到期时间允许保存，提醒仅在有可解析时间时生成。 */
export function jobFollowupFormHtml(job) {
  const canonical = canonicalJobStatus(job.status);
  const defaultStatus =
    canonical === "applied" || canonical === "interview" ? canonical : "interview";
  const statusOptions = JOB_STATUS_CANONICAL.map(
    (value) =>
      `<option value="${value}" ${defaultStatus === value ? "selected" : ""}>${esc(JOB_STATUS_LABELS[value])}</option>`,
  ).join("");
  const stageOptions = `<option value="" ${job.interview_stage ? "" : "selected"}>无</option>${INTERVIEW_STAGES.map(
    (stage) =>
      `<option value="${esc(stage)}" ${job.interview_stage === stage ? "selected" : ""}>${esc(stage)}</option>`,
  ).join("")}`;
  return `<form data-form="job-followup">
      <input type="hidden" name="job_id" value="${esc(job.job_id)}">
      <div class="form-grid">
        <div class="field"><label>状态</label><select name="status">${statusOptions}</select></div>
        <div class="field"><label>面试阶段</label><select name="interview_stage">${stageOptions}</select></div>
        <div class="field wide"><label>下一步</label><input type="text" name="next_step" value="${esc(job.next_step || "")}"></div>
        <div class="field wide"><label>到期时间</label><input type="datetime-local" name="next_step_due_at" value="${esc(toDateTimeInputValue(job.next_step_due_at))}"></div>
      </div>
      <p class="small muted" style="margin:6px 0 0;color:var(--danger,#c0392b)">提示：保存后岗位状态将更新为「面试中」并记录投递日期。</p>
      <div class="actions">
        <button class="btn btn-ghost" type="button" data-action="close-modal">取消</button>
        <button class="btn btn-primary" type="submit">保存跟进</button>
      </div>
    </form>`;
}

function localDateInputValue(date = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/* #25: 终态收口确认表单。确认后由 main.js 的 job-terminal-confirm
 * 分支把日期/备注交给挂起的 onConfirm，走 PATCH 生命周期。 */
export function jobTerminalConfirmFormHtml(job, targetStatus, options = {}) {
  const canonical = canonicalJobStatus(targetStatus);
  if (canonical !== "offer" && canonical !== "withdrawn") return "";
  const dateName = canonical === "offer" ? "offer_at" : "rejected_at";
  const dateLabel = canonical === "offer" ? "Offer 日期" : "放弃日期";
  const dateValue = String(
    options.date || options.today || localDateInputValue(),
  ).slice(0, 10);
  return `<form data-form="job-terminal-confirm">
      <input type="hidden" name="job_id" value="${esc(job && job.job_id || "")}">
      <input type="hidden" name="status" value="${esc(canonical)}">
      <p class="small muted">将「${esc(job && job.title || "该岗位")}」收口为「${esc(JOB_STATUS_LABELS[canonical])}」，写入时间戳并清理跟进字段。</p>
      <div class="form-grid">
        <div class="field"><label>${esc(dateLabel)}</label><input type="date" name="${dateName}" value="${esc(dateValue)}" required></div>
        <div class="field wide"><label>备注（可选）</label><textarea name="notes" rows="3">${esc(options.notes || "")}</textarea></div>
      </div>
      <div class="actions">
        <button class="btn btn-ghost" type="button" data-action="cancel-status-back">取消</button>
        <button class="btn btn-primary" type="submit">确认收口</button>
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

/** 岗位卡片完整性徽章：JD 文本疑似整页 HTML/JSON（历史抓取残留）显示
 *  「JD 文本异常」，缺关键字段显示「待补全」（title 说明缺什么）。完整返回空串。 */
export function jobCompletenessBadge(job) {
  if (isJunkJd(job && job.jd_text)) {
    return '<span class="badge badge-amber" title="JD 文本疑似整页 HTML/JSON，可到工作台编辑修正">JD 文本异常</span>';
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
 * diffList(); this builds the read-only 对比视图 view with buildCmpSideHtml
 * from the session's alignment draft + diffs. */

export function buildLiveCompareHtml(session, originalContent) {
  const alignment = (session && session.alignment) || {};
  const optimizedText = alignment.draft || "";
  const diffs = alignment.diffs || [];
  return buildInlineSuggestionHtml(originalContent || "", optimizedText, diffs);
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
 *     kpi: { resumes, jobs, applied, interview, offer, declined },
 *     skill_gaps: [{ skill, count } ...],
 *     quick_continue: { job_id, title, company, alignment_status, updated_at } | null
 *   }
 */

/* 3 大 KPI 卡。applied 卡带投递转化提示（占岗位比例）。 */
export function dashboardKpiHtml(kpi = {}) {
  const data = kpi && typeof kpi === "object" ? kpi : {};
  const resumes = Math.max(0, Number(data.resumes) || 0);
  const jobs = Math.max(0, Number(data.jobs) || 0);
  const applied = Math.max(0, Number(data.applied) || 0);
  const applyRate = jobs > 0 ? Math.round((applied / jobs) * 100) : null;
  const cards = [
    { key: "resumes", label: "主简历", value: resumes, tone: "info", hint: "可用的主简历底稿" },
    { key: "jobs", label: "岗位", value: jobs, tone: "teal", hint: "岗位库总数" },
    { key: "applied", label: "已投递", value: applied, tone: "success", hint: applyRate != null ? `占岗位 ${applyRate}%` : "暂无岗位可计算转化" },
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

/* Lightweight empty-state illustration shared by dashboard and jobs views.
 * Kept as code-native SVG because this is a static, structural illustration
 * rather than a button icon or interactive glyph. */
function emptyStateIllustrationHtml() {
  return `
    <svg class="empty-state__illustration" viewBox="0 0 160 120" role="img" aria-hidden="true" focusable="false">
      <g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
        <path d="M60 16h42l18 18v64a6 6 0 0 1-6 6H60a6 6 0 0 1-6-6V22a6 6 0 0 1 6-6Z" stroke-width="4" opacity=".65"/>
        <path d="M102 16v20h18" stroke-width="4" opacity=".65"/>
        <path d="M69 48h36M69 64h36M69 80h20" stroke-width="5" opacity=".9"/>
        <circle cx="42" cy="72" r="24" stroke-width="3" opacity=".35"/>
        <path d="M42 58v28M26 72h32" stroke-width="3" opacity=".5"/>
      </g>
    </svg>`;
}

/* 空工作台引导：两个核心数据源都没有时给出第一步操作。 */
export function dashboardEmptyGuideHtml({
  hasJobs = false,
  hasResume = false,
  hasFollowups = false,
} = {}) {
  if (hasJobs || hasResume || hasFollowups) return "";
  return `
    <section class="panel panel-card empty-state dashboard-empty-guide" data-dashboard-empty>
      ${emptyStateIllustrationHtml()}
      <div class="big">欢迎使用 ResuAlign</div>
      <p class="muted">先导入一份主简历和一个岗位，工作台即可开始对齐。</p>
      <div class="actions">
        <a class="btn btn-primary" href="#/resume">上传简历</a>
        <a class="btn btn-secondary" href="#/jobs">导入 JD</a>
      </div>
    </section>`;
}

/* 岗位库空状态引导：直达添加岗位，而不是只看到空看板列。 */
export function jobsEmptyGuideHtml() {
  return `
    <section class="panel panel-card empty-state jobs-empty-guide" data-jobs-empty>
      ${emptyStateIllustrationHtml()}
      <div class="big">还没有岗位</div>
      <p class="muted">粘贴一份 JD 或导入收藏链接开始。</p>
      <div class="actions">
        <button class="btn btn-primary" type="button" data-action="show-add-job">粘贴 JD</button>
        <a class="btn btn-secondary" href="#/workspace">打开工作台</a>
      </div>
    </section>`;
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
 * 为 null / 缺 job_id 时返回空串（调用方直接注入，无节点则什么都不显示）。
 * P1-3（02-UID ③-6 / 01-GPM P1-3）：消费 alignment_status 分型渲染——
 * failed/canceled/expired 红示「上次失败 · 重新运行」；文案统一「继续」
 * 不再出现「继续对齐」动词。 */
const ALIGNMENT_STATUS_LABELS = {
  succeeded: "已对齐",
  running: "分析中",
  queued: "排队中",
  failed: "分析失败",
  canceled: "已取消",
  expired: "已过期",
  idle: "待分析",
  pending: "待分析",
};

export function alignmentStatusLabel(status) {
  return ALIGNMENT_STATUS_LABELS[status]
    || (status ? String(status) : "待分析");
}

export function quickContinueHtml(qc) {
  if (!qc || typeof qc !== "object" || !qc.job_id) return "";
  const status = qc.alignment_status;
  const qFailed = ["failed", "canceled", "expired"].includes(status);
  const qBusy = ["running", "queued"].includes(status);
  let badgeClass = "badge-gray";
  let badgeLabel = alignmentStatusLabel(status);
  let btnClass = "btn btn-primary btn-sm";
  let btnLabel = "继续";
  let btnAttr = "";
  let btnHref = `href="#/workspace/${encodeURIComponent(qc.job_id)}"`;
  if (qFailed) {
    badgeClass = "badge-red";
    badgeLabel = "上次失败 · 重新运行";
    btnClass = "btn btn-danger-solid btn-sm";
    btnLabel = "重新运行";
  } else if (status === "succeeded") {
    badgeClass = "badge-green";
    badgeLabel = "已对齐";
    btnClass = "btn btn-outline btn-sm";
    btnLabel = "查看";
  } else if (qBusy) {
    badgeClass = "badge-blue";
    badgeLabel = "分析中";
    btnClass = "btn btn-primary btn-sm is-loading";
    btnLabel = "分析中";
    btnAttr = ' aria-disabled="true"';
    btnHref = "";
  }
  return `
    <section class="panel panel-card quick-continue ${qFailed ? "quick-continue--failed" : ""}" data-quick-continue>
      <div class="quick-continue__head">
        <span class="badge badge-teal">继续上次</span>
        <span class="small muted">更新于 ${formatDate(qc.updated_at)}</span>
      </div>
      <div class="quick-continue__title">${esc(qc.title)}</div>
      <div class="quick-continue__meta">${esc(qc.company || "未知公司")} · <span class="quick-continue__status">${esc(badgeLabel)}</span></div>
      <div class="quick-continue__actions">
        <a class="${btnClass}" ${btnHref}${btnAttr}>${esc(btnLabel)}</a>
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
/* Resume optimizer: overview + modular polish (xzjobs 式)              */
/* ------------------------------------------------------------------ */
/* 简历中心「AI 优化」面板的纯函数构造器（DOM-free，Node 可单测）。
 * 数据契约与后端 run_resume_optimize / build_overview 对齐：
 *   overview = {score, verdict, skills, issues, highlights,
 *               project_count, sections_found, jd:{provided, ...}}
 *   module   = {module, index, title, original, optimized, rationale,
 *               status: "ok"|"failed", error}
 * accepted 由调用方以「模块在 result.modules 中的位置」为键传入，避免
 * 不同 section 出现相同 index 时互相覆盖。
 */

export function optimizeVerdict(score) {
  if (score === null || score === undefined || score === "") return "建议优化";
  const value = Number(score);
  if (!Number.isFinite(value)) return "建议优化";
  if (value >= 80) return "优秀";
  if (value >= 60) return "建议优化";
  return "需重点优化";
}

export function optimizeOverviewHtml(overview) {
  const data = overview && typeof overview === "object" ? overview : {};
  const rawScore = Number(data.score);
  const score = Number.isFinite(rawScore)
    ? Math.max(0, Math.min(100, rawScore))
    : null;
  const verdict = optimizeVerdict(score);
  const verdictClass =
    score == null
      ? "badge-gray"
      : score >= 80
        ? "badge-green"
        : score >= 60
          ? "badge-amber"
          : "badge-red";
  const projectCount = Number(data.project_count) || 0;
  const highlights = Array.isArray(data.highlights)
    ? data.highlights.map((item) => String(item ?? "")).filter(Boolean)
    : [];
  const issues = Array.isArray(data.issues)
    ? data.issues.map((item) => String(item ?? "")).filter(Boolean)
    : [];
  const skills = Array.isArray(data.skills)
    ? data.skills.map((item) => String(item ?? "")).filter(Boolean)
    : [];
  const jd =
    data.jd && typeof data.jd === "object" && data.jd.provided ? data.jd : null;
  const matched = jd
    ? (Array.isArray(jd.matched_keywords)
        ? jd.matched_keywords.map((item) => String(item ?? ""))
        : []
      ).filter(Boolean)
    : [];
  const unmatched = jd
    ? (Array.isArray(jd.unmatched_keywords)
        ? jd.unmatched_keywords.map((item) => String(item ?? ""))
        : []
      ).filter(Boolean)
    : [];
  return `
    <div class="optimize-overview" data-optimize-overview>
      <div class="optimize-overview__head">
        <span class="optimize-overview__score">${score ?? "—"}</span>
        <span class="badge ${verdictClass}" data-optimize-verdict>${esc(verdict)}</span>
        <span class="small muted">本地规则整体分析 · 识别 ${projectCount} 条项目/经历模块</span>
      </div>
      ${skills.length ? `
      <div class="optimize-overview__section" data-optimize-skills>
        <h4>技能亮点</h4>
        <div class="chips">${skills.slice(0, 8).map((item) => `<span class="chip">${esc(item)}</span>`).join("")}</div>
      </div>` : ""}
      ${highlights.length ? `
      <div class="optimize-overview__section" data-optimize-highlights>
        <h4>量化亮点</h4>
        <ul class="optimize-overview__list">${highlights.slice(0, 6).map((item) => `<li>${esc(item)}</li>`).join("")}</ul>
      </div>` : ""}
      ${issues.length ? `
      <div class="optimize-overview__section" data-optimize-issues>
        <h4>待优化点</h4>
        <ul class="optimize-overview__list">${issues.slice(0, 6).map((item) => `<li>${esc(item)}</li>`).join("")}</ul>
      </div>` : ""}
      ${jd ? `
      <div class="optimize-overview__section" data-optimize-jd>
        <h4>JD 关键词命中 <span class="small muted">${matched.length} 命中 / ${unmatched.length} 未命中</span></h4>
        ${matched.length ? `<div class="chips">${matched.map((item) => `<span class="chip chip--matched">${esc(item)}</span>`).join("")}</div>` : `<div class="small muted">未命中 JD 关键词</div>`}
        ${unmatched.length ? `<div class="small muted optimize-overview__unmatched">未命中：${unmatched.map((item) => esc(item)).join("、")}</div>` : ""}
      </div>` : ""}
    </div>`;
}

export function optimizeModuleHtml(item, key, accepted = false) {
  const data = item && typeof item === "object" ? item : {};
  const keyAttr = Number.isInteger(Number(key)) && Number(key) >= 0
    ? Number(key)
    : Math.max(0, Number(data.index) || 0);
  const failed = data.status === "failed" || data.status === "error";
  const title = String(data.title || `模块 ${Number(data.index) + 1}`);
  const moduleLabel = String(data.module || "");
  if (failed) {
    return `
      <div class="optimize-module optimize-module--failed" data-optimize-module data-optimize-key="${keyAttr}">
        <div class="optimize-module__head">
          <span class="optimize-module__title">${esc(title)}</span>
          ${moduleLabel ? `<span class="badge badge-gray">${esc(moduleLabel)}</span>` : ""}
          <span class="badge badge-red">润色失败</span>
        </div>
        <div class="form-error" role="alert">${esc(data.error || "润色失败，请重试")}</div>
      </div>`;
  }
  const original = data.original || "";
  const optimized = data.optimized || "";
  const rationale = data.rationale || "";
  const diffHtml = lineDiff(original, optimized)
    .map((row) => {
      const isAdd = row.type === "add";
      return `<div class="optimize-diff ${isAdd ? "optimize-diff--add" : "optimize-diff--remove"}">
        <span class="optimize-diff__sign">${isAdd ? "+" : "−"}</span>
        <span class="optimize-diff__text">${esc(row.text)}</span>
      </div>`;
    })
    .join("");
  return `
    <div class="optimize-module${accepted ? " is-accepted" : ""}" data-optimize-module data-optimize-key="${keyAttr}">
      <div class="optimize-module__head">
        <span class="optimize-module__title">${esc(title)}</span>
        ${moduleLabel ? `<span class="badge badge-gray">${esc(moduleLabel)}</span>` : ""}
        ${accepted ? `<span class="badge badge-green" data-optimize-accepted-mark>已采纳</span>` : ""}
      </div>
      <div class="optimize-module__diff">${diffHtml || `<span class="small muted">无改动</span>`}</div>
      ${rationale ? `<div class="optimize-module__rationale">${esc(rationale)}</div>` : ""}
      <div class="optimize-module__actions">
        <button type="button" class="btn ${accepted ? "btn-primary" : "btn-outline"} btn-sm" data-action="optimize-accept-item" data-optimize-key="${keyAttr}">${accepted ? "已采纳" : "采纳"}</button>
        <button type="button" class="btn btn-ghost btn-sm" data-action="optimize-reject-item" data-optimize-key="${keyAttr}">忽略</button>
      </div>
    </div>`;
}

export function optimizeActionsHtml(modules, accepted) {
  const list = Array.isArray(modules) ? modules : [];
  const okCount = list.filter((item) => item && item.status === "ok").length;
  const acceptedCount = Object.values(accepted || {}).filter(Boolean).length;
  return `
    <div class="optimize-actions" data-optimize-actions>
      <button type="button" class="btn btn-primary btn-sm" data-action="optimize-apply-accepted" ${acceptedCount ? "" : "disabled"}>应用已采纳（${acceptedCount}）为新版本</button>
      <button type="button" class="btn btn-outline btn-sm" data-action="optimize-accept-all" ${okCount ? "" : "disabled"}>全部采纳</button>
      <button type="button" class="btn btn-ghost btn-sm" data-action="optimize-rerun">重新润色</button>
    </div>`;
}

export function collectAcceptedOptimizeItems(modules, accepted) {
  const list = Array.isArray(modules) ? modules : [];
  const acceptedMap = accepted && typeof accepted === "object" ? accepted : {};
  return list
    .filter(
      (item, key) =>
        item &&
        item.status === "ok" &&
        acceptedMap[String(key)] &&
        String(item.optimized || "").trim(),
    )
    .map((item) => ({
      module: String(item.module || ""),
      index: Number(item.index),
      optimized: item.optimized,
    }));
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

/** Cost-guard panel: today's usage plus the daily cap / price form.
 *
 * settings comes from GET /api/settings; daily comes from the status
 * endpoint so the page can show the live block state.
 */
export function costGuardPanelHtml(settings, daily = {}) {
  const s = settings && typeof settings === "object" ? settings : {};
  const capValue = s.daily_llm_cap == null ? "" : String(s.daily_llm_cap);
  const inValue =
    s.llm_cost_per_1k_in == null ? "" : String(s.llm_cost_per_1k_in);
  const outValue =
    s.llm_cost_per_1k_out == null ? "" : String(s.llm_cost_per_1k_out);
  const callsNum = Number(daily.calls);
  const calls = Number.isFinite(callsNum) ? callsNum : 0;
  const costNum = Number(daily.estimated_cost);
  const cost = Number.isFinite(costNum) ? costNum : 0;
  const hasCap = daily.cap != null && daily.cap !== "";
  const capLabel = hasCap ? String(daily.cap) : "不限制";
  const remainingLabel =
    hasCap && daily.remaining != null ? String(daily.remaining) : "—";
  const blocked = Boolean(daily.blocked);
  return `
    <section class="panel cost-guard-panel" data-cost-guard-panel>
      <div class="panel-head">
        <div>
          <h2>成本护栏</h2>
          <p>每日 LLM 调用上限、估算成本与拦截状态</p>
        </div>
        ${blocked ? '<span class="badge badge-red" data-cost-blocked>今日已阻止新 LLM 任务</span>' : ""}
      </div>
      <div class="panel-body">
        <div class="cost-guard-status" data-cost-status data-cost-blocked="${blocked ? "true" : "false"}">
          <div><span>今日调用</span><strong data-daily-calls>${esc(calls)}</strong></div>
          <div><span>估算成本</span><strong data-daily-cost>¥${esc(cost.toFixed(4))}</strong></div>
          <div><span>今日上限</span><strong data-daily-cap>${esc(capLabel)}</strong></div>
          <div><span>剩余额度</span><strong data-daily-remaining>${esc(remainingLabel)}</strong></div>
        </div>
        <form data-form="settings-cost-guard" class="cost-guard-form">
          <div class="form-grid">
            <div class="field"><label>每日调用上限</label>
              <input type="number" name="daily_llm_cap" min="0" step="1" value="${esc(capValue)}" placeholder="留空表示不限制">
              <span class="small muted">达到上限后新任务返回 429，缓存命中不受影响</span></div>
            <div class="field"><label>每 1k 输入 token（元）</label>
              <input type="number" name="llm_cost_per_1k_in" min="0" step="0.001" value="${esc(inValue)}" placeholder="例如 0.5">
              <span class="small muted">仅用于成本估算</span></div>
            <div class="field"><label>每 1k 输出 token（元）</label>
              <input type="number" name="llm_cost_per_1k_out" min="0" step="0.001" value="${esc(outValue)}" placeholder="例如 1.5">
              <span class="small muted">仅用于成本估算</span></div>
          </div>
          <div class="row" style="margin-top:10px">
            <button class="btn btn-outline btn-sm" type="submit">保存成本护栏</button>
          </div>
        </form>
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

