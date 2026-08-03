# ResuAlign Phase 1 — Minimal Viable Pipeline Refactor

## Problem Statement

ResuAlign currently exists as a single 75-line Python script (`resualign.py`). It reads a PDF resume, calls a DeepSeek/OpenAI-compatible LLM for diagnosis (score, skills, issues) and optional JD alignment (diffs), and prints results to the terminal.

The single-file design bundles argument parsing, PDF parsing, LLM I/O, JSON parsing, output formatting, and domain logic into one scope. This makes isolated testing impossible, prevents adding a Web/API frontend later, and requires users to set environment variables manually in every terminal session.

Phase 1 refactors the code into a proper package with clean module boundaries, adds `.env` support, extends input formats to DOCX/txt, outputs JSON reports, and wires up a test suite — all while preserving the existing CLI user experience.

## Solution

Restructure `resualign.py` into a `src/resualign/` package with five modules + a thin root entry point. The core pipeline (`engine.py`) is frontend-agnostic: it accepts a config object + input text, returns a `Report`, and never touches stdout/argparse. The CLI (`cli.py`) is one of several possible frontends.

## User Stories

1. As a user, I want to run `resualign resume.pdf` and see a diagnosis (score, skills, issues) printed to the terminal, so that I can quickly evaluate my resume.
2. As a user, I want to run `resualign resume.pdf --jd "Java backend..."` and also see alignment diff suggestions, so that I can tailor my resume to a specific job.
3. As a user, I want to configure my API key and model in a `.env` file instead of setting environment variables every session, so that repeated use is frictionless.
4. As a user, I want to pass `--api-key`, `--model`, and `--provider` as CLI flags to override config per run, so that I can switch between providers/models without editing files.
5. As a user, I want to run `resualign resume.docx` or `resualign resume.txt` and get the same diagnosis, so that I'm not limited to PDF format.
6. As a user, I want to run `resualign resume.pdf --jd-file description.txt` to read the JD from a file, so that I can use long job descriptions conveniently.
7. As a user, I want a JSON report file (`resualign-report-{timestamp}.json`) saved automatically alongside terminal output, so that I can archive or process results programmatically.
8. As a user, I want to specify the output directory with `--output-dir`, so that I can organize reports into a specific folder.
9. As a developer, I want to call `from resualign.engine import run; run(config, resume_text, jd_text)` from Python code, so that I can integrate ResuAlign into other tools or build a Web frontend.

## Implementation Decisions

### Core principles

**Pipeline-first, prompt-later.** Phase 1 strictly uses hardcoded minimal prompts. Any prompt tuning beyond the literal minimum is deferred to a dedicated phase after all tickets pass. Target: validate data plumbing and schema parsing, not prompt quality.

**Fail fast on LLM output.** No heuristic JSON-repair logic. If the model does not return parseable output after 2 retries, raise a custom `LLMResponseError` and surface it clearly. The parser layer is not a recovery layer.

### Modules to create

- **`src/resualign/__init__.py`** — exports `run()`, `ResuAlignConfig`, `Report` for programmatic use
- **`src/resualign/models.py`** — dataclasses: `DiffItem`, `Analysis`, `Report`, `ResuAlignConfig`
- **`src/resualign/llm.py`** — `LLMClient` abstract class + `OpenAIClient` implementation. `llm_json()`: HTTP call + 2 retries + `raw_decode` parsing. Raises `LLMResponseError` on failure. Prompts are hardcoded strings, one constant per use case, no tuning.
- **`src/resualign/parser.py`** — `extract_text(path)`: extension-based dispatch. Raises `FileParseError` on unsupported format or read failure.
- **`src/resualign/engine.py`** — `run(config, resume_text, jd_text?) → Report`: chains parse → diagnose → align. No I/O, no argparse, no print().
- **`src/resualign/cli.py`** — argparse → config layering (CLI > .env > env) → engine.run() → terminal output + JSON file dump. Entry point for CLI only.

### Root entry

- `resualign.py` → thin shebang script: `from resualign.cli import main; main()`
- `pyproject.toml` → `[project.scripts]` entry: `resualign = resualign.cli:main`

### Configuration layering

Priority (high → low): CLI flags (`--api-key`, `--model`, `--provider`) > `.env` file > environment variables.

### Dependencies added

- `pydantic-settings` — config layering with `.env` support (handles CLI > .env > env automatically)
- `python-docx` — DOCX file parsing
- `pytest` + `pytest-httpx` — testing (dev dependencies)

### Import graph

`cli → engine → {parser, llm, models}`

## Testing Decisions

### Distributed testing (no single "test ticket")
Each module comes with its tests in the same ticket:

- **Ticket 01 (models + parser)** — `test_models.py` (construction, optional fields) + `test_parser.py` (fixture files, `FileParseError` on bad input)
- **Ticket 02 (LLM + engine)** — `test_llm.py` (mock transport, `LLMResponseError` on failure) + `test_engine.py` (mock `LLMClient`, verify Report shape)
- **Ticket 03 (CLI)** — `test_cli.py` (argparse flags, config precedence via `pydantic-settings`)

### Remaining: E2E + coverage acceptance ticket
A final ticket validates the integrated CLI with a fully mocked LLM and measures coverage threshold.

### What is NOT tested

- Real LLM API calls (costly, non-deterministic, key-dependent)
- Corrupted PDF/DOCX recovery beyond `FileParseError`

### Engine testability

`engine.run()` accepts an `LLMClient` interface — pass a mock that returns canned JSON. This makes unit tests deterministic and fast (<10ms per test).

Seam hierarchy:
1. `engine.run()` with mock `LLMClient` — primary seam (covers full pipeline)
2. `parser.extract_text()` with fixture files — secondary seam
3. `CLI argument parsing` in isolation — tertiary seam

New exception types for clean error handling:
- `LLMResponseError` — LLM non-coverage / parse failure
- `FileParseError` — unsupported format or read failure

## Out of Scope for Phase 1

- Prompt tuning or quality evaluation
- `DiffItem.provenance` population (field exists, stays empty until Phase 5)
- Heuristic JSON recovery beyond 2 retries
- Real LLM integration tests (key-dependent)

## Future Phases (not this spec)

- JD crawling from career sites (Phase 7)
- JD profiling / structured extraction (Phase 4)
- Gap analysis beyond simple diff generation (Phase 5)
- LLM-as-Judge evaluation (Phase 6)
- Two-stage token optimization (Phase 8)
- Web UI or API endpoint
