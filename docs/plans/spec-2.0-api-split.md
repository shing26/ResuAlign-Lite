# Spec: Split `api.py` into a package (T2)

## Goal

Turn the ~1500-line `src/resualign/api.py` into a package without changing any
route, status code, or response shape. `from resualign.api import app` and
`resualign.api:app` must keep working for Uvicorn, tests, and Playwright
smokes. The public OpenAPI must match the committed golden snapshot
(`contracts/openapi-v1.json`) after the split, including component schemas.

## Target layout

```text
src/resualign/api/
  __init__.py       # app factory, lifespan, static mount, middleware
  deps.py           # get_current_user, rate limiting, shared dependencies
  schemas.py        # all Pydantic request/response models
  services/
    __init__.py
    jobs.py         # queue, crawl, import, classification helpers
    workbench.py    # run_workbench, accept diffs, appraisal helpers
    resumes.py      # diagnosis queue, parse-upload helpers
  routers/
    __init__.py     # builds the FastAPI instance or returns an APIRouter
    health.py
    analyze.py
    jobs.py
    resumes.py
    applications.py
    settings.py
```

## Non-negotiable constraints

1. Keep module-level singletons (`_registry`, `_users`, `_resumes`,
   `_applications`, `_jobs`, `_settings_store`, `_payloads`, rate limiters,
   semaphore, `_import_batches`) in the package root module (or a single
   `state.py`), because tests monkeypatch `resualign.api._registry`,
   `resualign.api._users`, `resualign.api._jobs` etc. and those references
   must remain valid.
2. Route registration must happen exactly once, and route decorators stay on
   functions whose module path does not matter to callers.
3. No response drift: use the golden OpenAPI plus `tests/test_contract.py` as
   the guard. If a route was previously undocumented or body serialization
   differs, fix the split rather than updating the golden.
4. Do not fold T4 board changes into this ticket. Work on top of whatever T4
   already shipped and keep every new endpoint working.
5. `python -m pytest tests/ -q` must stay green (baseline plus all new tests).

## Suggested order

1. Extract Pydantic models to `api/schemas.py`; import them back into
   `api.py` so the diff is mechanical and tests stay green at each step.
2. Move helpers (`_report_to_dict`, `_build_diagnosis_section`,
   `_gap_match_score`, `_cached_diagnosis`, `_classify_job`, `_derive_title`,
   `_crawl_jd_or_502`, `_create_job_from_source`, `_queue_job`) into
   `services/`, passing state explicitly or importing from the package root.
3. Move route handlers into `routers/` grouped by prefix, importing state and
   services from the package.
4. Rewrite `api/__init__.py` to construct the app, mount static files, add the
   cache middleware, register routers, and re-export `app` plus the state
   names tests patch.
5. Delete the old `api.py` last, only after `pytest tests/test_contract.py`
   and the full suite pass with the package.

## Verification

- `python -m pytest tests/test_contract.py -q` (golden OpenAPI + routes)
- `python -m pytest tests/ -q` (full regression)
- `python -c "import sys; sys.path.insert(0,'src'); import resualign.api; print(resualign.api.app.title)"`
