# V3 recommendations

## Executive recommendation

**ADOPT:** make `TargetWeightVector` the unified stable desired-portfolio contract published only by PortfolioService/Portfolio Construction, then processed by an explicit Risk stage before Backtest/Execution planning.

Strategy, Model and AI publish only `SignalArtifact` and/or `PortfolioIntent`; proposed weights remain inside the intent. PortfolioService validates scope, completeness, cash/exposure, constraints and provenance before publishing `TargetWeightVector`. Risk always publishes a distinct immutable `RiskAdjustedWeightVector`, including an explicit pass-through derivative when no additional transform is applied. Execution converts only that risk-stage output into target quantities/orders using exact account, market and rule snapshots.

This gives V3 one comparable artifact across Visual/Code strategies, ML models and AI proposals without pretending that weights are orders or fills.

## Recommended object chain

| Object | Owns | Does not own | Disposition |
|---|---|---|---|
| `SignalArtifact` | scores/directions/confidence and exact data/model/strategy provenance | cash, holdings, orders | **ADOPT** |
| `PortfolioIntent` | selected scope, preferences/objective, proposed exposure/cash/rebalance and construction constraints | normalized/admitted vector unless fully resolved | **ADOPT** |
| `TargetWeightVector` | Portfolio-owned exact immutable desired weights over a pinned universe | direct publication by Strategy/Model/AI; current account, quantities, orders/fills | **ADOPT** |
| `RiskAdjustedWeightVector` | mandatory Risk-stage derivative, including explicit pass-through, plus source target and ordered risk evidence | mutation of Strategy/Model/target identity | **ADOPT** |
| `ExecutionPlan` | account/market-aware target quantities, deltas, blocked residuals and idempotency | economic reinterpretation of strategy | **ADOPT** |
| `Orders/Fills/Ledger` | actual engine/account state changes | desired portfolio identity | **ADOPT** |

## Fit with current V3

The recovered baseline already points in the right direction:

- Portfolio ASL input pins `portfolio_spec_id`, `signal_version_id`, `universe_version_id` and schedule artifact, and emits portfolio-target artifacts;
- Portfolio ASL explicitly forbids simulating fills and owning signals/risk models;
- Backtest ASL run identity pins strategy, snapshot, universe, portfolio, optional factor-risk/optimization references, rule profiles, engine and environment; an absent factor RiskModel must map to explicit pass-through RiskPolicySetVersion rather than bypass Risk;
- Risk ASL pins portfolio and risk-model identities for analysis;
- all published/versioned objects are immutable and workers own no V3 identity/truth;
- current desktop StrategyDraft/BacktestHandoffDraft surfaces are recovered/demo-level, not formal financial output.

The next phase should add these concepts through a design/versioned-contract proposal, not edit the current ASL opportunistically.

## Priority decisions

| Priority | Recommendation | Disposition | Acceptance gate |
|---|---|---|---|
| P0 | Write a schema RFC for the artifact chain and ownership matrix | **ADOPT** | every field has owner, temporal meaning, identity rule and failure semantics |
| P0 | Define `LONG_ONLY_UNLEVERED` as the first exposure profile | **ADAPT** | explicit cash, sum equation, bounds and decimal tolerance have goldens |
| P0 | Specify canonical bytes/content hashing | **ADOPT** | cross-language golden vectors reproduce the same hash |
| P0 | Require exact Dataset/Snapshot/Universe/source/policy refs | **ADOPT** | no mutable aliases admitted in FORMAL mode |
| P0 | Separate original and risk-adjusted vectors | **ADOPT** | risk can never overwrite original or source identity |
| P0 | Make PortfolioService/Portfolio Construction the only formal TargetWeightVector publisher | **ADOPT** | proposed weights cannot bypass complete Portfolio admission |
| P0 | Enforce Target and RiskAdjusted truth ceilings | **ADOPT** | PRE_ALPHA/NOT_FORMAL upstream can never become FORMAL |
| P0 | Require exact RiskPolicySetVersion on every formal path | **ADOPT** | pass-through is explicit and Execution has one input type |
| P0 | Define typed infeasible/blocked/stale results | **ADOPT** | no warning-only or silent fallback path |
| P1 | Build a deterministic weight-to-quantity adapter contract | **ADOPT** | price/lot/T+1/ST/suspension/limit goldens pass |
| P1 | Define ordered `RiskPolicySetVersion` and stage evidence | **ADOPT** | noncommuting/conflicting policy tests pass |
| P1 | Add provenance graph/read model | **ADOPT** | target-to-signal and fill-to-target traversal is complete |
| P1 | Define optimizer-run provenance/admission | **ADAPT** | infeasible/inaccurate/fallback cases are explicit |
| P2 | Add typed sparse `PortfolioIntentPatch` if demanded | **FUTURE** | concrete workflow proves full vectors insufficient |
| P2 | Add short/leverage/derivative exposure profiles | **FUTURE** | accounting, margin, borrow and adapter semantics are formalized |

## Required boundaries

| Boundary | Rule | Disposition |
|---|---|---|
| Strategy/Model/AI -> Portfolio | only typed `SignalArtifact`/`PortfolioIntent`; proposed weights remain intent and cannot be formally published directly | **ADOPT** |
| Portfolio -> Risk | only PortfolioService/Portfolio Construction publishes `TargetWeightVector` after full admission | **ADOPT** |
| Risk -> Execution | every path names `RiskPolicySetVersion`; only `RiskAdjustedWeightVector` or typed rejection crosses the boundary | **ADOPT** |
| Execution -> engine/account | target quantities/order intents under a pinned adapter | **ADOPT** |
| Worker -> V3 main service | result candidates/artifact bytes only; no identity issuance, registry or account writes | **ADOPT** |
| UI -> formal pipeline | immutable IDs/commands through the typed main-process boundary | **ADOPT** |

## What not to do

| Proposal | Disposition | Reason |
|---|---|---|
| Reuse LEAN `PortfolioTarget` directly | **REJECT** | quantity and live algorithm state make it the wrong stable layer |
| Standardize on a pandas DataFrame or `{ticker: weight}` | **REJECT** | loses identity, exact scope, time, cash profile and provenance |
| Let Risk edit weights in place | **REJECT** | destroys before/after comparison and causal identity |
| Let Backtest rerun Strategy to discover targets | **REJECT** | bypasses reviewed artifacts and can diverge |
| Let Execution silently renormalize/drop/replace | **REJECT** | changes economic intent without portfolio/risk ownership |
| Let Strategy/Model/AI directly publish formal TargetWeightVector | **REJECT** | bypasses Portfolio scope/completeness/cash/exposure/constraints/provenance admission |
| Let Execution consume raw TargetWeightVector when no factor RiskModel is configured | **REJECT** | creates two execution contracts and bypasses Risk ownership/evidence |
| Let Portfolio or Risk validation upgrade PRE_ALPHA/NOT_FORMAL upstream to FORMAL | **REJECT** | truth is monotone and bounded by required upstream admission |
| Infer current-holding semantics from missing rows | **REJECT** | ambiguous and non-idempotent |
| Treat target, plan, fill and holding as one mutable portfolio object | **REJECT** | conflates time, truth and ownership |
| Change existing Portfolio/Risk ASL in this research PR | **REJECT** | explicitly outside scope |

## Phased implementation input

### Phase 1 — RFC and goldens

**ADOPT:** formalize vocabulary, canonicalization, long-only exposure profile, identity graph, error taxonomy and golden examples. Produce no live financial output.

### Phase 2 — pure artifact transforms

**ADOPT:** implement Signal/Intent import, Portfolio-owned vector canonicalization/admission, truth-ceiling computation and ordered pure risk transforms behind worker boundaries. PortfolioService alone publishes TargetWeightVector; Risk always publishes RiskAdjustedWeightVector, including pass-through. Main service owns IDs and truth admission.

### Phase 3 — adapter conformance

**ADAPT:** connect an admitted backtest adapter through weight-to-quantity planning and A-share rule goldens. Preserve the current Backtest ASL run identity and artifact boundaries; revise contracts only through normal governance.

### Phase 4 — broader profiles

**FUTURE:** shorting, leverage, derivatives, stateful circuit breakers and live execution after accounting/risk/engine contracts mature.

## Ten core conclusions

1. **ADOPT** — `TargetWeightVector` is V3's stable desired-portfolio seam, published only by PortfolioService/Portfolio Construction.
2. **ADOPT** — Strategy/Model/AI publish SignalArtifact/PortfolioIntent; proposed weights cannot bypass Portfolio admission.
3. **ADOPT** — every formal route emits a separate immutable RiskAdjustedWeightVector under an exact RiskPolicySetVersion, including pass-through.
4. **REJECT** — Strategy/Model/AI reading accounts, writing holdings or calling Backtest/Execution.
5. **ADOPT** — Target and RiskAdjusted truth cannot exceed required upstream Signal/Intent/Data/Universe/policy admission.
6. **ADOPT** — explicit cash and named exposure profiles; no universal implicit residual rule.
7. **ADOPT** — complete absolute vectors; sparse commands use another type.
8. **ADOPT** — account-aware weight-to-quantity/order conversion belongs to Execution.
9. **REJECT** — silent renormalization, fuzzy mapping, invented prices or hidden fallback.
10. **FUTURE** — leverage/derivatives/stateful risk only after formal accounting and adapter goldens.
