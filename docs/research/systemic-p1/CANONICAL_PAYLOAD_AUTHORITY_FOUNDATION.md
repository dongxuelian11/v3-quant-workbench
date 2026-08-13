# Canonical Payload Authority Foundation

Status: Systemic P1 shared foundation, `MODULE_IMPLEMENTED` on this branch. The maximum candidate claim after all exact-head gates is `MODULE_ACCEPTED`; this document does not claim `INTEGRATION_ACCEPTED`, `PRODUCT_CONNECTED`, or `PRODUCTION_AVAILABLE`.

Resolver contract: `v3.canonical-payload-resolver/1.0.0`.

## Problem and authority boundary

A valid-looking ID or self-declared SHA-256 is not proof of the payload used by a computation. A caller can pair an authentic reference with different prices, scores, samples, or market state. If the formal engine accepts those independent values, the reference decorates an untrusted payload rather than authorizing it.

P1 establishes one shared boundary:

```text
untrusted PayloadResolutionRequest
  -> injected CanonicalPayloadBindingResolver
  -> owner-derived CanonicalPayloadBinding
  -> existing verified Artifact Store byte-reader seam
  -> P1 independent bounded SHA-256 and size verification
  -> VerifiedPayload
  -> deterministic PayloadResolutionReceipt
```

Authority comes from executing this boundary against the canonical owner and actual stored bytes. It does not come from Python type identity, a private token, a `trusted=True` flag, a self-consistent hash field, or possession of a binding, verified-payload, or receipt object.

## Contracts

### Untrusted request

`PayloadResolutionRequest` carries only canonical owner namespace/ID/version, payload role, exact context identity, and an explicit positive `max_bytes`. Its deterministic `prq_sha256_...` identity includes the bound read policy. It has no fields for values, prices, samples, scores, market state, bytes, paths, URLs, or decoding instructions.

### Owner-derived binding

`CanonicalPayloadBinding` carries the owner identity and version, role, existing `art_sha256_` artifact ID, expected SHA-256, expected byte size, schema and semantic fingerprints when known, exact context identity, provenance reference when known, and binding version. Its deterministic `cpb_sha256_...` identity uses the existing canonical JSON hash implementation.

Constructing a binding is not authority. The formal service obtains it only by calling the injected `CanonicalPayloadBindingResolver` for the current request and then verifies exact owner, role, and context equality before any byte read.

### Verified payload

The resolver passes only the bound artifact ID and caller's explicit read limit to `VerifiedArtifactByteReader`. `FileSystemArtifactStore` directly satisfies this seam: it derives the path from the canonical artifact ID, checks the read bound, and re-hashes the published file before returning bytes. P1 then independently hashes the exact returned bytes, derives their existing `art_sha256_` ID, and checks bound SHA-256, artifact ID, byte size, and read limit again.

`VerifiedPayload` is the result of that execution, but it remains a serializable value. A caller-created instance is not accepted as a substitute for `PayloadResolutionRequest` and cannot authorize a formal consumer.

### Deterministic receipt

`PayloadResolutionReceipt` binds the request identity, binding identity, artifact ID, actual verified SHA-256 and byte size, schema/semantic fingerprints when known, exact context identity, resolver contract version, and `VERIFIED` status. Its `prr_sha256_...` identity uses canonical JSON and contains no wall-clock timestamp, random UUID, Python `repr()`, path, or caller payload.

The receipt is evidence, not execution authorization. The resolver accepts only a request; a manually constructed receipt cannot bypass owner binding resolution or actual byte verification.

## Context semantics

P1 treats `context_identity` as an immutable, deterministic owner-defined reference and requires exact request/binding equality. It does not invent generic PIT, as-of, knowledge-time, calendar, membership, or financial semantics. A1/A2/A3/B1/B2/B3 must define and validate those meanings at their canonical owner boundary while reusing this shared equality and byte-verification path.

## Typed fail-closed outcomes

| Code | Meaning |
|---|---|
| `PAYLOAD_BINDING_UNAVAILABLE` | The canonical owner returned no binding; no empty/default payload is produced. |
| `PAYLOAD_OWNER_MISMATCH` | Owner namespace, ID, or version differs. |
| `PAYLOAD_ROLE_MISMATCH` | The bound role differs from requested role. |
| `PAYLOAD_CONTEXT_MISMATCH` | Exact owner-defined context identity differs. |
| `PAYLOAD_ARTIFACT_ID_MISMATCH` | Artifact ID is non-canonical or identifies a different SHA-256. |
| `PAYLOAD_CONTENT_MISMATCH` | Returned/stored bytes fail integrity or independent P1 hashing. |
| `PAYLOAD_SIZE_MISMATCH` | Actual byte size differs from the owner binding. |
| `PAYLOAD_READ_BOUND_EXCEEDED` | The bound or actual payload exceeds the explicit positive read limit. |
| `PAYLOAD_ARTIFACT_UNAVAILABLE` | The bound Artifact Store bytes are absent. |

Low-level Artifact Store integrity and missing-file failures are mapped without losing their original exception cause. Missing and malformed data never become empty bytes, zeros, demo content, or a verified result.

## Formal path examples

Accepted foundation path:

```text
request(owner=DatasetVersion dsv_001, role=FEATURE_ROWS,
        context=dataset-context-sha, max_bytes=8 MiB)
  -> Dataset owner adapter resolves its stored binding
  -> art_sha256_... bytes read from FileSystemArtifactStore
  -> actual bytes hash/ID/size/context all match
  -> VerifiedPayload + deterministic receipt
```

Rejected shortcut:

```text
request(dataset_id=dsv_001, values=[...])
```

The request contract cannot carry the values. A caller cannot instead hand the service a binding, verified payload, or receipt. Altered numeric-looking bytes reject even when the caller presents the expected reference and SHA field.

## Reuse and dependency direction

P1 directly reuses:

- `FileSystemArtifactStore` as the verified byte-reader implementation;
- `v3_backend.domain.artifacts.identity` as the only artifact ID/SHA namespace;
- `ArtifactDescriptor` semantics for hash, size, role, schema, semantic, and provenance metadata;
- artifact-domain exceptions as low-level causes;
- `v3_backend.provenance.canonical_hash` for structured deterministic identities.

P1 introduces no storage backend, artifact namespace, canonical JSON algorithm, repository expansion, network fetch, arbitrary path input, decoder, pickle/deserialization path, cache, or third-party dependency. Domain engines, Agent, runtime, Electron, and desktop do not sit below this module.

## Later integration obligations

- A1/A2/A3 must implement owner-specific binding resolvers for their named Data Truth, Universe, Factor/Dataset, Strategy, Backtest, or other authorized Wave A scopes. They must prove PIT/as-of meaning, repository reachability, descriptor/owner relationships, and exact context construction.
- B1/B2/B3 must consume this same foundation when resolving Model, Experiment/Reviewer, product evidence, or other authorized Wave B payloads. They may add thin owner adapters, not alternate trust models.
- Each integration must start from a request, cross the canonical owner binding port, resolve actual Artifact Store bytes, preserve the P1 receipt, and add its domain semantic evidence.
- Each formal consumer must reject caller-created `VerifiedPayload` or receipts as authorization and must not cache around required verification.
- Every downstream capability remains bounded by upstream truth/admission and must earn `INTEGRATION_ACCEPTED` separately with real positive and negative end-to-end evidence.

## What P1 proves and does not prove

P1 tests prove deterministic request/binding/receipt identities, exact successful resolution, altered-byte rejection, owner/role/context/artifact/size/bound failures, missing binding/artifact behavior, independent P1 rehashing, direct filesystem-store reuse, tamper rejection, non-authority of manually created output objects, and prohibition of raw payload fields.

P1 does not prove that Factor, FeatureMaterialization, Dataset, Strategy, Signal, Portfolio, Risk, Backtest, Result Analytics, Model, Alpha Mining, Reviewer, Agent, runtime, Electron, or desktop is integrated with this foundation. It does not prove PIT semantics, production storage, product connection, execution authorization, or production availability. Those states remain `PENDING`, `NOT_RUN`, or `NOT_AVAILABLE` according to their owning evidence.
