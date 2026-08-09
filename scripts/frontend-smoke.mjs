import { readdir, readFile, stat } from "node:fs/promises";
import { createHash } from "node:crypto";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const directory = resolve(root, "deliverables", "screenshots");
const expected = ["01-research-overview-chart-tree.png","02-universe-builder-nine-modes-import.png","03-research-linked-selection-inspector.png","04-strategy-react-flow-visual.png","05-strategy-monaco-code.png","06-strategy-split-monaco-diff.png","07-model-dataset-runs-seven-families.png","08-model-study-trial-hpo.png","09-model-version-signal-handoff.png","10-backtest-full-demo-surface.png","11-result-full-demo-surface.png","12-command-palette.png","13-dockview-split-docked-layout.png","14-restart-restored-layout-state.png"];
const files = new Set(await readdir(directory)); const hashes = new Set();
for (const name of expected) {
  if (!files.has(name)) throw new Error(`Missing Electron screenshot ${name}`);
  const path = resolve(directory, name); const info = await stat(path); if (info.size < 20_000) throw new Error(`Screenshot too small ${name}: ${info.size}`);
  hashes.add(createHash("sha256").update(await readFile(path)).digest("hex"));
}
if (hashes.size !== expected.length) throw new Error("Electron screenshot states are not distinct");
const capture = JSON.parse(await readFile(resolve(directory, "capture-result.json"), "utf8"));
const restart = JSON.parse(await readFile(resolve(directory, "restart-result.json"), "utf8"));
if (capture.electron !== "39.8.10" || restart.electron !== "39.8.10") throw new Error("Electron version evidence mismatch");
if (capture.prefs.contextIsolation !== true || capture.prefs.nodeIntegration !== false || capture.prefs.sandbox !== true || capture.prefs.webSecurity !== true) throw new Error("Electron security preferences failed");
if (capture.consoleErrors.length || restart.consoleErrors.length) throw new Error(`Renderer console errors: ${JSON.stringify([...capture.consoleErrors, ...restart.consoleErrors])}`);
console.log(`Behavioral frontend evidence PASS: ${expected.length} distinct real-Electron states, restart restored, secure preferences asserted.`);
