import { rm } from "node:fs/promises";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(import.meta.dirname, "..");
await rm(resolve(root, "dist"), { recursive: true, force: true });
function run(command, args) {
  const result = spawnSync(command, args, { cwd: root, stdio: "inherit", shell: process.platform === "win32" });
  if (result.status !== 0) process.exit(result.status ?? 1);
}
run(process.platform === "win32" ? "tsc.cmd" : "tsc", ["-p", "tsconfig.json"]);
run(process.platform === "win32" ? "vite.cmd" : "vite", ["build", "--config", "vite.config.mjs"]);
console.log(`Built Electron 39 + React/Vite renderer to ${resolve(root, "dist")}`);
