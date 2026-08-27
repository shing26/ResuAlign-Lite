# ResuAlign Phase 12 - Job Library and Classification

## Problem Statement

The workbench currently handles resume diagnosis and per-JD tailoring well, but
the user's core workflow also needs to collect jobs, classify them, and later
decide whether each is worth applying to. Without a Job Library, crawled jobs
are ephemeral, classification is absent, and the Single-Job Workspace has no
data to build on.

## Solution

Add a tenant-scoped Job Library as the core workbench entity. Jobs are ingested
from a single JD URL, pasted JD text, or batch JSON/CSV import; each record is
stored once with raw text, source, location, salary range, multi-dimensional
classification tags, and application status. A new Job Library page in the web
UI lists, filters, and edits jobs. This is the foundation for the Single-Job
Workspace (optimization + appraisal) in the next phase.

## User Stories

1. As a job seeker, I want to paste a JD into the workbench, so that the job is
   stored in my library and classified automatically.
2. As a job seeker, I want to submit a JD URL, so that the existing crawler
   fetches the text and saves it without copy-paste.
3. As a job seeker, I want to import multiple jobs from JSON/CSV, so that I can
   build my library from a spreadsheet in one step.
4. As a job seeker, I want each job classified by function, seniority, and
   technology/domain tags, so that I can filter and compare roles.
5. As a job seeker, I want to correct classification tags and salary manually,
   so that the library reflects reality even when the LLM gets it wrong.
6. As a job seeker, I want to mark each job's application status (not applied,
   applied, interviewing, offered, declined), so that my library doubles as a
   lightweight application tracker.
7. As a job seeker, I want duplicate jobs (same URL or same JD text) rejected
   with a clear message, so that the library stays clean.
8. As a developer, I want the salary extraction and classification to be
   testable offline, so that the ingestion path is verifiable without a real
   LLM call.

## Implementation Decisions

- A `JobLibraryStore` in `src/resualign/` backs the Job Library with SQLite,
  sharing the same database file and tenant scoping as jobs and workspace
  records (ADR-0013, ADR-0014).
- The jobs table stores: title, company, location, salary_min, salary_max,
  salary_currency, source_type (url/paste/import), source_url, raw JD text,
  job_function, seniority, tech tags (JSON), application status, posting date,
  timestamps, and a tenant-scoped dedupe key.
- Deduplication: source URL (normalized) when present, otherwise a stable hash
  of the JD text; a duplicate insert raises a clear domain error.
- Classification is an LLM stage with a controlled vocabulary for function and
  seniority and free-form technology/domain tags. Salary range extraction is
  regex-based first (common formats such as "15-25K", "20k-30k", "30-50万/年"),
  then LLM refinement only when needed; both are editable.
- The API adds `/api/jobs` CRUD plus a batch import endpoint. The personal
  mode default applies unchanged; requests map to the stable local tenant.
- The web UI gains a Job Library page with an add form (URL or paste), batch
  import control, filter chips for function/seniority/status, and inline
  editing of tags, salary, and status. Navigation becomes the four-page
  structure: Resume Center, Job Library, Single-Job Workspace, Settings.
- Single-Job Workspace and Settings pages are stubs in this phase.

## Testing Decisions

- `JobLibraryStore` is tested against a temp SQLite file: CRUD, tenant
  scoping, dedupe by URL and text hash, salary median helper, and status
  transitions.
- Salary extraction tests cover range formats, 面议/negotiable, annual salary
  in 万, and missing salary.
- Classification is tested with a fake LLM client (same pattern as
  `tests/conftest.py`) asserting function/seniority/tag parsing and enum
  normalization.
- API tests use `TestClient` with the existing temp-store fixture pattern,
  covering paste/URL/import creation, duplicate rejection, list filters,
  update, and tenant isolation.
- No test in the default suite hits the network.

## Out of Scope

- Salary reference table and appraisal scoring (next phase, Single-Job
  Workspace).
- Search/list-page batch crawling and agent-based JD acquisition.
- Per-job resume generation from the workspace.
- SaaS auth enforcement in the UI (personal mode remains default).

## Further Notes

This repository is not under git; reviews compare against this spec and the
pre-change file state. `.env` credentials must never be printed or committed.
