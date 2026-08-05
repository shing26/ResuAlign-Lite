# Spec: Frontend theming and three-column workbench (T5)

## Goal

Give the buildless vanilla frontend a token-based design system and turn the
workbench into a three-column immersive layout without breaking the selector
contracts that Playwright and the app itself depend on.

## Design tokens

- Define CSS custom properties in `styles.css` on `:root` and
  `[data-theme="dark"]`: `--bg`, `--surface`, `--surface-2`, `--text`,
  `--muted`, `--border`, `--accent`, `--accent-2`, `--danger`, `--success`,
  `--radius-sm/md/lg` (4/6/8px), `--shadow-sm`, `--transition-fast`,
  `--font-ui`, `--font-mono`.
- Theme toggle button in the top nav writes `document.documentElement.dataset.theme`
  and persists to localStorage. Respect `prefers-reduced-motion` by disabling
  non-essential transitions.
- Do not use one-note palettes; the light theme stays neutral with a single
  restrained accent and dark mode is slate-based.

## Workbench layout

- Wide screens (`>=1100px`): CSS grid `300px minmax(0, 1fr) 320px` with the
  left column for JD and controls, center for diffs, right for appraisal/JD
  profile summary.
- `1100px - 800px`: right column becomes an off-canvas drawer toggled by the
  existing workbench action bar.
- Below `800px`: left and right panels collapse into tabs; the center remains
  the primary reading surface.
- All existing `#app`, `#toast-region`, `#print-root`, `data-*`, and `aria-*`
  attributes remain present and functional; new controls use `data-action` and
  keyboard-accessible buttons.

## ESM split

Split `static/app.js` into:

- `static/app/main.js` - bootstrapping, routing, event delegation
- `static/app/theme.js` - token theme switching
- `static/app/events.js` - SSE/progress event handling and polling
- `static/app/diff-editor.js` - diff accept/regenerate and diff rendering
- `static/app/appraisal-panel.js` - score, radar, JD profile, provenance

`index.html` imports `static/app/main.js` with `type="module"`; old
`app.js` is removed only after smoke tests pass. `node --check` must pass for
every module. Preserve `static/app.js` as a thin re-export during migration.
