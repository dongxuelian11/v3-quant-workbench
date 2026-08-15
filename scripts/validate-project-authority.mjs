import { createHash } from "node:crypto";
import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const REQUIRED_FILES = [
  "V3_PROJECT_CONSTITUTION.md",
  "AGENTS.md",
  "docs/architecture/V3_CANONICAL_ARCHITECTURE.md",
  "docs/status/V3_CAPABILITY_LEVELS.md",
];

const AUTHORITY_VERSION_PATTERN = /^\d+\.\d+\.\d+$/;
const DISALLOWED_AMENDMENT_REASONS = new Set(["TODO", "TBD"]);

const MATURITY_LEVELS = [
  "DESIGNED",
  "MODULE_IMPLEMENTED",
  "MODULE_ACCEPTED",
  "SEMANTIC_OWNER_ACCEPTED",
  "INTEGRATION_ACCEPTED",
  "PRODUCT_CONNECTED",
  "USER_VISUAL_ACCEPTED",
  "PRODUCTION_AVAILABLE",
];

const ORTHOGONAL_STATES = [
  "NOT_AVAILABLE",
  "NOT_RUN",
  "PENDING",
  "BLOCKED",
  "UNKNOWN",
  "DEPRECATED",
];

const ARCHITECTURE_OWNERS = [
  "Data Truth",
  "Universe",
  "Factor",
  "Dataset",
  "Experiment",
  "Model",
  "Strategy",
  "Signal / Selection",
  "Portfolio",
  "Risk",
  "Backtest",
  "Result Analytics",
  "Artifact Store",
  "Reviewer",
  "Control Plane / Task / Worker",
  "Resource Governance",
  "Agent Plane",
  "Alpha Mining",
  "Desktop / Product Runtime",
];

function parseArguments(argv) {
  const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
  let root = path.resolve(scriptDirectory, "..");
  let manifest = "docs/status/V3_PROJECT_AUTHORITY_MANIFEST.json";

  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--root") {
      root = path.resolve(argv[index + 1] ?? "");
      index += 1;
    } else if (argument === "--manifest") {
      manifest = argv[index + 1] ?? "";
      index += 1;
    } else {
      throw new Error(`unknown argument: ${argument}`);
    }
  }

  return { root, manifest };
}

function resolveInsideRoot(root, relativePath) {
  if (!relativePath || path.isAbsolute(relativePath)) {
    throw new Error(`manifest path must be non-empty and relative: ${relativePath}`);
  }
  const resolvedRoot = path.resolve(root);
  const resolved = path.resolve(resolvedRoot, relativePath);
  const relation = path.relative(resolvedRoot, resolved);
  if (relation.startsWith("..") || path.isAbsolute(relation)) {
    throw new Error(`manifest path escapes authority root: ${relativePath}`);
  }
  return resolved;
}

async function sha256(filePath) {
  const bytes = await readFile(filePath);
  return createHash("sha256").update(bytes).digest("hex");
}

function requireTokens(label, text, tokens, failures) {
  for (const token of tokens) {
    if (!text.includes(token)) failures.push(`${label} missing required token: ${token}`);
  }
}

function requireOrderedTokens(label, text, tokens, failures) {
  let cursor = -1;
  for (const token of tokens) {
    const next = text.indexOf(token, cursor + 1);
    if (next === -1) {
      failures.push(`${label} missing ordered token: ${token}`);
      return;
    }
    cursor = next;
  }
}

function requireAuthorityVersion(relativePath, text, expectedVersion, failures) {
  const declarations = [...text.matchAll(/^Authority version:\s*`([^`\r\n]+)`\s*$/gm)];
  if (declarations.length !== 1) {
    failures.push(
      `${relativePath} authority version declaration count mismatch: observed ${declarations.length}, expected 1 with manifest version ${expectedVersion}`,
    );
    return;
  }

  const observedVersion = declarations[0][1];
  if (observedVersion !== expectedVersion) {
    failures.push(
      `${relativePath} authority version mismatch: observed ${observedVersion}, expected manifest version ${expectedVersion}`,
    );
  }
}

async function validate() {
  const { root, manifest: manifestArgument } = parseArguments(process.argv.slice(2));
  const failures = [];
  const manifestPath = resolveInsideRoot(root, manifestArgument);
  let manifest;

  try {
    manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  } catch (error) {
    throw new Error(`cannot load manifest ${manifestPath}: ${error.message}`);
  }

  if (manifest.schema_version !== "1.0.0") failures.push("manifest schema_version must be 1.0.0");
  const authorityVersionIsValid =
    typeof manifest.authority_version === "string" && AUTHORITY_VERSION_PATTERN.test(manifest.authority_version);
  if (!authorityVersionIsValid) failures.push("manifest authority_version must be a dotted numeric version (x.y.z)");
  if (manifest.status !== "P0_PROJECT_AUTHORITY") failures.push("manifest status must be P0_PROJECT_AUTHORITY");
  if (manifest.amendment_policy !== "P0_AUTHORITY_AMENDMENT") {
    failures.push("manifest amendment_policy must be P0_AUTHORITY_AMENDMENT");
  }
  const amendmentReason = typeof manifest.amendment_reason === "string" ? manifest.amendment_reason.trim() : "";
  if (!amendmentReason || DISALLOWED_AMENDMENT_REASONS.has(amendmentReason.toUpperCase())) {
    failures.push("manifest amendment_reason must be a non-placeholder string");
  }
  if (!Array.isArray(manifest.files)) failures.push("manifest files must be an array");

  const entries = Array.isArray(manifest.files) ? manifest.files : [];
  const paths = entries.map((entry) => entry?.path);
  if (JSON.stringify(paths) !== JSON.stringify(REQUIRED_FILES)) {
    failures.push(`manifest files must exactly match required ordered paths: ${REQUIRED_FILES.join(", ")}`);
  }
  if (paths.includes(manifestArgument.replaceAll("\\", "/"))) {
    failures.push("manifest must not include its own hash");
  }

  for (const entry of entries) {
    if (!entry || typeof entry.path !== "string" || !/^[0-9a-f]{64}$/.test(entry.sha256 ?? "")) {
      failures.push(`invalid manifest entry: ${JSON.stringify(entry)}`);
      continue;
    }
    try {
      const filePath = resolveInsideRoot(root, entry.path);
      const fileStat = await stat(filePath);
      if (!fileStat.isFile()) {
        failures.push(`authority path is not a file: ${entry.path}`);
        continue;
      }
      const actual = await sha256(filePath);
      if (actual !== entry.sha256) {
        failures.push(`sha256 mismatch for ${entry.path}: expected ${entry.sha256}, actual ${actual}`);
      }
    } catch (error) {
      failures.push(`cannot verify ${entry.path}: ${error.message}`);
    }
  }

  const texts = {};
  for (const relativePath of REQUIRED_FILES) {
    try {
      texts[relativePath] = await readFile(resolveInsideRoot(root, relativePath), "utf8");
    } catch (error) {
      failures.push(`cannot read required authority file ${relativePath}: ${error.message}`);
      texts[relativePath] = "";
    }
  }

  for (const relativePath of [
    "V3_PROJECT_CONSTITUTION.md",
    "docs/architecture/V3_CANONICAL_ARCHITECTURE.md",
    "docs/status/V3_CAPABILITY_LEVELS.md",
  ]) {
    requireAuthorityVersion(relativePath, texts[relativePath], manifest.authority_version, failures);
  }

  const agents = texts["AGENTS.md"];
  requireOrderedTokens("AGENTS read order", agents, [
    "/V3_PROJECT_CONSTITUTION.md",
    "/docs/architecture/V3_CANONICAL_ARCHITECTURE.md",
    "/docs/status/V3_CAPABILITY_LEVELS.md",
    "the complete task prompt",
    "the task State Ledger",
    "Git and GitHub CURRENT",
  ], failures);
  requireTokens("AGENTS", agents, [
    "TASK_GOAL",
    "TASK_PROGRESS",
    "PROJECT_AUTHORITY",
    "STOP_FOR_REVIEW",
    "SHA-256",
    "context compaction",
    "GitHub CURRENT",
    "canonical payload provenance",
    "Chinese-first",
    "low-chrome/no-box",
    "same PR",
    "No rebase, reset, force push",
    "P0 Authority Amendment Gate",
    "P0_AUTHORITY_AMENDMENT",
    "P0 authority file modification = forbidden",
    "original complete task prompt",
  ], failures);

  const constitution = texts["V3_PROJECT_CONSTITUTION.md"];
  requireTokens("Constitution", constitution, [
    "P0_PROJECT_AUTHORITY",
    "A local-first, A-share-first, AI-native, reproducible and auditable professional Quant Research IDE / Workbench.",
    "AI proposes and orchestrates; deterministic engines compute; V3 canonical owners validate, persist and own truth.",
    "Canonical Payload Resolver",
    "Verified Actual Payload",
    "Content-addressed Result",
    "FactorDefinitionVersion",
    "no second TDX VM",
    "PIT/as-of",
    "downstream truth/admission",
    "L0 READ",
    "L1 DRAFT",
    "L2 EXECUTE",
    "L3 PUBLISH",
    "INCOMPARABLE_CONTEXT",
    "Chinese-first — HARD",
    "Low-chrome / no-box — HARD",
    "No downgrade, substitution, or silent deferral",
    "No recursive correction chains",
    "Context compaction and State Ledgers",
    "Whole-system review questions",
    "P0 Authority Amendment Protocol — HARD",
    "P0_AUTHORITY_AMENDMENT",
    "MUST NOT modify any protected P0 Authority file or the Authority Manifest",
    "tamper-evident, governance-controlled, and Git-history traceable",
  ], failures);

  const capabilities = texts["docs/status/V3_CAPABILITY_LEVELS.md"];
  requireTokens("Capability Levels", capabilities, [
    ...MATURITY_LEVELS,
    ...ORTHOGONAL_STATES,
    "Generic `COMPLETE` is forbidden",
    "green unit tests",
    "merged backend PR",
    "Visual screenshot review",
    "runtime capability name",
  ], failures);
  const maturityHeading = "## Positive maturity levels";
  const orthogonalHeading = "## Orthogonal negative and unknown states";
  const maturityStart = capabilities.indexOf(maturityHeading);
  const maturityEnd = capabilities.indexOf(orthogonalHeading);
  if (maturityStart === -1 || maturityEnd <= maturityStart) {
    failures.push("Capability Levels must contain the bounded positive maturity table section");
  } else {
    const maturityRows = capabilities
      .slice(maturityStart + maturityHeading.length, maturityEnd)
      .split(/\r?\n/)
      .filter((line) => /^\|.*\|$/.test(line.trim()))
      .map((line) => line.trim().slice(1, -1).split("|").map((cell) => cell.trim()));
    if (maturityRows.length !== MATURITY_LEVELS.length + 2) {
      failures.push(`positive maturity table must have one header, one separator, and ${MATURITY_LEVELS.length} data rows; found ${maturityRows.length}`);
    }
    for (const row of maturityRows) {
      if (row.length !== 5) failures.push(`positive maturity table row must have 5 columns: ${row.join(" | ")}`);
    }
    const dataLevels = maturityRows.slice(2).map((row) => row[0]?.replaceAll("`", ""));
    if (JSON.stringify(dataLevels) !== JSON.stringify(MATURITY_LEVELS)) {
      failures.push(`positive maturity table levels must exactly match: ${MATURITY_LEVELS.join(", ")}`);
    }
  }

  const architecture = texts["docs/architecture/V3_CANONICAL_ARCHITECTURE.md"];
  requireTokens("Canonical Architecture", architecture, [
    "Canonical Ref",
    "Verified Payload",
    "Deterministic Engine",
    "Artifact/Provenance Receipt",
    "Domain Module",
    "Semantic Owner",
    "Integration Adapter",
    "Production Runtime Handler",
    "Desktop Bridge",
    "Product Surface",
    ...ARCHITECTURE_OWNERS,
  ], failures);
  const ownerFieldCount = (architecture.match(/\*\*Owner:\*\*/g) ?? []).length;
  if (ownerFieldCount !== ARCHITECTURE_OWNERS.length) {
    failures.push(`architecture must define exactly ${ARCHITECTURE_OWNERS.length} Owner fields; found ${ownerFieldCount}`);
  }

  if (failures.length > 0) {
    console.error("V3 project authority validation FAILED");
    for (const failure of failures) console.error(`- ${failure}`);
    process.exitCode = 1;
    return;
  }

  console.log(`V3 project authority validation PASS (${manifest.authority_version}; ${entries.length} locked files; ${ARCHITECTURE_OWNERS.length} owners)`);
}

validate().catch((error) => {
  console.error(`V3 project authority validation FAILED: ${error.message}`);
  process.exitCode = 1;
});
