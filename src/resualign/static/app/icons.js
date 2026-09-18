/* Lucide icon source (ISC) — ADR-0045.
 *
 * Icons are inlined as SVG strings so the local/embedded build has no sprite
 * request, no icon font, and no runtime package dependency. Path data follows
 * the Lucide 24px grid; --ic-stroke and currentColor keep sizing and theming
 * consistent with the rest of the UI.
 */

const ICON_PATHS = Object.freeze({
  check: '<path d="M20 6 9 17l-5-5"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  "triangle-alert":
    '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  pencil:
    '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
  sun:
    '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  moon:
    '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
  "more-horizontal":
    '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
  "arrow-right":
    '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
  "chevron-right": '<path d="m9 18 6-6-6-6"/>',
  "chevron-down": '<path d="m6 9 6 6 6-6"/>',
  "rotate-ccw": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
  "external-link":
    '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  "shield-check":
    '<path d="M20 13c0 5-3.5 7.5-8 9-4.5-1.5-8-4-8-9V5l8-3 8 3z"/><path d="m9 12 2 2 4-4"/>',
  "loader-circle": '<path d="M21 12a9 9 0 1 1-6.219-8.56"/>',
  dot: '<circle cx="12" cy="12" r="2" fill="currentColor" stroke="none"/>',
});

const ICON_SIZES = new Set([12, 13, 16, 20, 24]);

function sizeClass(size) {
  return size === 13 ? "ic--sm" : `ic--${size}`;
}

export function icon(name, size = 16, className = "") {
  const body = ICON_PATHS[name];
  if (!body) throw new Error(`Unknown icon: ${name}`);
  if (!ICON_SIZES.has(size)) {
    throw new Error(`Unsupported icon size: ${size}`);
  }
  const classes = ["ic", sizeClass(size), className].filter(Boolean).join(" ");
  return `<svg class="${classes}" data-icon="${name}" viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${body}</svg>`;
}
