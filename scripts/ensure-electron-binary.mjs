import { createRequire } from "node:module";
import { createWriteStream } from "node:fs";
import { access, mkdir, mkdtemp, readFile, rename, rm, writeFile } from "node:fs/promises";
import http from "node:http";
import https from "node:https";
import { dirname, join, resolve } from "node:path";
import { pipeline } from "node:stream/promises";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ELECTRON_DOWNLOAD_TIMEOUT_MS = 10 * 60 * 1_000;
const ELECTRON_DOWNLOAD_MAX_REDIRECTS = 10;

function transportFor(url) {
  if (url.protocol === "http:") return http;
  if (url.protocol === "https:") return https;
  throw new Error(`unsupported Electron download protocol: ${url.protocol}`);
}

async function downloadOnce(url, targetPath, timeoutMilliseconds, redirectsRemaining) {
  if (redirectsRemaining < 0) throw new Error("Electron download exceeded the redirect limit");
  await new Promise((resolveDownload, rejectDownload) => {
    let settled = false;
    let timer;
    const settle = (error) => {
      if (settled) return;
      settled = true;
      if (timer !== undefined) clearTimeout(timer);
      if (error) rejectDownload(error);
      else resolveDownload();
    };
    const request = transportFor(url).get(url, (response) => {
      const statusCode = response.statusCode ?? 0;
      if (statusCode >= 300 && statusCode < 400 && response.headers.location) {
        response.resume();
        if (timer !== undefined) clearTimeout(timer);
        downloadOnce(
          new URL(response.headers.location, url),
          targetPath,
          timeoutMilliseconds,
          redirectsRemaining - 1,
        ).then(() => settle(), settle);
        return;
      }
      if (statusCode !== 200) {
        response.resume();
        settle(new Error(`Electron download returned HTTP ${statusCode}`));
        return;
      }
      pipeline(response, createWriteStream(targetPath, { flags: "w" })).then(
        () => settle(),
        settle,
      );
    });
    request.once("error", settle);
    timer = setTimeout(
      () => request.destroy(new Error(`Electron download timed out after ${timeoutMilliseconds} milliseconds`)),
      timeoutMilliseconds,
    );
  });
}

export function createElectronDownloader({
  timeoutMilliseconds = ELECTRON_DOWNLOAD_TIMEOUT_MS,
  maxRedirects = ELECTRON_DOWNLOAD_MAX_REDIRECTS,
} = {}) {
  if (!Number.isSafeInteger(timeoutMilliseconds) || timeoutMilliseconds <= 0) {
    throw new Error("Electron download timeout must be a positive safe integer");
  }
  if (!Number.isSafeInteger(maxRedirects) || maxRedirects < 0) {
    throw new Error("Electron download redirect limit must be a non-negative safe integer");
  }
  return Object.freeze({
    async download(url, targetPath) {
      try {
        await downloadOnce(new URL(url), targetPath, timeoutMilliseconds, maxRedirects);
      } catch (error) {
        await rm(targetPath, { force: true });
        throw error;
      }
    },
  });
}

export async function awaitWithProcessLiveness(operation, {
  setIntervalImpl = setInterval,
  clearIntervalImpl = clearInterval,
} = {}) {
  if (typeof operation !== "function") throw new Error("Electron liveness operation must be callable");
  const livenessHandle = setIntervalImpl(() => {}, 1_000);
  livenessHandle?.ref?.();
  try {
    return await operation();
  } finally {
    clearIntervalImpl(livenessHandle);
  }
}

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
  const downloader = createElectronDownloader();
  const extract = extractImpl ?? require("extract-zip");
  const checksums = JSON.parse(await readFile(join(packageRoot, "checksums.json"), "utf8"));
  const zipPath = await awaitWithProcessLiveness(() => downloadArtifact({
    version,
    artifactName: "electron",
    force: process.env.force_no_cache === "true",
    cacheRoot: process.env.electron_config_cache,
    checksums: (process.env.electron_use_remote_checksums || process.env.npm_config_electron_use_remote_checksums)
      ? undefined
      : checksums,
    platform,
    arch,
    downloader,
  }));

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
