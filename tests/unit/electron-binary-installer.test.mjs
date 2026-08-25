import assert from "node:assert/strict";
import test from "node:test";
import { access, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";

const { ensureElectronBinary } = await import("../../scripts/ensure-electron-binary.mjs");

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
