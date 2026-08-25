import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import productClosureSmoke from "../../dist/apps/desktop/src/main/productClosureSmoke.js";

const {
  PRODUCT_VISUAL_MATRIX_CASES,
  parseProductClosureSmokePhase,
  productClosureSmokeRendererStoreInstance,
  productClosureSmokeSourceBoundary,
  productVisualMatrixEvidenceClass,
} = productClosureSmoke;

test("V1.1 packaged Golden Journey phases are closed and local-source truthful", () => {
  assert.equal(typeof parseProductClosureSmokePhase, "function");
  assert.equal(typeof productClosureSmokeRendererStoreInstance, "function");
  assert.equal(typeof productClosureSmokeSourceBoundary, "function");
  for (const [phase, processTruth] of [
    ["v1-1-journey-a-create", "FIRST_PROCESS"],
    ["v1-1-journey-a-reopen", "NEW_PROCESS"],
    ["v1-1-journey-b-create", "FIRST_PROCESS"],
    ["v1-1-journey-b-reopen", "NEW_PROCESS"],
    ["v1-1-journey-a-visual", "NEW_PROCESS"],
  ]) {
    assert.equal(parseProductClosureSmokePhase(phase), phase);
    assert.equal(productClosureSmokeSourceBoundary(phase), "LOCAL_USER_SUPPLIED");
    assert.equal(productClosureSmokeRendererStoreInstance(phase), processTruth);
  }

  assert.equal(
    productClosureSmokeSourceBoundary("provider-unavailable"),
    "TEST_EXTERNAL_PROVIDER_BOUNDARY_UNAVAILABLE",
  );
  assert.throws(
    () => parseProductClosureSmokePhase("v1-1-journey-a-success-with-fixture"),
    /unknown product closure smoke phase/,
  );
});

test("V1.1 Product visual owner closes the exact 4 by 3 matrix without claiming physical Windows scaling", () => {
  assert.equal(typeof productVisualMatrixEvidenceClass, "function");
  assert.equal(productVisualMatrixEvidenceClass(), "EMULATED_ELECTRON_ZOOM_NOT_PHYSICAL_WINDOWS_SCALING");
  assert.deepEqual(
    PRODUCT_VISUAL_MATRIX_CASES.map(({ width, height, scalePercent }) => `${width}x${height}@${scalePercent}`),
    [
      "1366x768@100", "1366x768@125", "1366x768@150",
      "1440x900@100", "1440x900@125", "1440x900@150",
      "1920x1080@100", "1920x1080@125", "1920x1080@150",
      "2560x1440@100", "2560x1440@125", "2560x1440@150",
    ],
  );
});

test("V1.1 Product typography keeps body at 13px and important tables at 12px", async () => {
  const css = await readFile(new URL("../../apps/desktop/src/renderer/styles.css", import.meta.url), "utf8");
  assert.match(css, /\.product-app-shell\s*\{[^}]*--product-body-font-size:\s*13px/s);
  assert.match(css, /\.product-app-shell\s+:where\(main, button, input, select, textarea, summary\)\s*\{[^}]*font-size:\s*var\(--product-body-font-size\)/s);
  assert.match(css, /\.product-app-shell\s+:where\(table, th, td, \.factor-row, \.analysis-list > div\)\s*\{[^}]*font-size:\s*12px/s);
  assert.match(css, /\.product-app-shell\s+:where\(button, input, select, textarea, summary, \[tabindex\]\):focus\s*\{[^}]*outline:\s*3px solid[^}]*!important/s);
});
