import {
  $,
  $$,
  api,
  applyPendingStatusTransition,
  buildDiagnosisMarkdown,
  cancelPendingStatusTransition,
  canonicalJobStatus,
  closeModal,
  confirmBackwardStatus,
  confirmTerminalStatus,
  download,
  esc,
  formatDate,
  isBackwardJobStatus,
  jobStatusLabel,
  jobStatusRank,
  normalizeVocabulary,
  renderBatchResults,
  refreshOptimizePanel,
  renderDiagnosisError,
  renderDiagnosisProgress,
  renderOptimizeError,
  renderOptimizeProgress,
  setWbMobilePane,
  showModal,
  startBatchPolling,
  startDiagnosisPolling,
  startOptimizePolling,
  state,
  stopAllPolling,
  stopBatchPolling,
  stopDiagnosisPolling,
  stopOptimizePolling,
  toast,
  vocabularyList,
} from "./events.js";
import { initTheme, toggleTheme } from "./theme.js";
import { renderDashboard } from "./dashboard-view.js";
import {
  openResumeCreator,
  openResumeEditor,
  renderResumeCenter,
} from "./resume-center.js";
import {
  closeCommandPanel,
  confirmCommandPanel,
  initializeCommandPanel,
  openCommandPanel,
} from "./command-panel.js";
import {
  analyzeActiveJd,
  activeSessionForExport,
  cancelActiveAlignment,
  closeSplitCanvas,
  copyAlignMarkdown,
  getLiveSheetDraft,
  renderOptimizerCanvas,
  setWbAuxPane,
  setWbViewMode,
  startAlignmentRun,
  syncLiveSheetDraft,
} from "./split-canvas.js";
import {
  renderKanban,
  setCanvasRenderHook,
} from "./kanban.js";
import {
  applyAcceptedDiffsToDraft,
  applyDiffToDraft,
  backupRestoreGuide,
  batchPanelHtml,
  batchRowsToCsv,
  buildJobsBackup,
  collectAcceptedOptimizeItems,
  buildLiveCompareHtml,
  costGuardPanelHtml,
  isJdUrl,
  jobApplyLinkHtml,
  jobEditFormHtml,
  jobFollowupFormHtml,
  jobSelectOptionsHtml,
  jobTimelineFormHtml,
  jobsToCsv,
  llmNodeCardHtml,
  llmNodeFormHtml,
  nodeTestResultHtml,
  offerCelebrationHtml,
  onboardingSteps,
  parseHashValue,
  RESUME_LIST_SENTINEL,
  renderMarkdown,
  renderOnboardingCard,
  ruleFormHtml,
  ruleListHtml,
  runEvalFromForm,
  settingsBentoHtml,
  snapshotDrawerHtml,
} from "./format.js";
import {
  buildAutomationRulePayload,
  buildCostGuardPayload,
  buildLlmNodePayload,
  evalDefaultFromForm,
  validateAutomationRule,
  validateCostGuardPayload,
  validateLlmNodePayload,
} from "./settings-form.js";

function isTerminalJobStatus(status) {
  const canonical = canonicalJobStatus(status);
  return canonical === "offer" || canonical === "withdrawn";
}

function celebrateOffer(job) {
  const html = offerCelebrationHtml(job);
  if (!html) return;
  const holder = document.createElement("div");
  holder.innerHTML = html;
  const overlay = holder.firstElementChild;
  if (!overlay) return;
  document.body.append(overlay);
  setTimeout(() => overlay.remove(), 2800);
}

const ROUTE_LABELS = {
  resume: "简历中心",
  jobs: "岗位库",
  workspace: "对齐工作台",
  settings: "系统设置",
  dashboard: "驾驶舱",
};

/* v3 shell: 顶栏标题/副标题随路由联动。 */
const PAGE_META = {
  dashboard: ["驾驶舱", "主简历与岗位对齐态势"],
  workspace: ["对齐工作台", "岗位上下文、Diff 画布与 JD/Live Sheet 辅助舱"],
  jobs: ["岗位库", "Pipeline 看板与 JD 粘贴建库"],
  resume: ["简历中心", "Markdown 双态编辑、ATS 健康度与版本时间线"],
  settings: ["系统设置", "LLM 节点、Guardrails、自动化规则与词表"],
};

function parseHash() {
  return parseHashValue(window.location.hash);
}

function navigate(name, id = null) {
  if (name === "workspace" && id) {
    window.location.hash = `#/workspace/${encodeURIComponent(id)}`;
  } else if (name === "resume" && id) {
    window.location.hash = `#/resume/${encodeURIComponent(id)}`;
  } else {
    window.location.hash = `#/${name}`;
  }
}

function setActiveTab() {
  $$(".tabs button").forEach((button) => {
    const selected = button.dataset.route === state.route.name;
    button.setAttribute("aria-selected", String(selected));
    button.classList.toggle("active", selected);
  });
}

function refreshHeaderMeta() {
  const route = (state.route && state.route.name) || "dashboard";
  const [title, subtitle] = PAGE_META[route] || PAGE_META.dashboard;
  const titleNode = $("#page-title");
  const subtitleNode = $("#page-subtitle");
  if (titleNode) titleNode.textContent = title;
  if (subtitleNode) subtitleNode.textContent = subtitle;
}

function refreshJobsRailCount(count) {
  const badge = $("[data-jobs-rail-count]");
  if (!badge) return;
  const total = Math.max(0, Number(count) || 0);
  badge.hidden = total === 0;
  badge.textContent = total;
}

/* 蓝图路由收口：hash → 视图分发的唯一入口。route 名直接来自 hash
 *（resumes 复数、workspace 带 job_id/id/skill query），视图实现由
 * 各子模块负责。workbench 是 workspace 的旧别名，一并归一。 */
async function handleRoute(app) {
  const hash = window.location.hash || "#/dashboard";
  const [rawRoute, queryString] = hash.replace("#/", "").split("?");
  /* route 取第一段：#/workspace/<jobId> → "workspace"，
   * #/workspace?job_id=X → "workspace"，#/resumes → "resumes" */
  const route = (rawRoute || "dashboard").split("/")[0] || "dashboard";
  const params = new URLSearchParams(queryString || "");

  switch (route) {
    case "dashboard":
      await renderDashboard(app);
      break;
    case "workspace":
    case "workbench": {
      /* 兼容两种 deep-link：#/workspace/<jobId>（path 段，已由
       * parseHashValue 解析）与 #/workspace?job_id=X&skill=Y（蓝图
       * 显式契约）。?skill= 深链由 split-canvas 内部自解析。 */
      const jobId =
        state.route.jobId || params.get("job_id") || params.get("id") || null;
      await renderOptimizerCanvas(app, jobId);
      break;
    }
    case "jobs": {
      const sort = params.get("sort");
      if (
        sort &&
        ["updated_at_desc", "match_score_desc", "match_score_asc"].includes(sort)
      ) {
        state.filters.sort = sort;
      }
      await renderKanban(app);
      break;
    }
    case "resumes":
    case "resume":
      await renderResumeCenter(app, {
        resumeId:
          state.route.resumeId === RESUME_LIST_SENTINEL
            ? null
            : state.route.resumeId,
        showList: state.route.resumeId === RESUME_LIST_SENTINEL,
      });
      break;
    case "settings":
      await renderSettingsView(app);
      break;
    default:
      await renderDashboard(app);
      break;
  }
}

/* 侧栏 footer 配额条：与设置页成本护栏同源（GET /api/settings/status 的
 * status.daily），消除「今日额度」数据不一致。 */
let railQuotaInFlight = false;
async function refreshRailQuota() {
  if (railQuotaInFlight) return;
  railQuotaInFlight = true;
  try {
    const status = await api("/api/settings/status", {
      cacheKey: "rail:status",
    });
    fillRailQuota((status && status.daily) || {});
  } catch {
    /* 保留占位状态，不打断路由渲染 */
  } finally {
    railQuotaInFlight = false;
  }
}

function fillRailQuota(daily = {}) {
  const root = $("[data-rail-quota]");
  if (!root || typeof daily !== "object") return;
  const callsNum = Number(daily.calls);
  const calls = Number.isFinite(callsNum) ? callsNum : 0;
  const costNum = Number(daily.estimated_cost);
  const cost = Number.isFinite(costNum) ? costNum : 0;
  const hasCap = daily.cap != null && daily.cap !== "";
  const capNum = Number(daily.cap);
  const capLabel = hasCap ? String(daily.cap) : "不限制";
  const remainingLabel = hasCap && daily.remaining != null ? String(daily.remaining) : "—";
  const blocked = Boolean(daily.blocked);
  const costEl = $("[data-rail-quota-cost]", root);
  if (costEl) costEl.textContent = `¥${cost.toFixed(4)} / ¥${capLabel}`;
  const percent = hasCap && Number.isFinite(capNum) && capNum > 0 ? Math.min(100, (cost / capNum) * 100) : 0;
  const trackEl = $("[data-rail-quota-track]", root);
  if (trackEl) {
    trackEl.classList.toggle("is-blocked", blocked);
    trackEl.setAttribute("aria-valuenow", String(Math.round(percent)));
  }
  const fillEl = $("[data-rail-quota-fill]", root);
  if (fillEl) fillEl.style.width = `${percent}%`;
  const remainingEl = $("[data-rail-quota-remaining]", root);
  if (remainingEl) remainingEl.textContent = `剩余 ¥${remainingLabel}`;
  const callsEl = $("[data-rail-quota-calls]", root);
  if (callsEl) callsEl.textContent = `${calls} 次调用`;
  const statusEl = $("[data-rail-quota-status]", root);
  if (statusEl) {
    statusEl.textContent = blocked ? "今日已阻止新 LLM 任务" : "";
    statusEl.classList.toggle("is-error", blocked);
  }
  root.hidden = false;
}

async function render() {
  state.route = parseHash();
  closeSplitCanvas();
  setActiveTab();
  refreshHeaderMeta();
  stopAllPolling();
  const app = $("#app-router-view");
  const printNode = $("#print-root");
  if (printNode) printNode.innerHTML = "";
  app.innerHTML = `<div class="skeleton is-shimmer">加载中...</div>`;
  /* T2: 每次路由渲染同步 Header 岗位快速选择器（异步填充 + 立即同步值）。 */
  refreshHeaderJobSelect();
  syncHeaderJobSelect();
  try {
    await handleRoute(app);
  } catch (error) {
    console.error("render error:", error && error.message, "route:", state.route && state.route.name);
    if (isApiKeyUnconfigured(error)) {
      renderApiKeyGuide(app);
      return;
    }
    /* S6-fix: a stale/removed workspace job id should fall back to the
       Dashboard instead of a dead-end error panel. */
    if (
      state.route.name === "workspace" &&
      /not found|404|已过期|不存在/i.test(String(error.message))
    ) {
      navigate("dashboard");
      return;
    }
    app.innerHTML = `<div class="panel"><h3>出错了</h3><p class="muted">${esc(error.message)}</p>
      <div class="row" style="margin-top:12px"><button class="btn btn-primary" data-action="reload">重试</button></div></div>`;
  }
  refreshRailQuota();
}

/* ------------------------------------------------------------------ */
/* API-key guidance empty state                                       */
/* ------------------------------------------------------------------ */

function isApiKeyUnconfigured(error) {
  return (
    error &&
    error.status === 503 &&
    /LLM 町配置|API key not configured/i.test(error.message || "")
  );
}

function renderApiKeyGuide(app) {
  app.innerHTML = `
    <div class="page-header page-header--workspace"><div><h2>单岗位工作台</h2>
      <div class="sub">先配置 LLM，再开始对齐分析</div></div></div>
    <div class="panel panel-card empty-state">
      <div class="big">LLM 尚未配置</div>
      <div>工作台的分析、对齐与改写需要调用大模型 API。到设置页填入 Key 并保存后即可开始。</div>
      <div class="actions">
        <a href="#/settings" class="btn btn-primary">去设置页配置 LLM</a>
      </div>
    </div>`;
}

/* T2: Header 岗位快速选择器。每次 render() 异步刷新（fetch 去重），
 * 成功后回填 option 并保持当前工作台岗位选中；非 workspace 页也显示，
 * change 事件直接跳 #/workspace/<job_id>。 */

let headerJobsCache = null;
let headerJobsFetch = null;

function refreshHeaderJobSelect() {
  if (headerJobsFetch) return;
  headerJobsFetch = api("/api/jobs?limit=100")
    .then((jobs) => {
      headerJobsCache = Array.isArray(jobs) ? jobs : [];
      populateHeaderJobSelect(headerJobsCache);
      refreshJobsRailCount(headerJobsCache.length);
      return headerJobsCache;
    })
    .catch(() => {
      headerJobsCache = headerJobsCache || [];
      return headerJobsCache;
    })
    .finally(() => {
      headerJobsFetch = null;
    });
}

function populateHeaderJobSelect(jobs) {
  const select = $("[data-header-job-select]");
  if (!select) return;
  const selectedId =
    state.route && state.route.name === "workspace" ? state.route.jobId : "";
  select.innerHTML = jobSelectOptionsHtml(jobs, selectedId);
}

function syncHeaderJobSelect() {
  const select = $("[data-header-job-select]");
  if (!select) return;
  select.value =
    state.route && state.route.name === "workspace" && state.route.jobId
      ? state.route.jobId
      : "";
}


/* ------------------------------------------------------------------ */
/* Job Library                                                         */
/* ------------------------------------------------------------------ */

function openJobEditor(job) {
  showModal(
    `编辑「${job.title}」`,
    jobEditFormHtml(job, {
      statuses: vocabularyList("statuses"),
      job_functions: vocabularyList("job_functions"),
      seniorities: vocabularyList("seniorities"),
    }),
  );
}

/* ------------------------------------------------------------------ */
/* Workspace                                                           */
/* ------------------------------------------------------------------ */

const JOB_CREATE_FORM_HTML = `
    <form class="panel panel-card" data-form="job-create" hidden>
      <h3>添加岗位</h3>
      <p class="small muted" style="margin:0 0 10px">岗位链接请用浏览器油猴插件一键入库，或用「粘贴 JD」方式录入（后端已不再抓取 JD 链接）</p>
      <div class="form-grid" style="margin-top:10px">
        <div class="field"><label>标题</label><input type="text" name="title" placeholder="留空则从 JD 首行提取"></div>
        <div class="field"><label>公司</label><input type="text" name="company"></div>
        <div class="field"><label>城市</label><input type="text" name="location"></div>
        <div class="field"><label>来源链接</label><input type="url" name="source_url"></div>
        <div class="field"><label>最低薪资（月，元）</label><input type="number" name="salary_min" min="0" step="100"></div>
        <div class="field"><label>最高薪资（月，元）</label><input type="number" name="salary_max" min="0" step="100"></div>
        <div class="field"><label>薪资币种</label><input type="text" name="salary_currency" placeholder="CNY"></div>
        <div class="field wide"><label>JD 文本</label><textarea name="jd_text" rows="8"></textarea></div>
      </div>
      <div class="row"><button class="btn btn-primary" type="submit">保存岗位</button>
        <button class="btn btn-ghost" type="button" data-action="cancel-add-job">取消</button></div>
    </form>`;

const JOB_IMPORT_FORM_HTML = `
    <form class="panel panel-card" data-form="job-import" hidden>
      <h3>批量导入</h3>
      <div class="field"><label>粘贴 CSV 或 JSON 数组（字段含 title / jd_text / company / location；jd_url 需同时提供 jd_text，否则该行会被跳过）</label>
        <textarea name="import_text" rows="6" placeholder='title,jd_text,location&#10;后端工程师,要求 Python 和 FastAPI,上海'></textarea></div>
      <div class="field"><label>或选择文件（.csv / .json）</label><input type="file" name="import_file" accept=".csv,.json,text/csv,application/json"></div>
      <div class="row"><button class="btn btn-primary" type="submit">开始导入</button>
        <button class="btn btn-ghost" type="button" data-action="cancel-import">取消</button>
        <span class="small muted" data-import-status></span></div>
    </form>`;

async function openJobDetail(job) {
  let snapshots = [];
  try {
    snapshots = await api(
      `/api/jobs/${encodeURIComponent(job.job_id)}/snapshots`,
    );
  } catch {
    snapshots = [];
  }
  state.applicationSnapshots = {
    ...(state.applicationSnapshots || {}),
    [job.job_id]: {
      jobId: job.job_id,
      job,
      snapshots: Array.isArray(snapshots) ? snapshots : [],
      legacyDraft: job.final_draft || null,
    },
  };
  showModal(
    `岗位详情 · ${job.title}`,
    jobTimelineFormHtml(job, snapshots),
  );
}

async function showDuplicateJobGuide(payload) {
  const matches = await api("/api/jobs?limit=100");
  const haystack = matches || [];
  const dup = haystack.find(
    (item) =>
      (payload.title && item.title === payload.title) ||
      (payload.jd_text &&
        (payload.jd_text || "").trim() &&
        item.jd_text === payload.jd_text.trim()) ||
      (payload.source_url && item.source_url === payload.source_url),
  );
  showModal(
    "检测到相同岗位",
    `<div class="drawer">
      <p>岗位库中已存在相同岗位${
        dup
          ? `：「${esc(dup.title)}」${dup.company ? ` · ${esc(dup.company)}` : ""}（${esc(dup.status || "未投递")}）`
          : ""
      }，无法重复添加。</p>
      <div class="actions">
        <button class="btn btn-ghost" type="button" data-action="close-modal">取消</button>
        ${
          dup
            ? `<button class="btn btn-primary" type="button" data-action="open-workspace" data-id="${dup.job_id}">打开已有岗位</button>`
            : ""
        }
      </div>
    </div>`,
  );
}

async function refreshOptimizerFromJob(jobId) {
  await renderOptimizerCanvas($("#app-router-view"), jobId);
}

async function refreshWbCanvas() {
  const job = state.wbJob;
  if (!job || !job.job_id) return;
  await refreshOptimizerFromJob(job.job_id);
}

/* T4: 岗位切换（Header select / 画布内 switcher 共用）。已在 workspace 页时
 * 直接复用 renderOptimizerCanvas 刷新 Diff 画布：用 history.pushState 更新 URL
 *（不触发 hashchange 整页路由，且保留 Back 后退语义），再同步 header select
 * 回显；非 workspace（无 context）时走 navigate 路由跳转并回显。 */
async function switchWorkspaceJob(jobId) {
  if (!jobId) return;
  try {
    if (!(state.route && state.route.name === "workspace")) {
      navigate("workspace", jobId);
      return;
    }
    if (state.route.jobId === jobId) {
      syncHeaderJobSelect();
      return;
    }
    state.route = {
      name: "workspace",
      jobId,
      resumeId: (state.route && state.route.resumeId) || null,
    };
    window.history.pushState(
      null,
      "",
      `#/workspace/${encodeURIComponent(jobId)}`,
    );
    syncHeaderJobSelect();
    await refreshOptimizerFromJob(jobId);
  } catch (error) {
    toast(error.message, "error");
  }
}

/* ------------------------------------------------------------------ */
/* Settings                                                            */
/* ------------------------------------------------------------------ */
/* Sprint 5 T1: 用纯函数 settingsBentoHtml 重渲染 Bento 概览（节点测试后
 * 刷新延迟卡）。state.llmNodeTests 由 renderSettingsView 与
 * llm-node-test action 维护。 */
async function renderSettingsView(app) {
  const [settings, status, nodes, rules] = await Promise.all([
    api("/api/settings"),
    api("/api/settings/status"),
    api("/api/llm/nodes").catch(() => []),
    api("/api/automation/rules").catch(() => []),
  ]);
  state.settings = settings;
  state.llmNodes = Array.isArray(nodes) ? nodes : [];
  state.automationRules = Array.isArray(rules) ? rules : [];
  const vocabulary = settings.classification_vocabulary;
  state.vocabulary = normalizeVocabulary(vocabulary);
  const activeNode = state.llmNodes.find((node) => node.is_active) || null;
  const activeLastTest = activeNode
    ? (state.llmNodeTests || {})[activeNode.node_id]
    : null;
  const latency = activeLastTest && activeLastTest.ok ? activeLastTest.latency_ms : null;
  const nodeCards = state.llmNodes
    .map((node) => llmNodeCardHtml(node, (state.llmNodeTests || {})[node.node_id]))
    .join("");
  app.innerHTML = `
    <div class="view view-scroll settings-view">
      <div class="settings-head">
        <div>
          <p>配置多个 LLM API 节点、超时护杠与粗筛规则引擎</p>
        </div>
        <div class="settings-head-actions">
          <span class="status-line"><span class="dot ${status.api_key_configured ? "dot-success" : "dot-warn"}" aria-hidden="true"></span>${status.api_key_configured ? "LLM 已配置" : "LLM 未配置"}</span>
          <button class="btn btn-outline btn-sm" type="button" data-action="reset-settings">恢复默认设置</button>
        </div>
      </div>
      ${settingsBentoHtml(activeNode, latency)}
      ${costGuardPanelHtml(settings, status.daily || {})}
      <section class="panel local-ingest-panel" data-local-ingest-panel>
        <div class="panel-head">
          <div>
            <h2>本地摄入 Token</h2>
            <p>油猴脚本访问 /api/jobs/local-ingest 的密钥</p>
          </div>
          <button class="btn btn-outline btn-sm" type="button" data-action="reset-local-ingest-token">重置</button>
        </div>
        <div class="panel-body">
          <div class="token-row">
            <code class="token-value" data-local-ingest-token>${esc(settings.local_ingest_token || "生成中…")}</code>
            <button class="btn btn-secondary btn-sm" type="button" data-action="copy-local-ingest-token">复制</button>
          </div>
          <p class="small muted">首次启动自动生成；重置后旧 Token 立即失效，需同步更新油猴脚本配置。</p>
        </div>
      </section>
      <div class="settings-main">
        <section class="panel console-main" data-llm-nodes-panel>
          <div class="panel-head">
            <div>
              <h2>LLM 节点</h2>
              <p>主节点与备用节点</p>
            </div>
            <button class="btn btn-primary btn-sm" type="button" data-action="llm-node-add">新增节点</button>
          </div>
          <div class="panel-body">
            <div class="llm-node-grid node-grid" data-llm-node-grid>
              ${nodeCards || `<div class="muted small" data-llm-node-empty>还没有配置节点，点击「新增节点」创建第一个。</div>`}
            </div>
            <form data-form="settings-eval-default" class="llm-eval-default">
              <label class="check-line">
                <input type="checkbox" name="eval_default" ${settings.eval_default ? "checked" : ""}>
                运行对齐时默认开启评估（幻觉检测 / JD 匹配分）
              </label>
              <div class="small muted">每任务额外一次 LLM 调用；工作台可按次覆盖。</div>
              <div class="row" style="margin-top:10px">
                <button class="btn btn-outline btn-sm" type="submit">保存评估开关</button>
              </div>
            </form>
          </div>
        </section>
        <aside class="panel" data-guardrails-panel>
          <div class="panel-head">
            <div>
              <h2>Guardrails</h2>
              <p>运行护栅与评估默认</p>
            </div>
          </div>
          <div class="guardrail-box">
            <div class="guardrail-row"><span>超时熔断</span><b>40s</b></div>
            <div class="guardrail-row"><span>并发额度</span><b>1</b></div>
            <div class="guardrail-row"><span>评估默认</span><label class="check-line"><input type="checkbox" checked> 默认运行对齐评估</label></div>
          </div>
          <div class="panel-head">
            <div>
              <h2>自动化规则</h2>
              <p>导入前置拦截</p>
            </div>
            <button class="btn btn-outline btn-sm" type="button" data-action="automation-rule-add">新增规则</button>
          </div>
          <div data-automation-rules-panel>${ruleListHtml(state.automationRules)}</div>
        </aside>
      </div>
      <form class="panel vocab-panel" data-form="settings-vocabulary">
        <div class="panel-head">
          <div>
            <h2>词表</h2>
            <p>岗位职能 / 职级 / 状态选项</p>
          </div>
          <button class="btn btn-secondary btn-sm" type="submit">保存词表</button>
        </div>
        <div class="panel-body">
          <div class="vocab-grid">
            <label><span>岗位职能</span><textarea name="job_functions" rows="6">${esc(vocabulary.job_functions.join("\n"))}</textarea></label>
            <label><span>职级</span><textarea name="seniorities" rows="4">${esc(vocabulary.seniorities.join("\n"))}</textarea></label>
            <label><span>状态</span><textarea name="statuses" rows="5">${esc(vocabulary.statuses.join("\n"))}</textarea></label>
          </div>
        </div>
      </form>
    </div>`;

  if (
    activeNode &&
    !activeLastTest &&
    !(state.llmNodeTestInflight || {})[activeNode.node_id]
  ) {
    state.llmNodeTestInflight = {
      ...(state.llmNodeTestInflight || {}),
      [activeNode.node_id]: true,
    };
    api(`/api/llm/nodes/${encodeURIComponent(activeNode.node_id)}/test`, {
      method: "POST",
    })
      .then((result) => {
        state.llmNodeTests = {
          ...(state.llmNodeTests || {}),
          [activeNode.node_id]: result,
        };
        updateSettingsBento($("#app-router-view"));
      })
      .catch(() => {
        /* keep the latency cell at — until the user tests explicitly */
      })
      .finally(() => {
        state.llmNodeTestInflight = {
          ...(state.llmNodeTestInflight || {}),
          [activeNode.node_id]: false,
        };
      });
  }
}

function updateSettingsBento(app = $("#app-router-view")) {
  if (!app) return;
  const mount = app.querySelector("[data-settings-bento]");
  if (!mount) return;
  const activeNode = (state.llmNodes || []).find((node) => node.is_active) || null;
  const lastTest = activeNode
    ? (state.llmNodeTests || {})[activeNode.node_id]
    : null;
  const latency = lastTest && lastTest.ok ? lastTest.latency_ms : null;
  mount.outerHTML = settingsBentoHtml(activeNode, latency);
}

/* ------------------------------------------------------------------ */
/* Event delegation                                                    */
/* ------------------------------------------------------------------ */

/* setWbMobilePane 实现在 events.js（F5：controls / diff 双面板）。 */

async function printTarget(kind, options = {}) {
  const printNode = $("#print-root");
  if (!printNode) return;
  let title = "ResuAlign";
  let body = "";
  if (kind === "resume") {
    const resumeId = state.route && state.route.resumeId;
    let resume = null;
    if (resumeId) {
      try {
        resume = await api(`/api/master-resumes/${encodeURIComponent(resumeId)}`);
      } catch {
        /* keep empty resume */
      }
    }
    title = resume ? resume.title : "简历";
    body =
      `<h1>${esc(title)}</h1>` +
      `<div class="print-meta">${resume ? `更新于 ${formatDate(resume.updated_at)} · 当前版本 v${resume.current_version}` : ""}</div>` +
      `<div class="resume-doc">${renderMarkdown(resume ? resume.content : "")}</div>`;
  } else if (kind === "final-draft") {
    const draft = state.wbFinalDraft;
    const job = state.wbJob || {};
    title = job.title || "定稿简历";
    body =
      `<h1>${esc(title)}</h1>` +
      `<div class="print-meta">${draft ? `保存于 ${formatDate(draft.updated_at)} · 第 ${draft.version} 版` : ""}</div>` +
      `<div class="resume-doc" data-final-draft-panel>${renderMarkdown(draft ? draft.draft : "")}</div>`;
  } else if (kind === "workbench") {
    const job = state.wbJob || {};
    const session = activeSessionForExport() || {};
    const result = state.wbResult || {};
    const sections = (result.tailored_resume && result.tailored_resume.sections) || {};
    const aligned = Object.values(sections).join("\n\n");
    const fallbackDraft =
      state.wbFinalDraft && state.wbFinalDraft.draft
        ? state.wbFinalDraft.draft
        : (session.alignment && session.alignment.draft) || "";
    const matchScore =
      (result.eval_score && result.eval_score.jd_match_score) ||
      result.score ||
      (session.gap && session.gap.score) ||
      "-";
    title = `${job.title || (session.job && session.job.title) || "工作台"} - AI 对齐稿`;
    body =
      `<h1>${esc(title)}</h1>` +
      `<div class="print-meta">匹配度 ${matchScore}/100</div>` +
      `<div class="resume-doc">${renderMarkdown(aligned || fallbackDraft)}</div>`;
  } else if (kind === "snapshot") {
    const snapshot = options || {};
    const job = state.wbJob || {};
    title = `${snapshot.job_title || job.title || "投递快照"} · 第 ${snapshot.version_index || 1} 版`;
    body =
      `<h1>${esc(title)}</h1>` +
      `<div class="print-meta">投递于 ${esc(snapshot.applied_at || formatDate(snapshot.created_at))}${snapshot.match_score != null ? ` · 匹配度 ${Math.round(snapshot.match_score)}` : " · 匹配度 —"}</div>` +
      `<div class="resume-doc">${renderMarkdown(snapshot.final_draft || "")}</div>`;
  } else if (kind === "diagnosis") {
    const resumeId = state.diagnosisResumeId || (state.route && state.route.resumeId);
    let content = "";
    if (resumeId) {
      try {
        const resume = await api(`/api/master-resumes/${encodeURIComponent(resumeId)}`);
        content = resume.content || "";
      } catch {
        /* keep diagnosis-only export */
      }
    }
    title = "简历诊断";
    body =
      `<h1>${esc(title)}</h1>` +
      `<div class="resume-doc">${renderMarkdown(buildDiagnosisMarkdown(content))}</div>`;
  }
  printNode.innerHTML = body;
  /* 黄金核心 2：A4 打印单页收敛——内容超一页时分级压缩字号/行高/间距，
   * 保证 Ctrl+P 导出的 PDF 收敛在 1 页，杜绝多出空白第二页。 */
  const resumeDoc = printNode.querySelector(".resume-doc");
  const textLen = resumeDoc ? resumeDoc.textContent.length : 0;
  printNode.classList.remove(
    "print-compact",
    "print-compact--tight",
    "print-compact--ultra",
  );
  if (textLen > 2400) {
    printNode.classList.add("print-compact--ultra");
  } else if (textLen > 1700) {
    printNode.classList.add("print-compact--tight");
  } else if (textLen > 1100) {
    printNode.classList.add("print-compact");
  }
  document.body.classList.add("is-printing");
  try {
    window.print();
  } finally {
    document.body.classList.remove("is-printing");
  }
}

/* Sprint 4 T3: 复制 Markdown 到剪贴板（navigator.clipboard + textarea 兜底，
 * 复用 split-canvas.js fallbackCopy 的既有模式）。 */
function copyMarkdownToClipboard(text) {
  const onOk = () => toast("简历 Markdown 已复制", "success");
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(onOk, () => fallbackCopyMarkdown(text));
  } else {
    fallbackCopyMarkdown(text);
  }
}

function fallbackCopyMarkdown(text) {
  const node = document.createElement("textarea");
  node.value = text;
  node.style.position = "fixed";
  node.style.opacity = "0";
  document.body.append(node);
  node.select();
  try {
    document.execCommand("copy");
    toast("简历 Markdown 已复制", "success");
  } catch {
    toast("复制失败，请手动选择", "error");
  }
  node.remove();
}

function copyTextToClipboard(text, successMessage = "已复制") {
  const onOk = () => toast(successMessage, "success");
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(onOk, () => fallbackCopyText(text, successMessage));
  } else {
    fallbackCopyText(text, successMessage);
  }
}

function fallbackCopyText(text, successMessage) {
  const node = document.createElement("textarea");
  node.value = text;
  node.style.position = "fixed";
  node.style.opacity = "0";
  document.body.append(node);
  node.select();
  try {
    document.execCommand("copy");
    toast(successMessage, "success");
  } catch {
    toast("复制失败，请手动选择", "error");
  }
  node.remove();
}

function todayDateString() {
  const today = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;
}

async function persistApplicationRecord(job, appliedAt, button, message) {
  await api(`/api/jobs/${encodeURIComponent(job.job_id)}`, {
    method: "PATCH",
    body: JSON.stringify({ status: "applied", applied_at: appliedAt }),
  });
  toast(message, "success");
  if (button && button.closest(".modal-backdrop")) closeModal();
  await render();
}

function findApplicationSnapshot(snapshotId) {
  const entries = state.applicationSnapshots || {};
  for (const jobId of Object.keys(entries)) {
    const found = (entries[jobId].snapshots || []).find(
      (snapshot) => String(snapshot.snapshot_id) === String(snapshotId),
    );
    if (found) return found;
  }
  return null;
}

function findApplicationEntry(jobId) {
  const entries = state.applicationSnapshots || {};
  return entries[jobId] || null;
}

/* MVP-09: 定稿导出统一走 POST /api/jobs/{job_id}/exports。PDF 响应把
 * print-html 写入 #print-root 后触发打印；Markdown/JSON 用响应里的
 * canonical 内容与文件名下载，不再从 transient session 拼装。 */
async function exportFinalDraft(format) {
  const jobId = (state.wbJob && state.wbJob.job_id) || (state.route && state.route.jobId);
  if (!jobId) {
    toast("当前没有可导出的岗位", "error");
    return;
  }
  let body;
  try {
    body = await api(`/api/jobs/${encodeURIComponent(jobId)}/exports`, {
      method: "POST",
      body: JSON.stringify({ format }),
    });
  } catch (error) {
    toast(error.message || "导出失败", "error");
    return;
  }
  if (format === "pdf") {
    const printNode = $("#print-root");
    if (!printNode) return;
    printNode.innerHTML = body.render === "print-html"
      ? (body.content || "")
      : `<h1>${esc(body.job_title || "定稿简历")}</h1><div class="resume-doc">${renderMarkdown(body.content || "")}</div>`;
    window.print();
    printNode.innerHTML = "";
    toast("已生成打印预览", "success");
    return;
  }
  const ext = format === "json" ? "json" : "md";
  /* Bug-03: JSON 导出下载整个结构化响应（meta/sections/skills/diffs），
   * 而不是把 Markdown 字符串当 JSON 写出。 */
  const payload =
    format === "json" ? JSON.stringify(body, null, 2) : body.content || "";
  download(
    body.filename || `resualign-${body.job_title || "job"}.${ext}`,
    payload,
    format === "json"
      ? "application/json;charset=utf-8"
      : "text/markdown;charset=utf-8",
  );
  toast(`已导出 ${body.filename || "定稿"}`, "success");
}

const actions = {
  reload: () => render(),
  /* v2.0: 新建主简历走模态框（主视图无内联 textarea）。 */
  "new-resume": () => openResumeCreator(),
  "cancel-new-resume": () => closeModal(),
  "upload-resume": () => {
    const input = $("#resume-upload-input");
    if (input) input.click();
  },
  "open-resume-archive": (button) => navigate("resume", button.dataset.id),
  "back-resume-center": () => {
    window.location.hash = "#/resume/list";
  },
  "print-resume": () => printTarget("resume"),
  "print-workbench": () => printTarget("workbench"),
  /* Sprint 4 T3: 复制简历 Markdown（data-action=copy-resume-md，data-id=resume_id） */
  "copy-resume-md": async (button) => {
    const resumeId = button.dataset.id || (state.route && state.route.resumeId);
    if (!resumeId) return;
    try {
      const resume = await api(`/api/master-resumes/${encodeURIComponent(resumeId)}`);
      copyMarkdownToClipboard(resume.content || "");
    } catch (error) {
      toast(error.message || "简历加载失败，无法复制", "error");
    }
  },
  /* Sprint 4 T3: 版本时间线预览 —— 切换主 Sheet 为所选版本内容。 */
  "preview-version": (button) => {
    const version = Number(button.dataset.version);
    const target = (state.resumeVersions || []).find(
      (item) => Number(item.version) === version,
    );
    if (!target) {
      toast("未找到该版本", "error");
      return;
    }
    const sheet = $("[data-resume-sheet-doc]");
    const bar = $("[data-resume-preview-bar]");
    const label = $("[data-preview-version]");
    if (sheet) sheet.innerHTML = renderMarkdown(target.content);
    if (bar) bar.hidden = false;
    if (label) label.textContent = `v${version}`;
    $$("[data-version-item]").forEach((item) => {
      item.classList.toggle("is-active", Number(item.dataset.version) === version);
    });
    toast(`正在预览 v${version}`, "info");
  },
  "restore-current-preview": () => {
    const sheet = $("[data-resume-sheet-doc]");
    const bar = $("[data-resume-preview-bar]");
    if (sheet) sheet.innerHTML = renderMarkdown(state.resumeCurrentContent || "");
    if (bar) bar.hidden = true;
    $$("[data-version-item]").forEach((item) => item.classList.remove("is-active"));
    toast("已返回当前版本", "info");
  },
  /* v2.0 双态编辑：全景渲染 View ↔ 隐藏 Textarea 零缝切换（保留模态框编辑）。
   * 保存走 data-form="resume-edit" 的既有 handleForm 提交，本 action 只负责
   * 切换两个面板的可见性。 */
  "toggle-resume-inline-edit": (button) => {
    const sheet = button && button.closest("[data-resume-sheet]");
    const doc = $("[data-resume-sheet-doc]", sheet);
    const form = $("[data-resume-inline-edit]", sheet);
    if (!doc || !form) return;
    const entering = form.hidden;
    form.hidden = !entering;
    doc.hidden = entering;
    if (entering) {
      const textarea = form.querySelector("textarea[name='content']");
      if (textarea) textarea.focus();
    }
    document.body.classList.toggle("resume-inline-editing", entering);
  },
  "cancel-resume-inline-edit": (button) => {
    const sheet = button && button.closest("[data-resume-sheet]");
    const doc = $("[data-resume-sheet-doc]", sheet);
    const form = $("[data-resume-inline-edit]", sheet);
    if (!doc || !form) return;
    /* 放弃未保存改动：重置 textarea 为当前已渲染内容 */
    const textarea = form.querySelector("textarea[name='content']");
    if (textarea) textarea.value = state.resumeCurrentContent || "";
    form.hidden = true;
    doc.hidden = false;
    document.body.classList.remove("resume-inline-editing");
  },
  "export-diagnosis": () => printTarget("diagnosis"),
  "export-diagnosis-md": async () => {
    const resumeId =
      state.diagnosisResumeId || (state.route && state.route.resumeId);
    let content = "";
    if (resumeId) {
      try {
        const resume = await api(
          `/api/master-resumes/${encodeURIComponent(resumeId)}`,
        );
        content = resume.content || "";
      } catch {
        /* keep the diagnosis-only export */
      }
    }
    download(
      `resume-diagnosis.md`,
      buildDiagnosisMarkdown(content),
      "text/markdown;charset=utf-8",
    );
  },
  "diagnose-resume": async (button) => {
    const resumeId = button.dataset.id || state.diagnosisResumeId;
    if (!resumeId) return;
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = "诊断中...";
    renderDiagnosisProgress({
      status: "queued",
      stage: "",
      message: "排队中...",
      elapsed_seconds: 0,
    });
    try {
      const response = await api(
        `/api/master-resumes/${encodeURIComponent(resumeId)}/diagnose`,
        { method: "POST" },
      );
      state.diagnosis = { job_id: response.job_id, ...response };
      state.diagnosisResumeId = resumeId;
      startDiagnosisPolling(response.job_id, resumeId);
      toast("诊断任务已排队，正在运行", "success");
    } catch (error) {
      button.disabled = false;
      button.textContent = originalText;
      button.classList.remove("is-loading");
      renderDiagnosisError({ status: "failed", error: error.message });
    }
  },
  "rerun-diagnosis": (button) => {
    const diagnoseBtn = $("[data-action='diagnose-resume']");
    if (diagnoseBtn && !diagnoseBtn.disabled) {
      diagnoseBtn.click();
    } else if (button.dataset.id) {
      actions["diagnose-resume"](button);
    }
  },
  "cancel-diagnosis": async () => {
    const snapshot = state.diagnosis;
    if (!snapshot || !snapshot.job_id) return;
    if (snapshot.status === "queued") {
      await api(
        `/api/jobs/${encodeURIComponent(snapshot.job_id)}/cancel`,
        { method: "POST" },
      );
      stopDiagnosisPolling();
      renderDiagnosisError({
        status: "canceled",
        error: "Canceled by user",
      });
      toast("诊断任务已取消", "success");
    } else {
      stopDiagnosisPolling();
      toast("任务将继续在后台完成，结果仍会保存；已停止本地等待", "info");
    }
  },
  /* AI 优化（xzjobs 式模块化润色）：运行 → 轮询 → 逐条采纳/忽略 →
   * 全部采纳 → 应用已采纳为新版本。 */
  "optimize-resume": async (button) => {
    const resumeId =
      button.dataset.id ||
      state.optimizeResumeId ||
      (state.route && state.route.resumeId);
    if (!resumeId) return;
    const panel = button.closest("[data-optimize-panel]");
    const jdInput = panel && panel.querySelector("[data-optimize-jd]");
    const jdText = jdInput ? jdInput.value.trim() : (state.optimizeJdText || "");
    stopOptimizePolling();
    state.optimizeResumeId = resumeId;
    state.optimizeJobResumeId = resumeId;
    state.optimizeJdText = jdText;
    state.optimizeAccepted = {};
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = "排队中...";
    renderOptimizeProgress({
      status: "queued",
      stage: "",
      message: "排队中...",
      elapsed_seconds: 0,
    });
    try {
      const response = await api(
        `/api/master-resumes/${encodeURIComponent(resumeId)}/optimize`,
        { method: "POST", body: JSON.stringify({ jd_text: jdText || null }) },
      );
      state.optimizeJob = { job_id: response.job_id, status: "queued", result: null };
      startOptimizePolling(response.job_id, resumeId);
      toast("优化任务已排队：先出整体分析，再逐条润色项目经历", "success");
    } catch (error) {
      button.disabled = false;
      button.textContent = originalText;
      button.classList.remove("is-loading");
      renderOptimizeError({ status: "failed", error: error.message });
    }
  },
  "optimize-rerun": (button) => {
    const runBtn = $("[data-optimize-panel] [data-action='optimize-resume']");
    if (runBtn && !runBtn.disabled) {
      runBtn.click();
    } else if (button.dataset.id) {
      actions["optimize-resume"](button);
    }
  },
  "cancel-optimize": async () => {
    const job = state.optimizeJob;
    if (!job || !state.optimizePolling) return;
    if (job.status === "queued") {
      await api(
        `/api/jobs/${encodeURIComponent(job.job_id)}/cancel`,
        { method: "POST" },
      );
      stopOptimizePolling();
      renderOptimizeError({ status: "canceled", error: "Canceled by user" });
      toast("优化任务已取消", "success");
    } else {
      stopOptimizePolling();
      toast("任务将继续在后台完成，结果仍会保存；已停止本地等待", "info");
    }
  },
  "optimize-accept-item": (button) => {
    const key = button.dataset.optimizeKey;
    if (key == null) return;
    state.optimizeAccepted = { ...(state.optimizeAccepted || {}) };
    state.optimizeAccepted[key] = true;
    refreshOptimizePanel();
  },
  "optimize-reject-item": (button) => {
    const key = button.dataset.optimizeKey;
    if (key == null) return;
    state.optimizeAccepted = { ...(state.optimizeAccepted || {}) };
    state.optimizeAccepted[key] = false;
    refreshOptimizePanel();
  },
  "optimize-accept-all": () => {
    const modules = state.optimizeModules || [];
    const next = {};
    let okCount = 0;
    modules.forEach((item, key) => {
      if (item && item.status === "ok") {
        next[String(key)] = true;
        okCount += 1;
      }
    });
    state.optimizeAccepted = next;
    refreshOptimizePanel();
    toast(`已全部采纳 ${okCount} 条优化`, "success");
  },
  "optimize-apply-accepted": async () => {
    const resumeId =
      state.optimizeResumeId || (state.route && state.route.resumeId);
    if (!resumeId) return;
    const items = collectAcceptedOptimizeItems(
      state.optimizeModules || [],
      state.optimizeAccepted || {},
    );
    if (!items.length) {
      toast("请先采纳至少一条优化", "error");
      return;
    }
    const btn = $("[data-action='optimize-apply-accepted']");
    if (btn) btn.disabled = true;
    try {
      const body = await api(
        `/api/master-resumes/${encodeURIComponent(resumeId)}/optimize/apply`,
        { method: "POST", body: JSON.stringify({ items }) },
      );
      toast(`已应用 ${(body && body.applied_count) || items.length} 条优化为新版本`, "success");
      render();
    } catch (error) {
      const again = $("[data-action='optimize-apply-accepted']");
      if (again) again.disabled = false;
      toast(error.message, "error");
    }
  },
  "export-resume-md": async (button) => {
    const resume = await api(
      `/api/master-resumes/${encodeURIComponent(button.dataset.id)}`,
    );
    download(`resume-${resume.title}.md`, resume.content || "", "text/markdown;charset=utf-8");
  },
  "edit-resume": (button) => openResumeEditor(button.dataset.id),
  "delete-resume": async (button) => {
    if (!window.confirm("确定删除这份主简历及全部版本？")) return;
    await api(`/api/master-resumes/${encodeURIComponent(button.dataset.id)}`, { method: "DELETE" });
    toast("主简历已删除", "success");
    if (state.route.resumeId === button.dataset.id) navigate("resume");
    else render();
  },
  "rollback-resume": async (button) => {
    await api(`/api/master-resumes/${encodeURIComponent(button.dataset.id)}/rollback`, {
      method: "POST",
      body: JSON.stringify({ version: Number(button.dataset.version) }),
    });
    toast(`已回滚到 v${button.dataset.version}`, "success");
    render();
  },
  "show-add-job": () => {
    $('[data-form="job-create"]').hidden = false;
    $('[data-form="job-import"]').hidden = true;
  },
  "cancel-add-job": () => {
    $('[data-form="job-create"]').hidden = true;
  },
  /* 后端已移除 JD 链接抓取（crawler 下线）：表单不再提供 JD 链接模式，
   * 保留该动作仅作兜底提示，防止历史遗留按钮误触。 */
  "parse-jd-link": () => {
    toast(
      "后端已不再抓取 JD 链接：请用油猴插件一键抓取，或粘贴 JD 文本",
      "info",
    );
  },
  "show-import": () => {
    $('[data-form="job-import"]').hidden = false;
    $('[data-form="job-create"]').hidden = true;
  },
  "cancel-import": () => {
    $('[data-form="job-import"]').hidden = true;
  },
  "clear-filters": () => {
    state.filters = {
      job_function: "",
      seniority: "",
      status: "",
      search: "",
      sort: "updated_at_desc",
    };
    state.offset = 0;
    render();
  },
  "prev-page": () => {
    state.offset = Math.max(0, state.offset - state.limit);
    render();
  },
  "next-page": () => {
    state.offset += state.limit;
    render();
  },
  "edit-job": (button) => {
    const job = state.jobs.find((item) => item.job_id === button.dataset.id);
    if (job) openJobEditor(job);
  },
  "open-job-timeline": async (button) => {
    let job = (state.jobs || []).find(
      (item) => item.job_id === button.dataset.id,
    );
    if (!job) {
      job = await api(`/api/jobs/${encodeURIComponent(button.dataset.id)}`);
    }
    if (job) openJobDetail(job);
  },
  "open-job-followup": async (button) => {
    let job = (state.jobs || []).find(
      (item) => item.job_id === button.dataset.id,
    );
    if (!job) {
      try {
        job = await api(`/api/jobs/${encodeURIComponent(button.dataset.id)}`);
      } catch (error) {
        toast(error.message || "岗位不存在", "error");
        return;
      }
    }
    if (job) {
      showModal(
        `安排跟进 · ${job.title || "该岗位"}`,
        jobFollowupFormHtml(job),
      );
    }
  },
  "record-application": async (button) => {
    const jobId = button.dataset.id || (state.wbJob && state.wbJob.job_id);
    if (!jobId) return;
    let job = state.wbJob && state.wbJob.job_id === jobId ? state.wbJob : null;
    if (!job) {
      try {
        job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
      } catch (error) {
        toast(error.message || "岗位不存在", "error");
        return;
      }
    }
    if (jobStatusRank(job.status) >= jobStatusRank("applied")) {
      showModal(
        "再次记录投递",
        `<p>岗位已是「${esc(jobStatusLabel(job.status))}」。再次记录会追加一轮不可篡改的投递快照，不会改变当前状态或时间线。</p>
        <div class="actions">
          <button class="btn btn-ghost" type="button" data-action="close-modal">取消</button>
          <button class="btn btn-primary" type="button" data-action="confirm-append-application" data-id="${esc(job.job_id)}">确认追加</button>
        </div>`,
      );
      return;
    }
    const activeSession = activeSessionForExport();
    const draft =
      (state.wbFinalDraft && state.wbFinalDraft.draft) ||
      job.final_draft ||
      (activeSession && activeSession.alignment && activeSession.alignment.draft) ||
      "";
    if (!draft) {
      toast("请先生成并保存定稿，再记录投递", "error");
      return;
    }
    await persistApplicationRecord(
      job,
      todayDateString(),
      button,
      "已记录投递",
    );
  },
  "confirm-append-application": async (button) => {
    const jobId = button.dataset.id;
    if (!jobId) return;
    let job = (state.jobs || []).find((item) => item.job_id === jobId);
    if (!job) {
      try {
        job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
      } catch (error) {
        toast(error.message || "岗位不存在", "error");
        return;
      }
    }
    await persistApplicationRecord(
      job,
      todayDateString(),
      button,
      "已追加投递快照",
    );
  },
  "toggle-batch-panel": (button) => {
    const wrap = button.parentElement && button.parentElement.querySelector("[data-batch-wrap]");
    const panel = wrap || document.querySelector("[data-batch-wrap]");
    if (panel) panel.hidden = !panel.hidden;
  },
  "delete-job": (button) => {
    /* #U9: replace window.confirm with the in-app modal. The confirm
       button reuses the document-level action delegation via a custom
       data-action so modal content needs no extra wiring. */
    const job = (state.jobs || []).find(
      (item) => item.job_id === button.dataset.id,
    );
    const title = job && job.title ? job.title : "该岗位";
    showModal(
      "删除岗位",
      `<p>确定删除「${esc(title)}」？此操作不可恢复。</p>
       <div class="actions">
         <button class="btn btn-ghost" type="button" data-action="close-modal">取消</button>
         <button class="btn btn-danger" type="button" data-action="confirm-delete-job" data-id="${esc(button.dataset.id)}">确认删除</button>
       </div>`,
    );
  },
  "confirm-delete-job": async (button) => {
    const jobId = button.dataset.id;
    if (!jobId) return;
    closeModal();
    await api(`/api/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });
    toast("岗位已删除", "success");
    render();
  },
  "reclassify-job": async (button) => {
    const job = state.jobs.find((item) => item.job_id === button.dataset.id);
    const hasManualFields =
      job &&
      Boolean(
        (job.job_function || "").trim() ||
          (job.seniority || "").trim() ||
          (job.tech_tags || []).length,
      );
    if (
      hasManualFields &&
      !window.confirm(
        "重新分类会用 LLM 结果覆盖当前职能、级别和标签，是否继续？",
      )
    ) {
      return;
    }
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = "分类中...";
    button.classList.add("is-loading");
    try {
      const updated = await api(
        `/api/jobs/${encodeURIComponent(button.dataset.id)}/reclassify`,
        { method: "POST" },
      );
      toast(
        `分类成功：${updated.job_function || "未分类"} · ${updated.seniority || "未知"} · ${(updated.tech_tags || []).join("/") || "无标签"}`,
        "success",
      );
      render();
    } catch (error) {
      toast(
        `重新分类失败：${error.message}，岗位仍为分类待定，可稍后重试`,
        "error",
      );
    } finally {
      button.disabled = false;
      button.textContent = originalText;
      button.classList.remove("is-loading");
    }
  },
  "recompute-match": async (button) => {
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = "评分中...";
    button.classList.add("is-loading");
    try {
      const updated = await api(
        `/api/jobs/${encodeURIComponent(button.dataset.id)}/match`,
        { method: "POST" },
      );
      toast(
        updated.match_reason || `匹配分已更新：${updated.match_score ?? "—"}`,
        "success",
      );
      renderKanban($("#app-router-view"));
    } catch (error) {
      toast(error.message, "error");
      button.disabled = false;
      button.textContent = originalText;
      button.classList.remove("is-loading");
    }
  },
  "open-workspace": (button) => navigate("workspace", button.dataset.id),
  /* Sprint 1 T3: 技能缺口热力条点击 → 跳到最近一个含该技能的岗位工作台；
   * 无匹配岗位时回退到岗位库并设置搜索关键词（renderKanban 读取
   * state.filters 回填搜索框）。 */
  "goto-skill": async (button) => {
    const skill = String(button.dataset.skill || "").trim();
    if (!skill) return;
    let jobs = state.jobs;
    if (!Array.isArray(jobs) || jobs.length === 0) {
      try {
        jobs = await api("/api/jobs?limit=200");
      } catch {
        jobs = [];
      }
    }
    const skillLower = skill.toLowerCase();
    const match = (jobs || []).find((job) => {
      const profile = job && job.jd_profile;
      const skills = [
        ...(profile && Array.isArray(profile.must_have_skills)
          ? profile.must_have_skills
          : []),
        ...(Array.isArray(job && job.tech_tags) ? job.tech_tags : []),
      ];
      return skills.some((item) => {
        const s = String(item || "").toLowerCase();
        /* Dashboard gap labels can be longer than a bare skill keyword;
           accept substring matches either way (mirrors highlightSkillGap). */
        return s === skillLower || s.includes(skillLower) || skillLower.includes(s);
      });
    });
    if (match && match.job_id) {
      window.location.hash = `#/workspace/${encodeURIComponent(match.job_id)}?skill=${encodeURIComponent(skill)}`;
      return;
    }
    state.filters = { ...state.filters, search: skill };
    navigate("jobs");
    toast(`未找到要求「${skill}」的岗位，已在岗位库带关键词搜索`, "info");
  },
  "open-job-detail": async (button) => {
    let job = (state.jobs || []).find(
      (item) => item.job_id === button.dataset.id,
    );
    if (!job) {
      try {
        job = await api(`/api/jobs/${encodeURIComponent(button.dataset.id)}`);
      } catch (error) {
        toast(error.message || "岗位不存在", "error");
        return;
      }
    }
    if (job) openJobDetail(job);
  },
  "open-source-url": (button) => {
    const url = String(button.dataset.url || "").trim();
    if (!url) return;
    if (!isJdUrl(url)) {
      toast("链接不是有效的 http(s) 地址", "error");
      return;
    }
    window.open(url, "_blank", "noopener,noreferrer");
  },
  "bulk-move-status": async () => {
    const selected = $$("[data-board-check]:checked").map(
      (input) => input.value,
    );
    const status = $("[data-board-bulk-status]").value;
    if (!selected.length || !status) {
      toast("请先选择岗位和目标状态", "error");
      return;
    }
    const body = await api("/api/jobs/bulk-status", {
      method: "POST",
      body: JSON.stringify({ job_ids: selected, status }),
    });
    toast(
      `批量移动完成：${body.updated} / ${body.total} 条`,
      body.updated === body.total ? "success" : "error",
    );
    render();
  },
  "goto-selected-job": () => {
    const select = $("[data-wb-job-select]");
    if (select && select.value) navigate("workspace", select.value);
  },
  "back-workspace": () => navigate("workspace"),
  "toggle-raw-jd": () => {
    state.wbRawJdOpen = !state.wbRawJdOpen;
    render();
  },
  "open-command-panel": () => openCommandPanel(),
  "close-command-panel": () => closeCommandPanel(),
  "back-to-jobs": () => navigate("jobs"),
  "go-resumes": () => navigate("resume"),
  "go-jobs": () => navigate("jobs"),
  "reset-settings": async () => {
    await api("/api/settings/reset", { method: "POST" });
    toast("已恢复默认设置", "success");
    render();
  },
  "copy-local-ingest-token": () => {
    const token = state.settings && state.settings.local_ingest_token;
    if (!token) {
      toast("本地摄入 Token 尚未生成", "error");
      return;
    }
    copyTextToClipboard(token, "本地摄入 Token 已复制");
  },
  "reset-local-ingest-token": async () => {
    const body = await api("/api/settings/local-ingest-token/reset", {
      method: "POST",
    });
    if (state.settings) {
      state.settings.local_ingest_token = body.local_ingest_token;
    }
    const node = $("[data-local-ingest-token]");
    if (node) node.textContent = body.local_ingest_token;
    toast("本地摄入 Token 已重置，请同步更新油猴脚本", "success");
  },
  /* Sprint 5 T2: LLM 节点管理（新增 / 编辑 / 测试 / 激活 / 删除）。 */
  "llm-node-add": () => {
    showModal("新增 LLM 节点", llmNodeFormHtml(null));
  },
  "llm-node-edit": (button) => {
    const node = (state.llmNodes || []).find(
      (item) => item.node_id === button.dataset.id,
    );
    if (!node) {
      toast("节点不存在或已删除", "error");
      return;
    }
    showModal(`编辑节点「${node.name || "未命名"}」`, llmNodeFormHtml(node));
  },
  "llm-node-test": async (button) => {
    const nodeId = button.dataset.id;
    if (!nodeId) return;
    const card = button.closest("[data-llm-node-card]");
    const resultNode = card && card.querySelector("[data-llm-node-test-result]");
    const originalText = button.textContent;
    if (resultNode) {
      resultNode.innerHTML =
        '<div class="form-success" role="status">正在测试连通性…</div>';
    }
    button.disabled = true;
    button.textContent = "测试中...";
    button.classList.add("is-loading");
    try {
      const result = await api(
        `/api/llm/nodes/${encodeURIComponent(nodeId)}/test`,
        { method: "POST" },
      );
      state.llmNodeTests = { ...(state.llmNodeTests || {}), [nodeId]: result };
      if (resultNode) resultNode.innerHTML = nodeTestResultHtml(result);
      updateSettingsBento($("#app-router-view"));
      toast(
        result.ok ? "节点连通正常" : "节点测试失败，请检查配置",
        result.ok ? "success" : "error",
      );
    } catch (error) {
      if (resultNode) {
        resultNode.innerHTML = `<div class="form-error" role="alert">${esc(error.message)}</div>`;
      }
      toast(error.message, "error");
    } finally {
      button.disabled = false;
      button.textContent = originalText;
      button.classList.remove("is-loading");
    }
  },
  "llm-node-activate": async (button) => {
    const nodeId = button.dataset.id;
    if (!nodeId) return;
    await api(`/api/llm/nodes/${encodeURIComponent(nodeId)}/activate`, {
      method: "POST",
    });
    toast("已切换为当前生效节点", "success");
    render();
  },
  "llm-node-delete": (button) => {
    const node = (state.llmNodes || []).find(
      (item) => item.node_id === button.dataset.id,
    );
    const name = node && node.name ? node.name : "该节点";
    showModal(
      "删除 LLM 节点",
      `<p>确定删除「${esc(name)}」？删除后该节点配置将不可恢复。</p>
       <div class="actions">
         <button class="btn btn-ghost" type="button" data-action="close-modal">取消</button>
         <button class="btn btn-danger" type="button" data-action="confirm-delete-llm-node" data-id="${esc(button.dataset.id)}">确认删除</button>
       </div>`,
    );
  },
  "confirm-delete-llm-node": async (button) => {
    const nodeId = button.dataset.id;
    if (!nodeId) return;
    closeModal();
    await api(`/api/llm/nodes/${encodeURIComponent(nodeId)}`, {
      method: "DELETE",
    });
    toast("节点已删除", "success");
    render();
  },
  /* Sprint 5 T4: 自动化规则（新增 Modal / 删除；开关走 change 委托）。 */
  "automation-rule-add": () => {
    showModal("新增自动化规则", ruleFormHtml());
  },
  "automation-rule-delete": async (button) => {
    const ruleId = button.dataset.id;
    if (!ruleId) return;
    await api(`/api/automation/rules/${encodeURIComponent(ruleId)}`, {
      method: "DELETE",
    });
    toast("规则已删除", "success");
    render();
  },
  "analyze-jd": async () => {
    try {
      await analyzeActiveJd();
      toast("已开始解析 JD", "success");
  } catch (error) {
    if (isApiKeyUnconfigured(error)) {
        renderApiKeyGuide($("#app-router-view"));
      } else {
        toast(error.message || "JD 解析失败", "error");
      }
    }
  },
  "run-alignment": () => {
    const form = $("[data-form='split-align']");
    if (!form) {
      toast("请先在右侧「优化设置」中配置主简历", "error");
      return;
    }
    if (typeof form.requestSubmit === "function") {
      form.requestSubmit();
    } else {
      form.dispatchEvent(
        new window.Event("submit", { bubbles: true, cancelable: true }),
      );
    }
  },
  "open-optimizer": (button) => navigate("workspace", button.dataset.id),
  /* Phase A5: 岗位库「批量对齐」——对 idle/failed 岗位逐个排队工作台对齐，
   * 使用最近创建的主简历。点击后即时反馈进度，完成自动刷新看板。 */
  "batch-align-pending": async () => {
    const pending = (state.jobs || []).filter(
      (job) => job && (job.alignment_status === "idle" || job.alignment_status === "failed"),
    );
    if (!pending.length) {
      toast("没有待对齐的岗位（idle / 失败）", "info");
      return;
    }
    const resumes = await api("/api/master-resumes?limit=1");
    const resume = (resumes && resumes[0]) || null;
    if (!resume) {
      toast("请先创建一份主简历，再批量对齐", "error");
      return;
    }
    const resumeId = resume.resume_id || resume.id;
    const button = $("[data-action='batch-align-pending']");
    if (button) button.disabled = true;
    let queuedCount = 0;
    let skipped = 0;
    try {
      for (const job of pending) {
        try {
          await api(`/api/jobs/${encodeURIComponent(job.job_id)}/workbench`, {
            method: "POST",
            body: JSON.stringify({
              master_resume_id: resumeId,
              granularity: "medium",
            }),
          });
          queuedCount += 1;
        } catch (error) {
          skipped += 1;
          toast(`「${job.title}」排队失败：${error.message || "未知错误"}`, "error");
        }
      }
      toast(
        `已排队 ${queuedCount} 个岗位的对齐${skipped ? `，${skipped} 个失败` : ""}，完成后可刷新查看`,
        queuedCount ? "success" : "error",
      );
    } finally {
      if (button) button.disabled = false;
      setTimeout(() => renderKanban($("#app-router-view")), 1500);
    }
  },
  /* #17: live 工作台「对比视图」——复用 buildLiveCompareHtml 的文档润色
   * 内联建议流，只读弹窗展示，不动卡片的逐条采纳交互。 */
  "toggle-live-compare": async () => {
    const session = activeSessionForExport();
    if (!session) {
      toast("暂无对齐会话，请先运行一次对齐", "error");
      return;
    }
    const alignment = session.alignment || {};
    if (!(alignment.diffs || []).length) {
      toast("暂无修改项可对比", "info");
      return;
    }
    let originalContent = "";
    const resumeId =
      (session.resume && session.resume.selected_resume_id) || null;
    if (resumeId) {
      try {
        const resume = await api(
          `/api/master-resumes/${encodeURIComponent(resumeId)}`,
        );
        originalContent = resume.content || "";
      } catch {
        originalContent = "";
      }
    }
    showModal(
      "对比视图 · 原版 vs 优化版",
      `${buildLiveCompareHtml(session, originalContent)}<div class="actions"><button class="btn btn-secondary btn-sm" type="button" data-action="close-modal">关闭</button></div>`,
    );
    const modal = $(".modal-backdrop .modal");
    if (modal) modal.classList.add("modal--wide");
  },
  /* F4: 简历诊断结果 → 用这份简历去对齐。跳到最近一个岗位的工作台并带上
   * ?resume= 深链参数（split-canvas 会预选该主简历）；岗位库为空时跳到
   * #/workspace?resume=<id>，工作台空态让用户先建/选岗位。 */
  "diagnosis-to-align": async (button) => {
    const resumeId = button.dataset.id;
    if (!resumeId) {
      toast("缺少简历信息，请重试诊断", "error");
      return;
    }
    let target = "";
    try {
      const jobs = await api("/api/jobs?limit=1");
      if (Array.isArray(jobs) && jobs.length) target = jobs[0].job_id;
    } catch {
      /* fall through to the job-less route */
    }
    window.location.hash = target
      ? `#/workspace/${encodeURIComponent(target)}?resume=${encodeURIComponent(resumeId)}`
      : `#/workspace?resume=${encodeURIComponent(resumeId)}`;
  },
  "accept-bullet": async (button) => {
    const jobId = button.dataset.id;
    const diffId = button.dataset.diffId;
    /* T2: 采纳前记录当前 Live Sheet 草稿，便于采纳成功后做增量 patch。 */
    const prevDraft = getLiveSheetDraft();
    const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    const resumeId = job.workbench_resume_id;
    if (!resumeId) {
      toast("请先运行一次对齐以固定主简历", "error");
      return;
    }
    const diffs = job.diffs || [];
    let diff = diffs.find((item) => item.diff_id === diffId);
    if (!diff) {
      toast("该条建议不在当前对齐结果中", "error");
      return;
    }
    /* 黄金核心 1：原地编辑采纳——若卡片处于编辑态且用户改写了建议文本，
     * 采纳时使用编辑后的文本而非 AI 原稿（补全量化数字等就地落稿）。 */
    const diffCardNode = $(
      `[data-diff-id="${CSS.escape(diffId)}"]`,
      $("#app-router-view"),
    );
    const bulletEditor = diffCardNode
      ? diffCardNode.querySelector("[data-bullet-editor]")
      : null;
    const editedText = bulletEditor ? bulletEditor.value.trim() : "";
    if (bulletEditor && !editedText) {
      toast("编辑后的建议文本不能为空", "error");
      return;
    }
    if (editedText && editedText !== diff.proposed) {
      diff = { ...diff, proposed: editedText };
    }
    /* U7: 每条采纳都在当前工作草稿上增量合并，不再从原始简历重建，
     * 连续采纳多条时前一条不会丢失。 */
    const currentAccepted = new Set(
      (state.wbAcceptedBullets || {})[jobId] || [],
    );
    if (currentAccepted.has(diffId)) {
      toast("该条已采纳过", "info");
      return;
    }
    const resume = await api(`/api/master-resumes/${encodeURIComponent(resumeId)}`);
    const base =
      (state.wbWorkingDraft && state.wbWorkingDraft.jobId === jobId
        ? state.wbWorkingDraft.draft
        : null) ||
      job.final_draft ||
      resume.content ||
      "";
    const draft = applyDiffToDraft(base, diff);
    state.wbWorkingDraft = { jobId, draft };
    const acceptedIds = [...currentAccepted, diffId];
    state.wbAcceptedBullets = {
      ...state.wbAcceptedBullets,
      [jobId]: acceptedIds,
    };
    await api(`/api/jobs/${encodeURIComponent(jobId)}/final-draft`, {
      method: "POST",
      body: JSON.stringify({ draft, accepted_diff_ids: acceptedIds }),
    });
    /* T2: 采纳成功后先做 Live Sheet 毫秒级增量更新（liveSheetPatch 只 patch
     * 变化行 + 高亮新增行），不等整画布刷新；整画布刷新后再同步一次，让
     * 高亮在新 DOM 上保留（patch 幂等，纯行级 diff，成本可忽略）。 */
    await syncLiveSheetDraft(draft, prevDraft);
    toast("已采纳该条优化", "success");
    await refreshOptimizerFromJob(jobId);
    await syncLiveSheetDraft(draft, prevDraft);
  },
  "reject-bullet": async (button) => {
    const jobId = button.dataset.id;
    const diffId = button.dataset.diffId;
    const app = $("#app-router-view");
    const card = $(`[data-diff-id="${CSS.escape(diffId)}"]`, app);
    if (card) {
      card.classList.add("is-rejected");
      card.querySelector("[data-diff-actions]").hidden = true;
      toast("已忽略该条建议", "info");
    }
  },
  "polish-bullet": async (button) => {
    const jobId = button.dataset.id;
    const diffId = button.dataset.diffId;
    const instruction = button.dataset.instruction || "quantified";
    button.disabled = true;
    button.textContent = "润色中...";
    try {
      const rewritten = await api(
        `/api/jobs/${encodeURIComponent(jobId)}/workbench/rewrite`,
        {
          method: "POST",
          body: JSON.stringify({ diff_id: diffId, instruction }),
        },
      );
      await refreshOptimizerFromJob(jobId);
      toast("该条已重新润色", "success");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
      button.textContent = "AI 润色";
    }
  },
  "toggle-bullet-edit": (button) => {
    const diffId = button.dataset.diffId;
    const card = button.closest("[data-diff-id]");
    if (!card) return;
    const proposedNode = card.querySelector("[data-diff-proposed]");
    if (!proposedNode) return;
    const isEditing = card.classList.contains("is-editing");
    if (isEditing) {
      /* 退出编辑：还原高亮 HTML，移除编辑器。 */
      const savedHtml = card.dataset.originalProposedHtml || "";
      proposedNode.innerHTML = savedHtml;
      card.classList.remove("is-editing");
      button.textContent = "✏️ 编辑";
      return;
    }
    /* 进入编辑：保存高亮 HTML，替换为可编辑 textarea（纯文本）。 */
    card.dataset.originalProposedHtml = proposedNode.innerHTML;
    const plainText = proposedNode.textContent || "";
    const textarea = document.createElement("textarea");
    textarea.className = "bullet-editor";
    textarea.dataset.bulletEditor = "";
    textarea.rows = 3;
    textarea.value = plainText;
    proposedNode.replaceChildren(textarea);
    card.classList.add("is-editing");
    button.textContent = "完成编辑";
    textarea.focus();
  },
  "apply-accepted-bullets": async (button) => {
    const jobId = button.dataset.id;
    /* T2: 应用采纳前记录当前 Live Sheet 草稿。 */
    const prevDraft = getLiveSheetDraft();
    const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    const resumeId = job.workbench_resume_id;
    const diffs = job.diffs || [];
    if (!resumeId || !diffs.length) {
      toast("没有可应用的对齐结果", "error");
      return;
    }
    /* U7: 只应用被采纳（accepted）的 diff 集合，而非全量 diff。 */
    const acceptedIds = state.wbAcceptedBullets[jobId] || [];
    if (!acceptedIds.length) {
      toast("还没有已采纳的建议，先逐条点「采纳」", "error");
      return;
    }
    const resume = await api(`/api/master-resumes/${encodeURIComponent(resumeId)}`);
    const base =
      (state.wbWorkingDraft && state.wbWorkingDraft.jobId === jobId
        ? state.wbWorkingDraft.draft
        : null) ||
      job.final_draft ||
      resume.content ||
      "";
    const draft = applyAcceptedDiffsToDraft(base, diffs, acceptedIds);
    state.wbWorkingDraft = { jobId, draft };
    await api(`/api/jobs/${encodeURIComponent(jobId)}/final-draft`, {
      method: "POST",
      body: JSON.stringify({ draft, accepted_diff_ids: acceptedIds }),
    });
    /* T2: 同 accept-bullet——先毫秒级增量 patch Live Sheet，再整画布刷新后
     * 重放高亮。 */
    await syncLiveSheetDraft(draft, prevDraft);
    toast("已应用已采纳建议", "success");
    await refreshOptimizerFromJob(jobId);
    await syncLiveSheetDraft(draft, prevDraft);
  },
  "copy-align-markdown": () => copyAlignMarkdown(
    state.route.jobId,
    activeSessionForExport(),
  ),
  "export-align-markdown": () => exportFinalDraft("markdown"),
  "export-align-pdf": () => printTarget("workbench"),
  "export-align-json": () => exportFinalDraft("json"),
  "export-jobs-csv": () => {
    if (!state.jobs.length) {
      toast("岗位库为空，暂无可导出的岗位", "error");
      return;
    }
    download("resualign-jobs.csv", jobsToCsv(state.jobs), "text/csv;charset=utf-8");
    toast(`已导出 ${state.jobs.length} 条岗位`, "success");
  },
  "export-jobs-backup": async () => {
    const jobs = await api("/api/jobs?limit=500");
    if (!jobs.length) {
      toast("岗位库为空，暂无可备份的岗位", "error");
      return;
    }
    download(
      `resualign-jobs-backup-${new Date().toISOString().slice(0, 10)}.json`,
      JSON.stringify(buildJobsBackup(jobs), null, 2),
      "application/json",
    );
    toast(`已备份 ${jobs.length} 条岗位`, "success");
  },
  "show-backup-guide": () => {
    showModal(
      "整库备份与还原",
      `<pre class="pre small" style="white-space:pre-wrap">${esc(backupRestoreGuide())}</pre>`,
    );
  },
  "export-batch-csv": () => {
    if (!state.batchAlign) {
      toast("暂无批量对比结果", "error");
      return;
    }
    download(
      "resualign-batch-compare.csv",
      batchRowsToCsv(state.batchAlign),
      "text/csv;charset=utf-8",
    );
    toast("对比 CSV 已导出", "success");
  },
  "show-last-batch": () => {
    if (!state.batchAlign) {
      toast("当前会话暂无历史批次", "error");
      return;
    }
    renderBatchResults(state.batchAlign);
    const panel = $("[data-batch-wrap]");
    if (panel) panel.hidden = false;
    toast("已恢复最近一次批次结果", "success");
  },
  /* 一键分析全部待处理岗位（idle/failed/卡死的 queued），后端 selector=pending 选岗。
   * 主简历/粒度复用批量面板当前选择，主简历未选时后端回退到最近更新的主简历。 */
  "batch-align-pending": async () => {
    const form = $('[data-form="batch-align"]');
    const data = form
      ? Object.fromEntries(new FormData(form).entries())
      : {};
    const result = await api("/api/batch-align", {
      method: "POST",
      body: JSON.stringify({
        selector: "pending",
        master_resume_id: data.master_resume_id || "",
        job_ids: [],
        granularity: data.granularity || "fine",
        prompt_focus: "balanced",
        custom_prompt: data.custom_prompt || null,
      }),
    });
    state.batchAlign = result;
    const panel = $("[data-batch-wrap]");
    if (panel) panel.hidden = false;
    const cancel = $("[data-batch-cancel]");
    if (cancel) cancel.hidden = false;
    renderBatchResults(result);
    startBatchPolling(result.batch_id);
    toast(`已排队 ${result.queued} 个待处理岗位`, "success");
  },
  "toggle-theme": () => toggleTheme(),
  "set-wb-tab": (button) => setWbMobilePane(button.dataset.wbTab),
  "set-wb-tab-v3": (button) => setWbAuxPane(button.dataset.wbTabV3),
  "set-wb-view-mode": (button) => setWbViewMode(button.dataset.wbViewMode),
  "cancel-workbench": () => cancelActiveAlignment(),
  "retry-workbench": () => {
    const form = $('[data-form="split-align"]') || $('[data-form="wb-run"]');
    if (form) form.dispatchEvent(new Event("submit", { cancelable: true }));
  },
  /* F1: Eval 折叠块里的「重新运行（开启评估）」——先勾选 per-run 开关再提交。 */
  "retry-workbench-eval": () => {
    const form = $('[data-form="split-align"]') || $('[data-form="wb-run"]');
    if (!form) {
      toast("当前工作台无法重新运行", "error");
      return;
    }
    const check = form.querySelector('[name="run_eval"]');
    if (check) check.checked = true;
    form.dispatchEvent(new Event("submit", { cancelable: true }));
  },
  "cancel-align-job": () => cancelActiveAlignment(),
  "export-final-draft": () => exportFinalDraft("pdf"),
  "open-snapshot": (button) => {
    const snapshot = findApplicationSnapshot(button.dataset.id);
    if (!snapshot) {
      toast("投递快照不存在", "error");
      return;
    }
    const entry =
      (snapshot.job_id && findApplicationEntry(snapshot.job_id)) || {};
    showModal(
      `投递快照 · 第 ${snapshot.version_index} 版`,
      snapshotDrawerHtml(snapshot, entry),
      { className: "modal--drawer", closeBtn: true },
    );
  },
  "export-snapshot-md": (button) => {
    const snapshot = findApplicationSnapshot(button.dataset.id);
    if (!snapshot) return;
    download(
      `resualign-snapshot-v${snapshot.version_index}.md`,
      snapshot.final_draft || "",
      "text/markdown;charset=utf-8",
    );
  },
  "export-snapshot-pdf": (button) => {
    const snapshot = findApplicationSnapshot(button.dataset.id);
    if (snapshot) printTarget("snapshot", snapshot);
  },
  "view-legacy-draft": (button) => {
    const entry = findApplicationEntry(button.dataset.id);
    if (!entry || !entry.legacyDraft) {
      toast("当前岗位没有定稿", "error");
      return;
    }
    showModal(
      "早期投递版本（未生成不可篡改快照）",
      snapshotDrawerHtml(null, entry),
      { className: "modal--drawer", closeBtn: true },
    );
  },
  "export-legacy-draft-md": (button) => {
    const entry = findApplicationEntry(button.dataset.id);
    if (!entry || !entry.legacyDraft) return;
    download(
      "resualign-legacy-applied-draft.md",
      entry.legacyDraft,
      "text/markdown;charset=utf-8",
    );
  },
  "export-legacy-draft-pdf": (button) => {
    const entry = findApplicationEntry(button.dataset.id);
    if (!entry || !entry.legacyDraft) return;
    printTarget("snapshot", {
      version_index: 0,
      final_draft: entry.legacyDraft,
      applied_at: "",
      match_score: null,
    });
  },
  "export-final-draft-md": () => exportFinalDraft("markdown"),
  "export-final-draft-json": () => exportFinalDraft("json"),
  "save-as-new-resume": () => {
    const draft = state.wbFinalDraft && state.wbFinalDraft.draft;
    if (!draft) {
      toast("请先保存定稿", "error");
      return;
    }
    showModal(
      "另存为新主简历",
      `<p class="muted">将当前定稿创建为一份新的主简历，不会改动当前主简历。</p>
       <div class="actions">
         <button class="btn btn-ghost" type="button" data-action="close-modal">取消</button>
         <button class="btn btn-primary" type="button" data-action="confirm-save-as">确认另存</button>
       </div>`,
    );
  },
  "confirm-save-as": async () => {
    const draft = state.wbFinalDraft && state.wbFinalDraft.draft;
    const job = state.wbJob || {};
    closeModal();
    if (!draft) {
      toast("请先保存定稿", "error");
      return;
    }
    const now = new Date();
    const suffix = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(now.getDate()).padStart(2, "0")}`;
    const baseResume = (state.wbResumes || []).find(
      (resume) => resume.resume_id === job.workbench_resume_id,
    );
    const title = `${baseResume ? baseResume.title : "主简历"}-${job.title || "岗位"}-${suffix}`;
    const created = await api("/api/master-resumes", {
      method: "POST",
      body: JSON.stringify({ title, content: draft }),
    });
    toast(`已创建新主简历：${created.title}`, "success");
    navigate("resume", created.resume_id);
  },
  "export-markdown": () => {
    const job = state.wbJob;
    const result = state.wbResult || {};
    const sections = (result.tailored_resume || {}).sections || {};
    const content = [
      `# ${job ? job.title : "对齐简历"}`,
      "",
      `> 诊断分：${result.score ?? "—"} · 模型：${result.model || ""}`,
      "",
      "## 优化后内容",
      "",
      Object.values(sections).join("\n\n"),
      "",
      "## 修改项",
      "",
      ...(result.diffs || []).map((diff, index) => `${index + 1}. [${diff.type}] ${diff.reason || ""}`),
    ].join("\n");
    download(`resualign-${job ? job.title : "resume"}.md`, content, "text/markdown;charset=utf-8");
  },
  "export-json": () => {
    const job = state.wbJob;
    download(
      `resualign-${job ? job.title : "resume"}.json`,
      JSON.stringify({ job, result: state.wbResult }, null, 2),
      "application/json",
    );
  },
  "update-job-status": async (button) => {
    const select = $("[data-job-status]");
    await api(`/api/jobs/${encodeURIComponent(button.dataset.id)}`, {
      method: "PATCH",
      body: JSON.stringify({ status: select.value }),
    });
    toast("岗位状态已保存", "success");
    await refreshWbCanvas();
  },
  "cancel-batch-align": async () => {
    if (!state.batchAlign) return;
    const batchId = state.batchAlign.batch_id;
    const result = await api(
      `/api/batch-align/${encodeURIComponent(batchId)}/cancel`,
      { method: "POST" },
    );
    stopBatchPolling();
    const batch = await api(`/api/batch-align/${encodeURIComponent(batchId)}`);
    state.batchAlign = batch;
    renderBatchResults(batch);
    const cancel = $("[data-batch-cancel]");
    if (cancel) cancel.hidden = true;
    if (result.canceled === 0) {
      toast("任务已开始运行，无法取消", "error");
    } else {
      toast(`已取消 ${result.canceled} 个排队任务`, "success");
    }
  },
  "close-modal": closeModal,
  "confirm-status-back": () => applyPendingStatusTransition(),
  "cancel-status-back": () => cancelPendingStatusTransition(),
  "skip-onboarding-step": (button) => {
    const step = button.dataset.step;
    if (!step) return;
    const skipped = readOnboardingSkipped();
    if (!skipped.includes(step)) {
      skipped.push(step);
      try {
        localStorage.setItem(ONBOARDING_SKIPPED_KEY, JSON.stringify(skipped));
      } catch {
        /* storage unavailable: keep the in-page removal only */
      }
    }
    const card = $("[data-onboarding-card]");
    if (card) {
      const item = card.querySelector(`[data-step="${CSS.escape(step)}"]`);
      if (item) item.remove();
      if (!card.querySelector(".onboarding-step")) card.remove();
    }
    toast("已跳过该步骤，之后不再提示", "info");
  },
};

function setSegmented(selector, active) {
  $$(selector).forEach((button) =>
    button.setAttribute("aria-pressed", String(button === active)),
  );
}

document.addEventListener("click", async (event) => {
  const badge = event.target.closest(".opt-badge");
  if (badge) {
    const bubble = badge.nextElementSibling;
    if (bubble && bubble.classList.contains("opt-bubble")) {
      bubble.hidden = !bubble.hidden;
    }
  }
  const granularityButton = event.target.closest("[data-granularity]");
  if (granularityButton) setSegmented("[data-granularity]", granularityButton);
  const focusButton = event.target.closest("[data-focus]");
  if (focusButton) setSegmented("[data-focus]", focusButton);
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const action = actions[button.dataset.action];
  if (!action) return;
  try {
    await action(button, event);
  } catch (error) {
    if (isApiKeyUnconfigured(error)) {
      renderApiKeyGuide($("#app-router-view"));
    } else {
      toast(error.message, "error");
    }
  }
});

function updateBatchSelection() {
  const count = $$("[data-board-check]:checked").length;
  const label = $("[data-board-selected-count]");
  if (label) label.textContent = `已选 ${count}`;
  const fab = $("[data-batch-fab]");
  if (fab) fab.hidden = count === 0;
}

document.addEventListener("change", (event) => {
  const target = event.target;
  if (target.matches("[data-granularity]")) {
    setSegmented("[data-granularity]", target);
  }
  if (target.matches("[data-focus]")) {
    setSegmented("[data-focus]", target);
  }
  if (target.matches("[data-board-select-all]")) {
    $$("[data-board-check]").forEach(
      (input) => (input.checked = target.checked),
    );
    updateBatchSelection();
  }
  if (target.matches("[data-board-check]")) {
    updateBatchSelection();
  }
  if (target.matches("[data-board-status]")) {
    const job = (state.jobs || []).find(
      (item) => item.job_id === target.dataset.id,
    );
    const targetStatus = canonicalJobStatus(target.value);
    const resetStatus = () => {
      target.value = job ? canonicalJobStatus(job.status) : "";
    };
    const applyStatus = () => {
      api("/api/kanban/bulk-status", {
        method: "POST",
        body: JSON.stringify({
          job_ids: [target.dataset.id],
          status: targetStatus,
          idempotency_key: `fe-select-${target.dataset.id}-${targetStatus}`,
        }),
      })
        .then(() => {
          toast("岗位状态已更新", "success");
          render();
        })
        .catch((error) => toast(error.message, "error"));
    };
    if (job && isBackwardJobStatus(job.status, targetStatus)) {
      confirmBackwardStatus(job, targetStatus, applyStatus, resetStatus);
    } else if (job && isTerminalJobStatus(targetStatus)) {
      confirmTerminalStatus(job, targetStatus, async (payload) => {
        await api(`/api/jobs/${encodeURIComponent(job.job_id)}`, {
          method: "PATCH",
          body: JSON.stringify({
            status: targetStatus,
            ...(payload.offer_at ? { offer_at: payload.offer_at } : {}),
            ...(payload.rejected_at
              ? { rejected_at: payload.rejected_at }
              : {}),
            ...(payload.notes ? { notes: payload.notes } : {}),
          }),
        });
        toast("岗位状态已更新", "success");
        render();
      }, resetStatus);
    } else {
      applyStatus();
    }
  }
  if (target.matches("[data-job-switcher]") && target.value) {
    switchWorkspaceJob(target.value);
  }
  /* T2: Header 岗位快速选择器——选择后直接跳工作台（无 Context 也显示）。
   * T4: 已在 workspace 时复用 renderOptimizerCanvas 刷新 Diff 画布，避免
   * 整页路由重渲染；非 workspace 时 navigate 跳转。 */
  if (target.matches("[data-header-job-select]") && target.value) {
    switchWorkspaceJob(target.value);
  }
  /* Sprint 5 T4: 自动化规则 enabled 开关（checkbox change -> PUT）。 */
  if (target.matches("[data-rule-toggle]")) {
    const ruleId = target.dataset.id;
    if (!ruleId) return;
    const enabled = target.checked;
    api(`/api/automation/rules/${encodeURIComponent(ruleId)}`, {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    })
      .then(() => {
        toast(enabled ? "规则已启用" : "规则已停用", "success");
        render();
      })
      .catch((error) => {
        target.checked = !enabled;
        toast(error.message, "error");
      });
  }
});

document.addEventListener("submit", async (event) => {
  const form = event.target;
  const formName = form.dataset.form;
  if (!formName) return;
  event.preventDefault();
  const submitBtn = form.querySelector('button[type="submit"]');
  if (submitBtn) submitBtn.classList.add("is-loading");
  try {
    const data = Object.fromEntries(new FormData(form).entries());
    await handleForm(formName, data, form);
  } catch (error) {
    if (isApiKeyUnconfigured(error)) {
      renderApiKeyGuide($("#app-router-view"));
    } else {
      toast(error.message, "error");
    }
  } finally {
    if (submitBtn) submitBtn.classList.remove("is-loading");
  }
});

async function handleForm(formName, data, form) {
  switch (formName) {
    case "command-panel": {
      const session = await confirmCommandPanel();
      if (session && session.job && session.job.job_id) {
        navigate("workspace", session.job.job_id);
      } else if (session && session.session_id) {
        navigate("workspace", session.session_id);
      }
      break;
    }
    case "copilot-filter":
      state.filters = {
        job_function: data.job_function || "",
        seniority: data.seniority || "",
        status: data.status || "",
        search: data.search || "",
        sort: state.filters.sort || "updated_at_desc",
      };
      state.offset = 0;
      render();
      break;
    case "split-align": {
      const jobId = data.job_id;
      if (!data.master_resume_id) {
        toast("请先选择主简历", "error");
        return;
      }
      const result = await startAlignmentRun(
        jobId,
        data.master_resume_id,
        data.granularity || "medium",
        data.prompt_focus || "balanced",
        runEvalFromForm(data),
      );
      toast(`对齐任务已排队：${result.job_id}`, "success");
      break;
    }
    case "resume-create":
      await api("/api/master-resumes", {
        method: "POST",
        body: JSON.stringify({ title: data.title, content: data.content }),
      });
      toast("主简历已创建", "success");
      closeModal();
      render();
      break;
    case "resume-edit":
      await api(`/api/master-resumes/${encodeURIComponent(data.resume_id)}`, {
        method: "PATCH",
        body: JSON.stringify({ content: data.content }),
      });
      toast("新版本已保存", "success");
      closeModal();
      render();
      break;
    case "job-create": {
      /* #U8: submitting runs the job through classification (~2 min);
         disable the button and show progress instead of a silent wait. */
      const submitBtn = form && form.querySelector('button[type="submit"]');
      const originalText = submitBtn ? submitBtn.textContent : "";
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "保存并分类中...";
        submitBtn.classList.add("is-loading");
      }
      try {
        const payload = {
          title: data.title || null,
          jd_text: data.jd_text || null,
          jd_url: data.jd_url || null,
          company: data.company || null,
          location: data.location || null,
          salary_min: data.salary_min ? Number(data.salary_min) : null,
          salary_max: data.salary_max ? Number(data.salary_max) : null,
          salary_currency: data.salary_currency || null,
          source_url: data.source_url || null,
        };
        try {
          await api("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
          toast("岗位已添加", "success");
          render();
        } catch (error) {
          if (error.status === 409) {
            await showDuplicateJobGuide(payload);
          } else {
            throw error;
          }
        }
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = originalText;
          submitBtn.classList.remove("is-loading");
        }
      }
      break;
    }
    case "job-edit": {
      const payload = {
        title: data.title,
        jd_text: data.jd_text,
        company: data.company || null,
        location: data.location || null,
        salary_min: data.salary_min ? Number(data.salary_min) : null,
        salary_max: data.salary_max ? Number(data.salary_max) : null,
        status: data.status,
        job_function: data.job_function || null,
        seniority: data.seniority || null,
        tech_tags: (data.tech_tags || "").split(",").map((tag) => tag.trim()).filter(Boolean),
      };
      let job = (state.jobs || []).find(
        (item) => item.job_id === data.job_id,
      );
      if (!job) {
        try {
          job = await api(`/api/jobs/${encodeURIComponent(data.job_id)}`);
        } catch (error) {
          toast(error.message || "岗位不存在", "error");
          return;
        }
      }
      const targetStatus = canonicalJobStatus(data.status);
      const saveJob = async (extra = {}) => {
        const body = {
          ...payload,
          ...(extra.status
            ? { status: canonicalJobStatus(extra.status) }
            : {}),
          ...(extra.offer_at !== undefined
            ? { offer_at: extra.offer_at || null }
            : {}),
          ...(extra.rejected_at !== undefined
            ? { rejected_at: extra.rejected_at || null }
            : {}),
          ...(extra.notes !== undefined
            ? { notes: extra.notes || null }
            : {}),
        };
        await api(`/api/jobs/${encodeURIComponent(data.job_id)}`, {
          method: "PATCH",
          body: JSON.stringify(body),
        });
        toast("岗位已更新", "success");
        closeModal();
        render();
      };
      const reopenJobEditor = () => {
        showModal(
          `编辑「${job.title}」`,
          jobEditFormHtml(
            {
              ...job,
              title: data.title,
              jd_text: data.jd_text,
              company: data.company || job.company || "",
              location: data.location || job.location || "",
              status: data.status,
              job_function: data.job_function || job.job_function || "",
              seniority: data.seniority || job.seniority || "",
              salary_min: data.salary_min
                ? Number(data.salary_min)
                : job.salary_min,
              salary_max: data.salary_max
                ? Number(data.salary_max)
                : job.salary_max,
              tech_tags: (data.tech_tags || "")
                .split(",")
                .map((tag) => tag.trim())
                .filter(Boolean),
            },
            {
              statuses: vocabularyList("statuses"),
              job_functions: vocabularyList("job_functions"),
              seniorities: vocabularyList("seniorities"),
            },
          ),
        );
      };
      if (job && isTerminalJobStatus(targetStatus)) {
        confirmTerminalStatus(
          job,
          targetStatus,
          saveJob,
          reopenJobEditor,
        );
        return;
      }
      if (job && isBackwardJobStatus(job.status, targetStatus)) {
        confirmBackwardStatus(job, targetStatus, saveJob, reopenJobEditor);
        return;
      }
      await saveJob();
      break;
    }
    case "job-detail-edit": {
      const payload = {
        status: data.status,
        source_url: data.source_url || null,
        applied_at: data.applied_at || null,
        next_step: data.next_step || null,
        notes: data.notes || null,
        offer_at: data.offer_at || null,
        rejected_at: data.rejected_at || null,
        /* F6/U10: 结构化跟进字段。空串经 `|| null` 以 null 发送，后端将
         * null/"" 统一转成 NULL 写入（清除语义，无需前端特判）。 */
        next_step_due_at: data.next_step_due_at || null,
        interview_stage: data.interview_stage || null,
      };
      let job = (state.jobs || []).find(
        (item) => item.job_id === data.job_id,
      );
      if (!job) {
        try {
          job = await api(`/api/jobs/${encodeURIComponent(data.job_id)}`);
        } catch (error) {
          toast(error.message || "岗位不存在", "error");
          return;
        }
      }
      const targetStatus = canonicalJobStatus(data.status);
      const reopenDetail = () => {
        showModal(
          `岗位详情 · ${job.title}`,
          jobTimelineFormHtml({
            ...job,
            status: data.status,
            source_url: data.source_url || "",
            applied_at: data.applied_at || "",
            next_step: data.next_step || "",
            notes: data.notes || "",
            offer_at: data.offer_at || "",
            rejected_at: data.rejected_at || "",
            next_step_due_at: data.next_step_due_at || "",
            interview_stage: data.interview_stage || "",
          }),
        );
      };
      const saveDetail = async (extra = {}) => {
        const body = {
          ...payload,
          ...(extra.status
            ? { status: canonicalJobStatus(extra.status) }
            : {}),
          ...(extra.offer_at !== undefined
            ? { offer_at: extra.offer_at || null }
            : {}),
          ...(extra.rejected_at !== undefined
            ? { rejected_at: extra.rejected_at || null }
            : {}),
          ...(extra.notes !== undefined
            ? { notes: extra.notes || null }
            : {}),
        };
        await api(`/api/jobs/${encodeURIComponent(data.job_id)}`, {
          method: "PATCH",
          body: JSON.stringify(body),
        });
        toast("岗位时间线已保存", "success");
        closeModal();
        render();
        if (targetStatus === "offer") {
          celebrateOffer({ ...job, status: "offer" });
        }
      };
      if (job && isTerminalJobStatus(targetStatus)) {
        confirmTerminalStatus(
          job,
          targetStatus,
          saveDetail,
          reopenDetail,
          {
            date: targetStatus === "offer" ? data.offer_at : data.rejected_at,
            notes: data.notes || "",
          },
        );
        return;
      }
      if (job && isBackwardJobStatus(job.status, targetStatus)) {
        confirmBackwardStatus(job, targetStatus, saveDetail, reopenDetail);
        return;
      }
      await saveDetail();
      break;
    }
    case "job-followup": {
      const payload = {
        status: data.status,
        next_step: data.next_step || null,
        next_step_due_at: data.next_step_due_at || null,
        interview_stage: data.interview_stage || null,
      };
      let job = (state.jobs || []).find(
        (item) => item.job_id === data.job_id,
      );
      if (!job) {
        try {
          job = await api(`/api/jobs/${encodeURIComponent(data.job_id)}`);
        } catch (error) {
          toast(error.message || "岗位不存在", "error");
          return;
        }
      }
      const targetStatus = canonicalJobStatus(data.status);
      const reopenFollowup = () => {
        showModal(
          `安排跟进 · ${job.title || "该岗位"}`,
          jobFollowupFormHtml({
            ...job,
            status: data.status,
            next_step: data.next_step || "",
            next_step_due_at: data.next_step_due_at || "",
            interview_stage: data.interview_stage || "",
          }),
        );
      };
      const saveFollowup = async (extra = {}) => {
        const body = {
          ...payload,
          ...(extra.status
            ? { status: canonicalJobStatus(extra.status) }
            : {}),
          ...(extra.offer_at !== undefined
            ? { offer_at: extra.offer_at || null }
            : {}),
          ...(extra.rejected_at !== undefined
            ? { rejected_at: extra.rejected_at || null }
            : {}),
          ...(extra.notes !== undefined
            ? { notes: extra.notes || null }
            : {}),
        };
        await api(`/api/jobs/${encodeURIComponent(data.job_id)}`, {
          method: "PATCH",
          body: JSON.stringify(body),
        });
        toast("跟进已安排", "success");
        closeModal();
        render();
        if (targetStatus === "offer") {
          celebrateOffer({ ...job, status: "offer" });
        }
      };
      if (job && isTerminalJobStatus(targetStatus)) {
        confirmTerminalStatus(
          job,
          targetStatus,
          saveFollowup,
          reopenFollowup,
          {
            date: targetStatus === "offer" ? data.offer_at : data.rejected_at,
            notes: data.notes || "",
          },
        );
        return;
      }
      if (job && isBackwardJobStatus(job.status, targetStatus)) {
        confirmBackwardStatus(
          job,
          targetStatus,
          saveFollowup,
          reopenFollowup,
        );
        return;
      }
      await saveFollowup();
      break;
    }
    case "job-terminal-confirm": {
      const targetStatus = canonicalJobStatus(data.status);
      const payload = {
        status: targetStatus,
        ...(data.offer_at ? { offer_at: data.offer_at } : {}),
        ...(data.rejected_at ? { rejected_at: data.rejected_at } : {}),
        ...((data.notes || "").trim()
          ? { notes: (data.notes || "").trim() }
          : {}),
      };
      return applyPendingStatusTransition(payload);
    }
    case "job-filter":
      state.filters = {
        job_function: data.job_function || "",
        seniority: data.seniority || "",
        status: data.status || "",
        search: data.search || "",
        sort: state.filters.sort || "updated_at_desc",
      };
      state.offset = 0;
      render();
      break;
    case "job-import":
      await submitImport(data, form);
      break;
    case "batch-align": {
      const jobIds = $$("[data-batch-check]:checked").map((input) => input.value);
      if (jobIds.length < 2 || jobIds.length > 5) {
        toast("请选择 2-5 个岗位", "error");
        return;
      }
      if (!data.master_resume_id) {
        toast("请选择主简历", "error");
        return;
      }
      const result = await api("/api/batch-align", {
        method: "POST",
        body: JSON.stringify({
          master_resume_id: data.master_resume_id,
          job_ids: jobIds,
          granularity: data.granularity || "fine",
          prompt_focus: "balanced",
          custom_prompt: data.custom_prompt || null,
        }),
      });
      state.batchAlign = result;
      const cancel = $("[data-batch-cancel]");
      if (cancel) cancel.hidden = false;
      startBatchPolling(result.batch_id);
      toast(`已排队 ${result.queued} 个岗位`, "success");
      break;
    }
    case "wb-run": {
      const masterResumeId = data.master_resume_id;
      const granularity = data.granularity || "medium";
      const promptFocus = data.prompt_focus || "balanced";
      if (!masterResumeId) {
        toast("请先选择主简历", "error");
        return;
      }
      const jobId = state.wbJob && state.wbJob.job_id;
      if (!jobId) {
        toast("当前没有可对齐的岗位", "error");
        return;
      }
      const result = await startAlignmentRun(
        jobId,
        masterResumeId,
        granularity,
        promptFocus,
        runEvalFromForm(data),
      );
      toast(`对齐任务已排队：${result.job_id}`, "success");
      break;
    }
    case "login": {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: data.email, password: data.password }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "登录失败");
      state.token = body.token;
      localStorage.setItem("resualign_token", body.token);
      state.personal = false;
      closeModal();
      toast("登录成功", "success");
      render();
      break;
    }
    case "settings-vocabulary": {
      const vocabulary = {
        job_functions: (data.job_functions || "").split("\n").map((item) => item.trim()).filter(Boolean),
        seniorities: (data.seniorities || "").split("\n").map((item) => item.trim()).filter(Boolean),
        statuses: (data.statuses || "").split("\n").map((item) => item.trim()).filter(Boolean),
      };
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({ classification_vocabulary: vocabulary }),
      });
      state.vocabulary = normalizeVocabulary(vocabulary);
      toast("分类词表已保存", "success");
      render();
      break;
    }
    /* Sprint 5: 对齐评估默认开关（全局 eval_default，与 LLM 节点解耦）。 */
    case "settings-eval-default": {
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({ eval_default: evalDefaultFromForm(data) }),
      });
      toast("对齐评估默认开关已保存", "success");
      render();
      break;
    }
    case "settings-cost-guard": {
      const payload = buildCostGuardPayload(data);
      const validation = validateCostGuardPayload(payload);
      if (!validation.ok) {
        toast(validation.message, "error");
        return;
      }
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      toast("成本护栏已保存", "success");
      render();
      break;
    }
    /* Sprint 5 T2: LLM 节点新增（POST） / 编辑（PUT，隐藏 node_id 非空）。 */
    case "llm-node-form": {
      const payload = buildLlmNodePayload(data);
      const nodeId = (data.node_id || "").trim();
      const validation = validateLlmNodePayload(payload, {
        isEdit: Boolean(nodeId),
      });
      if (!validation.ok) {
        toast(validation.message, "error");
        return;
      }
      if (nodeId) {
        await api(`/api/llm/nodes/${encodeURIComponent(nodeId)}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        toast("节点已更新", "success");
      } else {
        await api("/api/llm/nodes", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        toast("节点已创建", "success");
      }
      closeModal();
      render();
      break;
    }
    /* Sprint 5 T4: 自动化规则新增（Modal 表单 -> POST）。 */
    case "automation-rule-form": {
      const payload = buildAutomationRulePayload(data);
      const validation = validateAutomationRule(payload);
      if (!validation.ok) {
        toast(validation.message, "error");
        return;
      }
      await api("/api/automation/rules", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      closeModal();
      toast("自动化规则已添加", "success");
      render();
      break;
    }
    default:
      break;
  }
}

async function submitImport(data, form) {
  const file = form.querySelector('[name="import_file"]').files[0];
  const pasted = data.import_text || "";
  let payload = {};
  if (file) {
    const text = await file.text();
    if (file.name.toLowerCase().endsWith(".json")) {
      const rows = parseImportText(text, file.name);
      if (rows.length) payload = { jobs: rows };
    } else if (text.trim()) {
      payload = { csv_text: text };
    }
  } else if (pasted.trim()) {
    if (pasted.trim().startsWith("[")) {
      const rows = parseImportText(pasted, "paste");
      if (rows.length) payload = { jobs: rows };
    } else {
      payload = { csv_text: pasted };
    }
  }
  if (!payload.jobs && !payload.csv_text) {
    toast("没有可导入的岗位数据", "error");
    return;
  }
  const statusNode = form.querySelector("[data-import-status]");
  statusNode.textContent = "已提交，正在处理...";
  const body = await api("/api/jobs/import", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!body.queued) {
    statusNode.textContent = "没有可导入的数据";
    return;
  }
  statusNode.textContent = `已提交 ${body.total} 条，正在处理...`;
  const timer = window.setInterval(async () => {
    try {
      const status = await api(`/api/jobs/import/${body.import_id}`);
      statusNode.textContent = `处理中：新建 ${status.created}，跳过 ${status.skipped}`;
      if (!status.queued) {
        window.clearInterval(timer);
        statusNode.textContent = `完成：新建 ${status.created}，跳过 ${status.skipped}`;
        toast(`导入完成：新建 ${status.created}，跳过 ${status.skipped}`, status.created ? "success" : "error");
        render();
      }
    } catch (error) {
      window.clearInterval(timer);
      statusNode.textContent = `导入失败：${error.message}`;
    }
  }, 800);
}

/* ------------------------------------------------------------------ */
/* #11 Onboarding card (DOM mounting)                                  */
/* 纯函数在 format.js（onboardingSteps / renderOnboardingCard）。        */
/* ------------------------------------------------------------------ */

const ONBOARDING_SKIPPED_KEY = "resualign_onboarding_skipped";

function readOnboardingSkipped() {
  try {
    const raw = JSON.parse(localStorage.getItem(ONBOARDING_SKIPPED_KEY) || "[]");
    return Array.isArray(raw)
      ? raw.filter((item) => typeof item === "string")
      : [];
  } catch {
    return [];
  }
}

async function loadResumesForOnboarding() {
  if (Array.isArray(state.resumes) && state.resumes.length > 0) {
    return state.resumes;
  }
  if (Array.isArray(state.batchResumes) && state.batchResumes.length > 0) {
    return state.batchResumes;
  }
  try {
    const resumes = await api("/api/master-resumes");
    state.resumes = resumes;
    return resumes;
  } catch {
    return [];
  }
}

/* 岗位库顶部：三步引导卡（仅当存在未完成且未跳过的步骤）。通过第二个
   canvas hook 挂载，不动 kanban.js 的 renderKanban。 */
setCanvasRenderHook(async (app) => {
  const header = app.querySelector(".jobs-topbar") || app.querySelector(".page-header");
  if (!header || app.querySelector("[data-onboarding-card]")) {
    return;
  }
  const card = renderOnboardingCard(
    onboardingSteps({
      resumes: await loadResumesForOnboarding(),
      jobs: state.jobs || [],
      skipped: readOnboardingSkipped(),
    }),
  );
  if (!card) return;
  const wrap = document.createElement("div");
  wrap.innerHTML = card;
  while (wrap.firstChild) header.before(wrap.firstChild);
});

/* ------------------------------------------------------------------ */
/* Boot                                                                */
/* ------------------------------------------------------------------ */

setCanvasRenderHook(async (app) => {
  const mount = app.querySelector("[data-jobs-batch-mount]");
  if (!mount || app.querySelector("[data-batch-wrap]")) return;
  let resumes = state.batchResumes;
  /* #B2: state.batchResumes starts as [] (truthy), so the old `if (!resumes)`
     guard never re-fetched and the panel was stuck on "先到简历中心创建主简历". */
  if (!Array.isArray(resumes) || resumes.length === 0) {
    try {
      resumes = await api("/api/master-resumes");
      state.batchResumes = resumes;
    } catch {
      resumes = [];
    }
  }
  const fab = document.createElement("div");
  fab.className = "batch-fab";
  fab.hidden = true;
  fab.setAttribute("data-batch-fab", "");
  fab.innerHTML = `
    <label class="board-check"><input type="checkbox" data-board-select-all aria-label="全选岗位"><span></span></label>
    <span class="batch-fab__count" data-board-selected-count>已选 0</span>
    <button class="btn btn-primary btn-sm" type="button" data-action="toggle-batch-panel">批量对比</button>
  `;
  const wrap = document.createElement("div");
  wrap.className = "panel panel-card batch-panel-wrap";
  wrap.hidden = true;
  wrap.setAttribute("data-batch-wrap", "");
  wrap.innerHTML = batchPanelHtml(state.jobs || [], resumes || []);
  mount.append(fab, wrap);

  const formsMount = app.querySelector("[data-jobs-forms-mount]");
  if (formsMount && !formsMount.querySelector('[data-form="job-create"]')) {
    const createForm = document.createElement("div");
    createForm.innerHTML = JOB_CREATE_FORM_HTML.trim();
    const importForm = document.createElement("div");
    importForm.innerHTML = JOB_IMPORT_FORM_HTML.trim();
    formsMount.append(createForm.firstChild, importForm.firstChild);
  }
});

async function boot() {
  initTheme();
  initializeCommandPanel();
  $$(".tabs button").forEach((button) => {
    button.addEventListener("click", () => navigate(button.dataset.route));
  });
  document.addEventListener("change", async (event) => {
    const input = event.target;
    if (
      !(input instanceof HTMLInputElement) ||
      input.id !== "resume-upload-input"
    ) {
      return;
    }
    const file = input.files && input.files[0];
    input.value = "";
    if (!file) return;
    try {
      const formData = new FormData();
      formData.append("file", file);
      const parsed = await api("/api/master-resumes/parse", {
        method: "POST",
        body: formData,
      });
      /* v2.0: 上传解析成功后打开新建模态框并预填标题/内容。 */
      openResumeCreator({
        title: parsed.title || file.name,
        content: parsed.content || "",
      });
      toast(`已解析 ${file.name}，请确认后保存`, "success");
    } catch (error) {
      toast(error.message, "error");
    }
  });
  try {
    await api("/api/auth/me");
    state.personal = true;
  } catch {
    state.personal = false;
  }
  window.addEventListener("hashchange", render);
  await render();
}

boot();
