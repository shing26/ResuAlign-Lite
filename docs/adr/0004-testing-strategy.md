 # ADR-004: Testing strategy

 **Status**: Proposed
 **Date**: 2026-07-31

 ## Context

 The tool has zero tests. LLM calls are expensive, non-deterministic, and require a valid API key. PDF parsing needs real fixture files. Without tests, refactoring (ADR-003) risks silent regressions.

 ## Decision

 Three test layers:

 1. **Unit tests (fast, no LLM, no fixtures)** — `test_models.py` constructs objects; `test_llm.py` mocks httpx at the transport level with `pytest-httpx` to verify retry logic and JSON parsing (raw_decode handling of trailing text).
 2. **Parser tests (fixture files)** — `test_parser.py` uses real small PDF/DOCX/txt files committed to the repo under `tests/fixtures/`. Tests verify text content, not exact formatting.
 3. **Integration tests (mocked LLM)** — `test_cli.py` wires all modules together with a mock httpx transport, verifies terminal output and JSON file creation.

 Test configuration:
 - `pytest` as the runner
 - `pytest-httpx` for LLM mock at the transport layer
 - Fixture files: single-page PDF with known text, minimal DOCX, plain-text input

 ## Consequences

 - CI runs without an API key.
 - Parser tests catch regressions in text extraction across library updates.
 - Integration tests catch wiring bugs between modules.
 - Fixture files add ~50 KB to the repo.
 - `pytest-httpx` adds a dev dependency but makes LLM tests deterministic.
