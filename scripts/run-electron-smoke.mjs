import { access, mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(import.meta.dirname, "..");
const electronCli = resolve(root, "node_modules", ".bin", process.platform === "win32" ? "electron.cmd" : "electron");
try { await access(electronCli); } catch { console.error("Electron binary not installed; run npm install first."); process.exit(2); }
const smokeScript = resolve(root, "scripts", "electron-smoke.cjs");
const result = spawnSync(electronCli, [smokeScript], { cwd: root, stdio: "inherit", shell: process.platform === "win32" });
process.exit(result.status ?? 1);

