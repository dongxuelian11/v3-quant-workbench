import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { test } from "node:test";

import { resolveBackendRuntime } from "../../dist/apps/desktop/src/main/backendRuntime/runtimeResolver.js";
import { sanitizedBackendEnvironment } from "../../dist/apps/desktop/src/main/backendRuntime/processFactory.js";

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

async function writeFixture({ corrupt = false, manifest = undefined } = {}) {
  const root = await mkdtemp(join(tmpdir(), "v3-packaged-runtime-resolver-"));
  const resourcesPath = join(root, "resources");
  const backendResourceRoot = join(resourcesPath, "backend-runtime");
  const files = new Map([
    ["python/python.exe", Buffer.from("python-runtime")],
    ["backend-package/v3_backend/runtime/bootstrap.py", Buffer.from("bootstrap")],
    ["backend-package/v3_backend/runtime/build_manifest.generated.json", Buffer.from("{\"build\":true}")],
    ["backend-package/packages/contracts/research_package_transport_v1.json", Buffer.from("{\"schema\":\"test\"}")],
    ["python/LICENSE.txt", Buffer.from("Python license")],
    ["python-dependency-inventory.json", Buffer.from("{\"dependency_count\":0}")],
  ]);
  for (const [relativePath, bytes] of files) {
    const target = join(backendResourceRoot, relativePath);
    await mkdir(resolve(target, ".."), { recursive: true });
    await writeFile(target, corrupt && relativePath === "python/python.exe" ? Buffer.from("corrupted") : bytes);
  }
  const criticalFiles = [...files].map(([relativePath, bytes]) => ({
    path: relativePath,
    sha256: sha256(bytes),
  }));
  const manifestValue = manifest ?? {
    schema_version: "v3.packaged-backend/1.0.0",
    source_git_sha: "a36a7f977a27673adde48fd4216776644d38fcf1",
    build_manifest_id: "bmanifest_sha256_test",
    critical_files: criticalFiles,
  };
  await writeFile(
    join(backendResourceRoot, "runtime-manifest.json"),
    JSON.stringify(manifestValue),
  );
  return {
    root,
    resourcesPath,
    backendResourceRoot,
    pythonRoot: join(backendResourceRoot, "python"),
  };
}

async function withFixture(options, callback) {
  const fixture = await writeFixture(options);
  try {
    return await callback(fixture);
  } finally {
    await rm(fixture.root, { recursive: true, force: true });
  }
}

test("development mode preserves explicit development discovery", () => {
  const runtime = resolveBackendRuntime(false, "ignored", {
    V3_BACKEND_PYTHON: "C:\\dev\\venv\\python.exe",
    V3_BACKEND_WORKING_DIRECTORY: "C:\\repo\\apps\\backend\\src",
  }, "win32");

  assert.equal(runtime.mode, "DEVELOPMENT");
  assert.equal(runtime.executable, "C:\\dev\\venv\\python.exe");
  assert.equal(runtime.workingDirectory, "C:\\repo\\apps\\backend\\src");
  assert.equal(runtime.backendResourceRoot, "");
});

test("packaged mode resolves only verified resources and ignores development overrides", async () => {
  await withFixture({}, async (fixture) => {
    const runtime = resolveBackendRuntime(true, fixture.resourcesPath, {
      V3_BACKEND_PYTHON: "C:\\developer\\python.exe",
      V3_PYTHON: "C:\\system\\python.exe",
      V3_BACKEND_WORKING_DIRECTORY: "C:\\repo\\apps\\backend\\src",
    }, "win32");

    assert.equal(runtime.mode, "PACKAGED");
    assert.equal(runtime.executable, join(fixture.pythonRoot, "python.exe"));
    assert.equal(runtime.workingDirectory, join(fixture.backendResourceRoot, "backend-package"));
    assert.equal(runtime.backendResourceRoot, fixture.backendResourceRoot);
    assert.equal(runtime.sourceGitSha, "a36a7f977a27673adde48fd4216776644d38fcf1");
    assert.equal(runtime.buildManifestId, "bmanifest_sha256_test");
    assert.equal(runtime.backendModule, "v3_backend.runtime.bootstrap");
    assert.equal(await readFile(runtime.manifestPath, "utf8").then((value) => value.includes("bmanifest_sha256_test")), true);
  });
});

test("packaged resolver rejects a missing runtime root", async () => {
  assert.throws(
    () => resolveBackendRuntime(true, join(tmpdir(), "v3-missing-packaged-resources"), {}, "win32"),
    /PACKAGED_BACKEND_RESOURCE_MISSING/,
  );
});

test("packaged resolver rejects a corrupt critical resource", async () => {
  await withFixture({ corrupt: true }, async (fixture) => {
    assert.throws(
      () => resolveBackendRuntime(true, fixture.resourcesPath, {}, "win32"),
      /PACKAGED_BACKEND_RESOURCE_HASH_MISMATCH: python\/python\.exe/,
    );
  });
});

test("packaged resolver rejects unsafe manifest paths", async () => {
  await withFixture({
    manifest: {
      schema_version: "v3.packaged-backend/1.0.0",
      source_git_sha: "a36a7f977a27673adde48fd4216776644d38fcf1",
      build_manifest_id: "bmanifest_sha256_test",
      critical_files: [{ path: "../outside.txt", sha256: "0".repeat(64) }],
    },
  }, async (fixture) => {
    assert.throws(
      () => resolveBackendRuntime(true, fixture.resourcesPath, {}, "win32"),
      /PACKAGED_BACKEND_MANIFEST_INVALID/,
    );
  });
});

test("packaged process environment pins shipped runtime and strips development overrides", async () => {
  await withFixture({}, async (fixture) => {
    const environment = sanitizedBackendEnvironment({
      PATH: "scrubbed-path",
      APPDATA: "C:\\user\\appdata",
      LOCALAPPDATA: "C:\\user\\localappdata",
      V3_PRODUCT_STORAGE_ROOT: "C:\\user-data\\product",
      V3_BACKEND_PYTHON: "C:\\developer\\python.exe",
      V3_PYTHON: "C:\\system\\python.exe",
      V3_BACKEND_WORKING_DIRECTORY: "C:\\repo\\apps\\backend\\src",
    }, fixture.pythonRoot, fixture.backendResourceRoot);

    assert.equal(environment.PYTHONHOME, fixture.pythonRoot);
    assert.equal(environment.PYTHONNOUSERSITE, "1");
    assert.equal(environment.PYTHONDONTWRITEBYTECODE, "1");
    assert.equal(environment.V3_BACKEND_RUNTIME_MODE, "PACKAGED");
    assert.equal("V3_PRODUCT_STORAGE_ROOT" in environment, false);
    assert.equal(
      environment.V3_RESEARCH_PACKAGE_TRANSPORT_PATH,
      join(fixture.backendResourceRoot, "backend-package", "packages", "contracts", "research_package_transport_v1.json"),
    );
    assert.equal("V3_BACKEND_PYTHON" in environment, false);
    assert.equal("V3_PYTHON" in environment, false);
    assert.equal("V3_BACKEND_WORKING_DIRECTORY" in environment, false);
  });
});
