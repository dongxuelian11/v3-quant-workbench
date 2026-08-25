import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");
const ci = await readFile(resolve(root, ".github/workflows/ci.yml"), "utf8");
const packaging = await readFile(resolve(root, ".github/workflows/packaging-clean-machine-evidence.yml"), "utf8");
const cleanMachineDriver = await readFile(resolve(root, "scripts/v1_1-release-clean-machine.ps1"), "utf8");
const packagedJourneyDriver = await readFile(resolve(root, "scripts/v1_1_product_release_packaged_e2e.mjs"), "utf8");
const liveProviderDriver = await readFile(resolve(root, "scripts/product-closure-packaged-e2e.mjs"), "utf8");

function jobSource(workflow, jobId, nextJobId) {
  const startToken = `  ${jobId}:\n`;
  const start = workflow.indexOf(startToken);
  assert.notEqual(start, -1, `missing workflow job ${jobId}`);
  if (nextJobId === undefined) return workflow.slice(start);
  const end = workflow.indexOf(`  ${nextJobId}:\n`, start + startToken.length);
  assert.notEqual(end, -1, `missing workflow job ${nextJobId}`);
  return workflow.slice(start, end);
}

function assertExactActionPins(workflow, label) {
  const refs = [...workflow.matchAll(/^\s*-?\s*uses:\s*([^\s#]+)(?:\s+#\s*(.+))?$/gm)];
  assert.ok(refs.length > 0, `${label} has no action references`);
  for (const ref of refs) {
    assert.match(ref[1], /^[^@\s]+@[0-9a-f]{40}$/, `${label} action is not pinned to an exact commit: ${ref[1]}`);
    assert.match(ref[2] ?? "", /^v\d+\.\d+\.\d+$/, `${label} action pin has no audited release annotation: ${ref[0]}`);
  }
}

test("V1.1 unified product gate exposes diagnostic Jobs A-F", () => {
  const jobA = jobSource(ci, "authority-contract-quality", "backend-runtime");
  const jobB = jobSource(ci, "backend-runtime", "windows-product-integration");
  const jobC = jobSource(ci, "windows-product-integration");
  const jobD = jobSource(packaging, "windows-package", "windows-clean-machine");
  const jobE = jobSource(packaging, "windows-clean-machine", "live-provider-acceptance");
  const jobF = jobSource(packaging, "live-provider-acceptance");

  assert.match(jobA, /runs-on:\s*ubuntu-latest/);
  assert.match(jobA, /fetch-depth:\s*0/);
  for (const command of ["validate:authority", "typecheck", "lint", "test:unit", "test:contracts"]) {
    assert.match(jobA, new RegExp(`npm run ${command.replaceAll(":", "\\:")}`));
  }
  assert.match(jobA, /python -m compileall -q apps\/backend\/src apps\/backend\/tests/);

  assert.match(jobB, /runs-on:\s*ubuntu-latest/);
  for (const command of ["test:backend", "smoke:product-runtime", "smoke:product-data", "smoke:product-factor", "smoke:product-backtest", "smoke:product-result"]) {
    assert.match(jobB, new RegExp(`npm run ${command.replaceAll(":", "\\:")}`));
  }

  assert.match(jobC, /runs-on:\s*windows-latest/);
  for (const command of ["build", "test:runtime", "verify:product-bundle-truth", "smoke:frontend", "smoke:electron:runtime", "smoke:product-data", "smoke:product-factor", "smoke:product-backtest", "smoke:product-result"]) {
    assert.match(jobC, new RegExp(`npm\\.cmd run ${command.replaceAll(":", "\\:")}`));
  }

  assert.match(jobD, /V3_SOURCE_GIT_SHA/);
  assert.match(jobD, /V3_V1_1_PRODUCT_RELEASE_PACKAGE\.zip/);
  assert.match(jobD, /v1_1-release-clean-machine\.ps1/);
  assert.match(jobD, /v1_1_product_release_packaged_e2e\.mjs/);

  assert.doesNotMatch(jobE, /actions\/checkout|npm(?:\.cmd)?\s+(?:ci|install)|pip\s+install/i);
  assert.match(jobE, /timeout-minutes:\s*45/);
  assert.match(jobE, /repository_source_tree_present\s*=\s*\$false/);
  assert.match(jobE, /v1_1-release-clean-machine\.ps1/);

  assert.match(jobF, /product-closure-packaged-e2e\.mjs/);
  assert.match(jobF, /BLOCKED_PROVIDER_ACCEPTANCE/);
  assert.doesNotMatch(jobF, /DETERMINISTIC_SUCCESS|DETERMINISTIC_UNAVAILABLE|fixture|fallback/i);
});

test("all V1.1 product-gate actions are exact audited commit pins", () => {
  assertExactActionPins(ci, "ci.yml");
  assertExactActionPins(packaging, "packaging-clean-machine-evidence.yml");
});

test("V1.1 Jobs D-F are triggered by every bounded release input", () => {
  for (const path of [
    ".github/workflows/ci.yml",
    "scripts/contract-fixture-test.mjs",
    "scripts/public-frontend-smoke.mjs",
    "scripts/v1_1-release-clean-machine.ps1",
    "scripts/v1_1_product_release_packaged_e2e.mjs",
    "scripts/product-closure-packaged-e2e.mjs",
    "tests/unit/v1-1-ci-workflow.test.mjs",
  ]) {
    assert.match(packaging, new RegExp(path.replaceAll(".", "\\.").replaceAll("/", "\\/")), `workflow path trigger omits ${path}`);
  }
  assert.match(packaging, /codex\/v1-1-usable-research-product-01/);
});

test("V1.1 clean-machine drivers need only transferred product artifacts", () => {
  assert.doesNotMatch(packagedJourneyDriver, /readFile\([^\n]*package\.json/);
  assert.match(packagedJourneyDriver, /V3_PRODUCT_VERSION/);
  assert.match(packagedJourneyDriver, /runtimeManifest\.product\?\.version/);
  assert.match(cleanMachineDriver, /ELECTRON_RUN_AS_NODE\s*=\s*"1"/);
  assert.match(cleanMachineDriver, /bundled_electron_node_used_for_driver\s*=\s*\$true/);
  assert.match(cleanMachineDriver, /no_npm_install_in_verify_job\s*=\s*\$true/);
  assert.match(cleanMachineDriver, /no_pip_install_in_verify_job\s*=\s*\$true/);
  assert.match(cleanMachineDriver, /user_data_outside_install_root\s*=\s*\$true/);
  assert.doesNotMatch(cleanMachineDriver, /npm(?:\.cmd)?\s+(?:ci|install)|pip\s+install/i);
});

test("Job F packaged child cannot inherit driver or deterministic-provider mode", () => {
  for (const variable of [
    "ELECTRON_RUN_AS_NODE",
    "V3_PRODUCT_CLOSURE_PROVIDER_MODE",
    "V3_PRODUCT_V1_1_SMOKE_LOCAL_DATA_SOURCE",
  ]) {
    assert.match(
      liveProviderDriver,
      new RegExp(`delete runtimeEnvBase\\[\\"${variable}\\"\\]|\\"${variable}\\"`),
      `live provider driver does not scrub ${variable}`,
    );
  }
});

test("Job F blocks only on the exact provider-unavailable code", () => {
  const jobF = jobSource(packaging, "live-provider-acceptance");
  assert.match(jobF, /\$logs -match "PROVIDER_ACQUISITION_UNAVAILABLE"/);
  assert.doesNotMatch(jobF, /\$logs\s+-match\s+"[^"]*(?:upstream|timed out|timeout)/i);
  assert.match(jobF, /result = "FAIL_PROVIDER_ACCEPTANCE_TIMEOUT"/);
});
