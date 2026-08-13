# ADR-0026: ResuAlign v3 structural redesign shell

Status: accepted (2026-08-13)

## Context

The v2.1 Apple Native shell still read as stacked cards with equal visual
weight, and the user asked for a structural redesign rather than another
incremental restyle. The frozen `designs/v3-redesign-preview.html` becomes
the visual baseline for the five views and the application shell.

## Decision

- Replace the fixed 240px rail / 64px header / card-heavy shell with the v3
  structural layer: `view-scroll` / `view-fit` page containers, metric
  strips, a jobs command bar, the split workbench, the resume detail band,
  and the settings status rail.
- Old style classes and DOM wrapper layers may be removed or renamed when
  the corresponding frontend tests are updated; `data-action`,
  `data-form`, form `name`, hash routes, and backend API contracts remain
  unchanged.
- This supersedes the ADR-0017 clause that old classes and selectors remain
  untouched, and the fixed shell/card clauses of ADR-0020 / ADR-0021 where
  they conflict with the frozen v3 preview.
- The v3 radius tokens (`--ra-radius-card` / `--ra-radius-panel` = 12px)
  supersede the ADR-0017 8px card radius for v3 surfaces, and the v3 layer
  may transition `color` for interaction feedback, superseding the ADR-0017
  motion property whitelist for new v3 components.
- No new framework or build step is introduced. Desktop-first; narrow
  screens only need to avoid breakage.

## Consequences

- `styles.css` carries a v3 layer as the active visual surface; legacy
  selectors may be dropped once tests no longer reference them.
- Playwright smoke compares the five views against the frozen preview.
- The v3 shell does not restore the removed appraisal / weight / salary
  benchmark modules recorded in ADR-0025.
