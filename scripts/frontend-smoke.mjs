import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const renderer = await readFile(resolve(root, "apps/desktop/src/renderer/renderer.ts"), "utf8");
const requiredLabs = ["research", "strategy", "model", "backtest", "result"];
const missing = requiredLabs.filter((id) => !renderer.includes(`id: "${id}"`));
if (missing.length) {
  console.error(`Missing Lab definitions: ${missing.join(", ")}`);
  process.exit(1);
}
for (const marker of ["contextIsolation: true", "nodeIntegration: false", "UnavailableBackendProvider", "Visual", "Code", "Split", "Study", "Trial", "HPO"]) {
  const source = marker.includes("contextIsolation") || marker.includes("nodeIntegration") ? await readFile(resolve(root, "apps/desktop/src/main.ts"), "utf8") : renderer;
  if (!source.includes(marker)) {
    console.error(`Missing frontend contract marker: ${marker}`);
    process.exit(1);
  }
}
console.log("Frontend route/workspace smoke passed: five Labs and accepted shell markers are present.");

