import { cp, mkdir, readdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { basename, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { root, runtimeRoot, researchPython, runPython } from "./research-python.mjs";

const pythonFlag = process.argv.indexOf("--python");
const requested = pythonFlag >= 0 ? process.argv[pythonFlag + 1] : process.env.V3_RESEARCH_BASE_PYTHON;
const destination = resolve(runtimeRoot, process.platform === "win32" ? "python.exe" : "bin/python3");
if (!existsSync(destination) && !process.env.V3_RESEARCH_PYTHON) {
  const candidates = requested ? [[requested, []]] : [["py", ["-3.12"]], ["python3.12", []], ["python", []]];
  let base;
  for (const [command, prefix] of candidates) {
    const probe = spawnSync(command, [...prefix, "-c", "import json,sys; print(json.dumps({'version':list(sys.version_info[:2]),'root':sys.base_prefix,'executable':sys.executable}))"], { encoding: "utf8", windowsHide: true });
    if (probe.status !== 0) continue;
    const value = JSON.parse(probe.stdout.trim());
    if (value.version.join(".") === "3.12") { base = value; break; }
  }
  if (!base) throw new Error("请安装 Python 3.12，或运行 npm run setup:research -- --python <Python 3.12 路径>。");
  await mkdir(runtimeRoot, { recursive: true });
  if (process.platform === "win32") {
    // Copy the interpreter, standard library and license into a relocatable app runtime.
    for (const entry of await readdir(base.root, { withFileTypes: true })) {
      if (!entry.isDirectory() || ["DLLs", "Lib"].includes(entry.name)) {
        await cp(resolve(base.root, entry.name), resolve(runtimeRoot, entry.name), {
          recursive: entry.isDirectory(),
          filter: (path) => !["site-packages", "__pycache__"].includes(basename(path)),
        });
      }
    }
    runPython(destination, ["-m", "ensurepip"]);
  } else runPython(base.executable, ["-m", "venv", runtimeRoot]);
}
const python = researchPython();
runPython(python, ["-c", "import sys; assert sys.version_info[:2] == (3,12), 'V3 requires Python 3.12'"]);
runPython(python, ["-m", "pip", "install", "setuptools", "wheel", "--disable-pip-version-check", "--no-warn-script-location"]);
runPython(python, ["-m", "pip", "install", "-r", resolve(root, "apps/backend/requirements-research.txt"), "--no-build-isolation", "--cache-dir", resolve(root, ".cache/pip"), "--disable-pip-version-check", "--no-warn-script-location"]);
console.log(`研究环境已准备：${python}`);
