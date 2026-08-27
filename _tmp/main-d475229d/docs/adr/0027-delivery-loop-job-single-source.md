# ADR-0027: Delivery loop owns job state; Applications panel becomes dormant

Status: accepted (2026-08-13)

## Context

The delivery loop (岗位库 → 工作台对齐 → 记录投递 → 安排跟进 → 终态收口) currently
reads job status and timestamps from the Job, while the workbench still exposes a
legacy Applications panel that writes to a separate per-tenant entity. The two
models disagree: 记录投递 can downgrade a later-stage job, timeline fields can
contradict the status, funnel metrics lose withdrawn-job history, and follow-up
reminders ignore terminal states.

## Decision

- Job is the single source of truth for the delivery loop. The frontend
  Applications panel is removed; backend application routes and storage stay
  dormant until a separate cleanup ticket removes them.
- Status changes follow a half-constrained lifecycle: forward transitions
  auto-fill the matching timestamp and clear later-stage fields; backward
  corrections require explicit confirmation and clean stale fields; terminal
  states keep applied/offer history while clearing follow-up fields.
- Funnel metrics use the historical peak (`offer_at` > `applied_at` > status),
  so withdrawn jobs keep their past-stage credit. Follow-up reminders fire only
  for active stages and stop automatically at terminal states.
- 记录投递 is idempotent and available from the workbench context, final-draft
  panel, and job detail; it never downgrades a later stage. A 安排跟进 quick
  modal and a 直达投递 (去投递 / 补链接) action close the loop without leaving
  the workflow.
- First-run guidance swaps the align CTA for 先创建主简历 when no master resume
  exists.

## Considered Options

- Application as the source of truth: would require rebuilding the kanban,
  funnel, and reminders around a second entity, and was rejected because the
  personal workflow already tracks the loop on the Job.
- Dual-write Job + Application: keeps both surfaces but invites the same
  divergence that caused the current inconsistencies, so it was rejected.

## Consequences

- The workbench and kanban share one coherent state model, which makes the
  funnel, reminders, and job detail consistent without a backend migration.
- Old application data remains readable via dormant APIs until the cleanup
  ticket lands, so no data loss is forced by this change.
- Follow-up cleanup: a dedicated issue should remove the dormant
  `/api/applications` routes, `ApplicationStore`, the `applications` table,
  and any remaining migration helper after confirming no local or SaaS tool
  still depends on them. Until then, new UI must not render or write
  Application records.
- Tests must move from asserting the old free-form timeline behavior to the
  lifecycle policy, and contract snapshots stay compatible because no backend
  schema changes are required.
