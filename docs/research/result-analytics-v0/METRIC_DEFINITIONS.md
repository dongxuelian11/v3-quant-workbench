# Result Analytics V0 — Metric Definitions

Profile: `A_SHARE_DAILY_RESEARCH_V0`

These definitions are identity-bearing. A change to any policy field produces a different policy hash and therefore a different analytics identity.

## Policy identity

| Field | Frozen V0 value | Meaning |
|---|---|---|
| `return_convention` | `SIMPLE_NAV_RETURN` | Session return is `NAV[t] / NAV[t-1] - 1`. |
| `annualization_sessions` | `252` | Explicit research assumption; not inferred from dates or a hidden calendar. |
| `volatility_ddof` | `1` | Sample standard deviation. |
| `risk_free_policy` | `ZERO_RISK_FREE_ASSUMPTION` | Annual and session risk-free rates are exactly zero. This is an assumption, not a market rate. |
| `sortino_target` | `0` | Session minimum acceptable return. |
| `drawdown_convention` | `RUNNING_PEAK_TO_NAV` | `NAV[t] / running_peak_NAV[t] - 1`. |
| `turnover_convention` | `GROSS_TRADED_NOTIONAL_OVER_ARITHMETIC_MEAN_DAILY_NAV` | Both buy and sell consideration are counted; no half-turnover factor. |
| `period_return_convention` | `PERIOD_END_OVER_PREVIOUS_PERIOD_END` | Each completed observed period uses its final NAV and the preceding period's final NAV; the first observed period uses the first observed NAV as its base. |
| `missing_data_policy` | `FAIL_CLOSED_EXACT_SESSIONS` | Duplicate/out-of-order dates, non-positive NAV, nonfinite decimals, or benchmark date mismatch are rejected. |
| `numeric_precision` | `12` | Public numeric outputs are quantized to 12 decimal places with `ROUND_HALF_EVEN`, then serialized as canonical decimal strings. |

## Return series

Let ordered positive daily NAV values be `N[0] ... N[n-1]`.

- Start NAV: `N[0]`.
- End NAV: `N[n-1]`.
- Total return: `N[n-1] / N[0] - 1`.
- Session return for `t > 0`: `r[t] = N[t] / N[t-1] - 1`.
- The first row has typed session-return status `NOT_AVAILABLE` with reason `NO_PRIOR_SESSION`.
- Cumulative return at `t`: `N[t] / N[0] - 1`.
- Annualized return, when at least one session return exists: `(N[n-1] / N[0]) ** (252 / (n - 1)) - 1`.
- With one NAV observation, start/end/total return remain available, while annualized return is `INSUFFICIENT_SAMPLE`.

The exponentiation uses Python `Decimal` under a pinned local context and only the 12-place canonical result enters output identity.

## Monthly and yearly returns

NAV rows are grouped by calendar month or year.

- For the first observed period, the base is the first NAV in that period.
- For every later period, the base is the immediately preceding observed period-end NAV.
- Period return is `period_end_NAV / base_NAV - 1`.
- A first period containing one row therefore truthfully reports `0`; it does not invent a pre-window price.
- Labels are `YYYY-MM` and `YYYY` and rows include exact start/end session dates.

## Volatility

For `m` session returns and `ddof = 1`:

`mean = sum(r) / m`

`sample_variance = sum((r - mean)^2) / (m - 1)`

`annualized_volatility = sqrt(sample_variance) * sqrt(252)`

At least two session returns are required. Otherwise status is `INSUFFICIENT_SAMPLE`. A finite zero volatility is an available value of `0`.

## Drawdown

For each session:

`peak[t] = max(N[0] ... N[t])`

`drawdown[t] = N[t] / peak[t] - 1`

Maximum drawdown is the minimum drawdown value. The episode records:

- peak date: the most recent running-peak date preceding the selected trough;
- trough date: the first date attaining the selected minimum;
- recovery date: the first later date where NAV is greater than or equal to the episode peak NAV;
- duration sessions: peak-to-recovery index distance, or peak-to-final-observation distance when unrecovered;
- recovery status: `RECOVERED` or `UNRECOVERED`.

If no negative drawdown occurs, max drawdown is `0` and there is no episode.

## Sharpe ratio

V0 uses `ZERO_RISK_FREE_ASSUMPTION`; there is no market-rate claim.

`Sharpe = mean(r) / sample_stddev(r, ddof=1) * sqrt(252)`

It requires at least two session returns and non-zero sample standard deviation. Zero variance produces `NOT_AVAILABLE / ZERO_VARIANCE`, never NaN or infinity.

## Sortino ratio

The session target is the policy value `T = 0`.

`downside_deviation = sqrt(sum(min(r - T, 0)^2) / m)`

`Sortino = mean(r - T) / downside_deviation * sqrt(252)`

At least one session return is required. Zero downside deviation produces `NOT_AVAILABLE / ZERO_DOWNSIDE_DEVIATION`.

## Trading and cost analytics

Every fill must reconcile to its exact cash-ledger trade entry. Every non-zero fill cost must reconcile to exactly one `FEE` ledger entry with the same `fill_id`, negative amount, and identical fee breakdown. Any mismatch rejects analytics creation.

- Buy traded notional: sum of exact `Fill.consideration` where side is `BUY`.
- Sell traded notional: sum where side is `SELL`.
- Gross traded notional: buy plus sell traded notional.
- Commission, stamp duty, transfer fee, and exchange fee: sums from reconciled exact fee-ledger breakdowns.
- Total fees: sum of those four components.
- Fee / traded notional: `total_fees / gross_traded_notional`; when gross notional is zero, status is `NOT_AVAILABLE / NO_TRADES`.
- Observed fee load component: `total_fees / start_NAV`; this is a descriptive cost load, not a return.
- Average NAV denominator: arithmetic mean of every observed daily NAV in the result.
- Turnover: `gross_traded_notional / average_daily_NAV`.

There is deliberately no `pre_cost_return` field. Adding fees back to observed NAV is not a counterfactual no-cost backtest and must never be labelled as one.

## Benchmark

Benchmark input is optional and typed. V0 never downloads by symbol and never supplies a default index.

A `BenchmarkSeriesVersion` identity includes exact date/value rows, name, provenance references, alignment policy, and Truth/Admission ceiling.

- Absent benchmark: `BENCHMARK_NOT_AVAILABLE`; all benchmark-dependent metrics are typed `NOT_AVAILABLE`.
- V0 alignment: strategy and benchmark date tuples must match exactly. Extra, missing, duplicated, or reordered dates reject the request.
- Benchmark total return: `B[last] / B[first] - 1`.
- Relative NAV: `(N[t] / N[0]) / (B[t] / B[0])`.
- Session excess return: `r_strategy[t] - r_benchmark[t]`; first row is unavailable because no prior session exists.
- Tracking difference: `strategy_total_return - benchmark_total_return`.
- Tracking error: sample standard deviation of session excess returns times `sqrt(252)`; at least two excess-return observations are required.
- Alpha and beta: `NOT_AVAILABLE / OUTSIDE_V0_CLOSED_FORMULA`. V0 does not emit them because their regression, intercept, benchmark and sample policy are not yet identity-frozen.

Analytics Truth/Admission is the meet of the source result and benchmark ceilings. It can never exceed the source `BacktestRunResult`.

## Nonfinite and typed availability rules

- Decimal inputs must be finite; `NaN`, `Infinity`, and `-Infinity` are rejected before calculation.
- Public metrics use only `AVAILABLE`, `NOT_AVAILABLE`, or `INSUFFICIENT_SAMPLE`.
- `NOT_AVAILABLE` and `INSUFFICIENT_SAMPLE` carry no numeric value.
- The renderer displays the typed status/reason; it never substitutes zero.
