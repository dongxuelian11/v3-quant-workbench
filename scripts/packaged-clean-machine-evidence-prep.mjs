import { createHash } from "node:crypto";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { resolve, join } from "node:path";

const root = resolve(import.meta.dirname, "..");
const packageRoot = resolve(process.env.V3_PACKAGE_ROOT ?? join(root, "artifacts/package/win-unpacked"));
const packageEvidencePath = resolve(process.env.V3_PACKAGE_EVIDENCE ?? join(root, "artifacts/package/V3_PACKAGE_EVIDENCE.json"));
const outputRoot = resolve(process.env.V3_LEVEL2_OUTPUT_ROOT ?? join(root, "artifacts/package-level2"));
const runtimeManifestPath = join(packageRoot, "resources/backend-runtime/runtime-manifest.json");
const pythonPath = join(packageRoot, "resources/backend-runtime/python/python.exe");
const buildScriptPath = resolve(root, "scripts/prepare-packaged-backend.mjs");

function assert(condition, message) {
  if (!condition) throw new Error(`LEVEL2_DELIVERY_PREP_FAILED: ${message}`);
}

async function requiredFile(path, label) {
  const info = await stat(path).catch((error) => {
    if (error?.code === "ENOENT") throw new Error(`LEVEL2_DELIVERY_PREP_FAILED: ${label} missing: ${path}`);
    throw error;
  });
  assert(info.isFile(), `${label} is not a file: ${path}`);
}

async function fileSha(path) {
  return createHash("sha256").update(await readFile(path)).digest("hex");
}

function git(args) {
  return execFileSync(process.platform === "win32" ? "git.exe" : "git", args, {
    cwd: root,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
}

await requiredFile(packageEvidencePath, "package evidence");
await requiredFile(runtimeManifestPath, "runtime manifest");
await requiredFile(pythonPath, "packaged CPython executable");
await requiredFile(buildScriptPath, "packaging build script");

const packageEvidence = JSON.parse(await readFile(packageEvidencePath, "utf8"));
const runtimeManifest = JSON.parse(await readFile(runtimeManifestPath, "utf8"));
const buildScript = await readFile(buildScriptPath, "utf8");
const buildPinMatch = /const EXPECTED_CPYTHON_SHA256 = "([0-9a-f]{64})"/u.exec(buildScript);
const sourceGitSha = process.env.V3_SOURCE_GIT_SHA ?? git(["rev-parse", "HEAD"]);
const observedGitSha = git(["rev-parse", "HEAD"]);
const cpythonShaPinnedInBuild = buildPinMatch?.[1] ?? null;
const cpythonShaFromManifest = runtimeManifest.python_runtime?.source_python_sha256 ?? null;
const cpythonShaActual = await fileSha(pythonPath);
const cpythonCritical = runtimeManifest.critical_files?.find((entry) => entry?.path === "python/python.exe")?.sha256 ?? null;
const artifactBytes = Number(packageEvidence.artifact_bytes);
const sourcePackageSha = String(packageEvidence.artifact_sha256 ?? "");

assert(/^[0-9a-f]{40}$/u.test(sourceGitSha), "source Git SHA is not exact");
assert(observedGitSha === sourceGitSha, `checkout HEAD ${observedGitSha} does not match requested source SHA ${sourceGitSha}`);
assert(runtimeManifest.source_git_sha === sourceGitSha, "runtime manifest source Git SHA mismatch");
assert(packageEvidence.source_git_sha === sourceGitSha, "package evidence source Git SHA mismatch");
assert(/^[0-9a-f]{64}$/u.test(cpythonShaPinnedInBuild ?? ""), "CPython build pin is missing");
assert(/^[0-9a-f]{64}$/u.test(cpythonShaFromManifest), "CPython manifest hash is missing");
assert(/^[0-9a-f]{64}$/u.test(cpythonShaActual), "actual packaged CPython hash is invalid");
assert(cpythonShaPinnedInBuild === cpythonShaFromManifest, "CPython build pin and manifest hash differ");
assert(cpythonShaFromManifest === cpythonShaActual, "CPython manifest hash and actual executable differ");
assert(cpythonCritical === cpythonShaActual, "CPython critical-file hash and actual executable differ");
assert(runtimeManifest.python_runtime?.version === "3.14.5", "unexpected packaged CPython version");
assert(runtimeManifest.python_runtime?.arch === "win_amd64", "unexpected packaged CPython architecture");
assert(runtimeManifest.first_launch_network_install === false, "first-launch network install is not disabled");
assert(runtimeManifest.source_capability === "NOT_AVAILABLE", "packaged source capability is not NOT_AVAILABLE");
assert(Number.isInteger(artifactBytes) && artifactBytes > 0, "package artifact byte count is invalid");
assert(/^[0-9a-f]{64}$/u.test(sourcePackageSha), "package artifact SHA is invalid");

await mkdir(outputRoot, { recursive: true });
const evidence = {
  schema_version: "v3.packaging-level2-build-pin/1.0.0",
  source_git_sha: sourceGitSha,
  source_git_tree_sha: runtimeManifest.source_git_tree_sha,
  package_artifact_sha256: sourcePackageSha,
  package_artifact_bytes: artifactBytes,
  package_artifact_file_count: packageEvidence.artifact_file_count,
  build_pin_source: "scripts/prepare-packaged-backend.mjs:EXPECTED_CPYTHON_SHA256",
  cpython_sha_pinned_in_build: cpythonShaPinnedInBuild,
  cpython_sha_from_manifest: cpythonShaFromManifest,
  cpython_sha_actual: cpythonShaActual,
  cpython_sha_from_manifest_critical_file: cpythonCritical,
  cpython_sha_reconciliation: "PASS",
  cpython_license_sha_from_manifest: runtimeManifest.python_runtime?.source_license_sha256 ?? null,
  runtime_manifest_sha256: await fileSha(runtimeManifestPath),
  app_asar_sha256: packageEvidence.app_asar_sha256,
  package_product_version: packageEvidence.package_product_version,
  backend_delivery_strategy: packageEvidence.backend_delivery_strategy,
  source_capability: packageEvidence.source_capability,
  first_launch_network_install: packageEvidence.first_launch_network_install,
};
const outputPath = join(outputRoot, "V3_PACKAGING_LEVEL2_BUILD_PIN.json");
await writeFile(outputPath, `${JSON.stringify(evidence, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ output_path: outputPath, ...evidence }, null, 2));
