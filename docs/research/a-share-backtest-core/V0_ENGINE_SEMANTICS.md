# Track J V0 Engine Semantics

The core is a deterministic daily/EOD research engine. It consumes only the canonical W0 `RiskAdjustedWeightVector` and produces immutable, content-addressed evidence. It has no broker, network, live or paper-trading adapter.

## Daily event order

1. Open the pinned trading session and unlock holdings acquired before that session (T+1).
2. Apply separately supplied corporate actions. Cash dividends and integer-ratio bonus/split actions are supported; all other types fail closed as `NOT_SUPPORTED`.
3. Consume scheduled W0 weights and calculate target quantities from pre-trade NAV and raw matching prices.
4. Create deterministic sell-then-buy orders sorted by instrument ID.
5. Evaluate suspension, tradability, buy restriction, price-limit, T+1, long-only, lot and cash constraints.
6. Produce fills and explicit unfilled/rejected diagnostics; update cash and position ledgers.
7. Value holdings at raw EOD close. A missing close fails closed; no adjusted price or implicit forward-fill is used.
8. Emit holding snapshots, NAV and a content-addressed `BacktestRunResult`.

## Quantity, fill and fee rules

- Weight vectors are not mutated or copied into a replacement DTO. Their canonical IDs and hashes enter the run identity.
- An absent W0 member means zero target weight under the W0 seam. Buy targets round down to the board profile's minimum/step. Sells may dispose of a complete odd-lot remainder.
- Same-session acquisitions are non-sellable. They become sellable at the next supplied open session.
- Daily bars do not justify intraday liquidity assumptions. A fill is all-or-constrained at the raw open: sell fills can be capped by T+1/holdings; buy fills can be reduced in lot steps by cash and fees. Every residual receives a diagnostic.
- Suspension/non-tradable sessions, restricted buys, limit-up buys and limit-down sells produce no fill.
- Commission, minimum commission, seller-only stamp duty, transfer fee and exchange fee are independently parameterized. Decimal arithmetic and half-up currency rounding are mandatory.
- There is no shorting, leverage, margin, borrowing, futures, options, intraday or tick execution.

## Identity and truth

The run specification pins code/runtime/environment, schedule, input object hashes, engine version, rule profile, cost profile, initial state and valuation convention. The result truth is the meet of all admitted upstream truths and is capped at `PRE_ALPHA`. A deterministic rerun with the same exact inputs must produce the same IDs and wire representation.
