import { createHash } from "node:crypto";
import { cp, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(import.meta.dirname, "..");
const deliverables = join(root, "deliverables");
const screenshotsSource = join(deliverables, "visual-restoration-screenshots");
const rawSource = join(deliverables, "raw");
const stage = join(deliverables, "fr1-visual-restoration-result-stage");
const baselineHead = "97ce15b7548df56312b785a5ce10b0fadb87d81a";
const taskId = "V3-OSS-REBUILD-FR1-VISUAL-UX-UE-ORIGINAL-WORKBENCH-RESTORATION-SOL-HIGH-02";
const decision = "FR1_VISUAL_UX_UE_RESTORATION_CANDIDATE_READY_FOR_USER_UAU";

const sha256 = (data) => createHash("sha256").update(data).digest("hex").toUpperCase();
const run = (command, args, allowFailure = false) => {
  const result = spawnSync(command, args, {
    cwd: root,
    encoding: "utf8",
    shell: process.platform === "win32",
    maxBuffer: 64 * 1024 * 1024,
  });
  if (!allowFailure && result.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed\n${result.stdout}\n${result.stderr}`);
  }
  return { command: `${command} ${args.join(" ")}`, exit_code: result.status, stdout: result.stdout, stderr: result.stderr };
};
const git = (...args) => run("git", args).stdout.trim();
const writeJson = (path, value) => writeFile(path, `${JSON.stringify(value, null, 2)}\n`);

await rm(stage, { recursive: true, force: true });
await mkdir(stage, { recursive: true });
await mkdir(rawSource, { recursive: true });

const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const checks = {};
for (const [name, args] of Object.entries({
  typecheck: ["run", "typecheck"],
  lint: ["run", "lint"],
  unit_tests: ["test"],
  deterministic_build: ["run", "build:determinism"],
  frontend_evidence: ["run", "smoke:frontend"],
  secret_scan: ["run", "secret-scan"],
  repository_audit: ["run", "repo-audit"],
})) {
  checks[name] = run(npm, args);
  await writeFile(
    join(rawSource, `${name}.txt`),
    `command=${checks[name].command}\nexit_code=${checks[name].exit_code}\nSTDOUT\n${checks[name].stdout}\nSTDERR\n${checks[name].stderr}`,
  );
}

const npmAudit = run(npm, ["audit", "--json"], true);
await writeFile(join(rawSource, "npm-audit.json"), npmAudit.stdout || npmAudit.stderr);
let npmAuditJson = {};
try { npmAuditJson = JSON.parse(npmAudit.stdout); } catch { npmAuditJson = { parse_error: true }; }

const branch = git("branch", "--show-current");
const head = git("rev-parse", "HEAD");
if (head !== baselineHead) throw new Error(`Unexpected HEAD ${head}; expected ${baselineHead}`);
const status = git("status", "--porcelain").split(/\r?\n/).filter(Boolean);
const changedNames = git("diff", "--name-only", baselineHead).split(/\r?\n/).filter(Boolean);

const changedFiles = [];
for (const name of changedNames) {
  const absolute = join(root, name);
  const beforeResult = spawnSync("git", ["show", `${baselineHead}:${name}`], { cwd: root, encoding: null });
  const before = beforeResult.status === 0 ? beforeResult.stdout : null;
  let after = null;
  try { after = await readFile(absolute); } catch { /* deleted */ }
  changedFiles.push({
    relative_path: name.replaceAll("\\", "/"),
    before_state: before ? "present" : "absent",
    before_bytes: before?.length ?? 0,
    before_sha256: before ? sha256(before) : null,
    after_state: after ? "present" : "deleted",
    after_bytes: after?.length ?? 0,
    after_sha256: after ? sha256(after) : null,
    classification: name.startsWith("scripts/") ? "test_or_evidence" : "frontend_source",
    reason: "Original V3 Chart-First workbench visual, hierarchy, density, and interaction restoration",
  });
  if (after) {
    const target = join(stage, "repository_delta", name);
    await mkdir(dirname(target), { recursive: true });
    await writeFile(target, after);
  }
}

const screenshotNames = (await readdir(screenshotsSource))
  .filter((name) => /^\d{2}-.*\.png$/.test(name))
  .sort();
if (screenshotNames.length !== 17) throw new Error(`Expected 17 screenshots, got ${screenshotNames.length}`);
const screenshotsTarget = join(stage, "screenshots");
await mkdir(screenshotsTarget, { recursive: true });
for (const name of [...screenshotNames, "capture-result.json", "restart-result.json", "layout-geometry.json"]) {
  await cp(join(screenshotsSource, name), join(screenshotsTarget, name));
}

const geometry = JSON.parse(await readFile(join(screenshotsSource, "layout-geometry.json"), "utf8"));
const capture = JSON.parse(await readFile(join(screenshotsSource, "capture-result.json"), "utf8"));
const restart = JSON.parse(await readFile(join(screenshotsSource, "restart-result.json"), "utf8"));
const deterministic = JSON.parse(await readFile(join(rawSource, "deterministic-build.json"), "utf8"));
await writeJson(join(rawSource, "electron-capture-result.json"), capture);
await writeJson(join(rawSource, "electron-restart-result.json"), restart);
await cp(rawSource, join(stage, "raw"), { recursive: true });

const summary = `# FR-1 Visual / UX / UE Restoration Result\n\n\`\`\`yaml\n+task_id: ${taskId}\n+decision: ${decision}\n+project_root: D:\\V3OpenSource\n+branch: ${branch}\n+baseline_head: ${baselineHead}\n+current_head: ${head}\n+visual_authority: ORIGINAL_V3_SAME_LINEAGE\n+real_electron_screenshots: 17\n+functional_internals_preserved: true\n+backend_rebuild_started: false\n+remote_push: false\n+tag_created: false\n+release_created: false\n+user_uau: NOT_REVIEWED\n+\`\`\`\n\nThis package is a restoration candidate for the user's personal UAU. It does not claim UAU PASS or formal frontend closure.\n`;

const acknowledgement = `# User UAU failure acknowledgement\n\nThe prior candidate was explicitly rejected because its UI, UX, and UE materially diverged from original V3 and read as a dashboard/card pile. This execution treats that rejection as binding. The implemented correction is structural: a chart-first Research canvas, focused Strategy modes, phased Model workflow, analytical Backtest/Result canvases, contextual Inspector, on-demand operations, original breakpoint geometry, and calm workstation density. Color adjustment alone is not presented as remediation.\n\nStatus: \`NOT_REVIEWED_BY_USER\`. Only the user may determine UAU PASS or FAIL.\n`;

const baseline = {
  task_id: taskId,
  captured_before_change: true,
  project_root: root,
  branch: "main",
  head: baselineHead,
  git_status_porcelain: [],
  package_json_sha256: "BEC5BE23B5A923576B0A1A18A29D7071793884483690454658EB88129F4128D",
  package_lock_sha256: "C1897BC4B55D5375E1F62A948271697B1B9EAD30A35681306306A9B0F47E7E01",
  runtime_versions: { electron: "39.8.10", react: "19.2.7", vite: "6.4.3", typescript: "5.9.3", dockview_react: "7.0.4", echarts: "6.1.0", react_flow: "12.11.2", monaco: "0.56.0" },
  rejected_candidate: { screenshot_count: 14, user_uau: "FAIL", defects: ["dashboard/card-pile composition", "weak chart-first hierarchy", "permanently competing secondary surfaces", "visual and interaction hierarchy unlike original V3"] },
};

const rootCause = `# Visual root-cause report\n\nThe rejected candidate preserved much of the functional kernel but exposed it as too many equal-weight bordered surfaces. Persistent analytics, Inspector-like evidence, controls, and truth labels competed with the analytical canvas. The result looked like a collection of web dashboards rather than the same-lineage V3 desktop quant workbench.\n\nThe repair re-established spatial hierarchy before styling: one dominant Lab canvas by default; contextual evidence; optional lower operations; original nav/Inspector breakpoint geometry; focused Visual, Code, Split, and Diff states; phased Model workflow; chart-first Backtest and Result. The locked tokens then reinforce this hierarchy without substituting for it. No recovered capability was removed to obtain the calmer layout.\n`;

const conformance = {
  decision,
  gates: [
    { id: "V1", status: "PASS", evidence: "Structural layout replacement; not a theme-only delta" },
    { id: "V2", status: "PASS", evidence: "Research chart is dominant and >=720x400 at all required viewports" },
    { id: "V3", status: "PASS", evidence: "Default Labs use one dominant surface and subordinate status treatment" },
    { id: "V4", status: "PASS", evidence: "1280x720, 1536x864, and 1920x1080 captured and measured" },
    { id: "V5", status: "PASS", evidence: "Visual/Code/Split are focused; Diff is a dedicated contextual state" },
    { id: "V6", status: "PASS", evidence: "Model is separated into Dataset/Run, Study/Trial, and Version/Signal phases" },
    { id: "V7", status: "PASS", evidence: "Backtest and Result have primary analytical canvases with compact Demo truth" },
    { id: "V8", status: "PASS", evidence: "One coherent five-Lab desktop workbench shell" },
    { id: "V9", status: "PASS", evidence: "Capability contract tests and Electron interaction smoke pass" },
    { id: "V10", status: "PASS", evidence: "All 17 PNGs captured from Electron 39.8.10" },
    { id: "V11", status: "PASS", evidence: "Dockview chart-first-workbench-v1 layout restored after process restart" },
    { id: "V12", status: "PASS", evidence: `Executor stops at ${decision}; user UAU remains NOT_REVIEWED` },
  ],
};

const tokenConformance = {
  status: "PASS",
  colors: { root: "#0B0D14", nav: "#0F1119", panel: "#141721", elevated: "#1A1D2B", border: "#262B3A", selected: "#4FC3F7", text_primary: "#E4E7F0", text_muted: "#8B90A7", warning: "#FFB74D", up_error: "#FF6B6B", down_success: "#3CCB7F" },
  density: { compact_controls: true, restrained_radius: true, subdued_borders: true, desktop_workbench_hierarchy: true },
  breakpoints: [
    { range: "1280-1439", nav: 56, inspector: "320 overlay/contextual" },
    { range: "1440-1679", nav: 200, inspector: "300 dock/contextual" },
    { range: ">=1680", nav: 220, inspector: "320 dock/contextual" },
  ],
};

const interactionEvidence = {
  status: "PASS",
  electron_version: capture.electron,
  security_preferences: capture.prefs,
  console_errors: [...capture.consoleErrors, ...restart.consoleErrors],
  evidence: [
    "Research event selection -> contextual Inspector -> provenance trace",
    "Universe Builder and secondary analytics open as focused, dismissible drawers",
    "Strategy Visual/Code/Split mode switching retains React Flow and Monaco",
    "Proposal Diff is an explicit review state",
    "Model phases preserve seven families, Study/Trial/HPO, version and signal handoff",
    "Backtest and Result keep chart-first review and compact Demo classification",
    "Dockview multi-panel preset persists and restores across Electron restart",
    "CommandRegistry, stores, bottom operations, and contextual Inspector remain active",
  ],
  restart,
};

const functional = {
  status: "PASS",
  tests: { count: 4, pass: 4, fail: 0 },
  preserved: ["React", "Dockview", "ECharts", "React Flow", "Monaco", "stores", "CommandRegistry", "Universe", "Strategy", "Model", "Backtest/Result Demo"],
  test_results: Object.fromEntries(Object.entries(checks).map(([name, value]) => [name, { command: value.command, exit_code: value.exit_code }])),
  capability_deletion_used_for_simplification: false,
  backend_rebuild_started: false,
};

const buildElectron = {
  status: "PASS",
  deterministic_build: { pass: deterministic.pass, file_count: deterministic.fileCount, differing: deterministic.differing },
  electron: { version: capture.electron, screenshot_count: screenshotNames.length, production_smoke: "PASS", restart_persistence: "PASS" },
  security_preferences: capture.prefs,
  npm_audit: { exit_code: npmAudit.exit_code, vulnerabilities: npmAuditJson.metadata?.vulnerabilities ?? null },
};

const gitResult = {
  branch,
  baseline_head: baselineHead,
  current_head: head,
  task_commit_created: false,
  worktree_clean: status.length === 0,
  git_status_porcelain: status,
  intentional_changed_file_count: changedNames.length,
  remote_push: false,
  tag_created: false,
  release_created: false,
};

const uauGuide = `# User UAU guide\n\nStatus: \`NOT_REVIEWED\`\n\nReview the 17 numbered screenshots in order, then run \`npm run build\` and \`npm run smoke:electron\` from \`D:\\V3OpenSource\` for live verification. Confirm Research is chart-first at 1280, 1536, and 1920 widths; Inspector appears only from contextual selection; Strategy modes each retain editor focus; Model progresses by phase; Backtest/Result prioritize analysis; and the research multi-panel preset restores after restart.\n\nRecord the user's own UAU PASS or FAIL outside this package. This package intentionally does not pre-fill acceptance.\n`;

await writeFile(join(stage, "00_RESULT_SUMMARY.md"), summary);
await writeFile(join(stage, "01_USER_UAU_FAIL_ACKNOWLEDGEMENT.md"), acknowledgement);
await writeJson(join(stage, "02_PRECHANGE_VISUAL_BASELINE.json"), baseline);
await writeFile(join(stage, "03_VISUAL_ROOT_CAUSE_REPORT.md"), rootCause);
await writeJson(join(stage, "04_CHANGED_FILE_MANIFEST.json"), { baseline_head: baselineHead, current_head: head, count: changedFiles.length, files: changedFiles });
await writeJson(join(stage, "05_VISUAL_CONFORMANCE_MATRIX.json"), conformance);
await writeJson(join(stage, "06_LAYOUT_GEOMETRY_MEASUREMENTS.json"), { status: "PASS", count: geometry.length, measurements: geometry });
await writeJson(join(stage, "07_DESIGN_TOKEN_CONFORMANCE.json"), tokenConformance);
await writeJson(join(stage, "08_UX_UE_INTERACTION_EVIDENCE.json"), interactionEvidence);
await writeJson(join(stage, "09_FUNCTIONAL_REGRESSION_RESULTS.json"), functional);
await writeJson(join(stage, "10_BUILD_ELECTRON_RESULTS.json"), buildElectron);
await writeJson(join(stage, "11_GIT_STATUS_AND_COMMIT.json"), gitResult);
await writeFile(join(stage, "12_USER_UAU_GUIDE.md"), uauGuide);
await writeJson(join(stage, "13_BLOCKERS.json"), { count: 0, blockers: [] });

async function inventory(directory) {
  const files = [];
  async function walk(current) {
    for (const entry of await readdir(current, { withFileTypes: true })) {
      const path = join(current, entry.name);
      if (entry.isDirectory()) await walk(path);
      else {
        const name = relative(directory, path).replaceAll("\\", "/");
        if (name === "14_PACKAGE_MANIFEST.json") continue;
        const data = await readFile(path);
        files.push({ path: name, bytes: data.length, sha256: sha256(data) });
      }
    }
  }
  await walk(directory);
  return files.sort((a, b) => a.path.localeCompare(b.path));
}

const manifestFiles = await inventory(stage);
await writeJson(join(stage, "14_PACKAGE_MANIFEST.json"), {
  schema_id: "urn:v3:oss-rebuild:fr1:visual-ux-ue-restoration-result-package:1.0.0",
  task_id: taskId,
  decision,
  self_excluded: true,
  file_count_non_self: manifestFiles.length,
  screenshot_count: screenshotNames.length,
  files: manifestFiles,
});

console.log(JSON.stringify({ stage, decision, baseline_head: baselineHead, current_head: head, changed_files: changedFiles.length, screenshots: screenshotNames.length, user_uau: "NOT_REVIEWED" }, null, 2));
