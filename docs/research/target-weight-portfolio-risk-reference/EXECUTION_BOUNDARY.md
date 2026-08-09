# Execution boundary

## Ownership statement

Backtest and live Execution accept a desired portfolio artifact; Strategy/Model/AI never write an account. Execution planning owns the conversion from a risk-admitted weight vector plus pinned account and market state into target quantities and order deltas. The engine owns order simulation/routing, fills and ledger changes.

```text
RiskAdjustedWeightVector
  + PortfolioStateSnapshot
  + MarketStateSnapshot
  + ExecutionPolicyVersion
  + InstrumentRuleProfileVersion
        -> ExecutionPlan
        -> TargetQuantityVector / OrderIntents
        -> Engine-specific Orders
        -> Fills
        -> Holdings / Ledger / ResidualReport
```

LEAN's `PortfolioTarget.Percent` confirms why the adapter is downstream: conversion depends on total portfolio value, free portfolio buffer, security price, leverage, buying power, lot size and current holdings. WonderTrader and Qlib independently demonstrate target-vs-current order generation. V3 should keep that state out of `TargetWeightVector`.

## Inputs and outputs

| Object | Owned by | Must include |
|---|---|---|
| `RiskAdjustedWeightVector` | Risk | immutable desired weights and lineage to original target |
| `PortfolioStateSnapshot` | Account/ledger service | exact holdings, cash, unsettled/frozen quantities, open orders and valuation basis |
| `MarketStateSnapshot` | market-data/runtime boundary | prices, status, limits, FX and timestamps used for planning |
| `ExecutionPolicyVersion` | execution domain | rebalance algorithm, rounding, cash buffer, order type, sequencing and retry rules |
| `InstrumentRuleProfileVersion` | rule/catalog domain | lot, T+1, ST, suspension, price-limit and delisting rules |
| `ExecutionPlan` | execution planner | target quantities, deltas, estimated costs/turnover, blocked items and idempotency identity |
| `Order/Fills/Ledger` | engine/account domain | actual state transitions and provenance to the plan |

## Target-to-order rules

1. Reject stale or not-yet-effective vectors.
2. Resolve every `instrument_id` exactly; never fuzzy-map tickers.
3. Value the account using the pinned planning valuation snapshot.
4. Convert weights to theoretical quantities using the named denominator and instrument multiplier.
5. Apply deterministic lot/tick/precision rounding and cash-buffer rules.
6. Compare target quantities with current, frozen and open-order-adjusted positions.
7. Apply buying-power, short-locate, T+1 and market-status checks.
8. Create ordered order intents or explicit blocked/no-op residuals.
9. Give the plan a deterministic idempotency key based on target, account, rebalance event and policies.
10. Let the engine create orders/fills; never back-propagate realized holdings into strategy identity.

## Blocked and partial realization

Suspended/ST/limit-state/missing-price instruments expose the key difference between desire and realization:

- the target remains immutable;
- the plan records the intended target and the executable subset;
- a blocked residual identifies instrument, desired delta, reason, market/rule snapshot and next policy action;
- partial fills update ledger state, not target state;
- replanning creates a new `ExecutionPlanAttempt` referencing the same target or a newly risk-adjusted target as policy requires.

**REJECT:** deleting a blocked row and renormalizing the target inside the engine. That changes portfolio intent without producing a portfolio/risk artifact.

## Rebalance and idempotency

At-most-once intent admission and exactly-once ledger effects are separate. Repeated delivery of the same target/account/rebalance event must not duplicate orders. A retry is a new attempt under the same execution-plan identity unless its semantic inputs changed; changed market/account snapshots may require a new plan revision with a causal link.

Multiple vectors for one rebalance event need an explicit supersession decision before order creation. An already partially executed plan cannot be erased; cancellation/replacement must preserve the audit chain.

## Backtest adapter

The backtest adapter consumes the same target semantics as live execution but applies a pinned simulated account, market timeline, fee/slippage/rule profiles and engine version. This does not make the strategy call the engine. The run specification selects an admitted adapter and pins all inputs.

Target identity should be reusable across backtest and live planning only when time, universe and admissibility conditions permit. Execution plan identity and results will differ because account/market/policy inputs differ.

This study does not specify fill models or backtest accounting. It only fixes the boundary.

## Decisions

| ID | Decision | Disposition |
|---|---|---|
| E-01 | Execution consumes risk-admitted target weights | **ADOPT** |
| E-02 | Strategy writes holdings, orders or broker APIs | **REJECT** |
| E-03 | Account/price/lot-aware conversion occurs downstream | **ADOPT** |
| E-04 | Persist target quantities separately from target weights | **ADOPT** |
| E-05 | Blocked/partial/no-op outcomes are first-class evidence | **ADOPT** |
| E-06 | Engine silently drops rows or renormalizes weights | **REJECT** |
| E-07 | Same semantic contract for backtest and live adapters | **ADAPT** |
| E-08 | Smart order routing and venue optimization in this phase | **FUTURE** |
