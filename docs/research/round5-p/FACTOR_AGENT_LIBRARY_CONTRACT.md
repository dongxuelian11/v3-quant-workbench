# Round 5 P Factor Agent and Factor Library Contract

Task: `V3-ROUND5-P-FACTOR-AGENT-01`

## Authority boundary

The Factor Agent is L0/L1 only. Its callable inventory is:

- L0: `factor_catalog_search`, `factor_catalog_read`, `factor_evidence_explain`;
- L1: `factor_draft_natural_language`, `factor_tdx_preview`, `factor_import_action_draft`, `factor_evaluate_action_draft`.

There is no Agent-callable confirmation, execute, review, promote, canonical-ID, Truth, Admission, or publication tool. `FactorApplicationCommand.apply_user_confirmation(...)` is retained only as a fail-closed compatibility seam: every call ends with `USER_EXECUTION_AUTHORITY_NOT_AVAILABLE` and creates neither `FactorImportReceipt` nor `FactorAssetVersion`. A preview ID, actor, timestamp, boolean, token, local receipt, or P-only object is not application authority. Production application remains `NOT_AVAILABLE / NOT_RUN` until a shared canonical user-action authority exists.

## AI / TDX creation flow

`natural-language intent`

`→ strict PydanticAI FactorDraftPayload`

`→ W0 FactorDraftProposal NON_CANONICAL / DRAFT`

`→ existing deterministic TDX parser, static analysis, data-profile and translator`

`→ FactorTranslationPreview READY_FOR_USER_CONFIRMATION or typed NOT_ADMITTED diagnostic`

`→ immutable FactorApplicationSpec draft outside the Agent`

`→ USER_EXECUTION_AUTHORITY_NOT_AVAILABLE`

`→ no receipt / no asset / NOT_RUN`

`FactorApplicationSpec` is immutable and content-addressed. It binds the proposal and preview, exact source formula hash/language/document/provenance, selected named output, translated `FactorDefinitionVersion` identity plus canonical wire hash, output binding, asset key/display name, data semantic profile, DRAFT lifecycle, source family, tags/categories/frequency, compatibility and import/admission/external-source options. The L1 import action draft references the exact spec ID and content hash. Any post-draft mutation produces `APPLICATION_SPEC_BINDING_MISMATCH`.

The P layer never parses arbitrary Python, calls `eval`/`exec`, repairs unsupported TDX, or constructs canonical IDs from model text. `V3_FACTOR_IR` can be returned only as a non-canonical typed draft; because P does not own an IR text parser, its current deterministic preview is `UNSUPPORTED_DRAFT_KIND` rather than an inferred canonical definition.

## Catalog and evidence

Catalog detail projects the exact asset version/key, definition ID/hash, source family/pack, available formula/language, full Canonical IR wire form, operators, data fields, lookback, output type, frequency, lifecycle, compatibility, and exact evidence/reviewer/provenance refs.

No canonically resolved evidence means `NOT_EVALUATED`. Public `EvaluationEvidence` is an untrusted request/projection DTO and cannot make a factor evaluated by itself. `CanonicalEvaluationEvidenceResolver` must resolve every object from its injected canonical owner and exact-bind `FactorDefinitionVersion`, materialization, `FactorEvaluation`, Dataset/Universe/Snapshot/PIT context, label/horizon/split period, evaluation policy, Experiment Run/Attempt/Result, RewardVector metrics, experiment `ReviewerEvidence`, canonical `ResearchReviewReport`, and every provenance/result Artifact. The review report must target the exact FactorEvaluation, DatasetVersion, ExperimentResult, and RewardVector chain. Missing owner, wrong relation, fabricated ref, or missing artifact fails with `EVIDENCE_BINDING_UNAVAILABLE`; it never degrades to an evaluated state.

IC, Rank IC, turnover, coverage, and other metrics remain properties of the exact resolved evaluation context. Missing metrics are unavailable and are never rendered as zero.

## Pack boundary

Only `FactorPackItemStatus.SUPPORTED` items can pass the frozen W0 `FactorImportReceipt.create_from_pack_item(...)` gate. Every admitted item reaches the exact existing translator-produced `FactorDefinitionVersion`; a `FactorAssetVersion` has no evaluate/execute method.

Pack listing, documented total, exact membership, supported translation, and actual canonical import count are separate facts. See `PACK_COVERAGE.md`.

## Production state

Production ResearchLoop `COMPLETE`: `NOT_AVAILABLE / NOT_RUN`.

No Track T UI, desktop shell, shared route, Factor IR, evaluator, OperatorRegistry, or TDX parser/translator core file is changed by P.
