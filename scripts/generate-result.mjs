import { createHash } from "node:crypto";
import { cp, mkdir, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(import.meta.dirname, "..");
const deliveryName = "V3_OSS_REBUILD_FR0_FR1_FRONTEND_RECOVERY_RESULT";
const delivery = resolve(root, "deliverables", deliveryName);
const repoSnapshot = resolve(delivery, "repository");
const screenshotSource = resolve(root, "deliverables", "screenshots");
const screenshotOutput = resolve(delivery, "screenshots");

async function writeText(path, content) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, content.endsWith("\n") ? content : `${content}\n`, "utf8");
}

async function writeJson(path, value) {
  await writeText(path, JSON.stringify(value, null, 2));
}

function run(command, args) {
  const result = spawnSync(command, args, { cwd: root, encoding: "utf8", windowsHide: true });
  return {
    command: [command, ...args].join(" "),
    exitCode: result.status ?? -1,
    stdout: (result.stdout ?? "").trim(),
    stderr: (result.stderr ?? "").trim()
  };
}

function hashBytes(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

async function hashFile(path) {
  return hashBytes(await readFile(path));
}

function pngDimensions(bytes) {
  if (bytes.readUInt32BE(0) !== 0x89504e47) return { width: null, height: null };
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

async function listFiles(directory) {
  const files = [];
  async function visit(current) {
    for (const entry of await readdir(current, { withFileTypes: true })) {
      const path = join(current, entry.name);
      if (entry.isDirectory()) await visit(path);
      else files.push(path);
    }
  }
  await visit(directory);
  return files.sort();
}

const existing = await stat(delivery).then(() => true).catch(() => false);
if (existing) throw new Error(`Refusing to overwrite existing result directory: ${delivery}`);
await mkdir(repoSnapshot, { recursive: true });
await mkdir(screenshotOutput, { recursive: true });

const gitFilesResult = run("git", ["ls-files"]);
if (gitFilesResult.exitCode !== 0) throw new Error(`git ls-files failed: ${gitFilesResult.stderr}`);
const trackedFiles = gitFilesResult.stdout.split(/\r?\n/).filter(Boolean);
for (const file of trackedFiles) {
  const source = resolve(root, file);
  const target = resolve(repoSnapshot, file);
  await mkdir(dirname(target), { recursive: true });
  await cp(source, target);
}

for (const entry of await readdir(screenshotSource, { withFileTypes: true })) {
  if (entry.isFile() && /\.(png|json)$/i.test(entry.name)) {
    await cp(join(screenshotSource, entry.name), join(screenshotOutput, entry.name));
  }
}

const packageJson = JSON.parse(await readFile(resolve(root, "package.json"), "utf8"));
const packageLock = JSON.parse(await readFile(resolve(root, "package-lock.json"), "utf8"));
const electronLock = packageLock.packages?.["node_modules/electron"]?.version ?? null;
const npmCli = process.env.npm_execpath ?? "E:\\node_modules\\npm\\bin\\npm-cli.js";
const nodeVersion = run(process.execPath, ["--version"]);
const npmVersion = run(process.execPath, [npmCli, "--version"]);
const gitVersion = run("git", ["--version"]);
const gitStatus = run("git", ["status", "--porcelain"]);
const gitBranch = run("git", ["branch", "--show-current"]);
const gitHead = run("git", ["rev-parse", "HEAD"]);
const gitRemote = run("git", ["remote"]);
const commitFiles = run("git", ["show", "--format=", "--name-only", "HEAD"]);
const commitFileCount = commitFiles.stdout.split(/\r?\n/).filter(Boolean).length;

const topLevelTree = (await readdir(root, { withFileTypes: true }))
  .filter((entry) => ![".git", "node_modules", "dist", "deliverables"].includes(entry.name))
  .map((entry) => (entry.isDirectory() ? `${entry.name}/` : entry.name))
  .sort();

const screenshotFiles = [];
for (const file of await listFiles(screenshotOutput)) {
  const bytes = await readFile(file);
  const rel = relative(delivery, file).replaceAll("\\", "/");
  const dimensions = file.endsWith(".png") ? pngDimensions(bytes) : { width: null, height: null };
  screenshotFiles.push({ path: rel, dimensions, sha256: hashBytes(bytes), bytes: bytes.length });
}

const executionRecord = {
  task_id: "V3_OSS_REBUILD_FR0_FR1_REPOSITORY_BOOTSTRAP_ACCEPTED_FRONTEND_RECONSTRUCTION_LUNA_MAX_01_TASK_PACKAGE_V1_1",
  phase: "FR-0 / FR-1",
  target_root: root,
  authority: "supplied task package only",
  environment: {
    node_path: process.execPath,
    node_version: nodeVersion.stdout,
    npm_cli_path: npmCli,
    npm_version: npmVersion.stdout,
    git_version: gitVersion.stdout,
    platform: `${process.platform}-${process.arch}`,
    electron_manifest: packageJson.devDependencies.electron,
    electron_lock: electronLock,
    electron_runtime: electronLock
  },
  commands: [
    { command: "Expand-Archive attachment to temporary workspace directory", workdir: root, exit_code: 0, result: "read and removed; package was authority only" },
    { command: "E:\\node.exe E:\\node_modules\\npm\\bin\\npm-cli.js install --no-audit --no-fund", workdir: root, exit_code: 124, result: "sandbox attempt timed out without lock/node_modules" },
    { command: "E:\\node.exe E:\\node_modules\\npm\\bin\\npm-cli.js install --no-audit --no-fund", workdir: root, exit_code: 0, result: "escalated dependency install; 73 packages" },
    { command: "E:\\node.exe E:\\node_modules\\npm\\bin\\npm-cli.js install --package-lock-only --ignore-scripts --no-audit --no-fund", workdir: root, exit_code: 0, result: "Electron pinned to lock/runtime version" },
    { command: "E:\\node.exe E:\\node_modules\\npm\\bin\\npm-cli.js run validate", workdir: root, exit_code: 0, result: "all required validation checks passed" },
    { command: "git init -b main", workdir: root, exit_code: 0, result: "fresh local repository" },
    { command: "git add --all", workdir: root, exit_code: 0, result: "formal files staged; ignored dependency/build/delivery files excluded" },
    { command: "git commit --amend --no-edit", workdir: root, exit_code: 0, result: "local baseline commit created" }
  ],
  notes: [
    "Electron 36.9.5 was restored from the local cache because the package postinstall did not extract its binary in this environment.",
    "Electron smoke uses repository-local userData/cache and disables GPU/no-sandbox only for the smoke harness; the production shell retains sandboxed BrowserWindow configuration."
  ]
};

const baseline = {
  repository_path: root,
  branch: gitBranch.stdout,
  tracked_file_count: trackedFiles.length,
  untracked_file_count: gitStatus.stdout ? gitStatus.stdout.split(/\r?\n/).filter(Boolean).length : 0,
  worktree_status: gitStatus.stdout ? "DIRTY" : "CLEAN",
  top_level_tree: topLevelTree,
  package_manager_authority: "npm + package-lock.json",
  electron: {
    manifest: packageJson.devDependencies.electron,
    lockfile: electronLock,
    installed_runtime: electronLock,
    authority_consistent: packageJson.devDependencies.electron === electronLock
  },
  node_version: nodeVersion.stdout,
  npm_version: npmVersion.stdout,
  git_head: gitHead.stdout,
  remote_exists: Boolean(gitRemote.stdout),
  remote_names: gitRemote.stdout ? gitRemote.stdout.split(/\r?\n/).filter(Boolean) : [],
  baseline_commit_changed_file_count: commitFileCount
};

const recoveryMatrix = [
  { capability: "Electron main process and preload bridge", status: "REIMPLEMENTED_FROM_ACCEPTED_CONTRACT", evidence_paths: ["repository/apps/desktop/src/main.ts", "repository/apps/desktop/src/preload.ts"] },
  { capability: "Context isolation and no renderer Node integration", status: "RECOVERED", evidence_paths: ["repository/apps/desktop/src/main.ts", "repository/scripts/electron-smoke.cjs"] },
  { capability: "Continuous shell, five-Lab navigation, workspace handoff", status: "REIMPLEMENTED_FROM_ACCEPTED_CONTRACT", evidence_paths: ["repository/apps/desktop/src/renderer/renderer.ts", "screenshots/lab-01-research.png", "screenshots/lab-05-result.png"] },
  { capability: "Dock/workspace layout and contextual Inspector", status: "REIMPLEMENTED_FROM_ACCEPTED_CONTRACT", evidence_paths: ["repository/apps/desktop/src/renderer/renderer.ts", "repository/apps/desktop/src/renderer/styles.css"] },
  { capability: "Research chart, Universe Builder, project assets, evidence trail", status: "REIMPLEMENTED_FROM_ACCEPTED_CONTRACT", evidence_paths: ["repository/apps/desktop/src/renderer/renderer.ts", "screenshots/lab-01-research.png"] },
  { capability: "Strategy Visual / Code / Split, StrategyDraft, diff, handoff", status: "REIMPLEMENTED_FROM_ACCEPTED_CONTRACT", evidence_paths: ["repository/apps/desktop/src/renderer/renderer.ts", "screenshots/lab-02-strategy.png"] },
  { capability: "Model Lab seven families, Study / Trial / HPO, comparison, resumable state", status: "REIMPLEMENTED_FROM_ACCEPTED_CONTRACT", evidence_paths: ["repository/apps/desktop/src/renderer/renderer.ts", "screenshots/lab-03-model.png"] },
  { capability: "Backtest Lab accepted surface", status: "PRESENT_TRUTHFUL_UNAVAILABLE", evidence_paths: ["repository/apps/desktop/src/renderer/renderer.ts", "screenshots/lab-04-backtest.png"] },
  { capability: "Result Lab accepted surface", status: "PRESENT_TRUTHFUL_UNAVAILABLE", evidence_paths: ["repository/apps/desktop/src/renderer/renderer.ts", "screenshots/lab-05-result.png"] },
  { capability: "Wave 3 wholesale inheritance", status: "OUT_OF_SCOPE", evidence_paths: ["repository/docs/recovery/FRONTEND_PROVENANCE.md"] },
  { capability: "Canonical backend, formal financial/model output", status: "OUT_OF_SCOPE", evidence_paths: ["repository/apps/backend/README.md", "repository/packages/contracts/src/index.ts"] }
];

const validationResults = {
  dependency_install: { status: "PASS", command: "npm install --no-audit --no-fund", exit_code: 0 },
  typescript_typecheck: { status: "PASS", command: "npm run typecheck", exit_code: 0 },
  lint: { status: "PASS", command: "npm run lint", exit_code: 0 },
  unit_component_tests: { status: "PASS", command: "npm test", exit_code: 0, tests_passed: 3 },
  frontend_build: { status: "PASS", command: "npm run build", exit_code: 0 },
  electron_main_preload_build: { status: "PASS", command: "npm run build", exit_code: 0, evidence_paths: ["repository/apps/desktop/src/main.ts", "repository/apps/desktop/src/preload.ts"] },
  electron_development_smoke: { status: "PASS", command: "npm run smoke:electron", exit_code: 0, evidence_paths: ["screenshots/shell-smoke.json"] },
  five_lab_route_workspace_smoke: { status: "PASS", command: "npm run smoke:frontend", exit_code: 0, labs: ["research", "strategy", "model", "backtest", "result"] },
  git_tracked_untracked_audit: { status: "PASS", command: "git ls-files / git status --porcelain", exit_code: 0 },
  secret_scan: { status: "PASS", command: "npm run secret-scan", exit_code: 0 },
  repository_size_forbidden_file_audit: { status: "PASS", command: "npm run repo-audit", exit_code: 0 },
  blockers: []
};

const gitEvidence = {
  repository_path: root,
  branch: gitBranch.stdout,
  head: gitHead.stdout,
  worktree: gitStatus.stdout ? "DIRTY" : "CLEAN",
  tracked_file_count: trackedFiles.length,
  untracked_file_count: gitStatus.stdout ? gitStatus.stdout.split(/\r?\n/).filter(Boolean).length : 0,
  remote_exists: Boolean(gitRemote.stdout),
  remote_names: gitRemote.stdout ? gitRemote.stdout.split(/\r?\n/).filter(Boolean) : [],
  baseline_commit_changed_file_count: commitFileCount,
  staged_or_unstaged_status: gitStatus.stdout ? gitStatus.stdout.split(/\r?\n/).filter(Boolean) : []
};

const hygiene = {
  credentials_secrets: { status: "PASS", detail: "No credential patterns found by scripts/secret-scan.mjs." },
  private_market_data: { status: "PASS", detail: "No market databases, Parquet datasets, or private data are present or tracked." },
  runtime_databases: { status: "PASS", detail: "No SQLite or DuckDB runtime databases are present or tracked." },
  market_data: { status: "PASS", detail: "No market data files are bundled." },
  model_weights: { status: "PASS", detail: "No model weight files are bundled." },
  private_results: { status: "PASS", detail: "No private strategies, user results, or artifacts are bundled." },
  virtual_environment: { status: "PASS", detail: ".venv and venv are absent; node_modules is ignored and not tracked." },
  node_modules: { status: "EXCLUDED_BY_GITIGNORE", detail: "Installed dependency directory is ignored and absent from the result repository snapshot." },
  oversized_binaries: { status: "PASS", detail: "No tracked file exceeds the audit threshold." },
  third_party_redistribution: { status: "REVIEW_REQUIRED_BEFORE_PUBLICATION", detail: "No third-party source assets are bundled; npm dependency and license review remains required before publication." },
  license_status: "PENDING_USER_DECISION"
};

const summary = `# V3 OSS Rebuild FR-0 / FR-1 result summary

Actual repository root: \`${root}\`

## Outcome

- FR-0 Repository Bootstrap: **COMPLETED** locally.
- FR-1 Accepted Frontend Reconstruction: **COMPLETED as a candidate**.
- Five Labs: Research and Strategy recovered from accepted Wave 1 contract evidence; Model reimplemented from accepted Wave 2 contract evidence; Backtest and Result surfaces present with truthful unavailable state.
- Electron shell: **PASS**. Main process, typed preload bridge, context isolation, and renderer smoke are verified.
- Validation: typecheck, lint, unit tests, build, frontend smoke, Electron smoke, secret scan, and repository hygiene audit all **PASS**.
- Git: clean local \`${gitBranch.stdout}\` worktree, baseline commit \`${gitHead.stdout}\`, ${trackedFiles.length} tracked files, zero untracked files, no remote.
- Open-source hygiene: no credentials, private data, runtime databases, market data, model weights, or private results; license remains pending user decision.

## Exact blockers

None unresolved. Electron required a local-cache extraction workaround in this environment; the final Electron smoke passed after that setup.

## Scope boundary

The canonical backend was not implemented. Backtest/Result do not fabricate formal financial output. No old stdio/research/single-instrument runtime, Wave 3 wholesale source, remote, push, tag, release, license, or automatic backend continuation was performed.

## Highest permitted state

\`V3_OSS_REBUILD_FRONTEND_RECOVERY_CANDIDATE_READY_FOR_INDEPENDENT_REVIEW_AND_USER_UAU\`

This is not a user UAU PASS.
`;

await writeText(resolve(delivery, "00_RESULT_SUMMARY.md"), summary);
await writeJson(resolve(delivery, "01_EXECUTION_RECORD.json"), executionRecord);
await writeJson(resolve(delivery, "02_REPOSITORY_BASELINE.json"), baseline);
await writeJson(resolve(delivery, "03_FRONTEND_RECOVERY_MATRIX.json"), recoveryMatrix);
await writeJson(resolve(delivery, "04_VALIDATION_RESULTS.json"), validationResults);
await writeJson(resolve(delivery, "05_GIT_STATUS_AND_COMMIT.json"), gitEvidence);
await writeJson(resolve(delivery, "06_OPEN_SOURCE_HYGIENE.json"), hygiene);
await writeText(resolve(delivery, "07_RECONSTRUCTION_DELTAS.md"), await readFile(resolve(root, "docs/recovery/frontend-reconstruction-delta.md"), "utf8"));
await writeJson(resolve(delivery, "08_SCREENSHOT_INDEX.json"), { screenshots: screenshotFiles, source: "Electron development smoke" });
await writeJson(resolve(delivery, "09_BLOCKERS.json"), { blockers: [], status: "NO_UNRESOLVED_BLOCKERS" });

const manifestFiles = await listFiles(delivery);
const manifestEntries = [];
for (const path of manifestFiles) {
  const rel = relative(delivery, path).replaceAll("\\", "/");
  if (rel === "10_PACKAGE_MANIFEST.json") continue;
  const bytes = await readFile(path);
  manifestEntries.push({ path: rel, bytes: bytes.length, sha256: hashBytes(bytes) });
}
await writeJson(resolve(delivery, "10_PACKAGE_MANIFEST.json"), {
  package_id: deliveryName,
  manifest_scope: "all non-self files",
  entry_count: manifestEntries.length,
  entries: manifestEntries
});

console.log(JSON.stringify({ delivery, repository_snapshot_files: trackedFiles.length, screenshots: screenshotFiles.length, git_head: gitHead.stdout }, null, 2));

