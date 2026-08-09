import { readdir, readFile, stat } from "node:fs/promises";
import { createHash } from "node:crypto";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const directory = resolve(root, "deliverables", "visual-restoration-screenshots");
const expected = [
  "01-research-default-chart-first.png",
  "02-research-selected-event-inspector.png",
  "03-research-universe-builder-focused.png",
  "04-research-secondary-analytics-expanded.png",
  "05-strategy-visual-mode.png",
  "06-strategy-code-mode.png",
  "07-strategy-split-mode.png",
  "08-strategy-proposal-diff-review.png",
  "09-model-dataset-family-run-workflow.png",
  "10-model-study-trial-hpo-workflow.png",
  "11-model-version-signal-handoff.png",
  "12-backtest-review.png",
  "13-result-review.png",
  "14-workbench-multi-panel-research-preset.png",
  "15-workbench-restored-layout-after-restart.png",
  "16-research-1280x720-compact-safe.png",
  "17-research-1920x1080-wide.png",
  "18-command-palette.png",
  "19-research-1280x720-inspector-overlay.png",
  "20-research-1920x1080-inspector-dock.png"
];
const files = new Set(await readdir(directory));
const hashes = new Set();
for (const name of expected) {
  if (!files.has(name)) throw new Error(`Missing Electron screenshot ${name}`);
  const screenshotPath = resolve(directory, name);
  const info = await stat(screenshotPath);
  if (info.size < 20_000) throw new Error(`Screenshot too small ${name}: ${info.size}`);
  hashes.add(createHash("sha256").update(await readFile(screenshotPath)).digest("hex"));
}
if (hashes.size < expected.length - 1) throw new Error(`Unexpected screenshot duplication: ${hashes.size} unique for ${expected.length} evidence files`);

const capture = JSON.parse(await readFile(resolve(directory, "capture-result.json"), "utf8"));
const restart = JSON.parse(await readFile(resolve(directory, "restart-result.json"), "utf8"));
const geometry = JSON.parse(await readFile(resolve(directory, "layout-geometry.json"), "utf8"));
if (capture.electron !== "39.8.10" || restart.electron !== "39.8.10") throw new Error("Electron version evidence mismatch");
if (capture.prefs.contextIsolation !== true || capture.prefs.nodeIntegration !== false || capture.prefs.sandbox !== true || capture.prefs.webSecurity !== true) throw new Error("Electron security preferences failed");
if (capture.consoleErrors.length || restart.consoleErrors.length) throw new Error(`Renderer console errors: ${JSON.stringify([...capture.consoleErrors, ...restart.consoleErrors])}`);
if (geometry.length !== 20) throw new Error(`Expected 20 geometry measurements, got ${geometry.length}`);
const byName = Object.fromEntries(geometry.map((item) => [item.screenshot, item]));
for (const name of ["01-research-default-chart-first.png", "16-research-1280x720-compact-safe.png", "17-research-1920x1080-wide.png"]) {
  const item = byName[name];
  if (!item || item.primary_canvas_dimensions.width < 720 || item.primary_canvas_dimensions.height < 400) throw new Error(`Chart-first geometry failed for ${name}: ${JSON.stringify(item)}`);
}
if (byName["16-research-1280x720-compact-safe.png"].viewport_css_width !== 1280 || byName["16-research-1280x720-compact-safe.png"].viewport_css_height !== 720) throw new Error("1280x720 viewport evidence mismatch");
if (byName["17-research-1920x1080-wide.png"].viewport_css_width !== 1920 || byName["17-research-1920x1080-wide.png"].viewport_css_height !== 1080) throw new Error("1920x1080 viewport evidence mismatch");
if (byName["19-research-1280x720-inspector-overlay.png"].inspector_state !== "open" || byName["19-research-1280x720-inspector-overlay.png"].primary_canvas_dimensions.width < 720) throw new Error("1280 Inspector overlay geometry failed");
if (byName["20-research-1920x1080-inspector-dock.png"].inspector_state !== "open" || byName["20-research-1920x1080-inspector-dock.png"].inspector_width < 280) throw new Error("1920 Inspector dock geometry failed");
if (byName["01-research-default-chart-first.png"].simultaneously_visible_major_panels > 2) throw new Error("Research default has too many visible major panels");
if (byName["01-research-default-chart-first.png"].inspector_state !== "closed" || byName["02-research-selected-event-inspector.png"].inspector_state !== "open") throw new Error("Research contextual Inspector contract failed");
if (byName["03-research-universe-builder-focused.png"].inspector_state !== "closed" || byName["04-research-secondary-analytics-expanded.png"].inspector_state !== "closed") throw new Error("Research focused drawers must not compete with the Inspector");
for (const name of ["14-workbench-multi-panel-research-preset.png", "15-workbench-restored-layout-after-restart.png"]) {
  const item = byName[name];
  if (item.viewport_css_width !== 1920 || item.viewport_css_height !== 1080 || item.primary_canvas_dimensions.width < 720 || item.primary_canvas_dimensions.height < 400) throw new Error(`Research preset geometry failed for ${name}: ${JSON.stringify(item)}`);
}
if (byName["05-strategy-visual-mode.png"].primary_panel_id !== "strategy-editor") throw new Error("Strategy primary editor measurement missing");
if (byName["09-model-dataset-family-run-workflow.png"].primary_panel_id !== "model-workflow") throw new Error("Model workflow measurement missing");
if (!capture.interactionEvidence?.commandPalette?.openedByKeyboard || !capture.interactionEvidence?.commandPalette?.inputFocused) throw new Error("Command palette keyboard/focus evidence failed");
if (!capture.interactionEvidence?.dockview?.focusable || !capture.interactionEvidence?.motion?.reducedMotionRulePresent) throw new Error("Dockview focus or reduced-motion evidence failed");
console.log(`Visual frontend evidence PASS: ${expected.length} distinct real-Electron states, chart geometry gates, restart layout, and secure preferences asserted.`);
