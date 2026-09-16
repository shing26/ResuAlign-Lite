# ResuAlign Phase 9 - Web/API polish, crawler hardening, benchmark expansion

## Problem Statement

The pipeline works end to end, but the web surface is not production-grade:
long runs block the browser on a spinner with no stage feedback, the web UI
does not expose the JD URL input or the extended report sections, and
`--jd-url` extraction is a single generic path that fails opaquely on real job
boards. Benchmark coverage is also narrow: three English backend/data cases
cannot catch regressions in frontend, ML, mobile, or Chinese-language
tailoring.

## Solution

Turn long analyses into observable asynchronous jobs, harden JD URL ingestion
for the two most common job boards, and widen the benchmark dataset to nine
synthetic cases. The engine stays frontend-agnostic; progress is delivered
through an optional callback and an in-memory job API with polling, and the
static web UI renders live stage progress plus the full Report.

## User Stories

1. As a user running a long analysis in the web UI, I want to see the current
   stage and elapsed time, so that I know the run is progressing.
2. As a user, I want to submit a job posting URL from the web UI, so that I do
   not have to copy-paste long JD text.
3. As a user, I want the results page to show the JD profile, gap report,
   tailored resume, and evaluation score when present, so that the web UI
   exposes the full Report.
4. As a CLI user, I want stage progress printed during long runs, so that I can
   tell what the pipeline is doing.
5. As a user pasting a job URL into the CLI or API, I want clear, categorized
   errors for network failures, HTTP errors, empty pages, and site-specific
   extraction issues, so that I know how to fix the input.
6. As a user, I want LinkedIn and BOSS直聘 job URLs to extract the relevant JD
   text, so that common job boards work without copy-paste.
7. As a developer, I want a wider benchmark dataset covering more roles and
   languages, so that regressions surface before release.
8. As a developer, I want optional tags on benchmark cases, so that future
   subset runs can be added without schema churn.
9. As a maintainer, I want a documented real-LLM verification pass over the
   web/API surface, so that mocked tests do not drift from reality.

## Implementation Decisions

- The engine gains an optional stage callback, defaulting to no-op behavior, so
  existing programmatic callers are unchanged. Fixed stage names cover
  diagnose, JD profile, gap analysis, tailoring, and evaluation.
- The API becomes asynchronous: creating an analysis returns `202` with a
  `job_id`, and a polling endpoint returns status, stage, message, elapsed
  time, the completed Report, or the failure reason. Jobs run on daemon threads
  in a process-local, size-capped, TTL-expiring registry; no persistence.
- The CLI wires the same stage callback to stderr output unless `--quiet` is
  set, and error surfaces include the categorized crawler failure.
- The web UI stays a single static page: it adds a JD URL field, polls the job
  endpoint, renders live stage progress, and shows every report section that
  the API returns.
- The crawler gains a site-handler registry for LinkedIn job pages and BOSS直聘
  job detail pages, with generic extraction as the fallback for every other
  host. Failures are categorized and carry the URL; fetching is bounded by a
  response size cap, charset-aware decoding, boilerplate removal, and an
  empty-content guard. No fetcher abstraction is introduced yet.
- The benchmark dataset grows to nine synthetic, PII-free cases with optional
  `tags` metadata; harness validation and README documentation are updated
  without changing the offline/online CLI.

## Testing Decisions

- Engine progress is tested at the public seam: `engine.run()` with a mocked
  LLM client and a recording callback, asserting stage names, order, and
  unchanged behavior when the callback is omitted.
- API jobs are tested through `TestClient` with patched config and engine, plus
  an injectable job runner for deterministic status transitions; polling
  helpers assert `queued -> running -> succeeded | failed`, 404 for unknown
  jobs, and bounded registry behavior.
- Crawler behavior is tested with local HTML fixture pages for LinkedIn,
  BOSS直聘, and generic pages, plus categorized error, size-limit, encoding,
  and empty-content cases. No test in the default suite hits the network.
- Benchmark tests validate the expanded case set, optional tags, unique ids,
  and the offline run without network access.
- Real-LLM verification is an explicit, separate ticket with a recorded
  evidence file; credentials are never printed or committed.

## Out of Scope

- Authentication, multi-user accounts, and persistent job storage.
- SSE streaming, WebSocket push, or any frontend build tooling.
- An agent-based JD fetcher (documented as future direction only).
- Prompt tuning beyond what verification evidence requires.
- Site handlers beyond LinkedIn and BOSS直聘, and benchmark subset filtering.

## Further Notes

This repository is not under git, so reviews compare against the written spec
and the pre-change file state rather than a git diff. The `.env` file contains
real credentials and must never be printed or committed. Real-LLM verification
is expected to take minutes per run.
