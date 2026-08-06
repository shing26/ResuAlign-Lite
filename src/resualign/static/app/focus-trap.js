/* Focus-trap helpers for dialogs (modal, palette).
 *
 * Pure + DOM-light so the tab-order math and class management can be
 * unit-tested with happy-dom: every function takes the document/root
 * explicitly instead of reading globals. events.js wires these into
 * showModal/closeModal; command-panel.js keeps its own inline trap.
 */

export const MODAL_OPEN_CLASS = "modal-open";

export const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

/** True when `node` is a real, enabled, visible focusable element. */
export function isFocusable(node) {
  if (!node || node.disabled) return false;
  if (node.hidden) return false;
  if (node.getAttribute("type") === "hidden") return false;
  if (node.closest && node.closest("[hidden], [aria-hidden='true']")) return false;
  return true;
}

/** Collect focusable elements inside `root` in document order. */
export function collectFocusables(root) {
  if (!root) return [];
  return [...root.querySelectorAll(FOCUSABLE_SELECTOR)].filter(isFocusable);
}

/** Next tab index with wraparound; -1 when there is nothing to focus. */
export function nextFocusIndex(current, length, shiftKey) {
  if (length <= 0) return -1;
  if (current < 0 || current >= length) return shiftKey ? length - 1 : 0;
  const delta = shiftKey ? -1 : 1;
  return (current + delta + length) % length;
}

/** Focus the first focusable element inside `root`; no-op when none. */
export function focusInitial(root) {
  const items = collectFocusables(root);
  if (items.length) items[0].focus();
}

/** Trap Tab navigation inside `root`: wraps at both ends and pulls focus
 *  back in when it has escaped (e.g. right after the dialog opens). */
export function trapTabKey(root, event, activeElement) {
  if (!root || !event || event.key !== "Tab") return;
  const items = collectFocusables(root);
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  const index = items.indexOf(activeElement);
  if (index === -1) {
    event.preventDefault();
    (event.shiftKey ? last : first).focus();
    return;
  }
  if (event.shiftKey && index === 0) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && index === items.length - 1) {
    event.preventDefault();
    first.focus();
  }
}

/** Restore focus to `node` when it is still connected to the document. */
export function restoreFocus(node) {
  if (node && node.isConnected && typeof node.focus === "function") {
    node.focus();
  }
}

/* Body scroll lock; mirrors command-panel's command-palette-open pattern
 * and pairs with `body.modal-open { overflow: hidden }` in styles.css. */
export function lockBodyScroll(body) {
  if (body) body.classList.add(MODAL_OPEN_CLASS);
}

export function unlockBodyScroll(body) {
  if (body) body.classList.remove(MODAL_OPEN_CLASS);
}
