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
assert.equal(packageJson.version, "1.0.0", "V1.1 package version must remain gated until complete C4 acceptance");
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
function workflowJob(jobId, nextJobId) {
  const start = workflow.indexOf(`  ${jobId}:\n`);
  assert.notEqual(start, -1, `Public CI is missing ${jobId}`);
  const end = nextJobId === undefined ? workflow.length : workflow.indexOf(`  ${nextJobId}:\n`, start + 1);
  assert.notEqual(end, -1, `Public CI is missing ${nextJobId}`);
  return workflow.slice(start, end);
}
const authorityJob = workflowJob("authority-contract-quality", "backend-runtime");
const backendJob = workflowJob("backend-runtime", "windows-product-integration");
const windowsJob = workflowJob("windows-product-integration", "verify-public-baseline");
const requiredCompatibilityGate = workflowJob("verify-public-baseline");
for (const command of ["validate:authority", "test:contracts", "typecheck", "lint", "test:unit"]) {
  assertSourceContract(authorityJob, new RegExp(`npm run ${command.replaceAll(":", "\\:")}`), `Job A is missing ${command}`);
}
for (const command of ["test:backend", "smoke:product-runtime", "smoke:product-data", "smoke:product-factor", "smoke:product-backtest", "smoke:product-result"]) {
  assertSourceContract(backendJob, new RegExp(`npm run ${command.replaceAll(":", "\\:")}`), `Job B is missing ${command}`);
}
assert.doesNotMatch(`${authorityJob}\n${backendJob}`, /visual-restoration-screenshots|smoke:visual-evidence|smoke:electron/, "Ubuntu Jobs A/B must not require local Electron/UAU evidence");
assertSourceContract(windowsJob, /npm\.cmd run smoke:electron:runtime/, "Job C must exercise the hosted Windows Electron runtime");
assert.doesNotMatch(windowsJob, /visual-restoration-screenshots|smoke:visual-evidence/, "Hosted Job C must not claim local UAU evidence");
assertSourceContract(requiredCompatibilityGate, /name:\s*verify-public-baseline/, "Public CI must emit the active Ruleset status context");
assertSourceContract(requiredCompatibilityGate, /if:\s*\$\{\{\s*always\(\)\s*\}\}/, "Required status compatibility gate must run after failures");
for (const jobId of ["authority-contract-quality", "backend-runtime", "windows-product-integration"]) {
  assertSourceContract(requiredCompatibilityGate, new RegExp(`- ${jobId}`), `Required status compatibility gate does not need ${jobId}`);
  assertSourceContract(requiredCompatibilityGate, new RegExp(`needs\\.${jobId.replaceAll("-", "\\-")}\\.result`), `Required status compatibility gate does not inspect ${jobId}`);
}
assertSourceContract(requiredCompatibilityGate, /exit 1/, "Required status compatibility gate must fail closed");

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
assertSourceContract(productAppSource, /<ProductRuntimePanel\s+onNavigate=\{setActivePage\}\s*\/>/, "Home must consume the canonical product runtime read model and real navigation owner");
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

const readme = await readRequired("README.md", 1000);
const currentStatus = await readRequired("docs/status/CURRENT_STATUS.md", 1000);
const productSurfaceDoc = await readRequired("docs/architecture/PRODUCT_SURFACE.md", 1000);
const deferredGaps = await readRequired("docs/status/V3_DEFERRED_GAPS.md", 1000);
const v1History = await readRequired("docs/release/V1_0_RELEASE_CANDIDATE.md", 1000);
const v11Candidate = await readRequired("docs/release/V1_1_RELEASE_CANDIDATE.md", 1000);

for (const [document, token] of [
  [readme, "V3 V1.1 Usable Research Product local candidate"],
  [readme, "Hosted Jobs A-F"],
  [currentStatus, "PRODUCT_CONNECTED / PRE_ALPHA / NOT_FORMAL"],
  [currentStatus, "FORMAL_EXECUTION_CONTRACT_NOT_CLOSED"],
  [productSurfaceDoc, "ProductEntryService"],
  [productSurfaceDoc, "PRODUCT_CONNECTED / PRE_ALPHA / NOT_FORMAL"],
  [deferredGaps, "CLOSED_FOR_V1_1_PRODUCT_RESEARCH_PATH"],
  [deferredGaps, "V1_1_HOSTED_JOBS_A_F = NOT_RUN"],
  [v1History, "RELEASED AS PUBLIC PRERELEASE"],
  [v11Candidate, "LOCAL CANDIDATE / UNPUSHED / C4 IN_PROGRESS"],
  [v11Candidate, "Package version: `1.0.0` (`1.1.0` bump gated)"],
]) {
  assert.ok(document.includes(token), `current product documentation is missing ${token}`);
}
for (const staleClaim of [
  "Desktop ↔ backend wiring | Not performed",
  "Backtest / Result backend | Not rebuilt",
  "Status: `PENDING EXACT-HEAD CI",
]) {
  assert.doesNotMatch(`${currentStatus}\n${v1History}`, new RegExp(staleClaim.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `stale documentation claim remains: ${staleClaim}`);
}

console.log(`Public frontend smoke PASS: truthful staged PRODUCT navigation, connected V1.1 owner calls, Electron security invariants, current evidence-ceiling docs, and ${new Set(referencedAssets).size} renderer assets verified without development fixtures.`);
