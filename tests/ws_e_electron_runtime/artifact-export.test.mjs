import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const { ArtifactExportBroker } = await import(
  "../../dist/apps/desktop/src/main/productRuntime/artifactExport.js"
);

function descriptor(bytes) {
  const sha256 = createHash("sha256").update(bytes).digest("hex");
  return {
    artifactId: `art_sha256_${sha256}`,
    sha256,
    byteSize: bytes.byteLength,
    mediaType: "application/json",
    role: "PRODUCT_RESEARCH_BACKTEST_READ_MODEL",
    createdAt: "2026-08-24T00:00:00Z"
  };
}

async function produceChunks(bytes, sink) {
  for (let offset = 0; offset < bytes.byteLength; offset += 256 * 1024) {
    const chunk = bytes.subarray(offset, Math.min(bytes.byteLength, offset + 256 * 1024));
    await sink(Uint8Array.from(chunk), offset);
  }
  const item = descriptor(bytes);
  return { artifactId: item.artifactId, sha256: item.sha256, byteSize: item.byteSize };
}

test("ACC-C3-10 native chooser cancellation is NOT_RUN and creates no capability", async () => {
  const broker = new ArtifactExportBroker({ chooseDestination: async () => null });
  assert.equal(await broker.chooseDestination("result.json"), null);
  assert.equal(broker.retainedCapabilityCount, 0);
});

test("ACC-C3-10 destination capability writes tmp, hashes, fsyncs and atomically renames exact bytes", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-artifact-export-"));
  try {
    const destination = join(dir, "result.json");
    const bytes = Buffer.from(`{"payload":"${"x".repeat(600 * 1024)}"}`, "utf8");
    const item = descriptor(bytes);
    const broker = new ArtifactExportBroker({
      chooseDestination: async () => destination,
      tokenFactory: () => "edc_01ARZ3NDEKTSV4RRFFQ69G5FAV",
      now: () => Date.parse("2026-08-24T00:00:00Z")
    });
    const selection = await broker.chooseDestination("result.json");
    assert.deepEqual(Object.keys(selection).sort(), ["capabilityToken", "displayName"]);
    assert.equal(JSON.stringify(selection).includes(destination), false);
    const receipt = await broker.writeDestination(
      {
        capabilityToken: selection.capabilityToken,
        artifactId: item.artifactId,
        expectedSha256: item.sha256,
        expectedByteSize: item.byteSize
      },
      (sink) => produceChunks(bytes, sink)
    );
    assert.deepEqual(await readFile(destination), bytes);
    assert.deepEqual(receipt, {
      destinationToken: selection.capabilityToken,
      displayName: "result.json",
      artifactId: item.artifactId,
      sha256: item.sha256,
      byteSize: item.byteSize,
      completedAt: "2026-08-24T00:00:00.000Z"
    });
    assert.deepEqual(await readdir(dir), ["result.json"]);
    await assert.rejects(
      () => broker.writeDestination(
        {
          capabilityToken: selection.capabilityToken,
          artifactId: item.artifactId,
          expectedSha256: item.sha256,
          expectedByteSize: item.byteSize
        },
        (sink) => produceChunks(bytes, sink)
      ),
      (error) => error.code === "ARTIFACT_EXPORT_CAPABILITY_NOT_AVAILABLE"
    );
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("ACC-C3-10 mid-stream failure removes tmp and never publishes destination", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-artifact-export-failure-"));
  try {
    const destination = join(dir, "orders.csv");
    const bytes = Buffer.alloc(600 * 1024, 0x61);
    const item = descriptor(bytes);
    const broker = new ArtifactExportBroker({
      chooseDestination: async () => destination,
      tokenFactory: () => "edc_01ARZ3NDEKTSV4RRFFQ69G5FAW"
    });
    const selection = await broker.chooseDestination("orders.csv");
    await assert.rejects(
      () => broker.writeDestination(
        {
          capabilityToken: selection.capabilityToken,
          artifactId: item.artifactId,
          expectedSha256: item.sha256,
          expectedByteSize: item.byteSize
        },
        async (sink) => {
          await sink(Uint8Array.from(bytes.subarray(0, 256 * 1024)), 0);
          throw new Error("simulated stream failure");
        }
      ),
      /simulated stream failure/
    );
    const names = await readdir(dir);
    assert.equal(names.includes("orders.csv"), false);
    assert.equal(names.filter((name) => /^\.orders\.csv\.v3-[0-9a-f]+\.tmp$/.test(name)).length, 0);
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});
