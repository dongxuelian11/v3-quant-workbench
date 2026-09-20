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
runPython(python, ["-c", "import sys,qlib,alphalens,baostock,optuna,pydantic_ai,lightgbm,pyarrow,cvxpy,scipy,pypinyin,pdfplumber; from sklearn.covariance import LedoitWolf; assert sys.version_info[:2] == (3,12); print('Python 3.12 research libraries ready')"]);
if (!existsSync(resolve(pythonRoot, "tdx-site/mootdx"))) throw new Error("缺少独立通达信适配依赖，请运行 npm run setup:research。");
runPython(python, ["-c", "import sys; from pathlib import Path; sys.path.insert(0,str(Path(sys.executable).parent/'tdx-site')); from mootdx.quotes import Quotes; from mootdx.reader import Reader; print('Isolated TDX adapter ready')"]);
const staging = resolve(root, "artifacts/package-staging/backend-runtime");
if (relative(root, staging).replaceAll("\\", "/") !== "artifacts/package-staging/backend-runtime") throw new Error("Invalid package staging directory");
await rm(staging, { recursive: true, force: true });
await mkdir(resolve(staging, "backend-package/v3_backend"), { recursive: true });
await cp(pythonRoot, resolve(staging, "python"), { recursive: true, filter: (path) => !["__pycache__", "report-ocr-site"].includes(basename(path)) });
await cp(resolve(root, "apps/backend/src/v3_backend/research"), resolve(staging, "backend-package/v3_backend/research"), { recursive: true, filter: (path) => basename(path) !== "__pycache__" });
await writeFile(resolve(staging, "backend-package/v3_backend/__init__.py"), '"""V3 desktop research backend."""\n');
await cp(resolve(root, "apps/backend/requirements-research.txt"), resolve(staging, "requirements-research.txt"));
await cp(resolve(root, "apps/backend/requirements-tdx.txt"), resolve(staging, "requirements-tdx.txt"));
await mkdir(resolve(staging, "formula"), { recursive: true });
await cp(resolve(root, "scripts/hq-formula.cjs"), resolve(staging, "formula/hq-formula.cjs"));
await cp(resolve(root, "node_modules/hqchart/src/jscommon/umychart.node/umychart.node.js"), resolve(staging, "formula/hqchart.node.js"));
// Renderer modules are bundled by Vite. Keep their upstream license texts in the installer.
for (const name of ["react", "react-dom", "scheduler", "dockview-react", "dockview", "dockview-core", "@tanstack/react-table", "@tanstack/table-core", "monaco-editor", "echarts", "zrender", "klinecharts", "@klinecharts/extension", "tslib", "hqchart", "jquery", "pdfjs-dist", "@openuidev/react-lang", "@openuidev/lang-core", "@openuidev/devtools", "@openuidev/observability", "zod"]) {
  const source = resolve(root, "node_modules", name);
  if (!existsSync(source)) continue;
  const destination = resolve(staging, "frontend-licenses", name.replaceAll("/", "-"));
  await mkdir(destination, { recursive: true });
  for (const entry of await readdir(source, { withFileTypes: true })) {
    if (entry.isFile() && /license|notice/i.test(entry.name)) await cp(resolve(source, entry.name), resolve(destination, entry.name));
  }
}
console.log(`Windows 研究运行时已准备：${staging}`);
