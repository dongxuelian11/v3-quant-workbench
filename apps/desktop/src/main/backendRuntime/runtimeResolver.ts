import { createHash } from "node:crypto";
import { existsSync, readFileSync, realpathSync, statSync } from "node:fs";
import { isAbsolute, join, relative, resolve, sep } from "node:path";

export const PACKAGED_BACKEND_MANIFEST_SCHEMA = "v3.packaged-backend/1.0.0";

export type BackendRuntimeMode = "DEVELOPMENT" | "PACKAGED";

export interface BackendRuntimeResolution {
  readonly mode: BackendRuntimeMode;
  readonly executable: string;
  readonly workingDirectory: string;
  readonly backendResourceRoot: string;
  readonly pythonRoot: string;
  readonly backendPackageRoot: string;
  readonly backendModule: "v3_backend.runtime.bootstrap";
  readonly manifestPath: string | null;
  readonly manifestSha256: string | null;
  readonly sourceGitSha: string | null;
  readonly buildManifestId: string | null;
}

interface PackagedBackendManifest {
  readonly schema_version: typeof PACKAGED_BACKEND_MANIFEST_SCHEMA;
  readonly source_git_sha: string;
  readonly build_manifest_id: string;
  readonly critical_files: readonly { readonly path: string; readonly sha256: string }[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function sha256File(path: string): string {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function canonicalExistingPath(path: string, label: string): string {
  if (!existsSync(path)) throw new Error(`PACKAGED_BACKEND_RESOURCE_MISSING: ${label}`);
  try {
    return realpathSync(path);
  } catch {
    throw new Error(`PACKAGED_BACKEND_RESOURCE_UNRESOLVABLE: ${label}`);
  }
}

function assertRegularFile(path: string, label: string): string {
  const canonical = canonicalExistingPath(path, label);
  if (!statSync(canonical).isFile()) throw new Error(`PACKAGED_BACKEND_RESOURCE_NOT_FILE: ${label}`);
  return canonical;
}

function assertRegularFileInside(parent: string, path: string, label: string): string {
  return assertInside(parent, assertRegularFile(path, label), label);
}

function assertDirectory(path: string, label: string): string {
  const canonical = canonicalExistingPath(path, label);
  if (!statSync(canonical).isDirectory()) throw new Error(`PACKAGED_BACKEND_RESOURCE_NOT_DIRECTORY: ${label}`);
  return canonical;
}

function assertDirectoryInside(parent: string, path: string, label: string): string {
  return assertInside(parent, assertDirectory(path, label), label);
}

function isInside(parent: string, candidate: string): boolean {
  const child = relative(resolve(parent), resolve(candidate));
  return child === "" || (child !== ".." && !child.startsWith(`..${sep}`) && !isAbsolute(child));
}

function assertInside(parent: string, candidate: string, label: string): string {
  if (!isInside(parent, candidate)) throw new Error(`PACKAGED_BACKEND_RESOURCE_ESCAPE: ${label}`);
  return candidate;
}

function parseManifest(path: string): { manifest: PackagedBackendManifest; sha256: string } {
  const raw = JSON.parse(readFileSync(path, "utf8")) as unknown;
  if (!isRecord(raw)
    || raw.schema_version !== PACKAGED_BACKEND_MANIFEST_SCHEMA
    || typeof raw.source_git_sha !== "string"
    || !/^[0-9a-f]{40}$/u.test(raw.source_git_sha)
    || typeof raw.build_manifest_id !== "string"
    || raw.build_manifest_id.length === 0
    || !Array.isArray(raw.critical_files)) {
    throw new Error("PACKAGED_BACKEND_MANIFEST_INVALID");
  }
  const criticalFiles = raw.critical_files.map((entry) => {
    if (!isRecord(entry) || typeof entry.path !== "string" || typeof entry.sha256 !== "string"
      || !/^[0-9a-f]{64}$/.test(entry.sha256) || isAbsolute(entry.path)
      || entry.path.split(/[\\/]/u).some((part) => part === ".." || part.length === 0)) {
      throw new Error("PACKAGED_BACKEND_MANIFEST_INVALID");
    }
    return Object.freeze({ path: entry.path.replaceAll("\\", "/"), sha256: entry.sha256 });
  });
  return {
    manifest: Object.freeze({
      schema_version: PACKAGED_BACKEND_MANIFEST_SCHEMA,
      source_git_sha: raw.source_git_sha,
      build_manifest_id: raw.build_manifest_id,
      critical_files: Object.freeze(criticalFiles),
    }),
    sha256: sha256File(path),
  };
}

function verifyCriticalFiles(
  resourceRoot: string,
  manifest: PackagedBackendManifest,
  requiredPaths: readonly string[],
): void {
  const entries = new Map(manifest.critical_files.map((entry) => [entry.path, entry.sha256]));
  for (const relativePath of requiredPaths) {
    const expectedHash = entries.get(relativePath);
    if (!expectedHash) throw new Error(`PACKAGED_BACKEND_MANIFEST_MISSING_CRITICAL_FILE: ${relativePath}`);
    const file = assertRegularFileInside(resourceRoot, resolve(resourceRoot, relativePath), relativePath);
    if (sha256File(file) !== expectedHash) throw new Error(`PACKAGED_BACKEND_RESOURCE_HASH_MISMATCH: ${relativePath}`);
  }
}

export function resolveBackendRuntime(
  isPackaged: boolean,
  resourcesPath: string,
  source: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform,
): BackendRuntimeResolution {
  if (!isPackaged) {
    const executable = source.V3_BACKEND_PYTHON ?? source.V3_PYTHON ?? (platform === "win32" ? "python" : "python3");
    const workingDirectory = source.V3_BACKEND_WORKING_DIRECTORY
      ?? join(process.cwd(), "apps", "backend", "src");
    return Object.freeze({
      mode: "DEVELOPMENT",
      executable,
      workingDirectory,
      backendResourceRoot: "",
      pythonRoot: "",
      backendPackageRoot: workingDirectory,
      backendModule: "v3_backend.runtime.bootstrap",
      manifestPath: null,
      manifestSha256: null,
      sourceGitSha: null,
      buildManifestId: null,
    });
  }

  if (typeof resourcesPath !== "string" || resourcesPath.length === 0) {
    throw new Error("PACKAGED_BACKEND_RESOURCES_PATH_MISSING");
  }
  const resourcesRoot = canonicalExistingPath(resolve(resourcesPath), "process.resourcesPath");
  const backendResourceRoot = assertDirectoryInside(resourcesRoot, resolve(resourcesRoot, "backend-runtime"), "backend-runtime");
  const manifestPath = assertRegularFileInside(backendResourceRoot, resolve(backendResourceRoot, "runtime-manifest.json"), "runtime-manifest.json");
  const { manifest, sha256: manifestSha256 } = parseManifest(manifestPath);
  const pythonRoot = assertDirectoryInside(backendResourceRoot, resolve(backendResourceRoot, "python"), "python");
  const backendPackageRoot = assertDirectoryInside(backendResourceRoot, resolve(backendResourceRoot, "backend-package"), "backend-package");
  const executableName = platform === "win32" ? "python.exe" : "python";
  const executable = assertRegularFileInside(backendResourceRoot, resolve(pythonRoot, executableName), "python executable");
  const workingDirectory = assertDirectoryInside(backendResourceRoot, backendPackageRoot, "backend working directory");
  const bootstrapPath = resolve(backendPackageRoot, "v3_backend", "runtime", "bootstrap.py");
  const buildManifestPath = resolve(backendPackageRoot, "v3_backend", "runtime", "build_manifest.generated.json");
  const dependencyInventoryPath = resolve(backendResourceRoot, "python-dependency-inventory.json");
  verifyCriticalFiles(backendResourceRoot, manifest, [
    `python/${executableName}`,
    "backend-package/v3_backend/runtime/bootstrap.py",
    "backend-package/v3_backend/runtime/build_manifest.generated.json",
    "backend-package/packages/contracts/research_package_transport_v1.json",
    "python/LICENSE.txt",
    "python-dependency-inventory.json",
  ]);
  assertRegularFileInside(backendResourceRoot, bootstrapPath, "backend bootstrap");
  assertRegularFileInside(backendResourceRoot, buildManifestPath, "backend BuildManifest");
  assertRegularFileInside(backendResourceRoot, dependencyInventoryPath, "Python dependency inventory");
  return Object.freeze({
    mode: "PACKAGED",
    executable,
    workingDirectory,
    backendResourceRoot,
    pythonRoot,
    backendPackageRoot,
    backendModule: "v3_backend.runtime.bootstrap",
    manifestPath,
    manifestSha256,
    sourceGitSha: manifest.source_git_sha,
    buildManifestId: manifest.build_manifest_id,
  });
}
