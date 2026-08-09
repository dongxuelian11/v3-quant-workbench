import { readFile, readdir } from "node:fs/promises";
import { join, relative, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const ignored = new Set([".git", "node_modules", "dist", "deliverables"]);
const suspicious = [
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/i,
  /AKIA[0-9A-Z]{16}/,
  /(?:api[_-]?key|secret|token|password)\s*[:=]\s*["'][^"']{8,}["']/i,
  /(?:sk|rk)-[A-Za-z0-9]{20,}/
];
const findings = [];

async function visit(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (ignored.has(entry.name)) continue;
    const path = join(directory, entry.name);
    if (entry.isDirectory()) await visit(path);
    if (!entry.isFile()) continue;
    if (entry.name.endsWith(".png") || entry.name.endsWith(".jpg") || entry.name.endsWith(".zip")) continue;
    const content = await readFile(path, "utf8");
    for (const pattern of suspicious) if (pattern.test(content)) findings.push(relative(root, path));
  }
}

await visit(root);
if (findings.length) {
  console.error(`Potential secrets found in: ${[...new Set(findings)].join(", ")}`);
  process.exit(1);
}
console.log("Secret scan passed: no credential patterns found in repository source.");

