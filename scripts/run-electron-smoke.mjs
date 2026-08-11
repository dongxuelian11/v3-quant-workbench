import { access, mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(import.meta.dirname, "..");
const electronName = process.platform === "win32" ? "electron.cmd" : "electron";
const electronCandidates = [
  resolve(root, "node_modules", ".bin", electronName),
  resolve(root, "..", "..", "..", "node_modules", ".bin", electronName)
];
let electron;
for (const candidate of electronCandidates) {
  try { await access(candidate); electron = candidate; break; } catch { /* try the shared primary-workspace dependency install */ }
}
if (!electron) await access(electronCandidates[0]);
await mkdir(resolve(root, "deliverables", "raw"), { recursive: true });
let backendPython = process.env.V3_BACKEND_PYTHON;
if (!backendPython && process.platform === "win32") {
  const probe = spawnSync("py", ["-3.14", "-c", "import sys; print(sys.executable)"], { encoding: "utf8" });
  if (probe.status === 0) backendPython = probe.stdout.trim();
}
backendPython ||= process.platform === "win32" ? "python" : "python3";
const records = [];
for (const phase of ["capture", "restart"]) {
  const result = spawnSync(electron, [resolve(root, "scripts", "electron-smoke.cjs")], { cwd: root, encoding: "utf8", shell: process.platform === "win32", env: { ...process.env, V3_SMOKE_PHASE: phase, V3_AGENT_EVIDENCE_MODE: "DEVELOPMENT_INTEGRATION_FIXTURE", V3_BACKEND_PYTHON: backendPython } });
  records.push({ phase, exitCode: result.status, stdout: result.stdout, stderr: result.stderr });
  if (result.stdout) process.stdout.write(result.stdout); if (result.stderr) process.stderr.write(result.stderr);
  if (result.status !== 0) { await writeFile(resolve(root, "deliverables", "raw", "electron-smoke.json"), JSON.stringify(records, null, 2)); process.exit(result.status ?? 1); }
}
await writeFile(resolve(root, "deliverables", "raw", "electron-smoke.json"), JSON.stringify(records, null, 2));
console.log("Electron canonical Round 3 integration smoke and restart persistence PASS");
