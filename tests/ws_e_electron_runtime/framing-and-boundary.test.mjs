import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { join, resolve } from "node:path";
import test from "node:test";

import { FrameDecoder, TransportProtocolError, encodeFrame } from "../../dist/apps/desktop/src/main/backendRuntime/framing.js";
import { contextBridgeSafe } from "../../dist/apps/desktop/src/main/backendRuntime/protocol.js";
import { createBackendRuntimeBridge, createBackendRuntimeReadOnlyBridge } from "../../dist/apps/desktop/src/preload/backendRuntime/bridge.js";

test("framing handles fragmented and multiple frames", () => {
  const wire = Buffer.concat([encodeFrame({ kind: "first", value: "雪" }), encodeFrame({ kind: "second" })]);
  const decoder = new FrameDecoder();
  const messages = [];
  for (let index = 0; index < wire.length; index += 2) messages.push(...decoder.feed(wire.subarray(index, index + 2)));
  decoder.finish();
  assert.deepEqual(messages, [{ kind: "first", value: "雪" }, { kind: "second" }]);
});

test("framing rejects malformed and oversized frames", () => {
  assert.throws(
    () => new FrameDecoder().feed(Buffer.from("Content-Length: 2\r\nContent-Type: text/plain\r\n\r\n{}")),
    TransportProtocolError
  );
  assert.throws(() => new FrameDecoder(2).feed(encodeFrame({ value: 1 })), TransportProtocolError);
});

test("stream tickets remain metadata and raw paths fail closed", () => {
  const safe = contextBridgeSafe({
    artifact_id: `art_sha256_${"a".repeat(64)}`,
    access: { mode: "STREAM_TICKET", ticket_id: "ticket-1", expires_at: "2026-08-09T00:00:00Z" }
  });
  assert.equal(safe.access.ticket_id, "ticket-1");
  assert.throws(() => contextBridgeSafe({ parquet_path: "D:\\secret\\table.parquet" }), /raw storage field/);
  assert.throws(() => contextBridgeSafe({ value: "D:\\secret\\table.parquet" }), /raw filesystem path/);
});

test("preload bridge exposes only explicit narrow capability methods and events", async () => {
  const calls = [];
  const listeners = new Map();
  const ipc = {
    invoke: async (channel, ...args) => { calls.push([channel, ...args]); return { ok: true }; },
    on: (channel, listener) => listeners.set(channel, listener),
    removeListener: (channel, listener) => { if (listeners.get(channel) === listener) listeners.delete(channel); }
  };
  const bridge = createBackendRuntimeBridge(ipc);
  assert.deepEqual(Object.keys(bridge).sort(), [
    "cancelTask", "getCapabilities", "getHealth", "onConnectionState", "onTaskEvent",
    "openArtifactStream", "resumeTask", "retryTask"
  ]);
  assert.equal("request" in bridge, false);
  assert.equal("spawn" in bridge, false);
  assert.equal("openPath" in bridge, false);
  await bridge.cancelTask({ taskId: "tsk_1", expectedStateVersion: 2, reason: "user" });
  assert.equal(calls[0][0], "backendRuntime:cancelTask");
  const unsubscribe = bridge.onTaskEvent(() => {});
  assert.equal(listeners.has("backendRuntime:taskEvent"), true);
  unsubscribe();
  assert.equal(listeners.has("backendRuntime:taskEvent"), false);
});

test("renderer product bridge exposes read-only evidence snapshot/event and no L2/L3 mutation", async () => {
  const calls = [];
  const listeners = new Map();
  const ipc = {
    invoke: async (channel) => { calls.push(channel); return channel.endsWith("evidenceSnapshot") ? { event_type: "round3.research.evidence.bundle.v1" } : {}; },
    on: (channel, listener) => listeners.set(channel, listener),
    removeListener: (channel, listener) => { if (listeners.get(channel) === listener) listeners.delete(channel); }
  };
  const bridge = createBackendRuntimeReadOnlyBridge(ipc);
  assert.deepEqual(Object.keys(bridge).sort(), ["getCapabilities", "getEvidenceSnapshot", "getHealth", "onConnectionState", "onEvidenceEvent"]);
  for (const forbidden of ["cancelTask", "retryTask", "resumeTask", "openArtifactStream", "execute", "publish"]) assert.equal(forbidden in bridge, false);
  assert.equal((await bridge.getEvidenceSnapshot()).event_type, "round3.research.evidence.bundle.v1");
  assert.deepEqual(calls, ["backendRuntime:evidenceSnapshot"]);
  const unsubscribe = bridge.onEvidenceEvent(() => {});
  assert.equal(listeners.has("backendRuntime:taskEvent"), true);
  unsubscribe();
});

test("preload source has no filesystem, database, process, or raw transport access", async () => {
  const root = resolve(import.meta.dirname, "../..");
  const preloadRoot = join(root, "apps", "desktop", "src", "preload", "backendRuntime");
  for (const name of await readdir(preloadRoot)) {
    const source = await readFile(join(preloadRoot, name), "utf8");
    assert.doesNotMatch(source, /node:(?:fs|child_process)|\b(?:sqlite|duckdb|parquet|sql)\b/i, name);
    assert.doesNotMatch(source, /\.send\(|postMessage|MessagePort/, name);
  }
});
