import { createServer } from "vite";
import { createRequire } from "node:module";
import { spawn, spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { root } from "./research-python.mjs";

const require = createRequire(import.meta.url);
const compile = spawnSync(process.execPath, [resolve(root, "node_modules/typescript/bin/tsc"), "-p", "tsconfig.json"], { cwd: root, stdio: "inherit", windowsHide: true });
if (compile.status !== 0) process.exit(compile.status ?? 1);
const server = await createServer({ configFile: resolve(root, "vite.config.mjs"), server: { host: "127.0.0.1", port: 5178, strictPort: false } });
await server.listen();
const environment = { ...process.env, V3_DEV_SERVER_URL: server.resolvedUrls.local[0] };
delete environment.ELECTRON_RUN_AS_NODE;
const desktop = spawn(require("electron"), [root], { cwd: root, stdio: "inherit", env: environment, windowsHide: true });
desktop.once("exit", async (code) => { await server.close(); process.exit(code ?? 0); });
desktop.once("error", async (error) => { console.error(error); await server.close(); process.exit(1); });
process.once("SIGINT", () => desktop.kill());
