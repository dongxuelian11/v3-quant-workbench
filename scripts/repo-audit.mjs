import { readdir, stat } from "node:fs/promises";
import { join, relative, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const forbiddenNames = new Set([".env", ".venv", "venv", "node_modules", "runtime", "data", "projects-local", "results-local", "strategies-local", "models-local"]);
const excludedGenerated = new Set([".git", "deliverables", "dist", "node_modules"]);
const forbiddenExtensions = new Set([".db", ".duckdb", ".parquet", ".onnx", ".safetensors", ".pt", ".pth"]);
const findings = [];
let bytes = 0;

async function visit(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (excludedGenerated.has(entry.name)) continue;
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      if (forbiddenNames.has(entry.name)) findings.push(`${relative(root, path)}: forbidden directory`);
      else await visit(path);
    } else {
      const info = await stat(path);
      bytes += info.size;
      const ext = entry.name.slice(entry.name.lastIndexOf(".")).toLowerCase();
      if (forbiddenExtensions.has(ext)) findings.push(`${relative(root, path)}: forbidden data/model file`);
      if (info.size > 50 * 1024 * 1024) findings.push(`${relative(root, path)}: oversized file`);
    }
  }
}

await visit(root);
if (findings.length) {
  console.error(findings.join("\n"));
  process.exit(1);
}
console.log(`Repository hygiene audit passed: ${bytes} source bytes, no forbidden local data or oversized files.`);
