import assert from "node:assert/strict";
import { readFile, stat } from "node:fs/promises";
import { dirname, resolve, sep } from "node:path";

import { DEMO_TRUTH, LAB_IDS } from "../packages/contracts/src/index.ts";
import { AGENT_WORKSPACE_BOUNDARY, ARTIFACT_RENDERER_REGISTRY, PERMISSION_SURFACE, validateAgentWorkspaceFixture } from "../apps/desktop/src/renderer/agentWorkspace.ts";
import { agentStatements, artifactViews, evidenceViews, researchSessions, timelineEntries } from "../apps/desktop/src/renderer/agentWorkspaceFixture.ts";

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
assert.equal(packageJson.scripts["smoke:visual-evidence"], "node scripts/frontend-smoke.mjs");
assert.match(packageJson.scripts["validate:public"], /npm run smoke:frontend/);
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

assert.deepEqual([...LAB_IDS], ["research", "strategy", "model", "backtest", "result"]);
const appSource = await readRequired("apps/desktop/src/renderer/App.tsx", 500);
assertSourceContract(appSource, /useState<WorkspaceSurface>\(["']agent["']\)/, "Agent Workspace must remain the default product surface");
assertSourceContract(appSource, /data-surface=["']agent["']/, "Agent Workspace navigation entry is missing");
for (const lab of LAB_IDS) {
  assertSourceContract(appSource, new RegExp(`id:\\s*["']${lab}["']`), `Renderer route metadata is missing for ${lab}`);
}
for (const componentPath of [
  "apps/desktop/src/renderer/components/ResearchPanels.tsx",
  "apps/desktop/src/renderer/components/StrategyPanels.tsx",
  "apps/desktop/src/renderer/components/ModelPanels.tsx",
  "apps/desktop/src/renderer/components/BacktestResultPanels.tsx",
  "apps/desktop/src/renderer/components/Workbench.tsx",
  "apps/desktop/src/renderer/components/AgentWorkspace.tsx",
  "apps/desktop/src/renderer/components/ResearchSessionNavigator.tsx",
  "apps/desktop/src/renderer/components/ArtifactViewer.tsx"
]) {
  await readRequired(componentPath, 500);
}

const agentWorkspaceSource = await readRequired("apps/desktop/src/renderer/components/AgentWorkspace.tsx", 1000);
const artifactViewerSource = await readRequired("apps/desktop/src/renderer/components/ArtifactViewer.tsx", 500);
assert.doesNotMatch(`${agentWorkspaceSource}\n${artifactViewerSource}`, /dangerouslySetInnerHTML|\beval\s*\(|new Function\s*\(/, "Agent output must never execute arbitrary model HTML or code");
assertSourceContract(agentWorkspaceSource, /NON_CANONICAL/, "Agent drafts must expose the non-canonical boundary");
assertSourceContract(agentWorkspaceSource, /Open in .* Lab/, "Open-in-Lab navigation is missing");
assert.equal(AGENT_WORKSPACE_BOUNDARY.mode, "DEMO_DEVELOPMENT_ONLY");
assert.deepEqual(PERMISSION_SURFACE.filter((item) => item.allowed).map((item) => item.level), ["L0_READ", "L1_DRAFT"]);
assert.deepEqual(Object.keys(ARTIFACT_RENDERER_REGISTRY), ["table", "metric", "text", "details", "chart", "backtest-result"]);
assert.ok(researchSessions.length >= 3 && evidenceViews.length >= 12 && timelineEntries.length >= 8, "Agent-first fixture coverage is incomplete");
assert.equal(validateAgentWorkspaceFixture({ sessions: researchSessions, statements: agentStatements, timeline: timelineEntries, evidence: evidenceViews, artifacts: artifactViews }), true);

assert.equal(DEMO_TRUTH.classification, "DEMO");
assert.match(DEMO_TRUTH.label, /NOT FORMAL FINANCIAL OUTPUT/);

console.log(`Public frontend smoke PASS: Agent-first default, ${LAB_IDS.length} preserved Lab contracts, closed artifact registry, Electron security invariants, runtime outputs, and ${new Set(referencedAssets).size} renderer assets verified without GUI or local evidence artifacts.`);
