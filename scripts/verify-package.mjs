import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { mkdir, readFile, readdir, stat } from "node:fs/promises";
import { listPackage } from "@electron/asar";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";

const root = resolve(import.meta.dirname, "..");
const packageRoot = resolve(process.env.V3_PACKAGE_ROOT ?? resolve(root, "artifacts/package/win-unpacked"));
const resourcesRoot = resolve(packageRoot, "resources");
const backendRoot = resolve(resourcesRoot, "backend-runtime");
const asarPath = resolve(resourcesRoot, "app.asar");
const evidencePath = resolve(process.env.V3_PACKAGE_EVIDENCE ?? resolve(root, "artifacts/package/V3_PACKAGE_EVIDENCE.json"));
const PACKAGED_SOURCE_CAPABILITY = "NOT_AVAILABLE";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function inside(parent, candidate) {
  const child = relative(resolve(parent), resolve(candidate));
  return child === "" || (child !== ".." && !child.startsWith(`..${sep}`) && !isAbsolute(child));
}

async function requiredFile(filePath, label) {
  let fileStat;
  try {
    fileStat = await stat(filePath);
  } catch (error) {
    if (error && typeof error === "object" && error.code === "ENOENT") {
      throw new Error(`${label} missing: ${filePath}`);
    }
    throw error;
  }
  assert(fileStat.isFile() === true, `${label} missing: ${filePath}`);
}

async function hashFile(path) {
  return createHash("sha256").update(await readFile(path)).digest("hex");
}

async function walk(directory, prefix = "") {
  const entries = (await readdir(directory, { withFileTypes: true })).sort((left, right) => left.name.localeCompare(right.name));
  const files = [];
  for (const entry of entries) {
    const absolute = resolve(directory, entry.name);
    const name = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) files.push(...await walk(absolute, name));
    else if (entry.isFile()) files.push({ path: name.replaceAll("\\", "/"), absolute });
  }
  return files;
}

async function directoryIdentity(directory) {
  const files = await walk(directory);
  const digest = createHash("sha256");
  let bytes = 0;
  for (const file of files) {
    const content = await readFile(file.absolute);
    bytes += content.byteLength;
    digest.update(file.path);
    digest.update("\0");
    digest.update(content);
    digest.update("\0");
  }
  return { bytes, sha256: digest.digest("hex"), file_count: files.length };
}

await requiredFile(asarPath, "Electron app.asar");
await requiredFile(resolve(backendRoot, "runtime-manifest.json"), "packaged runtime manifest");
await requiredFile(resolve(backendRoot, "python/python.exe"), "packaged CPython executable");
await requiredFile(resolve(backendRoot, "python/python314.dll"), "packaged CPython DLL");
await requiredFile(resolve(backendRoot, "python/LICENSE.txt"), "CPython license");
await requiredFile(resolve(backendRoot, "backend-package/v3_backend/runtime/bootstrap.py"), "packaged backend bootstrap");
await requiredFile(resolve(backendRoot, "backend-package/packages/contracts/research_package_transport_v1.json"), "packaged transport contract");
await requiredFile(resolve(backendRoot, "python-dependency-inventory.json"), "Python dependency inventory");

const runtimeManifestPath = resolve(backendRoot, "runtime-manifest.json");
const runtimeManifest = JSON.parse(await readFile(runtimeManifestPath, "utf8"));
assert(runtimeManifest.schema_version === "v3.packaged-backend/1.0.0", "unexpected packaged runtime manifest schema");
assert(runtimeManifest.product?.platform === "win32" && runtimeManifest.product?.arch === "x64", "packaged runtime is not Windows x64");
assert(runtimeManifest.backend_delivery_strategy === "BUNDLED_EMBEDDED_CPYTHON_MODULE_MODE", "unexpected backend delivery strategy");
assert(runtimeManifest.first_launch_network_install === false, "packaged runtime permits first-launch network install");
assert(runtimeManifest.source_capability === PACKAGED_SOURCE_CAPABILITY, "packaged source capability does not record the narrow AKShare boundary");
assert(runtimeManifest.real_free_source?.provider_id === "pvd_akshare_eastmoney_a_share_eod_v1", "packaged AKShare provider identity is missing");
assert(runtimeManifest.real_free_source?.connector_version_id === "cov_akshare_eod_research_v1", "packaged AKShare connector identity is missing");
assert(runtimeManifest.real_free_source?.endpoint === "stock_zh_a_hist", "packaged AKShare endpoint identity is missing");
assert(runtimeManifest.real_free_source?.package_version === "1.18.84", "packaged AKShare package version is missing");
assert(runtimeManifest.real_free_source?.truth_state === "DEMO" && runtimeManifest.real_free_source?.maturity === "PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE", "packaged source maturity metadata overclaims");
assert(typeof runtimeManifest.source_git_sha === "string" && /^[0-9a-f]{40}$/.test(runtimeManifest.source_git_sha), "runtime source identity missing");
assert(Array.isArray(runtimeManifest.files) && runtimeManifest.files.length > 0, "runtime manifest file inventory is empty");
assert(Array.isArray(runtimeManifest.critical_files) && runtimeManifest.critical_files.length > 0, "runtime manifest critical inventory is empty");

const manifestText = JSON.stringify(runtimeManifest);
for (const forbidden of ["D:\\V3OpenSource", "D:/V3OpenSource", "apps/backend/src", "process.cwd()", "V3_BACKEND_PYTHON", "V3_PYTHON"]) {
  assert(!manifestText.includes(forbidden), `forbidden development path/override in resource manifest: ${forbidden}`);
}

for (const entry of runtimeManifest.files) {
  assert(typeof entry?.path === "string" && !entry.path.startsWith("/") && !entry.path.split("/").includes(".."), `unsafe resource manifest path: ${entry?.path}`);
  const file = resolve(backendRoot, entry.path);
  assert(inside(backendRoot, file), `resource manifest escapes backend root: ${entry.path}`);
  await requiredFile(file, `manifest resource ${entry.path}`);
  assert(await hashFile(file) === entry.sha256, `resource hash mismatch: ${entry.path}`);
}
for (const entry of runtimeManifest.critical_files) {
  const matching = runtimeManifest.files.find((candidate) => candidate.path === entry.path);
  assert(matching?.sha256 === entry.sha256, `critical resource is not bound to full inventory: ${entry.path}`);
}

const inventory = JSON.parse(await readFile(resolve(backendRoot, "python-dependency-inventory.json"), "utf8"));
assert(inventory.schema_version === "v3.python-dependency-inventory/1.0.0", "unexpected Python inventory schema");
assert(inventory.first_launch_network_install === false, "Python inventory permits first-launch installation");
assert(inventory.python?.version === "3.14.5" && inventory.python?.arch === "win_amd64", "Python inventory identity mismatch");
assert(inventory.python?.license === "PSF-2.0", "Python runtime license is missing");
assert(Number.isInteger(inventory.installed_package_count) && inventory.installed_package_count > 0, "Python inventory has no packages");
assert(inventory.critical_import_smoke?.status === "PASS", "critical Python import smoke was not recorded as PASS");
assert(inventory.critical_import_smoke?.modules?.akshare === "1.18.84", "Python inventory does not prove exact AKShare import");
assert(inventory.source_capability === PACKAGED_SOURCE_CAPABILITY, "Python inventory source capability is not the narrow AKShare boundary");
assert(inventory.real_free_source?.provider_id === "pvd_akshare_eastmoney_a_share_eod_v1", "Python inventory AKShare provider identity is missing");
assert(inventory.real_free_source?.connector_version_id === "cov_akshare_eod_research_v1", "Python inventory AKShare connector identity is missing");
assert(inventory.real_free_source?.package_version === "1.18.84" && inventory.real_free_source?.endpoint === "stock_zh_a_hist", "Python inventory AKShare package/endpoint identity is missing");
assert(Array.isArray(inventory.packages) && inventory.packages.every((packageRecord) => packageRecord.name && packageRecord.version && packageRecord.license), "Python license inventory is incomplete");
assert(inventory.packages.some((packageRecord) => packageRecord.name.toLowerCase() === "akshare" && packageRecord.version === "1.18.84" && typeof packageRecord.integrity === "string"), "Python license inventory lacks exact AKShare archive identity");

const packagedAkshareImport = JSON.parse(execFileSync(resolve(backendRoot, "python/python.exe"), ["-c", "import akshare,json; print(json.dumps({'version': akshare.__version__}))"], {
  cwd: resolve(backendRoot, "backend-package"),
  encoding: "utf8",
  env: { ...process.env, PYTHONHOME: resolve(backendRoot, "python"), PYTHONPATH: "", PYTHONNOUSERSITE: "1" }
}).trim());
assert(packagedAkshareImport.version === "1.18.84", `packaged CPython imported unexpected AKShare version: ${packagedAkshareImport.version}`);
const asarFiles = await listPackage(asarPath);
const asarSet = new Set(asarFiles.map((entry) => String(entry).replaceAll("\\", "/").replace(/^\//u, "")));
for (const required of ["dist/apps/desktop/src/main.js", "dist/apps/desktop/src/preload.js", "dist/apps/desktop/src/renderer/index.html", "package.json"]) {
  assert(asarSet.has(required), `required Electron app resource missing from asar: ${required}`);
}
const identity = await directoryIdentity(packageRoot);
await mkdir(dirname(evidencePath), { recursive: true });
const evidence = {
  schema_version: "v3.package-evidence/1.0.0",
  artifact_type: "electron-unpacked-windows-x64",
  artifact_path: packageRoot,
  artifact_bytes: identity.bytes,
  artifact_sha256: identity.sha256,
  artifact_file_count: identity.file_count,
  app_asar_path: asarPath,
  app_asar_sha256: await hashFile(asarPath),
  resource_manifest_path: runtimeManifestPath,
  resource_manifest_sha256: await hashFile(runtimeManifestPath),
  source_git_sha: runtimeManifest.source_git_sha,
  build_manifest_id: runtimeManifest.build_manifest_id,
  package_product_version: runtimeManifest.product.version,
  package_platform: runtimeManifest.product.platform,
  package_arch: runtimeManifest.product.arch,
  backend_delivery_strategy: runtimeManifest.backend_delivery_strategy,
  python_dependency_count: inventory.installed_package_count,
  critical_import_smoke: inventory.critical_import_smoke,
  source_capability: runtimeManifest.source_capability,
  real_free_source: runtimeManifest.real_free_source,
  first_launch_network_install: runtimeManifest.first_launch_network_install,
};
const { writeFile } = await import("node:fs/promises");
await writeFile(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, "utf8");
console.log(JSON.stringify(evidence, null, 2));
