# ADR-003: Module decomposition

**Status**: Proposed
**Date**: 2026-07-31

## Context

The tool is a single 110-line file. It works, but the concerns are mixed: argument parsing, PDF parsing, LLM I/O, JSON parsing, output formatting, and domain logic all live in the same scope. This makes isolated testing impossible without running the full pipeline, makes it hard to reuse parts (e.g., just parse a PDF without calling the LLM), and makes it impossible to add a Web/API frontend without duplicating the pipeline logic.

## Decision

Split into five modules under `src/resualign/`:

- **`models.py`** — `DiffItem`, `Analysis`, `Report`, `ResuAlignConfig` dataclasses. No logic.
- **`parser.py`** — `extract_text()`. Only file-format concern.
- **`llm.py`** — `llm_json()`. Only API concern.
- **`engine.py`** — `run(config, resume_text, jd_text?) -> Report`. Pure orchestration, no I/O, no argparse, no print().
- **`cli.py`** — argparse → config → engine.run() → terminal + file output. One of several frontends.

`resualign.py` (root) is a thin entry script that imports and calls `resualign.cli.main()`. Future frontends (e.g., `api.py`) import `resualign.engine` and `resualign.models` directly, bypassing `cli.py` entirely.

## Consequences

- Each module can be tested independently.
- Import graph: `cli → engine → {parser, llm, models}`. Future `api → engine → {parser, llm, models}`.
- `engine.py` is the single seam for adding new frontends — it accepts config, returns Report, and never touches stdout.
- Adding a feature touches at most two modules (engine + one leaf).
- Slightly more files to navigate, but each file stays under ~80 lines.
