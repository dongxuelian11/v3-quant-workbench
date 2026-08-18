// smoke:product-entry — honest Product Entry foundation over the REAL
// production backend process + production typed Desktop bridge.
//
// EMPTY_TARGET proves only clean Project entry. A valid package exported from
// another storage fails SOURCE_AUTHORITY_NOT_VERIFIED and cannot register any
// source owner or executable RunSpec. TARGET_CANONICAL_REUSE starts only after
// explicit test setup establishes the exact source authority in the target.

import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(import.meta.dirname, "..");
const backendPython = process.env.V3_TEST_PYTHON ?? process.env.V3_PYTHON ?? (process.platform === "win32" ? "python" : "python3");
const targetStorageRoot = await mkdtemp(join(tmpdir(), "v3-product-entry-target-"));
const externalSourceRoot = await mkdtemp(join(tmpdir(), "v3-product-entry-external-source-"));
const userDataDir = await mkdtemp(join(tmpdir(), "v3-product-entry-userdata-"));
const packageDirs = [];
process.env.V3_PRODUCT_STORAGE_ROOT = targetStorageRoot;

const pythonEnv = {
  ...process.env,
  PYTHONPATH: [root, resolve(root, "apps/backend/src"), process.env.PYTHONPATH]
    .filter(Boolean)
    .join(delimiter)
};

function runHelper(args, label) {
  const outcome = spawnSync(
    backendPython,
    [resolve(root, "scripts/product_entry_smoke_python.py"), ...args],
    { cwd: root, encoding: "utf8", env: pythonEnv }
  );
  if (outcome.status !== 0) throw new Error(`${label} failed:\n${outcome.error?.message ?? outcome.stderr}`);
  return JSON.parse(outcome.stdout.trim());
}

const externalPackage = runHelper(["build", externalSourceRoot], "external package setup");
packageDirs.push(externalPackage.package_dir);

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
const workspacePath = join(userDataDir, "workspace.json");
const bindingPath = join(userDataDir, "v3-product-binding.json");

function makeBridge(supervisor, packageDir) {
  return new ProductBridge(
    supervisor,
    new WorkspaceStore(workspacePath),
    new ProductBindingStore(bindingPath),
    async () => packageDir
  );
}

async function stop(supervisor) {
  await supervisor.shutdown(20_000);
  if (activeSupervisor === supervisor) activeSupervisor = null;
}

try {
  // ---- Phase EMPTY_TARGET -------------------------------------------------
  const emptySupervisor = new BackendSupervisor(supervisorConfig);
  activeSupervisor = emptySupervisor;
  const emptyBridge = makeBridge(emptySupervisor, externalPackage.package_dir);
  await emptySupervisor.start();
  const initial = await emptyBridge.listProjects();
  assert.equal(initial.projects.length, 0, "true empty target must start with an empty project catalog");
  console.log("[EMPTY 1] target catalog empty");

  const cleanProject = await emptyBridge.createProject({ displayName: "空目标研究项目", notes: "clean Project entry only" });
  await emptyBridge.connectExistingProject({
    projectId: cleanProject.projectId,
    projectContextRevisionId: cleanProject.projectContextRevisionId
  });
  assert.equal((await emptyBridge.listBacktestRunSpecs()).specs.length, 0);
  console.log(`[EMPTY 2] createProject -> ${cleanProject.projectId}`);

  let importFailure = null;
  try {
    await emptyBridge.importResearchPackage();
  } catch (error) {
    importFailure = error;
  }
  assert.ok(importFailure, "external package must fail on an authority-empty target");
  assert.match(
    `${importFailure.code ?? ""} ${importFailure.message ?? importFailure}`,
    /SOURCE_AUTHORITY_NOT_VERIFIED/,
    "failure must name the missing target source authority"
  );
  assert.equal((await emptyBridge.listBacktestRunSpecs()).specs.length, 0);
  console.log("[EMPTY 3] external package -> SOURCE_AUTHORITY_NOT_VERIFIED");

  await stop(emptySupervisor);
  const pollution = runHelper(
    ["inspect-empty", targetStorageRoot, cleanProject.projectId, externalPackage.package_dir],
    "empty-target pollution inspection"
  );
  assert.deepEqual(pollution.project_ids, [cleanProject.projectId], "only the created Project may exist");
  assert.equal(pollution.source_project_present, false, "external source Project must not be registered");
  assert.deepEqual(Object.values(pollution.owner_row_matches), [0, 0, 0, 0], "no source owner rows may be registered");
  assert.equal(pollution.target_research_run_spec_refs, 0);
  assert.equal(pollution.all_research_run_spec_refs, 0);
  console.log("[EMPTY 4] no source owner rows / no RESEARCH_RUN_SPEC pollution");

  const emptyRestartSupervisor = new BackendSupervisor(supervisorConfig);
  activeSupervisor = emptyRestartSupervisor;
  const emptyRestartBridge = makeBridge(emptyRestartSupervisor, externalPackage.package_dir);
  await emptyRestartSupervisor.start();
  const projectsAfterEmptyRestart = await emptyRestartBridge.listProjects();
  assert.deepEqual(projectsAfterEmptyRestart.projects.map((item) => item.projectId), [cleanProject.projectId]);
  await emptyRestartBridge.connectExistingProject({
    projectId: cleanProject.projectId,
    projectContextRevisionId: cleanProject.projectContextRevisionId
  });
  assert.equal((await emptyRestartBridge.listBacktestRunSpecs()).specs.length, 0);
  await stop(emptyRestartSupervisor);
  console.log("[EMPTY 5] restart -> only Project, zero executable RunSpec");
  console.log("CLEAN_START_PROJECT_ENTRY = PASS");
  console.log("CLEAN_START_EXECUTABLE_RESEARCH = NOT_AVAILABLE");

  // ---- Phase TARGET_CANONICAL_REUSE --------------------------------------
  // Explicit test setup now publishes accepted owners and exact bytes into
  // the target. This is not part of the empty-target product path.
  const targetSetup = runHelper(["build", targetStorageRoot], "target canonical authority setup");
  packageDirs.push(targetSetup.package_dir);
  const reuseSupervisor = new BackendSupervisor(supervisorConfig);
  activeSupervisor = reuseSupervisor;
  const reuseBridge = makeBridge(reuseSupervisor, targetSetup.package_dir);
  await reuseSupervisor.start();
  const beforeReuse = await reuseBridge.listProjects();
  assert.equal(beforeReuse.projects.length, 2, "clean Project plus explicit source-authority Project must exist");
  assert.ok(beforeReuse.projects.some((item) => item.projectId === targetSetup.source_project_id));
  console.log("[REUSE 1] target canonical source authority explicitly prepared");

  await reuseBridge.connectExistingProject({
    projectId: targetSetup.source_project_id,
    projectContextRevisionId: targetSetup.source_project_context_revision_id
  });
  const sourceListing = await reuseBridge.listBacktestRunSpecs();
  assert.equal(sourceListing.specs.length, targetSetup.source_run_spec_count);
  assert.equal(new Set(sourceListing.specs.map((item) => item.artifactId)).size, targetSetup.source_run_spec_count);
  assert.equal(sourceListing.hasMore, false);
  console.log("[REUSE 2] artifact-cursor pagination -> 51 specs across two pages");

  const reuseProject = await reuseBridge.createProject({ displayName: "目标权威复用项目", notes: "TARGET_CANONICAL_REUSE" });
  await reuseBridge.connectExistingProject({
    projectId: reuseProject.projectId,
    projectContextRevisionId: reuseProject.projectContextRevisionId
  });
  assert.equal((await reuseBridge.listBacktestRunSpecs()).specs.length, 0);
  const imported = await reuseBridge.importResearchPackage();
  assert.ok(imported !== null);
  assert.equal(imported.runSpecId, targetSetup.run_spec_id);
  const replay = await reuseBridge.importResearchPackage();
  assert.equal(replay?.alreadyImported, true);
  const listing = await reuseBridge.listBacktestRunSpecs();
  assert.equal(listing.specs.length, 1);
  assert.equal(listing.specs[0].status, "EXECUTABLE");
  assert.equal(listing.specs[0].runSpecId, targetSetup.run_spec_id);
  console.log("[REUSE 3] target-authority match -> executable RunSpec");

  const outcome = await reuseBridge.submitExistingBacktestRunSpec(targetSetup.run_spec_id);
  let task = await reuseBridge.getTask(outcome.taskId);
  const deadline = Date.now() + 90_000;
  while (task.state !== "SUCCEEDED" && Date.now() < deadline) {
    if (task.state === "FAILED" || task.state === "CANCELLED") throw new Error(`task failed: ${task.state}`);
    await new Promise((resolveWait) => setTimeout(resolveWait, 500));
    task = await reuseBridge.getTask(outcome.taskId);
  }
  assert.equal(task.state, "SUCCEEDED");
  const events = await reuseBridge.getTaskEvents(0, 500);
  const successEvent = [...events.items].reverse().find((item) => item.eventType === "TASK_SUCCEEDED" && item.resultId !== null);
  assert.ok(successEvent?.resultId);
  const result = await reuseBridge.getResult(successEvent.resultId);
  assert.ok(result.resultArtifact);
  const artifactId = result.resultArtifact.artifactId;
  assert.match((await reuseBridge.getArtifactDescriptor(artifactId)).artifactId, /^art_sha256_/);
  console.log("[REUSE 4] submit -> Task/Result/Artifact");

  await stop(reuseSupervisor);
  const reuseRestartSupervisor = new BackendSupervisor(supervisorConfig);
  activeSupervisor = reuseRestartSupervisor;
  const reuseRestartBridge = makeBridge(reuseRestartSupervisor, targetSetup.package_dir);
  await reuseRestartSupervisor.start();
  const persisted = await reuseRestartBridge.restorePersistedBinding();
  assert.equal(persisted?.projectId, reuseProject.projectId);
  await reuseRestartBridge.connectExistingProject({
    projectId: reuseProject.projectId,
    projectContextRevisionId: reuseProject.projectContextRevisionId
  });
  assert.deepEqual(await reuseRestartBridge.listBacktestRunSpecs(), listing);
  assert.equal((await reuseRestartBridge.getTask(outcome.taskId)).state, "SUCCEEDED");
  assert.equal((await reuseRestartBridge.getResult(successEvent.resultId)).resultArtifact?.artifactId, artifactId);
  await stop(reuseRestartSupervisor);
  console.log("[REUSE 5] restart -> RunSpec/Task/Result/Artifact recovered");
  console.log("TARGET_CANONICAL_REUSE = PASS");
  console.log("\nsmoke:product-entry PASS — honest foundation classification preserved");
} catch (error) {
  await activeSupervisor?.shutdown(5_000).catch(() => {});
  console.error("\nsmoke:product-entry FAIL:", error);
  process.exitCode = 1;
} finally {
  for (const packageDir of packageDirs) {
    await rm(packageDir, { recursive: true, force: true });
  }
  await rm(targetStorageRoot, { recursive: true, force: true });
  await rm(externalSourceRoot, { recursive: true, force: true });
  await rm(userDataDir, { recursive: true, force: true });
  delete process.env.V3_PRODUCT_STORAGE_ROOT;
}
