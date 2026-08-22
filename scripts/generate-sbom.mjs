import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const lockPath = resolve(root, "package-lock.json");
const matrixPath = resolve(root, "docs/oss/THIRD_PARTY_LICENSE_MATRIX.csv");
const sbomPath = resolve(root, "sbom/v3-public-baseline.spdx.json");
const pythonLockPath = resolve(root, "apps/backend/python-dependency-lock.json");
const checkOnly = process.argv.includes("--check");

const lock = JSON.parse(await readFile(lockPath, "utf8"));
const rootPackage = lock.packages?.[""];
if (!rootPackage || lock.lockfileVersion !== 3) {
  throw new Error("Expected an npm package-lock v3 root package.");
}

const pythonLock = JSON.parse(await readFile(pythonLockPath, "utf8"));
if (pythonLock.schema_version !== "v3.python-dependency-lock/1.0.0" || !Array.isArray(pythonLock.packages) || pythonLock.packages.length === 0) {
  throw new Error("Expected the checked-in exact Python dependency lock.");
}

const directRuntime = new Set(Object.keys(rootPackage.dependencies ?? {}));
const directDevelopment = new Set(Object.keys(rootPackage.devDependencies ?? {}));

function packageName(path, metadata) {
  if (metadata.name) return metadata.name;
  const marker = "node_modules/";
  const index = path.lastIndexOf(marker);
  if (index < 0) return null;
  return path.slice(index + marker.length);
}

function normalizedLicense(value) {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (value && typeof value === "object" && typeof value.type === "string") return value.type;
  return "NOASSERTION";
}

function csv(value) {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function spdxId(name, version, index) {
  const safe = `${name}-${version}`.replace(/[^A-Za-z0-9.-]+/g, "-");
  return `SPDXRef-Package-${index + 1}-${safe}`;
}

function integrityChecksum(integrity) {
  if (typeof integrity !== "string") return undefined;
  const sha256Match = /^sha256=(.+)$/.exec(integrity);
  if (sha256Match) return { algorithm: "SHA256", checksumValue: sha256Match[1].toUpperCase() };
  const match = /^sha512-(.+)$/.exec(integrity);
  if (!match) return undefined;
  return {
    algorithm: "SHA512",
    checksumValue: Buffer.from(match[1], "base64").toString("hex").toUpperCase()
  };
}

const packages = Object.entries(lock.packages)
  .filter(([path, metadata]) => path.includes("node_modules/") && !metadata.link)
  .map(([path, metadata]) => {
    const name = packageName(path, metadata);
    if (!name || !metadata.version) {
      throw new Error(`Package entry lacks name/version: ${path}`);
    }
    const directRole = directRuntime.has(name)
      ? "direct-runtime"
      : directDevelopment.has(name)
        ? "direct-development"
        : "transitive";
    const nativeConcerns = [
      metadata.hasInstallScript ? "install-script" : null,
      metadata.os ? `os=${metadata.os.join("|")}` : null,
      metadata.cpu ? `cpu=${metadata.cpu.join("|")}` : null
    ].filter(Boolean).join("; ") || "none declared in package-lock";
    return {
      ecosystem: "npm",
      path,
      name,
      version: metadata.version,
      role: directRole,
      source: metadata.resolved ?? "npm lockfile (source URL not recorded)",
      license: normalizedLicense(metadata.license),
      redistributionNote: "Retain applicable upstream license and notice obligations; review package source before redistribution.",
      nativeConcerns,
      integrity: metadata.integrity
    };
  })
  .sort((a, b) => a.name.localeCompare(b.name) || a.version.localeCompare(b.version) || a.path.localeCompare(b.path));

const pythonPackages = pythonLock.packages.map((item) => {
  if (!item.name || !item.version || !item.source || !item.integrity) {
    throw new Error(`Python dependency lock entry is incomplete: ${JSON.stringify(item)}`);
  }
  return {
    ecosystem: "python",
    path: `apps/backend/python-dependency-lock.json#${item.name}@${item.version}`,
    name: item.name,
    version: item.version,
    role: item.role,
    source: item.source,
    license: normalizedLicense(item.license),
    redistributionNote: "Retain applicable upstream Python license and notice obligations; review package license files before redistribution.",
    nativeConcerns: item.native_runtime_concerns ?? "Python 3.14.5 win_amd64 packaged backend runtime",
    integrity: item.integrity
  };
});
const inventoryPackages = [...packages, ...pythonPackages]
  .sort((a, b) => a.name.localeCompare(b.name) || a.version.localeCompare(b.version) || a.ecosystem.localeCompare(b.ecosystem) || a.path.localeCompare(b.path));
const matrixHeader = [
  "package",
  "exact_locked_version",
  "role",
  "source",
  "license_spdx",
  "redistribution_note",
  "native_runtime_concerns"
];
const matrix = [
  matrixHeader.join(","),
  ...inventoryPackages.map((item) => [
    item.name,
    item.version,
    item.role,
    item.source,
    item.license,
    item.redistributionNote,
    item.nativeConcerns
  ].map(csv).join(","))
].join("\n") + "\n";

let created = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
try {
  const existing = JSON.parse(await readFile(sbomPath, "utf8"));
  if (typeof existing.creationInfo?.created === "string") created = existing.creationInfo.created;
} catch {
  // First generation establishes the stable document creation timestamp.
}

const namespaceDigest = createHash("sha256")
  .update(await readFile(lockPath))
  .update(await readFile(pythonLockPath))
  .digest("hex");
const rootSpdxId = "SPDXRef-Package-v3-oss-rebuild";
const directNames = new Set([...directRuntime, ...directDevelopment]);
const directPythonNames = new Set(pythonPackages.filter((item) => item.role === "direct-runtime").map((item) => item.name));
const isDirect = (item) => item.ecosystem === "python" ? directPythonNames.has(item.name) : directNames.has(item.name);
const spdxPackages = inventoryPackages.map((item, index) => {
  const checksum = integrityChecksum(item.integrity);
  return {
    SPDXID: spdxId(item.name, item.version, index),
    name: item.name,
    versionInfo: item.version,
    downloadLocation: item.source.startsWith("https://") ? item.source : "NOASSERTION",
    filesAnalyzed: false,
    licenseConcluded: "NOASSERTION",
    licenseDeclared: item.license,
    copyrightText: "NOASSERTION",
    ...(checksum ? { checksums: [checksum] } : {}),
    comment: `${item.ecosystem === "python" ? "Python dependency lock" : "npm package-lock v3"} path: ${item.path}; role: ${item.role}; native/runtime concerns: ${item.nativeConcerns}`
  };
});
const sbom = {
  spdxVersion: "SPDX-2.3",
  dataLicense: "CC0-1.0",
  SPDXID: "SPDXRef-DOCUMENT",
  name: "v3-public-baseline",
  documentNamespace: `https://v3.invalid/spdx/v3-public-baseline-${namespaceDigest}`,
  creationInfo: {
    created,
    creators: ["Tool: scripts/generate-sbom.mjs"]
  },
  documentDescribes: [rootSpdxId],
  packages: [
    {
      SPDXID: rootSpdxId,
      name: rootPackage.name,
      versionInfo: rootPackage.version,
      downloadLocation: "NOASSERTION",
      filesAnalyzed: false,
      licenseConcluded: "NOASSERTION",
      licenseDeclared: normalizedLicense(rootPackage.license),
      copyrightText: "NOASSERTION",
      comment: "Project license is declared by the root package metadata. Dependency inventory is derived from package-lock.json and apps/backend/python-dependency-lock.json; the packaged backend ships exact Python dependencies including AKShare 1.18.84."
    },
    ...spdxPackages
  ],
  relationships: [
    {
      spdxElementId: "SPDXRef-DOCUMENT",
      relationshipType: "DESCRIBES",
      relatedSpdxElement: rootSpdxId
    },
    ...inventoryPackages.flatMap((item, index) => isDirect(item) ? [{
      spdxElementId: rootSpdxId,
      relationshipType: "DEPENDS_ON",
      relatedSpdxElement: spdxId(item.name, item.version, index)
    }] : [])
  ]
};
const sbomText = JSON.stringify(sbom, null, 2) + "\n";

async function assertCurrent(path, expected, label) {
  let current;
  try {
    current = await readFile(path, "utf8");
  } catch {
    throw new Error(`${label} is missing; run npm run sbom:generate.`);
  }
  if (current !== expected) throw new Error(`${label} is stale; run npm run sbom:generate.`);
}

if (checkOnly) {
  await assertCurrent(matrixPath, matrix, "Third-party license matrix");
  await assertCurrent(sbomPath, sbomText, "SPDX SBOM");
  console.log(`SBOM check passed: ${inventoryPackages.length} npm/Python package entries.`);
} else {
  await mkdir(dirname(matrixPath), { recursive: true });
  await mkdir(dirname(sbomPath), { recursive: true });
  await writeFile(matrixPath, matrix, "utf8");
  await writeFile(sbomPath, sbomText, "utf8");
  console.log(`Generated SPDX 2.3 SBOM and license matrix for ${inventoryPackages.length} npm/Python package entries.`);
}
