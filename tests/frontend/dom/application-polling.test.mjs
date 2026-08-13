import test from "node:test";
import assert from "node:assert/strict";

/* Must be imported first: installs browser globals before events.js
 * evaluates (it reads localStorage at module scope). */
import "./happy-setup.mjs";

import {
  startPolling,
  state,
  stopApplicationPolling,
} from "../../../src/resualign/static/app/events.js";

test("stopApplicationPolling clears the raw application timer", () => {
  const cleared = [];
  const original = window.clearInterval;
  window.clearInterval = (timer) => cleared.push(timer);
  try {
    state.applicationPoll = { jobId: "j1", timer: 1 };
    stopApplicationPolling();
    assert.equal(state.applicationPoll, null);
    assert.ok(cleared.includes(1), "raw application timer was cleared");
  } finally {
    window.clearInterval = original;
  }
});

test("startPolling registers the application poller for stopAllPolling", () => {
  let runs = 0;
  startPolling("application", () => {
    runs += 1;
  }, 100000);
  assert.equal(runs, 1, "startPolling runs immediately");
  assert.ok(state.pollers.application, "application poller is registered");
  stopApplicationPolling();
  assert.equal(state.pollers.application, undefined);
  assert.equal(state.applicationPoll, null);
});
