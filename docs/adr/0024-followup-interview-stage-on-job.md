# ADR-0024: Follow-up and interview stage live on the Job, not a separate entity

Follow-up tracking (due datetime + interview stage) is modeled as fields on
the Job (`next_step_due_at`, `interview_stage`) instead of a separate
follow-up events table. Application Status keeps the 5-state funnel; Interview
Stage is an orthogonal follow-up anchor inside "interviewing".

A separate entity would enable per-interview history, but the personal
workbench never replays interview timelines and would pay for a new table,
migration, and API surface. If multi-round history ever becomes a real need,
the fields migrate into a `followup_events` table keyed by job_id with the
current due/stage promoted to the latest row — a mechanical migration.

This keeps existing status semantics untouched (no 5-state migration) and
gives the due-reminder logic one structured source instead of regex-parsing
free text.
