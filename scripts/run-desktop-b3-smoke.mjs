import { access, mkdir, mkdtemp, rename, writeFile } from "node:fs/promises";
import { delimiter, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";

// Targeted Desktop<->B3 integration smoke runner.
//
// Test-setup boundary (task section 17): the setup step prepares a canonical
// Project + BacktestRunSpec inside a TEMP product storage root through the
// accepted owner APIs. Electron then boots the normal production bootstrap
// with V3_PRODUCT_STORAGE_ROOT=<temp> and runs exclusively on the LIVE B3
// path — no renderer seeding, no LIVE auto-seed, no development fixture.

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

let backendPython = process.env.V3_BACKEND_PYTHON ?? process.env.V3_PYTHON;
if (!backendPython && process.platform === "win32") {
  const probe = spawnSync("py", ["-3.14", "-c", "import sys; print(sys.executable)"], { encoding: "utf8" });
  if (probe.status === 0) backendPython = probe.stdout.trim();
}
backendPython ||= process.platform === "win32" ? "python" : "python3";

// --- test-only canonical seed (accepted owner APIs, temp storage) --------
const storageRoot = await mkdtemp(resolve(tmpdir(), "v3-desktop-b3-smoke-"));
const setup = spawnSync(backendPython, [resolve(root, "scripts/product_runtime_smoke_python.py"), "setup", storageRoot], {
  cwd: resolve(root, "apps/backend/src"),
  encoding: "utf8",
  env: { ...process.env, PYTHONPATH: `${root}${delimiter}${resolve(root, "apps/backend/src")}` }
});
if (setup.status !== 0) {
  console.error(`desktop-b3 smoke setup failed: ${setup.stderr}`);
  process.exit(1);
}
const seed = JSON.parse(setup.stdout.trim());
console.log(`desktop-b3 smoke seed: project=${seed.project_id} run_spec=${seed.run_spec_id} storage=${storageRoot}`);

const runId = `${Date.now().toString(36)}-${Math.floor(Math.random() * 1296).toString(36)}`;
const userDataRel = `deliverables/electron-user-data-desktop-b3-${runId}`;
const records = [];
// Stale-binding preparation (T5): with a valid persisted binding in place,
// remove the canonical desktop session row so the next restart fails
// canonical re-validation (restoreSession NOT_FOUND) and must record
// BINDING_STALE instead of surfacing PROJECT_BOUND.
function dropDesktopSessions() {
  const drop = spawnSync(backendPython, ["-c",
    "import sqlite3,sys\nc=sqlite3.connect(sys.argv[1])\nc.execute('DELETE FROM desktop_session')\nc.commit()\nc.close()\n",
    `${storageRoot}/catalog.sqlite3`], { encoding: "utf8" });
  if (drop.status !== 0) throw new Error(`failed to drop desktop_session rows: ${drop.stderr}`);
}
for (const phase of ["capture", "restart", "stale-restart"]) {
  if (phase === "stale-restart") dropDesktopSessions();
  if (process.platform !== "win32") {
    const userDataDir = resolve(root, userDataRel);
    for (const name of ["SingletonLock", "SingletonSocket", "SingletonCookie"]) {
      try { await rename(join(userDataDir, name), join(userDataDir, `${name}.stale-${phase}`)); } catch { /* absent */ }
    }
  }
  const result = spawnSync(electron, ["--no-sandbox", "--no-zygote", resolve(root, "scripts", "desktop-b3-electron-smoke.cjs")], {
    cwd: root,
    encoding: "utf8",
    shell: process.platform === "win32",
    env: {
      ...process.env,
      V3_SMOKE_PHASE: phase,
      V3_SMOKE_USER_DATA: userDataRel,
      V3_PRODUCT_STORAGE_ROOT: storageRoot,
      V3_BACKEND_PYTHON: backendPython,
      V3_SMOKE_PROJECT_ID: seed.project_id,
      V3_SMOKE_PCR_ID: seed.project_context_revision_id,
      V3_SMOKE_RUN_SPEC_ID: seed.run_spec_id
      // V3_AGENT_EVIDENCE_MODE intentionally unset: LIVE product path only.
    }
  });
  records.push({ phase, exitCode: result.status, stdout: result.stdout, stderr: result.stderr });
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  if (result.status !== 0) {
    await writeFile(resolve(root, "deliverables", "raw", "desktop-b3-electron-smoke.json"), JSON.stringify(records, null, 2));
    process.exit(result.status ?? 1);
  }
  const combined = `${result.stdout ?? ""}\n${result.stderr ?? ""}`;
  if (!combined.includes(`[desktop-b3-smoke] ${phase}:`)) {
    console.error(`desktop-b3 smoke phase ${phase} did not report its golden-path stage`);
    await writeFile(resolve(root, "deliverables", "raw", "desktop-b3-electron-smoke.json"), JSON.stringify(records, null, 2));
    process.exit(1);
  }
  if (!combined.includes("GRACEFUL_SHUTDOWN_SUCCESS")) {
    console.error(`desktop-b3 smoke phase ${phase} did not complete the graceful shutdown handshake`);
    await writeFile(resolve(root, "deliverables", "raw", "desktop-b3-electron-smoke.json"), JSON.stringify(records, null, 2));
    process.exit(1);
  }
  if (combined.includes("FORCED_SHUTDOWN_FALLBACK")) {
    console.error(`desktop-b3 smoke phase ${phase} fell back to forced shutdown`);
    await writeFile(resolve(root, "deliverables", "raw", "desktop-b3-electron-smoke.json"), JSON.stringify(records, null, 2));
    process.exit(1);
  }
  if (combined.includes("DEVELOPMENT_INTEGRATION_FIXTURE")) {
    console.error(`desktop-b3 smoke phase ${phase} touched the development fixture on the LIVE path`);
    await writeFile(resolve(root, "deliverables", "raw", "desktop-b3-electron-smoke.json"), JSON.stringify(records, null, 2));
    process.exit(1);
  }
}
await writeFile(resolve(root, "deliverables", "raw", "desktop-b3-electron-smoke.json"), JSON.stringify(records, null, 2));
console.log("Desktop<->B3 integration smoke PASS: LIVE bind, existing canonical RunSpec execution, Task/Result/Artifact canonical reads, graceful shutdown and restart recovery with stable identities");
