# Canonical Risk Application Owner Gap Audit

Task: `V3-SYSTEMIC-RISK-APPLICATION-CANONICAL-PERSISTENCE-PUBLICATION-01`

Audited baseline: GitHub CURRENT `main` and branch HEAD
`9dda07c254e1e3108d9ce3fec7624b4c7d0710f1`.

This audit is the mandatory production-code edit gate. It records current-main
owners and gaps; it does not promote any capability or make A3 available.

## Authority and tooling boundary

- Repo P0 Authority `1.0.1`, the merged P1 foundation, this complete task,
  State Ledger, and Git/GitHub CURRENT are required authority.
- External WorkflowGuard tooling and `CURRENT_AUTHORITY.json` are
  `OPTIONAL_TOOLING / NON_AUTHORITATIVE` for this task. Their historical missing
  registry result is preserved in the Ledger and is not a project blocker.
- P0, P1, Backtest/A3, A1/A2/A4/Q/S/T, agents, desktop, package metadata, and
  lockfiles are outside the write-set.

## Exact current-main findings

| Object / seam | Semantic owner | Deterministic identity | Current persistence | Current Artifact publication | Canonical reachability | Caller constructibility | Truth ceiling | Gap | Reuse decision |
|---|---|---|---|---|---|---|---|---|---|
| `TargetWeightVector` | Portfolio construction; `publisher_service=v3.portfolio-service/1.0.0` | `twv_sha256_` over canonical W0 payload; `assert_canonical()` rebuilds | No row keyed by exact `TargetWeightVector` ID. `portfolio_version` can point at a generic targets artifact, but does not bind the W0 object/lineage by exact ID. | No canonical W0 vector publication path | In-memory only; not restart-safe | Public dataclass/factory | Meet of unresolved PortfolioIntent source, construction spec, diagnostics/provenance; currently capped at `PRE_ALPHA` | Exact-ID owner row, artifact binding, verified reconstruction | `DIRECT_REUSE` object; add minimal Portfolio-owned publication seam through existing Artifact/SQLite infrastructure |
| `RiskPolicySetVersion` | Risk semantic owner | `rpsv_sha256_` over ordered canonical policies | No exact policy-set owner row. Existing `risk` repository owns `risk_model_spec`/`risk_model_version`; existing Catalog also has `constraint_set_version`, but neither is the W0/R policy-set object and neither may be relabelled as one. | None required by current Risk V0; policy wire is bounded control metadata | In-memory/Agent evidence only; no restart-safe owner | Public dataclass/factory | Meet of ordered policy truth, at most `PRE_ALPHA` | Exact canonical policy-set owner record and resolver | `DIRECT_REUSE` model; `BOUNDED_EXTENSION` of the existing Risk repository registry with one append-only policy-set table. This is not a duplicate policy registry. |
| `RiskDecisionReport` | Risk runtime evidence owner | `rdr_sha256_`; canonical report rebuild/assertion | None | None | In-memory only | Public factory | Meet of source target, policy set, and required state refs | It remains computation evidence, not the persisted Risk application output owner | `DIRECT_REUSE`; no new report owner table in this task |
| `RiskApplicationReceipt` | Risk semantic owner; `publisher_service=v3.risk-service/1.0.0` | `rar_sha256_` over target/policy/stages/supporting refs/runtime/truth | None | None | In-memory only | Public dataclass/factory | Meet of target, policy, report/state/provenance refs | Exact artifact + append-only owner row + lineage resolver | `DIRECT_REUSE` object; add canonical publication metadata |
| `RiskAdjustedWeightVector` | Risk semantic owner; `publisher_service=v3.risk-service/1.0.0` | `rawv_sha256_` over exact target/receipt/runtime/weights/truth | None | None | In-memory only | Public dataclass/factory | Meet of source target and application receipt | Exact artifact + append-only owner row + restart-safe downstream resolver | `DIRECT_REUSE` object; add canonical publication metadata |
| `apply_risk()` / `RiskRuntimeResult` | Risk deterministic engine | Closed W0/R inputs and canonical returned objects | Deliberately none | Deliberately none | Direct call cannot be reached as persisted authority | Public callable/result dataclass | Existing fail-closed semantics; policy/runtime/PIT checks | Must remain pure and non-minting | `DIRECT_REUSE`; formal service calls it after owner resolution only |
| `portfolio_version` | Existing Portfolio Catalog owner | `pfv_` Catalog identity plus content/artifact fields | SQLite `0001` | Can reference `targets_artifact_id` | Persistent but not an exact W0 vector owner | Generic repository accepts bounded rows | Catalog state does not upgrade W0 truth | Cannot substitute for exact `twv_` reachability; retain as upstream lineage seam | `DIRECT_REUSE` lineage; no redefinition or Portfolio runtime rewrite |
| Existing Risk Catalog | Risk repository registry | Existing `rms_`/`rmv_` identities | SQLite `0001` | Risk-model artifacts only | Restart-safe for risk models, not Risk V0 policy/application outputs | Generic repository is infrastructure, not formal mint authority | Existing Catalog state | Add exact policy/application tables and a specialized repository | `BOUNDED_EXTENSION`; no second database or generic shadow registry |
| Artifact Store | Artifact byte owner | `art_sha256_` from exact bytes | Filesystem plus SQLite `artifact`/`artifact_reference` | Same-volume staged publication, SHA/size verification, PUBLISH UoW callbacks | Active references are reachability roots | Bytes/descriptors alone do not establish Risk meaning | Artifact integrity cannot promote semantic truth | Baseline safe-format allow-list lacks the three Risk/weight canonical JSON roles; artifact owner prefixes are not recognized by the SQLite publication port | `DIRECT_REUSE` with bounded allow-list/owner-type extension |
| Provenance registry | Provenance evidence owner | `prv_` / `pre_` append-only rows | SQLite `0001` | Artifact references may bind provenance | Restart-safe | Generic rows do not mint domain truth | Cannot upgrade upstream truth | Risk owner publications need exact subject entities/edges | `DIRECT_REUSE` |
| P1 payload authority | Shared owner-derived payload verification foundation | Request/binding/receipt content identities | P1 owner resolver supplied by domain adapter | Reads exact Artifact Store bytes | Verifies owner binding, context, hash, ID and size | Caller-created binding is explicitly non-authoritative | Verification does not promote owner truth | Risk repository must expose owner-derived binding metadata | `DIRECT_REUSE` on read side; P1 source remains unchanged |

## Portfolio / TargetWeight source decision

Current main has the Portfolio semantic owner, canonical construction engine,
`TargetWeightVector.publisher_service`, and a durable Portfolio Catalog seam, but
no exact `twv_` publication. This task may add the minimum publication record
needed by Risk. The new record must preserve the exact PortfolioIntent,
construction-spec, Universe, timing, runtime, truth and canonical artifact
lineage already present in `TargetWeightVector.to_wire()`.

Formal Risk publication accepts only `source_target_weight_vector_id`; it never
accepts target rows or a `TargetWeightVector` object. A public W0 object that has
not crossed the trusted upstream publication seam remains non-authoritative.

## Risk policy owner decision

Current main does not persist `RiskPolicySetVersion`, but it does have one
canonical Risk repository boundary (`SQLiteRepositoryRegistry.risk`) and an
additive migration framework. The safe decision is to extend that existing
boundary with an append-only exact policy-set owner table and resolver. Using
`risk_model_version` or `constraint_set_version` as an alias would be a semantic
owner violation and is rejected. Creating another database or registry is also
rejected.

The policy owner additionally binds the exact Risk execution
`RuntimeIdentity` triple (`code_version`, `runtime_profile_id`, and
`environment_fingerprint`) at admission. The formal Risk application request accepts only
`risk_policy_set_version_id`. The service re-resolves the exact policy wire from
the new existing-registry extension, reconstructs it through current R factories,
and requires exact object/wire identity before calling `apply_risk()`.

## RiskStateInput boundary

Risk V0 built-in policies may declare exact state requirements. Current main has
no generic canonical RiskState payload owner. This foundation therefore:

- supports the accepted no-state-input policy sets (`PASS_THROUGH`, normal
  `MAX_SINGLE_NAME`, and normal gross/net validation);
- rejects any policy requiring state input until every requirement can be
  resolved from an existing canonical owner;
- never accepts caller-created `RiskStateInput` objects or raw state values.

This is fail-closed and preserves the current truth ceiling. It is not represented
as state-input availability.

## Persistence design selected by the audit

Add migration `0003_risk_application_publication.sql` after the observed
contiguous `0001` and `0002` migrations. Add only append-only tables:

1. `risk_policy_set_publication`
2. `target_weight_vector_publication`
3. `risk_application_receipt_publication`
4. `risk_adjusted_weight_vector_publication`

Variable-length weight and receipt payloads live only in the Artifact Store.
Rows store exact identities, lineage, context, hash/size and truth metadata.
Policy-set wire is bounded control metadata and is stored canonically for exact
restart reconstruction. Foreign keys require source target before receipt and
receipt/source before adjusted vector. Triggers require every referenced artifact
to be `PUBLISHED` and make all four tables append-only.

## Formal service and read-side decision

`CanonicalRiskApplicationService.apply_and_publish(request)` will:

1. resolve exact target and policy owner rows;
2. resolve target bytes through the owner-derived P1 binding and existing
   Artifact Store;
3. reconstruct/assert the exact target and policy objects;
4. reject unresolved required RiskStateInput requirements;
5. validate the full request runtime triple and context against persisted owners;
6. call existing `apply_risk()`;
7. assert receipt/vector canonical identity;
8. publish exact canonical receipt/vector bytes to the existing Artifact Store;
9. write Artifact references, provenance and coupled owner rows in the existing
   SQLite PUBLISH transaction;
10. return persisted owner references, not a caller-provided runtime result.

The downstream resolver loads the adjusted owner, receipt owner and target owner,
uses owner-derived P1 bindings to verify exact bytes, reconstructs all canonical
objects, verifies cross-lineage, and returns the resolved vector plus metadata
needed for a future A3 binding.

## Atomicity and crash consistency

Filesystem publication and SQLite are not one atomic resource. Reuse the existing
PUBLISH UoW callback sequence:

```text
stage exact bytes
→ verify stages
→ publish same-volume content-addressed bytes
→ BEGIN IMMEDIATE SQLite transaction
→ register artifacts/references/provenance/owner rows
→ COMMIT
```

On pre-commit failure, delete only newly-created unreferenced content; never
delete a deduplicated pre-existing artifact. Exact idempotency makes retry safe.
After SQLite commit, owner rows and active references make bytes reachable. The
documented residual crash window is process loss after filesystem link but before
Catalog commit; such content is unreferenced and recoverable by the existing
reachability/GC model, never falsely claimed by an owner row.

## Derived exact write-set

Production/source:

- `apps/backend/src/v3_backend/domain/weights/codec.py`
- `apps/backend/src/v3_backend/domain/risk_runtime/codec.py`
- `apps/backend/src/v3_backend/domain/risk_runtime/application.py`
- `apps/backend/src/v3_backend/domain/risk_runtime/__init__.py`
- `apps/backend/src/v3_backend/domain/artifacts/policy.py`
- `apps/backend/src/v3_backend/adapters/sqlite/risk_application.py`
- `apps/backend/src/v3_backend/adapters/sqlite/repositories.py`
- `apps/backend/src/v3_backend/adapters/sqlite/artifact_publication.py`
- `apps/backend/src/v3_backend/adapters/sqlite/__init__.py`
- `apps/backend/src/v3_backend/migrations/versions/0003_risk_application_publication.sql`
- `apps/backend/src/v3_backend/migrations/validator.py`

Tests/docs:

- `apps/backend/tests/systemic_risk_application_publication/**`
- `docs/research/systemic-risk-application/RISK_APPLICATION_OWNER_GAP_AUDIT.md`
- `docs/research/systemic-risk-application/RISK_APPLICATION_PERSISTENCE_CONTRACT.md`
- `scripts/backend-foundation-test.mjs` only if suite discovery requires it

No package or lockfile change is required.

## Reuse closure

- W0 target/receipt/adjusted models: `DIRECT_REUSE`
- R policy/report/runtime/apply engine: `DIRECT_REUSE`
- SQLite Catalog/UoW/repository registry: `DIRECT_REUSE / BOUNDED_EXTENSION`
- Artifact Store/catalog/reachability: `DIRECT_REUSE / BOUNDED_ADMISSION_EXTENSION`
- Provenance: `DIRECT_REUSE`
- P1 resolver: `DIRECT_REUSE` on verification/read side
- new Risk engine/store/hash namespace/dependency: `PROHIBITED` and not needed

Owner audit result: the required vertical foundation is implementable through
bounded extensions of accepted owners; no real `STOP_FOR_REVIEW` condition is
present at this gate.
