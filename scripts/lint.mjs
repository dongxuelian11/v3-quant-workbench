import { readdir, readFile } from "node:fs/promises";
import { join, relative, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const roots = [resolve(root, "apps"), resolve(root, "packages"), resolve(root, "scripts"), resolve(root, "tests")];
const failures = [];

async function visit(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory() && !["node_modules", "dist"].includes(entry.name)) await visit(path);
    if (entry.isFile() && /\.(ts|mjs|cjs|json|css|html)$/.test(entry.name)) {
      const content = await readFile(path, "utf8");
      if (/\r\n/.test(content)) failures.push(`${relative(root, path)}: CRLF line endings`);
      if (/[ \t]+$/m.test(content)) failures.push(`${relative(root, path)}: trailing whitespace`);
    }
  }
}

for (const directory of roots) await visit(directory);
if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log("Lint checks passed: LF endings and no trailing whitespace.");
