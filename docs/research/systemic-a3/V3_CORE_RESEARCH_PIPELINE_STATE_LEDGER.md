# V3 Core Research Pipeline State Ledger

TASK_GOAL
: On existing PR #35 and branch `codex/systemic-a3-backtest-market-payload-closure-01`, close only `A3-MINT-01` so `FormalBacktestService.execute()` is the sole supported Formal Backtest result mint seam; preserve the accepted Strategy -> Portfolio -> Risk -> Research Backtest -> Result behavior, do not modify data quality, Model, Alpha, Desktop, or open R2/C2, and stop after bounded correction, tests, push, fresh exact-head CI, and the required report without merging PR #35.

TASK_PROGRESS
: `A3_MINT_01_LOCAL_CLOSED_CANDIDATE`; the public `FormalBacktestRunResult.create(...)` seam is removed, the normal constructor fails closed, the non-exported internal materializer is called only by `FormalBacktestService.execute()`, and exact Formal identity/content/wire compatibility is preserved. All required focused, layered, full-backend, compile/import, authority, public, Research smoke, and full validation gates pass locally. Commit, push, and fresh exact-head push/PR CI remain `NOT_RUN`.

PROJECT_AUTHORITY
: `P0_PROJECT_AUTHORITY 1.0.1`; normal task, `P0_AUTHORITY_AMENDMENT = NOT_AUTHORIZED`; protected files are read-only. Manifest hashes verified on exact CURRENT main:
  - `V3_PROJECT_CONSTITUTION.md = 63bfa526a607cf3e8f91667295a56377189ddf31d801bd9a4de8a4aa487e13f6`
  - `AGENTS.md = cbe7d78e2eccbfd5254fd08b30a0b145dc7c37b60aa5eadbbf4649b490f5b385`
  - `docs/architecture/V3_CANONICAL_ARCHITECTURE.md = f4184db8232c23b56d85fd4164e407277615bc2069e7f78268d4cc716bfb8037`
  - `docs/status/V3_CAPABILITY_LEVELS.md = e1ca59e408302c32e45390fc30372b19494351e8ebba58444504162a3ed6001d`
  - `npm.cmd run validate:authority = PASS` on exact CURRENT main `c5fb3b117c6466af3a19c12f65cfc8f7b5bd878c`.

TOOLING_AUTHORITY
: WorkflowGuard, skills, plugins, external registries, and `CURRENT_AUTHORITY.json` are `OPTIONAL_TOOLING / NON_AUTHORITATIVE`. `workflowguard-v3-preflight = NOT_APPLICABLE` because no explicit task-context JSON contract was supplied; no installation, repair, registry initialization, or governance inference is permitted.

## A3-MINT-01 execution checkpoint

- `CURRENT_PHASE = PRE_COMMIT_FINAL_REVIEW`
- `NEXT_EXACT_ACTION = commit the bounded four-path correction, push normally to the existing PR #35 branch, then wait for fresh push-event and PR-event CI bound to the resulting exact head`
- `CURRENT_MAIN = c5fb3b117c6466af3a19c12f65cfc8f7b5bd878c` (GitHub API exact ref; local commit object verified)
- `PR35_BRANCH = codex/systemic-a3-backtest-market-payload-closure-01`
- `PR35_ACCEPTED_HEAD = 79dcba91c69d9496e77f2b7706807d8ff130bc92`
- `PR35_PRE_CORRECTION_HEAD = 79dcba91c69d9496e77f2b7706807d8ff130bc92`
- `PR35_LOCAL_HEAD = 79dcba91c69d9496e77f2b7706807d8ff130bc92`
- `PR35_REMOTE_HEAD = 79dcba91c69d9496e77f2b7706807d8ff130bc92`
- `PR35_PR_HEAD = 79dcba91c69d9496e77f2b7706807d8ff130bc92`
- `PR35_MERGE_BASE = c5fb3b117c6466af3a19c12f65cfc8f7b5bd878c`
- `PR35_STATE = OPEN / CLEAN / MERGEABLE / UNMERGED`
- `PR35_CURRENT_CI = accepted-head push run 31773269919 SUCCESS and PR run 31773272478 SUCCESS; correction exact-head CI NOT_RUN`
- `P0/P1_STATE = VERIFIED_CURRENT`
- `A3_MINT_01_STATE = CLOSED CANDIDATE LOCALLY; remote delivery and exact-head CI NOT_RUN`
- `FORMAL_RESULT_PUBLIC_API_STATE = public create(...) ABSENT; normal constructor mint ABSENT; public export mint helper ABSENT`
- `FORMAL_SERVICE_MINT_STATE = sole supported Formal result mint seam; live execute resolves/builds/runs/evidences before invoking one module-private non-exported materializer`
- `FORMAL_RESULT_IDENTITY_BASELINE = formal_result_id fbtrr_sha256_f299aacc3689a20285d0143acaa848d96a690afe8c7a9b1f112a29eb5609bc03; content_sha256 f299aacc3689a20285d0143acaa848d96a690afe8c7a9b1f112a29eb5609bc03; full wire hash 80021e9a4b5ab9e4af4db1f93f9211079397b4b262763a46040e657845ee8782; exact before/after compatibility PASS`
- `CORE_RESEARCH_PIPELINE_BASELINE = RUNNABLE BACKEND CANDIDATE / REVIEW-ACCEPTED STATE; no current-task semantic change authorized`
- `RESEARCH_SMOKE_BASELINE = current correction local PASS; seven stages SUCCESS; PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE and RESEARCH_FREE_DATA_V1 unchanged`
- `DEFERRED_GAPS_LEDGER_STATE = CORE-PIPELINE-RUNTIME-DEFER-01 and CORE-PIPELINE-RUN-REGISTRY-DEFER-02 added as DEFERRED; all prior deferred entries remain DEFERRED; none resolved`
- `CHANGED_PATHS = apps/backend/src/v3_backend/domain/backtest_runtime/formal.py; apps/backend/tests/systemic_a3_backtest_payload/test_formal_backtest_payload.py; docs/research/systemic-a3/V3_CORE_RESEARCH_PIPELINE_STATE_LEDGER.md; docs/status/V3_DEFERRED_GAPS.md`
- `TESTS_ACTUALLY_RUN = A3 formal focused 21; P1 30; Data Truth 54; A1 34; A2 32; Portfolio owner 16; Portfolio core 32; Risk core 32; Risk Application 18; Backtest core 31; Artifact 36; Core Pipeline 3; smoke:research-pipeline; full backend; standalone compile/import; validate:authority; validate:public; npm.cmd run validate`
- `TEST_RESULTS_ACTUALLY_OBSERVED = every listed gate PASS; full validate exit 0; visual screenshot issue not reproduced; Research smoke SUCCESS with the same seven completed stages and restart-readable result Artifact`
- `PIPELINE_SMOKE_RUN_ID = rprun_sha256_6bf5a2ae3ec98cbf0001a5c96b8d445ee656067f3402eeca6ae622bdd15c3ad8`
- `PIPELINE_SMOKE_RESULT_ID = btrr_sha256_3a9093d476cb11529b5b82a288ac19774d0986fd78085b8ab9e630f4838eb20a`
- `PIPELINE_SMOKE_ARTIFACT_ID = art_sha256_4cd7fd0a6eaaabda9766e8c34ae9369a943d204ac9aa9c0e723d9c00e01a3957`
- `VALIDATE_AUTHORITY = PASS`
- `VALIDATE_PUBLIC = PASS`
- `FULL_VALIDATE = PASS`
- `VISUAL_EVIDENCE_DEFER_STATUS = DEFERRED; historical issue not reproduced; current full validate PASS`
- `CI_RUNS = baseline push 31773269919 SUCCESS; baseline PR 31773272478 SUCCESS; correction exact-head CI NOT_RUN`
- `NOT_RUN = correction commit; push; fresh exact-head push CI; fresh exact-head PR CI`
- `PENDING = remote delivery and fresh exact-head CI only`
- `BLOCKED = none`
- `OPTIONAL_TOOLING_STATUS = NOT_APPLICABLE`
- `RECOVERY_CONSISTENCY = PASS`

## Immutable task boundaries

- Preserve the existing Formal Backtest strict payload path and fail-closed behavior.
- Research results remain `PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE` and must expose assumption profile identity/codes.
- No P0, Model/PR #27, Alpha Mining/PR #30, Desktop/PR #29, deep Result Analytics, paid-source, broker/live, second engine, rebase, reset, force-push, new PR, or PR merge work.
- `DEFERRED/SKIPPED != RESOLVED`; `STRATEGY-PORTFOLIO-DEFER` remains deferred after runtime connection.
