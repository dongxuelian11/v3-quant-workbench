import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";

export const root = resolve(import.meta.dirname, "..");
export const runtimeRoot = resolve(root, "runtime/research-python");
export function researchPython() {
  const candidate = process.env.V3_RESEARCH_PYTHON ?? resolve(runtimeRoot, process.platform === "win32" ? "python.exe" : "bin/python3");
  if (!existsSync(candidate)) throw new Error("Python 3.12 研究环境尚未准备，请先运行 npm run setup:research。");
  return candidate;
}
export function runPython(python, args, options = {}) {
  const result = spawnSync(python, args, {
    cwd: root, stdio: "inherit", windowsHide: true,
    env: { ...process.env, PYTHONUTF8: "1", PYTHONDONTWRITEBYTECODE: "1", MPLBACKEND: "Agg", PYTHONPATH: resolve(root, "apps/backend/src") },
    ...options,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`Python 命令失败（退出码 ${result.status}）`);
  return result;
}
