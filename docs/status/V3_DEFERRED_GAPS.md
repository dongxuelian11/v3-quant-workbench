# V3 Deferred Gaps Ledger

Status: `PLANNING / DEFERRED STATUS`

Authority: `NON-P0`; this file records work that remains incomplete. It is not canonical market truth, does not amend P0, and cannot promote capability maturity.

Hard rule:

```text
DEFERRED != RESOLVED
SKIPPED != RESOLVED
```

| Stable ID | Status | Discovered/confirmed at | Why deferred now | Impact | Required strengthening stage |
|---|---|---|---|---|---|
| `DATA-QUALITY-DEFER-01` | `DEFERRED` | Research pipeline runnability / Data Truth | Current free research observations do not prove complete PIT or `available_time`. | Research results remain `PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE`. | Data Truth institutional-quality PIT/knowledge-time hardening. |
| `DATA-QUALITY-DEFER-02` | `DEFERRED` | Research pipeline runnability / Data Truth | Revision/version history is incomplete for free-source observations. | Historical replay may not reproduce source revisions unavailable today. | Provider revision capture and immutable version lineage. |
| `DATA-QUALITY-DEFER-03` | `DEFERRED` | Research Backtest assembly | Suspension and full trading-status facts are unavailable. | `RESEARCH_FREE_DATA_V1` uses the explicit `BAR_PRESENT_ASSUMED_TRADABLE` and `SUSPENSION_NOT_MODELLED` assumptions. | Canonical historical trading-status owner and resolver. |
| `DATA-QUALITY-DEFER-04` | `DEFERRED` | Research Backtest assembly | ST, board changes, listing and delisting histories are incomplete. | Research eligibility/execution can approximate unavailable restrictions. | Canonical security-status and listing-history payloads. |
| `DATA-QUALITY-DEFER-05` | `DEFERRED` | Research Backtest assembly | Complete board-specific price-limit and no-limit-session facts are unavailable. | `PRICE_LIMIT_NOT_MODELLED` is explicit; no Formal market truth is claimed. | Canonical price-limit state and board-rule history. |
| `DATA-QUALITY-DEFER-06` | `DEFERRED` | Research Backtest assembly | Corporate-action/adjustment coverage is limited to available observations. | Results can omit unavailable dividends, splits or adjustments. | Canonical corporate-action owner, adjustment policy and verified payloads. |
| `DATA-QUALITY-DEFER-07` | `DEFERRED` | Formal Backtest boundary | Strict Formal `DailyMarketState` actual-payload owner/resolver coverage is not available end to end. | Formal Backtest remains fail closed / `NOT_AVAILABLE`; Research path is isolated. | Complete formal market/calendar/action/Universe owner bindings and exact bytes. |
| `DATA-QUALITY-DEFER-08` | `DEFERRED` | Data-source strategy | No real paid institutional data source is connected for this path. | Free/development observations cannot establish institutional data quality. | Paid provider integration, licensing, SLA and quality acceptance. |
| `DT-PROVIDER-DEFER-01` | `DEFERRED` | Provider-neutral Data Truth foundation | Current accepted provider-neutral observation family is EOD-centered. | Non-EOD research/provider coverage remains unavailable. | Extend accepted provider-neutral observation contracts beyond EOD. |
| `DT-PROVIDER-DEFER-02` | `DEFERRED` | Product runtime boundary | B3 is not bound to a real SQLite/Catalog/P1 provider resolver for this pipeline. | Backend candidate is not a production runtime. | B3 production handler wiring through canonical resolver and Artifact Store. |
| `CORE-PIPELINE-RUNTIME-DEFER-01` | `DEFERRED` | Core Research Pipeline runtime boundary | The current smoke composition root lives under test/helpers and uses a bounded development fixture, synthetic research observations, and local SQLite/Artifact storage. | Current evidence proves the backend pipeline can run, but does not prove a product runtime composition root is connected to real Project/Task/Data Provider/connector admission/capability resolution. | Connect the real runtime composition root during B3. |
| `CORE-PIPELINE-RUN-REGISTRY-DEFER-02` | `DEFERRED` | Core Research Pipeline run/result durability | The pipeline generates deterministic `run_id`/`run_receipt_id`, and persists the result envelope as a restart-readable Artifact. | Current evidence does not prove run/result records are durable product-grade Run/Experiment/Task registry records that can be queried, restored, and enumerated. | Connect the real registry during B3 / Experiment productization. |
| `VISUAL-EVIDENCE-DEFER-01` | `DEFERRED` | Prior full local validation | Electron restart/layout functional assertions passed historically, but screenshot `15-workbench-restored-layout-after-restart.png` was once captured as 0 bytes. | Only an exact recurrence of this visual-capture defect may be recorded `DEFERRED_UNCHANGED`; other validation failures block. | Stabilize screenshot capture and re-run exact-head visual evidence; do not repair in this backend task. |
| `STRATEGY-PORTFOLIO-DEFER` | `DEFERRED` | Core research pipeline runtime connection | The same live Formal Strategy execution now feeds Portfolio, but a persisted canonical `PortfolioIntent` owner/handoff is not established. | `RUNTIME_CONNECTED CANDIDATE` only; not `INTEGRATION_ACCEPTED`. | Canonical PortfolioIntent publication, reachability, resolver and negative cross-binding evidence. |
| `MODEL-DEFER` | `CLOSED` | PR #27 Model pipeline runnability | `ModelPipelineRequest` accepts a canonical A1 Dataset ID and no numeric samples; the service resolves the persisted `FormalDatasetVersion`, verifies its `DATASET_SAMPLES` Artifact through P1, strictly decodes the exact bytes, and deterministically materializes Track E `ModelSample` rows. | The caller-supplied runnable sample gap is closed for the bounded `PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE` backend path. This does not establish product or production connection. | Closed by exact-head Model pipeline tests, restart/reopen artifact proof, smoke and CI. |
| `MODEL-RUNTIME-DEFER-01` | `DEFERRED` | PR #27 Model pipeline product boundary | The runnable backend service and repo-native smoke are not connected to Desktop or Agent product runtime. | Model Agent remains L0/L1 only; L2/L3 remain denied. No `PRODUCT_CONNECTED` or `PRODUCTION_AVAILABLE` claim. | Separate authorized Desktop/runtime integration through the canonical handler/bridge and shared user-action authority. |
| `MODEL-REGISTRY-DEFER-02` | `DEFERRED` | PR #27 forward defect scan | Model and Prediction Artifacts are content-addressed and restart-readable through the Artifact Store, but no durable product Model/Run registry enumerates or reloads them for B3. | The bounded backend pipeline is runnable; B3 product resume/discovery remains unavailable. | Establish the canonical Model/Run registry and bind it to Task/Experiment product runtime before B3 product connection. |
| `MODEL-ERROR-CLASSIFICATION-DEFER-03` | `DEFERRED` | PR #27 forward defect scan | The bounded pipeline maps stage failures to typed terminal statuses but currently catches broad worker/adapter exceptions at stage boundaries. | Errors remain visible and fail closed, but B3 cannot yet provide stable retryability/operator classifications for every failure. | Introduce canonical error taxonomy and retryability mapping during B3 runtime hardening without weakening terminal failures. |
| `EXPERIMENT-REWARD-DEFER` | `CLOSED_FOR_ALPHA_RESEARCH_BACKEND` | PR #30 Alpha research-loop runnability | The bounded Alpha backend now resolves canonical Dataset/Feature actual bytes through P1, uses the sole Formal Factor evaluator, computes metrics in V3, invokes the registered Reviewer, and binds Experiment/Reward identities. | Closure is limited to the Alpha backend research composition; it grants no product or production authority. | No further strengthening for this bounded backend seam; product runtime remains separately deferred below. |
| `ALPHA-RESEARCH-PRODUCT-RUNTIME-DEFER-01` | `DEFERRED` | PR #30 Alpha research-loop runnability | The runnable composition is not connected to a product Task/Run registry, production endpoint, or canonical user-start approval authority. | `RUNNABLE_BACKEND_CANDIDATE / PRE_ALPHA / RESEARCH_ONLY`; production user-start and Agent L2/L3 remain `NOT_AVAILABLE / NOT_RUN`. | Separately accepted product composition root, durable Run registry, and shared canonical user-action authority. |
| `ALPHA-REVIEW-EVIDENCE-DEFER-02` | `DEFERRED` | PR #30 post-merge guard closure | Registered Reviewer rules do not currently check sample coverage, missingness, turnover or complexity. The Alpha backend records those dimensions as `NOT_RUN`, never default `PASS`. | Research reward remains scored under the `PRE_ALPHA` ceiling, but these dimensions cannot support a stronger Reviewer or maturity claim. | Add real deterministic Reviewer rules and evidence before any of these dimensions can become `PASS`. |
| `ALPHA-GENERATOR-STATE-DEFER-03` | `DEFERRED` | PR #30 post-merge guard closure | Reward feedback is explicitly run-local, in-memory and non-canonical; a new run clears exact-job feedback even when the generator instance is reused. | Bounded same-run search uses prior-generation reward, but no cross-run recovery or continuation is available. | For B3 cross-run continuation, establish durable lineage/state ownership or an explicit stateless replay strategy. |
| `RESULT-ANALYTICS-DEFER` | `DEFERRED` | Result stage | Result Analytics is not re-anchored to the new Research Backtest result/P1 artifact. | Result Artifact is readable, but analytics/product integration is not complete. | Result Analytics canonical result/ledger resolver and P1 re-anchor. |
| `RISK-APP-HARDEN-01` | `DEFERRED` | Risk Application | Summary truth/admission presentation requires additional hardening beyond the accepted owner publication. | Core Risk output remains usable through exact owner IDs, but broader summaries must not overstate truth. | Risk Application summary/evidence truth-ceiling review. |

## Current task checkpoint

- `CORE_RESEARCH_PIPELINE = RUNNABLE BACKEND CANDIDATE` only after exact-head validation and CI succeed.
- `FORMAL_BACKTEST_MARKET_STATE = NOT_AVAILABLE` and the Formal path remains fail closed.
- `RESEARCH_FREE_DATA_V1` records every research assumption in result evidence.
- `DEFERRED_GAPS_CLOSED = NONE` for task `V3-CORE-RESEARCH-PIPELINE-RUNNABILITY-PR35-20260814-01`.
- `EXPERIMENT-REWARD-DEFER = CLOSED_FOR_ALPHA_RESEARCH_BACKEND` only for task
  `V3-PR30-ALPHA-EXPERIMENT-RUNNABILITY-20260814-01`; no PR #35 or Core
  Research Pipeline claim is changed.
- `ALPHA-RESEARCH-PRODUCT-RUNTIME-DEFER-01 = DEFERRED` and production
  user-start remains `NOT_AVAILABLE / NOT_RUN`.
- `ALPHA-REVIEW-EVIDENCE-DEFER-02 = DEFERRED`; unchecked Reviewer dimensions
  remain `NOT_RUN`, not `PASS`.
- `ALPHA-GENERATOR-STATE-DEFER-03 = DEFERRED`; reward feedback is run-local and
  non-canonical, with no durable product-runtime state owner.

## PR #27 Model pipeline runnability checkpoint

- `MODEL-DEFER = CLOSED` only for canonical A1 Dataset owner + P1 actual bytes to deterministic Track E `ModelSample` materialization with no caller sample arrays.
- `MODEL-RUNTIME-DEFER-01 = DEFERRED`: Desktop/Agent runtime connection remains outside this task.
- `MODEL-REGISTRY-DEFER-02 = DEFERRED`: B3 Model/Run discovery and reload lacks a canonical product registry.
- `MODEL-ERROR-CLASSIFICATION-DEFER-03 = DEFERRED`: B3 retryability/operator classification remains future hardening.
- All current-main non-Model Deferred entries remain preserved.
- Final candidate language remains conditional on exact-head tests, guard-skills, push and fresh CI.
