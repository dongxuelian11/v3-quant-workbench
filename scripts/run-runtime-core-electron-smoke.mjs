import { access, mkdir, rename, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(import.meta.dirname, "..");
const electronName = process.platform === "win32" ? "electron.cmd" : "electron";
const electronCandidates = [
  resolve(root, "node_modules", ".bin", electronName),
  resolve(root, "..", "..", "..", "node_modules", ".bin", electronName)
];
let electron = process.env.V3_ELECTRON_BINARY;
if (!electron) {
  for (const candidate of electronCandidates) {
    try { await access(candidate); electron = candidate; break; } catch { /* try the shared primary-workspace dependency install */ }
  }
  if (!electron) await access(electronCandidates[0]);
}
await mkdir(resolve(root, "deliverables", "raw"), { recursive: true });
let backendPython = process.env.V3_BACKEND_PYTHON;
if (!backendPython && process.platform === "win32") {
  const probe = spawnSync("py", ["-3.14", "-c", "import sys; print(sys.executable)"], { encoding: "utf8" });
  if (probe.status === 0) backendPython = probe.stdout.trim();
}
backendPython ||= process.platform === "win32" ? "python" : "python3";
const records = [];
const runId = `${Date.now().toString(36)}-${Math.floor(Math.random() * 1296).toString(36)}`;
const productStorageRoot = process.env.V3_PRODUCT_STORAGE_ROOT
  ?? resolve(root, `deliverables/product-storage-runtime-core-${runId}`);
await mkdir(productStorageRoot, { recursive: true });
const electronArgs = [
  // Containerized Linux runners need these to start Chromium at all; they
  // are accepted no-ops on Windows and mirror the existing FR-1 smoke.
  "--no-sandbox",
  "--no-zygote",
  resolve(root, "scripts", "runtime-core-electron-smoke.cjs")
];
for (const phase of ["capture", "restart"]) {
  // POSIX-only: Chromium's single-instance lock files live in userData and
  // are cleaned up at exit. On mounts that deny unlink (e.g. this Linux
  // sandbox) the cleanup fails and the next phase would be mis-detected as
  // a secondary instance, so stale lock files are renamed aside between
  // sequential phases. Windows uses a named mutex and has no such files.
  if (process.platform !== "win32") {
    const userDataDir = resolve(root, `deliverables/electron-user-data-runtime-core-${runId}`);
    for (const name of ["SingletonLock", "SingletonSocket", "SingletonCookie"]) {
      try { await rename(join(userDataDir, name), join(userDataDir, `${name}.stale-${phase}`)); } catch { /* absent */ }
    }
  }
  const result = spawnSync(electron, electronArgs, {
    cwd: root,
    encoding: "utf8",
    shell: process.platform === "win32",
    env: {
      ...process.env,
      V3_SMOKE_PHASE: phase,
      V3_SMOKE_USER_DATA: `deliverables/electron-user-data-runtime-core-${runId}`,
      V3_AGENT_EVIDENCE_MODE: "DEVELOPMENT_INTEGRATION_FIXTURE",
      V3_BACKEND_PYTHON: backendPython,
      V3_PRODUCT_STORAGE_ROOT: productStorageRoot
    }
  });
  records.push({ phase, exitCode: result.status, stdout: result.stdout, stderr: result.stderr });
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  if (result.status !== 0) {
    await writeFile(resolve(root, "deliverables", "raw", "runtime-core-electron-smoke.json"), JSON.stringify(records, null, 2));
    process.exit(result.status ?? 1);
  }
  const combined = `${result.stdout ?? ""}\n${result.stderr ?? ""}`;
  if (!combined.includes("GRACEFUL_SHUTDOWN_SUCCESS")) {
    console.error(`Electron runtime-core smoke phase ${phase} did not complete the graceful shutdown handshake`);
    await writeFile(resolve(root, "deliverables", "raw", "runtime-core-electron-smoke.json"), JSON.stringify(records, null, 2));
    process.exit(1);
  }
  if (combined.includes("FORCED_SHUTDOWN_FALLBACK")) {
    console.error(`Electron runtime-core smoke phase ${phase} fell back to forced shutdown`);
    await writeFile(resolve(root, "deliverables", "raw", "runtime-core-electron-smoke.json"), JSON.stringify(records, null, 2));
    process.exit(1);
  }
}
await writeFile(resolve(root, "deliverables", "raw", "runtime-core-electron-smoke.json"), JSON.stringify(records, null, 2));
console.log("Electron runtime-core smoke: handshake, replay, command idempotency, durable cursor, graceful shutdown and restart persistence PASS");
