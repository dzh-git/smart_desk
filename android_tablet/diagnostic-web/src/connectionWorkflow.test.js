import test from "node:test";
import assert from "node:assert/strict";

import { connectionWaitingCopy } from "./connectionWorkflow.js";

test("connection failures use waiting copy instead of diagnostics", () => {
  for (const mode of [
    "checking",
    "waiting-network",
    "waiting-backend",
    "waiting-binding",
    "waiting-frontend",
    "waiting-config",
  ]) {
    const copy = connectionWaitingCopy(mode);
    assert.ok(copy);
    assert.equal(copy.length, 2);
    assert.doesNotMatch(copy.join(" "), /诊断/);
  }
});

test("maintenance remains an explicit non-waiting mode", () => {
  assert.equal(connectionWaitingCopy("maintenance"), null);
  assert.equal(connectionWaitingCopy("setup"), null);
});
