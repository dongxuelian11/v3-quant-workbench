# Round 3 Integration Closure Evidence

Task: `V3-ROUND3-INTEGRATION-CLOSURE-01`

Base: `3fd4bc6e754d3e55e8c86da99acaadeb94c5affc`

This evidence records a read-only integration closure. It does not claim formal validation, user acceptance, execution authority, publication authority, or any Round 4 capability.

## Canonical source identities

| Source kind | Canonical object ID |
| --- | --- |
| PortfolioIntent | `pint_sha256_011e48a40e65b1ff92213b5ce1a4895f0412f91c0b534f8aa78c03e49df96a9e` |
| TargetWeightVector | `twv_sha256_7e9aa3d18cd1d4c1ea2dca665fdd760c866907c2043be3c467dc25df1152b9cd` |
| RiskAdjustedWeightVector | `rawv_sha256_d6f24bd4402608eb8a7c844137162c68d8effd9ad535509efe4cf586203ff2fa` |
| RiskDecisionReport | `rdr_sha256_060f64b4c30726126071aa15d407c1731ebf6fbec78d2d2494471117ec56cdf0` |
| BacktestRunSpec | `btrs_sha256_d39992efac79dd077ab0919b59bc4072adb0f987c624c25bbfd019fef31490be` |
| BacktestRunResult | `btrr_sha256_4f08d474405ec0a5451bfc898851848db37a893479bf6e51af0afaf9ed06c09f` |

Every source retains `truth_state=NOT_FORMAL`, `admission_state=PRE_ALPHA`, and `validation_state=NOT_RUN` in the backend projection, transport parser, renderer state, evidence cards, artifact view, and timeline.

## Exact lineage checks

The projection validates and emits six exact lineage edges:

1. PortfolioIntent ID and content hash to TargetWeightVector source binding.
2. TargetWeightVector ID and content hash to RiskAdjustmentReceipt source binding.
3. TargetWeightVector ID and content hash to RiskDecisionReport source binding.
4. RiskDecisionReport to RiskAdjustedWeightVector, carrying the exact RiskApplicationReceipt binding.
5. RiskAdjustedWeightVector ID and content hash to every BacktestRunSpec scheduled-vector binding.
6. BacktestRunSpec run-spec ID to BacktestRunResult run-spec binding.

Unknown source kinds, unknown fields, schema drift, source-hash mismatch, and any lineage mismatch fail closed.

## Runtime path and permission boundary

The development acceptance fixture invokes the existing canonical H construction, I risk application, and J backtest engine. The resulting projection crosses the existing WS-E framed event replay, `BackendSupervisor`, `BackendRuntimeEventRelay`, existing `backendRuntime:*` IPC namespace, the single sandboxed preload, and Agent Workspace.

Production starts the canonical backend bootstrap and reports either connected canonical evidence, explicit connected-empty `NO_CANONICAL_EVIDENCE_AVAILABLE`, or explicit disconnected state. It never substitutes the development fixture or demo evidence. The renderer receives only L0 observe and L1 local-draft behavior; L2 submit and L3 execute/publish remain denied and are absent from the exposed bridge.

## Verification

- Backend Round 3 suite: PASS, 7 tests.
- WS-E/backendRuntime suite: PASS, 15 tests including a real cross-language canonical H/I/J replay.
- Frontend unit behavior: PASS, 18 tests.
- Typecheck, lint, production build, public frontend smoke: PASS.
- Real Electron 39.8.10: PASS, sandbox and web security enabled, exact six source IDs observed, H/I/J slots connected, actual BacktestRunResult rendered, L1 draft remained local, L2/L3 absent, restart passed, and zero renderer console errors.
- Visual geometry evidence: PASS, all 21 required screenshots including `00-round3-canonical-agent-workspace.png`.
- `npm run validate`: PASS. The successful run used a transient local Git excludes file only to keep pre-existing untracked `.codex/worktrees/**` outside repo-audit discovery; the file was deleted after the run and the worktrees were not modified.
- `npm run validate:public`: PASS as an exact subcommand of the successful full validation chain.
- Bounded post-execution evidence collection: target root, branch, starting HEAD, five core artifacts, and zero boundary findings were OBSERVED. Its remote/push fields are contractually `NOT_OBSERVED`, so the skill reports `PARTIALLY_UNOBSERVED` and does not produce governance approval or user acceptance.

The Electron fixture is development integration evidence only. Its result remains `NOT_FORMAL`, `PRE_ALPHA`, and `NOT_RUN`; it is not UAU or formal truth.
