# Risk Application Canonical Owner Re-anchor Audit

Task: `V3-SYSTEMIC-PR36-RISK-APPLICATION-OWNER-REANCHOR-20260814-01-V1.1`

Audited authority: CURRENT main `ee3da288d06053928e0075797d834c50038a85d0`
and the existing PR #36 lineage. This is a candidate branch result, not a merge,
product connection, or production-availability claim.

## Current upstream authority

CURRENT main owns canonical upstream publication through:

- `CanonicalPortfolioOwnerService`, which constructs a `TargetWeightVector`
  through the existing deterministic Portfolio engine and publishes it without
  accepting a caller-built vector;
- `CanonicalRiskPolicyAuthoringService`, which authors a policy set from closed
  definition inputs and requires `RiskModelRequirement.NOT_REQUIRED`;
- `SQLitePortfolioRiskPolicyOwner`, which owns the two upstream publication
  tables introduced by `0003_portfolio_riskpolicy_owner.sql` and implements the
  shared `PayloadResolutionRequest` binding seam;
- `CanonicalPayloadResolver` plus `FileSystemArtifactStore`, which independently
  read and verify the actual Artifact bytes, SHA-256, byte size, identity,
  Project/ProjectContext-derived context, and active reference.

The accepted upstream constants are reused directly:

```text
TargetWeight: v3.portfolio.target-weight-vector / TARGET_WEIGHT_VECTOR
RiskPolicy:   v3.risk.policy-set-version / RISK_POLICY_SET
```

For both owners, the canonical ID suffix is the exact `content_sha256` supplied
as P1 `owner_version`. Prefix syntax alone is never treated as authority.

## Obsolete PR #36 seams removed

The Risk Application repository no longer exposes either of these supported
canonical APIs:

```text
publish_target_weight(prebuilt TargetWeightVector)
publish_risk_policy_set(prebuilt RiskPolicySetVersion)
```

It no longer creates upstream owner rows, stores inline `policy_json` as
canonical policy truth, or derives a local TargetWeight owner from a caller
object. Missing upstream IDs fail closed.

## Migration ownership

`0003_portfolio_riskpolicy_owner.sql` remains byte-identical to CURRENT main and
creates only:

- `target_weight_vector_publication`
- `risk_policy_set_publication`

PR #36 owns `0004_risk_application_publication.sql`, which creates only:

- `risk_application_receipt_publication`
- `risk_adjusted_weight_vector_publication`

The downstream tables reference the exact upstream owners and bind Project,
ProjectContext revision, context identity, content hashes, runtime identity,
Artifact identity/SHA/size, schema/serialization identity, truth/admission, and
receipt-to-adjusted lineage. They never bootstrap an absent upstream row.

## Preserved Risk Application authority

`CanonicalRiskApplicationRequest` carries only Project/ProjectContext identity,
canonical upstream IDs, runtime identity, and context identity. The formal
service and persistence adapter both re-resolve verified upstream actual bytes,
strictly decode them, and deterministically call the existing `apply_risk()`.
Only the recomputed `RiskApplicationReceipt` and
`RiskAdjustedWeightVector` are published.

The downstream exact-ID read side remains restart-safe and P1-verified.
Required RiskState inputs still fail closed because no canonical RiskStateInput
owner is accepted. Truth remains at the meet of the upstream owners, currently
`NOT_FORMAL / PRE_ALPHA`; persistence does not promote it.

## Explicit boundary

A3/PR #35, Data Truth Market, Model/B1, Experiment/Reward/B2, Strategy to
Portfolio handoff, Result Analytics, B3/B4, Desktop, product connection, and
production availability are unchanged and `NOT_RUN` in this task.
