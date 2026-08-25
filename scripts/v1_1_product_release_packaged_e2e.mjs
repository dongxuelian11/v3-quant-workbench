import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { cp, mkdir, mkdtemp, readFile, readdir, stat, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { tmpdir } from "node:os";

// This driver is executed by the transferred Electron binary in Node mode.
// Its package-copy and identity checks need the archive itself as a raw file.
process.noAsar = true;

const root = resolve(import.meta.dirname, "..");
const packageRoot = resolve(process.env.V3_PACKAGE_ROOT ?? join(root, "artifacts/package/win-unpacked"));
const reportPath = resolve(process.env.V3_PRODUCT_RELEASE_REPORT ?? join(root, "artifacts/package/V3_V1_1_PRODUCT_RELEASE_E2E.json"));
let expectedVersion = process.env.V3_PRODUCT_VERSION;

function assert(condition, message) {
  if (!condition) throw new Error(`V1_1_PRODUCT_RELEASE_E2E_FAILED: ${message}`);
}

function isoDate(date) {
  return date.toISOString().slice(0, 10);
}

function nextUtcDate(date) {
  return new Date(date.getTime() + 86_400_000);
}

function formatNumber(value) {
  return Number(value.toFixed(8)).toString();
}

function journeyACsv() {
  const rows = ["symbol,date,open,high,low,close,volume,amount"];
  const start = new Date("2018-01-01T00:00:00Z");
  const end = new Date("2026-09-30T00:00:00Z");
  const jump = new Date("2026-08-20T00:00:00Z");
  for (let cursor = start; cursor <= end; cursor = nextUtcDate(cursor)) {
    const price = cursor < jump ? 100 : 200;
    const volume = 10_000;
    rows.push(`600519,${isoDate(cursor)},${price},${price},${price},${price},${volume},${price * volume}`);
  }
  return `${rows.join("\n")}\n`;
}

function journeyBCsvAndReference() {
  const rows = ["symbol,date,open,high,low,close,volume,amount"];
  const sessions = [];
  const prices = new Map();
  const start = new Date("2026-01-01T00:00:00Z");
  for (let day = 0; day < 30; day += 1) {
    const sessionDate = isoDate(new Date(start.getTime() + day * 86_400_000));
    sessions.push(sessionDate);
    const bySymbol = new Map();
    for (let index = 0; index < 20; index += 1) {
      const symbol = String(600000 + index).padStart(6, "0");
      const price = 100 + index * 2 + day * (0.1 + index * 0.02);
      const volume = 10_000;
      bySymbol.set(symbol, price);
      rows.push([
        symbol,
        sessionDate,
        formatNumber(price),
        formatNumber(price),
        formatNumber(price),
        formatNumber(price),
        volume,
        formatNumber(price * volume),
      ].join(","));
    }
    prices.set(sessionDate, bySymbol);
  }
  const formationDate = sessions[0];
  const labelDate = sessions[5];
  const samples = [...prices.get(formationDate).entries()].map(([symbol, factor]) => ({
    symbol,
    factor,
    forwardReturn: prices.get(labelDate).get(symbol) / factor - 1,
  }));
  const pearson = (left, right) => {
    const leftMean = left.reduce((sum, value) => sum + value, 0) / left.length;
    const rightMean = right.reduce((sum, value) => sum + value, 0) / right.length;
    let covariance = 0;
    let leftSquares = 0;
    let rightSquares = 0;
    for (let index = 0; index < left.length; index += 1) {
      const a = left[index] - leftMean;
      const b = right[index] - rightMean;
      covariance += a * b;
      leftSquares += a * a;
      rightSquares += b * b;
    }
    return covariance / Math.sqrt(leftSquares * rightSquares);
  };
  const ranks = (values) => values
    .map((value, index) => ({ value, index }))
    .sort((left, right) => left.value - right.value || left.index - right.index)
    .reduce((result, item, rank) => { result[item.index] = rank + 1; return result; }, Array(values.length));
  const factorValues = samples.map((item) => item.factor);
  const returnValues = samples.map((item) => item.forwardReturn);
  const ordered = [...samples].sort((left, right) => left.factor - right.factor || left.symbol.localeCompare(right.symbol));
  const quantileReturns = Array.from({ length: 5 }, (_unused, index) => {
    const bucket = ordered.slice(index * 4, index * 4 + 4);
    return bucket.reduce((sum, item) => sum + item.forwardReturn, 0) / bucket.length;
  });
  return {
    csv: `${rows.join("\n")}\n`,
    reference: {
      formation_date: formationDate,
      label_date: labelDate,
      sample_size: 20,
      ic: pearson(factorValues, returnValues),
      rank_ic: pearson(ranks(factorValues), ranks(returnValues)),
      quantile_returns: quantileReturns,
      long_short_spread: quantileReturns[4] - quantileReturns[0],
    },
  };
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
  try { process.kill(pid, 0); return true; } catch (error) { return !["ESRCH", "ENOENT"].includes(error?.code); }
}

async function storageEnvironment(testRoot, name, localDataPath) {
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
  env.V3_PRODUCT_V1_1_SMOKE_LOCAL_DATA_SOURCE = localDataPath;
  return { paths, env };
}

function runProduct(executable, cwd, env, phase, outputPath) {
  return new Promise((resolveRun, rejectRun) => {
    const child = spawn(executable, ["--v3-product-closure-smoke", "--disable-gpu", "--disable-gpu-compositing", "--in-process-gpu"], {
      cwd,
      env: { ...env, V3_PRODUCT_CLOSURE_SMOKE_PHASE: phase, V3_PRODUCT_CLOSURE_SMOKE_OUTPUT: outputPath },
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8"); child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    const timeoutMs = Number(process.env.V3_PRODUCT_RELEASE_PHASE_TIMEOUT_MS ?? 360_000);
    const timer = setTimeout(() => {
      child.kill();
      rejectRun(new Error(`${phase} timed out after ${timeoutMs}ms\nSTDOUT:\n${stdout}\nSTDERR:\n${stderr}`));
    }, timeoutMs);
    child.on("error", (error) => { clearTimeout(timer); rejectRun(error); });
    child.on("exit", (code, signal) => { clearTimeout(timer); resolveRun({ code, signal, stdout, stderr, pid: child.pid ?? null }); });
  });
}

function assertRun(run, smoke, phase) {
  assert(run.code === 0 && run.signal === null, `${phase} exit=${run.code}/${run.signal}\n${run.stderr}`);
  assert(
    smoke.success === true && smoke.app_is_packaged === true && smoke.backend_runtime_mode === "PACKAGED",
    `${phase} did not prove packaged success\nSTDOUT:\n${run.stdout}\nSTDERR:\n${run.stderr}`,
  );
  assert(smoke.flow?.status?.productVersion === expectedVersion, `${phase} product version mismatch`);
  assert(smoke.provider_boundary === "LOCAL_USER_SUPPLIED", `${phase} source boundary is not LOCAL_USER_SUPPLIED`);
  assert(smoke.source_truth_ceiling === "PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE", `${phase} truth ceiling drifted`);
  assert(run.stderr.includes("PACKAGED_RUNTIME_SELECTED") && run.stderr.includes("GRACEFUL_SHUTDOWN_SUCCESS"), `${phase} did not prove packaged selection and graceful shutdown`);
  assert(!run.stderr.includes("FORCED_SHUTDOWN_FALLBACK"), `${phase} used forced shutdown fallback`);
  assert(!processAlive(Number(smoke.backend_pid)), `${phase} left backend PID ${smoke.backend_pid}`);
}

function assertVisualRun(run, smoke, phase) {
  assert(run.code === 0 && run.signal === null, `${phase} exit=${run.code}/${run.signal}\n${run.stderr}`);
  assert(smoke.success === true && smoke.app_is_packaged === true && smoke.backend_runtime_mode === "PACKAGED", `${phase} did not prove packaged success`);
  assert(smoke.provider_boundary === "LOCAL_USER_SUPPLIED", `${phase} source boundary is not LOCAL_USER_SUPPLIED`);
  assert(smoke.flow?.evidence_class === "EMULATED_ELECTRON_ZOOM_NOT_PHYSICAL_WINDOWS_SCALING", `${phase} scaling evidence was overstated`);
  assert(smoke.flow?.physical_windows_scaling === "NOT_RUN", `${phase} physical Windows scaling must remain NOT_RUN`);
  assert(smoke.flow?.user_visual_acceptance === "PENDING_USER_REVIEW", `${phase} user visual acceptance must remain pending`);
  assert(smoke.flow?.matrix_case_count === 12 && smoke.flow?.screenshot_count === 60, `${phase} matrix is incomplete`);
  assert(smoke.flow?.machine_baseline === "PASS" && smoke.flow?.failures?.length === 0, `${phase} machine visual/accessibility baseline failed: ${JSON.stringify(smoke.flow?.failures)}`);
  assert(run.stderr.includes("PACKAGED_RUNTIME_SELECTED") && run.stderr.includes("GRACEFUL_SHUTDOWN_SUCCESS"), `${phase} did not prove packaged selection and graceful shutdown`);
  assert(!processAlive(Number(smoke.backend_pid)), `${phase} left backend PID ${smoke.backend_pid}`);
}

function journeyIdentity(smoke, journey) {
  const flow = smoke.flow;
  const home = flow.home;
  const evidence = flow.rendererEvidence;
  const base = {
    project_id: home.projectId,
    project_context_revision_id: home.projectContextRevisionId,
    snapshot_id: home.data.snapshotId,
    universe_version_id: home.data.universeVersionId,
    formula_document_version_id: home.factor.formulaDocumentVersionId,
    analysis_artifact_id: home.factor.analysisArtifactId,
    factor_outputs: home.factor.outputs.map((item) => [item.name, item.factorDefinitionVersionId, item.materializationId]),
  };
  if (journey === "B") return base;
  assert(home.backtest.resultState === "VALID" && evidence.result.resultState === "VALID", "Journey A did not expose a VALID Result");
  assert(evidence.result.orderCount > 0 && evidence.result.fillCount > 0, "Journey A did not expose orders/fills");
  return {
    ...base,
    research_strategy_spec_id: home.strategy.researchStrategySpecId,
    result_id: home.backtest.resultId,
    backtest_result_id: home.backtest.backtestResultId,
    analytics_id: home.backtest.analyticsId,
    result_lineage_id: home.backtest.resultLineageId,
    result_artifact_id: home.backtest.resultArtifactId,
    analytics_artifact_id: home.backtest.analyticsArtifactId,
    lineage_artifact_id: home.backtest.lineageArtifactId,
  };
}

function assertClose(actual, expected, label, tolerance = 1e-12) {
  assert(Number.isFinite(actual) && Math.abs(actual - expected) <= tolerance, `${label} mismatch: actual=${actual} expected=${expected}`);
}

function assertJourneyBReference(smoke, expected) {
  const daily = smoke.flow.home.factor.analysis.dailyResults.find((item) => item.sessionDate === expected.formation_date);
  assert(daily?.status === "AVAILABLE" && daily.labelSessionDate === expected.label_date && daily.sampleSize === expected.sample_size, "Journey B independent-reference date/sample binding drifted");
  assertClose(daily.ic.value, expected.ic, "Journey B daily IC");
  assertClose(daily.rankIc.value, expected.rank_ic, "Journey B daily RankIC");
  assert(Array.isArray(daily.quantileReturns) && daily.quantileReturns.length === 5, "Journey B quantile returns are unavailable");
  daily.quantileReturns.forEach((value, index) => assertClose(value, expected.quantile_returns[index], `Journey B quantile ${index + 1}`));
  assertClose(daily.longShortSpread, expected.long_short_spread, "Journey B long-short spread");
}

assert((await stat(packageRoot)).isDirectory(), `package root missing: ${packageRoot}`);
const runtimeManifestPath = join(packageRoot, "resources/backend-runtime/runtime-manifest.json");
const runtimeManifest = JSON.parse(await readFile(runtimeManifestPath, "utf8"));
const runtimeVersion = String(runtimeManifest.product?.version ?? "");
assert(runtimeVersion.length > 0, "runtime manifest product version is missing");
assert(expectedVersion === undefined || expectedVersion === runtimeVersion, "runtime manifest product version does not match V3_PRODUCT_VERSION");
expectedVersion = expectedVersion ?? runtimeVersion;
assert(runtimeManifest.python_runtime?.version === "3.14.5", "runtime manifest CPython mismatch");

const tempParent = resolve(process.env.V3_C4_TEMP_ROOT ?? tmpdir());
await mkdir(tempParent, { recursive: true });
const testRoot = await mkdtemp(join(tempParent, "v3-v1-1-release-"));
const sourceRoot = join(testRoot, "User Supplied Data");
await mkdir(sourceRoot, { recursive: true });
const journeyAPath = join(sourceRoot, "journey-a-600519.csv");
const journeyBPath = join(sourceRoot, "journey-b-20-symbols.csv");
const journeyB = journeyBCsvAndReference();
await writeFile(journeyAPath, journeyACsv(), "utf8");
await writeFile(journeyBPath, journeyB.csv, "utf8");

const installRoot = join(testRoot, "Fresh Copied V3 V1.1 Product With Spaces");
await cp(packageRoot, installRoot, { recursive: true });
const executable = join(installRoot, "v3-quant-workbench.exe");
const installBefore = await directoryIdentity(installRoot);
const journeys = {};
for (const [journey, localDataPath] of [["A", journeyAPath], ["B", journeyBPath]]) {
  const storage = await storageEnvironment(testRoot, `Journey ${journey} Persistence`, localDataPath);
  const phases = journey === "A"
    ? ["v1-1-journey-a-create", "v1-1-journey-a-reopen", "v1-1-journey-a-visual"]
    : ["v1-1-journey-b-create", "v1-1-journey-b-reopen"];
  const runs = [];
  for (const phase of phases) {
    const output = join(storage.paths.evidence, `${phase}.json`);
    const run = await runProduct(executable, installRoot, storage.env, phase, output);
    const smoke = JSON.parse(await readFile(output, "utf8"));
    if (phase.endsWith("-visual")) assertVisualRun(run, smoke, phase);
    else assertRun(run, smoke, phase);
    runs.push({ phase, smoke, process: { code: run.code, signal: run.signal, pid: run.pid, stderr: run.stderr } });
  }
  const before = journeyIdentity(runs[0].smoke, journey);
  const after = journeyIdentity(runs[1].smoke, journey);
  assert(JSON.stringify(before) === JSON.stringify(after), `Journey ${journey} canonical identities changed after cold restart`);
  if (journey === "B") {
    assertJourneyBReference(runs[0].smoke, journeyB.reference);
    assertJourneyBReference(runs[1].smoke, journeyB.reference);
  }
  journeys[journey] = {
    source_file_name: localDataPath.split(/[\\/]/).at(-1),
    source_file_sha256: createHash("sha256").update(await readFile(localDataPath)).digest("hex"),
    storage_roots: storage.paths,
    canonical_identity_before_exit: before,
    canonical_identity_after_restart: after,
    cold_rediscovery_exact_equality: true,
    independent_reference: journey === "B" ? journeyB.reference : null,
    runs,
  };
}

const installAfter = await directoryIdentity(installRoot);
assert(JSON.stringify(installBefore) === JSON.stringify(installAfter), "packaged install tree mutated during V1.1 acceptance");
const report = {
  schema_version: "v3.v1-1-product-release-e2e/1.0.0",
  result: "PASS_CANDIDATE",
  product_version: expectedVersion,
  runtime_manifest_sha256: createHash("sha256").update(await readFile(runtimeManifestPath)).digest("hex"),
  package_identity_before: installBefore,
  package_identity_after: installAfter,
  source_boundary: "LOCAL_USER_SUPPLIED",
  truth: "NOT_FORMAL",
  admission: "PRE_ALPHA",
  maturity: "PRODUCT_CONNECTED",
  packaged_runtime: "PASS",
  full_app_exit: true,
  backend_exit: "GRACEFUL_SHUTDOWN_SUCCESS",
  orphan_process_count: 0,
  journeys,
};
await mkdir(dirname(reportPath), { recursive: true });
await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
console.log(JSON.stringify({
  result: report.result,
  product_version: expectedVersion,
  package_identity: installAfter,
  journey_a: journeys.A.canonical_identity_after_restart,
  journey_b: journeys.B.canonical_identity_after_restart,
  journey_b_reference: journeyB.reference,
}, null, 2));
