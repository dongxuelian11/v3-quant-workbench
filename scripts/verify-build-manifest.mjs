import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { execFileSync, spawnSync } from "node:child_process";

const root = resolve(import.meta.dirname, "..");
const sourcePath = resolve(root, "apps/backend/src/v3_backend/runtime/build_manifest.generated.json");
const distPath = resolve(root, "dist/apps/backend/src/v3_backend/runtime/build_manifest.generated.json");
const idPrefix = "bmanifest_sha256_";

function git(args) {
  return execFileSync(process.platform === "win32" ? "git.exe" : "git", args, { cwd: root, encoding: "utf8" }).trim();
}
function sha256(bytes) { return createHash("sha256").update(bytes).digest("hex"); }
function canonicalStable(value) {
  if (Array.isArray(value)) return `[${value.map((item) => canonicalStable(item)).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalStable(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

const manifest = JSON.parse(await readFile(sourcePath, "utf8"));
const commit = git(["rev-parse", "HEAD"]);
const tree = git(["rev-parse", "HEAD^{tree}"]);
const dirty = git(["status", "--porcelain", "--untracked-files=all"]).length === 0 ? "CLEAN" : "DIRTY";
if (manifest.git_commit_sha !== commit) throw new Error(`BuildManifest commit mismatch: ${manifest.git_commit_sha} != ${commit}`);
if (manifest.git_tree_sha !== tree) throw new Error(`BuildManifest tree mismatch: ${manifest.git_tree_sha} != ${tree}`);
if (manifest.dirty_state !== dirty) throw new Error(`BuildManifest dirty state mismatch: ${manifest.dirty_state} != ${dirty}`);
if (process.env.V3_BUILD_MANIFEST_REQUIRE_CLEAN === "1" && dirty !== "CLEAN") throw new Error("BuildManifest requires a clean checkout");
const { build_manifest_id: ignoredId, generated_at: ignoredTimestamp, ...stable } = manifest;
const expectedId = idPrefix + sha256(Buffer.from(canonicalStable(stable), "utf8"));
if (manifest.build_manifest_id !== expectedId) throw new Error("BuildManifest stable identity hash mismatch");
const lockHash = sha256(await readFile(resolve(root, "package-lock.json")));
if (manifest.package_lock_sha256 !== lockHash) throw new Error("BuildManifest package-lock hash mismatch");
const distManifest = JSON.parse(await readFile(distPath, "utf8"));
if (distManifest.build_manifest_id !== manifest.build_manifest_id) throw new Error("dist BuildManifest does not match source BuildManifest");

const python = process.env.V3_PYTHON ?? (process.platform === "win32" ? "python" : "python3");
const pythonEnv = { ...process.env, PYTHONPATH: resolve(root, "apps/backend/src") };
const runtime = spawnSync(python, ["-c", "from v3_backend.runtime.build_manifest import BUILD_MANIFEST; print(BUILD_MANIFEST.build_manifest_id or 'UNAVAILABLE')"], {
  cwd: root,
  env: pythonEnv,
  encoding: "utf8"
});
if (runtime.status !== 0 || runtime.stdout.trim() !== manifest.build_manifest_id) {
  throw new Error(`runtime did not consume the generated BuildManifest: ${runtime.stderr || runtime.stdout}`);
}
console.log(`BuildManifest verification PASS: ${manifest.build_manifest_id} (${manifest.dirty_state})`);
