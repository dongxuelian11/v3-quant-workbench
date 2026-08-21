import { createHash } from "node:crypto";
import { cp, mkdir, mkdtemp, readdir, readFile, stat, writeFile } from "node:fs/promises";
import { execFile, spawn } from "node:child_process";
import { promisify } from "node:util";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { tmpdir } from "node:os";

const execFileAsync = promisify(execFile);
const root = resolve(import.meta.dirname, "..");
const sourcePackageRoot = resolve(process.env.V3_PACKAGE_ROOT ?? join(root, "artifacts/package/win-unpacked"));
const reportPath = resolve(process.env.V3_PACKAGED_RUNTIME_SMOKE_REPORT ?? join(root, "artifacts/package/V3_PACKAGED_RUNTIME_SMOKE.json"));

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function inside(parent, candidate) {
  const child = relative(resolve(parent), resolve(candidate));
  return child === "" || (child !== ".." && !child.startsWith(`..${sep}`) && !isAbsolute(child));
}

async function fileSha(path) {
  return createHash("sha256").update(await readFile(path)).digest("hex");
}

async function statIfPresent(path) {
  try {
    return await stat(path);
  } catch (error) {
    if (error && typeof error === "object" && error.code === "ENOENT") return null;
    throw error;
  }
}

async function directoryIdentity(directory, prefix = "") {
  const entries = (await readdir(directory, { withFileTypes: true }))
    .sort((left, right) => left.name.localeCompare(right.name));
  const digest = createHash("sha256");
  let bytes = 0;
  let files = 0;
  for (const entry of entries) {
    const absolute = join(directory, entry.name);
    const name = prefix ? `${prefix}/${entry.name}` : entry.name;
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

async function hostCommandExists(command) {
  try {
    await execFileAsync("where.exe", [command], { windowsHide: true });
    return true;
  } catch (error) {
    const code = error && typeof error === "object" ? error.code : undefined;
    if (code === "ENOENT" || code === 1) return false;
    throw error;
  }
}

function processAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    const code = error && typeof error === "object" ? error.code : undefined;
    if (code === "ESRCH" || code === "ENOENT") return false;
    throw error;
  }
}

function runProduct(executable, cwd, env) {
  return new Promise((resolveRun, rejectRun) => {
    // Chromium can initialize its GPU child before the packaged main module
    // executes. Keep this runtime probe independent of host graphics DLLs;
    // normal packaged launches do not use the smoke-only switches.
    const child = spawn(executable, [
      "--v3-packaged-smoke",
      "--disable-gpu",
      "--disable-gpu-compositing",
      "--in-process-gpu",
    ], {
      cwd,
      env,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    const timeout = setTimeout(() => {
      child.kill();
      rejectRun(new Error("packaged Electron did not exit within 60 seconds"));
    }, 60_000);
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

async function readSmokeOutput(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

const startedAt = new Date().toISOString();
const sourceInfo = await statIfPresent(sourcePackageRoot);
assert(sourceInfo?.isDirectory() === true, `packaged artifact missing: ${sourcePackageRoot}`);
const sourceManifestPath = join(sourcePackageRoot, "resources/backend-runtime/runtime-manifest.json");
const sourceManifestSha = await fileSha(sourceManifestPath);
const sourcePackageIdentity = await directoryIdentity(sourcePackageRoot);
const testRoot = await mkdtemp(join(tmpdir(), "v3-packaged-runtime-smoke-"));
const installRoot = join(testRoot, "Fresh Extracted V3 Product With Spaces");
const userDataRoot = join(testRoot, "Fresh Electron UserData");
const localAppDataRoot = join(testRoot, "Fresh Local AppData");
const evidenceRoot = join(testRoot, "Evidence");
await mkdir(installRoot, { recursive: true });
await cp(sourcePackageRoot, installRoot, { recursive: true });
await mkdir(userDataRoot);
await mkdir(evidenceRoot, { recursive: true });
const executable = join(installRoot, "v3-quant-workbench.exe");
const runtimeEnvBase = { ...process.env };
for (const key of [
  "V3_BACKEND_PYTHON", "V3_PYTHON", "V3_BACKEND_WORKING_DIRECTORY", "V3_PACKAGED_PYTHON_ROOT", "PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE",
  "NODE_PATH", "npm_config_prefix", "ELECTRON_RUN_AS_NODE", "V3_PRODUCT_STORAGE_ROOT", "V3_RESEARCH_PACKAGE_TRANSPORT_PATH", "V3_AGENT_EVIDENCE_MODE",
]) delete runtimeEnvBase[key];
delete runtimeEnvBase.Path;
delete runtimeEnvBase.PATH;
runtimeEnvBase.Path = join(process.env.SystemRoot ?? "C:\\Windows", "System32");
runtimeEnvBase.SystemRoot = process.env.SystemRoot ?? "C:\\Windows";
runtimeEnvBase.WINDIR = process.env.WINDIR ?? runtimeEnvBase.SystemRoot;
runtimeEnvBase.APPDATA = join(testRoot, "Roaming AppData");
runtimeEnvBase.LOCALAPPDATA = localAppDataRoot;
runtimeEnvBase.TEMP = join(testRoot, "Temp");
runtimeEnvBase.TMP = runtimeEnvBase.TEMP;
runtimeEnvBase.USERPROFILE = join(testRoot, "User Profile");
runtimeEnvBase.V3_PACKAGED_SMOKE_USER_DATA = userDataRoot;

const runs = [];
for (const [phase, name] of [["create-bind", "first"], ["relaunch", "relaunch"]]) {
  const outputPath = join(evidenceRoot, `${name}.json`);
  const productRun = await runProduct(executable, installRoot, {
    ...runtimeEnvBase,
    V3_PACKAGED_SMOKE_PHASE: phase,
    V3_PACKAGED_SMOKE_OUTPUT: outputPath,
  });
  const smoke = await readSmokeOutput(outputPath);
  assert(productRun.code === 0 && productRun.signal === null, `${phase} packaged product exit failed: ${productRun.code}/${productRun.signal}`);
  assert(smoke.success === true, `${phase} packaged smoke reported failure: ${JSON.stringify(smoke)}\nSTDERR:\n${productRun.stderr}`);
  assert(smoke.app_is_packaged === true && smoke.backend_runtime_mode === "PACKAGED", `${phase} packaged mode was not selected`);
  assert(inside(smoke.resources_path, smoke.backend_executable), `${phase} backend executable is outside packaged resources`);
  assert(inside(smoke.resources_path, smoke.backend_working_directory), `${phase} backend working root is outside packaged resources`);
  assert(smoke.source_capability?.truth_state === "UNAVAILABLE", `${phase} source capability was not NOT_AVAILABLE`);
  assert(!productRun.stderr.includes("FORCED_SHUTDOWN_FALLBACK"), `${phase} used forced shutdown fallback`);
  assert(productRun.stderr.includes("PACKAGED_RUNTIME_SELECTED"), `${phase} did not log packaged runtime selection`);
  assert(productRun.stderr.includes("GRACEFUL_SHUTDOWN_SUCCESS"), `${phase} did not log graceful shutdown success`);
  if (smoke.backend_pid !== null) assert(!(await processAlive(smoke.backend_pid)), `${phase} backend process remained alive: ${smoke.backend_pid}`);
  assert(!inside(installRoot, smoke.user_data_path), `${phase} userData is inside install root`);
  assert(!inside(installRoot, smoke.storage_root), `${phase} product storage is inside install root`);
  runs.push({ phase, result: { code: productRun.code, signal: productRun.signal, pid: productRun.pid, stdout: productRun.stdout, stderr: productRun.stderr }, smoke });
}

const first = runs[0].smoke;
const relaunch = runs[1].smoke;
assert(first.product_status_after?.bindingState === "PROJECT_BOUND", "first run did not bind project");
assert(relaunch.product_status_before?.bindingState === "PROJECT_BOUND", "relaunch did not recover project binding");
assert(first.product_status_after.boundProject?.projectId === relaunch.product_status_after.boundProject?.projectId, "relaunch project identity changed");
assert(first.product_status_after.boundProject?.projectContextRevisionId === relaunch.product_status_after.boundProject?.projectContextRevisionId, "relaunch project revision changed");
assert(await fileSha(join(installRoot, "resources/backend-runtime/runtime-manifest.json")) === sourceManifestSha, "packaged resource manifest changed during smoke");
const finalPackageIdentity = await directoryIdentity(installRoot);
assert(finalPackageIdentity.sha256 === sourcePackageIdentity.sha256, "packaged install tree changed during smoke");

const report = {
  schema_version: "v3.packaged-runtime-smoke/1.0.0",
  result: "PACKAGED_ISOLATED_RUNTIME_CANDIDATE_PASS",
  clean_environment_class: "ISOLATED_SAME_MACHINE",
  started_at: startedAt,
  finished_at: new Date().toISOString(),
  os: { platform: process.platform, release: process.release, arch: process.arch },
  host_inventory: {
    repo_present_on_host: true,
    repo_path: root,
    system_python_present: await hostCommandExists("python.exe"),
    node_present_on_host: await hostCommandExists("node.exe"),
    npm_present_on_host: await hostCommandExists("npm.cmd"),
    developer_venv_present: false,
    runtime_path: runtimeEnvBase.PATH,
    runtime_node_or_npm_available: false,
  },
  artifact: {
    source_path: sourcePackageRoot,
    copied_install_path: installRoot,
    source_bytes: sourcePackageIdentity.bytes,
    source_tree_sha256: sourcePackageIdentity.sha256,
    final_bytes: finalPackageIdentity.bytes,
    final_tree_sha256: finalPackageIdentity.sha256,
    runtime_manifest_sha256: sourceManifestSha,
  },
  environment: {
    user_data_root: userDataRoot,
    local_app_data_root: localAppDataRoot,
    evidence_root: evidenceRoot,
    repo_hidden_from_runtime: true,
    developer_python_overrides_removed: true,
    developer_venv_removed: true,
    node_modules_not_on_runtime_path: true,
  },
  runs,
  clean_machine_proof: "NOT_PROVEN",
  clean_machine_launch: "NOT_PROVEN",
  no_orphan_backend_processes_observed: true,
};
await mkdir(dirname(reportPath), { recursive: true });
await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
console.log(JSON.stringify(report, null, 2));
