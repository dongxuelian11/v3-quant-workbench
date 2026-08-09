import { execFileSync } from "node:child_process";
import { stat } from "node:fs/promises";
import { basename, extname, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const forbiddenTopLevel = new Set([
  ".agents", ".codex", ".env", ".venv", "artifacts", "crash-dumps", "data",
  "dist", "models-local", "projects-local", "results-local", "runtime",
  "strategies-local"
]);
const forbiddenAnywhere = new Set([".env", ".venv", "node_modules", "venv"]);
const forbiddenExtensions = new Set([
  ".bin", ".db", ".duckdb", ".feather", ".h5", ".onnx", ".parquet",
  ".pt", ".pth", ".safetensors", ".sha256", ".zip"
]);
const maxBytes = 10 * 1024 * 1024;
const current = execFileSync(
  "git",
  ["ls-files", "--cached", "--others", "--exclude-standard", "-z"],
  { cwd: root, encoding: "utf8" }
).split("\0").filter(Boolean);

const findings = [];
let totalBytes = 0;
for (const relativePath of current) {
  const components = relativePath.replaceAll("\\", "/").split("/");
  const extension = extname(relativePath).toLowerCase();
  if (forbiddenTopLevel.has(components[0]) || components.some((component) => forbiddenAnywhere.has(component))) {
    findings.push(`${relativePath}: forbidden path component`);
  }
  if (forbiddenExtensions.has(extension)) findings.push(`${relativePath}: forbidden artifact extension`);
  let info;
  try {
    info = await stat(resolve(root, relativePath));
  } catch (error) {
    if (error?.code === "ENOENT") continue;
    throw error;
  }
  totalBytes += info.size;
  if (info.size > maxBytes) findings.push(`${relativePath}: ${info.size} bytes exceeds 10 MiB`);
  if (basename(relativePath).toLowerCase() === "kline_v3.db") findings.push(`${relativePath}: forbidden market database`);
}

const historyNames = execFileSync(
  "git",
  ["log", "--all", "--name-only", "--format="],
  { cwd: root, encoding: "utf8" }
).split(/\r?\n/).filter(Boolean);
for (const relativePath of historyNames) {
  const extension = extname(relativePath).toLowerCase();
  if (forbiddenExtensions.has(extension)) findings.push(`history:${relativePath}: forbidden artifact extension`);
  if (basename(relativePath).toLowerCase() === "kline_v3.db") findings.push(`history:${relativePath}: forbidden market database`);
}

if (findings.length) {
  console.error([...new Set(findings)].join("\n"));
  process.exit(1);
}
console.log(`Repository hygiene audit passed: ${current.length} current files, ${totalBytes} bytes, no forbidden/private or >10 MiB artifact.`);
