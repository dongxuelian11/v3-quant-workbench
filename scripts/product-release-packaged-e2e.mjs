import { createHash } from "node:crypto";
import { cp, mkdir, mkdtemp, readFile, readdir, stat, writeFile } from "node:fs/promises";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { dirname, join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { spawn } from "node:child_process";

const execFileAsync = promisify(execFile);
const root = resolve(import.meta.dirname, "..");
const packageRoot = resolve(process.env.V3_PACKAGE_ROOT ?? join(root, "artifacts/package/win-unpacked"));
const reportPath = resolve(process.env.V3_PRODUCT_RELEASE_REPORT ?? join(root, "artifacts/package/V3_V1_PRODUCT_RELEASE_E2E.json"));

function assert(condition, message) {
  if (!condition) throw new Error(`V1_PRODUCT_RELEASE_E2E_FAILED: ${message}`);
}

async function fileSha(path) {
  return createHash("sha256").update(await readFile(path)).digest("hex");
}

async function walk(directory, prefix = "") {
  const entries = (await readdir(directory, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name));
  const files = [];
  for (const entry of entries) {
    const absolute = join(directory, entry.name);
    const name = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) files.push(...await walk(absolute, name));
    else if (entry.isFile()) files.push({ absolute, name: name.replaceAll("\\", "/") });
  }
  return files;
}

async function directoryIdentity(directory) {
  const digest = createHash("sha256");
  let bytes = 0;
  const files = await walk(directory);
  for (const file of files) {
    const content = await readFile(file.absolute);
    bytes += content.byteLength;
    digest.update(file.name); digest.update("\0"); digest.update(content); digest.update("\0");
  }
  return { sha256: digest.digest("hex"), bytes, file_count: files.length };
}

function processAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try { process.kill(pid, 0); return true; } catch (error) {
    return !["ESRCH", "ENOENT"].includes(error?.code);
  }
}

function runProduct(executable, cwd, env, phase, providerMode, outputPath) {
  return new Promise((resolveRun, rejectRun) => {
    const child = spawn(executable, [
      "--v3-product-closure-smoke", "--disable-gpu", "--disable-gpu-compositing", "--in-process-gpu",
    ], {
      cwd,
      env: {
        ...env,
        V3_PRODUCT_CLOSURE_SMOKE_PHASE: phase,
        V3_PRODUCT_CLOSURE_SMOKE_OUTPUT: outputPath,
        V3_PRODUCT_CLOSURE_PROVIDER_MODE: providerMode,
      },
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8"); child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    const phaseTimeoutMs = Number(process.env.V3_PRODUCT_RELEASE_PHASE_TIMEOUT_MS ?? 240_000);
    const timer = setTimeout(() => {
      child.kill();
      rejectRun(new Error(`${phase} timed out after ${phaseTimeoutMs}ms\nSTDOUT:\n${stdout}\nSTDERR:\n${stderr}`));
    }, phaseTimeoutMs);
    child.on("error", (error) => { clearTimeout(timer); rejectRun(error); });
    child.on("exit", (code, signal) => { clearTimeout(timer); resolveRun({ code, signal, stdout, stderr, pid: child.pid ?? null }); });
  });
}

function assertRun(run, smoke, phase, providerMode) {
  assert(run.code === 0 && run.signal === null, `${phase} exit=${run.code}/${run.signal}\n${run.stderr}`);
  assert(smoke.success === true && smoke.app_is_packaged === true && smoke.backend_runtime_mode === "PACKAGED", `${phase} did not prove packaged success`);
  assert(smoke.flow?.status?.productVersion === "1.0.0", `${phase} product version mismatch`);
  assert(smoke.known_id_injection === false, `${phase} used known-ID injection`);
  assert(run.stderr.includes("PACKAGED_RUNTIME_SELECTED") && run.stderr.includes("GRACEFUL_SHUTDOWN_SUCCESS"), `${phase} did not prove packaged selection and graceful shutdown`);
  assert(!run.stderr.includes("FORCED_SHUTDOWN_FALLBACK"), `${phase} used forced shutdown fallback`);
  assert(!processAlive(Number(smoke.backend_pid)), `${phase} left backend PID ${smoke.backend_pid}`);
  const expectedBoundary = providerMode === "DETERMINISTIC_UNAVAILABLE"
    ? "TEST_EXTERNAL_PROVIDER_BOUNDARY_UNAVAILABLE"
    : "TEST_EXTERNAL_PROVIDER_BOUNDARY_SUCCESS";
  assert(smoke.provider_boundary === expectedBoundary, `${phase} provider boundary mismatch`);
}

function canonicalIdentity(smoke) {
  const { projectContext, task, result, artifactDescriptor } = smoke.flow;
  assert(task.state === "SUCCEEDED", "canonical research Task is not successful");
  assert(result.state === "PENDING_RECONCILIATION", "canonical Result truth state is not PENDING_RECONCILIATION");
  assert(task.projectId === projectContext.projectId && result.projectId === projectContext.projectId, "project identity is detached");
  assert(task.resultId === result.resultId && task.runId === result.backtestRunId, "Task/Run/Result identity mismatch");
  assert(task.outputs.BACKTEST_RUN_RESULT === artifactDescriptor.artifactId, "Task output is not result Artifact");
  assert(result.resultArtifact.artifactId === artifactDescriptor.artifactId && result.resultArtifact.sha256 === artifactDescriptor.sha256, "Result/Artifact identity mismatch");
  return {
    project_id: projectContext.projectId,
    project_context_revision_id: projectContext.projectContextRevisionId,
    task_id: task.taskId,
    run_id: task.runId,
    result_id: result.resultId,
    artifact_id: artifactDescriptor.artifactId,
    artifact_sha256: artifactDescriptor.sha256,
    artifact_bytes: artifactDescriptor.byteSize,
  };
}

async function catalogEvidence(pythonPath, pythonRoot, catalogPath, cwd, env) {
  const probe = [
    "import json,sqlite3,sys",
    "c=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True)",
    "c.row_factory=sqlite3.Row",
    "counts={t:c.execute('select count(*) from '+t).fetchone()[0] for t in ('task','run','result','raw_capture','artifact')}",
    "row=c.execute('select source_metadata_json from raw_capture_truth_descriptor order by rowid desc limit 1').fetchone()",
    "metadata=json.loads(row['source_metadata_json']) if row is not None else None",
    "roles=[r[0] for r in c.execute('select semantic_role from artifact order by semantic_role')]",
    "print(json.dumps({'counts':counts,'source_metadata':metadata,'artifact_roles':roles},ensure_ascii=True,sort_keys=True))",
    "c.close()",
  ].join("\n");
  const result = await execFileAsync(pythonPath, ["-c", probe, catalogPath], {
    cwd, windowsHide: true, maxBuffer: 2_000_000,
    env: {
      ...env,
      PYTHONHOME: pythonRoot,
      PYTHONPATH: "",
      PYTHONNOUSERSITE: "1",
      PYTHONDONTWRITEBYTECODE: "1",
    },
  });
  return JSON.parse(result.stdout.trim());
}

async function storageEnvironment(testRoot, name) {
  const base = join(testRoot, name);
  const paths = {
    userData: join(base, "Electron UserData"), local: join(base, "Local AppData"), roaming: join(base, "Roaming AppData"),
    profile: join(base, "User Profile"), temp: join(base, "Temp"), evidence: join(base, "Evidence"),
  };
  await Promise.all(Object.values(paths).map((path) => mkdir(path, { recursive: true })));
  const env = { ...process.env };
  for (const key of [
    "V3_BACKEND_PYTHON", "V3_PYTHON", "V3_BACKEND_WORKING_DIRECTORY", "V3_PACKAGED_PYTHON_ROOT", "V3_PRODUCT_STORAGE_ROOT",
    "V3_RESEARCH_PACKAGE_TRANSPORT_PATH", "V3_AGENT_EVIDENCE_MODE", "PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE", "NODE_PATH",
    "npm_config_prefix", "ELECTRON_RUN_AS_NODE", "VIRTUAL_ENV", "V3_PRODUCT_CLOSURE_PROVIDER_MODE",
  ]) delete env[key];
  delete env.PATH; delete env.Path;
  env.Path = join(process.env.SystemRoot ?? "C:\\Windows", "System32");
  env.SystemRoot = process.env.SystemRoot ?? "C:\\Windows";
  env.APPDATA = paths.roaming; env.LOCALAPPDATA = paths.local; env.USERPROFILE = paths.profile; env.TEMP = paths.temp; env.TMP = paths.temp;
  env.V3_PACKAGED_SMOKE_USER_DATA = paths.userData;
  return { paths, env };
}

assert((await stat(packageRoot)).isDirectory(), `package root missing: ${packageRoot}`);
const runtimeManifestPath = join(packageRoot, "resources/backend-runtime/runtime-manifest.json");
const runtimeManifest = JSON.parse(await readFile(runtimeManifestPath, "utf8"));
assert(runtimeManifest.product?.version === "1.0.0", "runtime manifest is not V1.0.0");
assert(runtimeManifest.python_runtime?.version === "3.14.5", "runtime manifest CPython mismatch");
assert(runtimeManifest.real_free_source?.package_version === "1.18.84", "runtime manifest AKShare mismatch");

const testRoot = await mkdtemp(join(tmpdir(), "v3-v1-release-"));
const installRoot = join(testRoot, "Fresh Copied V3 Product With Spaces");
await cp(packageRoot, installRoot, { recursive: true });
const executable = join(installRoot, "v3-quant-workbench.exe");
const installBefore = await directoryIdentity(installRoot);
const success = await storageEnvironment(testRoot, "Success Persistence");
const runs = [];
for (const [phase, name] of [["create-submit", "first"], ["reopen-discover", "reopen"]]) {
  const output = join(success.paths.evidence, `${name}.json`);
  const run = await runProduct(executable, installRoot, success.env, phase, "DETERMINISTIC_SUCCESS", output);
  const smoke = JSON.parse(await readFile(output, "utf8"));
  assertRun(run, smoke, phase, "DETERMINISTIC_SUCCESS");
  runs.push({ phase, run, smoke });
}
const before = canonicalIdentity(runs[0].smoke);
const after = canonicalIdentity(runs[1].smoke);
assert(JSON.stringify(before) === JSON.stringify(after), "cold rediscovery identities/hashes are not exactly equal");
assert(runs[1].smoke.flow.rendererEvidence.initialRendererState.lastResearch === null, "new renderer initial state was not empty");
assert(runs[1].smoke.flow.rendererEvidence.currentRendererState.researchDiscoveryState === "RECOVERED", "new store did not use canonical TaskService discovery");

const pythonRoot = join(installRoot, "resources/backend-runtime/python");
const pythonPath = join(pythonRoot, "python.exe");
const backendRoot = join(installRoot, "resources/backend-runtime/backend-package");
const successCatalog = join(success.paths.local, "v3-quant-workbench/product/catalog.sqlite3");
const persisted = await catalogEvidence(pythonPath, pythonRoot, successCatalog, backendRoot, success.env);
assert(persisted.source_metadata?.source_kind === "TEST_EXTERNAL_PROVIDER_BOUNDARY", "deterministic data was not explicitly classified test-only");
assert(persisted.counts.task === 1 && persisted.counts.run >= 1 && persisted.counts.result >= 1 && persisted.counts.raw_capture === 1 && persisted.counts.artifact >= 1, "successful canonical chain was not persisted");

const unavailable = await storageEnvironment(testRoot, "Unavailable Fail Closed");
const unavailableOutput = join(unavailable.paths.evidence, "unavailable.json");
const unavailableRun = await runProduct(executable, installRoot, unavailable.env, "provider-unavailable", "DETERMINISTIC_UNAVAILABLE", unavailableOutput);
const unavailableSmoke = JSON.parse(await readFile(unavailableOutput, "utf8"));
assertRun(unavailableRun, unavailableSmoke, "provider-unavailable", "DETERMINISTIC_UNAVAILABLE");
assert(unavailableSmoke.flow.tasks.length === 0 && unavailableSmoke.flow.successful_canonical_chain_count === 0, "provider unavailable minted a Task chain");
assert(unavailableSmoke.flow.rendererEvidence.currentRendererState.errorMessage.includes("PROVIDER_ACQUISITION_UNAVAILABLE"), "provider unavailable error is not explicit");
const unavailableCatalog = join(unavailable.paths.local, "v3-quant-workbench/product/catalog.sqlite3");
const failed = await catalogEvidence(pythonPath, pythonRoot, unavailableCatalog, backendRoot, unavailable.env);
assert(failed.counts.task === 0 && failed.counts.run === 0 && failed.counts.result === 0 && failed.counts.raw_capture === 0, "provider unavailable created fake canonical market/research data");
assert(failed.counts.artifact === 1 && JSON.stringify(failed.artifact_roles) === JSON.stringify(["DATA_TRUTH_CAPABILITY_POLICY"]), "provider unavailable created an artifact other than the real admission policy");

const installAfter = await directoryIdentity(installRoot);
assert(JSON.stringify(installBefore) === JSON.stringify(installAfter), "packaged install tree mutated during acceptance");
const report = {
  schema_version: "v3.v1-product-release-e2e/1.0.0",
  result: "PASS_CANDIDATE",
  product_version: "1.0.0",
  runtime_manifest_sha256: await fileSha(runtimeManifestPath),
  package_identity_before: installBefore,
  package_identity_after: installAfter,
  deterministic_provider_boundary: "TEST_EXTERNAL_PROVIDER_BOUNDARY",
  canonical_identity_before_exit: before,
  canonical_identity_after_cold_restart: after,
  cold_rediscovery_exact_equality: true,
  new_process: true,
  new_renderer: true,
  new_store_instance: true,
  history_discovery_operation: "TaskService.v1.listTasks",
  known_id_injection: false,
  history_shadow_store: false,
  successful_persistence_counts: persisted.counts,
  provider_unavailable: {
    status: "PASS_FAIL_CLOSED",
    reason_code: "PROVIDER_ACQUISITION_UNAVAILABLE",
    retry_later: true,
    canonical_counts: failed.counts,
    artifact_roles: failed.artifact_roles,
    fallback_used: false,
  },
  full_app_exit: true,
  backend_exit: "GRACEFUL_SHUTDOWN_SUCCESS",
  orphan_process_count: 0,
  runs,
  unavailable_run: { run: unavailableRun, smoke: unavailableSmoke },
};
await mkdir(dirname(reportPath), { recursive: true });
await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
console.log(JSON.stringify(report, null, 2));
