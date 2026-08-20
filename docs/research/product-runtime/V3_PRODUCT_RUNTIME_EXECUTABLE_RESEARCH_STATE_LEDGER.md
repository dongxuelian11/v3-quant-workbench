# V3 PR #46 Desktop Typed Executable Research Acceptance Closure State Ledger

TASK_GOAL
: Execute `V3-PR46-DESKTOP-TYPED-EXECUTABLE-RESEARCH-ACCEPTANCE-CLOSURE-20260821-01` only as one bounded same-PR correction on PR #46 / `codex/product-runtime-executable-research-01`: prove EMPTY STORAGE -> real Desktop ProductBridge -> real BackendSupervisor/framed backend -> `ProductEntryService.v1.submitResearch` -> actual source bytes/provenance -> existing `CoreResearchPipelineService` -> canonical Task/Run/Result/Artifact -> ProductBridge and renderer-store typed readback -> shutdown/restart/reopen. Keep PR #46 OPEN / UNMERGED and stop for independent review.

TASK_PROGRESS
: LOCAL_ACCEPTANCE_PASS; full P0, original task prompt, prior Ledger, local Git, and fresh GitHub CURRENT were reread after compaction. Prior backend composition is preserved. The real Desktop ProductBridge/BackendSupervisor/framed-backend path, renderer-store typed readback, restart/reopen equality, bounded contract test, and source-unavailable fail-closed path pass from empty storage. Focused suites, full backend, and full local `npm run validate` pass. Exact FINAL_HEAD guards, commit/push, fresh exact-head CI, forward scan, and independent-review stop remain PENDING.

PROJECT_AUTHORITY
: P0 authority `1.0.2`; no explicit `P0_AUTHORITY_AMENDMENT` in the user request or attached task document. Protected files are read-only. Manifest-locked SHA-256 verified at admission: `V3_PROJECT_CONSTITUTION.md=92ff8049addd10c1ca7f6ca293007b254045f3f63bae53ddc626b761da5bd32b`, `AGENTS.md=cbe7d78e2eccbfd5254fd08b30a0b145dc7c37b60aa5eadbbf4649b490f5b385`, `docs/architecture/V3_CANONICAL_ARCHITECTURE.md=ca74dcd00d2d20ba106d962b2455254f8ee69807df09d20ff4984e20a362bc5b`, `docs/status/V3_CAPABILITY_LEVELS.md=79ca5210a33f283332884a9a4268e08a093ffe2d4ea33fe97d20672d355a9266`. Manifest self-hash at admission was recorded by the prior Ledger and will be recomputed on final head.

TOOLING_AUTHORITY
: The attached task document is task-scoped execution authority. `workflowguard-v3-preflight` and `workflowguard-v3-evidence` are `NOT_APPLICABLE` because no explicit task-context JSON contract was supplied; no synthetic contract will be invented. `clean-code-guard`, `test-guard`, and `docs-guard` are required on exact FINAL_HEAD and must report zero findings. GitHub CURRENT, P0, this Ledger, and actual test/build evidence outrank historical Ledger claims.

TASK_SCOPE_EXACT
: Existing PR #46 and branch only; bounded Desktop typed acceptance correction. Allowed: tests/smoke orchestration and minimal direct Desktop typed wiring if the real path exposes a small defect. Keep existing Product Entry backend composition, ASL, source authority ceiling, CoreResearchPipeline, Task/Run/Result/Artifact owners, and restart behavior.

FORBIDDEN_SCOPE_EXACT
: No backend Product Runtime redo; no new ASL operation/service; no new PR; no merge; no packaging/release/V1/Model/Agent/First Source Authority wave; no caller observations/bars/weights/raw bytes; no fake Product Entry authority, fixture fallback, second engine, shadow canonical objects, migration, dependency/lock graph, P0, CI workflow, or broad backend/domain semantic change.

## Admission and CURRENT

TASK_GOAL_EXACT
: `EMPTY STORAGE -> real ProductBridge -> real BackendSupervisor/framed backend -> submitResearch -> actual source bytes -> existing CoreResearchPipeline -> canonical Task/Run/Result/Artifact -> renderer store typed readback -> restart/reopen`, same PR only.

CURRENT_MAIN
: `2ee330f4d4967e4ecfbd58b1480753fd94e5fee3` (fresh GitHub API).

CURRENT_MAIN_TREE
: `2751ca39f06ad818cad502bb771457fd8876f79e` (fresh GitHub API).

PR_NUMBER
: `46`.

TASK_BRANCH
: `codex/product-runtime-executable-research-01`.

PRE_CORRECTION_HEAD
: `a86b8f824739ea9a11b20e3a1273712a0246d08b` (fresh GitHub API and local).

PRE_CORRECTION_TREE
: `481cae45ba6cfd4a1afeb9f19ce1417f94ea5704` (local exact `a86b8f824739ea9a11b20e3a1273712a0246d08b` tree; GitHub head commit matches).

MERGE_BASE
: `2ee330f4d4967e4ecfbd58b1480753fd94e5fee3` (local exact refs).

PR_STATE
: `OPEN / UNMERGED` before correction; `merged=false`, `closed_at=null` from fresh GitHub API.

PR_MERGEABILITY
: `clean` before correction from fresh GitHub API.

PR_HEAD_REMOTE
: `a86b8f824739ea9a11b20e3a1273712a0246d08b`; local `HEAD` and `origin/codex/product-runtime-executable-research-01` match.

PR_CI_BEFORE
: push run `32396624355=SUCCESS`; pull_request run `32396644582=SUCCESS`, both for pre-correction head only.

ACCEPTED_BACKEND_COMPOSITION
: `PRESERVE`: ProductEntry `submitResearch`, actual provider adapter bytes/hash/provenance, backend-only observations, existing CoreResearchPipeline and Strategy/Portfolio/Risk/Backtest owners, canonical Task/Run/Result/Artifact, and backend restart/reopen.

CONFIRMED_ACCEPTANCE_BLOCKER
: Current `smoke:product-research` runs only Node -> Python ProductRuntime/ProductEntry facade; it does not exercise real Desktop ProductBridge, BackendSupervisor/framed transport, or renderer store typed readback.

DESKTOP_TYPED_PATH_BEFORE
: `NO` / confirmed blocker.

BACKEND_SMOKE_BEFORE
: `PASS_REPORTED_PRIOR_LEDGER`; not treated as fresh evidence for this task.

DESKTOP_TYPED_E2E_BEFORE
: `NO`.

CHANGED_PATHS
: `apps/desktop/src/renderer/productRuntimeStore.ts`; `tests/ws_e_electron_runtime/product-bridge.test.mjs`; `scripts/product-research-smoke.mjs`; `docs/research/product-runtime/V3_PRODUCT_RUNTIME_EXECUTABLE_RESEARCH_STATE_LEDGER.md`.

COMPLETED_WORK
: Full attached task document read; P0 read/hash verified; fresh GitHub CURRENT recovery check; prior accepted backend composition inspected and preserved; real framed Desktop harness, renderer canonical readback wiring, bounded contract test, provider-boundary unavailable-path assertion, focused regressions, 982-test backend foundation, and full local validation completed successfully.

REMAINING_WORK
: Complete guard self-checks and Ledger closure fields; create normal same-branch correction commit; validate clean exact FINAL_HEAD; push the same branch; wait for fresh push/PR CI on that exact SHA; perform forward defect scan; stop for independent review.

BLOCKERS
: `NONE` at admission.

TESTS_ACTUALLY_RUN
: `npm run build=PASS`; `npm run smoke:product-research=PASS`; `npm run test:runtime=PASS (74/74)`; `npm test=PASS (123/123)`; `npm run smoke:product-entry=PASS`; `V3_PYTHON=python npm run smoke:product-runtime=PASS (69 checks)`; `npm run test:backend=PASS (37/37 suites, 62/62 files, 982 tests, one declared optional TA-Lib skip)`; `npm run validate=PASS` including authority, typecheck, lint, unit, backend, build/manifest, runtime, frontend, secret scan, repo audit, SBOM, Electron, and visual evidence. Exact clean FINAL_HEAD reruns remain `PENDING`.

RESULTS_ACTUALLY_OBSERVED
: `BACKEND_PRODUCT_RESEARCH_E2E=PASS`; `PRODUCTBRIDGE_REAL_BACKEND_INTEGRATION=PASS`; `RENDERER_STORE_REAL_TYPED_PATH=PASS`; `DESKTOP_TYPED_EXECUTABLE_RESEARCH_E2E=PASS_CANDIDATE`. Empty storage produced canonical `Task=tsk_YEZ64M3D2N2GDD2K4E4XZ6FJB4`, `Run=run_FPWG0SHX5H23D18FZ049M1N50M`, `Result=res_AR7SYZHJP13Q1BV3CZ1ZGMW7Z0`, result Artifact `art_sha256_c7b6f032f9ba7129754f835af5c4faeed1c0e86a4f49b036a0ab149d47780779`, and lineage Artifact `art_sha256_571bb2aefdd5d0e10595bfb71921ed6f209b0897fde6a94ae03b1ba3abd482e9`; new supervisor/bridge on the same storage reopened all exact IDs/hashes. Desktop caller carried only symbol/start/end. Source kind was `TEST_EXTERNAL_PROVIDER_BOUNDARY`. Unavailable source returned `INVALID_ARGUMENT` with no Task/Result/Artifact and transport remained READY.

FULL_VALIDATE_STATE
: `PASS` on the local correction candidate; exact clean FINAL_HEAD rerun is `PENDING`.

GUARD_STATE
: `PASS_CANDIDATE`; clean-code/test/docs self-checks are clean after one production error-message precedence fix and Ledger evidence refresh. Exact FINAL_HEAD confirmation remains `PENDING`.

CI_STATE
: `PENDING` for correction head; old CI is pre-correction only.

DEFERRED
: Real network free-source claim, First Source Authority broad wave, Formal Data Truth, Packaging, Release CI, V1 final acceptance, Model/Agent productization, async worker, checkpoint/resume.

NOT_RUN
: Exact clean FINAL_HEAD validation/guards, commit, push, fresh correction CI, and forward defect scan.

PENDING
: FINAL_HEAD/tree, exact-head guard evidence, push/PR CI, forward defect scan, final report, independent-review stop.

BLOCKED
: `NONE`.

EXACT_NEXT_ACTION
: Create the normal same-branch correction commit from the four allowed paths, then validate a clean exact FINAL_HEAD before push.

- Task document: `Downloads/V3_PR46_DESKTOP_TYPED_EXECUTABLE_RESEARCH_ACCEPTANCE_CLOSURE_20260821_V1_0.md`, read in full before this correction.
- Expected remote `main`: `2ee330f4d4967e4ecfbd58b1480753fd94e5fee3`.
- Expected `main` tree: `2751ca39f06ad818cad502bb771457fd8876f79e`.
- Fresh GitHub state at admission: PR #46 is open, mergeability `clean`, head and base match the exact values above; pre-correction push/PR CI succeeded.
- Isolated worktree: `.codex/worktrees/product-runtime-executable-research-01` under the repository root.
- The original root checkout was dirty on `codex/product-entry-v1-01`; its changes are user-owned and remain untouched.
- No reset, rebase, force push, direct-main write, automatic merge, packaging, release, V1 acceptance, Model/Agent work, or next-task work is authorized.

## First trace before edit

`ProductEntryService.v1.listBacktestRunSpecs` and `ProductEntryService.v1.importResearchPackage` are the only Product Entry operations in the admitted ASL. The current Product Runtime creates a durable Task/Run for the existing Backtest operation but reconstructs a stored RunSpec and calls the existing deterministic Backtest engine directly. There is no Product Entry research operation, no provider/source resolver in the product lifecycle, no backend-only construction of `ResearchSessionObservation`, no connection from Product Runtime to `CoreResearchPipelineService`, and no Desktop research submission/readback path.

FIRST_MISSING_EDGE
: `Product Entry project-bound research admission -> canonical source/provider resolution -> verified actual bytes -> backend-internal observations -> CoreResearchPipelineService`. The first contract-level missing edge is the single allowed `ProductEntryService.v1.submitResearch` operation; the first runtime-level missing edge is the bounded source-admission/composition bridge into the existing core pipeline.

## Frozen boundaries

- Exact admitted ASL is 18 services / 66 operations. The target is 18 services / 67 operations, with the original 17-service / 64-operation subset and both existing Product Entry operations unchanged.
- The new request must not accept `observations`, `ResearchSessionObservation`, bars/OHLCV, returns, weights, factor values, signals, metrics, reviewer evidence, precomputed results, or caller-built BacktestRunSpec.
- Only canonical project/context/profile/provider/source/snapshot/strategy/portfolio/risk/rule/cost/timing references and bounded non-market research intent may cross the Product Entry boundary.
- No second research engine, fixture fallback, migration, P0 edit, broad First Source Authority expansion, PIT/paid-data/Formal Market State work, or fake progress/cancel/resume is permitted.
- Product maturity ceiling is `PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE` / `PRODUCT_CONNECTED_CANDIDATE`; never `FORMAL` or `PRODUCTION_AVAILABLE`.

## Required evidence state

- `workflowguard-v3-preflight`: `NOT_APPLICABLE` (no explicit task context JSON).
- `workflowguard-v3-evidence`: `NOT_APPLICABLE` unless a real explicit execution context is supplied later.
- ASL contract and frozen-subset tests: `PASS`.
- Closed DTO and project-bound/idempotency tests: `PASS`.
- Source actual-bytes/hash/provenance tests SRC1-SRC5: `PASS` at the bounded Product Entry source boundary.
- Existing CoreResearchPipelineService integration tests: `PASS`.
- Desktop bridge/store/panel regressions: `PASS`.
- Clean-start empty-storage smoke and restart/reopen: `PASS` for the new executable research path.
- `npm run validate:authority`: `PASS`.
- `npm run validate:public`: `PASS`.
- `npm run validate`: `PASS`.
- Clean-code/test/docs guards on exact FINAL_HEAD: `NOT_RUN`.
- GitHub push, one PR, fresh exact-head PR CI: `NOT_RUN`.

## Change boundary

Allowed implementation area is limited to Product Entry contracts/registry, backend product research composition and existing runtime facades/lifecycle, the typed Desktop bridge/store/panel path, bounded tests/scripts, and exact status documentation facts. Any need to edit P0 authority, migrations, dependency manifests/lockfiles, CI/installer/release files, semantic Data Truth doctrine, or the existing core pipeline API is `STOP_FOR_REVIEW`.

## Closure state

FINAL_HEAD: `PENDING`
PR: `PENDING / OPEN / UNMERGED`
STOP_STATE: `PENDING_STOP_FOR_INDEPENDENT_REVIEW`
RESULT: `PENDING`

## Required final report fields

RESULT
: `PENDING` until exact FINAL_HEAD, one OPEN/UNMERGED PR, fresh CI, and the independent-review stop are complete.

REPOSITORY
: `V3OpenSource`

BASE_MAIN_SHA
: `2ee330f4d4967e4ecfbd58b1480753fd94e5fee3`

BASE_MAIN_TREE
: `2751ca39f06ad818cad502bb771457fd8876f79e`

TASK_BRANCH
: `codex/product-runtime-executable-research-01`

FINAL_HEAD_SHA
: `PENDING`

FINAL_TREE_SHA
: `PENDING`

PR_NUMBER
: `PENDING`

PR_STATE
: `PENDING / OPEN / UNMERGED`

PR_HEAD
: `PENDING`

MERGE_BASE
: `2ee330f4d4967e4ecfbd58b1480753fd94e5fee3`

PR_MERGEABILITY
: `PENDING`

LOCAL_REMOTE_PR_MATCH
: `PENDING`

WORKTREE
: `.codex/worktrees/product-runtime-executable-research-01` under the repository root.

P0_AUTHORITY
: Version `1.0.2`; no amendment authorization; protected files unchanged.

P0_HASH_STATE
: `PASS` at admission and after implementation; final exact-head recomputation `PENDING`.

NEXT_WAVE
: `STOP_FOR_INDEPENDENT_REVIEW`; no Packaging, Release CI, V1 acceptance, First Source Authority broad wave, Model, Agent, or next task.

ASL_OPERATION_PLACEMENT
: `ProductEntryService.v1`.

ASL_OPERATION_ID
: `ProductEntryService.v1.submitResearch`.

ASL_SERVICE_COUNT_BEFORE
: `18`.

ASL_OPERATION_COUNT_BEFORE
: `66`.

ASL_SERVICE_COUNT_AFTER
: `18`.

ASL_OPERATION_COUNT_AFTER
: `67`.

FROZEN_REGISTRY_SUBSET_PRESERVED
: `PASS`; original 17-service/64-operation subset and both prior Product Entry operations remain unchanged.

PRODUCT_RESEARCH_REQUEST_SHAPE
: Closed project-bound DTO: request/project/context/profile/idempotency plus provider/source refs and symbol/date intent; no caller numeric payload.

CALLER_OBSERVATIONS_AUTHORITY
: `FORBIDDEN`; unknown `observations` and downstream numeric fields are rejected.

CALLER_NUMERIC_MARKET_TRUTH
: `FORBIDDEN`; bars, OHLCV, returns, weights, factor values, signals, metrics, and precomputed results do not cross the Product Entry boundary.

CALLER_RUN_SPEC_AUTHORITY
: `FORBIDDEN`; caller cannot provide a BacktestRunSpec or downstream owner payload.

RESEARCH_PROFILE
: `RESEARCH_FREE_DATA_V1`; strategy profile `RESEARCH_CLOSE_RANK_TOP1_V1`.

RESEARCH_MATURITY
: `PRODUCT_CONNECTED_CANDIDATE`; classification `PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE`; truth `DEMO`, admission `PRE_ALPHA`.

SOURCE_ADMISSION_PATH
: Narrow persisted provider/connector/version/capability/admission binding through the existing Data Truth registry; no PIT, paid-data, or Formal Market State expansion.

SOURCE_PROVIDER_PATH
: `pvd_akshare_eastmoney_a_share_eod_v1` via connector `cov_akshare_eod_research_v1`.

SOURCE_CANONICAL_REFERENCE
: `CN_A_SHARE_EOD`, frequency `P1D`, closed six-digit symbol and bounded `YYYYMMDD` date range.

SOURCE_ACTUAL_BYTE_RESOLUTION
: Existing `AkshareAShareEodAdapter` resolves provider output; backend publishes and independently re-reads raw capture, normalized snapshot, calendar, partition, and lineage bytes.

SOURCE_SHA256_VERIFICATION
: `PASS`; raw capture, source snapshot, result, and lineage identities are independently rehashed before acceptance/reference.

SOURCE_PROVENANCE
: Provider/source refs -> raw capture -> normalized snapshot/calendar/partition -> observed universe/strategy signal -> internal observations -> CoreResearchPipeline -> result/lineage Artifact.

SOURCE_UNAVAILABLE_BEHAVIOR
: Typed fail-closed provider/source admission or execution error; no fixture fallback and no fabricated source bytes.

TEST_SOURCE_BOUNDARY
: `TEST_EXTERNAL_PROVIDER_BOUNDARY`; injected provider exists only at the provider adapter boundary in offline tests/smokes.

REAL_FREE_SOURCE_SMOKE
: `NOT_RUN`; no network-dependent free-provider claim is promoted by this wave.

RESEARCH_OBSERVATION_CONSTRUCTION
: `PASS`; `ResearchSessionObservation` is constructed only inside backend composition from actual normalized provider records.

CORE_RESEARCH_PIPELINE_REUSE
: `PASS`; existing `CoreResearchPipelineService` and existing Strategy/Portfolio/Risk/Backtest owners are reused.

SECOND_RESEARCH_ENGINE
: `NONE`; no second engine or fixture fallback introduced.

TASK_IDEMPOTENCY
: `PASS`; durable idempotency is project-bound, exact-request conflict fails closed, and restart replay returns the same Task/Run without a new cursor.

TASK_ID
: `tsk_P0HFNMWH0N00F0H4Y48W3F77KM` from the latest real Desktop clean-start research smoke.

RUN_ID
: `run_SEQXJ845791F1C7E4KXKJMFFWR` from the latest real Desktop clean-start research smoke.

PIPELINE_RUN_RELATION
: Product canonical Run is the active reference for the existing pipeline output; lineage records bind the core pipeline run/result to the Product Task/Run.

RESULT_RELATION
: Canonical Result is project/context/task/run bound and points to the registered result Artifact.

RESULT_ID
: `res_XV0KXVRNMS4TX78A69P0D896K4`.

RESULT_ARTIFACT_ID
: `art_sha256_c7b6f032f9ba7129754f835af5c4faeed1c0e86a4f49b036a0ab149d47780779`.

RESULT_ARTIFACT_SHA256
: `c7b6f032f9ba7129754f835af5c4faeed1c0e86a4f49b036a0ab149d47780779`.

LINEAGE_ARTIFACT_ID
: `art_sha256_d5876fc20f78ef57486e11270856fa83270a9adc6bf40cda38cdacc9fecb3bbb`; ProductBridge descriptor role `RESEARCH_PIPELINE_LINEAGE` and SHA identity verified.

RESTART_REOPEN
: `PASS`; after shutdown, new `BackendSupervisor B` and `ProductBridge B` reopened/rebound the same storage and renderer refresh reacquired the exact Task/Run/Result/result Artifact/lineage Artifact IDs and hashes.

PRODUCT_ENTRY_FACADE
: `PASS`; closed `submitResearch` facade delegates to ProductExecution and returns the bounded accepted read model.

PRODUCT_RUNTIME_COMPOSITION
: `PASS`; ProductResearchService is a composition boundary only and delegates execution to existing canonical owners.

TASK_SERVICE_CAPABILITY
: Existing TaskService remains honest; canonical Product Entry research Task lifecycle is persisted and queryable.

RESULT_SERVICE_CAPABILITY
: Existing ResultService remains honest; canonical Product Entry research Result/Artifact is queryable and restart-readable.

RESEARCH_SERVICE_CAPABILITY
: Generic ResearchService capability remains `UNAVAILABLE` on the normal service matrix; the bounded Product Entry operation is explicitly `PRODUCT_CONNECTED_CANDIDATE` and does not inflate generic capability.

DESKTOP_BRIDGE
: `PASS`; main-owned source refs/idempotency and typed response adapter; renderer receives only symbol/date intent.

DESKTOP_STORE
: `PASS`; submit then Task/Result/Artifact query, explicit PRE_ALPHA state, and restart-safe read path.

DESKTOP_PANEL
: `PASS`; Chinese-first bounded research entry with visible DEMO/PRE_ALPHA/RESEARCH_ONLY/PRODUCT_CONNECTED_CANDIDATE state.

DESKTOP_CALLER_DATA_BOUNDARY
: `PASS`; renderer/preload IPC accepts only symbol/date intent and rejects numeric/observation drift.

CLEAN_START_PROJECT_ENTRY
: `PASS` via existing `smoke:product-entry`.

CLEAN_START_EXECUTABLE_RESEARCH
: `PASS_CANDIDATE` via `smoke:product-research` on empty Product Runtime storage.

PRODUCT_CONNECTED
: `PRODUCT_CONNECTED_CANDIDATE` only; not Formal or Production Available.

ASL_CONTRACT_TESTS
: `PASS`; frozen subset and new 67-operation registry/fixture tests.

SOURCE_ADMISSION_TESTS
: `PASS`; provider boundary, actual-byte hash, provenance, unavailable, and caller-truth rejection tests.

PIPELINE_REUSE_TESTS
: `PASS`; existing CoreResearchPipeline integration and product composition tests.

TASK_RUN_TESTS
: `PASS`; canonical lifecycle, idempotency, conflict, and restart tests.

RESULT_ARTIFACT_TESTS
: `PASS`; result Artifact catalog registration, exact bytes, hash, and relation tests.

RESTART_TESTS
: `PASS`; Product Runtime, Electron runtime, B3, and clean research smoke reopen paths.

DESKTOP_BRIDGE_TESTS
: `PASS`; typed bridge contract regression and real bridge/backend integration included in 123 unit tests, 74 runtime tests, and `smoke:product-research`.

DESKTOP_STORE_TESTS
: `PASS`; real ProductBridge-backed renderer store submit/readback/restart refresh behavior covered by `smoke:product-research`.

DESKTOP_PANEL_TESTS
: `PASS`; panel state and boundary behavior covered by frontend/runtime regression suite.

CLEAN_START_PRODUCT_SMOKE
: `PASS`; `npm run smoke:product-research`.

PRODUCT_RUNTIME_SMOKE
: `PASS`; 69 checks with `V3_PYTHON=python` on Windows.

PRODUCT_ENTRY_SMOKE
: `PASS`; clean-start project entry remained honest and target canonical reuse passed.

WINDOWS_ELECTRON_B3_SMOKE
: `PASS`; LIVE bind, canonical RunSpec execution, Task/Result/Artifact reads, shutdown/restart recovery.

ELECTRON_SMOKE
: `PASS`.

VISUAL_EVIDENCE_SMOKE
: `PASS`; 27 real-Electron states and layout/security assertions.

BACKEND_FOCUSED_TESTS
: `PASS`; Product Entry/Product Runtime/WS-A focused tests plus new research tests.

FULL_BACKEND
: `PASS`; 37/37 suites, 62/62 discovered files, 982 test cases.

RUNTIME_TESTS
: `PASS`; 74/74.

UNIT_TESTS
: `PASS`; 123/123.

VALIDATE_AUTHORITY
: `PASS`.

VALIDATE_PUBLIC
: `PASS`.

FULL_VALIDATE
: `PASS`; final local run completed authority, typecheck, lint, unit/backend/runtime/build/smoke/secret/repo/SBOM and Electron/visual stages.

FULL_VALIDATE_ENVIRONMENT_NOTE
: Electron 39.8.10 binary was restored from its existing cached locked archive into ignored `node_modules`; Windows Product Runtime smoke requires `V3_PYTHON=python`. No source, package, or lockfile change was made for this environment repair.

BUILD_MANIFEST
: `PASS` locally; exact-clean-head manifest verification is `PENDING` until final commit/worktree.

GIT_DIFF_CHECK
: `PASS`; four-path bounded write set only. Rerun after this Ledger update and on exact FINAL_HEAD.

DEFERRED_GAPS_UPDATED
: `PASS`; this Ledger records the bounded wave status and preserves deferred gaps.

DEFERRED_GAPS_PRESERVED
: `PASS`; First Source Authority broad work, strict PIT, paid data, Formal Market State, async worker, checkpoint/resume, Model/Agent, Packaging, and Release CI remain deferred.

CURRENT_STATUS_UPDATE
: Implementation, local full validation, and candidate guards complete; normal same-branch commit, exact FINAL_HEAD validation/guards, push, fresh CI, forward defect scan, and stop report remain pending.

GUARD_SKILLS_AVAILABLE
: `clean-code-guard`, `test-guard`, `docs-guard` read and available.

GUARD_SKILLS_TARGET_SHA
: `PENDING` until FINAL_HEAD is committed.

GUARD_SKILLS_SCOPE
: All changed paths plus Product Entry/ASL, Product Runtime composition, provider/source boundary, CoreResearchPipeline boundary, Task/Run/Result/Artifact, and Desktop bridge/store/panel.

CLEAN_CODE_GUARD
: `PASS_CANDIDATE`; one finding fixed in `productRuntimeStore.refresh` (typed readback errors were being cleared by a later spread), zero findings flagged for author.

TEST_GUARD
: `PASS_CANDIDATE`; the ProductBridge contract test asserts an observable closed boundary at the supervisor/framed transport seam, while the primary smoke uses real ProductBridge/Supervisor/backend and empty durable storage. Zero findings flagged.

DOCS_GUARD
: `PASS_CANDIDATE`; current symbols/commands/results were verified against source and actual runs; stale pre-acceptance IDs and the runtime count were corrected. Zero findings flagged.

GUARD_SKILLS_CODE_GATE
: `PASS_CANDIDATE`; exact FINAL_HEAD rerun remains `PENDING`.

GUARD_SKILLS_FINDINGS
: `clean-code-guard: 1 fixed, 0 flagged for author`; `test-guard: clean`; `docs-guard: stale evidence refreshed, 0 flagged for author`.

PUSH_CI
: `PENDING`.

PR_CI
: `PENDING`.

EXACT_HEAD_CI_STATUS
: `PENDING`.

CI_FULL_VALIDATE_SCOPE
: `PENDING`; distinguish exact workflow CI scope from local full validate.

FULL_VALIDATE_EVIDENCE_SOURCE
: Local exact worktree `npm run validate` result; exact FINAL_HEAD rerun remains pending.

FORWARD_DEFECT_SCAN
: `PENDING`.

CONFIRMED_BLOCKERS
: `PENDING`.

DEFERRED_NON_BLOCKING
: Packaging/clean-machine, Release CI, V1 acceptance, broad First Source Authority, Model/Agent, async worker, and checkpoint/resume are outside this wave.

NOT_A_DEFECT
: The explicit `DEMO / PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE` result is not a capability or maturity defect.

FIRST_SOURCE_AUTHORITY
: `NOT_REISSUED`.

DATA_TRUTH_FORMAL_STATUS
: `NOT_AVAILABLE`.

MODEL_PRODUCTIZATION_STATUS
: `NOT_RUN / LATER`.

AGENT_PRODUCTIZATION_STATUS
: `NOT_RUN / LATER`.

ASYNC_WORKER_STATUS
: `NOT_RUN / DEFERRED`.

CHECKPOINT_RESUME_STATUS
: `UNAVAILABLE / DEFERRED`.

PACKAGING_STATUS
: `NOT_RUN / LATER`.

RELEASE_CI_STATUS
: `NOT_RUN / LATER`.

PRODUCT_RUNTIME_EXECUTABLE_RESEARCH_STATUS
: `DESKTOP_TYPED_ACCEPTANCE_IMPLEMENTED / LOCAL_FULL_VALIDATION_PASS / FINAL_EXACT_HEAD_CLOSURE_PENDING`.

SUCCESS_MATURITY
: `CLEAN_START_EXECUTABLE_RESEARCH = PASS_CANDIDATE`; `DESKTOP_TYPED_EXECUTABLE_RESEARCH_E2E = PASS_CANDIDATE`; `PRODUCT_RUNTIME_EXECUTABLE_RESEARCH = PRODUCT_CONNECTED_CANDIDATE`; `RESEARCH = DEMO / PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE`.

TRACKED_P0_EDITS
: `NONE`.

MIGRATION_CHANGE
: `NONE`.

DEPENDENCY_CHANGE
: `NONE`; ignored local dependencies were installed from the existing lockfile only.

PACKAGE_LOCK_CHANGE
: `NONE`.

NOT_RUN
: Real network free-source smoke, final exact-head guards, push/PR/CI, forward defect scan, Packaging, Release CI, V1 acceptance, Model/Agent productization, async worker, and checkpoint/resume.

PENDING
: FINAL_HEAD, FINAL_TREE_SHA, PR correction state, guard results, push, fresh exact-head CI, forward scan, final RESULT, and STOP_FOR_INDEPENDENT_REVIEW.

BLOCKED
: `NONE`.

RECOVERED_TASK_GOAL
: Preserve the accepted PR #46 backend composition and close only the missing empty-storage Desktop typed ProductBridge/BackendSupervisor/renderer-store/restart acceptance path on the same PR, then leave it OPEN / UNMERGED for independent review.

RECOVERED_TASK_PROGRESS
: Bounded implementation is committed locally at `8e4bfa63941205399cd51085d82aa6c3a22cdda6`; clean detached exact-head `npm run validate` passed with `BuildManifest=CLEAN`, 74/74 runtime tests, Electron smoke PASS, and visual evidence PASS. The visual smoke regenerated 11 tracked screenshots in the detached validation worktree; those generated differences are pending exact restoration before the final clean guard.

RECOVERED_CURRENT_MAIN
: GitHub CURRENT remains `2ee330f4d4967e4ecfbd58b1480753fd94e5fee3`, tree `2751ca39f06ad818cad502bb771457fd8876f79e`; no main drift.

RECOVERED_HEAD
: Local branch/detached candidate `8e4bfa63941205399cd51085d82aa6c3a22cdda6`, tree `4b0b405a406d2d1a911b0560f70e13ec9ea63d8b`; remote branch and PR head remain the authorized pre-correction `a86b8f824739ea9a11b20e3a1273712a0246d08b` until the normal push.

RECOVERED_PENDING
: Commit this recovery-only Ledger update; validate the resulting clean exact FINAL_HEAD; rerun the real Desktop research smoke and exact guards; restore any generated screenshot differences; normal same-branch push; fresh push and pull_request CI; forward defect scan; final OPEN / UNMERGED reconciliation.

RECOVERED_NEXT_ACTION
: Create the normal recovery-only Ledger commit on `codex/product-runtime-executable-research-01`, then construct a clean detached worktree for that new exact head and rerun the required exact-head gates before push.

RECOVERY_CONSISTENCY
: `PASS`; the complete original task prompt, all P0 authority files, current Ledger, exact changed source/tests/scripts, local Git, and fresh GitHub CURRENT were reread after compaction. P0 hashes remain exact, main and remote PR head did not drift, PR #46 remains `OPEN / UNMERGED / CLEAN`, the local correction ancestry and four-path write set match the persisted task, and no authority or scope inconsistency was found.
