"""API tests for the canonical final-draft export endpoint (MVP-03)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.job_library import JobLibraryStore
from resualign.jobs import JobRegistry
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    MasterResumeStore,
    UserStore,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def temp_stores(tmp_path):
    saved = {
        "registry": api_module._registry,
        "users": api_module._users,
        "resumes": getattr(api_module, "_resumes", None),
        "applications": getattr(api_module, "_applications", None),
        "jobs": api_module._jobs,
        "settings": getattr(api_module, "_settings_store", None),
        "personal_mode": api_module._PERSONAL_MODE,
    }
    db_path = tmp_path / "export-api.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = True
    yield
    for name, value in saved.items():
        setattr(api_module, name, value)


def _create_job(title="Backend Engineer", jd_text="Python backend."):
    r = client.post(
        "/api/jobs",
        json={"title": title, "jd_text": jd_text},
    )
    assert r.status_code == 201
    return r.json()


def _seed_accepted_draft(job):
    api_module._jobs.save_alignment(
        job["tenant_id"],
        job["job_id"],
        jd_profile={"must_have_skills": ["Python"]},
        gap_report={"missing_keywords": ["Redis"]},
        match_score=81.5,
        diffs=[
            {
                "diff_id": "d1",
                "type": "modify",
                "section": "experience",
                "original": "Python developer.",
                "proposed": "Python developer with Redis caching.",
                "reason": "JD match",
                "confidence": "high",
                "provenance": "Python developer.",
                "provenance_state": "verified",
            },
            {
                "diff_id": "d2",
                "type": "add",
                "section": "skills",
                "original": "",
                "proposed": "Redis cluster operations.",
                "reason": "Gap coverage",
                "confidence": "medium",
                "provenance_quote": "Redis",
                "provenance_state": "verified",
            },
        ],
        invalid_diffs=[],
        draft="# Experience\nPython developer with Redis caching.",
        model="test-model",
        prompt_version="engine.v1",
    )
    saved = client.post(
        f"/api/jobs/{job['job_id']}/final-draft",
        json={
            "draft": "# Experience\nPython developer with Redis caching.",
            "accepted_diff_ids": ["d1"],
        },
    )
    assert saved.status_code == 200


def test_export_markdown_contains_meta_and_accepted_diff():
    job = _create_job()
    _seed_accepted_draft(job)

    r = client.post(
        f"/api/jobs/{job['job_id']}/exports",
        json={"format": "markdown"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["format"] == "markdown"
    assert body["job_title"] == "Backend Engineer"
    assert body["final_draft_version"] == 1
    assert body["filename"] == "resualign-Backend-Engineer-v1.md"
    assert body["meta"]["model"] == "test-model"
    assert body["meta"]["prompt_version"] == "engine.v1"
    assert body["accepted_diff_ids"] == ["d1"]
    assert len(body["accepted_diffs"]) == 1
    assert body["accepted_diffs"][0]["diff_id"] == "d1"
    assert body["content"].startswith("# Backend Engineer")
    assert "engine.v1" in body["content"]
    assert "Python developer with Redis caching" in body["content"]


def test_export_json_is_canonical_and_ignores_client_diff_ids():
    job = _create_job()
    _seed_accepted_draft(job)

    r = client.post(
        f"/api/jobs/{job['job_id']}/exports",
        json={"format": "json"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["format"] == "json"
    assert body["accepted_diff_ids"] == ["d1"]
    assert len(body["accepted_diffs"]) == 1
    # Bug-03: JSON content is plain text (dry of Markdown markers) while
    # sections/skills stay structured; the raw draft stays untouched.
    assert body["content"] == "Experience\nPython developer with Redis caching."
    assert body["filename"] == "resualign-Backend-Engineer-v1.json"
    # Bug-03: JSON 导出带结构化 sections/skills（无 ## 节的草稿 sections 为空，
    # skills 回退到 JD must_have）。
    assert body["sections"] == []
    assert body["skills"] == ["Python"]


def test_export_json_splits_sections_and_skills():
    job = _create_job()
    _seed_accepted_draft(job)
    saved = client.post(
        f"/api/jobs/{job['job_id']}/final-draft",
        json={
            "draft": "# 张三\n\n"
            "## 联系方式\n- 电话：138-0000-0000\n"
            "## 工作经历\n\n### 某某电商 高级后端工程师\n- 主导微服务化改造\n"
            "## 专业技能\n- 编程语言：Java、Go、Python\n"
            "- 框架：Spring Boot、Spring Cloud\n",
        },
    )
    assert saved.status_code == 200
    r = client.post(
        f"/api/jobs/{job['job_id']}/exports",
        json={"format": "json"},
    )
    assert r.status_code == 200
    body = r.json()
    assert [s["heading"] for s in body["sections"]] == [
        "联系方式",
        "工作经历",
        "专业技能",
    ]
    assert "138-0000-0000" in body["sections"][0]["content"]
    assert "主导微服务化改造" in body["sections"][1]["content"]
    assert body["skills"] == [
        "Java",
        "Go",
        "Python",
        "Spring Boot",
        "Spring Cloud",
    ]


def test_export_pdf_returns_print_html_contract():
    job = _create_job()
    _seed_accepted_draft(job)

    r = client.post(
        f"/api/jobs/{job['job_id']}/exports",
        json={"format": "pdf"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["render"] == "print-html"
    assert body["print_target"] == "#print-root"
    assert '<article class="rs-print"' in body["content"]
    assert "Python developer with Redis caching" in body["content"]
    # 投递版式（2026-10-27 用户反馈）：PDF 只放简历本身，不再输出定稿版本、
    # 匹配分、prompt 版本、采纳 diff id 这些审计信息；完整溯源在 Markdown / JSON。
    assert "定稿 v" not in body["content"]
    assert "匹配分" not in body["content"]
    assert "engine.v1" not in body["content"]
    assert "采纳项" not in body["content"]
    assert body["filename"] == "resualign-Backend-Engineer-v1.pdf"


_PDF_DRAFT = (
    "陈振成 AI 应用开发 / Agent 研发（Java + Python 双栈）\n"
    "132-2978-7513 ccshing426@qq.com github.com/shing26\n"
    "教育经历\n"
    "广东理工学院 — 计算机科学与技术（统招本科） 2025.09 – 2027.06\n"
    "主修：Java 程序设计、数据结构\n"
    "专业技能清单\n"
    "- AI 应用工程：LLM 编排、MCP 协议、<script>alert(1)</script>\n"
    "- 后端技术栈：Python / FastAPI\n"
    "核心项目经历\n"
    "ShopPilot — 大促客服 Agent\n"
    "技术栈：Java 21 · Spring Boot 3.3\n"
    "情境：大促客服需同时答政策与办业务\n"
    "- 有界编排（成本可预算）：自由 Agent 循环不可预算 → 改为有界状态机\n"
    "意图级联（1 次模型请求）：三级级联降低开销\n"
    "ResuAlign-Lite — 求职工作台\n"
    "技术栈：Python · FastAPI\n"
    "- 三道门禁：出处解析 + 内容核查\n"
    "CodeCompass — 代码理解工作台\n"
    "技术栈：Node 24 · TypeScript\n"
    "- MCP 封装：17 个只读工具\n"
    "综合评价\n"
    "- 设计先行：ADR 留痕\n"
)


def test_export_pdf_renders_structured_resume():
    from resualign.api.services.jobs import build_job_export

    job = {
        "title": "AI Agent 应用研发工程师（职位 ID A145034）",
        "final_draft": _PDF_DRAFT,
        "final_draft_version": 4,
        "model": "deepseek-v4-flash",
        "generated_at": 0,
        "diffs": [],
    }
    content = build_job_export(job, "pdf")["content"]

    for heading in ("教育经历", "专业技能清单", "核心项目经历", "综合评价"):
        assert f"<h2>{heading}</h2>" in content
    # 三个项目必须各自成块，不能被并进上一条 bullet（用户反馈的「项目经历被删减」）
    assert content.count('<div class="rs-project">') == 3
    for name in ("ShopPilot", "ResuAlign-Lite", "CodeCompass"):
        assert name in content
    # 求职意向按岗位推导，去掉「职位 ID」噪声
    assert '<div class="rs-role">AI Agent 应用研发工程师</div>' in content
    assert "【有界编排（成本可预算）】" in content
    assert "意图级联（1 次模型请求）：三级级联降低开销" in content
    assert "&lt;script&gt;" in content
    assert "<script>" not in content


def test_export_pdf_has_no_audit_metadata():
    from resualign.api.services.jobs import build_job_export

    job = {
        "title": "后端工程师",
        "final_draft": _PDF_DRAFT,
        "final_draft_version": 7,
        "model": "deepseek-v4-flash",
        "prompt_version": "engine:diag:v3;tailor:v5",
        "generated_at": 1793000000,
        "eval_score": {"jd_match_score": 88},
        "match_score_detail": {"total": 61.5},
        "diffs": [],
    }
    content = build_job_export(job, "pdf")["content"]
    for leaked in ("定稿 v7", "匹配分", "engine:", "采纳项", "diff_id"):
        assert leaked not in content


def test_export_missing_job_returns_404():
    r = client.post(
        "/api/jobs/does-not-exist/exports",
        json={"format": "markdown"},
    )
    assert r.status_code == 404


def test_export_without_final_draft_returns_422():
    job = _create_job()
    r = client.post(
        f"/api/jobs/{job['job_id']}/exports",
        json={"format": "markdown"},
    )
    assert r.status_code == 422
    assert "尚未保存定稿" in r.json()["detail"]


def test_export_unknown_format_returns_422():
    job = _create_job()
    _seed_accepted_draft(job)
    r = client.post(
        f"/api/jobs/{job['job_id']}/exports",
        json={"format": "docx"},
    )
    assert r.status_code == 422


def test_export_cross_tenant_returns_404():
    other = api_module._jobs.create_job(
        tenant_id="other-tenant",
        title="Other",
        jd_text="Other JD.",
    )
    api_module._jobs.save_final_draft(
        "other-tenant",
        other["job_id"],
        "Cross tenant draft",
    )
    r = client.post(
        f"/api/jobs/{other['job_id']}/exports",
        json={"format": "markdown"},
    )
    assert r.status_code == 404


def test_export_legacy_final_draft_without_alignment_meta():
    job = _create_job()
    api_module._jobs.save_final_draft(
        job["tenant_id"],
        job["job_id"],
        "Legacy final draft",
    )
    r = client.post(
        f"/api/jobs/{job['job_id']}/exports",
        json={"format": "json"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["model"] is None
    assert body["meta"]["prompt_version"] is None
    assert body["meta"]["match_score"] is None
    assert body["accepted_diff_ids"] == []
    assert body["content"] == "Legacy final draft"


def test_export_labels_match_score_calibers():
    """#82 匹配分双口径：AI 评估分与规则四维分在导出里分别标注，
    不再共用一个「匹配分」名字承载两个数值。"""
    job = _create_job()
    api_module._jobs.save_alignment(
        job["tenant_id"],
        job["job_id"],
        match_score=72,
        match_score_detail={"total": 52.0, "version": 1},
        eval_score={"jd_match_score": 72, "hallucination_detected": False},
        draft="Python developer with Redis caching.",
    )
    saved = client.post(
        f"/api/jobs/{job['job_id']}/final-draft",
        json={"draft": "Python developer with Redis caching."},
    )
    assert saved.status_code == 200
    md = client.post(
        f"/api/jobs/{job['job_id']}/exports",
        json={"format": "markdown"},
    ).json()
    assert "- 匹配分（AI 评估）：72" in md["content"]
    assert "- 匹配分（规则四维）：52.0" in md["content"]
    pdf = client.post(
        f"/api/jobs/{job['job_id']}/exports",
        json={"format": "pdf"},
    ).json()
    # PDF 是投递件：不带匹配分/审计元信息（2026-10-27 用户反馈），
    # 双口径由 Markdown 与 JSON 导出承载。
    assert "匹配分" not in pdf["content"]
    js = client.post(
        f"/api/jobs/{job['job_id']}/exports",
        json={"format": "json"},
    ).json()
    assert js["meta"]["eval_match_score"] == 72
    assert js["meta"]["rule_match_score"] == 52.0
