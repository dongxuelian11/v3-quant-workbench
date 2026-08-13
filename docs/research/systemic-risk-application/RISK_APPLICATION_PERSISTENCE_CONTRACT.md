# Canonical Risk Application Persistence Contract

Task: `V3-SYSTEMIC-RISK-APPLICATION-CANONICAL-PERSISTENCE-PUBLICATION-01`

This document describes the bounded foundation implemented on the task branch.
It is a candidate contract, not an A3, Backtest, product, or production
availability claim.

## Authority chain

The only formal Risk application entry point is identity-only:

```text
CanonicalRiskApplicationRequest
  source_target_weight_vector_id
  risk_policy_set_version_id
  runtime_identity
  context_identity
        ↓
SQLite canonical TargetWeight / Risk policy owners
        ↓
P1 owner-derived binding + verified Artifact bytes
        ↓
strict canonical reconstruction
        ↓
existing apply_risk()
        ↓
receipt + adjusted vector exact bytes
        ↓
existing Artifact Store + SQLite PUBLISH UoW
        ↓
append-only owner rows and active Artifact references
```

`CanonicalRiskApplicationRequest` has no numeric rows, state values, receipt,
adjusted vector, `RiskRuntimeResult`, or caller-selected truth field. The service
resolves the target and policy, checks the exact persisted runtime triple
(`code_version`, `runtime_profile_id`, `environment_fingerprint`) and context, rejects
policy sets requiring unavailable canonical `RiskStateInput` owners, and calls
the existing deterministic engine. The persistence adapter independently
re-resolves and recomputes before it writes. Expected output IDs are only a
cross-check; they do not supply values or authority.

Direct `apply_risk()` remains public and pure. Its return value creates no
Artifact, owner row, reachability root, or downstream authority.

## Canonical owners and storage

- Portfolio remains the semantic owner of `TargetWeightVector`. The additive
  `target_weight_vector_publication` row is only its exact downstream
  publication seam; Portfolio construction is unchanged.
- The existing SQLite Risk repository boundary owns the exact
  `RiskPolicySetVersion`, `RiskApplicationReceipt`, and
  `RiskAdjustedWeightVector` records. No second registry exists.
- Variable-length target/receipt/vector bytes live only in the existing
  content-addressed Artifact Store. SQLite rows contain immutable identity,
  Artifact binding, source lineage, runtime/context, timing, and truth metadata.
- The bounded Risk policy wire is canonical control metadata stored in the
  existing Risk repository table and reconstructed through current Risk V0
  factories.
- P1 remains unchanged and read-only. The repository derives each
  `CanonicalPayloadBinding` from persisted owner state and P1 re-hashes the
  actual bytes before reconstruction.

Same ID plus the exact same immutable state is idempotent. Same ID plus
conflicting state, missing upstream owners, inactive/unpublished Artifacts,
hash/size changes, context changes, or reconstruction mismatches fail closed.

## Restart-safe downstream resolution

After closing every repository and database connection, downstream can resolve:

```text
rawv_sha256_* ID
→ risk_adjusted_weight_vector_publication
→ source twv_sha256_* + receipt rar_sha256_*
→ exact Artifact ID / SHA-256 / byte size / active reference
→ P1 verified bytes
→ reconstructed TargetWeightVector
→ reconstructed RiskApplicationReceipt
→ reconstructed RiskAdjustedWeightVector
```

The returned downstream view includes the adjusted vector, owner-derived P1
binding, source target ID, and receipt ID. No in-memory owner is required. This
is metadata readiness for a future A3 binding; it does not modify or resume A3.

## Truth and state boundary

Persisted truth is the existing W0/R meet of the resolved target, resolved policy
set, supporting Risk evidence, and runtime semantics. Current unresolved W0/R
inputs cap the chain at `NOT_FORMAL / PRE_ALPHA`. Publication integrity cannot
promote that state.

Risk V0 policy sets declaring `RiskStateInput` requirements are rejected by the
formal service because current main has no canonical generic Risk-state payload
owner for this foundation. Caller state objects and raw values are never
accepted as substitutes.

## Atomicity and crash consistency

Filesystem and SQLite are not represented as one atomic resource. The existing
PUBLISH UoW sequence is reused:

```text
stage and hash exact bytes
→ safe-format verification
→ same-volume content-addressed publish
→ BEGIN IMMEDIATE
→ Artifact descriptors/references + provenance + owner rows
→ COMMIT
```

If SQLite begin/insert/commit fails, compensation removes only newly published,
unreferenced content and never deletes deduplicated existing content. A process
crash after the filesystem link but before SQLite commit may leave unreferenced
content. It cannot leave an owner row claiming missing bytes; the residual bytes
remain outside reachability and are recoverable by the existing GC model.
Retry is deterministic and idempotent. Foreign keys and insert triggers prevent
a receipt without its target/policy owner, an adjusted vector without its exact
receipt/source lineage, or any owner row whose Artifact is not exact and
`PUBLISHED`.

## Vertical authority closure

1. Portfolio owns target truth; exact target bytes and owner metadata are durable.
2. Target is persisted and reachable by exact ID.
3. Formal Risk requests cannot carry target objects or rows and must resolve the owner.
4. The existing Risk repository boundary owns exact policy-set truth.
5. The formal service re-resolves the policy owner.
6. Existing `apply_risk()` produces the actual adjusted numbers.
7. Receipt and adjusted bytes are content-addressed in the existing store.
8. Append-only SQLite rows and active references survive restart.
9. No formal API accepts a caller `RiskRuntimeResult`, receipt, or vector.
10. Exact adjusted vectors resolve after restart through P1-verified bytes.
11. Existing domain factories derive the truth ceiling from resolved upstreams.
12. Owner namespace/version/role, Artifact ID/SHA/size, context and lineage are
    present for a future A3 P1 binding.

## Explicit non-claims

- A3 and PR #35 remain unchanged and on hold.
- Backtest integration is not established.
- Required RiskState input publication remains `NOT_AVAILABLE` in this scope.
- Product connection and production availability are not established.
- No merge is authorized by this task.
