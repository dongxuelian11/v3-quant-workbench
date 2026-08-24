import { readdir, readFile, stat } from "node:fs/promises";
import { extname, relative, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const rendererRoot = resolve(root, "dist/apps/desktop/src/renderer");
const forbiddenProductTokens = [
  "BT-DEMO",
  "demo-v",
  "DEVELOPMENT_INTEGRATION_FIXTURE",
  "DeterministicFrontendDemoProvider",
  "CN Daily Adjusted · Demo",
  "BacktestHandoffDraft/demo",
  "agentWorkspaceFixture",
  "integrationFixture",
];
const textExtensions = new Set([".css", ".html", ".js", ".map"]);

async function collectTextFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const absolute = resolve(directory, entry.name);
    if (entry.isDirectory()) files.push(...await collectTextFiles(absolute));
    else if (entry.isFile() && textExtensions.has(extname(entry.name))) files.push(absolute);
  }
  return files;
}

const rendererInfo = await stat(rendererRoot).catch(() => null);
if (!rendererInfo?.isDirectory()) {
  throw new Error("PRODUCT renderer output is missing; run npm run build first");
}

const violations = [];
for (const file of await collectTextFiles(rendererRoot)) {
  const content = await readFile(file, "utf8");
  for (const token of forbiddenProductTokens) {
    if (content.includes(token)) {
      violations.push(`${relative(root, file)} contains ${JSON.stringify(token)}`);
    }
  }
}

if (violations.length > 0) {
  throw new Error(`PRODUCT bundle contains development/demo material:\n${violations.slice(0, 30).join("\n")}`);
}

console.log("PRODUCT bundle truth PASS: packaged renderer output contains no development fixture or fabricated demo identifiers.");
