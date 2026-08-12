# Round 5 W0 Factor Asset and Catalog Contract

## Sole factor authority

`FactorDefinitionVersion` in the existing Canonical Factor IR remains the only factor-math authority. Formula documents, external pack items, AI drafts, mining candidates, assets, and catalog entries cannot be evaluated directly and cannot enter Dataset, Experiment, Strategy, or publication flows in their own form.

Every accepted output follows:

`source → deterministic translator → FactorDefinitionVersion → existing evaluator / evaluation owner`

## Asset and provenance contracts

- `FormulaDocumentVersion` preserves exact source text/hash, language, parser compatibility profile, AST digest, outputs, and provenance.
- `FormulaOutputBinding` binds one exact document output to one exact `FactorDefinitionVersion` and typed output.
- `FactorImportReceipt` records source digest/revision, license provenance, translator, exact compatibility profile, OperatorRegistry, data-semantic profile, and resulting definition. Raw `create(..., ADMITTED)` is closed. User-authored formulas use `create_from_user_formula(...)` and bind the source SHA, registered profiles, translator result, and exact definition without inventing a third-party license. External packs use `create_from_pack_item(...)` and additionally bind the actual canonical manifest, exact member item/digest/revision/license/status; non-`SUPPORTED` items cannot admit.
- `FactorAssetVersion` is display/discovery metadata around an exact definition and binding. Generic create only permits `DRAFT` or `CANDIDATE`; `REVIEWED`, `PROMOTED`, and `DEPRECATED` fail with `LIFECYCLE_TRANSITION_NOT_AUTHORIZED` until a separate owner transition is formally implemented. Lifecycle remains independent of Truth and Admission.
- `FactorCatalogSnapshotVersion` contains only exact asset key/version refs. It does not copy formulas or execute factors.

Catalog discovery supports asset key, source family, pack manifest, tag/category, output type, maximum lookback, frequency, lifecycle, operator dependency, and compatibility status. Performance remains `NOT_EVALUATED` unless an explicit existing Evaluation context is provided; otherwise `EVALUATION_CONTEXT_REQUIRED` is raised.

## Packs, AI drafts, and mining

Pack manifests preserve project/publication, exact revision, license evidence, import mode, per-item operators/data/PIT notes, and explicit compatibility status. Missing revision and license evidence fail with typed errors. W0 contains only smoke contracts; bulk import is `NOT_RUN`.

`FactorDraftProposal` and `MiningFactorCandidate` are always `NON_CANONICAL / DRAFT`. Successful deterministic translation can produce a canonical definition, but neither object can claim effectiveness, review, promotion, or publication.
