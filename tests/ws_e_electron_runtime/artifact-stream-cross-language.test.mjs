import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, join, resolve } from "node:path";
import test from "node:test";

import { BackendSupervisor } from "../../dist/apps/desktop/src/main/backendRuntime/supervisor.js";
import { ProductBindingStore, productBindingPath } from "../../dist/apps/desktop/src/main/productRuntime/bindingStore.js";
import { ProductBridge } from "../../dist/apps/desktop/src/main/productRuntime/productBridge.js";
import { ArtifactExportBroker } from "../../dist/apps/desktop/src/main/productRuntime/artifactExport.js";
import { WorkspaceStore } from "../../dist/apps/desktop/src/main/runtimePersistence/workspaceStore.js";

test("ACC-C3-09 real Python backend streams a large exact Artifact through Electron ProductBridge", { timeout: 30_000 }, async () => {
  const root = resolve(import.meta.dirname, "../..");
  const storageRoot = await mkdtemp(join(tmpdir(), "v3-stream-xlang-storage-"));
  const userDataRoot = await mkdtemp(join(tmpdir(), "v3-stream-xlang-userdata-"));
  const priorStorageRoot = process.env.V3_PRODUCT_STORAGE_ROOT;
  const python = process.env.V3_TEST_PYTHON ?? process.env.V3_PYTHON ?? (process.platform === "win32" ? "python" : "python3");
  const expected = Buffer.concat([
    Buffer.from('{"payload":"', "utf8"),
    Buffer.alloc(600 * 1024, "x"),
    Buffer.from('"}', "utf8")
  ]);
  let supervisor;
  process.env.V3_PRODUCT_STORAGE_ROOT = storageRoot;
  try {
    const setupProcess = spawnSync(
      python,
      [resolve(root, "scripts/artifact-stream-smoke-python.py"), storageRoot],
      {
        cwd: root,
        encoding: "utf8",
        env: {
          ...process.env,
          PYTHONPATH: [root, resolve(root, "apps/backend/src"), process.env.PYTHONPATH]
            .filter(Boolean)
            .join(delimiter)
        }
      }
    );
    assert.equal(setupProcess.status, 0, setupProcess.stderr || setupProcess.error?.message);
    const setup = JSON.parse(setupProcess.stdout.trim());
    assert.ok(setup.byte_size > 2 * 256 * 1024, "fixture must cross at least two chunk boundaries");
    assert.equal(setup.byte_size, expected.byteLength);
    assert.equal(setup.sha256, createHash("sha256").update(expected).digest("hex"));

    supervisor = new BackendSupervisor({
      pythonExecutable: python,
      backendWorkingDirectory: resolve(root, "apps/backend/src"),
      desktopVersion: "0.1.0-artifact-stream-test",
      handshakeTimeoutMs: 10_000,
      requestTimeoutMs: 10_000,
      autoReconnect: false
    });
    const bridge = new ProductBridge(
      supervisor,
      new WorkspaceStore(join(userDataRoot, "workspace.json")),
      new ProductBindingStore(productBindingPath(userDataRoot))
    );
    await supervisor.start();
    await bridge.connectExistingProject({
      projectId: setup.project_id,
      projectContextRevisionId: setup.project_context_revision_id
    });
    const streamed = await bridge.readArtifactBytes(setup.artifact_id);
    assert.equal(streamed.artifactId, setup.artifact_id);
    assert.equal(streamed.sha256, setup.sha256);
    assert.equal(streamed.byteSize, setup.byte_size);
    assert.deepEqual(Buffer.from(streamed.bytes), expected);
    await supervisor.shutdown(5_000);
    supervisor = undefined;
  } finally {
    await supervisor?.shutdown(5_000).catch(() => undefined);
    if (priorStorageRoot === undefined) delete process.env.V3_PRODUCT_STORAGE_ROOT;
    else process.env.V3_PRODUCT_STORAGE_ROOT = priorStorageRoot;
    await rm(storageRoot, { recursive: true, force: true }).catch(() => undefined);
    await rm(userDataRoot, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("ACC-C3-10 real Python backend and Electron main complete export only after exact native write", { timeout: 30_000 }, async () => {
  const root = resolve(import.meta.dirname, "../..");
  const storageRoot = await mkdtemp(join(tmpdir(), "v3-export-xlang-storage-"));
  const userDataRoot = await mkdtemp(join(tmpdir(), "v3-export-xlang-userdata-"));
  const priorStorageRoot = process.env.V3_PRODUCT_STORAGE_ROOT;
  const python = process.env.V3_TEST_PYTHON ?? process.env.V3_PYTHON ?? (process.platform === "win32" ? "python" : "python3");
  const expected = Buffer.concat([
    Buffer.from('{"payload":"', "utf8"),
    Buffer.alloc(600 * 1024, "x"),
    Buffer.from('"}', "utf8")
  ]);
  const destination = join(userDataRoot, "verified-result.json");
  let supervisor;
  process.env.V3_PRODUCT_STORAGE_ROOT = storageRoot;
  try {
    const setupProcess = spawnSync(
      python,
      [resolve(root, "scripts/artifact-stream-smoke-python.py"), storageRoot],
      {
        cwd: root,
        encoding: "utf8",
        env: {
          ...process.env,
          PYTHONPATH: [root, resolve(root, "apps/backend/src"), process.env.PYTHONPATH]
            .filter(Boolean)
            .join(delimiter)
        }
      }
    );
    assert.equal(setupProcess.status, 0, setupProcess.stderr || setupProcess.error?.message);
    const setup = JSON.parse(setupProcess.stdout.trim());
    supervisor = new BackendSupervisor({
      pythonExecutable: python,
      backendWorkingDirectory: resolve(root, "apps/backend/src"),
      desktopVersion: "0.1.0-artifact-export-test",
      handshakeTimeoutMs: 10_000,
      requestTimeoutMs: 10_000,
      autoReconnect: false
    });
    const diagnostics = [];
    supervisor.on("diagnostic", (diagnostic) => diagnostics.push(diagnostic));
    const exportBroker = new ArtifactExportBroker({
      chooseDestination: async () => destination,
      tokenFactory: () => "edc_01ARZ3NDEKTSV4RRFFQ69G5FAX"
    });
    const bridge = new ProductBridge(
      supervisor,
      new WorkspaceStore(join(userDataRoot, "workspace.json")),
      new ProductBindingStore(productBindingPath(userDataRoot)),
      undefined,
      undefined,
      null,
      exportBroker
    );
    await supervisor.start();
    await bridge.connectExistingProject({
      projectId: setup.project_id,
      projectContextRevisionId: setup.project_context_revision_id
    });
    let outcome;
    try {
      outcome = await bridge.exportArtifact({
        artifactId: setup.artifact_id,
        suggestedName: "verified-result.json"
      });
    } catch (error) {
      error.message = `${error.message}; diagnostics=${JSON.stringify(diagnostics)}`;
      throw error;
    }
    assert.equal(outcome.state, "COMPLETED");
    assert.equal(outcome.artifactId, setup.artifact_id);
    assert.equal(outcome.sha256, setup.sha256);
    assert.equal(outcome.byteSize, setup.byte_size);
    assert.deepEqual(await readFile(destination), expected);
    assert.deepEqual((await readdir(userDataRoot)).sort(), [
      "v3-product-binding.json",
      "verified-result.json"
    ]);
    const task = await bridge.getTask(outcome.taskId);
    assert.equal(task.state, "SUCCEEDED");
    assert.equal(task.outputs.EXPORT_MANIFEST, outcome.manifestArtifactId);
    const manifest = await bridge.getArtifactDescriptor(outcome.manifestArtifactId);
    assert.equal(manifest.artifactId, outcome.manifestArtifactId);
    await supervisor.shutdown(5_000);
    supervisor = undefined;
  } finally {
    await supervisor?.shutdown(5_000).catch(() => undefined);
    if (priorStorageRoot === undefined) delete process.env.V3_PRODUCT_STORAGE_ROOT;
    else process.env.V3_PRODUCT_STORAGE_ROOT = priorStorageRoot;
    await rm(storageRoot, { recursive: true, force: true }).catch(() => undefined);
    await rm(userDataRoot, { recursive: true, force: true }).catch(() => undefined);
  }
});
