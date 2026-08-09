# WS-B Logical and External Constraint Boundary

All non-external persistence constraints required by the frozen schema notes are implemented:

- every Artifact-reference column is guarded by INSERT/UPDATE triggers requiring a PUBLISHED Artifact;
- ProjectContext to Universe is guarded by an INSERT trigger requiring a PUBLISHED UniverseVersion;
- provider alias overlap is rejected at both the repository boundary and schema trigger;
- ProjectContext revisions, Events, provenance, and other immutable records are append-only;
- published/versioned and terminal rows reject mutation/deletion according to their lifecycle;
- Run inputs and Trial parameters are sealed;
- JSON is valid and at most 64 KiB at the schema boundary; canonicalization and numerical-array rejection occur at the repository boundary;
- one active WorkerLease per Attempt is enforced by the frozen partial unique index.

Exact remaining external/logical-only checks:

1. Artifact byte existence, byte hash, safe-format verification, atomic rename, and compensation are
   represented by the PUBLISH callback contract; the byte-store implementation belongs to WS-C.
2. Semantic classification of a small JSON value as tabular/numerical is enforced by the sole
   repository write path, because SQLite cannot infer business meaning from JSON shape.
3. Reconciliation PASS, optimization residual PASS, and other report-content decisions are
   explicit boolean preconditions to repository methods; producing those financial/validation
   decisions is outside WS-B.
4. Backup bytes are managed by the authorized Catalog backup/restore adapter. Publishing those
   bytes into the future general Artifact Store is an integration responsibility with WS-C.

No legacy database upgrade or in-place restore entry point exists.
