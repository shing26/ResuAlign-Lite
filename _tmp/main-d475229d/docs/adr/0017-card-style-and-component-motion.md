# ADR-0017: Card-Style UI with Component Motion

**Status**: Accepted
**Date**: 2026-08-03

## Context

The Phase 17 redesign replaced the default grey-on-white template with a dark
rail, warm paper canvas, and semantic color bands. User feedback asked for a
clearer visual shift: card-style information hierarchy plus component-level
motion, without turning the local workbench into a marketing page.

## Decision

- Phase 18 keeps the Phase 17 skeleton (`app-rail` / `app-main`, module color
  bands, semantic states) and layers a card system on top: `panel-card`,
  `card-base`, `card-hover-soft`, and card tokens for radius (8px), shadows,
  borders, and padding.
- Cards do not float on hover; interactive cards may lift at most 2px, while
  resume/job/version/diff/application cards only change border and shadow.
- Motion is CSS-only and property-whitelisted: opacity, transform,
  background, border-color, box-shadow, and progress width. No animation
  library, icon library, bundler, or external font is introduced.
- Component motion includes list stagger (max ~320ms), nav and segmented
  indicators driven by `aria-selected`/`aria-pressed`, button press feedback,
  progress pulse, diff-line reveal, toast slide-in, skeleton pulse, and a
  two-beat empty-state action cue.
- All motion honors `prefers-reduced-motion`, mobile 390px disables stagger,
  touch targets are >= 40px (44px recommended), and print output inside
  `#print-root` stays static and clean.

## Considered Options

- Keep the flat Phase 17 look and only recolor: rejected because the user
  explicitly asked for a card-based design with component animation.
- Add a motion library such as GSAP: rejected because the no-build constraint
  and the CSS-only whitelist keep the app maintainable and dependency-free.
- Add a sliding cross-button indicator for segmented controls: rejected in
  favor of per-button `::before` scale transitions, which avoid JS geometry
  measurement and off-screen overflow.

## Consequences

- `styles.css` gains a Phase 18 token/component overlay after the Phase 17
  layer; old classes and selectors remain untouched.
- `app.js` only appends visual classes (`panel-card`, `card-base`,
  `card-hover-soft`, `motion-stagger`, `segmented-card`, `is-loading`,
  `is-saved`) and never changes `data-*`, `aria-*`, or protected selectors.
- The API server continues to serve versioned static assets (`?v=18`) so
  browsers replace cached files.
- A Phase 18 Playwright smoke gates desktop 1440 and mobile 390 for card
  classes, motion, touch targets, overflow, and reduced-motion behavior.
