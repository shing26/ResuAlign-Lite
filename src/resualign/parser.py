from pathlib import Path
import re


class FileParseError(Exception):
    """Raised when resume file cannot be parsed."""
    pass


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}


def normalize_text(text: str) -> str:
    """Collapse blank lines and edge whitespace for stable resume text."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return "\n".join(lines)


def extract_text(path: Path) -> str:
    if not path.exists():
        raise FileParseError(f"File not found: {path}")

    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise FileParseError(
            f"Unsupported format '{ext}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    if ext == ".pdf":
        import fitz
        doc = fitz.open(path)
        pages = []
        for page in doc:
            text = page.get_text()
            if text.strip():
                pages.append(normalize_text(text))
        doc.close()
        return "\n\n".join(pages)

    if ext == ".docx":
        from docx import Document
        doc = Document(str(path))
        lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    lines.append(" | ".join(cells))
        return normalize_text("\n".join(lines))

    # .txt
    try:
        return normalize_text(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        try:
            return normalize_text(path.read_text(encoding="gb18030"))
        except UnicodeDecodeError as exc:
            raise FileParseError(
                "Text file encoding is not supported; "
                "please save it as UTF-8 or GB18030"
            ) from exc


_SECTION_HEADING_RE = re.compile(
    r"^(?:#\s*)?(?:个人(?:信息|简介)|教育(?:背景|经历)|工作经历|"
    r"项目(?:经历|经验)|专业技能|技能清单|证书|荣誉|自我评价|"
    r"summary|education|work\s+experience|project|skills|"
    r"certifications?|awards?)$",
    re.IGNORECASE,
)


def structured_resume_sections(text: str) -> dict[str, str]:
    """Group normalized resume text into familiar section buckets."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in (text or "").splitlines():
        heading = line.strip().lstrip("#").strip()
        if _SECTION_HEADING_RE.match(heading):
            current = heading
            sections.setdefault(current, [])
            continue
        if current is not None and line.strip():
            sections[current].append(line.strip())
    return {
        key: "\n".join(values)
        for key, values in sections.items()
        if values
    }
