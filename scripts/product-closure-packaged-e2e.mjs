import { createHash } from "node:crypto";
import { cp, mkdir, mkdtemp, readdir, readFile, stat, writeFile } from "node:fs/promises";
import { execFile, spawn } from "node:child_process";
import { promisify } from "node:util";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { tmpdir } from "node:os";

const execFileAsync = promisify(execFile);
const root = resolve(import.meta.dirname, "..");
const sourcePackageRoot = resolve(process.env.V3_PACKAGE_ROOT ?? join(root, "artifacts/package/win-unpacked"));
const reportPath = resolve(process.env.V3_PRODUCT_CLOSURE_REPORT ?? join(root, "artifacts/package/V3_V1_PRODUCT_CLOSURE_PRIMARY_E2E.json"));

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function inside(parent, candidate) {
  const child = relative(resolve(parent), resolve(candidate));
  return child === "" || (child !== ".." && !child.startsWith(".." + sep) && !isAbsolute(child));
}

async function fileSha(path) {
  return createHash("sha256").update(await readFile(path)).digest("hex");
}

async function directoryIdentity(directory, prefix = "") {
  const entries = (await readdir(directory, { withFileTypes: true }))
    .sort((left, right) => left.name.localeCompare(right.name));
  const digest = createHash("sha256");
  let bytes = 0;
  let files = 0;
  for (const entry of entries) {
    const absolute = join(directory, entry.name);
    const name = prefix ? prefix + "/" + entry.name : entry.name;
    if (entry.isDirectory()) {
      const nested = await directoryIdentity(absolute, name);
      bytes += nested.bytes;
      files += nested.files;
      digest.update(nested.sha256);
    } else if (entry.isFile()) {
      const content = await readFile(absolute);
      bytes += content.byteLength;
      files += 1;
      digest.update(name.replaceAll("\\", "/"));
      digest.update("\0");
      digest.update(content);
      digest.update("\0");
    }
  }
  return { bytes, files, sha256: digest.digest("hex") };
}

function processAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    const code = error && typeof error === "object" ? error.code : undefined;
    if (code === "ESRCH" || code === "ENOENT") return false;
    return true;
  }
}

function runProduct(executable, cwd, env, phase, outputPath) {
  return new Promise((resolveRun, rejectRun) => {
    const child = spawn(executable, [
      "--v3-product-closure-smoke",
      "--disable-gpu",
      "--disable-gpu-compositing",
      "--in-process-gpu"
    ], {
      cwd,
      env: {
        ...env,
        V3_PRODUCT_CLOSURE_SMOKE_PHASE: phase,
        V3_PRODUCT_CLOSURE_SMOKE_OUTPUT: outputPath
      },
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"]
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    const timeout = setTimeout(() => {
      child.kill();
      rejectRun(new Error(phase + " packaged product did not exit within 240 seconds"));
    }, 240_000);
    child.on("error", (error) => {
      clearTimeout(timeout);
      rejectRun(error);
    });
    child.on("exit", (code, signal) => {
      clearTimeout(timeout);
      resolveRun({ code, signal, stdout, stderr, pid: child.pid ?? null });
    });
  });
}

async function readJson(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

function assertSmokeRun(run, smoke, phase) {
  assert(run.code === 0 && run.signal === null, phase + " packaged product exit failed: " + run.code + "/" + run.signal + "\n" + run.stderr);
  assert(smoke.success === true, phase + " packaged product reported failure: " + JSON.stringify(smoke) + "\n" + run.stderr);
  assert(smoke.app_is_packaged === true && smoke.backend_runtime_mode === "PACKAGED", phase + " did not run packaged runtime");
  assert(smoke.known_id_injection === false, phase + " reported known-ID injection");
  assert(run.stderr.includes("PRODUCT_CLOSURE_PACKAGED_SMOKE_PASS"), phase + " did not report product closure pass");
  assert(run.stderr.includes("PACKAGED_RUNTIME_SELECTED"), phase + " did not select packaged backend runtime");
  assert(run.stderr.includes("GRACEFUL_SHUTDOWN_SUCCESS"), phase + " did not complete graceful shutdown");
  assert(!run.stderr.includes("FORCED_SHUTDOWN_FALLBACK"), phase + " used forced shutdown fallback");
  if (smoke.backend_pid !== null) {
    assert(!processAlive(Number(smoke.backend_pid)), phase + " backend process remained alive: " + smoke.backend_pid);
  }
}

function canonicalIdentity(smoke, phase) {
  const flow = smoke.flow;
  const context = flow?.projectContext;
  const task = flow?.task;
  const result = flow?.result;
  const artifact = flow?.artifactDescriptor;
  assert(context && typeof context.projectId === "string" && typeof context.projectContextRevisionId === "string", phase + " project context is incomplete");
  assert(task && task.state === "SUCCEEDED" && typeof task.taskId === "string" && typeof task.runId === "string" && typeof task.resultId === "string", phase + " canonical Task is incomplete");
  assert(result && result.state === "SUCCEEDED" && result.resultId === task.resultId && result.backtestRunId === task.runId, phase + " canonical Result does not match Task");
  assert(artifact && typeof artifact.artifactId === "string" && typeof artifact.sha256 === "string" && Number.isInteger(artifact.byteSize), phase + " canonical Artifact descriptor is incomplete");
  assert(task.projectId === context.projectId && result.projectId === context.projectId, phase + " Project identity does not propagate to Task/Result");
  assert(task.outputs?.BACKTEST_RUN_RESULT === artifact.artifactId, phase + " Task output is not the canonical Result Artifact");
  assert(result.resultArtifact?.artifactId === artifact.artifactId && result.resultArtifact?.sha256 === artifact.sha256 && result.resultArtifact?.byteSize === artifact.byteSize, phase + " Result Artifact does not exactly match descriptor");
  return {
    projectId: context.projectId,
    projectContextRevisionId: context.projectContextRevisionId,
    taskId: task.taskId,
    runId: task.runId,
    resultId: result.resultId,
    resultArtifactId: artifact.artifactId,
    resultArtifactSha256: artifact.sha256,
    resultArtifactByteSize: artifact.byteSize
  };
}

function assertEqualIdentity(before, after) {
  for (const field of ["projectId", "projectContextRevisionId", "taskId", "runId", "resultId", "resultArtifactId", "resultArtifactSha256", "resultArtifactByteSize"]) {
    assert(before[field] === after[field], "cold restart identity mismatch for " + field + ": " + before[field] + " != " + after[field]);
  }
}

async function queryPackagedSourceEvidence(pythonPath, pythonRoot, catalogPath, cwd, env) {
  const probe = [
    "import json, sqlite3, sys",
    "connection = sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True)",
    "connection.row_factory = sqlite3.Row",
    "query = 'SELECT r.raw_capture_id, r.connector_version_id, r.provider_dataset, r.effective_range_start, r.effective_range_end, r.available_time, r.captured_at, r.ingested_at, r.artifact_id, r.content_hash, r.state, t.provider_id, t.source_metadata_json, t.provenance_complete FROM raw_capture r JOIN raw_capture_truth_descriptor t ON t.raw_capture_id = r.raw_capture_id ORDER BY r.captured_at DESC'",
    "for row in connection.execute(query):",
    "    metadata_value = row['source_metadata_json']",
    "    metadata = json.loads(metadata_value) if isinstance(metadata_value, str) else metadata_value",
    "    request = metadata.get('request', {}) if isinstance(metadata, dict) else {}",
    "    if row['provider_id'] != 'pvd_akshare_eastmoney_a_share_eod_v1': continue",
    "    if row['connector_version_id'] != 'cov_akshare_eod_research_v1' or row['provider_dataset'] != 'CN_A_SHARE_EOD': continue",
    "    if request.get('symbol') != '600519' or request.get('start_date') != '20250701' or request.get('end_date') != '20250710': continue",
    "    print(json.dumps({'raw_capture_id': row['raw_capture_id'], 'provider_id': row['provider_id'], 'connector_version_id': row['connector_version_id'], 'provider_dataset': row['provider_dataset'], 'requested_start': request.get('start_date'), 'requested_end': request.get('end_date'), 'captured_at': row['captured_at'], 'acquired_at': metadata.get('acquired_at'), 'available_time': row['available_time'], 'available_time_evidence': metadata.get('available_time_evidence'), 'provider_revision_id': None, 'revision_evidence': metadata.get('revision_evidence'), 'provider_package_version': metadata.get('provider_package_version'), 'provider_repository_revision': metadata.get('provider_repository_revision'), 'raw_payload_sha256': row['content_hash'], 'raw_capture_id_from_hash': 'raw_sha256_' + row['content_hash'], 'source_artifact_id': row['artifact_id'], 'source_artifact_id_from_hash': 'art_sha256_' + row['content_hash'], 'state': row['state'], 'provenance_complete': row['provenance_complete'], 'record_request': request}, ensure_ascii=False))",
    "    break",
    "else:",
    "    raise SystemExit('no matching canonical AKShare raw capture was persisted')",
    "connection.close()"
  ].join("\n");
  const result = await execFileAsync(pythonPath, ["-c", probe, catalogPath], {
    cwd,
    windowsHide: true,
    maxBuffer: 2_000_000,
    env: { ...env, PYTHONHOME: pythonRoot, PYTHONPATH: "", PYTHONNOUSERSITE: "1" }
  });
  return JSON.parse(result.stdout.trim());
}

const packageInfo = await stat(sourcePackageRoot);
assert(packageInfo.isDirectory(), "packaged artifact missing: " + sourcePackageRoot);
const manifestPath = join(sourcePackageRoot, "resources", "backend-runtime", "runtime-manifest.json");
const sourceManifest = await readJson(manifestPath);
assert(sourceManifest.first_launch_network_install === false, "packaged runtime permits first-launch network install");
assert(sourceManifest.source_capability === "NOT_AVAILABLE", "packaged runtime source capability truth changed from NOT_AVAILABLE");
assert(sourceManifest.real_free_source?.provider_id === "pvd_akshare_eastmoney_a_share_eod_v1", "packaged AKShare provider metadata missing");
assert(sourceManifest.real_free_source?.package_version === "1.18.84", "packaged AKShare version metadata missing");
assert(sourceManifest.real_free_source?.endpoint === "stock_zh_a_hist", "packaged AKShare endpoint metadata missing");
assert(sourceManifest.real_free_source?.truth_state === "DEMO" && sourceManifest.real_free_source?.maturity === "PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE", "packaged source maturity metadata overclaims");

const testRoot = await mkdtemp(join(tmpdir(), "v3-product-closure-"));
const installRoot = join(testRoot, "Fresh Extracted V3 Product With Spaces");
const userDataRoot = join(testRoot, "Fresh Electron UserData");
const localAppDataRoot = join(testRoot, "Fresh Local AppData");
const roamingRoot = join(testRoot, "Fresh Roaming AppData");
const profileRoot = join(testRoot, "Fresh User Profile");
const tempRoot = join(testRoot, "Fresh Temp");
const evidenceRoot = join(testRoot, "Evidence");
await mkdir(installRoot, { recursive: true });
await mkdir(userDataRoot);
await mkdir(localAppDataRoot);
await mkdir(roamingRoot);
await mkdir(profileRoot);
await mkdir(tempRoot);
await mkdir(evidenceRoot, { recursive: true });
await cp(sourcePackageRoot, installRoot, { recursive: true });
const executable = join(installRoot, "v3-quant-workbench.exe");
assert((await stat(executable)).isFile(), "packaged Electron executable missing after copy");
const installBefore = await directoryIdentity(installRoot);

const runtimeEnvBase = { ...process.env };
for (const key of [
  "V3_BACKEND_PYTHON", "V3_PYTHON", "V3_BACKEND_WORKING_DIRECTORY", "V3_PACKAGED_PYTHON_ROOT", "PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE",
  "NODE_PATH", "npm_config_prefix", "ELECTRON_RUN_AS_NODE", "V3_PRODUCT_STORAGE_ROOT", "V3_RESEARCH_PACKAGE_TRANSPORT_PATH", "V3_AGENT_EVIDENCE_MODE",
  "V3_PACKAGED_SMOKE_PHASE", "V3_PACKAGED_SMOKE_OUTPUT", "V3_PRODUCT_CLOSURE_SMOKE_PHASE", "V3_PRODUCT_CLOSURE_SMOKE_OUTPUT"
]) delete runtimeEnvBase[key];
delete runtimeEnvBase.Path;
delete runtimeEnvBase.PATH;
runtimeEnvBase.Path = join(process.env.SystemRoot ?? "C:\\Windows", "System32");
runtimeEnvBase.SystemRoot = process.env.SystemRoot ?? "C:\\Windows";
runtimeEnvBase.APPDATA = roamingRoot;
runtimeEnvBase.LOCALAPPDATA = localAppDataRoot;
runtimeEnvBase.TEMP = tempRoot;
runtimeEnvBase.TMP = tempRoot;
runtimeEnvBase.USERPROFILE = profileRoot;
runtimeEnvBase.V3_PACKAGED_SMOKE_USER_DATA = userDataRoot;

const runs = [];
for (const [phase, name] of [["create-submit", "first"], ["reopen-discover", "relaunch"]]) {
  const outputPath = join(evidenceRoot, name + ".json");
  const productRun = await runProduct(executable, installRoot, runtimeEnvBase, phase, outputPath);
  const smoke = await readJson(outputPath);
  assertSmokeRun(productRun, smoke, phase);
  runs.push({ phase, product_run: productRun, smoke });
}

const first = runs[0].smoke;
const relaunch = runs[1].smoke;
const before = canonicalIdentity(first, "first");
const after = canonicalIdentity(relaunch, "relaunch");
assertEqualIdentity(before, after);
const firstEvidence = first.flow.rendererEvidence;
const secondEvidence = relaunch.flow.rendererEvidence;
assert(firstEvidence.currentRendererState.surface === "RESULT_AVAILABLE", "first renderer did not show RESULT_AVAILABLE");
assert(secondEvidence.initialRendererState.lastResearch === null && secondEvidence.initialRendererState.task === null && secondEvidence.initialRendererState.result === null && secondEvidence.initialRendererState.artifactDescriptor === null, "second renderer initial state was not empty");
assert(secondEvidence.currentRendererState.lastResearch === null, "cold renderer fabricated a submit outcome");
assert(secondEvidence.currentRendererState.researchDiscoveryState === "RECOVERED", "cold renderer did not report RECOVERED");
assert(secondEvidence.currentRendererState.recoveredResearchTaskId === after.taskId, "cold renderer recovered a different Task");
assert(secondEvidence.currentRendererState.surface === "RESULT_AVAILABLE", "cold renderer did not show RESULT_AVAILABLE");
assert(first.flow.projectContext.projectId === relaunch.flow.projectContext.projectId, "Project changed after full restart");
assert(first.flow.projectContext.projectContextRevisionId === relaunch.flow.projectContext.projectContextRevisionId, "Project context revision changed after full restart");

const pythonRoot = join(installRoot, "resources", "backend-runtime", "python");
const pythonPath = join(pythonRoot, "python.exe");
const catalogPath = join(localAppDataRoot, "v3-quant-workbench", "product", "catalog.sqlite3");
const sourceEvidence = await queryPackagedSourceEvidence(
  pythonPath,
  pythonRoot,
  catalogPath,
  join(installRoot, "resources", "backend-runtime", "backend-package"),
  runtimeEnvBase
);
assert(sourceEvidence.provider_package_version === "1.18.84", "persisted source evidence package version mismatch");
assert(sourceEvidence.provider_id === "pvd_akshare_eastmoney_a_share_eod_v1", "persisted source provider mismatch");
assert(sourceEvidence.connector_version_id === "cov_akshare_eod_research_v1", "persisted source connector mismatch");
assert(sourceEvidence.requested_start === "20250701" && sourceEvidence.requested_end === "20250710", "persisted source request range mismatch");
assert(Number.isInteger(sourceEvidence.provenance_complete) && sourceEvidence.provenance_complete === 0, "source provenance ceiling was not preserved as incomplete");
assert(sourceEvidence.available_time === null && sourceEvidence.available_time_evidence === "UNKNOWN", "source available-time truth was promoted");
assert(sourceEvidence.revision_evidence === "UNKNOWN" && sourceEvidence.provider_revision_id === null, "source revision truth was promoted");
assert(sourceEvidence.raw_capture_id === sourceEvidence.raw_capture_id_from_hash, "raw capture identity is not content-derived");
assert(sourceEvidence.source_artifact_id === sourceEvidence.source_artifact_id_from_hash, "raw source Artifact identity is not content-derived");

const installAfter = await directoryIdentity(installRoot);
assert(installBefore.sha256 === installAfter.sha256 && installBefore.bytes === installAfter.bytes && installBefore.files === installAfter.files, "packaged install tree changed during full restart flow");
const report = {
  schema_version: "v3.product-closure-packaged-e2e/1.0.0",
  result: "V3_V1_PRODUCT_CLOSURE_COMBINED_E2E_PASS_CANDIDATE",
  started_at: new Date().toISOString(),
  finished_at: new Date().toISOString(),
  artifact: {
    source_path: sourcePackageRoot,
    copied_install_path: installRoot,
    source_tree_sha256: installBefore.sha256,
    source_bytes: installBefore.bytes,
    source_file_count: installBefore.files,
    final_tree_sha256: installAfter.sha256,
    final_bytes: installAfter.bytes,
    final_file_count: installAfter.files,
    runtime_manifest_sha256: await fileSha(join(installRoot, "resources", "backend-runtime", "runtime-manifest.json"))
  },
  environment: {
    user_data_root: userDataRoot,
    local_app_data_root: localAppDataRoot,
    repo_hidden_from_runtime: true,
    developer_python_overrides_removed: true,
    node_modules_not_on_runtime_path: true
  },
  source_truth: {
    provider_id: sourceEvidence.provider_id,
    connector_version_id: sourceEvidence.connector_version_id,
    package_version: sourceEvidence.provider_package_version,
    endpoint: "stock_zh_a_hist",
    raw_capture_id: sourceEvidence.raw_capture_id,
    raw_payload_sha256: sourceEvidence.raw_payload_sha256,
    source_artifact_id: sourceEvidence.source_artifact_id,
    acquired_at: sourceEvidence.acquired_at ?? sourceEvidence.captured_at,
    requested_start: sourceEvidence.requested_start,
    requested_end: sourceEvidence.requested_end,
    provider_repository_revision: sourceEvidence.provider_repository_revision,
    available_time_evidence: sourceEvidence.available_time_evidence,
    revision_evidence: sourceEvidence.revision_evidence,
    maturity: "PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE"
  },
  primary_identity_before: before,
  primary_identity_after_restart: after,
  exact_identity_equality: true,
  full_electron_process_restart: true,
  new_renderer_store_on_relaunch: true,
  known_id_injection: false,
  automatic_history_discovery: true,
  result_surface_after_restart: "RESULT_AVAILABLE",
  runs,
  no_orphan_backend_processes_observed: true,
  source_capability: "NOT_AVAILABLE",
  research_maturity: "PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE",
  first_source_authority: "NOT_BROADLY_COMPLETE"
};
await mkdir(dirname(reportPath), { recursive: true });
await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
console.log(JSON.stringify(report, null, 2));
