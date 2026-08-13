# V3 Systemic Re-Audit Baseline

Baseline version: `1.0.0`
Status: finding register for future remediation; not a remediation-complete claim.

This register captures known systemic concerns conservatively against the mandatory vocabulary in `V3_CAPABILITY_LEVELS.md`. Historical module and PR evidence remains valid within its exact scope; this baseline does not reopen accepted local implementation findings and does not promote them to a broader capability level.

## Current conservative snapshot

Observed GitHub CURRENT at P0 admission: main `1c64a88b493631e0f6db973285477e1c0aca1f1a`, with exact-main CI success.

| Area | Current conservative state |
|---|---|
| Foundation, Data Truth, Factor, Dataset, Experiment, Model, Strategy, Portfolio, Risk, Backtest, Result, Artifact, Reviewer, Agent support | Multiple domain modules and historically accepted owner slices exist on current main. Exact maturity varies by owner; systemic payload, integration, product, and runtime re-audit is `PENDING`. Module presence alone is not `PRODUCT_CONNECTED` or `PRODUCTION_AVAILABLE`. |
| R Portfolio/Risk Agent | Merged owner implementation exists on current main. Production Agent execution remains `NOT_AVAILABLE / NOT_RUN`. |
| P Factor Agent/Library | PR #28 is merged into current main and exact-main CI succeeded. Systemic integration and payload-authority re-audit is `PENDING`; production Agent execution remains `NOT_AVAILABLE / NOT_RUN`. |
| Q Model Agent | PR #27 is OPEN and unmerged. Its candidate branch is not current-main authority. Merge is held. |
| S Alpha Mining | PR #30 is OPEN and unmerged. Its candidate branch is not current-main authority. Merge is held. |
| T Desktop Productization | PR #29 is OPEN and unmerged. Its candidate branch is not current-main authority. Complete Chinese-first, low-chrome/no-box, and `USER_VISUAL_ACCEPTED` status is not established. Merge is held. |

## SR-001 — Capability-level conflation

Historical module or PR acceptance was sometimes described too broadly as stage, product, or system completion.

- Current classification: systemic maturity reclassification `PENDING`.
- Disposition: future re-audit must restate each capability with the exact mandatory level and evidence.
- This P0 lock defines the vocabulary; it does not complete that reclassification.

## SR-002 — Documentation truth drift

README and status text can lag behind modules and merged work. At P0 admission, README still described several implemented domain areas as not rebuilt and described desktop/backend wiring as wholly absent despite a current read-only evidence bridge.

- Current classification: P0 README truth correction is in scope; repository-wide status reconciliation remains `PENDING`.
- Disposition: correct the root README now and build a later exact capability matrix.

## SR-003 — Canonical payload provenance gaps

Known audit concern: formal computation seams in Factor, Strategy, Backtest, and possibly downstream owners may allow caller-provided numeric payloads to be detached from canonical references. This is a concern to prove or disprove per path; this baseline does not claim every path is broken.

- Current classification: systemic payload re-audit `PENDING`.
- Disposition: P1 shared Canonical Payload Authority Foundation, followed only when authorized by A1/A2/A3 re-audit/remediation.
- Prohibited inference: module or unit-test acceptance does not prove resolver-backed actual payload ownership.

## SR-004 — Runtime/product connection gap

Domain modules may exist while production handlers, ports, desktop bridges, or product flows remain unavailable or only partially bound.

- Current classification: maturity varies; complete production integration is not established.
- Disposition: later Production Runtime Integration with named handlers, real canonical owners, negative/degraded-state evidence, and product proof.
- No module is promoted to `PRODUCTION_AVAILABLE` by this baseline.

## SR-005 — UI/product doctrine gap

The current T candidate improved chrome, scrollbars, and functionality, but complete Chinese-first, low-chrome/no-box, accessibility, and user-visual acceptance is not established.

- Current classification: T PR #29 OPEN; `USER_VISUAL_ACCEPTED` is `NOT_RUN` for the future systemic acceptance gate.
- Disposition: later bounded systemic UI remediation must remain on the same PR #29 if authorized.
- The P0 task does not modify UI source and does not merge T.

## SR-006 — Historical acceptance scope

Historical PASS remains evidence of local implementation quality for the named test, module, owner, or integration slice. It cannot automatically prove:

- `INTEGRATION_ACCEPTED` outside the tested path;
- `PRODUCT_CONNECTED`;
- `USER_VISUAL_ACCEPTED`;
- `PRODUCTION_AVAILABLE`.

Disposition: retain exact historical evidence while preventing language inflation. A generic `COMPLETE` claim is non-compliant unless the precise capability level, scope, and evidence are named.

## Held work and next authority boundary

- Q/S/T merges remain held.
- P1, A1, A2, A3, and A4 are `NOT_RUN` and are not authorized by this baseline.
- The next technical task after a separately authorized P0 merge is P1 Canonical Payload Authority Foundation.
