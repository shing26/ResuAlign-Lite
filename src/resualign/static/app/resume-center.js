/* ResuAlign v2.0 — Resume Center (蓝图文件 4)
 * 简历中心重构：主视图彻底切除内联 <textarea>（新建/编辑一律走模态框），
 * 左 65% renderMarkdown 结构化 Sheet + 编辑/复制 MD/导出 PDF 阻尼按钮，
 * 右 35% ATS 健康度仪表盘 + Version Timeline 竖线时间轴。
 */
import {
  api,
  closeModal,
  recoverDiagnosis,
  showModal,
  state,
  toast,
} from "./events.js";
import {
  atsHealthCardHtml,
  esc,
  formatDate,
  renderMarkdown,
  versionTimelineHtml,
} from "./format.js";

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

async function renderResumeListView(app) {
  state.resumes = await api("/api/master-resumes");
  const hasResumes = state.resumes.length > 0;
  const cards = state.resumes
    .map(
      (resume) => `
      <div class="card resume-card card-base card-hover-soft">
        <div class="card-head">
          <div>
            <div class="card-title">${esc(resume.title)}</div>
            <div class="card-meta">更新于 ${formatDate(resume.updated_at)} · v${resume.current_version}</div>
          </div>
          <span class="badge badge-teal">当前版本 v${resume.current_version}</span>
        </div>
        <div class="pre" style="max-height:160px">${esc(resume.content)}</div>
        <div class="row" style="margin-top:10px">
          <button class="btn btn-primary btn-sm" data-action="open-resume-archive" data-id="${resume.resume_id}">查看档案</button>
          <button class="btn btn-outline btn-sm" data-action="edit-resume" data-id="${resume.resume_id}">编辑</button>
          <button class="btn btn-danger btn-sm" data-action="delete-resume" data-id="${resume.resume_id}">删除</button>
        </div>
      </div>`,
    )
    .join("");

  app.innerHTML = `
    <div class="page-header page-header--resume flex items-center justify-between">
      <div>
        <h2>简历中心</h2>
        <div class="sub">维护主简历与版本历史，工作台始终基于当前版本生成对齐稿</div>
      </div>
      <div class="row">
        <button class="btn btn-primary" data-action="new-resume">新建主简历</button>
        <button class="btn btn-outline" data-action="upload-resume">上传简历文件</button>
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
  const diagnosis =
    state.diagnosis &&
    resume.latest_diagnosis_job_id &&
    state.diagnosis.job_id === resume.latest_diagnosis_job_id
      ? diagnosisFromSnapshot(state.diagnosis)
      : null;
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
          <span class="status-line" data-resume-band-status><span class="dot dot-success" aria-hidden="true"></span><span data-resume-band-status-text>最近诊断：${diagnosis && Number.isFinite(Number(diagnosis.score)) ? `${esc(diagnosis.score)} 分` : "尚未诊断"}</span></span>
          <button class="btn btn-primary btn-sm" data-action="diagnose-resume" data-id="${resume.resume_id}">诊断简历</button>
          <button class="btn btn-secondary btn-sm" data-action="export-resume-md" data-id="${resume.resume_id}">导出 Markdown</button>
          <button class="btn btn-danger btn-sm" data-action="delete-resume" data-id="${resume.resume_id}">删除</button>
        </div>
      </div>
      <section class="panel diagnosis-panel diagnosis-banner" data-diagnosis-panel>
        <div class="diagnosis-banner__row">
          <div class="diagnosis-banner__copy">
            <span class="diagnosis-banner__label">简历诊断</span>
            <span class="small muted" data-diagnosis-meta>尚未诊断</span>
          </div>
          <div class="diagnosis-banner__actions">
            <button class="btn btn-outline btn-sm" data-action="export-diagnosis" hidden>导出 PDF</button>
            <button class="btn btn-secondary btn-sm" data-action="export-diagnosis-md" hidden>导出 Markdown</button>
            <button class="btn btn-primary btn-sm" data-action="diagnose-resume" data-id="${resume.resume_id}">诊断简历</button>
          </div>
        </div>
        <div class="progress-wrap" data-diagnosis-progress hidden>
          <div class="progress-track"><div class="progress-fill" data-diagnosis-fill style="width:5%"></div></div>
          <span class="small" data-diagnosis-stage>排队中</span>
          <span class="small muted" data-diagnosis-elapsed>0s</span>
          <button class="btn btn-ghost btn-sm" type="button" data-action="cancel-diagnosis" hidden>取消任务</button>
        </div>
        <div data-diagnosis-result hidden></div>
        <div class="form-error" data-diagnosis-error hidden></div>
      </section>
      <div class="resume-archive-grid resume-grid">
        <section class="panel resume-sheet" data-resume-sheet>
          <div class="resume-sheet-head">
            <div>
              <h2>完整简历</h2>
              <p>Markdown 文档 · 预览与源码双态</p>
            </div>
            <div class="resume-sheet-actions">
              <button class="btn btn-primary btn-sm" data-action="toggle-resume-inline-edit" data-id="${resume.resume_id}">编辑源码</button>
              <button class="btn btn-outline btn-sm" data-action="edit-resume" data-id="${resume.resume_id}">编辑</button>
              <button class="btn btn-outline btn-sm" data-action="copy-resume-md" data-id="${resume.resume_id}">复制 MD</button>
              <button class="btn btn-secondary btn-sm" data-action="print-resume">导出 PDF</button>
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
              <span class="pill ${diagnosis && Number.isFinite(Number(diagnosis.score)) ? "pill-success" : "pill-neutral"}">${diagnosis && Number.isFinite(Number(diagnosis.score)) ? `${esc(diagnosis.score)} / 100` : "未诊断"}</span>
            </div>
            <div data-ats-health-mount>${atsHealthCardHtml(diagnosis)}</div>
          </section>
          <section class="rail-section" data-version-timeline-card>
            <div class="rail-section-head">
              <h3>版本时间线</h3>
            </div>
            ${versionTimelineHtml(versions, resume.current_version, resume.resume_id)}
          </section>
        </aside>
      </div>
    </div>`;
  state.diagnosisResumeId = resumeId;
  await recoverDiagnosis(resume);
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

/* 新建主简历模态框；prefill 用于上传解析回填（title/content）。 */
export function openResumeCreator(prefill = {}) {
  const title = prefill.title || "";
  const content = prefill.content || "";
  showModal(
    "新建主简历",
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

export async function renderResumeCenter(app, { resumeId = null, showList = false } = {}) {
  if (resumeId && resumeId !== "list") {
    await renderResumeDetailView(app, resumeId);
  } else if (showList) {
    await renderResumeListView(app);
  } else {
    /* v2.0 shell：默认直达最新主简历的 65/35 详情视图（preview.html 契约）；
     * 显式 #/resume/list 或无简历时才渲染列表/空态。 */
    state.resumes = await api("/api/master-resumes");
    const first = Array.isArray(state.resumes) ? state.resumes[0] : null;
    if (first) {
      await renderResumeDetailView(app, first.resume_id);
    } else {
      await renderResumeListView(app);
    }
  }
}

/* 供 main.js 复用：编辑后 closeModal 由 handleForm 统一处理，这里保持契约 */
export { closeModal };
