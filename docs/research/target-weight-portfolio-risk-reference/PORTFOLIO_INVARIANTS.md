# Portfolio invariants

## Ownership

Portfolio Construction owns the deterministic conversion from `PortfolioIntent` plus pinned construction inputs into `TargetWeightVector`. It may use an optimizer, but it does not own account mutation, orders, fills or the identity of the source Strategy/Model/AI.

| Invariant | Disposition | Required behavior |
|---|---|---|
| P-01 Input identity | **ADOPT** | Exact intent, signal, universe, dataset/snapshot, schedule, constraints, code and environment refs are pinned |
| P-02 Desired vs actual | **ADOPT** | Target weights and current holdings are separate objects; a target never becomes “actual” without fills/ledger evidence |
| P-03 Full scope | **ADOPT** | A published vector has complete absolute semantics over one exact universe |
| P-04 Pure publication | **ADOPT** | Publication writes a new immutable artifact; it does not trade or modify an account |
| P-05 No hidden normalization | **REJECT** | Sum/bound errors cannot be silently fixed; any admitted normalization rule is pinned and evidenced |
| P-06 Stable strategy identity | **ADOPT** | Portfolio construction creates its own artifact identity and references, but does not rewrite StrategyVersion/ModelVersion |

## Weight, cash and exposure

The admissibility equation is profile-specific.

For `LONG_ONLY_UNLEVERED`:

```text
for each i: 0 <= w_i <= configured_max_i
cash >= 0
sum_i(w_i) + cash = 1 within declared tolerance
```

For long/short:

```text
net = sum_i(w_i)
gross = sum_i(abs(w_i))
min_net <= net <= max_net
gross <= max_gross
cash and financing follow the named exposure profile
```

| Rule | Disposition | Rationale |
|---|---|---|
| Explicit cash, including zero | **ADOPT** | Prevents residual, reserve and omission from being conflated |
| One universal `cash = 1 - sum(weights)` equation | **REJECT** | Incorrect for some long/short, leveraged and derivatives profiles |
| Signed weights for short-enabled profiles | **ADOPT** | Keeps long/short intent explicit |
| Infer short permission from a negative value | **REJECT** | Permission belongs to pinned constraints/profile; a negative value without permission is invalid |
| Store net and gross exposure as validated diagnostics | **ADAPT** | They are derived, but persist them with recomputation checks for reviewability |
| First implementation limited to long-only unlevered | **ADAPT** | A narrow first profile is safer while schema remains extensible |

## Target versus current holdings

Current holdings are an input to turnover-aware construction and later execution, not part of the target's economic identity. If a turnover constraint is used, the exact `PortfolioStateSnapshot` is a semantic input of construction and must be pinned.

For normalized long-only portfolios, a common two-sided turnover convention is:

```text
turnover = 0.5 * (sum_i(abs(target_i - current_i)) + abs(target_cash - current_cash))
```

That formula is not universal. Whether cash is included, whether one-way or round-trip turnover is reported, and how derivatives/notional are treated must be part of a named convention.

| Rule | Disposition |
|---|---|
| Declare the turnover convention and current-state snapshot | **ADOPT** |
| Let different consumers recompute an unnamed “turnover” | **REJECT** |
| Treat predicted turnover as realized turnover | **REJECT** |
| Persist predicted, planned and realized turnover as distinct metrics | **ADOPT** |

## Rebalance semantics

A vector has `as_of`, `decision_time`, `rebalance_time` and `valid_until`. Schedule identity includes exchange calendar and timezone. Multiple targets for the same mandate/rebalance event require a deterministic supersession rule; admission should normally choose the latest valid formally published vector, then pin that choice in the run/execution plan.

No-op is a valid result. If the target equals the current weights within a declared planning tolerance, execution emits an explicit no-op plan/receipt, not an absence of evidence.

| Rule | Disposition |
|---|---|
| Separate decision time from intended effective time | **ADOPT** |
| Recompute targets implicitly when a consumer opens an artifact | **REJECT** |
| Carry `valid_until` and stale-target rejection | **ADOPT** |
| Intraday event-driven supersession | **FUTURE** |

## Universe and instrument state

The decision universe is exact and immutable. Eligibility such as ST, suspension, listing age or limit state is time-dependent and must identify the PIT snapshot and policy used.

An instrument may be desired yet not currently executable. The original target remains unchanged; a risk policy may produce a risk-adjusted vector, or execution may retain the desire and report a blocked residual. The choice must be policy-driven and visible.

| State | Construction behavior | Later behavior | Disposition |
|---|---|---|---|
| Instrument absent from pinned universe | reject intent or explicit construction exclusion | never infer ticker match | **ADOPT** |
| Suspended | include/exclude only per pinned policy | execution reports blocked residual | **ADAPT** |
| ST/restricted | construction or risk policy may bound to zero | evidence policy and effective snapshot | **ADAPT** |
| Price-limit state | do not fabricate fillability | engine reports blocked/partial outcome | **ADOPT** |
| Missing identifier mapping | fail publication | no fuzzy/simplified mapping | **ADOPT** |
| Delisted/expired | explicit terminal policy | liquidation desire may remain unfilled until engine rules resolve | **ADAPT** |

## Optimizer relationship

An optimizer is a deterministic producer/transformer whose output can be admitted as a vector only with:

- input covariance/return/signal/current-weight artifact hashes;
- objective and all constraint versions;
- solver name/version, parameters and numerical tolerances;
- seed and thread/determinism settings where relevant;
- solver status, termination reason and feasibility residuals;
- any post-processing/rounding identity.

`optimal_inaccurate`, time limit, unavailable solver, NaN output or fallback to previous/equal weights are distinct outcomes. None may silently publish a formal target.

| Decision | Disposition |
|---|---|
| Optimizer outputs feed `TargetWeightVector` admission | **ADOPT** |
| Optimizer object or `weights_` array is the durable contract | **REJECT** |
| Explicit approved fallback creates a separately identified candidate | **ADAPT** |
| Non-converged result silently becomes formal | **REJECT** |

## Feasibility

Construction validates syntax, scope and configured constraints. Risk may add constraints later. Execution feasibility is state-dependent and cannot be guaranteed by construction. These three notions must remain separate:

1. `CONSTRUCTION_FEASIBLE` against pinned construction inputs;
2. `RISK_ADMISSIBLE` after risk transformation;
3. `EXECUTION_PLANNABLE`/`EXECUTION_REALIZED` against account and market state.

An infeasible portfolio produces a typed failure artifact with constraint conflicts and solver diagnostics. **REJECT:** best-effort row dropping, proportional renormalization or retention of old holdings without a named policy.
