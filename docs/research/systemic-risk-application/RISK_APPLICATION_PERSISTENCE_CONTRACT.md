# Canonical Risk Application Persistence Contract

Task: `V3-SYSTEMIC-PR36-RISK-APPLICATION-OWNER-REANCHOR-20260814-01-V1.1`

This contract describes the corrected PR #36 candidate. It does not claim that
the PR is merged, exact-main verified, product-connected, or production-ready.

## Formal flow

```text
CanonicalRiskApplicationRequest
  project_id
  project_context_revision_id
  context_identity
  source_target_weight_vector_id
  risk_policy_set_version_id
  runtime_identity
        -> SQLitePortfolioRiskPolicyOwner exact persisted owners
        -> PayloadResolutionRequest using ID-committed content hash
        -> CanonicalPayloadResolver + FileSystemArtifactStore actual bytes
        -> strict TargetWeightVector / RiskPolicySetVersion decode
        -> exact project, context, runtime, identity and truth validation
        -> existing deterministic apply_risk()
        -> recomputed receipt + adjusted vector
        -> existing Artifact Store + SQLite PUBLISH UoW
        -> append-only 0004 downstream owner rows
```

The request has no weights, policy object, state values, result object, receipt,
adjusted vector, Artifact descriptor, owner record, or caller-selected truth.

## Upstream ownership

TargetWeight and RiskPolicy publication remain exclusively owned by CURRENT
main's `CanonicalPortfolioOwnerService`,
`CanonicalRiskPolicyAuthoringService`, and
`SQLitePortfolioRiskPolicyOwner`. The Risk Application repository only consumes
their P1 bindings and actual bytes. Its public API cannot mint either upstream
owner from caller-built objects.

`0003_portfolio_riskpolicy_owner.sql` is preserved without semantic or byte
change. `0004_risk_application_publication.sql` depends on its tables and owns
only the receipt and adjusted-vector publications.

## Downstream publication and read side

Each 0004 owner row binds exact content identity, Project/ProjectContext,
context identity, upstream IDs and content hashes, runtime identity, Artifact
ID/SHA/size, active reference, schema/serialization identity, truth/admission,
publication time, and receipt-to-adjusted lineage.

Downstream resolution starts from the receipt or adjusted-vector content ID,
derives the committed content hash, resolves the persisted owner binding, reads
and independently verifies actual bytes through P1, strictly decodes, and checks
all upstream and cross-output relationships. Restart/reopen does not rely on
in-memory owner objects.

## Fail-closed behavior

The formal path rejects missing or valid-looking unpersisted IDs, wrong Project
or ProjectContext, wrong context identity, runtime mismatch, released Artifact
references, missing or altered bytes, SHA/size mismatch, decoded identity
mismatch, upstream lineage mismatch, and any policy whose RiskModel requirement
is not `NOT_REQUIRED`.

Policies with non-empty `required_state_inputs` fail with unavailable canonical
RiskState authority; no zero/false/default state is fabricated.

## Determinism, idempotency, and crash boundary

The service and adapter independently recompute with `apply_risk()` before
persistence. Exact replay converges to the same identities. Conflicting content
or context fails closed. Existing PUBLISH callbacks stage and hash bytes before
the SQLite transaction and remove only newly published, unreferenced bytes on a
bounded failure. No distributed atomicity beyond those guarantees is claimed.

## Truth and non-claims

Downstream truth is the meet of the resolved upstream owners. The accepted
TargetWeight owner remains `PRE_ALPHA / UNRESOLVED_CALLER_ASSERTED`, so Risk
Application remains `NOT_FORMAL / PRE_ALPHA`.

A3/PR #35, Data Truth Market, Model/B1, Experiment/Reward/B2, Strategy to
Portfolio, Result Analytics, B3/B4, product connection, production availability,
and PR #36 merge are outside this contract and `NOT_RUN`.
