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
  console.error("Alpha research smoke requires CPython 3.14.x. Set V3_PYTHON to an explicit interpreter.");
  process.exit(1);
}

console.log(`Using ${selected.version} for the bounded PRE_ALPHA Alpha research smoke.`);
const environment = {
  ...process.env,
  PYTHONPATH: process.env.PYTHONPATH
    ? `${backendSource}${delimiter}${process.env.PYTHONPATH}`
    : backendSource
};
const result = spawnSync(
  selected.command,
  [...selected.prefix, "-B", "-m", "apps.backend.tests.round5_s_alpha_mining.smoke"],
  { cwd: root, env: environment, stdio: "inherit" }
);
process.exit(result.status ?? 1);
