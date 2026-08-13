# Systemic P1 Reuse Adoption Matrix

Baseline: GitHub CURRENT `main` at `d1a3b0fb1f5837843b1ababb6a45136fba48c69e`.

P1 is a shared `MODULE_IMPLEMENTED` candidate foundation. This matrix does not claim domain integration, product connection, or production availability.

| Existing asset / option | Exact current-main evidence | Decision | P1 use / boundary |
|---|---|---|---|
| `v3_backend.adapters.artifact_store.FileSystemArtifactStore` | `read_bytes(artifact_id, *, max_bytes)` derives the path from the canonical artifact identity, enforces a read bound when supplied, and re-hashes published bytes before returning them. | `DIRECT_REUSE` | Structurally satisfies the narrow P1 byte-reader port. P1 adds defense-in-depth byte rehash and receipt construction at its own boundary. No adapter is required. |
| `v3_backend.domain.artifacts.identity` | Defines the sole `art_sha256_` namespace, SHA-256 validation, byte hashing, and storage-key derivation. | `DIRECT_REUSE` | P1 validates binding artifact identity with `sha256_from_artifact_id` and derives actual byte identity with the existing functions. |
| `v3_backend.domain.artifacts.model.ArtifactDescriptor` | Binds `artifact_id`, SHA-256, byte size, role, schema fingerprint, semantic fingerprint, and provenance entity identity. | `DIRECT_REUSE` | Owner-specific later integrations may project descriptors into P1 bindings; P1 does not create a competing descriptor. |
| `v3_backend.domain.artifacts.exceptions` | Provides low-level identity, integrity, collision, and missing-stage failures. | `DIRECT_REUSE` | P1 maps low-level read failures into its small typed resolution vocabulary while preserving the original exception as `__cause__`. |
| `v3_backend.provenance.canonical_hash` | Provides deterministic canonical JSON bytes and SHA-256 identities. | `DIRECT_REUSE` | Request, binding, and receipt identities use `canonical_sha256`; raw payload content continues to be hashed as bytes. |
| Artifact repository port | Catalogs staged/published artifacts and owner references, but does not itself expose verified bytes. | `REUSE_AS_EXISTING_OWNER_BOUNDARY` | P1 does not expand it. Later owner-binding resolvers may consult it behind their own injected port. |
| Provenance repository port | Records provenance entities/edges and walks ancestors. | `REUSE_AS_EXISTING_OWNER_BOUNDARY` | P1 carries a provenance reference identity but does not expand or duplicate the repository. |
| Snapshot / Data Truth / version repository ports | Own their domain records and publication bindings. | `DEFER_OWNER_SPECIFIC_ADAPTERS` | A1/A2/A3/B1/B2/B3 must supply canonical owner-binding resolvers against these owners; P1 does not depend on them directly. |
| New external dependency | No gap requires one; dataclasses, Protocols, `hashlib`, and existing canonical hashing are sufficient. | `REJECT / NOT_NEEDED` | No package or lockfile change. |
| Second Artifact Store | Would split byte authority and violate P0. | `PROHIBITED` | Not created. |
| Second artifact ID / SHA namespace | Existing `art_sha256_` is canonical. | `PROHIBITED` | Not created. |
| Domain-specific payload resolvers | P1 must not repair Factor, Strategy, Backtest, Model, Dataset, Runtime, Reviewer, Agent, or Desktop semantics. | `DEFER_TO_A1_A2_A3_B1_B2_B3` | Explicit architectural boundary. Later tracks must reuse the P1 contracts/service and may not invent alternate resolver systems. |

## Exact P1 write-set

```text
apps/backend/src/v3_backend/domain/payload_authority/__init__.py
apps/backend/src/v3_backend/domain/payload_authority/exceptions.py
apps/backend/src/v3_backend/domain/payload_authority/model.py
apps/backend/src/v3_backend/domain/payload_authority/ports.py
apps/backend/src/v3_backend/domain/payload_authority/service.py
apps/backend/tests/systemic_p1_payload_authority/__init__.py
apps/backend/tests/systemic_p1_payload_authority/test_payload_authority.py
docs/research/systemic-p1/REUSE_ADOPTION_MATRIX.md
docs/research/systemic-p1/CANONICAL_PAYLOAD_AUTHORITY_FOUNDATION.md
scripts/backend-foundation-test.mjs
```

The State Ledger is persisted under the task-required ignored `.codex/context/` path and is not part of the Git write-set. No adapter export, domain owner, P0 Authority file, package file, Q/S/T path, Agent path, or Desktop path is in scope.
