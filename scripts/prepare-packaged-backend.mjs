import { createHash } from "node:crypto";
import { cp, mkdir, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { execFileSync, spawnSync } from "node:child_process";
import { dirname, relative, resolve, sep } from "node:path";

const root = resolve(import.meta.dirname, "..");
const sourceRoot = process.env.V3_PACKAGED_PYTHON_ROOT;
if (!sourceRoot) {
  throw new Error("V3_PACKAGED_PYTHON_ROOT is required and must point to the exact verified CPython build input");
}

const pythonSource = resolve(sourceRoot);
const sourcePython = resolve(pythonSource, "python.exe");
const sourcePythonLicense = resolve(pythonSource, "LICENSE.txt");
const stagingRoot = resolve(root, "artifacts/package-staging/backend-runtime");
const stagedPythonRoot = resolve(stagingRoot, "python");
const stagedPackageRoot = resolve(stagingRoot, "backend-package");
const stagedSitePackages = resolve(stagedPythonRoot, "Lib/site-packages");
const requirementsRoot = resolve(root, "apps/backend");
const requirementsPath = resolve(requirementsRoot, "requirements.txt");
const reportPath = resolve(stagingRoot, "python-pip-install-report.json");
const inventoryPath = resolve(stagingRoot, "python-dependency-inventory.json");
const manifestPath = resolve(stagingRoot, "runtime-manifest.json");
const packageJsonPath = resolve(root, "package.json");
const lockPath = resolve(root, "package-lock.json");
const buildManifestPath = resolve(root, "apps/backend/src/v3_backend/runtime/build_manifest.generated.json");
const transportContractPath = resolve(root, "packages/contracts/research_package_transport_v1.json");
const EXPECTED_CPYTHON_SHA256 = "3adbbf2af609e206e3ca18cd55fc7c4b52f5c8bb8218dd99fd5a9e50d7a193cd";
const EXPECTED_CPYTHON_LICENSE_SHA256 = "935cf13e19f8c31b497d20b05d73623431a226b230c3599bc30fa3348979bc68";

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

async function fileSha(path) {
  return sha256(await readFile(path));
}

function run(command, args, options = {}) {
  const commandResult = spawnSync(command, args, {
    cwd: root,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    ...options,
  });
  if (commandResult.error) throw commandResult.error;
  if (commandResult.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed (${commandResult.status}):\n${commandResult.stdout ?? ""}\n${commandResult.stderr ?? ""}`);
  }
  return commandResult.stdout ?? "";
}

function git(args) {
  return execFileSync(process.platform === "win32" ? "git.exe" : "git", args, { cwd: root, encoding: "utf8" }).trim();
}

async function copyTree(source, destination) {
  await cp(source, destination, {
    recursive: true,
    filter: (candidate) => !candidate.split(sep).includes("__pycache__") && !candidate.endsWith(".pyc"),
  });
}

async function walk(directory, prefix = "") {
  const entries = (await readdir(directory, { withFileTypes: true }))
    .sort((left, right) => left.name.localeCompare(right.name));
  const files = [];
  for (const entry of entries) {
    const absolute = resolve(directory, entry.name);
    const relativePath = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) files.push(...await walk(absolute, relativePath));
    else if (entry.isFile()) files.push({ path: relativePath.replaceAll("\\", "/"), absolute });
  }
  return files;
}

async function requireFile(filePath, label) {
  let fileStat;
  try {
    fileStat = await stat(filePath);
  } catch (error) {
    if (error && typeof error === "object" && error.code === "ENOENT") {
      throw new Error(`${label} is missing: ${filePath}`);
    }
    throw error;
  }
  if (!fileStat.isFile()) throw new Error(`${label} is missing: ${filePath}`);
}

await requireFile(sourcePython, "CPython executable");
await requireFile(resolve(pythonSource, "python314.dll"), "CPython DLL");
await requireFile(resolve(pythonSource, "LICENSE.txt"), "CPython license");
await requireFile(requirementsPath, "backend requirements");
await requireFile(buildManifestPath, "generated backend BuildManifest; run npm run build first");
await requireFile(transportContractPath, "research package transport contract");

const versionProbe = JSON.parse(run(sourcePython, ["-c", [
  "import json,platform,sys",
  "print(json.dumps({'version': list(sys.version_info[:3]), 'machine': platform.machine(), 'bits': 64 if sys.maxsize > 2**32 else 32}))",
].join(";")], { env: { ...process.env, PYTHONPATH: "", PYTHONHOME: "", PYTHONNOUSERSITE: "1" } }).trim());
if (versionProbe.version.join(".") !== "3.14.5" || versionProbe.bits !== 64 || !["AMD64", "amd64", "x86_64"].includes(versionProbe.machine)) {
  throw new Error(`Expected exact CPython 3.14.5 win_amd64, observed ${JSON.stringify(versionProbe)}`);
}
const sourcePythonSha256 = await fileSha(sourcePython);
const sourcePythonLicenseSha256 = await fileSha(sourcePythonLicense);
if (sourcePythonSha256 !== EXPECTED_CPYTHON_SHA256 || sourcePythonLicenseSha256 !== EXPECTED_CPYTHON_LICENSE_SHA256) {
  throw new Error(`CPython input identity mismatch: executable=${sourcePythonSha256}, license=${sourcePythonLicenseSha256}`);
}

await rm(stagingRoot, { recursive: true, force: true });
await mkdir(stagedPythonRoot, { recursive: true });
await mkdir(stagedPackageRoot, { recursive: true });

for (const file of ["python.exe", "pythonw.exe", "python3.dll", "python314.dll", "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt"]) {
  await cp(resolve(pythonSource, file), resolve(stagedPythonRoot, file));
}
await copyTree(resolve(pythonSource, "Lib"), resolve(stagedPythonRoot, "Lib"));
// Do not copy the build machine's Python site-packages.  The staged closure
// must contain only the exact wheels resolved from the current requirements.
await rm(resolve(stagedPythonRoot, "Lib/site-packages"), { recursive: true, force: true });
await mkdir(stagedSitePackages, { recursive: true });
await copyTree(resolve(pythonSource, "DLLs"), resolve(stagedPythonRoot, "DLLs"));
await copyTree(resolve(root, "apps/backend/src/v3_backend"), resolve(stagedPackageRoot, "v3_backend"));
await mkdir(resolve(stagedPackageRoot, "packages/contracts"), { recursive: true });
await cp(transportContractPath, resolve(stagedPackageRoot, "packages/contracts/research_package_transport_v1.json"));

const installEnvironment = { ...process.env };
for (const key of ["PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE", "V3_BACKEND_PYTHON", "V3_PYTHON", "V3_BACKEND_WORKING_DIRECTORY"]) {
  delete installEnvironment[key];
}
installEnvironment.PYTHONNOUSERSITE = "1";
run(sourcePython, [
  "-m", "pip", "install",
  "--target", stagedSitePackages,
  "--requirement", requirementsPath,
  "--only-binary=:all:",
  "--upgrade",
  "--no-compile",
  "--disable-pip-version-check",
  "--report", reportPath,
], { env: installEnvironment });

const criticalImportSmoke = JSON.parse(run(resolve(stagedPythonRoot, "python.exe"), ["-c", [
  "import importlib,json",
  "names=['v3_backend','pydantic','pydantic_core','pydantic_ai','numpy','scipy','sklearn','joblib']",
  "versions={}",
  "[versions.__setitem__(name, getattr(importlib.import_module(name),'__version__','UNAVAILABLE')) for name in names]",
  "print(json.dumps({'status':'PASS','modules':versions},sort_keys=True))",
].join(";")], {
  cwd: stagedPackageRoot,
  env: {
    ...installEnvironment,
    PYTHONHOME: stagedPythonRoot,
    PYTHONPATH: "",
    PYTHONNOUSERSITE: "1",
    V3_RESEARCH_PACKAGE_TRANSPORT_PATH: resolve(stagedPackageRoot, "packages/contracts/research_package_transport_v1.json"),
  },
}).trim());
if (criticalImportSmoke.status !== "PASS" || !criticalImportSmoke.modules || typeof criticalImportSmoke.modules !== "object") {
  throw new Error(`critical Python import smoke did not pass: ${JSON.stringify(criticalImportSmoke)}`);
}

const report = JSON.parse(await readFile(reportPath, "utf8"));
if (!Array.isArray(report.install) || report.install.length === 0) throw new Error("Python pip report has no installed packages");
const requirementsFiles = (await readdir(requirementsRoot))
  .filter((name) => name.startsWith("requirements") && name.endsWith(".txt"))
  .sort();
const requirementManifests = [];
for (const name of requirementsFiles) {
  const path = resolve(requirementsRoot, name);
  requirementManifests.push({
    path: relative(root, path).replaceAll("\\", "/"),
    sha256: await fileSha(path),
    included_in_packaged_core: name === "requirements.txt" || name === "requirements-model-runtime-v0.txt",
    note: name === "requirements-track-c-v0.txt"
      ? "Existing Track C adapter manifest is not included in the Product Runtime core package; TA-Lib remains outside this wave's packaged source capability."
      : null,
  });
}

const packages = report.install.map((installRecord) => {
  const metadata = installRecord.metadata ?? {};
  const archiveHash = installRecord.download_info?.archive_info?.hash ?? null;
  const classifiers = Array.isArray(metadata.classifier) ? metadata.classifier.map(String) : [];
  const rawLicense = typeof metadata.license === "string" ? metadata.license.trim() : "";
  const classifierLicense = classifiers.some((classifier) => classifier.includes("MIT License"))
    ? "MIT"
    : classifiers.some((classifier) => classifier.includes("BSD License"))
      ? "BSD-3-Clause"
      : classifiers.some((classifier) => classifier.includes("Apache Software License"))
        ? "Apache-2.0"
        : classifiers.some((classifier) => classifier.includes("Mozilla Public License"))
          ? "MPL-2.0"
          : null;
  const license = metadata.license_expression
    ?? (rawLicense.length > 0 && rawLicense.length <= 80 && !/[\r\n]/u.test(rawLicense) ? rawLicense : null)
    ?? classifierLicense
    ?? "NOASSERTION";
  const licenseFiles = metadata.license_files ?? metadata.license_file ?? [];
  return {
    name: String(metadata.name ?? ""),
    version: String(metadata.version ?? ""),
    requested: installRecord.requested === true,
    source: installRecord.download_info?.url ?? "NOASSERTION",
    integrity: archiveHash,
    license: String(license),
    license_files: Array.isArray(licenseFiles) ? licenseFiles.map(String).sort() : [],
  };
}).sort((left, right) => left.name.localeCompare(right.name) || left.version.localeCompare(right.version));
if (packages.some((packageRecord) => packageRecord.name.length === 0 || packageRecord.version.length === 0)) throw new Error("Python pip report contains incomplete package identity");

const packageJson = JSON.parse(await readFile(packageJsonPath, "utf8"));
const buildManifest = JSON.parse(await readFile(buildManifestPath, "utf8"));
if (typeof buildManifest.build_manifest_id !== "string") throw new Error("backend BuildManifest identity is unavailable");
const inventory = {
  schema_version: "v3.python-dependency-inventory/1.0.0",
  strategy: "BUNDLED_EMBEDDED_CPYTHON_MODULE_MODE",
  python: {
    version: "3.14.5",
    arch: "win_amd64",
    runtime_source: "Pre-supplied exact CPython 3.14.5 win_amd64 build input; source identity is recorded by executable/license hashes",
    source_python_sha256: sourcePythonSha256,
    source_license_sha256: sourcePythonLicenseSha256,
    license: "PSF-2.0",
    license_file: "python/LICENSE.txt",
  },
  requirement_manifests: requirementManifests,
  installed_package_count: packages.length,
  packages,
  critical_import_smoke: criticalImportSmoke,
  first_launch_network_install: false,
  source_capability: "NOT_AVAILABLE (real free source is outside this wave and is not shipped)",
};
await writeFile(inventoryPath, `${JSON.stringify(inventory, null, 2)}\n`, "utf8");

const files = await walk(stagingRoot);
const criticalNames = [
  "python/python.exe",
  "python/python314.dll",
  "python/LICENSE.txt",
  "backend-package/v3_backend/runtime/bootstrap.py",
  "backend-package/v3_backend/runtime/build_manifest.generated.json",
  "backend-package/packages/contracts/research_package_transport_v1.json",
  "python-dependency-inventory.json",
];
const fileRecords = [];
for (const file of files) {
  if (file.path === "runtime-manifest.json" || file.path === "python-pip-install-report.json") continue;
  fileRecords.push({ path: file.path, bytes: (await stat(file.absolute)).size, sha256: await fileSha(file.absolute) });
}
const fileMap = new Map(fileRecords.map((file) => [file.path, file]));
for (const name of criticalNames) if (!fileMap.has(name)) throw new Error(`critical packaged resource missing: ${name}`);
const manifest = {
  schema_version: "v3.packaged-backend/1.0.0",
  product: { name: packageJson.name, version: packageJson.version, platform: "win32", arch: "x64" },
  source_git_sha: git(["rev-parse", "HEAD"]),
  source_git_tree_sha: git(["rev-parse", "HEAD^{tree}"]),
  package_lock_sha256: await fileSha(lockPath),
  build_manifest_id: buildManifest.build_manifest_id,
  backend_delivery_strategy: "BUNDLED_EMBEDDED_CPYTHON_MODULE_MODE",
  python_runtime: {
    executable: "python/python.exe",
    version: "3.14.5",
    arch: "win_amd64",
    module: "v3_backend.runtime.bootstrap",
    working_root: "backend-package",
    license: "PSF-2.0",
    source_python_sha256: sourcePythonSha256,
    source_license_sha256: sourcePythonLicenseSha256,
  },
  dependency_inventory: "python-dependency-inventory.json",
  critical_files: criticalNames.map((path) => ({ path, sha256: fileMap.get(path).sha256 })),
  files: fileRecords.sort((left, right) => left.path.localeCompare(right.path)),
  first_launch_network_install: false,
  source_capability: "NOT_AVAILABLE",
};
await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
console.log(JSON.stringify({
  staging_root: stagingRoot,
  python_version: versionProbe.version.join("."),
  python_arch: "win_amd64",
      dependency_count: packages.length,
  critical_import_smoke: criticalImportSmoke.status,
  source_python_sha256: sourcePythonSha256,
  source_license_sha256: sourcePythonLicenseSha256,
  build_manifest_id: buildManifest.build_manifest_id,
  resource_manifest: manifestPath,
  critical_file_count: criticalNames.length,
}, null, 2));
