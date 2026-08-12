# Round 5 P/Q/R/S/T Owner Matrix

All tracks below are frozen launch contracts and remain `NOT_RUN` in W0. They must consume W0 contracts and existing V3 authorities; none may fork canonical owners.

| Track | Owns | Does not own / hard boundary | W0 status |
|---|---|---|---|
| P — Factor Agent | Factor proposal/workflow, create/import/evaluate orchestration, catalog business integration, licensed bulk pack execution, user/AI factor research flow | Factor IR core, TDX parser core, desktop shell | `NOT_RUN` |
| Q — Model Agent | Model research proposal/workflow, training/prediction orchestration, model comparison | Factor Catalog core, Portfolio/Risk, desktop shell | `NOT_RUN` |
| R — Portfolio / Risk Agent | Portfolio/Risk proposals, scenario/research orchestration, existing H/I/J runtime consumption | Target/Risk canonical owners, Factor Catalog core, desktop shell | `NOT_RUN` |
| S — Alpha Mining | Bounded candidate generation, search/mutation, reward-driven loop, candidate-evaluation orchestration | Must use `MiningFactorCandidate → Canonical Factor IR → FactorDefinitionVersion → Evaluation → Reviewer → FactorAsset`; no second IR/evaluator | `NOT_RUN` |
| T — Desktop Productization / Apple UX | Custom desktop chrome, legacy menu/title replacement, Chinese-first product copy, Agent-first polish, Research Lab Factor Library, TDX editor, factor detail/version/evaluation/evidence/reviewer/provenance UX, catalog discovery, AI draft mount | Factor math, parser, backend authorities | `NOT_RUN` |

Track T must actually read and use the approved Apple design skill when launched. If unavailable it must report `APPLE_SKILL_NOT_AVAILABLE`; describing a UI as “Apple-like” is not evidence of skill use. W0 performs no UI, Electron chrome, menu, localization, or design-system change.

Bulk Qlib Alpha158/360, licensed Alpha101/191, TA-Lib/pandas-ta-classic, and A-share pack population belongs to P and must use `FactorPackManifestVersion + FactorImportReceipt + FactorDefinitionVersion`. Alpha-mining population belongs to S through the same path.
