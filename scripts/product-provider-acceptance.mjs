export function classifyFailedProviderSmoke(smoke) {
  const summary = smoke?.failure_summary;
  const providerUnavailable =
    typeof smoke?.error === "string" &&
    smoke.error.includes("CAPABILITY_UNAVAILABLE") &&
    smoke.error.includes("PROVIDER_ACQUISITION_UNAVAILABLE") &&
    summary?.diagnostic_state === "CAPTURED" &&
    summary?.failed_task_count === 1 &&
    summary?.successful_canonical_chain_count === 0 &&
    summary?.operation_id === "ProductEntryService.v1.submitResearch" &&
    summary?.task_state === "FAILED" &&
    summary?.result_present === false &&
    JSON.stringify(summary?.output_roles) === JSON.stringify(["EXECUTION_CONTEXT"]) &&
    summary?.execution_context_ref_valid === true &&
    summary?.attempt_state === "FAILED" &&
    summary?.error_category === "INVALID_ARGUMENT" &&
    summary?.reason_code === "PROVIDER_ACQUISITION_UNAVAILABLE" &&
    summary?.renderer_surface === "ERROR" &&
    summary?.renderer_provider_unavailable === true;
  return providerUnavailable ? "BLOCKED_PROVIDER_ACCEPTANCE" : "FAIL_PROVIDER_ACCEPTANCE";
}

export function failedProviderReport(run, smoke, phase) {
  return Object.freeze({
    schema_version: "v3.product-closure-packaged-e2e/1.0.0",
    result: classifyFailedProviderSmoke(smoke),
    phase,
    error_code: smoke?.failure_summary?.reason_code ?? "UNCLASSIFIED_PRODUCT_FAILURE",
    failure_summary: smoke?.failure_summary ?? null,
    successful_canonical_chain_count: smoke?.failure_summary?.successful_canonical_chain_count ?? null,
    product_exit_code: run.code,
    product_signal: run.signal,
  });
}
