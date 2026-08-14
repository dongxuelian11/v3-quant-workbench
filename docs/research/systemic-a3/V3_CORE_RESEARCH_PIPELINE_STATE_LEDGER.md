# V3 Core Research Pipeline State Ledger

TASK_GOAL
: On existing PR #35 and branch `codex/systemic-a3-backtest-market-payload-closure-01`, ordinary-merge exact GitHub CURRENT main, then make the bounded backend research chain Strategy -> Portfolio -> TargetWeight -> Risk -> RiskAdjustedWeight -> Research Backtest -> Result runnable without weakening the retained Formal Backtest fail-closed path.

TASK_PROGRESS
: `FINAL_LEDGER_CHECKPOINT_READY_FOR_DELIVERY`; exact CURRENT main ordinary-merged; existing owners audited and composed; explicit Research assumption profile, Research Backtest assembler, unified pipeline service, stage failures, integration tests, one-command smoke, and Deferred Gaps Ledger implemented. Focused regression, full backend, compile/import, `validate:public`, and full `validate` all passed. The implementation and first ledger checkpoint were pushed to the original PR #35 branch, PR metadata was updated, and both push-event and PR-event CI were started on exact head `c1f481dc802ce631d6833ce44bab01fe2772a409`; the PR-event CI completed successfully. This final ledger-only checkpoint must now be committed, pushed, and verified by fresh exact-head CI.

PROJECT_AUTHORITY
: `P0_PROJECT_AUTHORITY 1.0.1`; normal task, `P0_AUTHORITY_AMENDMENT = NOT_AUTHORIZED`; protected files are read-only. Manifest hashes verified on exact CURRENT main:
  - `V3_PROJECT_CONSTITUTION.md = 63bfa526a607cf3e8f91667295a56377189ddf31d801bd9a4de8a4aa487e13f6`
  - `AGENTS.md = cbe7d78e2eccbfd5254fd08b30a0b145dc7c37b60aa5eadbbf4649b490f5b385`
  - `docs/architecture/V3_CANONICAL_ARCHITECTURE.md = f4184db8232c23b56d85fd4164e407277615bc2069e7f78268d4cc716bfb8037`
  - `docs/status/V3_CAPABILITY_LEVELS.md = e1ca59e408302c32e45390fc30372b19494351e8ebba58444504162a3ed6001d`
  - `npm.cmd run validate:authority = PASS` on exact CURRENT main `c5fb3b117c6466af3a19c12f65cfc8f7b5bd878c`.

TOOLING_AUTHORITY
: WorkflowGuard, skills, plugins, external registries, and `CURRENT_AUTHORITY.json` are `OPTIONAL_TOOLING / NON_AUTHORITATIVE`. `workflowguard-v3-preflight = NOT_APPLICABLE` because no explicit task-context JSON contract was supplied; no installation, repair, registry initialization, or governance inference is permitted.

## Execution checkpoint

- `CURRENT_PHASE = FINAL_LEDGER_CHECKPOINT_BEFORE_EXACT_HEAD_CI`
- `NEXT_EXACT_ACTION = commit and push this final ledger-only checkpoint to the existing PR #35 branch, then wait for fresh CI on that resulting exact head and stop without merging`
- `CURRENT_MAIN = c5fb3b117c6466af3a19c12f65cfc8f7b5bd878c` (GitHub API exact ref; local commit object verified)
- `PR35_BRANCH = codex/systemic-a3-backtest-market-payload-closure-01`
- `PR35_PRE_TASK_HEAD = 862e0a1936c42cd70ab234324c79946d34fde490`
- `PR35_LOCAL_HEAD = c1f481dc802ce631d6833ce44bab01fe2772a409 before this final ledger-only checkpoint commit`
- `PR35_REMOTE_HEAD = c1f481dc802ce631d6833ce44bab01fe2772a409`
- `PR35_PR_HEAD = c1f481dc802ce631d6833ce44bab01fe2772a409`
- `PR35_MERGE_BASE = c5fb3b117c6466af3a19c12f65cfc8f7b5bd878c`
- `PR35_STATE = OPEN`
- `PR35_CURRENT_CI = exact-head c1f481dc802ce631d6833ce44bab01fe2772a409 PR-event CI SUCCESS; final ledger-only checkpoint CI PENDING`
- `CURRENT_MAIN_FETCH_STATE = FAILED_TRANSIENT_EMPTY_REPLY; exact GitHub ref and local object independently available`
- `P0/P1_STATE = VERIFIED_CURRENT`
- `DATA_TRUTH_STATE = CURRENT_MAIN_ACCEPTED_BASELINE; bounded composition audit PASS`
- `A1_STATE = CURRENT_MAIN_ACCEPTED_BASELINE; bounded composition audit PASS`
- `A2_STATE = CURRENT_MAIN_ACCEPTED_BASELINE; FormalStrategyEvaluationService composition PASS`
- `PORTFOLIO_OWNER_STATE = CURRENT_MAIN_ACCEPTED_BASELINE; CanonicalPortfolioOwnerService composition PASS`
- `RISK_POLICY_OWNER_STATE = CURRENT_MAIN_ACCEPTED_BASELINE; canonical identity reuse PASS`
- `RISK_APPLICATION_STATE = CURRENT_MAIN_ACCEPTED_BASELINE; CanonicalRiskApplicationService composition PASS`
- `MAIN_SYNC_STATE = PASS; ordinary merge commit 56c175689e7dca3c4a9293f939a2f54bf7837792`
- `MAIN_SYNC_PARENTS = 862e0a1936c42cd70ab234324c79946d34fde490 c5fb3b117c6466af3a19c12f65cfc8f7b5bd878c`
- `MAIN_SYNC_TREE = 2c14e5392e637e1d048c722ded38a70b5af26731`
- `FEATURE_COMMIT = 4a948e65b46d68d3e956e5549aa336b958182941`
- `FEATURE_TREE = c0f8e4587dbf9113852876605719e0a521a81435`
- `CONFLICT_PATHS = scripts/backend-foundation-test.mjs`
- `CONFLICT_RESOLUTIONS = additive suite union retaining systemic_a3_backtest_payload and CURRENT main systemic_a1_payload_closure plus all accepted A2/Portfolio/Risk/Data Truth suites`
- `RESEARCH_PIPELINE_STATE = RUNNABLE BACKEND CANDIDATE LOCALLY VALIDATED; exact-head c1f481dc802ce631d6833ce44bab01fe2772a409 PR-event CI PASS; final ledger-only checkpoint CI PENDING`
- `STRATEGY_STAGE = PASS in focused integration; FormalStrategyEvaluationService produced live Signal/Selection/PortfolioIntent`
- `PORTFOLIO_STAGE = PASS in focused integration; same live PortfolioIntent produced and published TargetWeight`
- `RISK_STAGE = PASS in focused integration; canonical owner IDs produced Risk receipt and adjusted vector`
- `BACKTEST_STAGE = PASS in focused integration; Research assembler invoked existing DeterministicAshareBacktestEngine`
- `RESULT_STAGE = PASS in focused integration; result envelope content-addressed and restart-readable`
- `PIPELINE_SMOKE_STATE = PASS; npm.cmd run smoke:research-pipeline exit 0/status SUCCESS`
- `DEFERRED_GAPS_LEDGER_STATE = PERSISTED; all required gaps DEFERRED; none RESOLVED`
- `TESTS_ACTUALLY_RUN = validate:authority; focused A2 32 + Portfolio owner 16 + Risk Application 18 + Formal Backtest 18 + Backtest core 31 + Artifact 36 + core pipeline 3; npm.cmd run test:backend; standalone compile/import; npm.cmd run smoke:research-pipeline; npm.cmd run validate:public; npm.cmd run validate`
- `TEST_RESULTS_ACTUALLY_OBSERVED = every listed gate PASS; full validate exit 0; smoke SUCCESS with seven completed stages and restart-readable result Artifact`
- `PIPELINE_SMOKE_RUN_ID = rprun_sha256_6bf5a2ae3ec98cbf0001a5c96b8d445ee656067f3402eeca6ae622bdd15c3ad8`
- `PIPELINE_SMOKE_RESULT_ID = btrr_sha256_3a9093d476cb11529b5b82a288ac19774d0986fd78085b8ab9e630f4838eb20a`
- `PIPELINE_SMOKE_ARTIFACT_ID = art_sha256_4cd7fd0a6eaaabda9766e8c34ae9369a943d204ac9aa9c0e723d9c00e01a3957`
- `VALIDATE_PUBLIC = PASS`
- `FULL_VALIDATE = PASS`
- `VISUAL_EVIDENCE_DEFER_STATUS = DEFERRED; historical issue not reproduced; current full validate PASS`
- `CI_RUNS = push-event run 31773065339 and PR-event run 31773067525 bind exact head c1f481dc802ce631d6833ce44bab01fe2772a409; PR-event run 31773067525 SUCCESS`
- `NOT_RUN = final ledger-only checkpoint push and its fresh exact-head CI`
- `PENDING = final ledger-only checkpoint remote delivery and CI`
- `BLOCKED = none`
- `OPTIONAL_TOOLING_STATUS = NOT_APPLICABLE`
- `RECOVERY_CONSISTENCY = PASS`

## Immutable task boundaries

- Preserve the existing Formal Backtest strict payload path and fail-closed behavior.
- Research results remain `PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE` and must expose assumption profile identity/codes.
- No P0, Model/PR #27, Alpha Mining/PR #30, Desktop/PR #29, deep Result Analytics, paid-source, broker/live, second engine, rebase, reset, force-push, new PR, or PR merge work.
- `DEFERRED/SKIPPED != RESOLVED`; `STRATEGY-PORTFOLIO-DEFER` remains deferred after runtime connection.
