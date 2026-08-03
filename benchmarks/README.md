# Benchmark Regression Harness

Runs the full ResuAlign pipeline against fixed sample cases and checks whether
the tailored output covers each case's `expected_direction` goals using a
keyword-overlap heuristic.

## Cases

Each JSON file in `cases/` has:

- `id`: unique case name
- `resume_text`: resume text (synthetic unless the source note says otherwise)
- `jd_text`: job description text
- `expected_direction`: list of concrete tailoring goals
- `source_note`: provenance note
- `tags` (optional): list of non-empty strings classifying the case, such as
  `["frontend", "english"]`, `["backend", "english"]`, or
  `["chinese", "backend"]`

The suite currently has nine synthetic, PII-free cases covering backend,
frontend, data, DevOps/SRE, machine learning, mobile, and Chinese-language
roles. All resumes and job descriptions are fictional.

## Offline run

Offline mode is the default. It uses a deterministic `FakeLLMClient` with fixed
JSON responses, so it needs no network access or API key:

```powershell
$env:PYTHONPATH='D:\ResuAlign-Lite\src'
python benchmarks\run_benchmark.py --offline
```

`python benchmarks\run_benchmark.py` is equivalent because `--offline` is the
default.

## Online run

Online mode reads `D:\ResuAlign-Lite\.env` for `DEEPSEEK_API_KEY` and
`DEEPSEEK_MODEL`, then calls the real DeepSeek API through `OpenAIClient`:

```powershell
$env:PYTHONPATH='D:\ResuAlign-Lite\src'
python benchmarks\run_benchmark.py --online
```

Online mode makes real LLM calls and can take several minutes.

## Results

Each run writes `benchmarks/results/benchmark-{timestamp}.json` containing the
per-case report, expected direction, and keyword-overlap metrics, and prints a
readable summary to stdout.

Use `--cases-dir` and `--results-dir` to override the default directories.
