import { rm } from "node:fs/promises";
import { relative, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(import.meta.dirname, "..");
const output = resolve(root, "dist");
if (relative(root, output) !== "dist") throw new Error("Invalid build output directory");
await rm(output, { recursive: true, force: true });
function run(script, args) {
  const result = spawnSync(process.execPath, [resolve(root, script), ...args], { cwd: root, stdio: "inherit", windowsHide: true });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
run("node_modules/typescript/bin/tsc", ["-p", "tsconfig.json"]);
run("node_modules/typescript/bin/tsc", ["-p", "tsconfig.renderer.json"]);
run("node_modules/vite/bin/vite.js", ["build", "--config", "vite.config.mjs"]);
console.log(`Built Electron 39 + React/Vite renderer to ${resolve(root, "dist")}`);
