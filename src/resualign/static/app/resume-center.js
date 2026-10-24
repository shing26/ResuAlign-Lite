/* ResuAlign v2.0 — Resume Center (蓝图文件 4)
 * 简历中心重构：主视图彻底切除内联 <textarea>（新建/编辑一律走模态框），
 * 左 65% renderMarkdown 结构化 Sheet + 编辑/复制 MD/导出 PDF 阻尼按钮，
 * 右 35% ATS 健康度仪表盘 + Version Timeline 竖线时间轴。
 */
import {
  api,
  atsSummaryHtml,
  closeModal,
  recoverDiagnosis,
  recoverOptimization,
  showModal,
  state,
  toast,
} from "./events.js";
import {
  atsHealthCardHtml,
  atsHealthScoreLevel,
  diagnosisStatusText,
  esc,
  formatDate,
  renderMarkdown,
  RESUME_LIST_SENTINEL,
  resumeListPreview,
  versionTimelineHtml,
} from "./format.js";
import { icon } from "./icons.js";

/* ------------------------------------------------------------------ */
/* ATS 诊断快照提取                                                     */
/* ------------------------------------------------------------------ */

/* 从 state.diagnosis 快照提取 diagnosis 对象，与 events.js
 * renderDiagnosisResult 的 result.diagnosis || result 语义保持一致。 */
function diagnosisFromSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== "object") return null;
  const result = snapshot.result || {};
  return result.diagnosis || result || null;
}

/* ------------------------------------------------------------------ */
/* 列表视图（65% Sheet 入口 + 新建/上传）                                */
/* ------------------------------------------------------------------ */

/* 「去看诊断」的落地位置：列表卡上点了之后，详情渲染完要把诊断卡滚进视口。
 * 用模块级标记而不是 URL 参数：main.js 的 navigate(name, id) 只带 id，
 * 加 query 会牵动路由解析（不在本次改动范围）。 */
let pendingResumeFocus = null;

/* RS-06（2026-10-22 审计）：7 份简历标题高度相似（3 份「Java 全栈」、2 份
 * 「AI 应用」），旧列表卡只有标题 + 更新时间 + vN，看不出「哪份最新改过、
 * 哪份 ATS 分高、哪份内容更全」，选简历全靠点进详情再返回。
 * 这里给每张卡补三样能一眼比较的依据：
 * ① 字数：内容量（含空白，与详情页「共 N 字」口径一致）；
 * ② ATS 分：列表 projection 的 latest_diagnosis 只在内容哈希仍匹配时才下发，
 *    有分即「这份简历的当前内容诊断过」，没分显示「未诊断」；
 * ③ 当前版本号：合进副标题，不再单独占一个「当前版本 vN」徽标。
 * 后端 list projection（workspace.list_master_resumes）没有 is_primary /
 * diagnosis_status 字段，所以不做「当前主简历」徽标，也不假装知道「诊断已过期」。 */
function resumeCharsLabel(content) {
  /* 千分位固定用 en-US 分组：toLocaleString() 的默认 locale 随运行环境变化，
   * 同一份简历在列表里的字数不该有时是 3,287 有时是 3287。 */
  return `${String(content || "").length.toLocaleString("en-US")} 字`;
}

/* ATS 徽标：复用 format.js 的分级阈值（85 优秀 / 70 良好），与详情页右栏
 * ATS 卡同一套口径，避免列表说「优秀」、详情说「良好」。 */
function resumeAtsBadgeHtml(resume) {
  const score = Number((resume.latest_diagnosis || {}).score);
  if (!Number.isFinite(score)) {
    return '<span class="badge badge-gray" data-resume-ats data-resume-ats-state="missing">未诊断</span>';
  }
  const clamped = Math.max(0, Math.min(100, Math.round(score)));
  const tone =
    clamped >= 85 ? "badge-green" : clamped >= 70 ? "badge-amber" : "badge-red";
  return `<span class="badge ${tone}" data-resume-ats data-resume-ats-state="done" title="ATS 健康度：${esc(atsHealthScoreLevel(clamped))}">ATS ${clamped}</span>`;
}

async function renderResumeListView(app) {
  state.resumes = await api("/api/master-resumes");
  const hasResumes = state.resumes.length > 0;
  const cards = state.resumes
    .map((resume) => {
      /* 预览文案末尾自带「（全文约 N 字）」（format.js resumeListPreview）；
       * 字数已经提到元信息行，这里去掉重复后缀，免得一张卡出现两个字数口径。 */
      const preview = String(resumeListPreview(resume.content)).replace(
        /（全文约 [\d,]+ 字）$/,
        "",
      );
      return `
      <div class="card resume-card card-base card-hover-soft" data-resume-card data-resume-id="${resume.resume_id}" title="打开详情">
        <div class="card-head">
          <div>
            <div class="card-title">${esc(resume.title)}</div>
            <div class="card-meta" data-resume-card-meta>更新于 ${formatDate(resume.updated_at)} · 当前 v${resume.current_version} · <span data-resume-chars>${resumeCharsLabel(resume.content)}</span></div>
          </div>
          ${resumeAtsBadgeHtml(resume)}
        </div>
        <p class="small muted" data-resume-preview title="打开详情阅读全文">${esc(preview)}</p>
        <div class="row mt-3">
          <button class="btn btn-primary btn-sm" type="button" data-action="open-resume-archive" data-id="${resume.resume_id}">打开详情</button>
          <button class="btn btn-outline btn-sm" type="button" data-action="open-resume-archive" data-id="${resume.resume_id}" data-resume-focus="diagnosis">去看诊断</button>
          <!-- 编辑/删除降权到 kebab：列表的主要任务是「选哪份」，破坏性动作
               不该和主操作同权重；二次确认仍在 main.js 的 delete-resume 里。 -->
          <details class="board-more" data-resume-card-more>
            <summary class="board-more__trigger" aria-label="更多操作" title="更多操作">${icon("more-horizontal", 20)}</summary>
            <div class="board-more__menu">
              <button class="btn btn-ghost btn-sm" type="button" data-action="edit-resume" data-id="${resume.resume_id}">编辑</button>
              <button class="btn btn-danger btn-sm" type="button" data-action="delete-resume" data-id="${resume.resume_id}">删除</button>
            </div>
          </details>
        </div>
      </div>`;
    })
    .join("");

  app.innerHTML = `
    <div class="page-header page-header--resume">
      <div>
        <div class="sub">维护主简历与版本历史，工作台始终基于当前版本生成对齐稿</div>
      </div>
      <div class="row">
        <button class="btn btn-primary" data-action="new-resume">新建主简历</button>
        <button class="btn btn-outline" data-action="upload-resume">上传简历文件</button>
        <span class="small muted">支持 PDF / DOCX / TXT</span>
        <input type="file" id="resume-upload-input" accept=".pdf,.docx,.txt" hidden>
      </div>
    </div>
    <div id="resume-list" class="card-list motion-stagger">${hasResumes ? cards : `
      <div class="panel panel-card empty-state">
        <div class="big">还没有主简历</div>
        <div>先创建一份主简历，工作台才能生成对齐版本。</div>
        <div class="actions"><button class="btn btn-primary" data-action="new-resume">新建主简历</button></div>
      </div>`}
    </div>`;
}

/* ------------------------------------------------------------------ */
/* 详情视图（65/35 网格）                                               */
/* ------------------------------------------------------------------ */

async function renderResumeDetailView(app, resumeId) {
  const resume = await api(`/api/master-resumes/${encodeURIComponent(resumeId)}`);
  const versions = resume.versions || [];
  /* Sprint 4 T3: ATS 卡数据源 —— state.diagnosis 只在 job_id 与本简历最新诊断
   * 任务一致时才可信（防止跨简历串数据）。renderDiagnosisResult 完成后还会
   * 通过 [data-ats-health-mount] 实时刷新（见 events.js）。 */
  /* Bug-05: 优先消费服务端持久化的 latest_diagnosis 快照；无快照时才
   * 回退到 state.diagnosis（仅在 job_id 与最新诊断任务一致时可信）。 */
  const diagnosis =
    resume.latest_diagnosis ||
    (state.diagnosis &&
      resume.latest_diagnosis_job_id &&
      state.diagnosis.job_id === resume.latest_diagnosis_job_id
      ? diagnosisFromSnapshot(state.diagnosis)
      : null);
  const diagnosisStatus = resume.diagnosis_status || { status: "missing" };
  const hasDiagnosis =
    diagnosis && Number.isFinite(Number(diagnosis.score));
  /* 按钮文案由「有没有诊断结果」决定，而不是固定写死：未诊断时主 CTA 说
   * 「诊断简历」，已有结果说「重新诊断」——同一个动作不换名字，用户不用
   * 猜「诊断」和「重新诊断」有什么区别。 */
  const diagnoseLabel =
    diagnosisStatus.status === "valid" ||
    diagnosisStatus.status === "stale" ||
    hasDiagnosis
      ? "重新诊断"
      : "诊断简历";
  state.resumeVersions = versions;
  state.resumeCurrentContent = resume.content || "";

  app.innerHTML = `
    <div class="view view-fit resume-view">
      <div class="resume-band">
        <div class="resume-band-main">
          <button class="btn btn-ghost btn-sm" data-action="back-resume-center">← 返回列表</button>
          <h2>${esc(resume.title)}</h2>
          <p>更新于 ${formatDate(resume.updated_at)} · 当前版本 v${resume.current_version} · 共 ${versions.length} 个版本</p>
        </div>
        <div class="resume-band-actions">
          <span class="status-line" data-resume-band-status><span class="dot ${diagnosisStatus.status === "valid" ? "dot-success" : diagnosisStatus.status === "stale" ? "dot-warn" : "dot-muted"}" aria-hidden="true"></span><span data-resume-band-status-text>最近诊断：${diagnosisStatusText(diagnosisStatus, diagnosis)}</span></span>
          <button class="btn btn-primary btn-sm" data-action="diagnose-resume" data-id="${resume.resume_id}">${diagnoseLabel}</button>
          <!-- RS-02 按钮收敛：4 个平铺导出按钮收进「导出」下拉菜单。导出不花钱，
               但仍然不该和主 CTA 抢同一个视觉层级；诊断报告两项在没有诊断
               结果时保持 hidden，避免点了没反应的空入口。 -->
          <details class="toolbar-more" data-resume-export>
            <summary class="btn btn-secondary btn-sm export-dock__trigger" aria-label="导出">导出 ${icon("chevron-down", 16)}</summary>
            <div class="export-dock__menu">
              <button class="btn btn-secondary btn-sm" type="button" data-action="export-resume-md" data-id="${resume.resume_id}" title="导出简历正文 Markdown">导出简历 MD</button>
              <button class="btn btn-secondary btn-sm" type="button" data-action="export-diagnosis-md" data-id="${resume.resume_id}" hidden title="导出最近一次诊断报告 Markdown">诊断报告 MD</button>
              <button class="btn btn-secondary btn-sm" type="button" data-action="export-diagnosis" data-id="${resume.resume_id}" hidden title="导出最近一次诊断报告 PDF">诊断报告 PDF</button>
              <button class="btn btn-outline btn-sm" type="button" data-action="print-resume" title="打开打印视图（可另存为 PDF）">打印预览</button>
            </div>
          </details>
          <!-- 删除是破坏性动作：收进「⋯」，与导出、诊断拉开距离，误触成本降低。
               二次确认仍在 main.js 的 delete-resume 里，不放宽。
               用 .board-more 而不是 .toolbar-more：≤640px 的旧规则会把
               .toolbar-more__menu 改成 left:0，菜单从右边界的按钮展开会撑出
               屏幕（实测 390 宽下右边缘 468px）。.board-more__menu 保持 right:0。 -->
          <details class="board-more" data-resume-more>
            <summary class="board-more__trigger" aria-label="更多操作" title="更多操作">${icon("more-horizontal", 20)}</summary>
            <div class="board-more__menu">
              <button class="btn btn-ghost btn-sm" type="button" data-action="edit-resume" data-id="${resume.resume_id}">编辑简历</button>
              <button class="btn btn-danger btn-sm" type="button" data-action="delete-resume" data-id="${resume.resume_id}">删除简历</button>
            </div>
          </details>
        </div>
      </div>
      <section class="panel diagnosis-panel diagnosis-banner" data-diagnosis-panel>
        <div class="diagnosis-banner__row">
          <div class="diagnosis-banner__copy">
            <span class="diagnosis-banner__label">简历诊断</span>
            <span class="small muted" data-diagnosis-meta>${diagnosisStatusText(diagnosisStatus, diagnosis)}</span>
            ${diagnosisStatus.status === "stale" ? `<span class="small muted" data-diagnosis-reason>${esc(diagnosisStatus.reason || "诊断已过期")}</span>` : ""}
          </div>
          <!-- 诊断卡内不再放按钮：主 CTA 只在页头一处（RS-02）。卡里重复一个
               同名按钮会让用户先犹豫「点哪个」，而诊断本身要花模型调用。 -->
        </div>
        <p class="small muted" data-diagnosis-hint${hasDiagnosis ? " hidden" : ""}>还没有诊断，点右上角「诊断简历」。</p>
        ${atsSummaryHtml(diagnosis)}
        <div class="progress-wrap" data-diagnosis-progress hidden>
          <div class="progress-track"><div class="progress-fill" data-diagnosis-fill style="--fill:5%"></div></div>
          <span class="small" data-diagnosis-stage>排队中</span>
          <span class="small muted" data-diagnosis-elapsed>0s</span>
          <button class="btn btn-ghost btn-sm" type="button" data-action="cancel-diagnosis" hidden>取消任务</button>
        </div>
        <div data-diagnosis-result hidden></div>
        <div class="form-error" data-diagnosis-error hidden></div>
      </section>
      <details class="panel optimize-panel" data-optimize-panel>
        <summary class="optimize-panel__head optimize-panel__row">
          <span class="optimize-panel__copy">
            <span class="optimize-panel__label">AI 优化（模块化润色项目经历）</span>
            <span class="small muted" data-optimize-meta>尚未运行</span>
          </span>
          <span class="optimize-panel__disclosure" aria-hidden="true"></span>
        </summary>
        <div class="optimize-panel__body">
          <div class="optimize-panel__jd">
            <textarea class="optimize-jd-input" data-optimize-jd rows="2" placeholder="可选：粘贴目标 JD，模块润色时会自然融入 JD 关键词与业务场景"></textarea>
          </div>
          <div class="optimize-panel__actions">
            <button class="btn btn-primary btn-sm" type="button" data-action="optimize-resume" data-id="${resume.resume_id}">运行 AI 优化</button>
            <button class="btn btn-ghost btn-sm" type="button" data-action="cancel-optimize" hidden>取消任务</button>
          </div>
          <div class="progress-wrap" data-optimize-progress hidden>
            <div class="progress-track"><div class="progress-fill" data-optimize-fill style="--fill:5%"></div></div>
            <span class="small" data-optimize-stage>排队中</span>
            <span class="small muted" data-optimize-elapsed>0s</span>
          </div>
          <div data-optimize-result hidden></div>
          <div class="form-error" data-optimize-error hidden></div>
        </div>
      </details>
      <div class="resume-archive-grid resume-grid">
        <section class="panel resume-sheet" data-resume-sheet>
          <div class="resume-sheet-head">
            <div>
              <h2>完整简历</h2>
              <p>Markdown 文档 · 预览与源码双态</p>
            </div>
            <div class="resume-sheet-actions">
              <!-- 文档头只留「读/改」三件事：编辑（模态）、编辑源码（内联双态，
                   data-action 契约保留）、复制 MD。打印预览只在页头「导出」下拉菜单
                   里出现一次，不在文档头重复同一动作。 -->
              <button class="btn btn-primary btn-sm" data-action="edit-resume" data-id="${resume.resume_id}">编辑</button>
              <button class="btn btn-ghost btn-sm" data-action="toggle-resume-inline-edit" data-id="${resume.resume_id}">编辑源码</button>
              <button class="btn btn-ghost btn-sm" data-action="copy-resume-md" data-id="${resume.resume_id}">复制 MD</button>
            </div>
          </div>
          <div class="resume-preview-bar" data-resume-preview-bar hidden>
            <span>正在预览 <strong data-preview-version></strong>，改动不会保存</span>
            <button class="btn btn-ghost btn-sm" data-action="restore-current-preview">返回当前版本</button>
          </div>
          <div class="resume-doc" data-resume-sheet-doc>${renderMarkdown(resume.content)}</div>
          <form class="resume-editor resume-inline-edit hidden" data-resume-inline-edit data-form="resume-edit">
            <input type="hidden" name="resume_id" value="${resume.resume_id}">
            <textarea name="content" rows="16" required aria-label="简历 Markdown 源码">${esc(resume.content)}</textarea>
            <div class="editor-actions">
              <button class="btn btn-ghost" type="button" data-action="cancel-resume-inline-edit">取消</button>
              <button class="btn btn-primary" type="submit">保存新版本</button>
            </div>
          </form>
        </section>
        <aside class="resume-rail">
          <section class="rail-section" data-ats-health-card>
            <div class="rail-section-head">
              <h3>ATS 健康度</h3>
              <!-- 标题旁的 "85 / 100" 胶囊与卡内大字重复（RS-02「85 分说了六遍」），
                   直接去掉；分数只在卡内大字与页头状态行各出现一次。 -->
            </div>
            <div data-ats-health-mount>${atsHealthCardHtml(diagnosis)}</div>
          </section>
          <section class="rail-section" data-version-timeline-card>
            <div class="rail-section-head">
              <h3>版本时间线</h3>
            </div>
            ${versionTimelineHtml(versions, resume.current_version, resume.resume_id)}
          </section>
          <section class="rail-section" data-profile-card>
            <div class="rail-section-head">
              <h3>网申档案</h3>
              ${profileBadgeHtml(resume.profile)}
            </div>
            <div data-profile-mount>${resumeProfileHtml(resume.resume_id, resume.profile)}</div>
          </section>
        </aside>
      </div>
    </div>`;
  state.diagnosisResumeId = resumeId;
  await recoverDiagnosis(resume);
  /* AI 优化面板：恢复上次任务状态（结果/失败/进行中继续轮询）。 */
  state.optimizeResumeId = resumeId;
  recoverOptimization(resume);
  /* 列表卡「去看诊断」：详情渲染完成后把诊断卡滚进视口并聚焦。
   * 只做定位，不自动发起诊断——诊断要花模型调用，必须由用户显式点页头主 CTA。 */
  if (pendingResumeFocus === "diagnosis") {
    pendingResumeFocus = null;
    const panel = app.querySelector("[data-diagnosis-panel]");
    if (panel) {
      panel.setAttribute("tabindex", "-1");
      requestAnimationFrame(() => {
        panel.focus({ preventScroll: true });
        panel.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  }
}

/* ------------------------------------------------------------------ */
/* 编辑 / 新建模态框（主视图无 textarea，输入一律走模态框）               */
/* ------------------------------------------------------------------ */

export function openResumeEditor(resumeId) {
  let resume = state.resumes.find((item) => item.resume_id === resumeId);
  if (!resume) {
    api(`/api/master-resumes/${encodeURIComponent(resumeId)}`)
      .then((loaded) => {
        openResumeEditorModal(loaded);
      })
      .catch(() => {
        toast("简历不存在或已删除", "error");
      });
    return;
  }
  openResumeEditorModal(resume);
}

function openResumeEditorModal(resume) {
  showModal(
    `编辑「${resume.title}」`,
    `<form data-form="resume-edit">
      <input type="hidden" name="resume_id" value="${resume.resume_id}">
      <div class="field"><label>简历内容（Markdown）</label>
        <textarea name="content" rows="16" required>${esc(resume.content)}</textarea></div>
      <div class="actions"><button class="btn btn-ghost" type="button" data-action="close-modal">取消</button>
        <button class="btn btn-primary" type="submit">保存新版本</button></div>
    </form>`,
  );
}

/* 新建/上传主简历模态框；prefill 用于上传解析回填（title/content）。 */
export function openResumeCreator(prefill = {}) {
  const title = prefill.title || "";
  const content = prefill.content || "";
  /* B6②（#83）：上传解析回填时弹窗标题与动作一致，不再都叫「新建」。 */
  showModal(
    content ? "上传主简历" : "新建主简历",
    `<form data-form="resume-create">
      <div class="field"><label>标题</label>
        <input type="text" name="title" required placeholder="例如：2026 后端大厂版" value="${esc(title)}"></div>
      <div class="field"><label>简历内容（Markdown）</label>
        <textarea name="content" rows="12" required placeholder="个人信息、工作经历、项目经历...">${esc(content)}</textarea></div>
      <div class="actions"><button class="btn btn-ghost" type="button" data-action="close-modal">取消</button>
        <button class="btn btn-primary" type="submit">保存</button></div>
    </form>`,
  );
}

/* ------------------------------------------------------------------ */
/* 路由入口                                                             */
/* ------------------------------------------------------------------ */

/* UX 走查 P1-C（2026-08-28）：档案页取数 1.5s+ 期间只有一行「加载中...」，
 * 改为与最终布局同构的骨架屏（band + 诊断横幅 + 版本/诊断面板占位）。 */
function resumeDetailSkeletonHtml() {
  return `
    <div class="view view-fit resume-view" data-resume-detail-skeleton aria-busy="true" aria-label="简历档案加载中">
      <div class="resume-band">
        <div class="resume-band-main">
          <div class="skeleton skeleton--sized is-shimmer" style="--w:220px;--h:22px"></div>
          <div class="skeleton skeleton--sized is-shimmer mt-3" style="--w:340px;--h:14px"></div>
        </div>
        <div class="resume-band-actions">
          <div class="skeleton skeleton--sized is-shimmer" style="--w:120px;--h:20px"></div>
          <div class="skeleton skeleton--sized is-shimmer" style="--w:96px;--h:28px"></div>
          <div class="skeleton skeleton--sized is-shimmer" style="--w:76px;--h:28px"></div>
          <div class="skeleton skeleton--sized is-shimmer" style="--w:28px;--h:28px"></div>
        </div>
      </div>
      <section class="panel diagnosis-panel">
        <div class="skeleton skeleton--sized is-shimmer" style="--w:100%;--h:110px"></div>
      </section>
      <section class="panel">
        <div class="skeleton skeleton--sized is-shimmer" style="--w:100%;--h:200px"></div>
      </section>
    </div>`;
}

/* 网申结构化档案：抽取 → 查看（分组只读）→ 手动编辑（模态 JSON 表单）。
 * 数据消费方是回填扩展（期一），此处保证用户可看可改可重抽。 */
function profileBadgeHtml(profile) {
  if (!profile) return '<span class="pill pill-neutral">未抽取</span>';
  return profile.stale
    ? '<span class="pill pill-warn" title="简历内容在抽取后有改动，建议重抽">已过期</span>'
    : '<span class="pill pill-success">已生成</span>';
}

function resumeProfileHtml(resumeId, profile) {
  if (!profile) {
    return `
      <p class="small muted">抽取姓名/教育/经历等原子字段，供浏览器回填扩展一键填网申表单。</p>
      <button class="btn btn-outline btn-sm" type="button" data-action="profile-extract" data-id="${esc(resumeId)}">生成档案</button>`;
  }
  const data = profile.data || {};
  const basic = data.basic || {};
  const rows = [
    ["姓名", basic.name], ["电话", basic.phone], ["邮箱", basic.email],
    ["地点", basic.location], ["证件号", basic.id_number],
  ].filter(([, v]) => v);
  const edu = (data.education || []).map((e) => `${e.school || ""} ${e.major || ""} ${e.degree || ""}`).filter(Boolean);
  const work = (data.work || []).map((w) => `${w.company || ""} · ${w.title || ""}`).filter(Boolean);
  return `
    ${rows.length ? `<dl class="profile-basic">${rows.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>` : '<p class="small muted">基本字段为空</p>'}
    ${edu.length ? `<p class="small">教育：${esc(edu.join("；"))}</p>` : ""}
    ${work.length ? `<p class="small">工作：${esc(work.join("；"))}</p>` : ""}
    ${profile.stale ? '<p class="small warn-note">简历在抽取后有改动，建议重新生成。</p>' : ""}
    <div class="row mt-2">
      <button class="btn btn-outline btn-sm" type="button" data-action="profile-extract" data-id="${esc(resumeId)}">${profile.stale ? "重新生成" : "重新抽取"}</button>
      <button class="btn btn-ghost btn-sm" type="button" data-action="profile-edit" data-id="${esc(resumeId)}">编辑</button>
    </div>`;
}

export function profileEditFormHtml(resumeId, profile) {
  const data = (profile && profile.data) || {};
  return `<form data-form="profile-edit">
    <input type="hidden" name="resume_id" value="${esc(resumeId)}">
    <div class="form-grid">
      <div class="field"><label>姓名</label><input name="basic_name" value="${esc((data.basic || {}).name || "")}"></div>
      <div class="field"><label>电话</label><input name="basic_phone" value="${esc((data.basic || {}).phone || "")}"></div>
      <div class="field"><label>邮箱</label><input name="basic_email" value="${esc((data.basic || {}).email || "")}"></div>
      <div class="field"><label>地点</label><input name="basic_location" value="${esc((data.basic || {}).location || "")}"></div>
      <div class="field"><label>证件号（敏感，仅本地保存）</label><input name="basic_id_number" value="${esc((data.basic || {}).id_number || "")}"></div>
      <div class="field wide"><label>技能（逗号分隔）</label><input name="skills" value="${esc((data.skills || []).join(", "))}"></div>
      <div class="field wide"><label>个人总结</label><textarea name="summary" rows="2">${esc(data.summary || "")}</textarea></div>
    </div>
    <p class="small muted mt-2">教育/工作/项目明细暂以抽取结果为准，可在生成后按需重抽。</p>
    <div class="actions mt-3">
      <button class="btn btn-primary btn-sm" type="submit">保存档案</button>
      <button class="btn btn-ghost btn-sm" type="button" data-action="close-modal">取消</button>
    </div>
  </form>`;
}

export async function renderResumeCenter(app, { resumeId = null, showList = false } = {}) {
  if (!showList) {
    /* UX 走查 P1-C：档案路径先上骨架屏，替代一行「加载中...」。 */
    app.innerHTML = resumeDetailSkeletonHtml();
  }
  if (resumeId && resumeId !== RESUME_LIST_SENTINEL) {
    await renderResumeDetailView(app, resumeId);
  } else if (showList) {
    await renderResumeListView(app);
  } else {
    /* v2.0 shell：默认直达最新主简历的 65/35 详情视图（v2 重设计契约）；
     * 显式 #/resume/list 或无简历时才渲染列表/空态。 */
    state.resumes = await api("/api/master-resumes");
    /* Bug-05: 默认直达带诊断的主简历，避免最新“另存版”抢占入口。 */
    const first = Array.isArray(state.resumes)
      ? state.resumes.find((resume) => resume && resume.latest_diagnosis) ||
        state.resumes[0] ||
        null
      : null;
    if (first) {
      await renderResumeDetailView(app, first.resume_id);
    } else {
      await renderResumeListView(app);
    }
  }
}

/* 供 main.js 复用：编辑后 closeModal 由 handleForm 统一处理，这里保持契约 */
export { closeModal };

/* ------------------------------------------------------------------ */
/* 简历中心页面内动作（事件委托）                                        */
/* ------------------------------------------------------------------ */

/* 简历中心的页面内交互（事件委托），不往 main.js 的动作表里加东西：
 * 1) 「查看完整 ATS 建议」（RS-03 移动摘要）：摘要卡在诊断卡里，完整建议在
 *    右栏 ATS 卡；窄屏时右栏排在正文之后，这里滚动并聚焦过去，给键盘用户
 *    一个可见落点（只滚动，不触发任何请求）。
 * 2) 列表卡主体可点进详情（RS-06）：鼠标用户不用精确点中按钮；卡片内真正的
 *    按钮/菜单仍走各自 action，不受影响。
 * 3) 列表卡「去看诊断」：进详情后把诊断卡滚进视口（只定位，不发起诊断）。
 * 4) 详情页导出/更多、列表卡 kebab 的下拉互斥与收起：原生 <details> 不会
 *    自动收起，两个都展开时会互相盖住菜单项。 */
if (typeof document !== "undefined") {
  const RESUME_DOCKS =
    "details[data-resume-export], details[data-resume-more]";
  const CARD_MENUS = "[data-resume-card] details[data-resume-card-more]";
  /* 卡片里这些元素自己就是交互目标，点它们时不要接管成「打开详情」。 */
  const CARD_INTERACTIVE =
    "button, summary, a, input, textarea, select, label, [role='button']";
  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    if (target.closest("[data-action='ats-summary-jump']")) {
      const card = document.querySelector("[data-ats-health-card]");
      if (card) {
        card.setAttribute("tabindex", "-1");
        card.focus({ preventScroll: true });
        card.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      return;
    }

    /* 「去看诊断」：记下落地目标，详情渲染完成后滚动到诊断卡。 */
    if (target.closest("[data-resume-focus='diagnosis']")) {
      pendingResumeFocus = "diagnosis";
    }

    /* 列表卡主体 → 详情（按钮/菜单自己处理，不重复导航）。 */
    const resumeCard = target.closest("[data-resume-card]");
    if (resumeCard && !target.closest(CARD_INTERACTIVE)) {
      const resumeId = resumeCard.dataset.resumeId;
      if (resumeId) {
        window.location.hash = `#/resume/${encodeURIComponent(resumeId)}`;
      }
      return;
    }

    /* 列表卡 kebab：同时只展开一个，点页面其它位置收起（与详情页下拉一致）。 */
    const cardMenus = [...document.querySelectorAll(CARD_MENUS)];
    if (cardMenus.length) {
      const openMenu = target.closest("details[data-resume-card-more]");
      cardMenus.forEach((menu) => {
        if (menu !== openMenu) menu.open = false;
      });
    }

    const docks = [...document.querySelectorAll(RESUME_DOCKS)];
    if (!docks.length) return;
    const owner = target.closest(RESUME_DOCKS);
    /* 点菜单项：执行完动作就收起当前菜单。 */
    if (owner && target.closest("button[data-action]")) {
      owner.open = false;
      return;
    }
    /* 展开另一个菜单前先收起其它菜单（summary 点击交给浏览器原生 toggle）。 */
    if (owner) {
      docks.forEach((node) => {
        if (node !== owner) node.open = false;
      });
      return;
    }
    docks.forEach((node) => {
      node.open = false;
    });
  });

  /* 卡片层叠修复：列表容器带 .motion-stagger，入场动画让每张卡都留下 identity
   * transform → 每张卡各自成为层叠上下文；于是后一张卡会把前一张卡展开的
   * kebab 菜单盖住（实测点菜单项时 pointer 被下一张卡拦截）。
   * 展开时把宿主卡抬到其它卡之上、收起后还原——等价于看板用
   * .board-card:has(.board-more[open]) 做的层级提升；styles.css 不在本次
   * 改动范围，只能用行内层叠属性兜底。 */
  /* Phase 3：kebab 菜单层叠上下文由 .resume-card:has(details[open]) 接管
   * （styles.css L13133，B7 落地），这里不再写行内 position/z-index。 */
  const syncCardMenuLayer = () => {};
  /* details 的 toggle 事件不冒泡，用捕获阶段监听。 */
  document.addEventListener(
    "toggle",
    (event) => {
      const menu = event.target;
      if (menu instanceof Element && menu.matches("details[data-resume-card-more]")) {
        syncCardMenuLayer(menu.closest("[data-resume-card]"));
      }
    },
    true,
  );
  /* 菜单项点击后 main.js 会收起 kebab（不经过我们关闭）；事件循环结束后
   * 按最终 open 状态校准一次，避免卡片一直保持抬升。 */
  document.addEventListener("click", () => {
    if (!document.querySelector(CARD_MENUS)) return;
    requestAnimationFrame(() => {
      document
        .querySelectorAll("[data-resume-card]")
        .forEach((card) => syncCardMenuLayer(card));
    });
  });
}
