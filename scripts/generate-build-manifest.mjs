import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { resolve, relative, dirname } from "node:path";
import { execFileSync } from "node:child_process";

const root = resolve(import.meta.dirname, "..");
const sourcePath = resolve(root, "apps/backend/src/v3_backend/runtime/build_manifest.generated.json");
const distPath = resolve(root, "dist/apps/backend/src/v3_backend/runtime/build_manifest.generated.json");
const schemaVersion = "v3.build-manifest/1.0.0";
const idPrefix = "bmanifest_sha256_";

function canonicalStable(value) {
  if (Array.isArray(value)) return `[${value.map((item) => canonicalStable(item)).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalStable(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function git(args) {
  return execFileSync(process.platform === "win32" ? "git.exe" : "git", args, { cwd: root, encoding: "utf8" }).trim();
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

async function fileSha(path) {
  return sha256(await readFile(path));
}

const packageJson = JSON.parse(await readFile(resolve(root, "package.json"), "utf8"));
const packageLockSha256 = await fileSha(resolve(root, "package-lock.json"));
const gitCommitSha = git(["rev-parse", "HEAD"]);
const gitTreeSha = git(["rev-parse", "HEAD^{tree}"]);
const dirtyState = git(["status", "--porcelain", "--untracked-files=all"]).length === 0 ? "CLEAN" : "DIRTY";

const backendRequirementsDir = resolve(root, "apps/backend");
const requirementNames = (await readdir(backendRequirementsDir))
  .filter((name) => name.startsWith("requirements") && name.endsWith(".txt"))
  .sort();
const dependencyFiles = [];
for (const name of requirementNames) {
  const path = resolve(backendRequirementsDir, name);
  dependencyFiles.push({ path: relative(root, path).replaceAll("\\", "/"), sha256: await fileSha(path) });
}
const backendDependencyAuthority = {
  files: dependencyFiles,
  authority_sha256: sha256(Buffer.from(canonicalStable(dependencyFiles), "utf8"))
};

const migrationDir = resolve(root, "apps/backend/src/v3_backend/migrations/versions");
const migrationNames = (await readdir(migrationDir)).filter((name) => /^\d{4}_[a-z0-9_]+\.sql$/.test(name)).sort();
const migrationFiles = [];
for (const name of migrationNames) {
  const path = resolve(migrationDir, name);
  migrationFiles.push({ path: relative(root, path).replaceAll("\\", "/"), sha256: await fileSha(path) });
}
const contractSchemaMigrationLevels = {
  asl_api_version: "1.0.0",
  local_transport_protocol: "v3.local/1.0",
  schema_compatibility: { min: "1.0.0", max: "1.0.0" },
  migration_application_version: "v3-product-runtime-composition",
  migration_files: migrationFiles,
  migration_set_sha256: sha256(Buffer.from(canonicalStable(migrationFiles), "utf8"))
};

const stable = {
  schema_version: schemaVersion,
  git_commit_sha: gitCommitSha,
  git_tree_sha: gitTreeSha,
  dirty_state: dirtyState,
  package_identity: { name: String(packageJson.name), version: String(packageJson.version) },
  package_lock_sha256: packageLockSha256,
  backend_dependency_authority: backendDependencyAuthority,
  contract_schema_migration_levels: contractSchemaMigrationLevels
};
const buildManifestId = idPrefix + sha256(Buffer.from(canonicalStable(stable), "utf8"));
const manifest = {
  ...stable,
  build_manifest_id: buildManifestId,
  generated_at: new Date().toISOString()
};
const content = `${JSON.stringify(manifest, null, 2)}\n`;
await mkdir(dirname(sourcePath), { recursive: true });
await writeFile(sourcePath, content, "utf8");
await mkdir(dirname(distPath), { recursive: true });
await writeFile(distPath, content, "utf8");
console.log(`Generated BuildManifest ${buildManifestId} (${dirtyState}) for ${gitCommitSha}`);
