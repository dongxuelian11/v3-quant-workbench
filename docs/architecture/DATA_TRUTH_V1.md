# WS-F Data Truth V1

WS-F is the first provider-independent financial capability layer on the Canonical Backend Foundation:

```text
Provider Adapter -> Raw Capture -> Canonical Normalize -> Snapshot -> PIT -> Universe
```

It is a daily/EOD China A-share foundation. It does not admit RQData, TuShare, AKShare, CSV, Demo data, or legacy data as Formal truth. External adapters remain optional isolated profiles.

## Authority and ownership

- The existing Control Catalog, repository registry, Artifact plane, Task/Run/Attempt model, and provenance graph remain the only authorities.
- A provider adapter can describe itself, declare capabilities, and submit `RawCaptureSubmission`. It has no Snapshot publication method or identity authority.
- Raw bytes are immutable, content-addressed Artifacts. Provider/source metadata and the provider-supplied availability fact are recorded separately from the legacy Catalog receipt timestamp.
- Canonical EOD records carry permanent `InstrumentId`, canonical Trading Session identity, OHLCV, amount, trading status, raw-capture lineage, effective/available/ingested time, revision, provider, and content hash.

## Instrument and calendar

`Instrument` remains the permanent provider-independent identity. Existing alias intervals stay connector-version scoped and overlap is rejected. `instrument_classification` freezes board and security category without changing the accepted Instrument table. Listing and delisting dates are historical eligibility boundaries.

`trading_calendar_version` and append-only `trading_session` rows provide stable session identity, trading/non-trading status, and unique session ordering. Calendar/session evidence must reference Published Artifacts.

## Snapshot publication

The lifecycle is `CANDIDATE -> VALIDATED -> PUBLISHED`.

Publication requires all of the following in one Catalog transaction:

- at least one accepted Raw Capture source and an exact CalendarVersion linked before publication;
- at least one canonical partition whose Artifact is Published;
- a blocking financial validation PASS and no blocking FAIL;
- a Published manifest whose SHA-256 is the Snapshot content hash;
- for `STRICT_PIT`, every partition and every Raw Capture source has provider-authoritative `available_time`.

Published snapshots, partitions, validations, and source links are immutable. A `ProjectContextRevision` can pin only a Published SnapshotVersion. New snapshots never revise an existing ProjectContext automatically.

## PIT rule

Strict visibility requires both:

```text
effective_time <= decision_time
available_time <= decision_time
```

The newest revision visible at the decision time wins. A missing provider `available_time` is represented explicitly, makes `strict_pit_capable=false`, and fails closed. Catalog receipt time is never promoted into provider availability.

## Corporate actions and adjustment

Execution matching uses raw prices. The append-only corporate-action ledger is independently versioned from adjustment-factor manifests. Applying corporate actions to adjusted execution prices raises the double-count guard.

## Universe

`UniverseDefinition` and `UniverseVersion` remain the accepted authorities. `universe_membership_interval` adds append-only historical intervals with revision, provider-availability cutoff, and exact provenance Artifact. Resolution applies membership interval, knowledge time, and listing/delisting lifecycle together; present-day constituents are never backfilled into history.

## Deliberate limits

- no external provider admission;
- no frontend wiring;
- no Factor, Model, Portfolio/Risk, Backtest, or AI implementation;
- no claim that the private GT-0 corpus exists in this public baseline. Equivalent PIT/Universe invariants are covered locally, but corpus reuse remains NOT_RUN until the authority files are present.
