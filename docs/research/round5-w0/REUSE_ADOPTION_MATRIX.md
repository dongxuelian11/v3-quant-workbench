# Round 5 W0 Reuse / License / PIT / Data-Semantics Adoption Matrix

Task: `V3-ROUND5-W0-AGENT-RESEARCH-LOOP-AND-FACTOR-ASSET-FOUNDATION-01`

Baseline: `dongxuelian11/v3-quant-workbench@a22092ea1a840f6e9bb790178eda0415379a8fdd`

Observed: 2026-08-12 (Asia/Shanghai). Context7 was not configured in this execution environment, so current library facts were checked against primary GitHub repositories, exact commits, repository licenses, project documentation, and the existing pinned V3 dependency manifests.

## Decision vocabulary

`DIRECT_DEPENDENCY`, `THIN_ADAPTER`, `ISOLATED_WORKER_API_CLI`, `SELECTIVE_MODULE_REUSE`, `DESIGN_REFERENCE`, `REJECT`, and `V3_NATIVE_REQUIRED` have their literal meanings. A decision never transfers canonical identity, PIT, Truth, Admission, publication, or execution authority to the external project.

## Current V3 owners

| Capability | Current owner | Decision | Boundary |
|---|---|---|---|
| Canonical Factor IR, operator registry, `FactorDefinitionVersion`, reference evaluator | `domain/factors` at baseline | `DIRECT_REUSE` plus the separately authorized bounded Signal-Compatible extension | Remains the sole factor-math authority. |
| `FactorEvaluation` / `FeatureMaterialization` | `domain/factors/evaluation.py` | `DIRECT_REUSE` | Evaluation context is not definition identity. Boolean definitions are callable, but numeric IC evaluation is not silently generalized. |
| Dataset / Experiment / Run / Attempt | existing canonical owners | `DIRECT_REUSE` | W0 only stores exact refs. No duplicate lifecycle or receipt owner. |
| Reviewer / RewardVector | `domain/reviewer_integration` and `domain/experiments` | `DIRECT_REUSE` | Loop records reference exact outputs; they do not recompute or promote them. |
| Agent permissions and trusted tools | `agents/permissions.py`, `agents/tools.py` | `DIRECT_REUSE` | L0/L1 remain allowed; L2/L3 remain denied. |
| Resource admission | `control_plane/resource_governor.py` | `DIRECT_REUSE` | W0 budget references a resource profile and does not duplicate CPU/RAM policy. |
| PydanticAI Slim | V3 pin `2.27.0`; upstream `pydantic/pydantic-ai@0a42080ddb72d7e1610b7ba4ec449a9707c0734d` (MIT) | `DIRECT_DEPENDENCY` already present | Typed proposal worker only; never the control plane or truth owner. |
| RD-Agent | `microsoft/RD-Agent@6762f84f9bc0f5c6486c50a00e128a57ac6c3683` (MIT) | `DESIGN_REFERENCE` | Proposal → experiment → feedback vocabulary only. No second agent framework. |

## Formula / TDX parity scan

| Candidate | Exact revision | License / maintenance | Observed semantics | Decision |
|---|---|---|---|---|
| formula-ts | `DTrader-store/formula-ts@c149cb603ad0df7ea1acb259e6be6af06263bc6f` | MIT; active, pushed 2026-05-05 | Script parser, Unicode identifiers, output styles, drawing events, `MA`, comparison, logic, `CROSS`; runtime represents comparisons as 1/0. | `DESIGN_REFERENCE`; do not use its interpreter and do not copy numeric-boolean coercion. |
| formula-go | `DTrader-store/formula-go@511fd6e0d1265616db117c082c2b3166a622c383` | README states ISC; GitHub license detector returned NOASSERTION; active, pushed 2026-05-05 | `CROSS`: previous `a <= b` and current `a > b`; first item forced to 0. `MA` is simple moving average. | `DESIGN_REFERENCE`; crossing parity only. V3 first item is `None`, not false/0. |
| Funcat | `cedricporter/funcat@076478dcd70d32c3304cd018c8b3b50716e8b17b` | Apache-2.0; last commit 2019-07-12 | Python operator DSL with `MA`, `CROSS`, `COUNT`, `EVERY`, etc.; not a TDX script parser and owns its own execution/data abstractions. | `DESIGN_REFERENCE`. |
| MyTT | `mpquant/MyTT@7cd36ae13cae56657284badc8d5a6b7b8ed62a37` | no detected/source license; active, pushed 2026-06-13 | `CROSS` uses prior not-above and current above, equivalent to `prev <=` + `current >`; first value forced false. `MA` uses rolling mean. | `DESIGN_REFERENCE / PARITY_ONLY`; no source reuse. |

V3 freezes `CROSS@1.0.0` as: at `t`, `left[t] > right[t]` and `left[t-1] <= right[t-1]`; first observation or any required missing current/prior input yields `None`. This intentionally rejects the reference projects' false/0 fallback for unknown history.

TDX `MA(X,N)` maps to the existing TA-Lib-backed canonical `SMA@1.0.0`, whose semantics are a simple moving average with `N-1` warmup. TDX `SMA(X,N,M)` is not the same operation and remains `SEMANTICS_UNRESOLVED` / `UNSUPPORTED_CANONICAL_OPERATOR` in W0.

## Factor packs and compute libraries

| Candidate | Exact revision / version | License | Data/PIT/operator finding | Decision |
|---|---|---|---|---|
| Microsoft Qlib Alpha158/360 | `microsoft/qlib@79633dd9506ea689e5400dea0197717b5b3d74b7`; `pyqlib 0.9.7` | MIT | Rich expressions and packs, but provider/cache/workflow identities and Python runtime are not V3 authorities; PIT depends on caller data preparation. | `ISOLATED_WORKER_API_CLI`; pack formulas require manifests and translation receipts. |
| WorldQuant Alpha101 reference implementation | `yli188/WorldQuant_alpha101_code@3bb9918dd7b62039f41a585a9e37bfd67ce3719f` | no detected license; unmaintained since 2019 | Publication provenance differs from repository code license; data/rank/industry assumptions are not V3 PIT semantics. | `DESIGN_REFERENCE / REFERENCE_ONLY`. |
| Alpha101 + GTJA191 A-share pack | `yupoet/aurumq-rl@5cf7e83637b85e4f855daec16099148b358b89b3` | README claims MIT; GitHub detector NOASSERTION | Broad Polars pack with explicit quality flags, but includes its own factor engine, training stack and data assumptions. | `DESIGN_REFERENCE`; items require per-item license/PIT/operator admission. |
| TA-Lib core / Python | core `c83a2852335ebf21668f94ebe2237cd9a0ad599d`; Python `a9ff1b47b3ddbd57274116645d688c0ed677338b`; V3 pin `0.7.1` | BSD-3-Clause / BSD-2-Clause | Deterministic compute backend; no PIT or publication authority. Initial/missing behavior is adapter-owned. | `DIRECT_DEPENDENCY` through existing V3 adapter. |
| pandas-ta-classic | `33c855e853c5ae235abb2a0b010e62abf4e14cf1` | MIT | Large indicator catalog; missing/warmup and input conventions require translation. | `THIN_ADAPTER` only in future bounded pack import. |
| bukosabino/ta | `a890410710a6e483c9ba08da7f3dd5089e4b9dff` | MIT | Indicator library without V3 PIT/identity semantics. | `THIN_ADAPTER` candidate, not added in W0. |
| KunQuant | `Menooker/KunQuant@d4b9e61f729df347730aa921b539b9df3c3fe36d` | Apache-2.0 | Compiler/runtime can accelerate Alpha101/158 but owns another IR/executor. | `ISOLATED_WORKER_API_CLI`; never canonical IR. |
| QUANTAXIS / QAFactor ideas | `yutiansut/QUANTAXIS@a69e978a2e38d045a64c380cc3b5c9fa08fa4903` | MIT | Catalog/pipeline concepts coexist with its own data/backtest/trading authority. | `DESIGN_REFERENCE`. |

No external pack code or new dependency is copied or installed by W0. Smoke manifests prove the seam only. Publication/formula provenance, repository implementation license, source revision, operator requirements, data requirements, and PIT notes remain separate fields.

## VOL / AMOUNT data-semantics gate

TDX reference semantics used by the acceptance fixture are `VOL = hands (100 shares)` and `AMOUNT/AMO = CNY amount`. The current V3 normalized observation exposes fields named `volume` and `amount`, but its canonical contract does not carry unit evidence. Therefore name-only mapping is rejected.

`TDXDataSemanticProfileVersion` must bind each alias to:

- the exact canonical field semantic version;
- canonical and TDX units;
- an explicit deterministic conversion;
- Dataset/Data Profile evidence refs.

For a profile proving canonical volume is shares, `VOL` translates to `canonical_volume * 0.01` hands. Thus the unchanged source `AMOUNT / VOL / 100` becomes `amount_cny / (volume_shares * 0.01) / 100`, i.e. CNY per share. For a profile proving canonical volume is already hands, the conversion is 1. Any absent/ambiguous evidence is `TDX_DATA_SEMANTIC_UNRESOLVED`; no `FactorDefinitionVersion` or import admission is produced.

## Closed gate

- Agent loop: reuse existing permissions, trusted tools, Control Plane, Experiment/Run/Attempt, Reviewer, RewardVector, and Resource Governor; add only immutable proposal/action/budget/iteration contracts.
- Formula: implement a small V3-native TDX parser and translator only. Execution always uses Canonical Factor IR and `DeterministicReferenceEvaluator` plus registered backends.
- Core: use the explicit same-task authorization for `BOOLEAN_SERIES`, numeric literal, comparison, boolean logic, and `CROSS`. Boolean values remain bool/None and are never coerced to 1/0.
- Packs: manifests/receipts/catalog wrappers only; no bulk import.
- Data semantics: explicit unit evidence and conversion are mandatory; unresolved profiles fail closed.

Gate result: `ADMITTED_FOR_BOUNDED_W0_IMPLEMENTATION`.
