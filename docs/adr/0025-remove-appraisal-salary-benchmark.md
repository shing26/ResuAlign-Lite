# ADR-0025: Remove delivery appraisal, delivery weights, and salary benchmark

The product decision removes the delivery-value appraisal, delivery-weight
evaluation, and salary-benchmark modules from both the UI and the backend.
This supersedes the earlier ADR clauses that pinned those surfaces
(ADR-0014 job-library workbench, ADR-0015 single-job workspace, and
ADR-0020 2.0.1 decisions).

Removed surfaces: the `GET /api/jobs/{job_id}/appraisal` route, the
`appraisal_weights` and `salary_reference` settings fields, the workbench
appraisal panel, the `appraisal` property on the incremental
`WorkstationState` schema, and the dedicated appraisal tests. Kept untouched: job
`salary_min` / `salary_max` fields, `formatSalary`, the salary-based
automation rules, and the `.appraisal-score` / `.score-ring` score styles.
The resume center renders diagnosis scores through the v3
`diagnosis-banner__score` surface; the ring utility remains in use by the
legacy workbench result view.

`contracts/openapi-v1.json` remains immutable per ADR-0020 / ADR-0021. The
removals are recorded deliberately in `contracts/incremental/manifest.json`
under `removed_paths`, `removed_schema_properties`, and `breaking_changes`,
and the incremental manifest version is bumped to 2.1.0 to mark the breaking
surface. `tests/test_contract.py` consults that record instead of editing the
v1 golden. A future restore would remove the manifest entries and re-add the
route/fields.
