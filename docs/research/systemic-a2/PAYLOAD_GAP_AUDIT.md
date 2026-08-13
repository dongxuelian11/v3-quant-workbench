# Systemic A2 Strategy / Signal Payload Gap Audit

Task: `V3-SYSTEMIC-A2-STRATEGY-SIGNAL-PAYLOAD-CLOSURE-01`
Authorized main / P1 base: `9dda07c254e1e3108d9ce3fec7624b4c7d0710f1`
Audit scope: Strategy formal input payload through `SignalArtifact`, `SelectionArtifact`, and `PortfolioIntent` only.

## PR #33 authority-final correction

Task `V3-SYSTEMIC-A2-STRATEGY-SIGNAL-AUTHORITY-FINAL-CLOSURE-01` closes the two
post-review findings without changing P0 or P1:

- `A2-OWNER-01`: the former public `StrategyPayloadOwnerRecord` seam is removed.
  Formal resolution now reads the shared SQLite Catalog under an active
  `READ_ONLY` unit of work: immutable `prediction_signal_version` publication,
  its exact PUBLISHED `model_version`/Dataset binding, the Dataset's exact
  PUBLISHED Snapshot/Universe context and membership Artifact, and the exact
  PUBLISHED score `artifact` descriptor. `CanonicalOwnerArtifactReference` is
  request intent only and carries no truth/admission claim.
  `GenericAdmittedArtifactReference` remains `UNRESOLVED_CALLER_ASSERTED` /
  `PRE_ALPHA` / non-formal.
- `A2-MINT-01`: `InputArtifactEvidence` is audit projection only; its
  `is_p1_verified` property is not authority.  All `_create_formal()` methods are
  removed.  Each formal service call reconstructs the owner resolver from the
  live Catalog, re-runs P1 byte resolution, runs the preserved pure evaluator,
  and materializes the exact Signal/Selection/PortfolioIntent chain within that
  execution.  Direct formal dataclass construction is rejected.

Formal input evidence records the canonical owner namespace, ID, version, and
payload role only after the live Catalog owner lookup and P1 resolution have
succeeded. Those owner fields are immutable audit provenance, not a second
authority path and not a mint credential.

The canonical owner source is the existing `prediction_signal_version` model
publication plus the shared Artifact Catalog.  This is a narrow A2 adapter over
the existing repository/publication seams, not a second registry or store.

## Authority and boundaries

- P0 authority `1.0.1` and all four locked hashes match `docs/status/V3_PROJECT_AUTHORITY_MANIFEST.json`.
- `npm.cmd run validate:authority` passed on the authorized base.
- P1 in `domain/payload_authority/**` is the sole shared payload-resolution foundation and is read-only for A2.
- No P0 amendment, P1 semantic change, A1/A3/A4/Q/S/T dependency, second payload system, second Strategy engine, or Portfolio/Risk/Backtest ownership change is authorized.

## Existing formal-path inventory

| Area | Existing behavior | Payload authority result | A2 action |
|---|---|---|---|
| `StrategyDefinitionVersion` | Content-addresses canonical Strategy IR, compiler, registry, runtime profile, and declared binding slots. | Owns Strategy semantics, but does not resolve score bytes. | Preserve unchanged. |
| `StrategyEvaluationBindingVersion` | Exact-binds Dataset, FactorEvaluation, FeatureMaterialization, Snapshot, Universe membership, period, knowledge cutoff, calendar, environment, and `BoundInputReference` ID/hash. | Strong identity graph, but `BoundInputReference` is not proof that evaluation used the referenced bytes. | Preserve identity; derive formal resolution context from it. |
| `BoundInputReference` | Carries binding key, artifact kind, source ID, artifact ID, SHA-256, and truth state. | Declared canonical ref/hash only. No byte size, owner version, payload role, schema fingerprint, or P1 receipt. | A2 resolver adapter supplies exact owner metadata without modifying the binding model. |
| `CrossSectionInputArtifact` | Carries `artifact_id`, `content_sha256`, `decision_time`, and caller-provided `values`. | **Gap:** evaluator compares ID/hash fields to the binding, then computes over the independent caller values. It never hashes those values or retrieves canonical bytes. | Keep only as pure/internal/legacy deterministic evaluator input. It must not establish formal payload provenance. |
| `DeterministicStrategyEvaluator.evaluate` | Checks exact binding keys, ID/hash equality, Universe membership, decision time, cutoff, and deterministic component execution. | **Gap:** correct-looking refs plus altered caller values can mint Signal/Selection/Intent objects. | Preserve pure engine semantics. New formal service resolves and decodes P1 payload first; pure results remain non-formal. |
| `InputArtifactEvidence` | Carries binding key, artifact ID, and content SHA-256. | **Gap:** no P1 request/binding/receipt identity, byte size, schema fingerprint, semantic fingerprint, or verified context. | Version evidence so formal identity includes exact P1 receipt and verified context while legacy wires remain compatible. |
| `SignalArtifact` | Binds definition, evaluation binding, input ref/hash, runtime/compiler, Universe hash, decision time, rows, truth, and content identity. | **Gap:** provenance proves only the declared input graph, not actual score bytes or a P1 receipt. | Formal creation binds receipt-bearing input evidence and formal evaluator/context identity. Legacy creation is explicitly non-formal and truth-capped. |
| `SelectionArtifact` | Binds definition, evaluation binding, input ref/hash, Universe membership, selected order and exclusions. | **Gap:** does not bind the exact SignalArtifact and has no P1 receipt. | Formal provenance binds the exact SignalArtifact identity plus the same verified input evidence/context. |
| `PortfolioIntent` | Requires exact canonical Selection/Signal objects and recomputes their identities; preserves Strategy binding and Universe lineage. | Downstream object linkage is strong, but inherited input evidence is still ID/hash-only. | Preserve linkage and add formal P1/context lineage through formal source artifacts. |
| Artifact Store | `FileSystemArtifactStore.read_bytes` validates content-addressed bytes and implements the P1 byte-reader port. | Reusable canonical byte source exists. | Reuse through `CanonicalPayloadResolver`; no second store. |
| P1 `CanonicalPayloadResolver` | Resolves an owner binding, verifies owner/role/context, reads exact bytes, independently recomputes SHA-256/artifact ID/size, and returns `VerifiedPayload` plus deterministic `PayloadResolutionReceipt`. | Satisfies shared byte-verification authority. It deliberately accepts requests only, not caller-created verified objects/receipts. | Consume unchanged from A2 formal service. |
| Strategy repository/contracts | Repository stores strategy definitions; current generated service contracts cover draft validation/compile/publish, not formal runtime evaluation. | No alternate formal evaluation entry point found. | Do not widen service/API scope in A2. Add bounded domain formal service only. |

## Formal input matrix

| Formal input | Declared ref/hash today | Actual value source today | Payload hash recomputed today | Bytes from canonical artifact today | Context binding today | Fix required |
|---|---|---|---|---|---|---|
| `FEATURE_MATERIALIZATION` score vector | `BoundInputReference.artifact_id/content_sha256` | `CrossSectionInputArtifact.values` supplied by evaluator caller | No | No | Definition binding, Dataset/Factor, Snapshot, Universe, period, cutoff, calendar and decision time are checked, but not bound to fetched bytes | Owner-specific A2 binding adapter + P1 resolution + strict deterministic score payload decoder + receipt evidence. |
| Generic prediction/factor/data score artifact | `GenericAdmittedArtifactReference` then `BoundInputReference` | `CrossSectionInputArtifact.values` supplied by evaluator caller | No | No | Generic ref is explicitly `UNRESOLVED_CALLER_ASSERTED`; evaluator only matches declared fields | Same P1 formal path; wrong owner/role/context/schema must fail before evaluation. |
| Universe ordering for decoded scores | `ExactUniverseReference.instrument_ids` and membership hash | Caller mapping is reordered/fill-missing by evaluator | No payload binding between score bytes and ordering | No | Evaluator rejects extra instruments but score payload does not prove exact ordered Universe | Formal payload must carry exact ordered instrument IDs and context identity; decoder rejects any order/membership mismatch. |
| Decision/as-of context | Binding period/cutoff plus caller `decision_time` | Caller field | No | No | Range and cutoff checks only | Decision time becomes part of the formal resolution context and verified payload schema. |

## Required formal contract

The formal request carries only Strategy definition/binding identity, binding key, expected canonical owner identity/version, payload role, decision time, schema expectation, and a byte bound. It carries no numeric vector.

For each required Strategy binding, the A2 adapter resolves an exact P1 `CanonicalPayloadBinding`. P1 retrieves and verifies the bytes. A2 then decodes one canonical JSON score-vector schema deterministically and checks:

- schema version and schema fingerprint;
- Strategy definition and evaluation binding identity;
- binding key and payload role;
- decision time / knowledge cutoff;
- exact Universe version, membership artifact/hash, and ordered instrument IDs;
- exact source artifact ID/hash and P1 context identity;
- unique instruments, finite decimal scores, and no unknown fields.

The score bytes do not embed `StrategyEvaluationBindingVersion` identity because that
binding includes the score artifact hash and would create a content-addressing cycle.
The exact evaluation binding is instead included in the P1 request/binding
`context_identity`, which is receipt-bound and verified before decoding.

Only the resulting internal `CrossSectionInputArtifact` reaches the pure evaluator.

## Compatibility and identity decision

Historical Track F artifacts used ID/hash-only `InputArtifactEvidence`. Silently interpreting those immutable objects as P1-verified would be false. A2 therefore uses a versioned provenance distinction:

- legacy/pure evaluator artifacts remain deterministic, separately testable, and explicitly non-formal;
- formal artifacts include P1 receipt identity, request/binding identity, verified byte size, schema/semantic fingerprints, context identity, and formal evaluator version in their content/provenance identity;
- absence of complete receipt evidence caps output truth at `PRE_ALPHA` and cannot represent the A2 formal path;
- public legacy artifact factories reject P1-verified evidence/formal source artifacts;
  only `FormalStrategyEvaluationService` uses the internal formal assembly path after
  crossing P1 in the same call;
- Selection formal identity binds the exact SignalArtifact where Signal is an upstream output;
- PortfolioIntent continues to require exact canonical source objects and inherits the receipt-bearing evidence.

This preserves existing IR and legacy artifact identity semantics while introducing a versioned formal provenance path. It does not create a second artifact namespace or mutate P1.

## Mandatory negative mapping

1. Altered caller score vector: formal request has no values; manual `CrossSectionInputArtifact` reaches only legacy non-formal evaluation.
2. Wrong bytes: rejected by P1 SHA/artifact/size verification.
3. Manual `CrossSectionInputArtifact`: cannot produce formal provenance state.
4. Wrong owner: rejected by P1 owner comparison / A2 owner adapter.
5. Wrong role: rejected by P1 role comparison.
6. Wrong context/as-of: rejected before decode/evaluation.
7. Wrong Universe/order: rejected by the A2 decoder.
8. Wrong schema fingerprint: rejected before decode.
9. No verified receipt: cannot create an A2 formal Signal.
10. Unrelated Signal: formal Selection linkage validation rejects it.
11. Unrelated Selection/context: PortfolioIntent exact-source validation rejects it.
12. Canonical happy path: owner binding -> P1 bytes -> deterministic decode/evaluate -> receipt-bound outputs.
13. Pure evaluator determinism: retained and tested separately.
14. Pure evaluator bypass: outputs remain non-formal/`PRE_ALPHA`; it has no argument that grants formal provenance.

## Acceptance ceiling

If all required tests, regressions, validations, exact-head PR checks, and CI pass, the maximum claim is:

`A2 STRATEGY/SIGNAL FORMAL PAYLOAD CHAIN = INTEGRATION_ACCEPTED CANDIDATE`

This does not establish `PRODUCT_CONNECTED`, `USER_VISUAL_ACCEPTED`, or `PRODUCTION_AVAILABLE`.
