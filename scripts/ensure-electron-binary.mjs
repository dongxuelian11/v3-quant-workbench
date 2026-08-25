import { createRequire } from "node:module";
import { access, mkdir, mkdtemp, readFile, rename, rm, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);

function executablePathFor(platform) {
  switch (platform) {
    case "darwin":
    case "mas":
      return "Electron.app/Contents/MacOS/Electron";
    case "freebsd":
    case "openbsd":
    case "linux":
      return "electron";
    case "win32":
      return "electron.exe";
    default:
      throw new Error(`Electron builds are not available on platform: ${platform}`);
  }
}

async function verifyExtractedDist(distRoot, expectedVersion, platformPath) {
  const observedVersion = (await readFile(join(distRoot, "version"), "utf8")).trim().replace(/^v/, "");
  if (observedVersion !== expectedVersion) {
    throw new Error(`Electron extracted version mismatch: expected=${expectedVersion} observed=${observedVersion}`);
  }
  await access(join(distRoot, platformPath));
}

async function installedState(packageRoot, expectedVersion, platformPath) {
  try {
    const recordedPath = await readFile(join(packageRoot, "path.txt"), "utf8");
    if (recordedPath !== platformPath) return false;
    await verifyExtractedDist(join(packageRoot, "dist"), expectedVersion, platformPath);
    return true;
  } catch {
    return false;
  }
}

export async function ensureElectronBinary({
  electronPackageRoot,
  platform = process.env.npm_config_platform || process.platform,
  arch = process.env.npm_config_arch || process.arch,
  downloadArtifactImpl,
  extractImpl,
} = {}) {
  const packageRoot = resolve(electronPackageRoot ?? dirname(require.resolve("electron/package.json")));
  const packageJson = JSON.parse(await readFile(join(packageRoot, "package.json"), "utf8"));
  const version = String(packageJson.version ?? "");
  if (!/^\d+\.\d+\.\d+$/.test(version)) throw new Error("Electron package version is invalid");
  const platformPath = executablePathFor(platform);
  if (await installedState(packageRoot, version, platformPath)) {
    return Object.freeze({ version, platform, arch, platformPath, alreadyInstalled: true });
  }

  const downloadArtifact = downloadArtifactImpl ?? require("@electron/get").downloadArtifact;
  const extract = extractImpl ?? require("extract-zip");
  const checksums = JSON.parse(await readFile(join(packageRoot, "checksums.json"), "utf8"));
  const zipPath = await downloadArtifact({
    version,
    artifactName: "electron",
    force: process.env.force_no_cache === "true",
    cacheRoot: process.env.electron_config_cache,
    checksums: (process.env.electron_use_remote_checksums || process.env.npm_config_electron_use_remote_checksums)
      ? undefined
      : checksums,
    platform,
    arch,
  });

  const stagingRoot = await mkdtemp(join(packageRoot, ".v3-electron-dist-"));
  const finalDist = join(packageRoot, "dist");
  try {
    await mkdir(stagingRoot, { recursive: true });
    await extract(zipPath, { dir: stagingRoot });
    await verifyExtractedDist(stagingRoot, version, platformPath);
    await rm(finalDist, { recursive: true, force: true });
    await rename(stagingRoot, finalDist);
    await writeFile(join(packageRoot, "path.txt"), platformPath, "utf8");
    if (!(await installedState(packageRoot, version, platformPath))) {
      throw new Error("Electron binary verification failed after publication");
    }
  } finally {
    await rm(stagingRoot, { recursive: true, force: true });
  }
  return Object.freeze({ version, platform, arch, platformPath, alreadyInstalled: false });
}

const isDirectExecution = process.argv[1] !== undefined && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isDirectExecution) {
  try {
    delete process.env.ELECTRON_SKIP_BINARY_DOWNLOAD;
    const installed = await ensureElectronBinary();
    process.stdout.write(`Electron ${installed.version} binary verified at ${installed.platformPath}\n`);
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.stack : String(error)}\n`);
    process.exitCode = 1;
  }
}
