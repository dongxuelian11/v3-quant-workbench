# TASK_GOAL

Execute V3 V1.1 Usable Research Product as one bounded program, one branch, one final PR, and four checkpoint commits. A first-time user must be able to complete a truthful A-share research journey without source code or demo substitution. Preserve PRE_ALPHA / RESEARCH_ONLY / NOT_FORMAL truth, exact canonical ownership, the existing dirty root, and compaction-safe progress. After C1-C4, re-audit source and observable product effects against this goal before any push decision.

# TASK_PROGRESS

- current_checkpoint: C2_DATA_FACTOR_RESEARCH
- checkpoint_state: VALIDATING
- last_completed_action: C2 ACC-C2-01..10 source/effect reconciliation is PASS after correcting the stale Data smoke caller without weakening exact ProjectContext recovery. Latest gates pass: unit 143; backend 39/39 suites, 70/70 files, 1031 tests; authority/typecheck/lint; 33-module build; bundle/manifest; runtime 104; C1 faults 27 Python + 70 Electron; frontend/Data/Factor smokes; local Data 16; secret/repo/SBOM; diff check and P0 write-set.
- exact_next_action: Capture the final exact C2 Git status/diff stat/authority hashes, update both Ledgers with the resulting checkpoint identity, and create the single C2 checkpoint commit `feat(v1.1): connect data and factor research`. Do not push. After commit, verify the commit tree and begin C3 from section 14.1 Strategy authoring.
- active_acceptance_id: C2_CHECKPOINT_COMMIT_GATE
- files_currently_modified:
  - apps/backend/src/v3_backend/domain/strategies/__init__.py
  - apps/backend/src/v3_backend/domain/strategies/formal.py
  - apps/backend/src/v3_backend/runtime/product_research.py
  - apps/backend/src/v3_backend/adapters/artifact_store/__init__.py
  - apps/backend/src/v3_backend/adapters/local_data/__init__.py
  - apps/backend/src/v3_backend/adapters/local_data/importer.py
  - apps/backend/src/v3_backend/adapters/artifact_store/filesystem.py
  - apps/backend/src/v3_backend/adapters/tdx_formula/translator.py
  - apps/backend/src/v3_backend/contracts/product_entry.py
  - apps/backend/src/v3_backend/contracts/registry.py
  - apps/backend/src/v3_backend/domain/factors/__init__.py
  - apps/backend/src/v3_backend/domain/factors/evaluator.py
  - apps/backend/src/v3_backend/domain/factors/analysis.py
  - apps/backend/src/v3_backend/domain/factors/ir.py
  - apps/backend/src/v3_backend/runtime/composition_root.py
  - apps/backend/src/v3_backend/runtime/local_data_transfer.py
  - apps/backend/src/v3_backend/runtime/product_data.py
  - apps/backend/src/v3_backend/runtime/product_factor.py
  - apps/backend/src/v3_backend/runtime/product_facades.py
  - apps/backend/src/v3_backend/runtime/product_runtime.py
  - apps/backend/src/v3_backend/runtime/product_workers.py
  - apps/backend/requirements.txt
  - apps/backend/python-dependency-lock.json
  - apps/backend/tests/v1_1_local_data/test_local_data_import.py
  - apps/backend/tests/v1_1_local_data/test_product_data_persistence.py
  - apps/backend/tests/v1_1_local_data/test_product_data_entry.py
  - apps/backend/tests/v1_1_local_data/test_local_data_transfer.py
  - apps/backend/tests/v1_1_factor/__init__.py
  - apps/backend/tests/v1_1_factor/test_factor_panel.py
  - apps/backend/tests/v1_1_factor/test_factor_analysis.py
  - apps/backend/tests/v1_1_factor/test_product_factor_persistence.py
  - apps/backend/tests/v1_1_factor/test_product_factor_entry.py
  - apps/backend/tests/product_runtime/test_product_runtime_research.py
  - apps/backend/tests/systemic_a2_strategy_signal_payload/test_formal_strategy_payload.py
  - apps/desktop/src/main.ts
  - apps/desktop/src/main/backendRuntime/supervisor.ts
  - apps/desktop/src/main/backendRuntime/types.ts
  - apps/desktop/src/main/productRuntime/index.ts
  - apps/desktop/src/main/productRuntime/localDataImport.ts
  - apps/desktop/src/main/productRuntime/ipc.ts
  - apps/desktop/src/main/productRuntime/productBridge.ts
  - apps/desktop/src/preload.ts
  - apps/desktop/src/renderer/ProductApp.tsx
  - apps/desktop/src/renderer/components/ProductDataWorkspace.tsx
  - apps/desktop/src/renderer/components/ProductFactorWorkspace.tsx
  - apps/desktop/src/renderer/productRuntimeStore.ts
  - apps/desktop/src/renderer/productShellModel.ts
  - apps/desktop/src/renderer/styles.css
  - tests/ws_e_electron_runtime/local-data-import.test.mjs
  - tests/ws_e_electron_runtime/product-bridge.test.mjs
  - tests/ws_e_electron_runtime/supervisor.test.mjs
  - tests/unit/product-runtime-cold-discovery.test.mjs
  - tests/unit/product-shell-truth.test.mjs
  - tests/unit/desktop-product-bridge.test.mjs
  - packages/contracts/src/index.ts
  - scripts/prepare-packaged-backend.mjs
  - docs/oss/THIRD_PARTY_LICENSE_MATRIX.csv
  - docs/backend/parallel/WS_A_CONTRACT_SEED_V1_READY.json
  - apps/backend/tests/ws_a_contracts/fixtures/asl/product_entry.contract.json
  - apps/backend/tests/ws_a_contracts/fixtures/asl/index.json
  - apps/backend/tests/ws_a_contracts/fixtures/conformance_manifest.json
  - apps/backend/tests/ws_a_contracts/test_contract_seed.py
  - apps/backend/tests/ws_a_contracts/test_hardening.py
  - sbom/v3-public-baseline.spdx.json
  - package.json
  - scripts/run-v1-1-product-smoke.mjs
  - scripts/v1_1_product_data_smoke.py
  - scripts/v1_1_product_factor_smoke.py
  - docs/release/V1_1_USABLE_RESEARCH_PRODUCT_STATE_LEDGER.md
- tests:
  - last_backend_command: TEMP/TMP=.codex-tmp/python-temp-c1-ultimate-2; PYTHONPYCACHEPREFIX=.codex-tmp/compileall-c1-ultimate-2; npm.cmd run test:backend
  - backend_result: PASS — aggregate exit 0; 37/37 suites, 62/62 discovered files, 1005/1005 tests, compileall passed
  - final_required_commands: PASS — validate:authority; typecheck; lint; test:unit 138/138; test:backend 1005/1005; build 31 modules; test:runtime 98/98; test:c1-faults 27 Python + 67 Electron; verify:product-bundle-truth; smoke:frontend; verify:build-manifest
  - build_manifest: bmanifest_sha256_13ea7d1081d84269ce61960434fb3db5fc1238e452a01cd02ab3d0300ac8e2f2; DIRTY local build only
  - evidence_path: exact worktree-local D-drive caches under .codex-tmp; reproducible temporary outputs were deleted after validation and before commit
  - c2_owner_boundary_regression: PASS — ScorePayloadOwnerBoundaryTests proves direct exact-Universe encoding equals the legacy wrapper bytes and contains neither owner_id nor sgv_placeholder
  - c1_deadline_determinism_regression: PASS — the test observes a real DISPATCHED child before deadline cancellation and retains the exact TERMINATE_SENT/TERMINATED trace assertion
  - c2_local_data_red: EXPECTED FAIL — LocalDataImportError import was absent before the owner implementation
  - c2_local_data_narrow: PASS — 5 tests cover closed UTF-8 CSV, resource bounds, duplicate/OHLC rejection, nested Parquet rejection, SHARES/HANDS equivalence, MJ unit identity and CSV/Parquet normalized hash equivalence
  - c2_dependency_truth: PARTIAL PASS — requirements exact pin, checked-in CPython 3.14 win_amd64 wheel URL/SHA, packaged critical import, regenerated license matrix/SPDX and sbom:check PASS; actual packaged build/import/size delta remains NOT_RUN
  - c2_full_backend_inventory: FAIL then targeted correction PASS — the first 63-file/38-suite run reached the new suite but unittest `-t apps/backend/tests` rejected it because the new directory lacked __init__.py; added the package marker and reran the exact discovery form successfully at 5/5. A new complete backend run after this correction remains NOT_RUN.
  - c2_product_data_persistence_red: EXPECTED FAIL — `py -3.14 -B -m unittest apps.backend.tests.v1_1_local_data.test_product_data_persistence -v` fails at import with `ModuleNotFoundError: No module named 'v3_backend.runtime.product_data'`; no assertion was weakened and no implementation exists yet.
  - c2_product_data_persistence_green: PASS — 3 application tests prove exact raw CSV/Parquet bytes/media, project-scoped Artifact roles, PRE_ALPHA Snapshot/RawCapture/USER_DEFINED_STATIC Universe/ProjectContext persistence, restart readback, same-project format equivalence, immutable published Snapshot source membership, cross-project rejection and invalid-input zero publication.
  - c2_product_data_entry_red: EXPECTED FAIL — 2/2 tests fail because ProductEntryService.v1.importLocalDataset is absent from the registry and therefore unknown to RequestRouter. The acceptance fixes the additive 1.1 ref-only schema, legacy 1.0 compatibility, durable Task-before-Snapshot ordering, isolated execution and PRE_ALPHA/NOT_FORMAL readback; no assertion was weakened.
  - c2_product_data_entry_green: PASS — 4/4 Product Entry tests cover additive 1.1 closed schema and fixture, exact legacy 1.0 operation/version preservation, sub-two-second durable QUEUED acceptance before Snapshot work, isolated completion, idempotent replay, cross-project pre-Task rejection and actual-byte tamper failure with zero Snapshot.
  - c2_contract_regression: PASS — 15/15 contract seed/hardening tests; 18 services/68 operations, ProductEntryService API 1.1.0 with the original three 1.0 operations as the exact ordered prefix, fixture manifest and seed digest match.
  - c2_shared_worker_regression: PASS — 50/50 Product Runtime + legacy Product Research tests and 5/5 runtime-integrity tests after the worker manager became a closed work-kind dispatcher; 1.0 research behavior remains green.
  - c2_artifact_stream_regression: PASS — 36/36 Artifact owner tests plus the local-data tamper test; published source verification hashes the same open handle and does not load the source into memory.
  - c2_local_data_suite: PASS — 12/12 importer + Product Entry + application/persistence tests after compaction recovery, including actual-byte tamper failure.
  - c2_native_transfer_red: EXPECTED FAIL — focused Electron acceptance cannot import dist/apps/desktop/src/main/productRuntime/localDataImport.js because the owner is not implemented. The immediately preceding build attempt also hit EPERM while unlinking a prior dist contract copy; this is recorded separately and must be rechecked after implementation rather than treated as the acceptance cause.
  - c2_native_transfer_green: PASS — 45/45 focused Electron tests prove chooser cancellation, renderer path non-disclosure, non-regular/reparse/replacement-race rejection, one-use bounded verified chunks, Supervisor correlation/path rejection, backend publication and ProductEntry ref-only submission.
  - c2_backend_transfer_green: PASS — 15/15 importer/transfer/ProductEntry/persistence tests prove exact project-scoped raw publication, chunk/final identity rejection without publication, RuntimeSession correlation stripping and restart persistence; 21/21 backend transport tests also pass.
  - c2_adjacent_artifact_regression: PASS — 36/36 WS-C Artifact Store/policy/publication/reachability tests.
  - c2_adjacent_product_runtime_regression: PASS — 55/55 Product Runtime tests; exit 0.
  - c2_local_partition_ceiling: PARTIAL PASS — the former 16 MiB single-payload rejection is removed. Deterministic canonical chunks are bounded to <=8 MiB, manifest-addressed, and persisted as multiple Snapshot partitions; a forced-small-bound acceptance proves multi-partition publication and restart metadata. The default 2,000,000-row loop boundary is preserved but an actual 2,000,000-row resource benchmark remains NOT_RUN, so maximum-capacity evidence is not claimed.
  - c2_product_home_version_red: EXPECTED FAIL — Electron Supervisor silently forced expected_api_version 1.0 for the new 1.1 ProductEntry import; focused acceptance captured the exact outgoing contract/API options before the correction.
  - c2_product_home_green: PASS — additive ProductEntryService.v1.getProjectHome 1.1, strict Electron adapter, typed IPC/preload, current-context enforcement, date coverage and restart readback are connected. ProductEntry preserves the original three 1.0 operations; registry/fixture/manifest/seed now conform at 18 services/69 operations.
  - c2_renderer_data_green: PASS — 18/18 focused renderer tests prove chooser cancellation creates no Task, successful import adopts the returned ProjectContextRevision before getProjectHome, renderer state contains neither path nor bytes, reset refreshes canonical Data without reimport, and Data navigation is enabled only by the real connected bridge.
  - c2_focused_environment_retry: INFRA FAIL then PASS — the first focused runtime invocation pointed TEMP/TMP to a missing D-drive parent and 21 tests failed before assertions with ENOENT; after creating only that D-drive directory, the unchanged runtime set passed except a test-only noncanonical ID, then ProductBridge passed 22/22 after correcting the fixture ID.
  - c2_data_ui_build: PASS — typecheck and production build pass at 32 renderer modules; dirty BuildManifest bmanifest_sha256_145ce4ecc68932f738b7936bca0be41cc0586cec6396d154d13b444dc9ed45b7 is local evidence only.
  - c2_snapshot_validation_truth: PASS — seven blocking CLOSED_SCHEMA/UNIT_NORMALIZATION/UNIQUE_SYMBOL_DATE/OHLC_INVARIANTS/RESOURCE_BOUNDS/DATE_ORDERING/INSTRUMENT_RESOLUTION requirements and PASS results reference the format-independent canonical manifest; the Catalog transition now executes CANDIDATE→VALIDATED→PUBLISHED and CSV/Parquet replay remains immutable.
  - c2_multiload_boundary: PRESERVED — the frozen SQLiteA1CanonicalOwnerRepository remains a single-payload formal owner and was not reinterpreted as manifest-aware. Its exploratory edit was fully reverted (zero diff). V1.1 Factor must add a P1-verified manifest-aware reader instead of feeding manifest bytes to the legacy decoder.
  - c2_factor_panel_red: EXPECTED FAIL — `py -3.14 -B -m unittest apps.backend.tests.v1_1_factor.test_factor_panel -v` fails at import because DeterministicPanelEvaluator is absent. The new acceptance fixes actual manifest/partition identity, per-instrument rolling isolation, explicit DIVIDE_BY_ZERO_OR_MISSING, Golden MJ/MA/CROSS dates, per-date RANK and future-read rejection.
  - c2_factor_panel_green: PASS — unchanged focused acceptance 2/2. The manifest-aware reader verifies project reachability, PUBLISHED Snapshot/Universe, all seven blocking validations, actual manifest/membership/partition bytes and descriptor hashes before exposing a canonical panel. The additive axis registry and evaluator keep legacy hashes unchanged; legacy TDX/Factor regression executed 33 tests PASS with one pre-existing optional TA-Lib skip.
  - c2_factor_analysis_red: EXPECTED FAIL — `py -3.14 -B -m unittest apps.backend.tests.v1_1_factor.test_factor_analysis -v` fails at import because the FactorAnalysis owner module is absent; assertions fix one-member honesty and daily-before-aggregate statistical semantics.
  - c2_factor_analysis_green: PASS — unchanged 2-test acceptance after correcting the aggregate reason for a one-member Universe. The owner computes forward t→t+5 returns, Pearson/Spearman/quintiles per date before aggregation, stable tie splitting diagnostics, first-valid-day turnover unavailability and population IC std/ICIR over 23 valid golden dates.
  - c2_product_factor_persistence_red: EXPECTED FAIL — focused persistence test fails at import because ProductFactorStudyService is absent. It fixes exact user source persistence, six FactorDefinition/materialization owners, analysis artifact/read model and restart readback without recomputation.
  - c2_product_factor_persistence_green: PASS — unchanged focused acceptance 1/1. The service verifies ProjectContext/Snapshot/Universe ownership and bytes, uses the registered SHARES→TDX HANDS profile, evaluates six real named outputs, publishes <=8 MiB materialization partitions plus manifests, analysis and read model artifacts, persists six exact catalog definition/version pairs, and returns the identical JSON value model after restart. A discovered global-index warmup diagnostic defect was corrected to use each instrument's local position; no assertion was weakened.
  - c2_product_factor_entry_red: EXPECTED FAIL — the new durable acceptance initially failed because ProductEntryService.v1.submitFactorStudy was absent/unknown; the assertion fixed Task-before-Factor publication, closed intent and restart readback before implementation.
  - c2_product_factor_entry_green: PASS — submitFactorStudy now accepts only bounded formula source/output name, creates a durable QUEUED Task before Factor artifacts, dispatches isolated FACTOR_STUDY work, and recovers the exact formula/result through a restarted ProductRuntime. Original ProductEntry 1.0 operations remain the exact ordered prefix.
  - c2_factor_contract_regression: PASS — regenerated executable contract schemas/hashes and idempotent generator synchronization; contract/Data/Factor focus is 38 PASS plus 3 subtests at 18 services/70 operations.
  - c2_factor_electron_green: PASS — ProductBridge 41/41, renderer scope/navigation 20/20 and desktop bridge 23/23. The 22-channel frozen IPC surface rejects extra fields and caller owner IDs; main owns idempotency; canonical Factor readback rejects identity drift, non-finite values, incomplete output coverage and malformed exclusion tuples; Project A late completion is dropped after Project B activation.
  - c2_factor_ui_build: PASS — TypeScript typecheck and production build pass at 33 renderer modules. BuildManifest bmanifest_sha256_145ce4ecc68932f738b7936bca0be41cc0586cec6396d154d13b444dc9ed45b7 remains DIRTY local evidence only. One transient EPERM unlink during a combined build/test invocation was followed by an unchanged successful standalone build and is not promoted to a product defect.
  - c2_factor_context_recovery_red_green: EXPECTED FAIL then PASS — a direct restart regression proved get_latest_factor_study previously ignored ProjectContextRevision. Recovery now requires the exact project/context/snapshot triple; old-context Factor cannot leak into a newer current context.
  - c2_factor_link_recovery_green: PASS — restart readback verifies project-reachable PUBLISHED source manifest, FormulaDocument, every FactorDefinition/materialization manifest/partition descriptor, and analysis artifact with actual small-owner bytes and cross-artifact identities. Releasing the analysis reference leaves Data AVAILABLE but returns Factor UNAVAILABLE / FACTOR_READ_MODEL_NOT_AVAILABLE with no stale Factor payload.
  - c2_panel_property_green: PASS — 11 rolling-window subtests prove independent per-instrument warmup and perturbation isolation across MA windows 2..12; focused panel suite is 3 PASS + 11 subtests.
  - c2_required_product_smokes: PASS — npm.cmd run smoke:product-data and smoke:product-factor execute from D-drive temp storage. Data proves canonical restart identities; Factor proves durable QUEUED ProductEntry Task, real Golden formula/materialization, single-member INSUFFICIENT_SAMPLE and restart readback. No fixture substitution or production-availability claim.
  - c2_backend_current_aggregate: PASS — contract/Data/Factor focus 39 PASS + 14 subtests after recovery hardening.
  - c2_full_inherited_validation_before_latest_corrections: PASS — backend 39/39 suites, 70/70 files and 1030/1030 tests; unit 143/143; runtime 104/104; C1 faults 27 Python + 70 Electron; authority, typecheck, lint, 33-module build, bundle truth, dirty BuildManifest verification, frontend smoke, repo audit and SBOM all pass. Secret scan initially found only untracked Node compile caches under .codex-tmp; after exact temporary-directory removal it passed 723 source/history paths.
  - c2_format_to_factor_equivalence: PASS — one end-to-end acceptance imports the same panel as CSV and Parquet and proves identical normalized hash, Snapshot, Universe, FormulaDocument, all Factor output/materialization identities, FactorAnalysisResult and visual preview; distinct raw bytes remain distinct.
  - c2_provider_task_order_red_green: EXPECTED FAIL then PASS — the inline Product Research path previously captured the provider before creating any Task. It now durably accepts an inline Task/Run/Attempt, transitions to RUNNING, then captures; deterministic network unavailability returns exact PROVIDER_ACQUISITION_UNAVAILABLE with fallback_used=false/canonical_chain_created=false, leaves no RawCapture/Result, and persists Task FAILED plus the failure event.
  - c2_data_context_and_link_recovery: PASS — ProductDataService restart readback requires the exact project/context/snapshot triple and validates every read-model Artifact identity, semantic/reference role and active project reachability. Releasing the raw reference now fails closed instead of returning stale Data AVAILABLE; the focused local-data suite remains 16/16 PASS.
  - c2_latest_full_backend: PASS — after all provider/Data recovery corrections, the canonical backend inventory passed 39/39 suites, 70/70 files, 1031/1031 tests and compile gate.
  - c2_post_compaction_recovery: PASS — complete P0/request/attachment/2368-line plan/both-Ledger recovery; remote main/tree remain 02c5b8748170569ffc436f3bf5d2f682c21d2811/e3f3d3155177c17580015f4ef5b5405d0b689774, planned remote branch absent, 0 open PRs/issues, authority hashes match and P0 diff is empty.
  - c2_final_data_smoke_context_caller: FAIL — after authority/typecheck/lint/33-module build/bundle/manifest/runtime 104/104/C1 fault 27 Python + 70 Electron and Factor smoke passed, smoke:product-data failed because scripts/v1_1_product_data_smoke.py called the strengthened get_local_dataset without project_context_revision_id. Production exact-context behavior remains correct; the smoke caller must be corrected and rerun.
  - c2_final_data_smoke_context_caller_fix: PASS — only the smoke caller now supplies imported project_context_revision_id; Data smoke proves PRE_ALPHA/NOT_FORMAL canonical restart identities and the unchanged focused local-data suite passes 16/16.
  - acc_c2_01_secure_import: PASS — native chooser cancellation/non-regular/reparse/replacement race, bounded one-use transfer, CSV byte/row/instrument/UTF-8/closed-schema, nested Parquet, duplicate and OHLC negatives fail closed; invalid ProductData publication leaves Artifact/RawCapture/Snapshot counts at zero.
  - acc_c2_02_csv_parquet_equivalence: PASS — equivalent formats retain distinct raw identities but produce identical normalized hash, Snapshot/Universe, FormulaDocument, every Factor materialization/output, FactorAnalysis and visual preview.
  - acc_c2_03_unit_equivalence: PASS — SHARES and equivalent HANDS normalize to identical canonical rows/hash and identical per-row MJ; missing/unknown volume unit is rejected.
  - acc_c2_04_provider_failure: PASS — inline provider capture occurs only after durable Task/Run/Attempt acceptance; deterministic unavailability records exact PROVIDER_ACQUISITION_UNAVAILABLE, fallback_used=false, canonical_chain_created=false, Task FAILED/event evidence, and no RawCapture/Result/canonical bars.
  - acc_c2_05_golden_tdx: PASS — the real parser/translator/evaluator computes MJ, MA5/20/60 and both crosses against hand-calculated rows/dates with deterministic identities; no renderer formula fixture path exists.
  - acc_c2_06_axis_safety: PASS — per-instrument warmup/rolling isolation is property-tested over windows 2..12, RANK is per-date cross-section, and LEAD/negative lag/future reads fail closed.
  - acc_c2_07_single_symbol_honesty: PASS — price/MA/cross overlay remains available, while IC/RankIC/quantile metrics are INSUFFICIENT_SAMPLE with reason and no fabricated numeric cross-sectional chart.
  - acc_c2_08_cross_sectional_metrics: PASS — 20-symbol x 25-evaluable-date independent reference proves daily Pearson/Spearman/quintiles before aggregate mean/std/ICIR, coverage/missing/constant/tie/no-prior turnover branches.
  - acc_c2_09_persistence: PASS — Project/source/Snapshot/Universe/Formula/Factor/Analysis read models survive backend and Electron-shaped restart by exact canonical IDs, exact ProjectContext and active linked Artifact reachability without reimport/recompute.
  - acc_c2_10_product_ui: PASS — PRODUCT bundle contains no fixture/demo identifiers; enabled Data/Research actions issue real native bridge/ProductEntry durable Tasks and canonical Project Home readback; user-facing forms do not request owner IDs and trace IDs remain in lineage/details surfaces.
  - c2_live_provider_acceptance: NOT_RUN — no concrete post-failure availability-change signal exists; REAL_NETWORK_REQUEST_COUNT=0, no probe, provider switch or fallback was attempted.
  - c2_capacity_package_clean_machine: NOT_RUN — actual 2,000,000-row resource benchmark, packaged PyArrow/build-size delta, installer and distinct clean-machine journey remain deferred to their named later evidence gates; no stronger claim is made.
  - c2_checkpoint_write_set: PASS — staged diff contains 70 bounded C2 files, 13,088 insertions and 340 deletions; no cache/temp/P0 file is staged and cached diff --check passes.
  - clean-code-guard: 0 fixed, 7 flagged for author — FactorAnalysisService.analyze, ProductData _persist_snapshot/_persist_normalized_import/get_local_dataset, ManifestAwareLocalSnapshotReader.resolve, ProductFactor run_factor_study/_verify_recovered_study_links exceed the general function-size target. They remain cohesive single-owner seams and are explicitly non-blocking under this plan's no-large-refactor rule; no swallowed error, mock success, second evaluator, dead dependency or unverified boundary API was found.
  - test-guard: clean — C2 tests assert caller-visible owner bytes/IDs/states, use real SQLite/artifact files and real domain value objects, and mock only OS/runtime/provider/time boundaries. No internal call-count, framework-guarantee or fixture-success test was accepted.
  - docs-guard: clean — Ledger operation names, commands, counts, truth levels and NOT_RUN boundaries were checked against current contract registry/package scripts/source/test outputs. No packaged, provider, formal or production claim was promoted.
- git:
  - admitted_base_sha: 02c5b8748170569ffc436f3bf5d2f682c21d2811
  - admitted_base_tree: e3f3d3155177c17580015f4ef5b5405d0b689774
  - local_head_sha: f19a18c8ad1901abd72f6f9e81b5b90de8f20fe6
  - remote_head_sha: NOT_CREATED
  - branch: codex/v1-1-usable-research-product-01
  - status: DIRTY_IMPLEMENTATION
- github:
  - pr: NOT_CREATED
  - state: NOT_CREATED
  - checks: NOT_RUN
  - independent_review: PENDING
- blockers: NONE
- source_audit_finding: C1_SOURCE_AND_EFFECT_REAUDIT_PASS and C2_SOURCE_EFFECT_RECONCILIATION_PASS. C2 Data import/readback/UI and durable Factor formula→panel→analysis→persistence→ProductEntry→Electron→Research UI are PRODUCT_CONNECTED at LOCAL_WORKTREE / PRE_ALPHA / NOT_FORMAL scope. Deep source review corrected per-instrument warmup, Electron exclusion-tuple coercion, Task-before-provider ordering, format-to-Factor equivalence, exact Data ProjectContext recovery, linked-Artifact reachability and the stale Data smoke caller that broad green suites did not initially expose. Actual 2,000,000-row, packaged PyArrow/build-size, installer/clean-machine, live-provider, PR and independent-review evidence remain literal NOT_RUN/PENDING; no production claim is made.
- compaction_recovery: PASS on 2026-08-24 Asia/Shanghai after the current automatic compaction. All 2368 plan lines, both audit attachments, both Ledgers and the authority set were reread; Authority Manifest hashes match and P0 diff is empty. Worktree/branch/HEAD remain D:\V3OpenSource-worktrees\v1-1-usable-research-product-01, codex/v1-1-usable-research-product-01, f19a18c8ad1901abd72f6f9e81b5b90de8f20fe6. GitHub CURRENT was refreshed: remote main/tree remain 02c5b8748170569ffc436f3bf5d2f682c21d2811/e3f3d3155177c17580015f4ef5b5405d0b689774, open PRs/issues are 0, planned remote branch is absent, and exact-main CI runs 32628893718/32626717592 plus packaging run 32626717564 are SUCCESS. The stale dirty-file inventory and obsolete 16 MiB statement were corrected without changing implementation. Continue only at FactorPanel/FactorAnalysis RED.

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

- C1 Product Shell + Runtime Truth: COMMITTED f19a18c8ad1901abd72f6f9e81b5b90de8f20fe6
- ACC-C1-01 Binding failure matrix: PASS
- ACC-C1-02 Project isolation: PASS
- ACC-C1-03 Health timeout recovery: PASS
- ACC-C1-04 Exit fencing: PASS
- ACC-C1-05 Real cancellation: PASS
- ACC-C1-06 Deadline: PASS
- ACC-C1-07 Bounded memory: PASS
- ACC-C1-08 UI truth: PASS
- C1 section 11.5 control-plane composition re-audit: PASS
- C2 Data + Factor Research: ACC-C2-01..10 PASS; CHECKPOINT_COMMIT_PENDING
- C3 Strategy + Backtest + Final Result: NOT_STARTED
- C4 Usability + Release Qualification: NOT_STARTED
- Final goal/effect re-audit: NOT_STARTED
- Commit: C1_CHECKPOINT_CREATED; C2_CHECKPOINT_NOT_RUN
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

## C2_SOURCE_OWNER_AUDIT

- audit_basis: The GAP map below is the historical admission baseline from the post-compaction source audit. Current implementation results at lines above and the superseding delta below are execution truth; historical GAP text must not be used to repeat completed owners.
- ACC-C2-01 secure import: GAP — no LocalDataImportIntentV1, native chooser capability, bounded streaming CSV/Parquet importer, symlink/reparse/TOCTOU fence, or import security suite exists.
- ACC-C2-02 CSV/Parquet equivalence: GAP — the packaged Python lock contains pandas but no admitted Parquet engine; the existing Parquet port is explicitly unavailable and existing snapshot partitions do not contain canonical bar bytes.
- ACC-C2-03 unit equivalence: PARTIAL OWNER ONLY — TdxDataSemanticProfileVersion supports explicit canonical-to-TDX multipliers, but no local-import DataSemanticProfile or SHARES/HANDS MJ product gate exists.
- ACC-C2-04 provider failure: PARTIAL — ProductResearchService captures inside the C1 child worker after durable acceptance and records fallback_used=false/canonical_chain_created=false; current operation remains the legacy single-symbol profile and the connector capability row still uses the legacy DEMO vocabulary.
- ACC-C2-05 Golden TDX: PARTIAL — real TdxParser/TdxTranslator and canonical Factor IR are present, but admitted translation supports only MA/CROSS; Product Research computes only source close and constructs its score payload through a temporary sgv_placeholder reference. No Golden MJ/MA/cross product study exists.
- ACC-C2-06 axis safety: PARTIAL OWNER ONLY — the legacy deterministic evaluator is one-dimensional per series and rejects PIT-unsafe LEAD for admitted definitions, but there is no V1.1 panel evaluator owning instrument/date partitions or cross-section-per-date RANK.
- ACC-C2-07 single-symbol honesty: GAP — no FactorAnalysis application service or product read model returns INSUFFICIENT_SAMPLE for one-member Universe; Data and Research pages remain disabled.
- ACC-C2-08 cross-sectional metrics: GAP — there is no date-wise IC/RankIC/quantile/coverage/missing/turnover owner matching FactorAnalysisSpecV1.
- ACC-C2-09 persistence: PARTIAL PASS — local CSV/Parquet RawCapture, normalized Snapshot, USER_DEFINED_STATIC Universe, new ProjectContext and project-scoped Data read model now persist and survive restart with exact raw/normalized identities. Formula, V1.1 factor materialization and analysis persistence remain absent, so the full acceptance is not yet PASS.
- ACC-C2-10 Product UI: GAP — PRODUCT shell keeps Data/Research disabled and the Home panel exposes only legacy ProductEntryService.v1.submitResearch; no enabled V1.1 Data/Factor actions exist.
- canonical owner map: provider=AkshareAShareEodAdapter + ProviderRegistry + ProductResearchService child execution; raw/snapshot=normalize_a_share_eod + product_research Catalog persistence; Universe=product_research WATCHLIST/observed membership path; formula=TdxParser/TdxTranslator; Factor=FactorDefinitionVersion + DeterministicReferenceEvaluator + FeatureMaterialization/FactorEvaluation; UI=ProductApp/ProductRuntimePanel/productRuntimeStore; local import and FactorAnalysis owners are absent.
- first source-proven correction: remove the non-canonical bootstrap placeholder without changing legacy score-payload bytes. Add a binding-free encoder over exact StrategyDefinitionVersion + ExactUniverseReference, retain encode_score_payload as a compatible wrapper, and regress both payload equivalence and absence of placeholder source text.
- first source-proven correction result: PASS at local worktree source level — Product Research now encodes owner score bytes directly against the exact Universe reference; the legacy encode_score_payload entry point remains a compatibility wrapper; sgv_placeholder and the temporary binding are absent from production source.
- adjacent regression hardening: PASS — ACC-C1-06 no longer races a worker that has not entered the non-cooperative start delay; it waits for the real DISPATCHED response and still requires OS terminate evidence.
- local-data semantic owner result: MODULE_ACCEPTED for the bounded importer, additive persistence slice and durable ProductEntry 1.1 acceptance on the dirty C2 worktree — CSV reads through a bounded hashing RawIO stream; Parquet requires a bounded seekable handle, checks metadata/schema before `iter_batches`, rejects nested/dictionary/binary/extension columns, and normalizes canonical volume to SHARES. ProductDataService now proves durable raw Artifact/Snapshot/Universe/ProjectContext/read-model restart persistence and isolated Task execution. Native chooser/transfer security, product bridge/UI, >16 MiB chunked partitions, packaged PyArrow and clean-machine evidence remain NOT_RUN/NOT_AVAILABLE as stated.
- dependency owner result: PyArrow 23.0.1 is an exact direct-runtime requirement and SBOM entry for CPython 3.14 win_amd64. The official wheel identity is recorded, but package:win/clean-machine proof remains NOT_RUN and no PRODUCTION_AVAILABLE claim is made.
- superseding_current_delta: Secure native CSV/Parquet transfer, normalized Snapshot/Universe persistence, deterministic <=8 MiB partitions, seven blocking validations, Golden TDX panel, single-symbol honesty, cross-sectional analysis, durable Factor ProductEntry, canonical Project Home readback and connected Data/Research UI are locally green. The Product path is PRODUCT_CONNECTED / PRE_ALPHA / NOT_FORMAL only; it is not FORMAL or production available.
- truth ceiling: C2 remains IN_PROGRESS during post-green source/effect audit and complete validation. Actual 2,000,000-row resource evidence, packaged PyArrow/build-size proof, clean-machine evidence, PR review and production availability remain literal NOT_RUN/NOT_AVAILABLE.

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
