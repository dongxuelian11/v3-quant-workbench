# Systemic A1 Payload Gap Audit

## PR #34 bounded final correction

The reviewed `f60022e` candidate proved actual-byte integrity but still permitted
independently constructed Snapshot/Universe projections, caller-published label
bytes, and MemoryRepository-only formal owners. This correction closes those
three findings without changing P1:

- `A1-OWNER-01`: `SQLiteA1CanonicalOwnerRepository` derives Snapshot only from
  the existing `data_snapshot` publication/validation binding, exact persisted
  partition Artifact, accepted raw-capture sources, calendar, and effective /
  available-time ceiling. Universe is derived only from the existing published
  `universe_version` and `SQLiteDataTruthRepository.resolve_members_as_of()` PIT
  membership resolution. The A1 types remain projections and cannot mint owner
  authority by construction.
- `A1-LABEL-01`: `FormalLabelService` has no caller values argument. It resolves
  the Snapshot payload through P1, decodes the already admitted Factor input
  schema, and applies the existing `LabelSpec` horizon/source/missing semantics
  with `DeterministicForwardReturnLabelEngine`. Insufficient future observations
  are explicit JSON null and are never replaced with zero. The resulting label
  has a context- and source-receipt-bound `clp_sha256_` identity and is persisted
  before Dataset consumption re-resolves its bytes through P1.
- `A1-PERSIST-01`: FeatureMaterialization, canonical Label, and formal Dataset
  owner records are immutable canonical JSON Artifacts referenced through the
  existing SQLite Catalog `artifact` / `artifact_reference` infrastructure.
  There is no new database engine, payload resolver, Artifact Store, hash
  namespace authority, Factor evaluator, or label-definition system. Reopening
  the SQLite Catalog rehydrates the exact owner lineage; conflicting overwrite
  and unpersisted formal-looking objects fail closed.

The production formal service constructors require publisher ports. A memory
repository remains only a unit-test double and is not integration evidence.

Exact audit base: `origin/main@9dda07c254e1e3108d9ce3fec7624b4c7d0710f1` (P1 merge / GitHub CURRENT observed 2026-08-13).

## Owner map

| Boundary | Current-main owner | Observed payload behavior | Truth/admission today | A1 action |
|---|---|---|---|---|
| Data Truth / PIT | `domain/data_truth/model.py`, `pit.py`; SQLite repositories in `adapters/sqlite/repositories.py` | EOD and historical membership rows are resolved by time, but no immutable formal Snapshot owner object binds the Factor/Dataset payload artifact and knowledge cutoff. | Existing row/PIT behavior; no A1 formal payload receipt. | Add a narrow canonical Snapshot/Universe owner contract and repository port used only by the A1 formal service. |
| Universe | `UniverseMembershipInterval`, `resolve_universe_as_of`, SQLite membership repository | Membership is resolved as rows; raw `universe_version_id` is accepted by legacy Factor/Dataset context. | Legacy bindings are explicitly `UNRESOLVED_RAW_ID` and capped at `PRE_ALPHA`. | Formal path resolves a registered immutable Universe version and validates membership identity, instruments, Snapshot, as-of, and knowledge cutoff. |
| Factor definition/math | `domain/factors/ir.py`, `evaluator.py` | `FactorDefinitionVersion` is canonical math; pure evaluator accepts decoded `Mapping[str, Sequence]`. | Pure/internal engine, not a payload-authority boundary. | Preserve unchanged; formal service resolves exact definition from its owner repository, decodes only P1-verified bytes, then calls this evaluator. |
| Factor materialization | `domain/factors/evaluation.py::FeatureMaterialization.create` | Caller-provided `EvaluationResult.values` are hashed into an Artifact-looking ID; actual bytes are neither published nor verified and no P1 input receipt is bound. | Snapshot/Universe remain `PRE_ALPHA`; cannot establish formal payload provenance. | Keep legacy API compatible and add an A1 formal materialization with exact input receipt, schema/context, evaluator and published output descriptor. |
| Dataset | `domain/datasets/model.py::DatasetVersion.create` | Binds Factor evaluation IDs and label/split metadata, but does not resolve feature bytes or label bytes; a caller supplies an Artifact-looking dataset ID. | Context remains `PRE_ALPHA`; detached values are not excluded by a formal service. | Add an A1 formal Dataset service that re-resolves every FeatureMaterialization output and label payload through P1, builds deterministic samples, publishes actual bytes, and binds all receipts. |
| Artifact bytes | `domain/artifacts/**`, `adapters/artifact_store/filesystem.py` | Existing content-addressed store stages, validates, publishes, and re-hashes bytes on read. | Byte integrity owner exists. | Reuse through an A1 publisher adapter; no second store. |
| Shared payload verification | `domain/payload_authority/**` | P1 `CanonicalPayloadResolver` obtains owner binding through a port, reads exact bytes, independently verifies ID/SHA/size/context, and emits `PayloadResolutionReceipt`. | Accepted P1 foundation. | Reuse unchanged via narrow A1 owner-specific binding resolvers. |

## Formal computation audit

| Formal entry point | Declared canonical refs | Numeric payload parameter/source today | Current verification | Required P1 binding | Current level |
|---|---|---|---|---|---|
| `DeterministicReferenceEvaluator.evaluate` | `FactorDefinitionVersion` | Caller `Mapping[str, Sequence]` | shape/type/math only | Not formal; remains pure engine | internal/pure |
| `FeatureMaterialization.create` | definition + raw-ID context | caller-created `EvaluationResult` | derived hash only | Factor-input owner binding + P1 receipt; verified output Artifact | `PRE_ALPHA` legacy |
| `DatasetVersion.create` | feature/evaluation IDs + raw-ID context | no actual feature/label reads; caller Artifact ID | relationship metadata only | one materialization output binding per feature plus label binding | `PRE_ALPHA` legacy |

## Frozen implementation boundaries

Final source write-set:

- `apps/backend/src/v3_backend/domain/data_truth/formal.py`
- `apps/backend/src/v3_backend/domain/factors/formal.py`
- `apps/backend/src/v3_backend/domain/datasets/formal.py`
- package exports in those three A1 owners
- `apps/backend/src/v3_backend/adapters/systemic_a1_payload.py`
- `apps/backend/tests/systemic_a1_payload_closure/**`
- this audit and bounded suite registration

Protected semantic diff remains zero for `domain/payload_authority/**`, P0, A2/A3/A4/Q/S/T, Model, Strategy, Backtest, Agents, and Desktop.
