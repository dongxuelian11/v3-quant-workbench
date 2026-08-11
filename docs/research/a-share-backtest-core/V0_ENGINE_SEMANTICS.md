# Track J V0 Engine Semantics

The core is a deterministic daily/EOD research engine. It consumes only the canonical W0 `RiskAdjustedWeightVector` and produces immutable, content-addressed evidence. It has no broker, network, live or paper-trading adapter.

## Temporal contract at raw open

- `ScheduledWeights.effective_at` must exactly equal `vector.source_target.rebalance_time`. The scheduler cannot invent a second effective timestamp.
- `ExecutionTimingProfileVersion` is a content-addressed RunSpec input. The bundled `CN_A_SHARE_RAW_OPEN_2026_07_06_V1` profile uses `Asia/Shanghai`, the convention `NEXT_ELIGIBLE_SESSION_RAW_OPEN`, strict eligibility `effective_at < 09:15`, and raw-open execution timestamp `09:25`.
- The 09:15 cutoff is the start of the official opening call auction. Information arriving at 09:15 or later can influence or follow opening-price formation and is therefore ineligible for that session's raw open. It waits for the next supplied session whose calendar state is open.
- A closed/holiday/weekend session does not consume a scheduled vector. For each actual open, all eligible vectors are considered together and exactly the latest is selected (`LATEST_ELIGIBLE_VECTOR_PER_SESSION_OPEN`); earlier eligible vectors are superseded rather than executed sequentially.
- The selected vector must still be valid at the pinned 09:25 raw-open execution timestamp: `execution_timestamp <= source_target.valid_until`. Expiry fails closed with `ExpiredScheduledWeightsError`.

## Daily event order

1. Open the pinned trading session and unlock holdings acquired before that session (T+1).
2. Apply separately supplied corporate actions. Cash dividends and integer-ratio bonus/split actions are supported; all other types fail closed as `NOT_SUPPORTED`.
3. Resolve the latest temporally eligible W0 vector and calculate target quantities from pre-trade NAV and raw matching prices.
4. Create deterministic sell-then-buy orders sorted by instrument ID.
5. Evaluate suspension, tradability, buy restriction, price-limit, T+1, long-only, lot and cash constraints.
6. Resolve exactly one market cost rule for `(board, session_date)`, produce fills and diagnostics, then update cash and position ledgers.
7. Value holdings at raw EOD close. A missing close fails closed; no adjusted price or implicit forward-fill is used.
8. Emit holding snapshots, NAV and a content-addressed `BacktestRunResult`.

## Quantity, fill and fee rules

- Weight vectors are not mutated or copied into a replacement DTO. Their canonical IDs, hashes and exact W0 timing enter the run identity.
- An absent W0 member means zero target weight under the W0 seam. Buy targets round down to the board profile's minimum/step. Sells may dispose of a complete odd-lot remainder.
- Same-session acquisitions are non-sellable. They become sellable at the next supplied open session.
- Daily bars do not justify intraday liquidity assumptions. A fill is all-or-constrained at the raw open: sell fills can be capped by T+1/holdings; buy fills can be reduced in lot steps by cash and fees. Every residual receives a diagnostic.
- Suspension/non-tradable sessions, restricted buys, limit-up buys and limit-down sells produce no fill.
- Broker commission and minimum commission are global contractual inputs. Stamp duty is global only while its official effective period is pinned. Transfer and exchange handling fees are `MarketCostRule` inputs scoped by board and inclusive effective period.
- `CostPolicyVersion.calculate(board, side, consideration, session_date)` must resolve exactly one rule. Missing or overlapping rules fail closed during RunSpec construction for every instrument and supplied session.
- Commission, stamp duty, transfer fee and exchange handling fee are separate decimal values with half-up currency rounding. Each fee cash-ledger entry embeds the exact `CostBreakdown` used by its fill.
- There is no shorting, leverage, margin, borrowing, futures, options, intraday or tick execution.

## Identity and truth

The run specification pins code/runtime/environment, W0 schedule and timestamps, execution timing profile, input object hashes, engine version, trading-rule profile, market/effective-period cost schedule, initial state and valuation convention. The result truth is the meet of all admitted upstream truths and is capped at `PRE_ALPHA`. A deterministic rerun with the same exact inputs must produce the same IDs and wire representation.
