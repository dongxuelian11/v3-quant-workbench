import { spawnSync } from "node:child_process";
import { delimiter, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const backendSource = resolve(root, "apps/backend/src");
const candidates = process.env.V3_PYTHON
  ? [[process.env.V3_PYTHON, []]]
  : process.platform === "win32"
    ? [["py", ["-3.14"]], ["python", []]]
    : [["python3", []], ["python", []]];

let python;
for (const [command, prefix] of candidates) {
  const probe = spawnSync(command, [...prefix, "--version"], { encoding: "utf8" });
  const version = `${probe.stdout ?? ""}${probe.stderr ?? ""}`.trim();
  if (probe.status === 0 && /^Python 3\.14\./.test(version)) {
    python = { command, prefix, version };
    break;
  }
}
if (!python) {
  console.error("C1 fault injection requires CPython 3.14.x; set V3_PYTHON explicitly.");
  process.exit(1);
}

const env = {
  ...process.env,
  PYTHONPATH: process.env.PYTHONPATH
    ? `${backendSource}${delimiter}${process.env.PYTHONPATH}`
    : backendSource
};

const backend = spawnSync(
  python.command,
  [
    ...python.prefix,
    "-B",
    "-m",
    "unittest",
    "apps.backend.tests.product_runtime.test_product_runtime_research",
    "apps.backend.tests.ws_e_runtime.test_runtime_transport",
    "-v"
  ],
  { cwd: root, env, encoding: "utf8" }
);
if (backend.stdout) process.stdout.write(backend.stdout);
if (backend.stderr) process.stderr.write(backend.stderr);
if (backend.status !== 0) process.exit(backend.status ?? 1);

const desktop = spawnSync(
  process.execPath,
  [
    "--test",
    "tests/ws_e_electron_runtime/product-bridge.test.mjs",
    "tests/ws_e_electron_runtime/runtime-core-shutdown.test.mjs",
    "tests/ws_e_electron_runtime/runtime-core-workspace-store.test.mjs",
    "tests/ws_e_electron_runtime/supervisor.test.mjs"
  ],
  { cwd: root, env, encoding: "utf8" }
);
if (desktop.stdout) process.stdout.write(desktop.stdout);
if (desktop.stderr) process.stderr.write(desktop.stderr);
if (desktop.status !== 0) process.exit(desktop.status ?? 1);

console.log(
  `C1 fault injection PASS (${python.version} backend worker/router matrix + Electron binding/exit/correlation/workspace matrix).`
);
