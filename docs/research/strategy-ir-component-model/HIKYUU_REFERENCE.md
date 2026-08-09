# Hikyuu Strategy/System component reference

## Scope and evidence pin

This study is implementation input for V3 Strategy Lab. It is not a Hikyuu port and does not change a production contract. Source observations are pinned so later work can reproduce the study.

| Source | Pin | License | Use in this study | Disposition |
|---|---|---|---|---|
| [fasiondog/hikyuu](https://github.com/fasiondog/hikyuu/tree/7e1a61d98cf4efa5dbac5a4feab749e28dbe5b95) | `7e1a61d98cf4efa5dbac5a4feab749e28dbe5b95` | Apache-2.0 | Primary component, lifecycle, composition and test reference | ADAPT |
| [QuantConnect/Lean](https://github.com/QuantConnect/Lean/tree/c6cc3b743ed7b65d5e0b9fa2bfc18b7d3ac2aea0) | `c6cc3b743ed7b65d5e0b9fa2bfc18b7d3ac2aea0` | Apache-2.0 | Narrow corroboration of Alpha/Portfolio/Risk/Execution separation | ADAPT |
| [wondertrader/wondertrader](https://github.com/wondertrader/wondertrader/tree/70feef13ef7cbc6d4c3333a6158a92b919311d48) | `70feef13ef7cbc6d4c3333a6158a92b919311d48` | MIT | Narrow corroboration of strategy target-position and execution separation | ADAPT |
| V3 baseline | `0ca98311b15971ea31039c6faed1a3be09a40357` | Repository license | Current Visual/Code/Split, StrategyDraft, handoff and worker boundaries | ADOPT |

Only invariants, interface ideas and test ideas are learned. No upstream implementation is copied.

## Hikyuu component map

The central Hikyuu [`System`](https://github.com/fasiondog/hikyuu/blob/7e1a61d98cf4efa5dbac5a4feab749e28dbe5b95/hikyuu_cpp/hikyuu/trade_sys/system/System.h) composes a TradeManager with Environment, Condition, Signal, MoneyManager, Stoploss, Takeprofit, ProfitGoal and Slippage parts. A higher-level [`Portfolio`](https://github.com/fasiondog/hikyuu/blob/7e1a61d98cf4efa5dbac5a4feab749e28dbe5b95/hikyuu_cpp/hikyuu/trade_sys/portfolio/Portfolio.h) combines Selector and AllocateFunds over System prototypes/instances.

| Hikyuu part | Observed responsibility | Lifecycle/dependencies | V3 reading | Disposition |
|---|---|---|---|---|
| [`EnvironmentBase`](https://github.com/fasiondog/hikyuu/blob/7e1a61d98cf4efa5dbac5a4feab749e28dbe5b95/hikyuu_cpp/hikyuu/trade_sys/environment/EnvironmentBase.h) | Produces a dated market-regime validity/value series and is explicitly independent of the traded object | `setQuery` → `_calculate`; may be shared; `reset`/`clone` | A pure, reusable regime/gate component with an explicit time-series input | ADAPT |
| [`ConditionBase`](https://github.com/fasiondog/hikyuu/blob/7e1a61d98cf4efa5dbac5a4feab749e28dbe5b95/hikyuu_cpp/hikyuu/trade_sys/condition/ConditionBase.h) | Produces per-system validity; may depend on KData, TradeManager and Signal | `setTO`, `setTM`, `setSG` → `_calculate`; `reset`/`clone` | A typed eligibility gate; do not retain its account or signal-object backreferences | ADAPT |
| [`SignalBase`](https://github.com/fasiondog/hikyuu/blob/7e1a61d98cf4efa5dbac5a4feab749e28dbe5b95/hikyuu_cpp/hikyuu/trade_sys/signal/SignalBase.h) | Calculates dated positive buy values and negative sell values; supports logical/arithmetic composition | `setTO` triggers calculation and memoization; cycle, alternation and short support are parameters | A first-class, immutable SignalArtifact producer | ADOPT |
| [`StoplossBase`](https://github.com/fasiondog/hikyuu/blob/7e1a61d98cf4efa5dbac5a4feab749e28dbe5b95/hikyuu_cpp/hikyuu/trade_sys/stoploss/StoplossBase.h) | Computes planned long/short protective prices | KData and TradeManager are injected; reset/clone | A pure exit-policy/constraint node that emits an intent attribute, not an order | ADAPT |
| Takeprofit slot | `System` uses another `StoplossBase` instance for a trailing/monotonic take-profit threshold | Same lifecycle as Stoploss; evaluation order is encoded in System | Keep a distinct typed semantic role even when implementation is shared | ADAPT |
| [`ProfitGoalBase`](https://github.com/fasiondog/hikyuu/blob/7e1a61d98cf4efa5dbac5a4feab749e28dbe5b95/hikyuu_cpp/hikyuu/trade_sys/profitgoal/ProfitGoalBase.h) | Computes an absolute profit goal or holding-day exit | KData and TradeManager are injected; buy/sell notifications update state | Model separately from take-profit because goal and trailing-exit semantics differ | ADAPT |
| [`MoneyManagerBase`](https://github.com/fasiondog/hikyuu/blob/7e1a61d98cf4efa5dbac5a4feab749e28dbe5b95/hikyuu_cpp/hikyuu/trade_sys/moneymanager/MoneyManagerBase.h) | Converts opportunity, price and risk into buy/sell quantity and receives trade notifications | Reads TradeManager; stateful; reset/clone | Preserve signal/sizing separation, but make sizing pure over an explicit PortfolioStateSnapshot | ADAPT |
| [`SelectorBase`](https://github.com/fasiondog/hikyuu/blob/7e1a61d98cf4efa5dbac5a4feab749e28dbe5b95/hikyuu_cpp/hikyuu/trade_sys/selector/SelectorBase.h) | Selects weighted System instances from prototypes across multiple instruments | Holds prototypes, calculates by query, can account for already-running real systems | Explicit multi-instrument selection stage producing a SelectedUniverse/SelectionArtifact | ADAPT |
| [`SlippageBase`](https://github.com/fasiondog/hikyuu/blob/7e1a61d98cf4efa5dbac5a4feab749e28dbe5b95/hikyuu_cpp/hikyuu/trade_sys/slippage/SlippageBase.h) | Transforms planned buy/sell price into a simulated real price | Bound to raw KData; deterministic and stochastic implementations exist | Belongs to Backtest/Execution configuration, not canonical Strategy identity | REJECT |
| [`AllocateFundsBase`](https://github.com/fasiondog/hikyuu/blob/7e1a61d98cf4efa5dbac5a4feab749e28dbe5b95/hikyuu_cpp/hikyuu/trade_sys/allocatefunds/AllocateFundsBase.h) | Allocates relative weights/cash among selected/running systems and coordinates shadow accounts | Reads TradeManager and Portfolio shadow cash account | Preserve allocation as a PortfolioIntent stage; reject account mutation and shadow-account ownership | ADAPT |
| `System` | Orchestrates all parts and calls TradeManager buy/sell methods | Validates required parts, injects mutable dependencies, loops bars and mutates an account | Use only as a composition/lifecycle reference; V3 Strategy must not own execution | REJECT |
| `Portfolio` | Schedules rebalance, invokes Selector/AllocateFunds and runs real systems | Owns real and shadow TradeManagers and mutable System instances | Keep scheduling/selection/allocation concepts, but separate pure intent from execution/accounting | ADAPT |

## How Hikyuu composes parts

1. A System is assembled by setters (`setTM`, `setMM`, `setEV`, `setCN`, `setSG`, `setST`, `setTP`, `setPG`, `setSP`) or by the `SYS_Simple` creator. `readyForRun` fails when TradeManager, MoneyManager or Signal is absent and injects TradeManager/Signal into dependent parts. **Disposition: ADAPT** — V3 should validate required typed inputs, but inject immutable evaluation context rather than live mutable services.
2. Environment, Condition and Signal expose algebraic/logical combinators implemented as component objects. **Disposition: ADOPT** — typed composition is the right basis for both a node graph and code DSL.
3. `setTO` binds KData and triggers component calculation. Adjusted KData is sent to Signal/Condition/Stoploss/Takeprofit while raw KData is sent to ProfitGoal/Slippage. **Disposition: ADAPT** — the distinction is valuable, but V3 must encode price-basis and adjustment policy in every input port rather than hide it in orchestration.
4. Selector associates stock lists with System prototypes, then produces weighted System instances. Portfolio combines Selector with AllocateFunds and a rebalance schedule. **Disposition: ADAPT** — V3 should make selection and allocation explicit artifacts instead of mutable object graphs.
5. Component classes share a parameter mechanism (`PARAMETER_SUPPORT_WITH_CHECK`), names, clone/reset hooks and optional serialization. **Disposition: ADAPT** — V3 should use schema-versioned, closed, canonical parameters and immutable nodes; clone/reset are runtime implementation details, not persisted semantics.

## Observed lifecycle

The main sequence is visible in [`System.cpp`](https://github.com/fasiondog/hikyuu/blob/7e1a61d98cf4efa5dbac5a4feab749e28dbe5b95/hikyuu_cpp/hikyuu/trade_sys/system/System.cpp):

| Phase | Hikyuu behavior | V3 implication | Disposition |
|---|---|---|---|
| Construct/configure | Create component instances and mutate named parameters | Draft editing may be mutable, but publish must freeze a canonical semantic snapshot | ADAPT |
| Clone/reset | Clone parts according to `shared_*` flags; reset cached/position-sensitive state | Never let sharing policy change StrategyVersion semantics; each evaluation gets isolated state | ADAPT |
| Bind inputs | `setTO` obtains KData and propagates adjusted/raw series; Environment and MoneyManager receive query | Resolve exact Dataset/Snapshot/Universe before evaluation and supply read-only handles | ADOPT |
| Prepare | `readyForRun` checks TM/MM/SG and wires TM/SG dependencies | Compile/validate all ports, capabilities and required bindings before dispatch | ADOPT |
| Bar open | Reject malformed OHLC and process delayed requests | Data-quality diagnostics and delayed execution belong to data/engine stages | ADAPT |
| Bar close | Evaluate Environment, then Condition, then Signal, then Stoploss/ProfitGoal/Takeprofit with early returns | Precedence is semantic and must be explicit in IR; do not rely on incidental node traversal order | ADAPT |
| Size and price | MoneyManager returns quantity; Slippage returns real price | Strategy may emit sizing intent; simulated/real price conversion belongs downstream | ADAPT |
| Mutate | System calls TradeManager buy/sell and notifies MoneyManager/ProfitGoal | Strategy must instead emit immutable SignalArtifact/PortfolioIntent | REJECT |
| Finish | Cache `m_calculated`, retain account/trade state, expose last suggestion | Evaluation outputs and diagnostics are immutable artifacts; cache keys include all exact inputs | ADAPT |

The upstream tests are unusually valuable. [`test_Simple_SYS_for_base.cpp`](https://github.com/fasiondog/hikyuu/blob/7e1a61d98cf4efa5dbac5a4feab749e28dbe5b95/hikyuu_cpp/unit_test/hikyuu/trade_sys/system/test_Simple_SYS_for_base.cpp) asserts missing required parts, exact timestamps, delayed versus same-bar behavior, planned/real price, quantity, cash and provenance `SystemPart`. Selector, allocation, portfolio, slippage, stoploss and deterministic-tie tests live under [`unit_test/hikyuu/trade_sys`](https://github.com/fasiondog/hikyuu/tree/7e1a61d98cf4efa5dbac5a4feab749e28dbe5b95/hikyuu_cpp/unit_test/hikyuu/trade_sys). **Disposition: ADOPT** — port the categories of tests, not their implementation.

## Parameterization and reproducibility assessment

| Observation | Assessment for V3 | Disposition |
|---|---|---|
| Parameters are named, checked and serialized by each component | Require a closed JSON Schema per component type/version, defaults expanded at compile time, units explicit and unknown fields rejected | ADAPT |
| Components can be cloned and reset | Evaluation isolation is necessary, but an immutable IR plus fresh worker state is safer than persisting clone/share flags | ADAPT |
| Query/KData are explicit runtime bindings | Pin DatasetVersion, DataSnapshotVersion, UniverseVersion, member artifact hash, calendar, frequency, adjustment basis and as-of boundary | ADOPT |
| Cached calculation and shared parts are mutable | They can leak stale/cross-run state and must not participate in canonical semantics | REJECT |
| Some slippage models draw from distributions | A seed and RNG algorithm/version would be required for reproducibility; preferably keep them in engine configuration | REJECT |
| Serialization can retain calculated values but omits some runtime bindings | Persist definitions and immutable outputs separately; never infer missing runtime bindings during replay | ADAPT |
| Selection/order can be sensitive to ties and container iteration | Define total ordering by score then stable `instrument_id`; test identical output across process/thread counts | ADOPT |

## Separation lessons

### Signal generation versus money management

Hikyuu distinctly models Signal and MoneyManager, and MoneyManager receives opportunity/risk information to compute quantity. This is a mature separation worth keeping. Hikyuu's MoneyManager also reads TradeManager and receives fills, which makes it stateful and account-coupled. V3 should instead pass a versioned, read-only PortfolioStateSnapshot into a pure sizing/allocation stage and emit PortfolioIntent. **Disposition: ADAPT**.

### Strategy versus execution

Hikyuu System crosses this boundary by invoking TradeManager. LEAN's [`ProcessInsights`](https://github.com/QuantConnect/Lean/blob/c6cc3b743ed7b65d5e0b9fa2bfc18b7d3ac2aea0/Algorithm/QCAlgorithm.Framework.cs#L166-L244) supplies the better invariant: Alpha/Insight → PortfolioConstruction targets → Risk overrides → Execution. WonderTrader likewise documents “strategy only sets target position; backend executes”, merges target positions before execution, and exposes a separate executor target interface in [`ExecuteDefs.h`](https://github.com/wondertrader/wondertrader/blob/70feef13ef7cbc6d4c3333a6158a92b919311d48/src/Includes/ExecuteDefs.h). **Disposition: ADOPT**.

### Multi-instrument/selector boundary

Hikyuu's Selector selects System instances while Portfolio/AllocateFunds decides capital distribution. V3 should preserve the boundary but normalize its output: a Selector consumes a pinned candidate universe and emits a SelectedUniverse/SelectionArtifact; strategy components then emit cross-sectional SignalArtifact rows; allocation emits PortfolioIntent. A per-instrument signal node may not expand its own universe. **Disposition: ADAPT**.

## What not to carry into V3

| Upstream behavior | Reason | Disposition |
|---|---|---|
| Live TradeManager inside Strategy/System | Lets strategy mutate holdings/cash and makes replay depend on hidden state | REJECT |
| Database/StockManager discovery from strategy code | Breaks exact input binding, authorization and PIT provenance | REJECT |
| Slippage and fill simulation inside canonical strategy | Mixes hypothesis identity with execution scenario | REJECT |
| Mutable shared component flags as persisted semantics | Results can change with clone/reset topology | REJECT |
| Implicit precedence through C++ control flow | Visual/code projections cannot reliably explain or round-trip hidden ordering | REJECT |
| Arbitrary in-process Python/C++ extension hooks | No capability, resource or provenance boundary | REJECT |

## Mature reference conclusion

Hikyuu is strongest as a vocabulary and test reference: explicit component roles, component algebra, parameter checking, required-part validation, reset/clone awareness, per-stage tests and a Selector/AllocateFunds boundary. Its direct account/execution ownership is intentionally not the V3 target. The canonical V3 Strategy IR should therefore retain the component model while changing the runtime contract from “components orchestrate trades” to “immutable definition evaluates pinned inputs and emits immutable intent artifacts.” **Disposition: ADAPT**.
