/* Pure model helpers for the Job Hall (职位大厅).
 *
 * Kept free of DOM / fetch / localStorage so it can be imported by the
 * node:test suite. The live view (job-hall.js) owns persistence and events.
 */
import {
  JOB_STATUS_CANONICAL,
  JOB_STATUS_LABELS,
  canonicalJobStatus,
} from "./format.js";

export const AUDIENCES = [
  { value: "all", label: "全部" },
  { value: "campus", label: "校园招聘" },
  { value: "experienced", label: "社会招聘" },
];

export const SALARY_BANDS = [
  { value: "", label: "不限" },
  { value: "0-10", label: "10K 以下" },
  { value: "10-20", label: "10–20K" },
  { value: "20-30", label: "20–30K" },
  { value: "30-50", label: "30–50K" },
  { value: "50+", label: "50K 以上" },
];

export const HALL_SORTS = [
  { value: "match_desc", label: "匹配优先" },
  { value: "updated_desc", label: "最近更新" },
  { value: "salary_desc", label: "薪资从高到低" },
  { value: "deadline_asc", label: "截止日期最近" },
];

const CAMPUS_SIGNAL = /校招|校园招聘|应届|实习|管培|储备干部|202[5-9]届/;
const DAY_MS = 86400000;

export function audienceLabel(value) {
  const found = AUDIENCES.find((item) => item.value === value);
  return found ? found.label : "全部";
}

/* The API has no explicit campus/experienced column. We only use signals the
 * job actually carries (seniority, title, tags, JD opening) and default to
 * experienced when nothing indicates campus — never invent a field backend
 * cannot persist. */
export function inferAudience(job) {
  if (!job || typeof job !== "object") return "experienced";
  /* The summary projection derives the hint from the full JD server-side;
     prefer it when present so the campus tab stays exact without shipping
     the JD body. Older/full payloads still fall through to the local rules. */
  if (job.audience === "campus" || job.audience === "experienced") {
    return job.audience;
  }
  const seniority = String(job.seniority || "").trim();
  if (seniority === "实习" || seniority === "应届") return "campus";
  const tags = Array.isArray(job.tech_tags) ? job.tech_tags.join(" ") : "";
  const jd = String(job.jd_text || job.jd_excerpt || "").slice(0, 2000);
  const haystack = [
    job.title,
    job.job_function,
    seniority,
    tags,
    jd,
  ]
    .filter(Boolean)
    .join(" ");
  return CAMPUS_SIGNAL.test(haystack) ? "campus" : "experienced";
}

export function salaryBand(job) {
  const max = Number(job && (job.salary_max ?? job.salary_min));
  if (!Number.isFinite(max) || max <= 0) return "";
  if (max < 10000) return "0-10";
  if (max < 20000) return "10-20";
  if (max < 30000) return "20-30";
  if (max < 50000) return "30-50";
  return "50+";
}

export function salaryValue(job) {
  const max = Number(job && (job.salary_max ?? job.salary_min));
  return Number.isFinite(max) ? max : 0;
}

export function timestampMs(value) {
  if (value == null || value === "") return null;
  if (typeof value === "number") {
    return value > 1e12 ? value : value * 1000;
  }
  const numeric = Number(value);
  if (Number.isFinite(numeric) && String(value).trim() !== "") {
    return numeric > 1e12 ? numeric : numeric * 1000;
  }
  const parsed = Date.parse(String(value));
  return Number.isFinite(parsed) ? parsed : null;
}

export function relativeTime(value, now = Date.now()) {
  const ts = timestampMs(value);
  if (ts == null) return "";
  const diff = Math.max(0, now - ts);
  if (diff < 60000) return "刚刚";
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`;
  if (diff < DAY_MS) return `${Math.floor(diff / 3600000)} 小时前`;
  if (diff < DAY_MS * 7) return `${Math.floor(diff / DAY_MS)} 天前`;
  const date = new Date(ts);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
    date.getDate(),
  ).padStart(2, "0")}`;
}

export function companyInitial(company) {
  const text = String(company || "").trim();
  if (!text) return "?";
  return Array.from(text)[0].toUpperCase();
}

export function jobStage(job) {
  const canonical = canonicalJobStatus(job && job.status);
  if (canonical === "withdrawn") return "withdrawn";
  if (canonical === "offer") return "offer";
  if (canonical === "interview") return "interview";
  if (canonical === "applied") return "applied";
  return "draft";
}

/* Historical peak used for conversion rates only: offer_at > applied_at >
 * current status, mirroring /api/dashboard's funnel semantics. */
export function peakStage(job) {
  const canonical = canonicalJobStatus(job && job.status);
  const order = ["draft", "applied", "interview", "offer"];
  let peak = Math.max(0, order.indexOf(canonical));
  if (job && job.applied_at) peak = Math.max(peak, 1);
  if (job && job.offer_at) peak = Math.max(peak, 3);
  return order[peak] || "draft";
}

function lower(value) {
  return String(value || "").toLowerCase();
}

function matchesText(job, query) {
  const needle = lower(query).trim();
  if (!needle) return true;
  const tags = Array.isArray(job.tech_tags) ? job.tech_tags.join(" ") : "";
  const haystack = [
    job.title,
    job.company,
    job.location,
    job.job_function,
    job.seniority,
    tags,
    String(job.jd_text || job.jd_excerpt || "").slice(0, 4000),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return needle.split(/\s+/).every((word) => haystack.includes(word));
}

/* Filters are applied in memory over the already-fetched page of library
 * jobs. That keeps typing instant and avoids a request per keystroke; the
 * API itself already supports search/sort for callers that need paging. */
export function filterHallJobs(
  jobs,
  filters = {},
  savedIds = new Set(),
  now = Date.now(),
) {
  const list = Array.isArray(jobs) ? jobs : [];
  const matchMin = Number(filters.matchMin) || 0;
  const saved = savedIds instanceof Set ? savedIds : new Set(savedIds || []);
  const recentCutoff = now - 7 * DAY_MS;
  return list.filter((job) => {
    if (!job || !job.job_id) return false;
    if (!matchesText(job, filters.query)) return false;
    if (filters.audience && filters.audience !== "all") {
      if (inferAudience(job) !== filters.audience) return false;
    }
    if (filters.city && String(job.location || "") !== filters.city) return false;
    if (
      filters.jobFunction &&
      String(job.job_function || "") !== filters.jobFunction
    ) {
      return false;
    }
    if (
      filters.seniority &&
      String(job.seniority || "") !== filters.seniority
    ) {
      return false;
    }
    if (filters.status) {
      if (canonicalJobStatus(job.status) !== canonicalJobStatus(filters.status)) {
        return false;
      }
    }
    if (filters.salary && salaryBand(job) !== filters.salary) return false;
    if (matchMin > 0) {
      const score = Number(job.match_score);
      if (!Number.isFinite(score) || score < matchMin) return false;
    }
    if (filters.savedOnly && !saved.has(job.job_id)) return false;
    if (filters.recentOnly) {
      const updated = timestampMs(job.updated_at);
      if (updated == null || updated < recentCutoff) return false;
    }
    return true;
  });
}

export function sortHallJobs(jobs, sort = "match_desc") {
  const list = Array.isArray(jobs) ? [...jobs] : [];
  if (sort === "updated_at_desc") sort = "updated_desc";
  if (sort === "match_score_desc") sort = "match_desc";
  if (sort === "match_score_asc") sort = "match_asc";
  const byUpdated = (a, b) =>
    (timestampMs(b.updated_at) || 0) - (timestampMs(a.updated_at) || 0);
  if (sort === "updated_desc") return list.sort(byUpdated);
  if (sort === "match_asc") {
    return list.sort((a, b) => {
      const aScore = Number.isFinite(Number(a.match_score))
        ? Number(a.match_score)
        : Number.MAX_SAFE_INTEGER;
      const bScore = Number.isFinite(Number(b.match_score))
        ? Number(b.match_score)
        : Number.MAX_SAFE_INTEGER;
      return aScore - bScore || byUpdated(a, b);
    });
  }
  if (sort === "salary_desc") {
    return list.sort((a, b) => {
      const delta = salaryValue(b) - salaryValue(a);
      return delta || byUpdated(a, b);
    });
  }
  if (sort === "deadline_asc") {
    return list.sort((a, b) => {
      const aTime = timestampMs(a.deadline) || Number.MAX_SAFE_INTEGER;
      const bTime = timestampMs(b.deadline) || Number.MAX_SAFE_INTEGER;
      return aTime - bTime || byUpdated(a, b);
    });
  }
  return list.sort((a, b) => {
    const aScore = Number.isFinite(Number(a.match_score))
      ? Number(a.match_score)
      : -1;
    const bScore = Number.isFinite(Number(b.match_score))
      ? Number(b.match_score)
      : -1;
    return bScore - aScore || byUpdated(a, b);
  });
}

export function dueItems(jobs, now = Date.now()) {
  const items = [];
  for (const job of Array.isArray(jobs) ? jobs : []) {
    const due = timestampMs(job.next_step_due_at);
    if (due != null) {
      items.push({
        job,
        kind: "next_step",
        at: due,
        label: job.next_step || "跟进下一步",
      });
    }
    const deadline = timestampMs(job.deadline);
    if (deadline != null) {
      items.push({
        job,
        kind: "deadline",
        at: deadline,
        label: "投递截止",
      });
    }
  }
  return items.sort((a, b) => a.at - b.at);
}

export function computeHallStats(jobs, savedIds = new Set(), now = Date.now()) {
  const list = Array.isArray(jobs) ? jobs : [];
  const saved = savedIds instanceof Set ? savedIds : new Set(savedIds || []);
  const stats = {
    total: list.length,
    draft: 0,
    applied: 0,
    interview: 0,
    offer: 0,
    withdrawn: 0,
    appliedCumulative: 0,
    interviewCumulative: 0,
    offerCumulative: 0,
    saved: 0,
    highMatch: 0,
    overdue: 0,
    dueSoon: 0,
    applyRate: 0,
    interviewRate: 0,
    offerRate: 0,
  };
  const week = now + 7 * DAY_MS;
  const seenDue = new Set();
  const seenOverdue = new Set();
  for (const job of list) {
    const stage = jobStage(job);
    stats[stage] += 1;
    const peak = peakStage(job);
    const peakIndex = ["draft", "applied", "interview", "offer"].indexOf(peak);
    if (peakIndex >= 1) stats.appliedCumulative += 1;
    if (peakIndex >= 2) stats.interviewCumulative += 1;
    if (peakIndex >= 3) stats.offerCumulative += 1;
    if (saved.has(job.job_id)) stats.saved += 1;
    if (Number(job.match_score) >= 80) stats.highMatch += 1;
    for (const item of dueItems([job], now)) {
      if (item.at < now) {
        seenOverdue.add(job.job_id);
        seenDue.add(job.job_id);
      } else if (item.at <= week) {
        stats.dueSoon += 1;
        seenDue.add(job.job_id);
      }
    }
  }
  stats.overdue = seenOverdue.size;
  stats.dueSoon = seenDue.size;
  stats.applyRate = stats.total
    ? Math.round((stats.appliedCumulative / stats.total) * 100)
    : 0;
  stats.interviewRate = stats.appliedCumulative
    ? Math.round((stats.interviewCumulative / stats.appliedCumulative) * 100)
    : 0;
  stats.offerRate = stats.appliedCumulative
    ? Math.round((stats.offerCumulative / stats.appliedCumulative) * 100)
    : 0;
  return stats;
}

export function uniqueValues(jobs, key) {
  const seen = new Set();
  for (const job of Array.isArray(jobs) ? jobs : []) {
    const value = String((job && job[key]) || "").trim();
    if (value) seen.add(value);
  }
  return [...seen].sort((a, b) => a.localeCompare(b, "zh-CN"));
}

export function cityOptions(jobs) {
  return uniqueValues(jobs, "location");
}

export function functionOptions(jobs) {
  return uniqueValues(jobs, "job_function");
}

export function seniorityOptions(jobs) {
  return uniqueValues(jobs, "seniority");
}

export function statusOptions() {
  return JOB_STATUS_CANONICAL.map((value) => ({
    value,
    label: JOB_STATUS_LABELS[value],
  }));
}

export function activeFilterCount(filters = {}) {
  let count = 0;
  if (String(filters.query || "").trim()) count += 1;
  if (filters.audience && filters.audience !== "all") count += 1;
  for (const key of [
    "city",
    "jobFunction",
    "seniority",
    "status",
    "salary",
  ]) {
    if (filters[key]) count += 1;
  }
  if (Number(filters.matchMin) > 0) count += 1;
  if (filters.savedOnly) count += 1;
  if (filters.recentOnly) count += 1;
  if (filters.work_status && filters.work_status !== "all") count += 1;
  return count;
}

export function isDeadlineOverdue(job, now = Date.now()) {
  const deadline = timestampMs(job && job.deadline);
  return deadline != null && deadline < now;
}

export function isDeadlineSoon(job, now = Date.now()) {
  const deadline = timestampMs(job && job.deadline);
  return deadline != null && deadline >= now && deadline <= now + 7 * DAY_MS;
}
