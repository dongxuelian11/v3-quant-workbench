import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { access, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { pathToFileURL } from "node:url";

const {
  awaitWithProcessLiveness,
  createElectronDownloader,
  ensureElectronBinary,
} = await import("../../scripts/ensure-electron-binary.mjs");

async function listen(server) {
  await new Promise((resolveListen, rejectListen) => {
    server.once("error", rejectListen);
    server.listen(0, "127.0.0.1", resolveListen);
  });
  const address = server.address();
  assert(address && typeof address === "object");
  return `http://127.0.0.1:${address.port}`;
}

async function close(server) {
  server.closeAllConnections?.();
  await new Promise((resolveClose) => server.close(resolveClose));
}

test("Electron downloader follows redirects and publishes only a completed archive", async () => {
  const root = await mkdtemp(join(tmpdir(), "v3-electron-download-"));
  const target = join(root, "electron.zip");
  const server = createServer((request, response) => {
    if (request.url === "/redirect") {
      response.writeHead(302, { location: "/archive" });
      response.end();
      return;
    }
    response.writeHead(200, { "content-type": "application/zip" });
    response.write("verified ");
    setTimeout(() => response.end("archive"), 20);
  });
  try {
    const origin = await listen(server);
    const downloader = createElectronDownloader({ timeoutMilliseconds: 1_000 });
    await downloader.download(`${origin}/redirect`, target);
    assert.equal(await readFile(target, "utf8"), "verified archive");
  } finally {
    await close(server);
    await rm(root, { recursive: true, force: true });
  }
});

test("Electron downloader rejects an unsettled transfer and removes partial bytes", async () => {
  const root = await mkdtemp(join(tmpdir(), "v3-electron-download-timeout-"));
  const target = join(root, "electron.zip");
  const server = createServer((_request, _response) => {});
  try {
    const origin = await listen(server);
    const downloader = createElectronDownloader({ timeoutMilliseconds: 50 });
    await assert.rejects(downloader.download(`${origin}/archive`, target), /timed out/);
    await assert.rejects(access(target));
  } finally {
    await close(server);
    await rm(root, { recursive: true, force: true });
  }
});

test("Electron artifact resolution owns a ref'ed liveness handle until settlement", async () => {
  const marker = { refCalls: 0, ref() { this.refCalls += 1; } };
  const cleared = [];
  const options = {
    setIntervalImpl(callback, delay) {
      assert.equal(typeof callback, "function");
      assert.equal(delay, 1_000);
      return marker;
    },
    clearIntervalImpl(handle) {
      cleared.push(handle);
    },
  };
  assert.equal(await awaitWithProcessLiveness(async () => "settled", options), "settled");
  assert.equal(marker.refCalls, 1);
  assert.deepEqual(cleared, [marker]);
  await assert.rejects(
    awaitWithProcessLiveness(async () => { throw new Error("download failed"); }, options),
    /download failed/,
  );
  assert.deepEqual(cleared, [marker, marker]);
});

test("Electron installer retains process liveness through extraction and publication", async () => {
  const packageRoot = await mkdtemp(join(tmpdir(), "v3-electron-liveness-"));
  const moduleUrl = pathToFileURL(join(process.cwd(), "scripts", "ensure-electron-binary.mjs")).href;
  try {
    await writeFile(join(packageRoot, "package.json"), JSON.stringify({ version: "39.8.10" }), "utf8");
    await writeFile(join(packageRoot, "checksums.json"), "{}", "utf8");
    const child = spawnSync(process.execPath, [
      "--input-type=module",
      "--eval",
      `import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { ensureElectronBinary } from ${JSON.stringify(moduleUrl)};
const packageRoot = ${JSON.stringify(packageRoot)};
const installed = await ensureElectronBinary({
  electronPackageRoot: packageRoot,
  platform: "win32",
  arch: "x64",
  downloadArtifactImpl: async () => join(packageRoot, "electron.zip"),
  extractImpl: async (_zipPath, { dir }) => new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      (async () => {
        await mkdir(dir, { recursive: true });
        await writeFile(join(dir, "version"), "39.8.10", "utf8");
        await writeFile(join(dir, "electron.exe"), "binary", "utf8");
      })().then(resolve, reject);
    }, 40);
    timer.unref();
  }),
});
process.stdout.write(installed.platformPath);`,
    ], { encoding: "utf8", timeout: 5_000 });
    assert.equal(child.status, 0, child.stderr);
    assert.equal(child.stdout, "electron.exe");
    assert.doesNotMatch(child.stderr, /unsettled top-level await/i);
  } finally {
    await rm(packageRoot, { recursive: true, force: true });
  }
});

test("Electron installer awaits verified extraction and becomes idempotent", async () => {
  const root = await mkdtemp(join(tmpdir(), "v3-electron-installer-"));
  const packageRoot = join(root, "electron");
  const zipPath = join(root, "electron.zip");
  await mkdir(packageRoot);
  await writeFile(join(packageRoot, "package.json"), JSON.stringify({ version: "39.8.10" }));
  await writeFile(join(packageRoot, "checksums.json"), "{}");
  await writeFile(zipPath, "fake archive");
  let downloads = 0;
  let extractions = 0;
  try {
    const options = {
      electronPackageRoot: packageRoot,
      platform: "win32",
      arch: "x64",
      downloadArtifactImpl: async (request) => {
        downloads += 1;
        assert.equal(request.version, "39.8.10");
        assert.equal(request.artifactName, "electron");
        assert.equal(request.platform, "win32");
        assert.equal(request.arch, "x64");
        assert.equal(typeof request.downloader?.download, "function");
        return zipPath;
      },
      extractImpl: async (_archive, { dir }) => {
        extractions += 1;
        await mkdir(dir, { recursive: true });
        await writeFile(join(dir, "version"), "v39.8.10");
        await writeFile(join(dir, "electron.exe"), "verified binary");
      },
    };
    const installed = await ensureElectronBinary(options);
    assert.equal(installed.version, "39.8.10");
    assert.equal(installed.platformPath, "electron.exe");
    assert.equal(await readFile(join(packageRoot, "path.txt"), "utf8"), "electron.exe");
    await access(join(packageRoot, "dist", "electron.exe"));

    const repeated = await ensureElectronBinary(options);
    assert.equal(repeated.alreadyInstalled, true);
    assert.equal(downloads, 1);
    assert.equal(extractions, 1);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Electron installer rejects an extracted version mismatch before publishing path.txt", async () => {
  const root = await mkdtemp(join(tmpdir(), "v3-electron-installer-mismatch-"));
  const packageRoot = join(root, "electron");
  const zipPath = join(root, "electron.zip");
  await mkdir(packageRoot);
  await writeFile(join(packageRoot, "package.json"), JSON.stringify({ version: "39.8.10" }));
  await writeFile(join(packageRoot, "checksums.json"), "{}");
  await writeFile(zipPath, "fake archive");
  try {
    await assert.rejects(
      ensureElectronBinary({
        electronPackageRoot: packageRoot,
        platform: "win32",
        arch: "x64",
        downloadArtifactImpl: async () => zipPath,
        extractImpl: async (_archive, { dir }) => {
          await mkdir(dir, { recursive: true });
          await writeFile(join(dir, "version"), "v39.8.9");
          await writeFile(join(dir, "electron.exe"), "wrong binary");
        },
      }),
      /version mismatch/,
    );
    await assert.rejects(access(join(packageRoot, "path.txt")));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
