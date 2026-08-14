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
| `VISUAL-EVIDENCE-DEFER-01` | `DEFERRED` | Prior full local validation | Electron restart/layout functional assertions passed historically, but screenshot `15-workbench-restored-layout-after-restart.png` was once captured as 0 bytes. | Only an exact recurrence of this visual-capture defect may be recorded `DEFERRED_UNCHANGED`; other validation failures block. | Stabilize screenshot capture and re-run exact-head visual evidence; do not repair in this backend task. |
| `STRATEGY-PORTFOLIO-DEFER` | `DEFERRED` | Core research pipeline runtime connection | The same live Formal Strategy execution now feeds Portfolio, but a persisted canonical `PortfolioIntent` owner/handoff is not established. | `RUNTIME_CONNECTED CANDIDATE` only; not `INTEGRATION_ACCEPTED`. | Canonical PortfolioIntent publication, reachability, resolver and negative cross-binding evidence. |
| `MODEL-DEFER` | `DEFERRED` | Model boundary | Dataset actual bytes to deterministic `ModelSample` remains outside this task. | Model/PR #27 is not advanced by pipeline runnability. | Dataset/Model actual-payload owner integration. |
| `EXPERIMENT-REWARD-DEFER` | `DEFERRED` | Experiment boundary | Experiment/Reviewer/Reward canonical recomputation is not connected to this result. | The smoke result is not a canonical experiment/reward result. | Exact result payload resolution and deterministic experiment/reward recompute. |
| `RESULT-ANALYTICS-DEFER` | `DEFERRED` | Result stage | Result Analytics is not re-anchored to the new Research Backtest result/P1 artifact. | Result Artifact is readable, but analytics/product integration is not complete. | Result Analytics canonical result/ledger resolver and P1 re-anchor. |
| `RISK-APP-HARDEN-01` | `DEFERRED` | Risk Application | Summary truth/admission presentation requires additional hardening beyond the accepted owner publication. | Core Risk output remains usable through exact owner IDs, but broader summaries must not overstate truth. | Risk Application summary/evidence truth-ceiling review. |

## Current task checkpoint

- `CORE_RESEARCH_PIPELINE = RUNNABLE BACKEND CANDIDATE` only after exact-head validation and CI succeed.
- `FORMAL_BACKTEST_MARKET_STATE = NOT_AVAILABLE` and the Formal path remains fail closed.
- `RESEARCH_FREE_DATA_V1` records every research assumption in result evidence.
- `DEFERRED_GAPS_CLOSED = NONE` for task `V3-CORE-RESEARCH-PIPELINE-RUNNABILITY-PR35-20260814-01`.
