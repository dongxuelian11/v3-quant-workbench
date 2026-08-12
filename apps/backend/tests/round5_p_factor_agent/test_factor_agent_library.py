from __future__ import annotations

import ast
from dataclasses import replace
import pathlib
import unittest

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from v3_backend.adapters.factor_packs.manifests import (
    alpha101_reference_manifest,
    alpha158_coverage,
    alpha191_reference_manifest,
    alpha360_manifest,
    a_share_extended_coverage,
    import_supported_alpha360,
    pandas_ta_classic_coverage,
    talib_v3_coverage,
)
from v3_backend.adapters.tdx_formula import (
    TdxDataFieldMapping,
    TdxDataSemanticProfileVersion,
    TdxTranslator,
    registered_tdx_data_semantic_profile,
)
from v3_backend.agents.contracts import PermissionLevel
from v3_backend.agents.factor_agent import (
    FactorAgentService,
    FactorDraftPayload,
    FactorDraftWorker,
    FactorStructuredOutputRejected,
)
from v3_backend.agents.permissions import PermissionDenied
from v3_backend.domain.agent_research_loop import (
    BudgetLimit,
    ResearchActionState,
    ResearchLoopBudgetVersion,
)
from v3_backend.domain.factor_assets import (
    CatalogQuery,
    FactorAssetError,
    FactorAssetLifecycle,
    FactorAssetVersion,
    FactorCatalogSnapshotVersion,
    FactorDraftProposal,
    FactorImportReceipt,
)
from v3_backend.domain.factor_library import (
    EvaluationEvidence,
    FactorApplicationCommand,
    FactorLibraryError,
    FactorLibraryService,
    FactorTranslationPreview,
    PackCoverageService,
)
from v3_backend.domain.factors import signal_compatible_operator_registry


TDX_SOURCE = "GOLDEN:MA(CLOSE,5)>MA(CLOSE,20);"


def _model_response(_messages: list[object], info: AgentInfo) -> ModelResponse:
    payload = {
        "draft_kind": "TDX",
        "draft_payload": TDX_SOURCE,
        "rationale": "A deterministic moving-average crossover draft.",
        "expected_inputs": ["close"],
        "expected_output": "BOOLEAN_SERIES",
        "unsupported_assumptions": [],
        "arbitrary_python": None,
        "execution_requested": False,
        "review_or_promotion_requested": False,
    }
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, payload)])


def _invalid_model_response(_messages: list[object], info: AgentInfo) -> ModelResponse:
    payload = {
        "draft_kind": "TDX",
        "draft_payload": "eval('CLOSE')",
        "rationale": "invalid",
        "expected_inputs": ["close"],
        "expected_output": "FLOAT_SERIES",
        "execution_requested": True,
    }
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, payload)])


class Round5PFactorAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = signal_compatible_operator_registry()
        self.translator = TdxTranslator(self.registry)
        self.profile = registered_tdx_data_semantic_profile(volume_in_hands=False)
        self.worker = FactorDraftWorker(
            model=FunctionModel(_model_response, model_name="round5-p-function-model"),
            permission=PermissionLevel.L1_DRAFT,
            model_name="round5-p-test-model",
            provider_name="deterministic-function-model",
            prompt_version="round5-p-test/1.0.0",
        )
        self.proposal = FactorDraftProposal.create(
            natural_language_intent="Draft a golden cross factor",
            draft_kind="TDX",
            draft_payload=TDX_SOURCE,
            rationale="User requested a deterministic TDX preview",
            expected_inputs=("close",),
            expected_output="BOOLEAN_SERIES",
        )
        self.preview = FactorTranslationPreview.from_proposal(
            self.proposal,
            translator=self.translator,
            data_profile=self.profile,
            provenance_ref="test:round5-p",
        )
        self.applied = FactorApplicationCommand().apply_user_confirmation(
            proposal=self.proposal,
            preview=self.preview,
            confirmed_preview_id=self.preview.preview_id,
            output_name="GOLDEN",
            asset_key="user.golden-cross",
            display_name="Golden Cross",
            data_profile=self.profile,
        )
        snapshot = FactorCatalogSnapshotVersion.create((self.applied.asset,))
        self.library = FactorLibraryService(
            snapshot=snapshot,
            assets=(self.applied.asset,),
            definitions=(self.applied.definition,),
            formula_documents=(self.preview.translation.document,),  # type: ignore[union-attr]
        )
        self.budget = ResearchLoopBudgetVersion.create(
            max_iterations=BudgetLimit.finite(1),
            max_actions=BudgetLimit.finite(2),
            max_candidates=BudgetLimit.finite(1),
            max_experiments=BudgetLimit.finite(1),
            max_model_calls=BudgetLimit.finite(1),
            resource_profile_ref="resource-profile:round5-p-test",
        )

    def _agent(self, permission: object = PermissionLevel.L1_DRAFT) -> FactorAgentService:
        worker = self.worker if permission is PermissionLevel.L1_DRAFT else None
        return FactorAgentService(
            permission=permission,
            library=self.library,
            translator=self.translator,
            data_profile=self.profile,
            worker=worker,
        )

    def test_catalog_exact_factor_definition_binding(self) -> None:
        detail = self.library.read("user.golden-cross")
        self.assertEqual(detail.factor_definition_version_id, self.applied.definition.factor_definition_version_id)
        self.assertEqual(detail.factor_definition_hash, self.applied.definition.factor_definition_version_id)
        with self.assertRaisesRegex(FactorLibraryError, "FACTOR_DEFINITION_BINDING_MISMATCH"):
            FactorLibraryService(
                snapshot=FactorCatalogSnapshotVersion.create((self.applied.asset,)),
                assets=(self.applied.asset,),
                definitions=(),
            )

    def test_agent_l0_catalog_transport_is_exact_and_serializable(self) -> None:
        agent = self._agent()
        detail = agent.read_factor("user.golden-cross")
        results = agent.search_catalog(CatalogQuery(asset_key="user.golden-cross"))
        self.assertEqual(detail["factor_definition_version_id"], self.applied.definition.factor_definition_version_id)
        self.assertEqual(results, (detail,))
        self.assertIsInstance(detail["canonical_ir"], dict)

    def test_unknown_evaluation_definition_fails_closed(self) -> None:
        evidence = EvaluationEvidence(
            "factor-evaluation:unknown",
            "fdv_sha256_unknown",
            "dataset-version:exact",
            "evaluation-context:exact",
            (),
            (),
            (),
        )
        with self.assertRaisesRegex(FactorLibraryError, "EVALUATION_DEFINITION_BINDING_MISMATCH"):
            FactorLibraryService(
                snapshot=FactorCatalogSnapshotVersion.create((self.applied.asset,)),
                assets=(self.applied.asset,),
                definitions=(self.applied.definition,),
                formula_documents=(self.preview.translation.document,),  # type: ignore[union-attr]
                evaluations=(evidence,),
            )

    def test_missing_evaluation_context_is_not_evaluated(self) -> None:
        detail = self.library.read("user.golden-cross")
        explanation = self.library.explain_evidence("user.golden-cross")
        self.assertEqual(detail.evaluation_status, "NOT_EVALUATED")
        self.assertEqual(explanation.evaluation_status, "NOT_EVALUATED")
        self.assertEqual(explanation.exact_evaluation_refs, ())

    def test_agent_factor_draft_is_non_canonical(self) -> None:
        proposal = self._agent().draft_natural_language("Draft a golden cross factor")
        self.assertEqual(proposal.authority_status, "NON_CANONICAL")
        self.assertEqual(proposal.lifecycle_state, "DRAFT")
        self.assertIsNone(getattr(proposal, "canonical_identity", None))

    def test_agent_cannot_review_or_promote(self) -> None:
        agent = self._agent()
        for method in ("review", "promote", "publish", "apply_user_confirmation"):
            self.assertFalse(hasattr(agent, method))
        with self.assertRaisesRegex(FactorAssetError, "LIFECYCLE_TRANSITION_NOT_AUTHORIZED"):
            FactorAssetVersion.create(
                asset_key="blocked.reviewed",
                definition=self.applied.definition,
                source_family="AI_ASSISTED_TDX",
                output_binding=self.preview.translation.output("GOLDEN").binding,  # type: ignore[union-attr]
                display_name="blocked",
                tags=(),
                categories=(),
                frequency="1d",
                lifecycle=FactorAssetLifecycle.REVIEWED,
            )

    def test_natural_language_returns_typed_draft(self) -> None:
        response = self.worker.draft("Draft a golden cross factor")
        self.assertIsInstance(response.payload, FactorDraftPayload)
        self.assertEqual(response.payload.draft_kind, "TDX")
        self.assertFalse(response.payload.execution_requested)

    def test_valid_tdx_has_deterministic_preview(self) -> None:
        self.assertEqual(self.preview.status, "READY_FOR_USER_CONFIRMATION")
        self.assertTrue(self.preview.confirmation_required)
        self.assertEqual(self.preview.diagnostics, ())
        self.assertEqual(
            self.preview.translation.output("GOLDEN").definition.factor_definition_version_id,  # type: ignore[union-attr]
            self.applied.definition.factor_definition_version_id,
        )

    def test_unsupported_operator_fails_closed(self) -> None:
        proposal = FactorDraftProposal.create(
            natural_language_intent="Use EMA",
            draft_kind="TDX",
            draft_payload="BAD:EMA(CLOSE,5);",
            rationale="test unsupported operator",
            expected_inputs=("close",),
            expected_output="FLOAT_SERIES",
        )
        preview = self._agent().preview_tdx(proposal)
        self.assertEqual(preview.status, "NOT_ADMITTED")
        self.assertIn("UNSUPPORTED_TDX_OPERATOR", preview.diagnostics)
        self.assertFalse(preview.confirmation_required)

    def test_unresolved_data_semantics_fail_closed(self) -> None:
        mappings = tuple(
            replace(mapping, field_semantic_version="eod.close/unregistered")
            if "CLOSE" in mapping.aliases
            else mapping
            for mapping in self.profile.mappings
        )
        unregistered = TdxDataSemanticProfileVersion.create(mappings)
        preview = FactorTranslationPreview.from_proposal(
            self.proposal,
            translator=self.translator,
            data_profile=unregistered,
            provenance_ref="test:unregistered-profile",
        )
        self.assertEqual(preview.status, "NOT_ADMITTED")
        self.assertIn("TDX_DATA_SEMANTIC_PROFILE_NOT_REGISTERED", preview.diagnostics)

    def test_explicit_confirmation_creates_exact_definition_and_asset(self) -> None:
        self.assertEqual(self.applied.import_receipt.status.value, "ADMITTED")
        self.assertEqual(
            self.applied.import_receipt.resulting_factor_definition_version_id,
            self.applied.definition.factor_definition_version_id,
        )
        self.assertEqual(self.applied.asset.factor_definition_version_id, self.applied.definition.factor_definition_version_id)
        with self.assertRaisesRegex(FactorLibraryError, "USER_CONFIRMATION_BINDING_MISMATCH"):
            FactorApplicationCommand().apply_user_confirmation(
                proposal=self.proposal,
                preview=self.preview,
                confirmed_preview_id="ftp_sha256_wrong",
                output_name="GOLDEN",
                asset_key="wrong",
                display_name="wrong",
                data_profile=self.profile,
            )

    def test_forged_preview_cannot_cross_confirmation_boundary(self) -> None:
        forged = replace(self.preview, preview_id="ftp_sha256_" + "0" * 64)
        with self.assertRaisesRegex(FactorLibraryError, "INVALID_TRANSLATION_PREVIEW"):
            FactorApplicationCommand().apply_user_confirmation(
                proposal=self.proposal,
                preview=forged,
                confirmed_preview_id=forged.preview_id,
                output_name="GOLDEN",
                asset_key="forged",
                display_name="forged",
                data_profile=self.profile,
            )

    def test_same_input_profile_has_deterministic_identity(self) -> None:
        clone = FactorTranslationPreview.from_proposal(
            self.proposal,
            translator=TdxTranslator(signal_compatible_operator_registry()),
            data_profile=registered_tdx_data_semantic_profile(),
            provenance_ref="test:round5-p",
        )
        second = FactorApplicationCommand().apply_user_confirmation(
            proposal=self.proposal,
            preview=clone,
            confirmed_preview_id=clone.preview_id,
            output_name="GOLDEN",
            asset_key="user.golden-cross",
            display_name="Golden Cross",
            data_profile=self.profile,
        )
        self.assertEqual(clone.preview_id, self.preview.preview_id)
        self.assertEqual(second.confirmation_id, self.applied.confirmation_id)
        self.assertEqual(second.asset.factor_asset_version_id, self.applied.asset.factor_asset_version_id)

    def test_agent_cannot_invoke_confirmation_as_l2(self) -> None:
        with self.assertRaises(PermissionDenied):
            self._agent(PermissionLevel.L2_EXECUTE).preview_tdx(self.proposal)
        inventory = self._agent().tool_inventory
        self.assertNotIn("apply_user_confirmation", inventory)
        self.assertNotIn("execute_task", inventory)

    def test_pack_membership_and_coverage_are_exact(self) -> None:
        alpha360 = alpha360_manifest()
        coverage = PackCoverageService.from_manifest(alpha360)
        self.assertEqual(len(alpha360.items), 360)
        self.assertEqual(len({item.source_item_name for item in alpha360.items}), 360)
        self.assertEqual((coverage.supported, coverage.unsupported_operator, coverage.unsupported_data, coverage.pit_unresolved), (4, 354, 1, 1))
        self.assertEqual(len(alpha101_reference_manifest().items), 101)
        self.assertEqual(len(alpha191_reference_manifest().items), 191)
        self.assertEqual(alpha158_coverage().total_known_items, 158)

    def test_pack_import_count_requires_exact_admitted_receipts(self) -> None:
        manifest = alpha360_manifest()
        imported = import_supported_alpha360(translator=self.translator, data_profile=self.profile)
        coverage = PackCoverageService.from_manifest(
            manifest,
            import_receipts=tuple(value.receipt for value in imported),
        )
        self.assertEqual(coverage.actually_imported_canonical_definitions, 4)
        user_receipt = self.applied.import_receipt
        with self.assertRaisesRegex(FactorLibraryError, "INVALID_PACK_IMPORT_EVIDENCE"):
            PackCoverageService.from_manifest(manifest, import_receipts=(user_receipt,))

    def test_license_blocked_pack_cannot_import(self) -> None:
        manifest = alpha101_reference_manifest()
        item = manifest.items[0]
        with self.assertRaisesRegex(FactorAssetError, "LICENSE_BLOCKED"):
            FactorImportReceipt.create_from_pack_item(
                manifest=manifest,
                item=item,
                translation=self.preview.translation,
                compatibility_profile=self.translator.compatibility,
                data_profile=self.profile,
                definition=self.applied.definition,
            )

    def test_pit_unresolved_pack_cannot_import(self) -> None:
        manifest = alpha360_manifest()
        item = next(value for value in manifest.items if value.source_item_name == "VOLUME0")
        volume_translation = self.translator.translate(
            "VOLUME0:VOL;", data_profile=self.profile, provenance_ref="test:volume"
        )
        with self.assertRaisesRegex(FactorAssetError, "PIT_UNRESOLVED"):
            FactorImportReceipt.create_from_pack_item(
                manifest=manifest,
                item=item,
                translation=volume_translation,
                compatibility_profile=self.translator.compatibility,
                data_profile=self.profile,
                definition=volume_translation.output("VOLUME0").definition,
            )

    def test_imported_pack_item_reaches_existing_definition(self) -> None:
        imported = import_supported_alpha360(translator=self.translator, data_profile=self.profile)
        self.assertEqual(tuple(value.source_item_name for value in imported), ("CLOSE0", "OPEN0", "HIGH0", "LOW0"))
        for value in imported:
            self.assertEqual(
                value.receipt.resulting_factor_definition_version_id,
                value.asset.factor_definition_version_id,
            )
            self.assertTrue(value.asset.factor_definition_version_id.startswith("fdv_sha256_"))
        close = next(value for value in imported if value.source_item_name == "CLOSE0")
        self.assertEqual(close.asset.operator_dependencies, ("DIVIDE@1.0.0",))
        self.assertEqual(close.asset.required_data_fields, ("close",))

    def test_factor_import_action_is_a_not_run_user_confirmation_draft(self) -> None:
        action = self._agent().draft_import_action(
            self.preview,
            resource_profile_ref="resource-profile:round5-p-test",
            budget=self.budget,
        )
        self.assertEqual(action.action_type.value, "FACTOR_IMPORT")
        self.assertIs(action.state, ResearchActionState.NOT_RUN)
        self.assertIn(self.preview.preview_id, action.exact_input_refs)
        self.assertEqual(action.requested_capability, "factor.import.user-confirmation-required")

    def test_factor_asset_cannot_execute_math(self) -> None:
        for method in ("evaluate", "execute", "compute", "run"):
            self.assertFalse(hasattr(self.applied.asset, method))

    def test_evidence_explanation_uses_exact_refs_only(self) -> None:
        evidence = EvaluationEvidence(
            "factor-evaluation:exact-1",
            self.applied.definition.factor_definition_version_id,
            "dataset-version:exact-1",
            "evaluation-context:exact-1",
            ("result:exact-1",),
            ("reviewer:exact-1",),
            ("provenance:exact-1",),
        )
        library = FactorLibraryService(
            snapshot=FactorCatalogSnapshotVersion.create((self.applied.asset,)),
            assets=(self.applied.asset,),
            definitions=(self.applied.definition,),
            formula_documents=(self.preview.translation.document,),  # type: ignore[union-attr]
            evaluations=(evidence,),
        )
        explanation = library.explain_evidence("user.golden-cross")
        self.assertEqual(explanation.exact_evaluation_refs, ("factor-evaluation:exact-1",))
        self.assertEqual(explanation.exact_result_refs, ("result:exact-1",))
        self.assertNotIn("IC", explanation.statement)

    def test_no_arbitrary_python_or_eval_path(self) -> None:
        root = pathlib.Path(__file__).parents[2] / "src" / "v3_backend"
        paths = (
            root / "agents" / "factor_agent",
            root / "domain" / "factor_library",
            root / "adapters" / "factor_packs",
        )
        for directory in paths:
            for path in directory.rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                forbidden_calls = [
                    node.func.id
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in {"eval", "exec"}
                ]
                self.assertEqual(forbidden_calls, [], str(path))

    def test_structured_output_failure_is_typed(self) -> None:
        with self.assertRaises(FactorStructuredOutputRejected):
            FactorDraftWorker.validate_payload(
                {
                    "draft_kind": "TDX",
                    "draft_payload": "eval('CLOSE')",
                    "rationale": "invalid",
                    "expected_inputs": ["close"],
                    "expected_output": "FLOAT_SERIES",
                    "execution_requested": True,
                }
            )
        worker = FactorDraftWorker(
            model=FunctionModel(_invalid_model_response, model_name="invalid-round5-p-model"),
            permission=PermissionLevel.L1_DRAFT,
            model_name="invalid",
            provider_name="deterministic-function-model",
            prompt_version="invalid/1",
        )
        with self.assertRaises(FactorStructuredOutputRejected):
            worker.draft("invalid output test")

    def test_research_loop_complete_remains_not_available_not_run(self) -> None:
        action = self._agent().draft_evaluate_action(
            self.applied.definition.factor_definition_version_id,
            evaluation_context_ref="evaluation-context:explicit",
            resource_profile_ref="resource-profile:round5-p-test",
            budget=self.budget,
        )
        self.assertIs(action.state, ResearchActionState.NOT_RUN)
        self.assertEqual(action.authority_status, "NON_CANONICAL")
        self.assertFalse(hasattr(self._agent(), "complete_research_loop"))

    def test_coverage_reports_noninflated_external_and_a_share_boundaries(self) -> None:
        talib = talib_v3_coverage()
        pandas_ta = pandas_ta_classic_coverage()
        a_share = a_share_extended_coverage()
        self.assertEqual(talib.total_known_items, 1)
        self.assertEqual(talib.actually_imported_canonical_definitions, 0)
        self.assertEqual(pandas_ta.reference_only, 1)
        self.assertEqual((a_share.unsupported_data, a_share.pit_unresolved), (3, 4))


if __name__ == "__main__":
    unittest.main()
