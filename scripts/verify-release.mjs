import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const packageRoot = resolve(process.env.V3_PACKAGE_ROOT ?? join(root, "artifacts/package/win-unpacked"));
const installerPath = resolve(process.env.V3_INSTALLER_PATH ?? join(root, "artifacts/package/v3-quant-workbench-1.0.0-x64.exe"));
const outputPath = resolve(process.env.V3_RELEASE_MANIFEST ?? join(root, "artifacts/package/V3_RELEASE_MANIFEST.json"));
const expectedVersion = "1.0.0";

function assert(condition, message) {
  if (!condition) throw new Error(`V1_RELEASE_VERIFY_FAILED: ${message}`);
}

async function requiredFile(path, label) {
  const info = await stat(path).catch((error) => {
    if (error?.code === "ENOENT") throw new Error(`V1_RELEASE_VERIFY_FAILED: ${label} missing: ${path}`);
    throw error;
  });
  assert(info.isFile(), `${label} is not a file: ${path}`);
  return info;
}

async function sha256(path) {
  return createHash("sha256").update(await readFile(path)).digest("hex");
}

function git(args) {
  return execFileSync(process.platform === "win32" ? "git.exe" : "git", args, {
    cwd: root,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
}

const packageJsonPath = join(root, "package.json");
const packageLockPath = join(root, "package-lock.json");
const buildManifestPath = join(root, "apps/backend/src/v3_backend/runtime/build_manifest.generated.json");
const packageEvidencePath = join(root, "artifacts/package/V3_PACKAGE_EVIDENCE.json");
const asarPath = join(packageRoot, "resources/app.asar");
const runtimeManifestPath = join(packageRoot, "resources/backend-runtime/runtime-manifest.json");
const pythonInventoryPath = join(packageRoot, "resources/backend-runtime/python-dependency-inventory.json");
const sbomPath = join(root, "sbom/v3-public-baseline.spdx.json");
const licenseMatrixPath = join(root, "docs/oss/THIRD_PARTY_LICENSE_MATRIX.csv");
const projectLicensePath = join(root, "LICENSE");
for (const [path, label] of [
  [packageJsonPath, "package metadata"], [packageLockPath, "npm lockfile"], [buildManifestPath, "BuildManifest"],
  [packageEvidencePath, "package evidence"], [asarPath, "app.asar"], [runtimeManifestPath, "runtime manifest"],
  [pythonInventoryPath, "Python inventory"], [sbomPath, "SPDX SBOM"], [licenseMatrixPath, "license matrix"],
  [projectLicensePath, "project license"], [installerPath, "Windows installer"],
]) await requiredFile(path, label);

const packageJson = JSON.parse(await readFile(packageJsonPath, "utf8"));
const packageLock = JSON.parse(await readFile(packageLockPath, "utf8"));
const buildManifest = JSON.parse(await readFile(buildManifestPath, "utf8"));
const packageEvidence = JSON.parse(await readFile(packageEvidencePath, "utf8"));
const runtimeManifest = JSON.parse(await readFile(runtimeManifestPath, "utf8"));
const pythonInventory = JSON.parse(await readFile(pythonInventoryPath, "utf8"));
const sbom = JSON.parse(await readFile(sbomPath, "utf8"));
const sourceSha = git(["rev-parse", "HEAD"]);
const sourceTree = git(["rev-parse", "HEAD^{tree}"]);
const installerBytes = await readFile(installerPath);

assert(packageJson.version === expectedVersion, "root product version mismatch");
assert(packageLock.version === expectedVersion && packageLock.packages?.[""]?.version === expectedVersion, "npm lock product version mismatch");
assert(buildManifest.package_identity?.version === expectedVersion, "BuildManifest product version mismatch");
assert(buildManifest.git_commit_sha === sourceSha && buildManifest.git_tree_sha === sourceTree, "BuildManifest source identity mismatch");
assert(buildManifest.dirty_state === "CLEAN", "release BuildManifest is not CLEAN");
assert(runtimeManifest.product?.version === expectedVersion && packageEvidence.package_product_version === expectedVersion, "package/runtime product version mismatch");
assert(runtimeManifest.source_git_sha === sourceSha && runtimeManifest.source_git_tree_sha === sourceTree, "runtime manifest source identity mismatch");
assert(runtimeManifest.build_manifest_id === buildManifest.build_manifest_id && packageEvidence.build_manifest_id === buildManifest.build_manifest_id, "build identity mismatch");
assert(packageEvidence.app_asar_sha256 === await sha256(asarPath), "app.asar evidence mismatch");
assert(packageEvidence.resource_manifest_sha256 === await sha256(runtimeManifestPath), "runtime manifest evidence mismatch");
assert(installerBytes[0] === 0x4d && installerBytes[1] === 0x5a, "installer is not a Windows PE executable");
assert(pythonInventory.python?.version === "3.14.5" && pythonInventory.python?.arch === "win_amd64", "packaged CPython identity mismatch");
assert(pythonInventory.critical_import_smoke?.modules?.akshare === "1.18.84", "packaged AKShare identity mismatch");
assert(Array.isArray(pythonInventory.packages) && pythonInventory.packages.length > 0, "Python dependency inventory is empty");
assert(pythonInventory.packages.every((entry) => entry.name && entry.version && entry.license), "Python license inventory is incomplete");
const described = sbom.packages?.find((entry) => entry.SPDXID === "SPDXRef-Package-v3-oss-rebuild");
assert(described?.versionInfo === expectedVersion, "SBOM product version mismatch");
assert(Array.isArray(sbom.packages) && sbom.packages.length > 1, "SBOM dependency inventory is empty");

const manifest = {
  schema_version: "v3.v1-release-manifest/1.0.0",
  product: {
    name: "V3 Quant Workbench",
    version: expectedVersion,
    classification: "PRE_ALPHA / RESEARCH_ONLY / NO_BROKER / NO_LIVE_TRADING",
  },
  source: { git_sha: sourceSha, git_tree_sha: sourceTree, dirty_state: buildManifest.dirty_state },
  build: { build_manifest_id: buildManifest.build_manifest_id, package_lock_sha256: await sha256(packageLockPath) },
  unpacked_package: {
    artifact_type: packageEvidence.artifact_type,
    bytes: packageEvidence.artifact_bytes,
    file_count: packageEvidence.artifact_file_count,
    sha256: packageEvidence.artifact_sha256,
  },
  installer: {
    name: installerPath.split(/[\\/]/u).at(-1),
    bytes: installerBytes.byteLength,
    sha256: await sha256(installerPath),
    target: "NSIS Windows x64 per-user installer",
  },
  electron: { app_asar_sha256: await sha256(asarPath) },
  packaged_runtime: {
    manifest_sha256: await sha256(runtimeManifestPath),
    python_version: pythonInventory.python.version,
    python_arch: pythonInventory.python.arch,
    python_executable_sha256: pythonInventory.python.source_python_sha256,
    akshare_version: pythonInventory.critical_import_smoke.modules.akshare,
    dependency_inventory_sha256: await sha256(pythonInventoryPath),
    dependency_count: pythonInventory.installed_package_count,
    first_launch_network_install: false,
  },
  software_bill_of_materials: {
    format: "SPDX-2.3",
    path: "sbom/v3-public-baseline.spdx.json",
    sha256: await sha256(sbomPath),
    package_count: sbom.packages.length,
  },
  licenses: {
    project: "Apache-2.0",
    project_license_sha256: await sha256(projectLicensePath),
    npm_python_matrix_sha256: await sha256(licenseMatrixPath),
    python_entries_complete: true,
  },
  npm_dependency_inventory: {
    package_lock_sha256: await sha256(packageLockPath),
    locked_path_count: Object.keys(packageLock.packages ?? {}).length,
  },
};
await mkdir(dirname(outputPath), { recursive: true });
await writeFile(outputPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ release_manifest: outputPath, ...manifest }, null, 2));
