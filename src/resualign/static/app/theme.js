const STORAGE_KEY = "resualign_theme";

function preferredTheme() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    /* storage can be unavailable in embedded contexts */
  }
  if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
    return "dark";
  }
  return "light";
}

export function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const toggle = document.querySelector("[data-theme-toggle]");
  if (!toggle) return;
  toggle.setAttribute("aria-pressed", String(theme === "dark"));
  const label = toggle.querySelector("[data-theme-label]");
  if (label) label.textContent = theme === "dark" ? "深色" : "浅色";
}

export function toggleTheme() {
  const next =
    document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    /* keep the in-page toggle working when storage is blocked */
  }
  applyTheme(next);
  return next;
}

export function initTheme() {
  applyTheme(preferredTheme());
  return document.documentElement.dataset.theme;
}
