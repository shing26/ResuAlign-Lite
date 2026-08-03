# ResuAlign — Implementation Roadmap

> 终局：简历-岗位全链路优化平台。
> CLI 只是前端之一，未来会扩展 Web UI / API 层。
> 核心引擎前端无关，多阶段 pipeline 可组合。
> 铁律：AI 不得凭空捏造事实（provenance tracking）。

## Implementation Status (2026-08-01)

- Phase 1-3: package scaffold, models, parser, LLM client, engine, CLI,
  JSON output, and mocked test suite are implemented.
- Phase 4-6: JD profiling, gap analysis, tailoring with provenance, and
  LLM-as-Judge evaluation are implemented.
- Phase 7: crawler with `--jd-url`, FastAPI app, and web UI are implemented.
- Phase 8: two-stage extractor (regex pre-pass) is implemented.
- Quality gates: 85+ unit/integration tests, 94% coverage, offline benchmark
  harness, and CI workflow are in place.
- Prompt tuning loop is complete: online benchmark reaches 9/9 expected
  directions, and the real CLI pipeline runs end to end.

Based on design review (2026-07-31). Implementation in phases.

## Long-term Package Structure

```
resualign/
├── .env.example
├── CONTEXT.md
├── README.md
├── pyproject.toml
├── requirements.txt
├── src/
│   └── resualign/
│       ├── __init__.py
│       ├── cli.py            # CLI frontend
│       ├── api.py            # Web/API frontend (future)
│       ├── engine.py         # pipeline orchestration, no I/O
│       ├── llm.py            # LLM call + JSON parsing
│       ├── models.py         # dataclasses
│       ├── parser.py         # file-format abstraction
│       ├── extractor.py      # two-stage text extraction (future)
│       ├── crawler.py        # JD crawling (future)
│       ├── jd_profiler.py    # JD → JDProfile (future)
│       ├── gap_analyzer.py   # resume + JD → gap report (future)
│       ├── tailor.py         # constraint-guided rewriting (future)
│       └── evaluator.py      # LLM-as-Judge (future)
├── docs/
│   ├── plan.md               # this file
│   └── adr/
│       ├── 0001-*.md
│       └── ...
└── tests/
    ├── __init__.py
    ├── conftest.py           # shared fixtures
    ├── test_cli.py
    ├── test_engine.py
    ├── test_llm.py
    ├── test_models.py
    └── test_parser.py
```

## Phase 1 — Minimal Viable Pipeline  (current)

Goal: working CLI tool with the current feature set, refactored into modules.

1. Scaffold `src/resualign/` package
2. `models.py` — DiffItem, Analysis, Report, ResuAlignConfig dataclasses
3. `llm.py` — llm_json() with raw_decode + retry
4. `parser.py` — extract_text() for PDF/DOCX/txt
5. `engine.py` — run(config, resume_text, jd_text?) → Report
6. `cli.py` — argparse → config → engine.run() → terminal + JSON output
7. Root `resualign.py` → thin entry calling cli.main()
8. `.env.example`, `pyproject.toml`, updated `requirements.txt`

## Phase 2 — Output + JD file

1. Report → JSON file (`resualign-report-{timestamp}.json`)
2. `--jd-file` flag, mutually exclusive with `--jd`
3. `--output-dir` flag (default: current directory)
4. Diffs printed with confidence tags

## Phase 3 — Testing

1. `pytest` + `pytest-httpx` dev dependencies
2. `conftest.py` — mock LLM transport, sample texts, dynamic PDF fixture
3. Unit tests: models, llm, parser
4. Engine integration test with mocked LLM
5. CLI-specific tests (argparse, config layering)

## Phase 4 — JD Profiling (next major feature)

1. `jd_profiler.py` — JD → JDProfile via structured LLM extraction
2. Extend `models.py` with JDProfile dataclass
3. Extend engine pipeline: inject JDProfile stage before gap analysis
4. Prompt for must-have vs nice-to-have classification

## Phase 5 — Gap Analysis + Tailoring

1. `gap_analyzer.py` — Master Resume + JDProfile → GapReport
2. `tailor.py` — constraint-guided rewriting with provenance tracking
3. Iron rule enforcement: every output sentence links to source
4. Extend Report with GapReport and TailoredResume

## Phase 6 — Evaluation

1. `evaluator.py` — LLM-as-Judge for quality measurement
2. EvalScore: JD match rate, hallucination flag, gap coverage
3. Optional `--eval` flag to run evaluation after tailoring

## Phase 7 — JD Crawling + Web Frontend

1. `crawler.py` — Playwright-based job site crawling
2. `extractor.py` — two-stage extraction (regex → LLM)
3. `api.py` — FastAPI endpoint wrapping engine.run()
4. Basic Web UI

## Phase 8 — Token Optimization

1. Two-stage extraction on all long-text paths
2. Caching layer for repeated JD Profile lookups
3. Optional: streaming LLM responses for progress feedback
