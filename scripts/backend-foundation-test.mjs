import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";
import { delimiter, dirname, join, relative, resolve, sep } from "node:path";

const root = resolve(import.meta.dirname, "..");
const backendSource = resolve(root, "apps/backend/src");
const testsRoot = resolve(root, "apps/backend/tests");
const testsTop = "apps/backend/tests";
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
  console.error("Canonical Backend Foundation tests require CPython 3.14.x. Set V3_PYTHON to an explicit interpreter when it is not on PATH.");
  process.exit(1);
}

console.log(`Using ${selected.version}; authority patch is 3.14.7.`);
const env = {
  ...process.env,
  PYTHONPATH: process.env.PYTHONPATH
    ? `${backendSource}${delimiter}${process.env.PYTHONPATH}`
    : backendSource
};

// Recursive deterministic discovery: every test_*.py under apps/backend/tests
// enters the execution inventory without any manual allowlist.
function collectTestFiles(directory) {
  const found = [];
  for (const entry of readdirSync(directory, { withFileTypes: true }).sort((left, right) => left.name.localeCompare(right.name))) {
    const full = join(directory, entry.name);
    if (entry.isDirectory()) found.push(...collectTestFiles(full));
    else if (entry.isFile() && entry.name.startsWith("test_") && entry.name.endsWith(".py")) found.push(full);
  }
  return found;
}

const discoveredFiles = collectTestFiles(testsRoot).map((file) => relative(root, file).split(sep).join("/")).sort();
const suites = [...new Set(discoveredFiles.map((file) => dirname(file)))].sort();
const filesBySuite = new Map(suites.map((suite) => [suite, discoveredFiles.filter((file) => dirname(file) === suite)]));

console.log(`Discovered ${discoveredFiles.length} backend test files across ${suites.length} suites (no manual allowlist).`);
for (const file of discoveredFiles) console.log(`  discovered ${file}`);

const escapeRegex = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const executedSuites = [];
let ranTotal = 0;

for (const suite of suites) {
  const args = [
    ...selected.prefix,
    "-B",
    "-m",
    "unittest",
    "discover",
    "-s",
    suite,
    "-t",
    testsTop,
    "-p",
    "test_*.py",
    "-v"
  ];
  const result = spawnSync(selected.command, args, { cwd: root, env, encoding: "utf8" });
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  if (result.status !== 0) {
    console.error(`Backend suite failed: ${suite} (exit ${String(result.status)})`);
    process.exit(result.status ?? 1);
  }
  const output = `${result.stdout ?? ""}\n${result.stderr ?? ""}`;
  const unloaded = filesBySuite.get(suite).filter((file) => {
    const stem = file.slice(file.lastIndexOf("/") + 1, -3);
    return !new RegExp(`\\b${escapeRegex(stem)}\\s*(?:\\(|\\.)`).test(output);
  });
  if (unloaded.length > 0) {
    console.error(`Discovered backend test file(s) did not enter the execution inventory for ${suite}: ${unloaded.join(", ")}`);
    process.exit(1);
  }
  const ran = /Ran (\d+) tests?/.exec(output)?.[1] ?? "?";
  ranTotal += Number.isFinite(Number(ran)) ? Number(ran) : 0;
  executedSuites.push(suite);
  console.log(`  executed ${suite} (${filesBySuite.get(suite).length} file(s), ${ran} test case(s))`);
}

console.log(`Executed inventory: ${executedSuites.length}/${suites.length} suites, ${discoveredFiles.length}/${discoveredFiles.length} discovered files, ${ranTotal} test cases total.`);
if (executedSuites.length !== suites.length) {
  console.error(`Execution inventory mismatch: ${executedSuites.length} executed vs ${suites.length} discovered suites.`);
  process.exit(1);
}

const compile = spawnSync(
  selected.command,
  [...selected.prefix, "-m", "compileall", "-q", "apps/backend/src", "apps/backend/tests"],
  { cwd: root, env, stdio: "inherit" }
);
if (compile.status !== 0) process.exit(compile.status ?? 1);
console.log(`Canonical Backend Foundation suites (${executedSuites.length} discovered, ${ranTotal} test cases) and compile gate passed.`);
