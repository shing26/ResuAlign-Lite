from pathlib import Path


class FileParseError(Exception):
    """Raised when resume file cannot be parsed."""
    pass


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}


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
        lines = [
            l.strip()
            for page in doc
            for l in page.get_text().splitlines()
            if l.strip()
        ]
        doc.close()
        return "\n".join(lines)

    if ext == ".docx":
        from docx import Document
        doc = Document(str(path))
        lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        return "\n".join(lines)

    # .txt
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise FileParseError(
            "Text file is not valid UTF-8; please save it as UTF-8"
        ) from exc
