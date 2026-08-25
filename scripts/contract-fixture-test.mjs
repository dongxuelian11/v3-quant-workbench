import { spawnSync } from "node:child_process";
import { delimiter, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const backendSource = resolve(root, "apps/backend/src");
const candidates = process.env.V3_PYTHON
  ? [[process.env.V3_PYTHON, []]]
  : process.platform === "win32"
    ? [["py", ["-3.14"]], ["python", []]]
    : [["python3", []], ["python", []]];

let selected;
for (const [command, prefix] of candidates) {
  const probe = spawnSync(command, [...prefix, "--version"], { encoding: "utf8" });
  const version = `${probe.stdout ?? ""}${probe.stderr ?? ""}`.trim();
  if (probe.status === 0 && /^Python 3\.14\./.test(version)) {
    selected = { command, prefix, version };
    break;
  }
}

if (!selected) {
  console.error("Contract fixture validation requires CPython 3.14.x. Set V3_PYTHON to an explicit interpreter.");
  process.exit(1);
}

const env = {
  ...process.env,
  PYTHONDONTWRITEBYTECODE: "1",
  PYTHONPATH: process.env.PYTHONPATH
    ? `${backendSource}${delimiter}${process.env.PYTHONPATH}`
    : backendSource,
};
const result = spawnSync(selected.command, [
  ...selected.prefix,
  "-B",
  "-m",
  "unittest",
  "apps.backend.tests.ws_a_contracts.test_contract_seed",
  "apps.backend.tests.ws_a_contracts.test_hardening",
  "-v",
], { cwd: root, env, stdio: "inherit" });

if (result.status !== 0) process.exit(result.status ?? 1);
console.log(`Frozen contract fixtures and code-generation drift checks passed with ${selected.version}.`);
