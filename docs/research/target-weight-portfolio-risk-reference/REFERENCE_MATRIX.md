# Target-weight / portfolio / risk OSS reference matrix

## Scope and method

This is an implementation-input study, not a proposal to replace the current Portfolio or Risk ASL contracts and not a backtest-engine study. Conclusions are derived from official repositories, documentation and tests at the pinned commits below. We learn boundaries, invariants and test ideas; we do not copy implementations.

| Project | Pinned source | License at pin | Examined surfaces |
|---|---|---|---|
| LEAN | [`QuantConnect/Lean@c6cc3b7`](https://github.com/QuantConnect/Lean/tree/c6cc3b743ed7b65d5e0b9fa2bfc18b7d3ac2aea0) | Apache-2.0 | `QCAlgorithm.Framework`, `Insight`, portfolio construction, `PortfolioTarget`, risk models, execution models and framework tests |
| FinRL-X | [`AI4Finance-Foundation/FinRL-Trading@e65d6f0`](https://github.com/AI4Finance-Foundation/FinRL-Trading/tree/e65d6f0483ead7d2ef4a5fc940cdf960392a25c1) | Apache-2.0 | weight-centric README, `BaseStrategy`, adaptive-rotation portfolio builder, execution engine and trade executor |
| WonderTrader | [`wondertrader/wondertrader@70feef1`](https://github.com/wondertrader/wondertrader/tree/70feef13ef7cbc6d4c3333a6158a92b919311d48) | MIT | strategy context target-position APIs, execution-unit APIs, portfolio/target merging, CTA/SEL behavior and backtest mocker checks |
| Qlib | [`microsoft/qlib@79633dd`](https://github.com/microsoft/qlib/tree/79633dd9506ea689e5400dea0197717b5b3d74b7) | MIT | `WeightStrategyBase`, target-weight-to-order generators and strategy documentation |
| skfolio | [`skfolio/skfolio@c06db84`](https://github.com/skfolio/skfolio/tree/c06db8406385cf4bce83577d0f0710ee5a27e67e) | BSD-3-Clause | optimizer `weights_`, budget/bounds/transaction-cost constraints, solver and fallback behavior |
| V3 baseline | `v3-quant-workbench@0ca9831` | Apache-2.0 | recovered contracts, StrategyDraft/BacktestHandoffDraft UI, portfolio/risk/backtest ASL fixtures |

License note: citations and architectural observations are used as reference material only. No third-party source is vendored or translated into V3 code by this study.

## Layer comparison

| Concern | LEAN | FinRL-X | WonderTrader | Limited references | V3 disposition |
|---|---|---|---|---|---|
| Signal boundary | `Insight` carries direction, magnitude, confidence and time semantics | strategies return a weight DataFrame directly | strategies calculate desired positions | Qlib accepts prediction scores | **ADAPT** — retain a separately versioned `SignalArtifact`; do not require every producer to jump directly to weights |
| Portfolio expression | portfolio-construction model emits `PortfolioTarget` | README calls target weights the sole inter-module interface | strategy/context emits target position | Qlib has `{instrument: weight}`; skfolio exposes optimizer weights | **ADOPT** — a weight vector is the stable desired-state boundary, with a stricter V3 envelope |
| Target unit | concrete target is quantity; percentage helper converts using live state | weight | target quantity/position | Qlib weight upstream then converts to orders | **ADAPT** — V3 stable artifact is weight; target quantity is an execution-plan derivative |
| Cash | implicit through remaining buying power/holdings | adaptive rotation records residual cash; general DataFrame contract is inconsistent | implicit in account/position mechanics | skfolio models portfolio budget, not execution cash | **ADAPT** — explicit cash plus an explicit exposure profile; never infer from omitted rows |
| Risk | receives proposed targets and emits overriding targets | risk/rules occur in strategy execution and trade executor | engine rules constrain target realization | skfolio embeds constraints in optimization | **ADOPT** — risk emits a new target derivative; **REJECT** in-place mutation or strategy-identity change |
| Execution | consumes targets and owns order placement | trade executor converts weights using account state | execution units consume merged positions | Qlib order generator converts desired weights | **ADOPT** — execution owns target/current reconciliation, lot rounding, orders, fills and residuals |
| Rebalance | portfolio construction decides whether to emit targets; execution works from latest targets | explicit scheduling/cooldown plus stateful current weights | scheduled SEL/CTA cycles | optimizer itself is schedule-agnostic | **ADAPT** — make decision time, effective rebalance time and validity explicit in artifacts |
| Multi-asset scope | symbols associated with insights/targets | DataFrame rows | SEL engine and portfolio target aggregation | Qlib target dictionary | **ADOPT** — bind exact `UniverseVersion` and define complete-scope membership semantics |
| Provenance | runtime objects/tags, insight IDs and framework state; not a durable content-addressed vector | metadata is free-form | operational logs/state | estimator attributes/config | **REJECT** as sufficient; V3 needs immutable identities, hashes and exact source snapshots |
| Failure semantics | conversion can return null/error; models and tests expose edge cases | some paths warn, normalize or use fallback prices | trading restrictions can prevent realization | skfolio can warn and set `weights_=None` when configured | **REJECT** silent fallback; every degradation must be typed and provenance-bearing |

## What the implementations actually establish

### LEAN

`QCAlgorithm.OnFrameworkData` evaluates Alpha, passes new insights to Portfolio Construction, lets Risk Management return target overrides, then passes final targets to Execution. This is strong evidence for stage ownership. However, `PortfolioTarget.Percent` depends on current total portfolio value, prices, leverage, buying power, lot size and holdings; the concrete target stores quantity. Therefore it is not a portable immutable weight artifact.

The framework's override merge is useful operationally, but V3 should preserve both before-risk and after-risk artifacts instead of collapsing them into one collection.

### FinRL-X

The README's weight-centric architecture is directionally aligned with V3. `StrategyResult.weights` is a `pandas.DataFrame`, and adaptive rotation adds a more structured `PortfolioWeights` with `cash_weight` and residual-to-cash behavior. Yet the general contract lacks a schema version, exact universe, time semantics, deterministic identity and required provenance. The trade executor also reads account state and converts weights to orders, confirming that conversion belongs downstream.

### WonderTrader

WonderTrader's important invariant is not the unit but the boundary: strategies set target positions; portfolio logic merges targets; execution units realize positions. Target-vs-current reconciliation and trading-rule failures belong after strategy evaluation. Its position-oriented interface should not replace V3's upstream weight artifact because it is already account/capital/unit sensitive.

### Qlib and skfolio

Qlib explicitly allows a strategy to focus on a target-weight position while an order generator compares it with current positions. This supports the desired-state boundary, but a plain dictionary is too weak for V3 provenance. skfolio clarifies that weight feasibility depends on explicit budget, bounds, costs, previous weights, solver and failure policy. An optimizer is a producer or transformer of a vector, not the vector's identity system.

## Reference decisions

| ID | Decision | Disposition | Reason |
|---|---|---|---|
| R-01 | Preserve Signal/Portfolio Construction/Risk/Execution stages | **ADOPT** | Common strong boundary across LEAN and the other references |
| R-02 | Make `TargetWeightVector` the stable desired-state handoff | **ADOPT** | Account-neutral enough for Strategy, Model, AI, Risk and simulation consumers |
| R-03 | Use LEAN `PortfolioTarget` as the V3 contract | **REJECT** | Concrete quantity conversion depends on live account and security state |
| R-04 | Treat FinRL-X's arbitrary DataFrame as sufficient contract | **REJECT** | Missing identity, exact bindings, cash/profile and failure semantics |
| R-05 | Preserve explicit residual cash from FinRL-X | **ADAPT** | Generalize to exposure profiles including short/leverage cases |
| R-06 | Preserve WonderTrader target-position separation | **ADAPT** | Keep the separation but place position conversion after the weight boundary |
| R-07 | Use Qlib's target-weight/order-generator split | **ADAPT** | Add immutable envelope, full universe scope and provenance |
| R-08 | Adopt skfolio optimizer constraint vocabulary | **ADAPT** | Useful inputs/evidence, but library objects are not cross-domain artifacts |
| R-09 | Silently renormalize, reuse prior weights or invent prices | **REJECT** | Changes meaning while hiding a failure |
| R-10 | Add tax-aware lots and prime-broker margin models now | **FUTURE** | Requires product scope and execution/accounting contracts beyond this study |
