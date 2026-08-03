# ADR-0014: Job library as the personal workbench core

**Status**: Accepted
**Date**: 2026-08-02

## Context

The user's goal is a personal job-seeking workbench with four functional
modules: resume analysis/scoring, JD-based optimization and new-resume
generation, job crawling and classification, and job-worth appraisal by
location and salary. The earlier roadmap drifted toward SaaS multi-tenancy as
the immediate priority. A grilling session (2026-08-02) re-converged the
product: SaaS remains the long-term end state, but the personal-use stage
skips login, and the Job Library is the core entity that feeds the other
modules.

## Decision

- Personal-first product: the web UI opens directly into the workbench
  (personal mode already default in ADR-0013); auth/tenancy stays implemented
  but dormant, with `RESUALIGN_PERSONAL_MODE=0` as the SaaS switch.
- The Job Library is the core data entity. Crawled, pasted, or imported jobs
  are stored once with their raw JD text, source, location, salary range,
  classification tags, and application status.
- Job classification uses a multi-dimensional tag model: job function, seniority,
  and free-form technology/domain tags, extracted by the LLM and editable by
  the user.
- Salary benchmarking uses an editable reference table (city x function x
  seniority), the median salary of same-function jobs already in the library
  as a supplementary signal, and per-job manual overrides.
- Worth appraisal is a transparent 0-100 score: resume match 40%, salary
  competitiveness 30%, hard conditions 20%, job quality signals 10%, with a
  three-level conclusion (apply / consider / skip). Weights are editable.
- MVP job ingestion has three entry points: single JD URL crawl (existing
  LinkedIn / BOSS直聘 / generic handlers), pasted JD text, and JSON/CSV batch
  import. Search/list-page crawling is deferred to the agent-based JD
  acquisition phase (ADR-0010 seam).
- The workbench UI becomes a four-page navigation: Resume Center, Job Library,
  Single-Job Workspace, and Settings. Development order is Job Library +
  classification first, then Single-Job Workspace (optimization + appraisal),
  then Settings.

## Considered Options

- Keep the SaaS application workspace as the next phase: it matched the
  earlier roadmap but not the user's stated modules, so it is deferred.
- Treat modules as independent screens with no shared job store: simpler but
  makes appraisal, classification, and per-job resume generation disconnected.
- Store jobs only transiently: insufficient for a job library and appraising
  over time.

## Consequences

- New Job Library tables live in the existing SQLite storage alongside users
  and applications, tenant-scoped by the same user id.
- Module 3 (ingestion + classification) is the first implementation phase;
  modules 2 and 4 build on its records.
- Existing resume analysis/tailoring capabilities are reused by the Single-Job
  Workspace without rework.
