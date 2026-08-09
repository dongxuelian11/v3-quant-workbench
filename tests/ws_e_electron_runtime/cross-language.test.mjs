import assert from "node:assert/strict";
import { resolve } from "node:path";
import test from "node:test";

import { BackendSupervisor } from "../../dist/apps/desktop/src/main/backendRuntime/supervisor.js";

test("real Python bootstrap completes framed authenticated handshake and graceful shutdown", { timeout: 15_000 }, async () => {
  const root = resolve(import.meta.dirname, "../..");
  const supervisor = new BackendSupervisor({
    pythonExecutable: process.env.V3_TEST_PYTHON ?? "python",
    backendWorkingDirectory: resolve(root, "apps/backend/src"),
    desktopVersion: "0.1.0-test",
    handshakeTimeoutMs: 10_000,
    requestTimeoutMs: 2_000,
    autoReconnect: false
  });
  const diagnostics = [];
  supervisor.on("diagnostic", (item) => diagnostics.push(item));
  await supervisor.start();
  assert.equal(supervisor.state, "READY");
  assert.equal(supervisor.capabilities.length, 17);
  assert.equal(supervisor.capabilities.every((item) => item.truth_state === "UNAVAILABLE"), true);
  const health = await supervisor.getHealth();
  assert.equal(health.state, "READY");
  await supervisor.shutdown(5_000);
  assert.equal(supervisor.state, "STOPPED");
  assert.deepEqual(diagnostics, []);
});
