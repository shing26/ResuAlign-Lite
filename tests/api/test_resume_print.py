"""Unit tests for the print-resume renderer (PDF export path)."""

from __future__ import annotations

from resualign.api.services.resume_print import parse_draft, render_resume_print_html

DRAFT = (
    "陈振成 AI 应用开发 / Agent 研发（Java + Python 双栈）\n"
    "132-2978-7513 ccshing426@qq.com github.com/shing26\n"
    "教育经历\n"
    "广东理工学院 — 计算机科学与技术（统招本科） 2025.09 – 2027.06\n"
    "主修：Java 程序设计、数据结构\n"
    "专业技能清单\n"
    "- AI 应用工程：LLM 编排、MCP 协议\n"
    "核心项目经历 Northwind — 客服 Agent\n"
    "技术栈：Java 21 · Spring Boot 3.3\n"
    "- 有界编排（成本可预算）：改为有界状态机\n"
    "续行：并回上一条 bullet\n"
    "Southgate — 求职工作台\n"
    "技术栈：Python · FastAPI\n"
    "- 三道门禁：出处解析\n"
    "Eastwood — 代码理解\n"
    "技术栈：Node 24\n"
    "- MCP 封装：17 个只读工具\n"
    "综合评价\n"
    "- 设计先行：ADR 留痕\n"
)


def test_parse_draft_keeps_all_three_projects():
    document = parse_draft(DRAFT)
    projects = [
        item
        for section in document["sections"]
        for item in section["items"]
        if item.get("type") == "project"
    ]
    assert [project["name"] for project in projects] == [
        "Northwind", "Southgate", "Eastwood",
    ]
    assert projects[0]["tech"] == "Java 21 · Spring Boot 3.3"
    assert projects[0]["bullets"][0]["tag"] == "有界编排（成本可预算）"
    # 硬折行续行并回上一条，而不是新起一条或粘到下一个项目
    assert projects[0]["bullets"][0]["text"].endswith(
        "改为有界状态机 续行：并回上一条 bullet"
    )


def test_parse_draft_header_and_education():
    document = parse_draft(DRAFT)
    assert document["name"] == "陈振成"
    assert document["contact"]["phone"] == "132-2978-7513"
    assert document["contact"]["email"] == "ccshing426@qq.com"
    assert document["contact"]["github"] == "github.com/shing26"
    edu = document["sections"][0]["items"]
    assert edu[0]["school"] == "广东理工学院"
    assert edu[0]["major"] == "计算机科学与技术（统招本科）"
    assert edu[0]["date"] == "2025.09 – 2027.06"
    assert edu[1]["type"] == "major"


def test_render_uses_job_role_as_objective():
    html = render_resume_print_html(
        {"title": "Java 后台开发工程师（所属类别：软件算法研发类）"},
        DRAFT,
    )
    assert '<div class="rs-role">Java 后台开发工程师</div>' in html


def test_render_has_no_audit_metadata():
    html = render_resume_print_html({"title": "后端工程师"}, DRAFT)
    for leaked in ("定稿 v", "匹配分", "engine:", "采纳项", "diff_id"):
        assert leaked not in html


def test_render_escapes_content():
    html = render_resume_print_html(
        {"title": "后端工程师"},
        "张三 求职意向\n联系方式\n- 技能：<script>alert(1)</script>\n",
    )
    assert "&lt;script&gt;" in html
    assert "<script>" not in html
