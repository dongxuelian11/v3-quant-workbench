# Round 5 P Factor Agent and Factor Library Contract

Task: `V3-ROUND5-P-FACTOR-AGENT-01`

## Authority boundary

The Factor Agent is L0/L1 only. Its callable inventory is:

- L0: `factor_catalog_search`, `factor_catalog_read`, `factor_evidence_explain`;
- L1: `factor_draft_natural_language`, `factor_tdx_preview`, `factor_import_action_draft`, `factor_evaluate_action_draft`.

There is no Agent-callable confirmation, execute, review, promote, canonical-ID, Truth, Admission, or publication tool. `FactorApplicationCommand.apply_user_confirmation(...)` is a separate application boundary and requires an exact `preview_id` supplied back by the user/application. The action drafts remain `NON_CANONICAL / NOT_RUN`.

## AI / TDX creation flow

`natural-language intent`

`→ strict PydanticAI FactorDraftPayload`

`→ W0 FactorDraftProposal NON_CANONICAL / DRAFT`

`→ existing deterministic TDX parser, static analysis, data-profile and translator`

`→ FactorTranslationPreview READY_FOR_USER_CONFIRMATION or typed NOT_ADMITTED diagnostic`

`→ exact explicit preview confirmation outside the Agent`

`→ existing FactorImportReceipt factory + exact translator-produced FactorDefinitionVersion`

`→ FactorAssetVersion DRAFT/CANDIDATE`

The P layer never parses arbitrary Python, calls `eval`/`exec`, repairs unsupported TDX, or constructs canonical IDs from model text. `V3_FACTOR_IR` can be returned only as a non-canonical typed draft; because P does not own an IR text parser, its current deterministic preview is `UNSUPPORTED_DRAFT_KIND` rather than an inferred canonical definition.

## Catalog and evidence

Catalog detail projects the exact asset version/key, definition ID/hash, source family/pack, available formula/language, full Canonical IR wire form, operators, data fields, lookback, output type, frequency, lifecycle, compatibility, and exact evidence/reviewer/provenance refs.

No bound `EvaluationEvidence` means `NOT_EVALUATED`. IC, ICIR, turnover, and performance are never projected as timeless asset properties. Evidence referring to an unknown definition fails with `EVALUATION_DEFINITION_BINDING_MISMATCH`.

## Pack boundary

Only `FactorPackItemStatus.SUPPORTED` items can pass the frozen W0 `FactorImportReceipt.create_from_pack_item(...)` gate. Every admitted item reaches the exact existing translator-produced `FactorDefinitionVersion`; a `FactorAssetVersion` has no evaluate/execute method.

Pack listing, documented total, exact membership, supported translation, and actual canonical import count are separate facts. See `PACK_COVERAGE.md`.

## Production state

Production ResearchLoop `COMPLETE`: `NOT_AVAILABLE / NOT_RUN`.

No Track T UI, desktop shell, shared route, Factor IR, evaluator, OperatorRegistry, or TDX parser/translator core file is changed by P.
