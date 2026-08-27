import { $$ } from "./events.js";

/* Mirror source.scrollTop onto target; returns true when it moved.
 * Scroll sync is position state, not animation, so it stays active
 * under prefers-reduced-motion (the reduced-motion CSS already forces
 * scroll-behavior: auto for any native smooth scrolling). */
export function syncScrollTop(target, source) {
  if (!target || !source || target === source) return false;
  if (target.scrollTop === source.scrollTop) return false;
  target.scrollTop = source.scrollTop;
  return true;
}

/* Wire two compare columns so scrolling one mirrors the other, guarded
 * by a reentrancy flag (programmatic scrollTop assignment fires scroll
 * events in real browsers). Returns an unbind function. */
export function bindColumnScrollSync(columns) {
  const [left, right] = columns;
  if (!left || !right || left === right) return () => {};
  let syncing = false;
  const onLeftScroll = () => {
    if (syncing) return;
    syncing = true;
    syncScrollTop(right, left);
    syncing = false;
  };
  const onRightScroll = () => {
    if (syncing) return;
    syncing = true;
    syncScrollTop(left, right);
    syncing = false;
  };
  left.addEventListener("scroll", onLeftScroll);
  right.addEventListener("scroll", onRightScroll);
  return () => {
    left.removeEventListener("scroll", onLeftScroll);
    right.removeEventListener("scroll", onRightScroll);
  };
}

/* Read the .cmp-column scroll positions inside `container`. */
export function captureColumnScrolls(container) {
  if (!container) return [];
  return $$(".cmp-column", container).map((column) => column.scrollTop);
}

/* Restore .cmp-column scroll positions from `tops`; returns the number
 * of columns restored. */
export function restoreColumnScrolls(container, tops) {
  if (!container || !Array.isArray(tops)) return 0;
  let restored = 0;
  $$(".cmp-column", container).forEach((column, index) => {
    const top = tops[index];
    if (typeof top === "number" && Number.isFinite(top)) {
      column.scrollTop = top;
      restored += 1;
    }
  });
  return restored;
}
