# ADR-0010: Crawler hardening with site-specific handlers

**Status**: Accepted
**Date**: 2026-08-01

## Context

The crawler applies one generic extraction path to every job URL. Real job
boards have noisy page structures, anti-scraping pages, and site-specific
containers. Users hit `--jd-url` failures with little information about whether
the problem was the network, the HTTP status, an empty page, or a site quirk.

## Decision

Harden the crawler and add a small site-handler registry:

- Site handlers cover LinkedIn job pages and BOSS直聘 job detail pages; all
  other hosts fall back to generic extraction and never produce an
  "unsupported site" error.
- Failures are categorized (`fetch`, `http`, `selector`, `empty`) and carry the
  URL so CLI/API error surfaces can be precise.
- Fetching is bounded: a response size cap, charset-aware decoding, boilerplate
  removal, and an empty-content guard.
- No fetcher abstraction is added yet. Agent-based data acquisition is a known
  future direction; when it lands, CLI/API will depend on a thin
  `JDSourceFetcher` protocol instead of the concrete crawler.

## Considered Options

- Playwright/Selenium for dynamic pages: too heavy for this phase and not needed
  for the two chosen sites.
- Many site handlers at once: maintenance and brittleness grow with each
  handler; two representative sites establish the pattern.
- Protocol abstraction now: only one concrete fetcher exists, so it would be
  speculative generality.

## Consequences

- Tests use local HTML fixtures, so the suite stays network-free.
- New job boards are added by registering a handler, not by forking the fetch
  logic.
- When an agent fetcher arrives, the integration seam is already documented.
