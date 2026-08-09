# WS-D Task / Workers / Resource Governor

Seed: `rebuild/br1-ws-a-contracts-v1@1f598ace73bbd1fe2c43e7253a7b9fcbe1f1658a`

## Ownership boundary

The backend main process is the only authority for Task, Run, Attempt, Event and
WorkerLease state. It injects identities and persistence ports into supervisors.
Workers receive bounded inputs, read tickets, an opaque lease token and a staging
namespace. They can return progress, checkpoint proposals, staged-output proposals
or a structured terminal result. A worker protocol message has no Task, Project,
Artifact, Registry, Catalog, publication or truth-state authority.

WS-D defines persistence protocols and deterministic in-memory fakes only. It does
not implement or modify WS-B DDL/repositories, WS-E transport, Artifact publication,
financial truth, contracts or frontend code.

## State machines

- Task: `QUEUED -> RUNNING`, pause/checkpoint, cancel, success/failure, and batch
  `PARTIAL`; retry/resume opens a new execution epoch and creates a new Attempt.
- Run: immutable identity tuple, `SEALED -> ACTIVE -> TERMINAL`; input changes are
  rejected with a new-Run requirement.
- Attempt: `QUEUED -> LEASED -> STARTING -> RUNNING`, optional checkpoint loops,
  then exactly one terminal state (`SUCCEEDED`, `FAILED`, `CANCELLED`, `LOST`).

## Durability and isolation

`DurableEventLog` orders aggregate mutation, append, commit and only then publish.
Replay is bounded and monotonic per project. Lease grants and heartbeats are
persisted, late/revoked leases cannot be used, and expiry marks the Attempt `LOST`.
Resource sampling is injected; the unadmitted default is one worker. Pressure
reduces future concurrency, requests checkpoint/spill, pauses admission, then
isolates the specific over-limit worker. No implicit environment or GPU fallback is
implemented.

Explicit shutdown enters `DRAINING`, checkpoints resumable work, cancels other work,
waits bounded grace, terminates remaining workers, expires leases, flushes events and
closes the Catalog through injected hooks.

## Verification

The WS-D suite exhaustively checks legal/illegal Task and Attempt transitions,
retry/resume identity rules, durable-before-notify ordering, replay, lease/heartbeat,
lost-worker recovery, cancellation, checkpoint compatibility, batch `PARTIAL`,
failed-child-only retry, pressure admission, staged-output non-publication, simulated
worker OOM isolation, worker authority prohibitions and shutdown order.
