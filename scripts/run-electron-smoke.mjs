import { access, mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(import.meta.dirname, "..");
const electron = resolve(root, "node_modules", ".bin", process.platform === "win32" ? "electron.cmd" : "electron");
await access(electron); await mkdir(resolve(root, "deliverables", "raw"), { recursive: true });
const records = [];
for (const phase of ["capture", "restart"]) {
  const result = spawnSync(electron, [resolve(root, "scripts", "electron-smoke.cjs")], { cwd: root, encoding: "utf8", shell: process.platform === "win32", env: { ...process.env, V3_SMOKE_PHASE: phase } });
  records.push({ phase, exitCode: result.status, stdout: result.stdout, stderr: result.stderr });
  if (result.stdout) process.stdout.write(result.stdout); if (result.stderr) process.stderr.write(result.stderr);
  if (result.status !== 0) { await writeFile(resolve(root, "deliverables", "raw", "electron-smoke.json"), JSON.stringify(records, null, 2)); process.exit(result.status ?? 1); }
}
await writeFile(resolve(root, "deliverables", "raw", "electron-smoke.json"), JSON.stringify(records, null, 2));
console.log("Electron production smoke and restart persistence PASS");
