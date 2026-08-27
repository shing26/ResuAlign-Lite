 # ADR-001: Multi-format input abstraction

 **Status**: Proposed
 **Date**: 2026-07-31

 ## Context

 The tool currently only reads PDFs via PyMuPDF. Users may have resumes in DOCX or plain text. Adding `if-elif` chains for each new format works for two formats but becomes messy as the set grows.

 ## Decision

 Introduce a single `extract_text(path: Path) -> str` function that inspects the file extension and delegates to a format-specific reader.

 - `.pdf` → `fitz.open()` (PyMuPDF)
 - `.docx` → `python-docx`
 - `.txt` / no extension → raw `read_text(encoding="utf-8")`

 Unknown extensions raise a clear error listing supported formats.

 ## Consequences

 - Adding a new format means adding one branch inside `extract_text()` — no changes needed in the pipeline.
 - The caller never imports `fitz` or `docx` directly.
 - A new parser dependency (python-docx) is added to the project.
 - Extension-based dispatch is not perfect (some `.docx` files mislabelled), but good enough for a CLI tool.
