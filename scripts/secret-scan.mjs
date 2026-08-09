import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { extname, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const binaryExtensions = new Set([".gif", ".ico", ".jpeg", ".jpg", ".png", ".zip"]);
const patterns = [
  ["private-key", /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/],
  ["aws-access-key", /AKIA[0-9A-Z]{16}/],
  ["github-token", /gh[pousr]_[A-Za-z0-9]{30,}/],
  ["openai-style-key", /sk-(?:proj-)?[A-Za-z0-9_-]{20,}/],
  ["slack-token", /xox[baprs]-[A-Za-z0-9-]{20,}/],
  ["credential-assignment", /(?:api[_-]?key|client[_-]?secret|access[_-]?token|password)\s*[:=]\s*["'][^"']{12,}["']/i],
  ["windows-user-path", /[A-Za-z]:[\\/]Users[\\/][^\\/\s]+[\\/]/i],
  ["unix-user-path", /\/(?:home|Users)\/[^/\s]+\//]
];

const listed = execFileSync(
  "git",
  ["ls-files", "--cached", "--others", "--exclude-standard", "-z"],
  { cwd: root, encoding: "utf8" }
).split("\0").filter(Boolean);

const findings = [];
for (const relativePath of listed) {
  if (binaryExtensions.has(extname(relativePath).toLowerCase())) continue;
  let content;
  try {
    content = await readFile(resolve(root, relativePath), "utf8");
  } catch {
    continue;
  }
  for (const [name, pattern] of patterns) {
    if (pattern.test(content)) findings.push(`${relativePath}: ${name}`);
  }
}

const historyPatterns = [
  "-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----",
  "AKIA[0-9A-Z]{16}",
  "gh[pousr]_[A-Za-z0-9]{30,}",
  "sk-(proj-)?[A-Za-z0-9_-]{20,}",
  "xox[baprs]-[A-Za-z0-9-]{20,}"
];
const historyFindings = [];
for (const pattern of historyPatterns) {
  const output = execFileSync(
    "git",
    ["log", "--all", "--format=%H", `-G${pattern}`, "--", "."],
    { cwd: root, encoding: "utf8" }
  ).trim();
  if (output) historyFindings.push(`${pattern}: ${output.split(/\r?\n/).filter(Boolean).join(",")}`);
}

if (findings.length || historyFindings.length) {
  console.error([...findings, ...historyFindings.map((item) => `history:${item}`)].join("\n"));
  process.exit(1);
}

console.log(`Secret/private-path scan passed: ${listed.length} current source files and relevant Git history checked.`);
