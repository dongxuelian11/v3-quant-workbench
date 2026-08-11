# Deterministic Risk Runtime V0 contract

## Authority and boundary

Track I consumes the merged W0 `TargetWeightVector` object and publishes through the merged W0 `RiskAdjustedWeightVector.create(...)` seam. It does not redefine or modify W0 types and does not depend on unmerged H/J branches.

```text
canonical TargetWeightVector object
  -> exact ordered RiskPolicySetVersion
  -> ordered RiskStageReport evidence
  -> RiskDecisionReport
  -> W0 RiskApplicationReceipt
  -> new W0 RiskAdjustedWeightVector identity
```

An arbitrary target ID is not an input. `apply_risk` requires the actual W0 object and calls `assert_canonical()` before any policy stage. The frozen source object is never mutated.

## Policy set and supported V0 algebra

`RiskPolicySetVersion` is frozen, content-addressed and order-sensitive. Every policy binds its type/version, mode, exact parameters, required state declarations, reject behavior, residual/cash rule, risk-model requirement, code/runtime/backend, PIT requirement and truth ceiling. The enum is closed; generic callbacks are forbidden.

| Policy | Mode | Behavior | Cash rule | Failure |
|---|---|---|---|---|
| `PASS_THROUGH` | `PASS_THROUGH` | No weight transform; `NO_ADDITIONAL_RISK_TRANSFORM` evidence | `PRESERVE` | typed reject for contract/state failure |
| `MAX_SINGLE_NAME` | `CLIP` | Clip each exact instrument weight to `max_weight` | `ADD_REDUCTION_TO_CASH`; no renormalization | typed reject for contract/state failure |
| `GROSS_NET_EXPOSURE_VALIDATE` | `VALIDATE` | Validate exact gross/net limits over the W0 exposure profile | `PRESERVE` | `RiskPolicyRejected` with exact reason |

A non-transforming policy set must contain explicit `PASS_THROUGH`. A transforming set produces `ADJUSTED`; a successful no-transform set produces `PASS_THROUGH`. Both produce a new RiskAdjusted identity because the W0 receipt binds the exact policy-set and decision-report references.

## State, PIT and failure semantics

Policies may declare exact `RISK_STATE` or `RISK_MODEL` inputs. Supplied inputs must be declared, unique and kind-matched. `AS_OF_NOT_AFTER_TARGET_DECISION` is checked against target decision time. Missing, wrong-kind or future state produces a deterministic rejected stage and raises `RiskPolicyRejected`; no RiskAdjusted vector is returned.

Forbidden fallbacks remain forbidden:

- error to cash;
- error to prior weights;
- unknown state to pass-through;
- external solver failure/candidate to unchanged canonical output.

An `external_solver_candidate` is rejected with `ExternalSolverAuthorityError`. A future worker may propose evidence, but only canonical Track I code may validate it and call the W0 publisher.

## Evidence and identity

Every stage records stage index, exact policy identity/type, input/output vector hashes and rows, before/after gross/net/cash/max-single values, limits, reason, typed status, residual/cash handling, required state refs and external-solver evidence.

The W0 receipt binds every rich stage report by content hash. `RiskDecisionReport` binds source target ID/content, policy set ID/content, ordered reports, final rows/cash/vector hash, state inputs, runtime and truth. Policy order, parameter, state or target changes therefore change the published derivative identity.

## RiskModel decision and truth

`RiskModelVersion` is **NOT_IMPLEMENTED / optional** in V0. Current main does not provide a sufficiently admitted PIT-safe return panel, canonical risk taxonomy, estimation-window contract, covariance/specific-risk evidence and validation chain. Fabricating a factor model would exceed current truth.

Rule-based policies are the complete V0 scope. Policy definitions/sets are capped at `PRE_ALPHA`; the report meets source, policy-set and required-state truth; the W0 receipt/vector apply their existing ceilings. Validation or solver success never promotes upstream truth.

## Acceptance mapping

The `round3_track_i_risk_runtime` suite covers actual canonical input, source immutability, explicit pass-through/new identity, policy ordering, deterministic max-single-name clipping, residual cash equation, gross/net validation, missing/PIT-invalid state, no fallback, identity sensitivity, PRE_ALPHA preservation, worker authority rejection and complete deterministic evidence. Full repository regression, compile and public validation remain separate delivery gates.
