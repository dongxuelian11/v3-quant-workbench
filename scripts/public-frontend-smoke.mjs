import assert from "node:assert/strict";
import { readFile, stat } from "node:fs/promises";
import { dirname, resolve, sep } from "node:path";

import { PRODUCT_NAVIGATION } from "../apps/desktop/src/renderer/productShellModel.ts";

const root = resolve(import.meta.dirname, "..");

async function readRequired(relativePath, minimumBytes = 1) {
  const absolutePath = resolve(root, relativePath);
  const info = await stat(absolutePath);
  assert.ok(info.isFile(), `${relativePath} must be a file`);
  assert.ok(info.size >= minimumBytes, `${relativePath} is unexpectedly small (${info.size} bytes)`);
  return readFile(absolutePath, "utf8");
}

function assertSourceContract(source, pattern, message) {
  assert.match(source, pattern, message);
}

const packageJson = JSON.parse(await readRequired("package.json"));
assert.equal(packageJson.main, "dist/apps/desktop/src/main.js", "Electron main entrypoint changed unexpectedly");
assert.equal(packageJson.scripts["smoke:frontend"], "node scripts/public-frontend-smoke.mjs");
assert.equal(packageJson.scripts["verify:product-bundle-truth"], "node scripts/verify-product-bundle-truth.mjs");
assert.equal(packageJson.scripts["smoke:visual-evidence"], "node scripts/frontend-smoke.mjs");
assert.match(packageJson.scripts["validate:public"], /npm run smoke:frontend/);
assert.match(packageJson.scripts["validate:public"], /npm run build && npm run verify:product-bundle-truth/);
assert.doesNotMatch(packageJson.scripts["validate:public"], /smoke:(?:electron|visual-evidence)/);
assert.match(packageJson.scripts.validate, /npm run validate:public/);
assert.match(packageJson.scripts.validate, /npm run smoke:electron/);
assert.match(packageJson.scripts.validate, /npm run smoke:visual-evidence/);

const workflow = await readRequired(".github/workflows/ci.yml");
assertSourceContract(workflow, /run:\s*npm run validate:public/, "Public CI must use the repository-contained public validation chain");
assert.doesNotMatch(workflow, /visual-restoration-screenshots|smoke:visual-evidence|smoke:electron/, "Public CI must not require local Electron/UAU evidence");

const gitignore = await readRequired(".gitignore");
assertSourceContract(gitignore, /^\/deliverables\/\s*$/m, "Generated local evidence must remain ignored");

const requiredBuildOutputs = [
  packageJson.main,
  "dist/apps/desktop/src/preload.js",
  "dist/apps/desktop/src/main/backendRuntime/index.js",
  "dist/apps/desktop/src/main/backendRuntime/supervisor.js",
  "dist/apps/backend/src/index.js",
  "dist/packages/contracts/src/index.js"
];
for (const output of requiredBuildOutputs) await readRequired(output, 20);

const rendererIndexPath = "dist/apps/desktop/src/renderer/index.html";
const rendererIndex = await readRequired(rendererIndexPath, 200);
assertSourceContract(rendererIndex, /id=["']app["']/, "Renderer root element is missing");
assertSourceContract(rendererIndex, /Content-Security-Policy/, "Renderer CSP is missing");
const rendererDirectory = dirname(resolve(root, rendererIndexPath));
const referencedAssets = [...rendererIndex.matchAll(/(?:src|href)=["']\.\/(assets\/[^"']+)["']/g)].map((match) => match[1]);
assert.ok(referencedAssets.some((asset) => asset.endsWith(".js")), "Renderer bundle has no JavaScript entry");
assert.ok(referencedAssets.some((asset) => asset.endsWith(".css")), "Renderer bundle has no stylesheet entry");
for (const asset of new Set(referencedAssets)) {
  const assetPath = resolve(rendererDirectory, asset);
  assert.ok(assetPath.startsWith(`${rendererDirectory}${sep}`), `Renderer asset escapes build root: ${asset}`);
  const info = await stat(assetPath);
  assert.ok(info.isFile() && info.size > 0, `Renderer asset is missing or empty: ${asset}`);
}
const rendererPayload = (await Promise.all([...new Set(referencedAssets)].map((asset) => readFile(resolve(rendererDirectory, asset), "utf8")))).join("\n");
for (const token of [
  "BT-DEMO",
  "demo-v",
  "DEVELOPMENT_INTEGRATION_FIXTURE",
  "DeterministicFrontendDemoProvider",
  "CN Daily Adjusted · Demo",
  "BacktestHandoffDraft/demo",
]) {
  assert.doesNotMatch(rendererPayload, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `PRODUCT renderer asset contains ${token}`);
}
for (const marker of [
  "首页 / 项目",
  "V1_1_C2_DATA_NOT_CONNECTED",
  "V1_1_C2_FACTOR_NOT_CONNECTED",
  "V1_1_C3_BACKTEST_NOT_CONNECTED",
  "V1_1_C3_RESULTS_NOT_CONNECTED",
]) {
  assert.ok(rendererPayload.includes(marker), `PRODUCT renderer asset is missing ${marker}`);
}

const mainSource = await readRequired("apps/desktop/src/main.ts", 500);
for (const [preference, expected] of [
  ["contextIsolation", "true"],
  ["nodeIntegration", "false"],
  ["sandbox", "true"],
  ["webSecurity", "true"]
]) {
  assertSourceContract(mainSource, new RegExp(`${preference}\\s*:\\s*${expected}`), `Electron ${preference} must remain ${expected}`);
}
assertSourceContract(mainSource, /setWindowOpenHandler\(\(\)\s*=>\s*\(\{\s*action:\s*["']deny["']/, "New-window denial is missing");
assertSourceContract(mainSource, /will-navigate["']\s*,\s*\(event\)\s*=>\s*event\.preventDefault\(\)/, "Navigation denial is missing");

const preloadSource = await readRequired("apps/desktop/src/preload.ts", 200);
assertSourceContract(preloadSource, /contextBridge\.exposeInMainWorld\(["']v3Desktop["']/, "Preload bridge exposure is missing");
const rendererEntrySource = await readRequired("apps/desktop/src/renderer/main.tsx", 200);
assertSourceContract(rendererEntrySource, /import \{ ProductApp \} from ["']\.\/ProductApp["']/, "PRODUCT renderer entry must import ProductApp");
assert.doesNotMatch(rendererEntrySource, /from ["']\.\/App["']|<App\s*\//, "Development workbench must not be the PRODUCT entry");
const productAppSource = await readRequired("apps/desktop/src/renderer/ProductApp.tsx", 1000);
assertSourceContract(productAppSource, /data-product-mode=["']PRODUCT["']/, "PRODUCT mode marker is missing");
assertSourceContract(productAppSource, /<ProductRuntimePanel\s*\/>/, "Home must consume the canonical product runtime read model");
assertSourceContract(productAppSource, /disabled=\{!item\.available\}/, "Deferred PRODUCT pages must render disabled");
assertSourceContract(productAppSource, /data-unavailable-reason=\{item\.reason \?\? undefined\}/, "Deferred PRODUCT pages must expose their reason");
assert.deepEqual(PRODUCT_NAVIGATION.map((item) => item.id), ["home", "data", "research", "backtest", "results"]);
assert.deepEqual(PRODUCT_NAVIGATION.filter((item) => item.available).map((item) => item.id), ["home"]);
assert.ok(PRODUCT_NAVIGATION.filter((item) => !item.available).every((item) => item.reason?.startsWith("NOT_AVAILABLE · ")));
const productPanelSource = await readRequired("apps/desktop/src/renderer/components/ProductRuntimePanel.tsx", 1000);
for (const [action, ownerCall] of [
  ["create-project", "createProjectAndBind"],
  ["submit-product-research", "submitResearch"],
  ["import-research-package", "importResearchPackage"],
  ["submit-existing-runspec", "submitRunSpec"],
]) {
  assert.ok(productPanelSource.includes(`data-action=\"${action}\"`), `PRODUCT action ${action} is missing`);
  assert.ok(productPanelSource.includes(`${ownerCall}(`), `PRODUCT action ${action} has no real owner call`);
}

const preloadBridgeSource = await readRequired("apps/desktop/src/preload/backendRuntime/bridge.ts", 500);
assertSourceContract(preloadBridgeSource, /createBackendRuntimeReadOnlyBridge/, "Read-only backendRuntime product bridge is missing");
for (const forbidden of ["cancelTask", "retryTask", "resumeTask", "openArtifactStream"]) {
  const productSurface = preloadBridgeSource.slice(preloadBridgeSource.indexOf("createBackendRuntimeReadOnlyBridge"));
  assert.doesNotMatch(productSurface, new RegExp(`${forbidden}\\s*:`), `Renderer product bridge must not expose ${forbidden}`);
}
console.log(`Public frontend smoke PASS: truthful PRODUCT shell, one connected Home, four reasoned NOT_AVAILABLE pages, Electron security invariants, and ${new Set(referencedAssets).size} renderer assets verified without development fixtures.`);
