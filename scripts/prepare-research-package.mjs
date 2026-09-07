import { cp, mkdir, readdir, rm, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { basename, dirname, relative, resolve } from "node:path";
import { researchPython, root, runPython } from "./research-python.mjs";

if (process.platform !== "win32") throw new Error("Windows 安装包请在 Windows 上构建。");
const python = researchPython();
const pythonRoot = dirname(python);
if (existsSync(resolve(pythonRoot, "pyvenv.cfg")) || basename(pythonRoot).toLowerCase() === "scripts") {
  throw new Error("打包需要独立 Python 运行时；请运行 npm run setup:research 创建 runtime/research-python。");
}
runPython(python, ["-c", "import sys,qlib,alphalens,baostock,optuna,pydantic_ai,lightgbm,pyarrow; assert sys.version_info[:2] == (3,12); print('Python 3.12 research libraries ready')"]);
const staging = resolve(root, "artifacts/package-staging/backend-runtime");
if (relative(root, staging).replaceAll("\\", "/") !== "artifacts/package-staging/backend-runtime") throw new Error("Invalid package staging directory");
await rm(staging, { recursive: true, force: true });
await mkdir(resolve(staging, "backend-package/v3_backend"), { recursive: true });
await cp(pythonRoot, resolve(staging, "python"), { recursive: true, filter: (path) => basename(path) !== "__pycache__" });
await cp(resolve(root, "apps/backend/src/v3_backend/research"), resolve(staging, "backend-package/v3_backend/research"), { recursive: true, filter: (path) => basename(path) !== "__pycache__" });
await writeFile(resolve(staging, "backend-package/v3_backend/__init__.py"), '"""V3 desktop research backend."""\n');
await cp(resolve(root, "apps/backend/requirements-research.txt"), resolve(staging, "requirements-research.txt"));
// Renderer modules are bundled by Vite. Keep their upstream license texts in the installer.
for (const name of ["react", "react-dom", "scheduler", "dockview-react", "dockview", "dockview-core", "@tanstack/react-table", "@tanstack/table-core", "monaco-editor", "echarts", "zrender", "klinecharts", "tslib"]) {
  const source = resolve(root, "node_modules", name);
  if (!existsSync(source)) continue;
  const destination = resolve(staging, "frontend-licenses", name.replaceAll("/", "-"));
  await mkdir(destination, { recursive: true });
  for (const entry of await readdir(source, { withFileTypes: true })) {
    if (entry.isFile() && /license|notice/i.test(entry.name)) await cp(resolve(source, entry.name), resolve(destination, entry.name));
  }
}
console.log(`Windows 研究运行时已准备：${staging}`);
