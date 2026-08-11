# Track F bounded Reuse / Adoption report

## Decision

Track F uses a small V3-native closed Strategy IR compiler/evaluator while selectively reusing the repository's existing canonical JSON/hash implementation, A0 truth/admission lattice, and Track C `DatasetVersion` / `FactorEvaluation` / `FeatureMaterialization` types. External frameworks remain design and test references only. No upstream implementation is copied, and no new runtime dependency is added.

The scan was bounded to implementation-critical candidates. Current upstream state was read from official GitHub repositories because Context7 MCP was unavailable in this execution environment.

## Evidence pins

| Candidate | Current pin observed 2026-08-11 | License | Maintenance / release evidence | Adoption |
|---|---|---|---|---|
| Hikyuu | `fasiondog/hikyuu@7e1a61d98cf4efa5dbac5a4feab749e28dbe5b95` | Apache-2.0 | pushed 2026-08-05; release `2.8.1` on 2026-07-09; extensive `trade_sys` unit tests | Design / Algorithm Reference |
| vn.py including `vnpy.alpha` | `vnpy/vnpy@fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09` | MIT | pushed 2026-08-06; release `4.4.0` on 2026-05-14; alpha tests present | Design / Algorithm Reference |
| Qlib | `microsoft/qlib@79633dd9506ea689e5400dea0197717b5b3d74b7` | MIT | pushed 2026-07-23; release `v0.9.7`; broad pytest/dev surface | Design / Algorithm Reference |
| NetworkX | `networkx/networkx@7c635c9e05da7873cd53a919434e36a137e70fe1` | BSD-3-Clause | pushed 2026-08-11; release `3.6.1`; dedicated DAG algorithms/tests | Reject direct dependency; native bounded DAG validation |
| Pydantic | `pydantic/pydantic@c67a1397327c6abc1a2e2e921af01aebbbeedf1c` | MIT | pushed 2026-08-10; release `2.13.4`; mature validation/tests | Reject new Track F authority/dependency; existing V3 dataclass boundary is sufficient |

The Hikyuu current pin exactly matches the accepted Strategy IR research pin, so no current-source drift invalidated the already accepted component invariants.

## Adoption Gate

| Criterion | Hikyuu | vn.py / vnpy.alpha | Qlib | NetworkX | Pydantic |
|---|---|---|---|---|---|
| Functional coverage | Rich component/System/Selector/AllocateFunds vocabulary | Alpha signal, target-position and execution workflow | Signal strategies, ranking, position and order generation | Cycle detection and topological ordering only | Closed typed validation only |
| Test quality | Strong component and lifecycle tests | Alpha and platform tests; strategy is engine-coupled | Broad project tests, but strategy semantics are backtest-coupled | Mature focused algorithm tests | Mature validation and property-test culture |
| Windows / Python 3.14 | Windows paths exist; current packaging does not explicitly prove Python 3.14 | Windows supported; classifiers stop at Python 3.13 | classifiers stop at Python 3.12 | OS-independent; Python 3.14 supported except 3.14.1 | OS-independent; Python 3.14 supported |
| Determinism / reproducibility | Useful reset/clone warnings, but mutable caches/shared parts and account state remain | mutable positions/orders/engine callbacks | mutable infrastructure, exchange, calendar and position; dynamic config | deterministic graph algorithms when callers provide stable nodes | deterministic validation, not financial semantics |
| API stability | mature but C++/Python object lifecycle is not V3 IR | production-stable platform API, wrong ownership boundary | alpha-stage package and configuration-driven APIs | production-stable | production-stable |
| Dependency weight | full C++/Python quant framework | Qt, pandas, NumPy, TA-Lib, plotting, alpha/ML extras | pandas, NumPy, MLflow, LightGBM, cvxpy and more | zero core dependencies but still a new package for a small subproblem | native core dependency and Rust extension |
| Isolation | would require a large adapter/worker boundary | strategy directly holds `BacktestingEngine` and trading state | strategy directly holds exchange/account/backtest infrastructure | pure in-process library | pure validation library |
| PIT / truth compatibility | hidden data/account discovery and execution must be removed | no V3 exact binding or admission lattice | no V3 exact binding or admission lattice | no financial/PIT semantics | no financial/PIT semantics |
| Exact identity / provenance | mutable serialized objects are not canonical V3 identity | settings/object state are not canonical content identity | config/model/dataset objects do not satisfy V3 definition/binding identity | no component/registry/compiler identity | validation schema is not executable Strategy identity |
| NaN / missing / error semantics | component-specific and runtime-dependent | platform/strategy-specific | `pred_score is None` may become an empty trade decision | explicit graph exceptions only | explicit validation errors only |
| Safe artifact format | not V3 Artifact-owned | orders/trades/dataframes cross the strategy boundary | signals, positions and orders are framework objects | graph container only | validated Python objects only |
| Silent fallback risk | cached/shared lifecycle state | unknown settings are ignored when attributes are absent; mutable engine behavior | missing signal can return an empty `TradeDecisionWO` | low for graph validation | low for validation |
| Second-authority risk | high if System/Portfolio becomes canonical | high if AlphaStrategy owns signal/order/position truth | high if Qlib config/recorder/strategy becomes canonical | low, but cannot own V3 typed semantics | medium if schemas replace V3 domain invariants |

## Why higher-priority reuse modes were not selected

1. **Direct dependency:** Hikyuu, vn.py and Qlib cross forbidden Backtest/Execution/account/order boundaries. NetworkX and Pydantic do not provide the V3 financial contract, identity or truth semantics that dominate this implementation.
2. **Thin adapter:** adapting framework strategy objects would preserve hidden mutable state, engine capabilities and second-authority risk rather than remove them.
3. **Isolated Worker / API / CLI:** V0 is a small pure batch evaluator. Isolating a full trading framework would add packaging, IPC and artifact translation without satisfying the canonical owner boundary.
4. **Selective module reuse:** no external module is needed. The implementation selectively reuses V3-owned `canonical_sha256`, `TruthAdmissionState`/`propagate_downstream_ceiling`, and exact Track C domain objects.
5. **Design / Algorithm Reference:** retain Hikyuu component vocabulary and required-part tests, vn.py/Qlib ranking and signal/portfolio separation lessons, and NetworkX-style deterministic Kahn topological validation.
6. **V3 Native:** implement only the missing closed typed IR, exact evaluation binding, deterministic component runtime, and Track F artifacts.

## Resulting dependency boundary

The Track F runtime imports only Python standard-library modules and existing V3-owned modules. It has no repository, database, filesystem, network, Backtest, broker, order, fill, ModelVersion or PredictionArtifact capability. Future model output can enter only through `GenericAdmittedArtifactReference`, which is an exact external-owner reference and does not define a Model or Prediction owner.
