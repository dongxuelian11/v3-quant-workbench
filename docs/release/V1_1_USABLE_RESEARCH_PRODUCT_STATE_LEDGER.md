# TASK_GOAL

Execute V3 V1.1 Usable Research Product as one bounded program, one branch, one final PR, and four checkpoint commits. A first-time user must be able to complete a truthful A-share research journey without source code or demo substitution. Preserve PRE_ALPHA / RESEARCH_ONLY / NOT_FORMAL truth, exact canonical ownership, the existing dirty root, and compaction-safe progress. After C1-C4, re-audit source and observable product effects against this goal before any push decision.

# TASK_PROGRESS

- current_checkpoint: C1_PRODUCT_SHELL_RUNTIME_TRUTH
- checkpoint_state: READY_FOR_CHECKPOINT_COMMIT
- last_completed_action: C1 sections 11.1-11.10 were re-audited against source after all tests were green. The audit found and corrected four additional runtime defects: unknown worker spawn errors were falsely retryable; post-spawn composition failure could leave a real child running; failure finalization overwrote REVOKED lease truth as RELEASED; and idle lease-monitor threads could leak SQLite handles on Windows. Latest-source gates now pass: authority, typecheck, lint, 138/138 unit, 37/37 backend suites with 62/62 files and 1005/1005 tests plus compileall, 31-module build, 98/98 Electron runtime, C1 fault injection 27 Python + 67 Electron, PRODUCT bundle truth, frontend smoke, and BuildManifest verification.
- exact_next_action: Verify bounded Git status/P0 hashes/diff after exact D-drive temp cleanup, then create checkpoint commit 1 without push. After that, record its SHA and begin C2 in the same branch.
- active_acceptance_id: C1_CHECKPOINT_COMMIT_GATE
- files_currently_modified:
  - docs/release/V1_1_USABLE_RESEARCH_PRODUCT.md
  - docs/release/V1_1_USABLE_RESEARCH_PRODUCT_STATE_LEDGER.md
  - package.json
  - scripts/verify-product-bundle-truth.mjs
  - vite.config.mjs
  - tsconfig.json
  - apps/desktop/src/renderer/main.tsx
  - apps/desktop/src/renderer/ProductApp.tsx
  - apps/desktop/src/renderer/productShellModel.ts
  - apps/desktop/src/renderer/components/ProductRuntimePanel.tsx
  - apps/desktop/src/renderer/styles.css
  - tests/unit/product-shell-truth.test.mjs
  - scripts/public-frontend-smoke.mjs
  - apps/desktop/src/renderer/round3Evidence.ts
  - tsconfig.renderer.json
  - tests/ws_e_electron_runtime/cross-language.test.mjs
  - scripts/product-research-smoke.mjs
  - apps/backend/tests/systemic_portfolio_riskpolicy_owner/test_owner_foundation.py
  - apps/desktop/src/main/backendRuntime/supervisor.ts
  - apps/desktop/src/main/backendRuntime/types.ts
  - apps/desktop/src/main/backendRuntime/processFactory.ts
  - apps/desktop/src/main/productRuntime/adapters.ts
  - apps/desktop/src/main/productRuntime/bindingStore.ts
  - apps/desktop/src/main/productRuntime/productBridge.ts
  - apps/desktop/src/renderer/productRuntimeStore.ts
  - apps/backend/src/v3_backend/runtime/composition_root.py
  - apps/backend/src/v3_backend/runtime/health.py
  - apps/backend/src/v3_backend/runtime/bootstrap.py
  - apps/backend/src/v3_backend/runtime/product_facades.py
  - apps/backend/src/v3_backend/runtime/product_research.py
  - apps/backend/src/v3_backend/runtime/product_runtime.py
  - apps/backend/src/v3_backend/runtime/product_workers.py
  - apps/backend/src/v3_backend/adapters/sqlite/lease_persistence.py
  - apps/backend/src/v3_backend/control_plane/resource_governor.py
  - apps/backend/src/v3_backend/control_plane/lease_manager.py
  - apps/backend/src/v3_backend/workers/protocol.py
  - apps/backend/src/v3_backend/runtime/request_router.py
  - apps/backend/src/v3_backend/migrations/versions/0005_task_execution_deadline.sql
  - apps/backend/src/v3_backend/migrations/validator.py
  - apps/backend/src/v3_backend/domain/tasks/state_machine.py
  - apps/backend/tests/ws_e_runtime/test_runtime_transport.py
  - apps/backend/tests/product_runtime/test_product_runtime_research.py
  - apps/backend/tests/ws_d_task_workers/test_worker_resource.py
  - apps/backend/tests/ws_b_catalog/test_migrations.py
  - tests/ws_e_electron_runtime/runtime-core-shutdown.test.mjs
  - tests/ws_e_electron_runtime/supervisor.test.mjs
  - tests/ws_e_electron_runtime/product-bridge.test.mjs
  - tests/unit/desktop-product-bridge.test.mjs
  - tests/unit/product-runtime-cold-discovery.test.mjs
  - scripts/c1-fault-injection-test.mjs
- tests:
  - last_backend_command: TEMP/TMP=.codex-tmp/python-temp-c1-ultimate-2; PYTHONPYCACHEPREFIX=.codex-tmp/compileall-c1-ultimate-2; npm.cmd run test:backend
  - backend_result: PASS — aggregate exit 0; 37/37 suites, 62/62 discovered files, 1005/1005 tests, compileall passed
  - final_required_commands: PASS — validate:authority; typecheck; lint; test:unit 138/138; test:backend 1005/1005; build 31 modules; test:runtime 98/98; test:c1-faults 27 Python + 67 Electron; verify:product-bundle-truth; smoke:frontend; verify:build-manifest
  - build_manifest: bmanifest_sha256_13ea7d1081d84269ce61960434fb3db5fc1238e452a01cd02ab3d0300ac8e2f2; DIRTY local build only
  - evidence_path: exact worktree-local D-drive caches under .codex-tmp; reproducible temporary outputs were deleted after validation and before commit
- git:
  - admitted_base_sha: 02c5b8748170569ffc436f3bf5d2f682c21d2811
  - admitted_base_tree: e3f3d3155177c17580015f4ef5b5405d0b689774
  - local_head_sha: 02c5b8748170569ffc436f3bf5d2f682c21d2811
  - remote_head_sha: NOT_CREATED
  - branch: codex/v1-1-usable-research-product-01
  - status: DIRTY_IMPLEMENTATION
- github:
  - pr: NOT_CREATED
  - state: NOT_CREATED
  - checks: NOT_RUN
  - independent_review: PENDING
- blockers: NONE
- source_audit_finding: C1_SOURCE_AND_EFFECT_REAUDIT_PASS — sections 11.1-11.10 and ACC-C1-01..08 map to implemented owners and executable evidence. C2 remains NOT_STARTED; admitted-base DEMO capability labels and sgv_placeholder are explicitly deferred to the C2 provider/data/strategy truth correction and are not claimed as C1 closure.
- compaction_recovery: PASS on 2026-08-23 Asia/Shanghai; complete authority/task/plan/Ledger order repeated, GitHub CURRENT refreshed, and no authority/base/remote-lineage drift observed.

# PROJECT_AUTHORITY

- authority_version: 1.0.2
- authority_status: P0_PROJECT_AUTHORITY
- P0_AUTHORITY_AMENDMENT authorization: ABSENT
- P0 authority modification: FORBIDDEN
- V3_PROJECT_CONSTITUTION.md SHA-256: 92ff8049addd10c1ca7f6ca293007b254045f3f63bae53ddc626b761da5bd32b
- AGENTS.md SHA-256: cbe7d78e2eccbfd5254fd08b30a0b145dc7c37b60aa5eadbbf4649b490f5b385
- docs/architecture/V3_CANONICAL_ARCHITECTURE.md SHA-256: ca74dcd00d2d20ba106d962b2455254f8ee69807df09d20ff4984e20a362bc5b
- docs/status/V3_CAPABILITY_LEVELS.md SHA-256: 79ca5210a33f283332884a9a4268e08a093ffe2d4ea33fe97d20672d355a9266
- docs/status/V3_PROJECT_AUTHORITY_MANIFEST.json SHA-256: 3306f51f4d9b26577f092d53e3a5cdb319619e9e9a75c0b90203c87bd21c425a
- authority hash status: MATCH
- authority drift rule: STOP_FOR_REVIEW

## GIT_GITHUB_CURRENT

- repository: dongxuelian11/v3-quant-workbench
- refreshed_at: 2026-08-24 Asia/Shanghai
- remote main: 02c5b8748170569ffc436f3bf5d2f682c21d2811
- remote main tree: e3f3d3155177c17580015f4ef5b5405d0b689774
- open PRs: 0
- open issues: 0
- planned remote branch: NOT_FOUND
- exact-main ci: SUCCESS, run 32626717592
- exact-main packaging-clean-machine-evidence: SUCCESS, run 32626717564
- implementation worktree: D:\V3OpenSource-worktrees\v1-1-usable-research-product-01
- original root: D:\V3OpenSource at fd451c83005e444f84161e0c905f853a2b36d5a3 with 28 pre-existing status entries; do not modify or clean

## EXECUTION_BOUNDARIES

- One branch, one eventual PR, four checkpoint commits.
- No reset, rebase, force push, amend, auto-merge, recursive correction branch, or administrative bypass.
- No push until C1-C4 implementation and final task-goal/effect audit are complete and the user has been shown push eligibility.
- No fixture/provider fallback may mint product truth.
- Single-symbol Golden Case A must report cross-sectional metrics as INSUFFICIENT_SAMPLE.
- Golden Case B owns per-date cross-sectional IC/RankIC/quantile metrics.
- Formal Backtest checkpoint/resume remains NOT_AVAILABLE unless its full contract is genuinely closed.
- P0 authority files are outside the write set.
- The obsolete workflowguard-v3-preflight skill was uninstalled by explicit user request and is not an execution authority.

## CHECKPOINT_STATUS

- C1 Product Shell + Runtime Truth: PASS; CHECKPOINT_COMMIT_PENDING
- ACC-C1-01 Binding failure matrix: PASS
- ACC-C1-02 Project isolation: PASS
- ACC-C1-03 Health timeout recovery: PASS
- ACC-C1-04 Exit fencing: PASS
- ACC-C1-05 Real cancellation: PASS
- ACC-C1-06 Deadline: PASS
- ACC-C1-07 Bounded memory: PASS
- ACC-C1-08 UI truth: PASS
- C1 section 11.5 control-plane composition re-audit: PASS
- C2 Data + Factor Research: NOT_STARTED
- C3 Strategy + Backtest + Final Result: NOT_STARTED
- C4 Usability + Release Qualification: NOT_STARTED
- Final goal/effect re-audit: NOT_STARTED
- Commit: NOT_RUN
- Push: NOT_RUN
- PR: NOT_CREATED

## C1_SOURCE_EFFECT_REAUDIT

- 11.1 characterization: PASS — original failure modes remain represented by named regressions; no assertion was deleted to make them green.
- 11.2 correlated control: PASS — closed control envelope, generation fencing, bounded pending/tombstone ownership, health/shutdown/Product Entry correlation.
- 11.3 process exit: PASS — graceful ack, wait, terminate, kill, confirmed-exit fence; unconfirmed exit blocks the next generation.
- 11.4 atomic activation: PASS — BindingActivationV2 rollback matrix and renderer ProjectScopeToken drop late Project A responses after Project B activation.
- 11.5 task coordinator: PASS — existing TaskSupervisor/WorkerSupervisor composition, independent command/response pipes, child SQLite UoW, 2-second heartbeat, 10-second lease, real cancellation/deadline/restart reconciliation, lazy monitor lifecycle.
- 11.6 router/errors: PASS — bounded request cache, enforced deadline, Exception-only orchestration, unknown INTERNAL_ERROR nonretryable, touched bridge coercions fail closed.
- 11.7 pagination/persistence: PASS — scope/filter/sort-bound opaque keyset cursors, page size 1..100, explicit next-page UI, virtualized lists, ENOENT-only BindingStore default, bounded Workspace V2 backup/rollback migration.
- 11.8 UI truth: PASS — five fixed Chinese-first pages, only real Home enabled, four deferred pages disabled with NOT_AVAILABLE reasons, release bundle scanner rejects demo identifiers.
- 11.9 migration: PASS — additive transactionally validated 0005 adds deadlines, task_output, publication_intent, immutable session/project binding, and cursor indexes; old-catalog upgrade/backup failure paths are tested.
- 11.10 acceptance: PASS — ACC-C1-01..08 plus post-green source audit and all required commands.
- evidence ceiling: LOCAL_WORKTREE / SAME_MACHINE only. No clean-machine, packaged installer, hosted, PR, independent review, merge, or production claim is made for this checkpoint.
- deferred_to_C2: exact-main already contains admitted_truth_state DEMO, submitResearch truth_state DEMO, and sgv_placeholder. These were verified in both HEAD and working source, were not introduced by C1, and remain a mandatory C2 truth-chain correction rather than hidden debt.
- clean-code-guard: runtime error classification, partial-start exit fencing, worker configuration object, execution-path split, non-swallowing lease monitor, and idle-monitor lifecycle fixed; long OS child entrypoint remains cohesive and is not generalized further in C1.
- test-guard: clean — new tests inject at OS process/SQLite/lease boundaries and assert durable state plus real process exit, not internal call counts.
- docs-guard: claims above were checked against current symbols, migrations, package scripts, test inventories, Git status, and authority hashes; no stronger availability claim is recorded.

## COMPACTION_RECOVERY

After any automatic compaction:

1. Read V3_PROJECT_CONSTITUTION.md completely.
2. Read docs/architecture/V3_CANONICAL_ARCHITECTURE.md completely.
3. Read docs/status/V3_CAPABILITY_LEVELS.md completely.
4. Read the original user requests and both audit attachments.
5. Read docs/release/V1_1_USABLE_RESEARCH_PRODUCT.md completely.
6. Read this Ledger from the first line.
7. Recompute all Authority Manifest hashes.
8. Refresh Git/GitHub CURRENT.
9. Verify worktree, branch, HEAD, dirty files, and remote state against this Ledger.
10. If any identity or authority drift exists, STOP_FOR_REVIEW.
11. Otherwise execute only exact_next_action; do not repeat completed work.
