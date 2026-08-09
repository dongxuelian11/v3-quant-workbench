import { cp, mkdir, rm } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(import.meta.dirname, "..");
const dist = resolve(root, "dist");
await rm(dist, { recursive: true, force: true });
await mkdir(dirname(dist), { recursive: true });

const tsc = spawnSync(process.platform === "win32" ? "tsc.cmd" : "tsc", ["-p", "tsconfig.json"], {
  cwd: root,
  stdio: "inherit",
  shell: process.platform === "win32"
});
if (tsc.status !== 0) process.exit(tsc.status ?? 1);

const rendererTsc = spawnSync(process.platform === "win32" ? "tsc.cmd" : "tsc", ["-p", "tsconfig.renderer.json"], {
  cwd: root,
  stdio: "inherit",
  shell: process.platform === "win32"
});
if (rendererTsc.status !== 0) process.exit(rendererTsc.status ?? 1);

const sourceRenderer = resolve(root, "apps/desktop/src/renderer");
const outputRenderer = resolve(dist, "apps/desktop/src/renderer");
await mkdir(outputRenderer, { recursive: true });
await cp(resolve(sourceRenderer, "index.html"), resolve(outputRenderer, "index.html"));
await cp(resolve(sourceRenderer, "styles.css"), resolve(outputRenderer, "styles.css"));
console.log(`Built Electron shell to ${dist}`);
