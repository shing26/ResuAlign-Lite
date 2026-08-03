# ADR-0011: Synthetic benchmark dataset expansion

**Status**: Accepted
**Date**: 2026-08-01

## Context

The benchmark suite has only three English backend/data cases, so regression
signals are narrow: prompt changes that hurt frontend, ML, mobile, or
Chinese-language tailoring could pass unnoticed. Real job postings would
improve realism but bring licensing and PII concerns into fixtures.

## Decision

Expand the dataset with synthetic, PII-free cases and treat them as the
benchmark standard:

- New cases must be authored, not scraped, and each `source_note` records that
  provenance.
- Coverage grows from three to nine cases across backend, frontend, data,
  DevOps/SRE, ML, mobile, and Chinese-language roles.
- Optional `tags` metadata (role, domain, language) is allowed on cases; the
  harness ignores unknown fields for now, so subset filtering can be added
  later without a breaking change.
- Harness behavior stays unchanged in this phase except validation and
  documentation updates.

## Considered Options

- Scraping public job pages for fixtures: realism, but PII/licensing risk and
  volatile fixtures.
- Adding 10+ cases immediately: quality and maintenance costs dilute the value
  of each case.

## Consequences

- Regression runs cover a materially wider surface without network access.
- The fixture style and provenance rule are now explicit for future
  contributors.
- Subset filtering remains possible later by reading `tags` when the harness
  grows.
