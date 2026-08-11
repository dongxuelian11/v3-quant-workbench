# Round 3 Integration Reuse / Adoption Report

Task: `V3-ROUND3-INTEGRATION-CLOSURE-01`

Base: `3fd4bc6e754d3e55e8c86da99acaadeb94c5affc`

This closure is a read-only view and transport integration. It does not add or own portfolio, risk, backtest, truth, admission, execution, or publication semantics.

## Adoption matrix

| Existing owner/capability | Decision | Integration use |
| --- | --- | --- |
| `PortfolioIntent.to_wire()` | DIRECT_REUSE | Source identity, truth/admission, intent facts, and provenance inputs |
| `TargetWeightVector.to_wire()` | DIRECT_REUSE | Exact H identity/hash, timing, rows, cash, construction and evidence refs |
| `RiskAdjustedWeightVector.to_wire()` | DIRECT_REUSE | Exact I identity/hash, source Target binding, receipt binding, rows and cash |
| `RiskDecisionReport.to_wire()` | DIRECT_REUSE | Exact policy/report/stage evidence without recomputing risk |
| `BacktestRunSpec.to_wire()` | DIRECT_REUSE | Exact scheduled RiskAdjusted IDs/hashes and pinned rule/cost/timing identities |
| `BacktestRunResult.to_wire()` | DIRECT_REUSE | Exact result/run-spec identity, NAV, fill/diagnostic and ledger facts |
| Artifact / Provenance repository protocols | DIRECT_REUSE | Official storage boundary retained; no second store |
| Persisted H/I/J discovery | NOT_NEEDED | Current repositories expose no canonical H/I/J discovery contract; production returns explicit no-evidence until official persistence exists |
| `Round3EvidenceProvider` | THIN_ADAPTER | Read-only provider seam; production unavailable/empty and explicit development provider share the same projection path |
| Canonical projection builder | THIN_ADAPTER | Validates exact H→I→J lineage and copies canonical truth/admission only |
| `Round3ResearchEvidenceBundleV1` 1.1.0 | BOUNDED_EXTENSION | Closed kind vocabulary with variable H/I cardinality, structured canonical schedule bindings, exact coverage, and no orphan RiskAdjusted evidence |
| WS-E framed runtime and event replay | DIRECT_REUSE | Canonical projection bundle crosses the existing authenticated transport |
| `BackendSupervisor` | BOUNDED_EXTENSION | Optional explicit backend module for integration fixture; default production bootstrap unchanged |
| `BackendRuntimeEventRelay` | BOUNDED_EXTENSION | Cache the latest validated evidence event for race-free read-only snapshot delivery |
| `backendRuntime:*` IPC | BOUNDED_EXTENSION | One read-only evidence snapshot in the existing namespace; no portfolio/risk/backtest/round3 IPC |
| preload backendRuntime bridge | BOUNDED_EXTENSION | Read-only product surface only; mutation methods are not exposed to renderer |
| sandboxed Electron preload | BOUNDED_EXTENSION | The single existing preload exposes the bounded read-only backendRuntime methods; no adjacent preload bundle or second IPC is introduced |
| backend child-process environment | BOUNDED_EXTENSION | Preserve the standard Windows `APPDATA` location so CPython can load installed IANA timezone data; no secret or application-owned environment is forwarded |
| Agent Workspace active-session scope | DIRECT_REUSE | Statements, timeline, evidence selection, and artifact rendering remain session-bound |
| closed Artifact renderer registry | BOUNDED_EXTENSION | Activate a typed bounded `backtest-result` renderer; arbitrary HTML/JS remains rejected |
| five canonical Labs | DIRECT_REUSE | Strategy/Backtest/Result routing uses the existing five-Lab registry |
| `packages/contracts` | BOUNDED_EXTENSION | Closed view/transport schema; explicitly not canonical financial authority |
| parallel finance model/IPC/store | REJECT_DUPLICATION | Forbidden by task boundary |

## Why there is no second IPC

The integration uses the existing WS-E request/event framing, `BackendSupervisor`, event relay, and `backendRuntime:*` main/preload namespace. The sole new renderer fetch is a read-only snapshot on that existing namespace so a renderer cannot miss an evidence replay event during startup. No `round3:*`, `portfolio:*`, `risk:*`, or `backtest:*` IPC exists.

## Why there is no second Artifact Store

The official Artifact/Provenance repository protocols remain the only storage authority. They currently do not expose persisted H/I/J discovery, so the production provider returns explicit `NO_CANONICAL_EVIDENCE_AVAILABLE`. The explicit development provider generates real canonical H/I/J objects and sends their projection through the same WS-E/preload/renderer path; it does not persist or impersonate production data.

## Why the projection is not financial authority

Every projection carries the canonical source object ID and content SHA-256 and is built only from existing owner `to_wire()` output. It creates no finance IDs, factories, truth state, admission state, weights, risk decision, run spec, or backtest result. Any lineage mismatch fails closed.

## Multi-rebalance cardinality and ordering

Bundle `v3.round3_research_evidence_bundle/1.1.0` keeps the six-kind vocabulary closed while admitting all canonical upstream objects required by one RunSpec: zero-to-many deduplicated Intent/Target/RiskAdjusted/RiskDecision projections and exactly one RunSpec/Result. A valid emitted bundle has at least one scheduled RiskAdjusted chain.

Projections are ordered first by the fixed kind order and then by canonical object ID. Structured `schedule_bindings` remain in canonical RunSpec `effective_at` order and carry index, timestamp, RiskAdjusted ID, and content SHA-256. Every scheduled vector must have one exact projected chain, every projected RiskAdjusted must be scheduled, and each receipt-bound edge uses that chain's actual receipt ID. Shared upstream objects are deduplicated by `(kind, canonical ID)`; duplicate wire projections, conflicting hashes, missing schedule evidence, orphan risk evidence, and extra lineage edges fail closed.

## Frozen exact write-set

```text
.codex/context/V3-ROUND3-INTEGRATION-CLOSURE-01_STATE.json
apps/backend/src/v3_backend/adapters/round3_evidence/**
apps/backend/tests/round3_integration_closure/**
packages/contracts/src/index.ts
packages/contracts/src/round3Evidence.ts
apps/desktop/src/main/backendRuntime/eventRelay.ts
apps/desktop/src/main/backendRuntime/ipc.ts
apps/desktop/src/main/backendRuntime/processFactory.ts
apps/desktop/src/main/backendRuntime/supervisor.ts
apps/desktop/src/main/backendRuntime/types.ts
apps/desktop/src/preload/backendRuntime/bridge.ts
apps/desktop/src/preload/backendRuntime/install.ts
apps/desktop/src/preload/backendRuntime/types.ts
apps/desktop/src/main.ts
apps/desktop/src/preload.ts
apps/desktop/src/renderer/agentWorkspace.ts
apps/desktop/src/renderer/round3Evidence.ts
apps/desktop/src/renderer/App.tsx
apps/desktop/src/renderer/components/AgentWorkspace.tsx
apps/desktop/src/renderer/components/ArtifactViewer.tsx
apps/desktop/src/renderer/components/ResearchSessionNavigator.tsx
tests/unit/contract-behavior.test.mjs
tests/ws_e_electron_runtime/cross-language.test.mjs
tests/ws_e_electron_runtime/framing-and-boundary.test.mjs
tests/ws_e_electron_runtime/supervisor.test.mjs
scripts/backend-foundation-test.mjs
scripts/public-frontend-smoke.mjs
scripts/run-electron-smoke.mjs
scripts/electron-smoke.cjs
scripts/frontend-smoke.mjs
docs/research/round3-integration-closure/**
```

Protected H/I/J financial-semantic owners remain read-only.
