# Round 5 P Reuse / Adoption Matrix

Task: `V3-ROUND5-P-FACTOR-AGENT-01`

Frozen base: `dongxuelian11/v3-quant-workbench@f2cd80ee377d213a1bc1e78fb9812d2192b10cf9`

Observed: 2026-08-12 (Asia/Shanghai). A mandatory fresh `git fetch` was attempted twice and failed only at GitHub port 443. Context7 is not configured in this execution environment, and the external documentation search endpoint also failed. Exact upstream revisions below therefore come from the accepted same-day W0 research frozen into this base and current repository dependency manifests. Every upstream-current claim remains `PENDING_NETWORK_RECHECK` before delivery; the matrix does not silently promote cached facts to GitHub CURRENT.

## Authority and decision vocabulary

`FactorDefinitionVersion` remains the sole factor-math authority. External libraries, formula publications, manifests, assets, catalog records, AI drafts, and pack implementations never own V3 identity, PIT, Truth, Admission, execution, review, or publication.

Decisions use only:

`DIRECT_DEPENDENCY / THIN_ADAPTER / ISOLATED_WORKER_API_CLI / SELECTIVE_MODULE_REUSE / DESIGN_REFERENCE / REJECT / V3_NATIVE_REQUIRED`

## Current V3 components

| Candidate | Exact local/frozen evidence | License / maintenance / compatibility | Semantic finding | Decision |
|---|---|---|---|---|
| Canonical Factor IR and `FactorDefinitionVersion` | `domain/factors` at frozen base; W0 contract and tests | V3-owned; Windows/Python native | Sole math, operator-registry, deterministic identity and evaluator authority | `DIRECT_DEPENDENCY`; consume public contracts only; P must not edit core |
| FactorAsset / Catalog / pack admission | `domain/factor_assets` at frozen base | V3-owned | Exact definition/output/import binding, contextual evaluation gate, typed per-item compatibility | `DIRECT_DEPENDENCY`; build P business services around it |
| V3 TDX parser/translator | `adapters/tdx_formula` at frozen base | V3-owned | Deterministic parse/static analysis/translation; unresolved data semantics and unsupported operators fail closed | `DIRECT_DEPENDENCY`; orchestration only; P must not edit parser/translator core |
| PydanticAI Slim | repository pin `2.27.0`; frozen W0 upstream `pydantic/pydantic-ai@0a42080ddb72d7e1610b7ba4ec449a9707c0734d`; MIT | Python `>=3.10`, pure Python wheel; installed-version guard already exists; fresh upstream state `PENDING_NETWORK_RECHECK` | Typed structured proposal output is useful; its tools, approvals or durable runtime are not V3 control-plane authority | `DIRECT_DEPENDENCY` for a bounded typed L1 worker only |
| TA-Lib V3 adapter | Python pin/evidence `0.7.1`; frozen core `c83a2852335ebf21668f94ebe2237cd9a0ad599d`, Python `a9ff1b47b3ddbd57274116645d688c0ed677338b`; BSD-3-Clause/BSD-2-Clause | Existing Windows adapter; real availability remains environment-dependent and may honestly SKIP | Deterministic compute only; warmup/missing behavior is V3 adapter-owned; no PIT or catalog authority | `DIRECT_DEPENDENCY` through the existing adapter; add no new dependency |

## Pack and reference candidates

| Candidate | Exact frozen evidence | License / maintenance / Windows-Python finding | Semantics and coverage consequence | Decision |
|---|---|---|---|---|
| Qlib Alpha158 / Alpha360 | `microsoft/qlib@79633dd9506ea689e5400dea0197717b5b3d74b7`, `pyqlib 0.9.7`; MIT | Frozen research: supports Python 3.8-3.12; no supported CPython 3.14 Windows path established; current status `PENDING_NETWORK_RECHECK` | Rich expression language, rolling/rank/correlation operators and caller-owned data/PIT assumptions exceed current V3 TDX subset. Listing a pack cannot imply runnable items | `ISOLATED_WORKER_API_CLI` for future compute; this P slice uses a deterministic coverage manifest and imports only exact representable formulas |
| pandas-ta-classic | `xgboosted/pandas-ta-classic@33c855e853c5ae235abb2a0b010e62abf4e14cf1`; MIT | Frozen W0 observed active project; Python/Windows compatibility must be refreshed before adding dependency | Broad indicator catalog, but input names, warmup, fill and output conventions need per-indicator parity; no PIT authority | `THIN_ADAPTER`; no dependency added merely to inflate counts |
| WorldQuant Alpha101 publication | Kakushadze, *101 Formulaic Alphas* publication | Publication provenance is not a reusable-code license | Formula assumptions include cross-sectional rank, correlation, volume and industry inputs; publication alone does not license random implementation copying | `DESIGN_REFERENCE` |
| WorldQuant Alpha101 reusable implementation | `yli188/WorldQuant_alpha101_code@3bb9918dd7b62039f41a585a9e37bfd67ce3719f`; no detected license, unmaintained since 2019 | License blocks source reuse; Windows/Python freshness not relied upon | Reference formulas/data assumptions only; no canonical import from repository code | `REJECT` for code reuse; manifest items are `LICENSE_BLOCKED` or `REFERENCE_ONLY` |
| GTJA / Alpha191 publication family | Publication/formula family; no single implementation license grants the publication corpus | Publication provenance and implementation license must remain separate | Many formulas require rolling statistics, ranks and A-share semantics not available in current operator/data profiles | `DESIGN_REFERENCE`; no bulk canonical import without per-item licensed source and exact semantics |
| AurumQ-RL | `yupoet/aurumq-rl@5cf7e83637b85e4f855daec16099148b358b89b3`; README claims MIT while frozen GitHub detector reported NOASSERTION | License evidence is insufficient for copying; broad Polars/training stack and current compatibility `PENDING_NETWORK_RECHECK` | Useful quality-flag and pack-organization reference, but owns a separate engine and data assumptions | `DESIGN_REFERENCE`; no source reuse or dependency |
| `bukosabino/ta` | `bukosabino/ta@a890410710a6e483c9ba08da7f3dd5089e4b9dff`; MIT | Frozen W0 candidate; current maintenance/Windows/Python compatibility `PENDING_NETWORK_RECHECK` | Indicator implementations need per-output parameter, warmup and missing-value parity; no identity/PIT authority | `THIN_ADAPTER` candidate; not added in this slice |
| Funcat | `cedricporter/funcat@076478dcd70d32c3304cd018c8b3b50716e8b17b`; Apache-2.0; last frozen commit 2019-07-12 | Old Python DSL; no current Windows support claim | `MA`, `CROSS`, `COUNT`, `EVERY` parity reference but owns execution/data abstractions and is not a TDX parser | `DESIGN_REFERENCE` |
| MyTT | `mpquant/MyTT@7cd36ae13cae56657284badc8d5a6b7b8ed62a37`; no detected/source license | Frozen W0 saw activity through 2026-06-13, but no license permits copying | Parity-only reference: its `CROSS` first value is false, whereas V3 preserves unknown as `None` | `DESIGN_REFERENCE`; source reuse `REJECT` |

## Closed adoption gate

- No dependency is added for factor-count optics.
- P reuses W0 FactorAsset/Catalog/TDX and the existing permissions/action contracts, and creates only P-owned orchestration, typed agent output, application command, exact-evidence projections, and bounded pack manifests.
- Natural-language output remains `FactorDraftProposal NON_CANONICAL`. Deterministic translation is mandatory before any user-confirmable plan exists.
- The application command is not registered as an Agent tool. It alone may apply an already previewed, exact user confirmation to W0 `FactorImportReceipt + FactorDefinitionVersion + FactorAssetVersion`.
- Alpha101/191 code without adequate license evidence is never copied or admitted. Qlib and third-party engines never become Canonical Factor IR.
- A-share data lacking exact fields and available-time/PIT evidence is classified `UNSUPPORTED_DATA` or `PIT_UNRESOLVED`, never synthesized.
- Bulk coverage is deterministic and reports every W0 status plus actual admitted canonical definition count. Pack listed does not mean pack supported.

Gate result: `ADMITTED_FOR_BOUNDED_ROUND5_P_IMPLEMENTATION_WITH_NETWORK_RECHECK_PENDING`.
