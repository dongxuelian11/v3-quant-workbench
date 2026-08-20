# V3 Product Runtime Executable Research State Ledger

TASK_GOAL
: Execute task `V3-PRODUCT-RUNTIME-EXECUTABLE-RESEARCH-20260820-01` from the exact GitHub CURRENT and deliver one bounded, project-bound `ProductEntryService.v1.submitResearch` operation. The product path must resolve canonical provider/source references to verified actual source bytes, construct `ResearchSessionObservation` only inside the backend, reuse `CoreResearchPipelineService` and its existing Strategy/Portfolio/Risk/Backtest owners, persist one canonical Task/Run/Result/Artifact lineage, expose typed Desktop query and restart/reopen behavior, and remain `PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE`.

TASK_PROGRESS
: ADMITTED; exact-main worktree created; authority and CURRENT verified; first trace recorded; implementation complete; clean-start smokes, regressions, and full local validation PASS; guard fixes and focused rechecks PASS; final exact-head validation/guard, GitHub delivery, CI, and independent-review stop remain PENDING.

PROJECT_AUTHORITY
: P0 authority version `1.0.2`; no `P0_AUTHORITY_AMENDMENT` is present in the user request or attached task document. Protected authority files are read-only for this task. Locked-file SHA-256 values verified against `docs/status/V3_PROJECT_AUTHORITY_MANIFEST.json` before implementation: `V3_PROJECT_CONSTITUTION.md=92ff8049addd10c1ca7f6ca293007b254045f3f63bae53ddc626b761da5bd32b`, `AGENTS.md=cbe7d78e2eccbfd5254fd08b30a0b145dc7c37b60aa5eadbbf4649b490f5b385`, `docs/architecture/V3_CANONICAL_ARCHITECTURE.md=ca74dcd00d2d20ba106d962b2455254f8ee69807df09d20ff4984e20a362bc5b`, `docs/status/V3_CAPABILITY_LEVELS.md=79ca5210a33f283332884a9a4268e08a093ffe2d4ea33fe97d20672d355a9266`, manifest self-hash `3306f51f4d9b26577f092d53e3a5cdb319619e9e9a75c0b90203c87bd21c425a`.

TOOLING_AUTHORITY
: The attached V3 task document is the task-scoped execution authority. WorkflowGuard preflight/evidence are `NOT_APPLICABLE` because no explicit task-context JSON contract was provided; no synthetic context will be invented. Clean-code, test, and docs guards are required on exact FINAL_HEAD and must each report zero findings. GitHub CURRENT, repository P0 authority, this Ledger, and real test/build evidence outrank optional or missing tooling inputs.

## Admission and CURRENT

- Task document: `Downloads/V3_PRODUCT_RUNTIME_EXECUTABLE_RESEARCH_20260820_V1_0.md`, read in full before work.
- Expected remote `main`: `2ee330f4d4967e4ecfbd58b1480753fd94e5fee3`.
- Expected `main` tree: `2751ca39f06ad818cad502bb771457fd8876f79e`.
- Fresh GitHub state at admission: open PR count `0`; main push CI for `2ee330f4d4967e4ecfbd58b1480753fd94e5fee3` succeeded.
- Working branch: `codex/product-runtime-executable-research-01`.
- Isolated worktree: `.codex/worktrees/product-runtime-executable-research-01` under the repository root.
- Exact starting HEAD: `2ee330f4d4967e4ecfbd58b1480753fd94e5fee3`.
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
: `tsk_Q8YMT7ZZJ96VHEZR0AGT34M9FR` from the latest clean-start research smoke.

RUN_ID
: `run_BG54J57R7N3ND2D3TDD6G6R6KG` from the latest clean-start research smoke.

PIPELINE_RUN_RELATION
: Product canonical Run is the active reference for the existing pipeline output; lineage records bind the core pipeline run/result to the Product Task/Run.

RESULT_RELATION
: Canonical Result is project/context/task/run bound and points to the registered result Artifact.

RESULT_ID
: `res_CCY9Y5NWBH15547X5TQ6G93RX8`.

RESULT_ARTIFACT_ID
: `art_sha256_28427b2e3500316382d0596373974924a7b62130b1553e1fb2951c2b4f6ee7b3`.

RESULT_ARTIFACT_SHA256
: `28427b2e3500316382d0596373974924a7b62130b1553e1fb2951c2b4f6ee7b3`.

RESTART_REOPEN
: `PASS`; clean-start smoke reopened Product Runtime and replayed the same idempotency key with stable Task/Run/Result/Artifact identity.

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
: `PASS`; typed adapter and bridge regressions included in 123 unit tests and 73 runtime tests.

DESKTOP_STORE_TESTS
: `PASS`; submit/query/replay behavior covered.

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
: `PASS`; 73/73.

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
: `PASS` before this Ledger update; rerun after the update and on exact FINAL_HEAD.

DEFERRED_GAPS_UPDATED
: `PASS`; this Ledger records the bounded wave status and preserves deferred gaps.

DEFERRED_GAPS_PRESERVED
: `PASS`; First Source Authority broad work, strict PIT, paid data, Formal Market State, async worker, checkpoint/resume, Model/Agent, Packaging, and Release CI remain deferred.

CURRENT_STATUS_UPDATE
: Implementation and local validation complete; exact final-head guard, normal push, one PR, fresh CI, forward defect scan, and stop report remain pending.

GUARD_SKILLS_AVAILABLE
: `clean-code-guard`, `test-guard`, `docs-guard` read and available.

GUARD_SKILLS_TARGET_SHA
: `PENDING` until FINAL_HEAD is committed.

GUARD_SKILLS_SCOPE
: All changed paths plus Product Entry/ASL, Product Runtime composition, provider/source boundary, CoreResearchPipeline boundary, Task/Run/Result/Artifact, and Desktop bridge/store/panel.

CLEAN_CODE_GUARD
: `PENDING`.

TEST_GUARD
: `PENDING`.

DOCS_GUARD
: `PENDING`.

GUARD_SKILLS_CODE_GATE
: `PENDING`.

GUARD_SKILLS_FINDINGS
: `PENDING`.

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
: `IMPLEMENTED / LOCAL_VALIDATION_PASS / FINAL_CLOSURE_PENDING`.

SUCCESS_MATURITY
: `CLEAN_START_EXECUTABLE_RESEARCH = PASS_CANDIDATE`; `PRODUCT_RUNTIME_EXECUTABLE_RESEARCH = PRODUCT_CONNECTED_CANDIDATE`; `RESEARCH = PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE`.

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
: FINAL_HEAD, FINAL_TREE_SHA, PR, guard results, push, fresh exact-head CI, forward scan, final RESULT, and STOP_FOR_INDEPENDENT_REVIEW.

BLOCKED
: `NONE`.

RECOVERY_CONSISTENCY
: `PASS`; authority, task document, Ledger, Git CURRENT, and implementation status were rechecked after compaction before final closure.
