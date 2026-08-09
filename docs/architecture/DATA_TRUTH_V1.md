# WS-F Data Truth V1

WS-F is the first provider-independent financial capability layer on the Canonical Backend Foundation:

```text
Provider Adapter -> Raw Capture -> Canonical Normalize -> Snapshot -> PIT -> Universe
```

It is a daily/EOD China A-share foundation. It does not admit RQData, TuShare, AKShare, CSV, Demo data, or legacy data as Formal truth. External adapters remain optional isolated profiles.

## Authority and ownership

- The existing Control Catalog, repository registry, Artifact plane, Task/Run/Attempt model, and provenance graph remain the only authorities.
- `connector_capability(connector_version_id, capability_code)` is the single capability authority. A provider descriptor is identity/metadata only; `connector_data_capability` is connector-version-scoped policy/evidence with a composite foreign key to that authority. Missing exact-version capability resolves as typed `UNAVAILABLE` and never inherits from another connector version.
- A provider adapter can describe itself, report connector-version-scoped capability declarations, and submit `RawCaptureSubmission`. It has no Snapshot publication method or identity authority.
- Raw bytes are immutable, content-addressed Artifacts. Provider/source metadata and the provider-supplied availability fact are recorded separately from receipt/ingestion time. `raw_capture.available_time` is a nullable timestamp; no string sentinel can enter temporal comparison.
- Canonical EOD records carry permanent `InstrumentId`, canonical Trading Session identity, OHLCV, amount, trading status, raw-capture lineage, effective/available/ingested time, revision, provider, and content hash.

## Instrument and calendar

`Instrument` remains the permanent provider-independent identity. Existing alias intervals stay connector-version scoped and overlap is rejected. The canonical append-only `instrument_revision` authority carries board/security category in versioned lifecycle data together with effective interval, `available_time`, revision, provider, ingestion, content hash, and evidence. There is no parallel classification truth table. Listing and delisting dates are historical eligibility boundaries.

`trading_calendar_version` and append-only `trading_session` rows provide stable session identity, trading/non-trading status, and unique session ordering. Calendar/session evidence must reference Published Artifacts.

## Snapshot publication

The lifecycle is `CANDIDATE -> VALIDATED -> PUBLISHED`.

Publication requires all of the following in one Catalog transaction:

- at least one accepted Raw Capture source and an exact CalendarVersion linked before publication;
- at least one canonical partition whose Artifact is Published;
- a registered validation profile whose complete required-check set is PASS, with no blocking FAIL;
- a Published manifest whose SHA-256 is the Snapshot content hash;
- for `STRICT_PIT`, each source uses the Snapshot's exact admitted ConnectorVersion, its canonical connector capability is `DECLARED/FORMAL`, its policy revision semantics are `REVISION_AWARE` or `SOURCE_IMMUTABLE`, provider `available_time` exists, and provenance is complete.

Published snapshots, partitions, validations, and source links are immutable. A `ProjectContextRevision` can pin only a Published SnapshotVersion. New snapshots never revise an existing ProjectContext automatically.

## PIT rule

Strict visibility requires both:

```text
effective_time <= decision_time
available_time <= decision_time
```

The newest unambiguous revision visible at the decision time wins. A missing provider `available_time`, missing exact-version capability, `UNKNOWN` revision semantics, incomplete provenance, or competing latest revisions makes Strict PIT explicitly unavailable and fails closed. Availability alone never grants Strict PIT.

## Corporate actions and adjustment

Execution matching uses raw prices. The append-only corporate-action ledger is independently versioned from adjustment-factor manifests. Applying corporate actions to adjusted execution prices raises the double-count guard.

## Universe

`UniverseDefinition` and `UniverseVersion` remain the accepted authorities. `universe_membership_interval` stores immutable revision rows under a stable membership fact identity; raw revision intervals may overlap, while resolution selects exactly one latest visible revision or fails closed. Resolution requires the exact Published UniverseVersion, rejects `decision_time > knowledge_cutoff`, applies availability through `min(decision_time, knowledge_cutoff)`, and returns audit context containing SnapshotId, cutoff, as-of, decision time, and visibility ceiling. Present-day constituents and post-cutoff corrections are never backfilled into an older version.

The repository now enforces validation-profile completeness. The built-in `financial-invariants-v1` fixture profile remains `PRE_ALPHA`; this is a complete local invariant gate, not external-provider Formal admission.

## Deliberate limits

- no external provider admission;
- no frontend wiring;
- no Factor, Model, Portfolio/Risk, Backtest, or AI implementation;
- no claim that the private GT-0 corpus exists in this public baseline. Equivalent PIT/Universe invariants are covered locally, but corpus reuse remains NOT_RUN until the authority files are present.
