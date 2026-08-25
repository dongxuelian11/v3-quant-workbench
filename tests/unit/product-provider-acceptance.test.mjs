import assert from "node:assert/strict";
import test from "node:test";

import { classifyFailedProviderSmoke, failedProviderReport } from "../../scripts/product-provider-acceptance.mjs";

function blockedSmoke() {
  return {
    error: "CAPABILITY_UNAVAILABLE · PROVIDER_ACQUISITION_UNAVAILABLE",
    failure_summary: {
      diagnostic_state: "CAPTURED",
      failed_task_count: 1,
      successful_canonical_chain_count: 0,
      operation_id: "ProductEntryService.v1.submitResearch",
      task_state: "FAILED",
      result_present: false,
      output_roles: ["EXECUTION_CONTEXT"],
      execution_context_ref_valid: true,
      attempt_state: "FAILED",
      error_category: "INVALID_ARGUMENT",
      reason_code: "PROVIDER_ACQUISITION_UNAVAILABLE",
      renderer_surface: "ERROR",
      renderer_provider_unavailable: true,
    },
  };
}

test("exact canonical provider block remains literal BLOCKED evidence", () => {
  const smoke = blockedSmoke();
  assert.equal(classifyFailedProviderSmoke(smoke), "BLOCKED_PROVIDER_ACCEPTANCE");
  assert.deepEqual(
    failedProviderReport({ code: 1, signal: null }, smoke, "create-submit"),
    {
      schema_version: "v3.product-closure-packaged-e2e/1.0.0",
      result: "BLOCKED_PROVIDER_ACCEPTANCE",
      phase: "create-submit",
      error_code: "PROVIDER_ACQUISITION_UNAVAILABLE",
      failure_summary: smoke.failure_summary,
      successful_canonical_chain_count: 0,
      product_exit_code: 1,
      product_signal: null,
    },
  );
});

test("provider wording alone cannot turn an invalid failure into BLOCKED", () => {
  assert.equal(
    classifyFailedProviderSmoke({ error: "CAPABILITY_UNAVAILABLE PROVIDER_ACQUISITION_UNAVAILABLE" }),
    "FAIL_PROVIDER_ACCEPTANCE",
  );
});

for (const [field, invalid] of [
  ["successful_canonical_chain_count", 1],
  ["result_present", true],
  ["reason_code", "INTERNAL_ERROR"],
  ["renderer_provider_unavailable", false],
]) {
  test(`invalid ${field} cannot be accepted as a provider block`, () => {
    const smoke = blockedSmoke();
    smoke.failure_summary[field] = invalid;
    assert.equal(classifyFailedProviderSmoke(smoke), "FAIL_PROVIDER_ACCEPTANCE");
  });
}
