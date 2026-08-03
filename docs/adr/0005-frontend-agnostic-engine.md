 # ADR-0005: Frontend-agnostic core engine

 **Status**: Proposed
 **Date**: 2026-07-31

 ## Context

 The initial single-file design embeds CLI-specific concerns (argparse, stdout print, file I/O) into the same scope as pipeline logic. Adding a Web UI or API later would require either duplicating the pipeline or contorting the CLI to serve double duty. The user confirmed the end goal includes a Web/API frontend, so the module split (ADR-003) needs a clear engine boundary.

 ## Decision

 Introduce a dedicated `engine.py` module with a single public function:

 ```python
 def run(config: ResuAlignConfig, resume_text: str, jd_text: str | None = None) -> Report: ...
 ```

 Rules:
 - `engine.py` never imports `sys`, `argparse`, `pathlib` (beyond type hints), or any I/O module.
 - `engine.py` never prints to stdout/stderr. All logging goes through a callback or is returned in the `Report`.
 - `engine.py` only calls `parser.extract_text()` for its internal needs (none currently; resumes arrive pre-parsed from the frontend).
 - The caller (CLI or API) is responsible for: file reading, config assembly, and output rendering.

 ## Consequences

 - Adding a FastAPI frontend requires only a new `api.py` that calls `engine.run()` and serializes the `Report` to JSON.
 - Integration tests can test `engine.run()` directly without invoking argparse or parsing CLI output.
 - CLI-specific complexity (output paths, terminal formatting) stays in `cli.py` and never leaks into the core.
 - Learning curve for contributors: understand `engine.py` first, then whichever frontend they modify.
 - Mild overhead: CLI must do a `parser.extract_text()` call before `engine.run()`, but that's one line.
