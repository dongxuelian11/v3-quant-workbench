# Round 3 Integration Closure Evidence

Task: `V3-ROUND3-INTEGRATION-CLOSURE-01`

Correction finding: `ROUND3-INTEGRATION-MULTI-REBALANCE-LINEAGE-CARDINALITY`

Base: `3fd4bc6e754d3e55e8c86da99acaadeb94c5affc`

Previous reviewed head: `60a7e41f51bc4c201d8ac26f7fb2739c63623dfd`

This evidence records a read-only integration closure. It does not claim formal validation, user acceptance, execution authority, publication authority, or any Round 4 capability.

## Schema and cardinality

- Projection schema remains `v3.round3_canonical_evidence_projection/1.0.0`.
- Bundle schema is `v3.round3_research_evidence_bundle/1.1.0`.
- Closed vocabulary: PortfolioIntent, TargetWeightVector, RiskAdjustedWeightVector, RiskDecisionReport, BacktestRunSpec, BacktestRunResult.
- Cardinality: deduplicated zero-to-many upstream H/I projections, at least one scheduled RiskAdjusted chain, exactly one BacktestRunSpec, and exactly one BacktestRunResult.
- Projection order: fixed kind order, then canonical object ID.
- Schedule order: canonical RunSpec order by `effective_at`, preserved in structured `schedule_bindings` with exact RiskAdjusted ID/hash.

## Canonical two-rebalance acceptance graph

| Rebalance | effective_at | PortfolioIntent | TargetWeightVector | RiskAdjustedWeightVector | RiskDecisionReport | RiskApplicationReceipt |
| --- | --- | --- | --- | --- | --- | --- |
| A | `2026-01-06T01:00:00+00:00` | `pint_sha256_011e48a40e65b1ff92213b5ce1a4895f0412f91c0b534f8aa78c03e49df96a9e` | `twv_sha256_9d9d92d3de1d30e4149879183aab5b2bdf2f0e93227526054e477d8bc86ffabd` | `rawv_sha256_d088399d897adb9b91d1126d5bc68415a6633a180017de5d43949f01a0579eaa` | `rdr_sha256_b732c998ff2c2f65f81303c128dc0f368059eacb91d66b4321f36e915de339e4` | `rar_sha256_2d20d5593550d6835e43e378c69a4538d781c8f020b72b0fac815a98eda5eb9d` |
| B | `2026-01-07T01:00:00+00:00` | `pint_sha256_146f74ad6f8d8d2be0d21e3590f573125a7e57d566f9fc4357b30a74a23789de` | `twv_sha256_208750185bacf5ce2758e4ba1eff8ecbfea197f792d5894954d02565ffc4bc32` | `rawv_sha256_2afb77846c2f39a7c92ef883767416b336bf4a9c8762a3636c68eb749bfa0efb` | `rdr_sha256_f0c13729801864cb98a96f9ae3bf30e17d0ad2e390db2203529f10324c51c8ec` | `rar_sha256_943847544e759dad2e4f66eaaac98923eb84405067d1bf52c965181666d8b823` |

RunSpec: `btrs_sha256_30a3debc8b915903d748c6e5613375a1219bed7ca8397f9a3539a49ddcebf7ba`

Result: `btrr_sha256_e21779419581527099a019c32512b3e10c3c74ca962cfd266f7a63c689d1722d`

The actual deterministic engine produced two target quantity vectors, two NAV rows, four fills, and the canonical Result above. No Round 4 performance analytics were added.

## Exact coverage and fail-closed graph

The acceptance bundle contains 10 projections, two structured schedule bindings, and 11 exact lineage edges. For each scheduled RiskAdjusted vector, Python validates its Target ID/hash, exact RiskApplicationReceipt equality and Target binding, RiskDecisionReport Target binding, and Target PortfolioIntent ID/hash. Each receipt-bound edge carries that rebalance chain's actual receipt ID.

The TypeScript parser independently requires unique `(kind, ID)` objects, deterministic ordering, one RunSpec/Result, exact schedule coverage, no orphan RiskAdjusted or upstream evidence, exact per-risk Target/Report/Intent/receipt edges, exact Result/RunSpec identity, and no missing, duplicate, wrong, or extra edges. Unknown fields, kinds, schemas, renderers, or executable output remain rejected.

Every projection preserves `truth_state=NOT_FORMAL`, `admission_state=PRE_ALPHA`, and `validation_state=NOT_RUN` through backend, transport, Agent Workspace, evidence cards, artifacts, and timeline.

## Runtime and production boundary

The explicit development acceptance runtime invokes canonical H construction twice, canonical I risk application twice, canonical J `BacktestRunSpec.create`, and the actual deterministic J engine. Its bundle crosses the existing WS-E replay, BackendSupervisor, BackendRuntimeEventRelay, existing `backendRuntime:*` namespace, the single sandboxed preload, and Agent Workspace.

Production discovery remains `LIVE_READ_ONLY / NO_CANONICAL_EVIDENCE_AVAILABLE` until an official persisted H/I/J discovery owner exists. It never substitutes this fixture. The renderer surface remains exactly `getCapabilities`, `getHealth`, `getEvidenceSnapshot`, `onEvidenceEvent`, and `onConnectionState`; L0/L1 remain available and L2/L3 remain denied.

## Verification

- Python correction suite: PASS, 17 tests including single/multi paths, missing/orphan risk, wrong Target/Report/Intent, borrowed receipt, shared Intent dedup, duplicate/conflicting projections, deterministic ordering, schedule display, and Result/Spec mismatch.
- Full backend suite and compile: PASS.
- TypeScript/WS-E/backendRuntime: PASS, 15 tests including real two-rebalance cross-language replay and parser fail-closed mutations.
- Frontend unit behavior: PASS, 18 tests.
- Typecheck, lint, production build: PASS.
- Real Electron 39.8.10: PASS; 10 exact evidence objects, 10 session-scoped timeline entries, both Target/Risk/Report chains individually inspected, structured two-entry RunSpec schedule rendered, canonical Result rendered, five Labs preserved, L1 local draft preserved, L2/L3 absent, restart passed, and zero renderer console errors.
- `npm run validate`: PASS on the full local validation chain.
- `npm run validate:public`: PASS on the exact public validation chain.

The Electron fixture is development integration evidence only. It remains `NOT_FORMAL`, `PRE_ALPHA`, and `NOT_RUN`; it is not UAU or formal truth.
