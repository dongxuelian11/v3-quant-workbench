// smoke:product-entry — clean-start research entry end-to-end over the REAL
// production backend process + the production typed Desktop bridge.
//
// Flow (task section 12):
//   target-owned source authority -> create Project (backend-minted ids) ->
//   target-authorized research-package import -> durable discovery -> submit -> Task/Result/
//   Artifact -> graceful shutdown -> restart same storage -> all canonical
//   state recovered.  The package is prepared ONLY as test setup through
//   accepted canonical owners in the exact target storage. The LIVE import
//   independently resolves those target rows/bytes before registration. No
//   fixture backend, package-bootstrapped authority, or caller numeric truth.

import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(import.meta.dirname, "..");
const backendPython = process.env.V3_TEST_PYTHON ?? process.env.V3_PYTHON ?? "python3";
const storageRoot = await mkdtemp(join(tmpdir(), "v3-product-entry-storage-"));
const userDataDir = await mkdtemp(join(tmpdir(), "v3-product-entry-userdata-"));
process.env.V3_PRODUCT_STORAGE_ROOT = storageRoot;

// ---- test-setup boundary: prepare a canonical research package ------------
const packageBuild = spawnSync(backendPython, [resolve(root, "scripts/product_entry_smoke_python.py"), storageRoot], {
  cwd: root,
  encoding: "utf8",
  env: {
    ...process.env,
    PYTHONPATH: [root, resolve(root, "apps/backend/src"), process.env.PYTHONPATH]
      .filter(Boolean)
      .join(delimiter)
  }
});
if (packageBuild.status !== 0) {
  console.error(`product-entry smoke package build failed:\n${packageBuild.stderr}`);
  process.exit(1);
}
const {
  package_dir: packageDir,
  run_spec_id: runSpecId,
  source_project_id: sourceProjectId,
  source_project_context_revision_id: sourcePcr,
  source_run_spec_count: sourceRunSpecCount
} = JSON.parse(packageBuild.stdout.trim());

const { BackendSupervisor } = await import("../dist/apps/desktop/src/main/backendRuntime/supervisor.js");
const { ProductBridge } = await import("../dist/apps/desktop/src/main/productRuntime/productBridge.js");
const { WorkspaceStore } = await import("../dist/apps/desktop/src/main/runtimePersistence/workspaceStore.js");
const { ProductBindingStore } = await import("../dist/apps/desktop/src/main/productRuntime/bindingStore.js");

const supervisorConfig = {
  pythonExecutable: backendPython,
  backendWorkingDirectory: resolve(root, "apps/backend/src"),
  desktopVersion: "0.1.0-smoke",
  handshakeTimeoutMs: 30_000,
  requestTimeoutMs: 120_000,
  crashLoopLimit: 3,
  crashLoopWindowMs: 60_000
};

let activeSupervisor = null;
let shutdownDone = false;
async function shutdownSupervisor(supervisor) {
  if (shutdownDone) return;
  await supervisor.shutdown(20_000);
  shutdownDone = true;
}

try {
  // ---- phase 1: target authority -> create Project -> import -> run -------
  const supervisor = new BackendSupervisor(supervisorConfig);
  activeSupervisor = supervisor;
  shutdownDone = false;
  const store = new WorkspaceStore(join(userDataDir, "workspace.json"));
  const bindings = new ProductBindingStore(join(userDataDir, "v3-product-binding.json"));
  const bridge = new ProductBridge(supervisor, store, bindings, async () => packageDir);

  await supervisor.start();
  console.log("[1] backend ready (target canonical source authority present)");

  const before = await bridge.listProjects();
  assert.equal(before.projects.length, 1, "only the explicit target source-authority project may pre-exist");
  assert.equal(before.projects[0].projectId, sourceProjectId, "pre-existing project must be the declared target authority");

  await bridge.connectExistingProject({ projectId: sourceProjectId, projectContextRevisionId: sourcePcr });
  const sourceListing = await bridge.listBacktestRunSpecs();
  assert.equal(sourceListing.specs.length, sourceRunSpecCount, "Desktop must fetch page 2 and list all 51 target-owned specs");
  assert.equal(new Set(sourceListing.specs.map((item) => item.artifactId)).size, sourceRunSpecCount, "Desktop pagination must not duplicate specs");
  assert.equal(sourceListing.hasMore, false, "bounded Desktop auto-pagination must exhaust 51 specs");
  console.log("[2] artifact-cursor pagination -> 51 specs across page 1 + page 2");

  const created = await bridge.createProject({ displayName: "冒烟研究项目", notes: "clean-start smoke" });
  assert.match(created.projectId, /^prj_[0-9A-HJKMNP-TV-Z]{26}$/, "backend must mint prj_ id");
  assert.match(created.projectContextRevisionId, /^pcr_[0-9A-HJKMNP-TV-Z]{26}$/, "backend must mint pcr_ id");
  console.log(`[3] createProject -> ${created.projectId}`);

  await bridge.connectExistingProject({ projectId: created.projectId, projectContextRevisionId: created.projectContextRevisionId });
  const context = await bridge.getProjectContext();
  assert.equal(context.projectId, created.projectId, "bound project must match created project");
  console.log("[4] project bound + persisted");

  const emptySpecs = await bridge.listBacktestRunSpecs();
  assert.equal(emptySpecs.specs.length, 0, "no hidden/fixture run specs on empty project");

  const imported = await bridge.importResearchPackage();
  assert.ok(imported !== null, "package import must succeed");
  assert.equal(imported.runSpecId, runSpecId, "imported run spec identity must equal the packaged identity");
  const replay = await bridge.importResearchPackage();
  assert.equal(replay?.alreadyImported, true, "same package re-import must be idempotent");
  console.log(`[5] target-authorized package import -> ${imported.runSpecId.slice(0, 24)}…`);

  const listing = await bridge.listBacktestRunSpecs();
  assert.equal(listing.specs.length, 1, "discovery must find the imported spec");
  assert.equal(listing.specs[0].status, "EXECUTABLE", "verified spec must list executable");
  assert.equal(listing.specs[0].runSpecId, runSpecId, "discovery identity exact");

  const outcome = await bridge.submitExistingBacktestRunSpec(runSpecId);
  assert.ok(outcome.taskId.startsWith("tsk_"), "submit must return a canonical task");

  let task = await bridge.getTask(outcome.taskId);
  const deadline = Date.now() + 90_000;
  while (task.state !== "SUCCEEDED" && Date.now() < deadline) {
    if (task.state === "FAILED" || task.state === "CANCELLED") {
      throw new Error(`task failed: ${task.state}`);
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 500));
    task = await bridge.getTask(outcome.taskId);
  }
  assert.equal(task.state, "SUCCEEDED", "canonical backtest task must succeed");
  console.log(`[6] submit -> Task ${outcome.taskId.slice(0, 16)} SUCCEEDED`);

  const events = await bridge.getTaskEvents(0, 500);
  const successEvent = [...events.items].reverse().find((item) => item.eventType === "TASK_SUCCEEDED" && item.resultId !== null);
  assert.ok(successEvent?.resultId, "TASK_SUCCEEDED must carry a canonical result id");
  const result = await bridge.getResult(successEvent.resultId);
  assert.ok(result.resultArtifact, "result must publish a canonical artifact");
  const artifactId = result.resultArtifact.artifactId;
  const descriptor = await bridge.getArtifactDescriptor(artifactId);
  assert.match(descriptor.artifactId, /^art_sha256_/, "result artifact must be content-addressed");
  console.log(`[7] Result ${result.resultId.slice(0, 16)} + Artifact ${artifactId.slice(0, 20)}…`);

  // ---- graceful shutdown ----------------------------------------------------
  await shutdownSupervisor(supervisor);
  console.log("[8] graceful shutdown");

  // ---- phase 2: restart same storage; all canonical state recovered --------
  const supervisor2 = new BackendSupervisor(supervisorConfig);
  activeSupervisor = supervisor2;
  shutdownDone = true; // phase-1 supervisor already shut down
  const store2 = new WorkspaceStore(join(userDataDir, "workspace.json"));
  const bindings2 = new ProductBindingStore(join(userDataDir, "v3-product-binding.json"));
  const bridge2 = new ProductBridge(supervisor2, store2, bindings2, async () => packageDir);
  await supervisor2.start();
  const persisted = await bridge2.restorePersistedBinding();
  assert.ok(persisted !== null, "persisted binding must restore after restart");
  await bridge2.connectExistingProject({
    projectId: persisted.projectId,
    projectContextRevisionId: persisted.projectContextRevisionId
  });
  console.log("[9] restart: binding restored");

  const projectsAfter = await bridge2.listProjects();
  assert.ok(projectsAfter.projects.some((item) => item.projectId === created.projectId), "listProjects stable after restart");
  const listingAfter = await bridge2.listBacktestRunSpecs();
  assert.deepEqual(listingAfter, listing, "run-spec discovery stable after restart");
  const taskAfter = await bridge2.getTask(outcome.taskId);
  assert.equal(taskAfter.state, "SUCCEEDED", "task state recovered after restart");
  const resultAfter = await bridge2.getResult(successEvent.resultId);
  assert.equal(resultAfter.resultArtifact?.artifactId, artifactId, "result artifact stable after restart");
  await supervisor2.shutdown(20_000);
  console.log("[10] restart: Task/Result/Artifact recovered");

  console.log("\nsmoke:product-entry PASS — target owner match -> Project -> RunSpec -> Backtest -> Task/Result/Artifact -> shutdown -> restart recovery");
} catch (error) {
  await activeSupervisor?.shutdown(5_000).catch(() => {});
  console.error("\nsmoke:product-entry FAIL:", error);
  process.exit(1);
} finally {
  await rm(packageDir, { recursive: true, force: true });
  await rm(storageRoot, { recursive: true, force: true });
  await rm(userDataDir, { recursive: true, force: true });
  delete process.env.V3_PRODUCT_STORAGE_ROOT;
}
