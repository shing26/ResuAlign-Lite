"""Render a saved final draft as a print-ready resume (PDF export path).

Why this module exists
----------------------
The editor's final draft is plain text: section titles are bare lines, bullets
are hard-wrapped, and project metadata (tech stack, links, dates) is glued to
the same lines. The old PDF path wrapped that text in a pre block and also
printed export metadata and accepted diff ids, so the printed resume looked
like a log.

This renderer restores the resume structure for printing: a header with the
name, a per-job 求职意向 (derived from the job title) and contact line, then
sections, and project blocks with a tech line and tag bullets. It emits a
self-contained HTML fragment with an inline style block so the export does not
depend on the app stylesheet (and the CSS budget ratchet is untouched).
"""

from __future__ import annotations

import html
import re
from typing import Any

_HEADINGS = (
    "个人信息", "教育经历", "教育背景", "专业技能清单", "专业技能",
    "技能清单", "核心项目经历", "项目经历", "工作经历", "实习经历",
    "实践经历", "校园经历", "获奖经历", "荣誉奖项", "证书",
    "自我评价", "工作方式与个人特点", "综合评价", "求职意向",
)

# 打印件用模板里的通用章节名（求职简历不暴露内部叫法）。
_TITLE_MAP = {
    "专业技能清单": "专业技能",
    "技能清单": "专业技能",
    "核心项目经历": "核心项目",
    "项目经历": "核心项目",
    "工作方式与个人特点": "综合评价",
    "工作方式": "综合评价",
    "个人特点": "综合评价",
    "自我评价": "综合评价",
}

_HEADING_KINDS = {
    "教育经历": "edu", "教育背景": "edu",
    "专业技能清单": "skills", "专业技能": "skills", "技能清单": "skills",
    "核心项目经历": "projects", "项目经历": "projects", "工作经历": "projects",
    "实习经历": "projects", "实践经历": "projects", "校园经历": "projects",
}

_DATE_RANGE = re.compile(r"\d{4}\s*[.年/-]\s*\d{1,2}\s*[–\-—~至]\s*\d{4}\s*[.年/-]\s*\d{1,2}")
_GITHUB = re.compile(r"github\.com/[\w.-]+/[\w.-]+")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"1[3-9]\d[-\s]?\d{4}[-\s]?\d{4}")
_SCHOOL_SPLIT = re.compile(r"(?<![\u4e00-\u9fff])(?=[\u4e00-\u9fff]{2,20}(?:学院|大学)\s*[—·-])")
_ROLE_NOISE = re.compile(r"[（(][^）)]*(?:职位\s*ID|所属类别|招聘|岗位\s*ID)[^）)]*[）)]")


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def _inline(text: str) -> str:
    """Escape then re-enable bold markdown (the only inline syntax the app emits)."""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", _esc(text))


def _split_label(text: str) -> tuple[str, str]:
    """Split a short leading label from its body, e.g. 标签：正文."""
    position = text.find("：")
    if 0 < position <= 30:
        return text[:position].strip(), text[position + 1:].strip()
    return "", text


def _split_headings(line: str) -> list[tuple[str, str]]:
    """Split section titles glued to content by the editor's hard wrap."""
    segments: list[tuple[str, str]] = []
    remaining = line.strip()
    if remaining.startswith("#"):
        stripped = remaining.lstrip("#").strip()
        if stripped in _HEADINGS:
            return [("heading", stripped)]
        if stripped:
            return [("text", stripped)]
        return []
    for _ in range(8):
        found: tuple[int, int] | None = None
        for heading in _HEADINGS:
            if remaining == heading:
                found = (0, len(remaining))
                break
            for separator in (" ", "\u3000"):
                if remaining.startswith(heading + separator):
                    found = (0, len(heading))
                    break
                if remaining.endswith(separator + heading):
                    found = (len(remaining) - len(heading), len(remaining))
                    break
            if found:
                break
        if found is None:
            break
        start, end = found
        if start > 0:
            segments.append(("text", remaining[:start].strip()))
        segments.append(("heading", remaining[start:end]))
        remaining = remaining[end:].strip()
        if not remaining:
            return segments
    if remaining:
        segments.append(("text", remaining))
    return segments


def _parse_education(lines: list[str], items: list[dict[str, Any]]) -> None:
    for line in lines:
        pieces = [piece.strip() for piece in _SCHOOL_SPLIT.split(line) if piece.strip()]
        for piece in pieces:
            if piece.startswith(("主修", "专业", "课程")):
                items.append({"type": "major", "text": piece})
                continue
            dates = _DATE_RANGE.search(piece)
            head = piece[: dates.start()].strip() if dates else piece
            date = dates.group(0) if dates else ""
            head = head.strip(" —·-")
            parts = re.split(r"\s*[—·]\s*|\s{2,}", head, maxsplit=1)
            school = parts[0].strip()
            major = parts[1].strip() if len(parts) > 1 else ""
            if school:
                items.append({
                    "type": "edu", "school": school, "major": major, "date": date,
                })


def _parse_skills(lines: list[str], items: list[dict[str, Any]]) -> None:
    for line in lines:
        cleaned = line[2:].strip() if line.startswith("- ") else line
        cat, body = _split_label(cleaned)
        items.append({"type": "skill", "cat": cat, "text": body})


_PROJECT_PREFIX = re.compile(r"(?=(?:技术栈|情境|背景|任务|结果|痛点)：)")


def _project_segments(line: str) -> list[str]:
    """拆分被硬折行粘在一起的项目元信息（如 技术栈… 情境… 在同一行）。"""
    return [part.strip() for part in _PROJECT_PREFIX.split(line) if part.strip()]


def _parse_projects(lines: list[str], items: list[dict[str, Any]]) -> None:
    project: dict[str, Any] | None = None
    queue: list[str] = []
    for raw_line in lines:
        queue.extend(_project_segments(raw_line))
    while queue:
        line = queue.pop(0)
        bullet = line.startswith("- ")
        text = line[2:].strip() if bullet else line
        link = _GITHUB.search(text)
        looks_like_project = link is not None or (
            "—" in text
            and not text.startswith(("技术栈", "情境", "背景", "任务", "结果"))
        )
        if not bullet and looks_like_project:
            dates = _DATE_RANGE.search(text)
            before = (text[: link.start()].strip() if link else text.strip())
            if dates and dates.start() < len(before):
                before = before[: dates.start()].strip()
            # 去掉「角色 / 独立开发 · 个人开源」这类尾部元信息，只留项目名与一句话定位。
            if " / " in before:
                before = before.split(" / ", 1)[0]
            before = re.sub(
                r"\s+(?:AI\s*工程|全栈|后端|前端|算法|数据|测试|AI\s*工具)$", "", before
            )
            before = before.rstrip(" ·/-—")
            name, description = before, ""
            if "—" in before:
                name, description = [part.strip() for part in before.split("—", 1)]
            project = {
                "type": "project",
                "name": name,
                "description": description,
                "link": link.group(0) if link else "",
                "date": dates.group(0) if dates else "",
                "tech": "",
                "scene": "",
                "bullets": [],
            }
            items.append(project)
            continue
        if project is None:
            items.append({"type": "para", "text": text})
            continue
        if text.startswith("技术栈"):
            project["tech"] = text.split("：", 1)[-1].strip()
        elif text.startswith(("情境", "背景", "任务", "结果")):
            project["scene"] = (project["scene"] + " " + text).strip()
        elif bullet:
            tag, body = _split_label(text)
            project["bullets"].append({"tag": tag, "text": body})
        else:
            if project["bullets"]:
                project["bullets"][-1]["text"] += " " + text
            elif project["scene"]:
                project["scene"] += " " + text
            else:
                project["description"] = (project["description"] + " " + text).strip()


def _parse_generic(lines: list[str], items: list[dict[str, Any]]) -> None:
    for line in lines:
        if line.startswith("- "):
            tag, body = _split_label(line[2:].strip())
            items.append({"type": "bullet", "tag": tag, "text": body})
        else:
            tag, body = _split_label(line)
            items.append({"type": "para", "tag": tag, "text": body})


def parse_draft(draft: str) -> dict[str, Any]:
    """Turn the plain-text final draft into a structured resume document."""
    flat: list[tuple[str, str]] = []
    for raw in (draft or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        for kind, text in _split_headings(line):
            flat.append((kind, text))

    header_lines: list[str] = []
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for kind, text in flat:
        if kind == "heading":
            current = {
                "title": _TITLE_MAP.get(text, text),
                "kind": _HEADING_KINDS.get(text, "generic"),
                "items": [],
                "lines": [],
            }
            sections.append(current)
            continue
        if current is None:
            header_lines.append(text)
        else:
            current["lines"].append(text)

    name, role = "", ""
    if header_lines:
        first = header_lines[0]
        head = first.split(" ", 1)
        name = head[0].strip()
        role = head[1].strip() if len(head) > 1 else ""
    contact: dict[str, str] = {}
    for line in header_lines[1:]:
        if "phone" not in contact:
            found = _PHONE.search(line)
            if found:
                contact["phone"] = found.group(0)
        if "email" not in contact:
            found = _EMAIL.search(line)
            if found:
                contact["email"] = found.group(0)
        if "github" not in contact:
            found = re.search(r"github\.com/[\w.-]+", line)
            if found:
                contact["github"] = found.group(0)

    for section in sections:
        kind = section["kind"]
        if kind == "edu":
            _parse_education(section["lines"], section["items"])
        elif kind == "skills":
            _parse_skills(section["lines"], section["items"])
        elif kind == "projects":
            _parse_projects(section["lines"], section["items"])
        else:
            _parse_generic(section["lines"], section["items"])

    return {
        "name": name,
        "role": role,
        "contact": contact,
        # 无章节的纯文本定稿也要能打印：头部行之外的内容兜底成段落。
        "body": header_lines[1:],
        "sections": [
            {"title": s["title"], "kind": s["kind"], "items": s["items"]}
            for s in sections
        ],
    }


def _role_from_job(job: dict[str, Any]) -> str:
    """求职意向：按岗位标题推导，去掉「职位 ID / 所属类别」之类的噪声。"""
    title = (job.get("title") or "").strip()
    cleaned = _ROLE_NOISE.sub("", title).strip()
    return cleaned or title


_STYLE = """
.rs-print{font-family:"Microsoft YaHei UI","Microsoft YaHei","SimHei",sans-serif;color:#1e293b;line-height:1.5;font-size:9.6pt}
.rs-print *{margin:0;padding:0;box-sizing:border-box}
.rs-print .rs-header{margin-bottom:10px;padding-bottom:7px;border-bottom:2px solid #2563eb}
.rs-print .rs-top{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:3px}
.rs-print .rs-name{font-size:17px;font-weight:700}
.rs-print .rs-role{font-size:11px;color:#2563eb;font-weight:500}
.rs-print .rs-contact{display:flex;flex-wrap:wrap;gap:10px;font-size:9.5px;color:#334155}
.rs-print .rs-section{margin-bottom:6px}
.rs-print .rs-section h2{font-size:11.5px;font-weight:700;color:#0f172a;margin-bottom:4px;padding-bottom:2px;border-bottom:1px solid #cbd5e1}
.rs-print .rs-edu{display:flex;justify-content:space-between;font-size:10.5px;margin-bottom:2px}
.rs-print .rs-school{font-weight:600}
.rs-print .rs-date{color:#64748b}
.rs-print .rs-major{font-size:9.5px;color:#64748b;margin:0 0 3px}
.rs-print .rs-skill{font-size:10px;line-height:1.65;margin-bottom:2px}
.rs-print .rs-cat{color:#0891b2;font-weight:600}
.rs-print .rs-project{margin-bottom:6px;break-inside:avoid}
.rs-print .rs-proj-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:2px}
.rs-print .rs-proj-name{font-size:11px;font-weight:700;color:#0f172a}
.rs-print .rs-proj-git{font-size:8.5px;color:#64748b}
.rs-print .rs-proj-tech{font-size:8.5px;color:#64748b;margin-bottom:3px}
.rs-print .rs-proj-scene{font-size:9.5px;color:#334155;margin-bottom:3px}
.rs-print .rs-project ul{list-style:none;padding:0}
.rs-print .rs-project li{position:relative;padding-left:9px;margin-bottom:1px;font-size:9.2px;color:#334155;line-height:1.4}
.rs-print .rs-project li:before{content:"\\2022";position:absolute;left:0;color:#2563eb;font-size:9px}
.rs-print .rs-tag{color:#0f172a;font-weight:700}
.rs-print .rs-p{font-size:9.5px;color:#334155;line-height:1.5;margin-bottom:2px}
.rs-print .rs-label{color:#0f172a;font-weight:700}
""".strip()


def _render_header(document: dict[str, Any], role: str) -> str:
    contact = document.get("contact") or {}
    parts: list[str] = []
    if contact.get("phone"):
        parts.append("电话：" + _esc(contact["phone"]))
    if contact.get("email"):
        parts.append("邮箱：" + _esc(contact["email"]))
    if contact.get("github"):
        parts.append("GitHub：" + _esc(contact["github"]))
    role_html = '<div class="rs-role">' + _esc(role) + "</div>" if role else ""
    return (
        '<div class="rs-header">'
        '<div class="rs-top">'
        '<div class="rs-name">' + _esc(document.get("name") or "") + "</div>"
        + role_html
        + "</div>"
        '<div class="rs-contact">' + "".join("<span>" + p + "</span>" for p in parts) + "</div>"
        "</div>"
    )


def _render_items(items: list[dict[str, Any]]) -> str:
    html_parts: list[str] = []
    bullets: list[str] = []

    def flush() -> None:
        if bullets:
            html_parts.append("<ul>" + "".join(bullets) + "</ul>")
            bullets.clear()

    for item in items:
        kind = item.get("type")
        if kind == "edu":
            head = _esc(item["school"])
            if item.get("major"):
                head += " · " + _esc(item["major"])
            html_parts.append(
                '<div class="rs-edu"><span class="rs-school">' + head + "</span>"
                '<span class="rs-date">' + _esc(item.get("date") or "") + "</span></div>"
            )
        elif kind == "major":
            html_parts.append('<div class="rs-major">' + _inline(item["text"]) + "</div>")
        elif kind == "skill":
            cat = (
                '<span class="rs-cat">' + _esc(item["cat"]) + "：</span>"
                if item.get("cat") else ""
            )
            html_parts.append('<div class="rs-skill">' + cat + _inline(item["text"]) + "</div>")
        elif kind == "project":
            flush()
            head = _esc(item["name"])
            if item.get("description"):
                head += " — " + _esc(item["description"])
            link = (
                '<div class="rs-proj-git">GitHub：'
                + _esc(item["link"].split("github.com/")[-1])
                + "</div>"
                if item.get("link") else ""
            )
            tech = (
                '<div class="rs-proj-tech">技术栈：' + _esc(item["tech"]) + "</div>"
                if item.get("tech") else ""
            )
            scene = (
                '<div class="rs-proj-scene">' + _inline(item["scene"]) + "</div>"
                if item.get("scene") else ""
            )
            inner = "".join(
                "<li>"
                + (
                    '<span class="rs-tag">【' + _esc(b["tag"]) + "】</span>"
                    if b.get("tag") else ""
                )
                + _inline(b["text"])
                + "</li>"
                for b in item.get("bullets") or []
            )
            bullets_html = "<ul>" + inner + "</ul>" if inner else ""
            html_parts.append(
                '<div class="rs-project">'
                '<div class="rs-proj-head"><div class="rs-proj-name">' + head + "</div>"
                + link
                + "</div>"
                + tech + scene + bullets_html
                + "</div>"
            )
        elif kind == "bullet":
            tag = (
                '<span class="rs-label">' + _esc(item["tag"]) + "：</span>"
                if item.get("tag") else ""
            )
            bullets.append("<li>" + tag + _inline(item["text"]) + "</li>")
        else:
            flush()
            tag = (
                '<span class="rs-label">' + _esc(item["tag"]) + "：</span>"
                if item.get("tag") else ""
            )
            html_parts.append('<p class="rs-p">' + tag + _inline(item["text"]) + "</p>")
    flush()
    return "".join(html_parts)


def render_resume_print_html(job: dict[str, Any], draft: str) -> str:
    """Return the self-contained HTML used by the PDF (print) export."""
    document = parse_draft(draft)
    role = _role_from_job(job) or document.get("role") or ""
    sections_html: list[str] = []
    for section in document["sections"]:
        body = _render_items(section["items"])
        if not body:
            continue
        sections_html.append(
            '<section class="rs-section"><h2>' + _esc(section["title"]) + "</h2>"
            + body
            + "</section>"
        )
    body_html = ""
    if not sections_html:
        body_html = "".join(
            '<p class="rs-p">' + _inline(line) + "</p>"
            for line in document.get("body") or []
        )
    return (
        '<article class="rs-print">'
        "<style>" + _STYLE + "</style>"
        + _render_header(document, role)
        + "".join(sections_html)
        + body_html
        + "</article>"
    )
