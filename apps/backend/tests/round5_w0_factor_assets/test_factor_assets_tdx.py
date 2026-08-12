from __future__ import annotations

import math
import unittest

from v3_backend.adapters.talib import TalibOperatorAdapter
from v3_backend.adapters.tdx_formula import (
    TdxCompatibilityProfileVersion,
    TdxDataFieldMapping,
    TdxDataSemanticProfileVersion,
    TdxFormulaError,
    TdxFunctionStatus,
    TdxParser,
    TdxTranslator,
)
from v3_backend.domain.agent_research_loop import (
    BudgetLimit,
    ResearchActionDraft,
    ResearchActionType,
    ResearchLoopBudgetVersion,
)
from v3_backend.domain.factor_assets import (
    CatalogQuery,
    FactorAssetCatalogService,
    FactorAssetError,
    FactorAssetLifecycle,
    FactorAssetVersion,
    FactorCatalogSnapshotVersion,
    FactorDraftProposal,
    FactorImportReceipt,
    FactorImportStatus,
    FactorPackItem,
    FactorPackItemStatus,
    FactorPackManifestVersion,
    FormulaDocumentVersion,
    FormulaOutputBinding,
    FormulaParseStatus,
    MiningFactorCandidate,
)
from v3_backend.domain.factors import (
    BackendBinding,
    DeterministicReferenceEvaluator,
    FeatureNode,
    MissingSemantics,
    OperatorRegistry,
    OperatorSpec,
    ValueType,
    default_operator_registry,
    signal_compatible_operator_registry,
)


USER_FORMULA = """MJ:=AMOUNT/VOL/100;
MA5:=MA(MJ,5);
MA20:=MA(MJ,20);
MA60:=MA(MJ,60);
GOLDEN:CROSS(MA20,MA60) AND MA5>MA20;
"""


class FakeTalibProvider:
    wrapper_version = "0.7.1"
    core_version = "0.7.1-test-double"

    def sma(self, values, timeperiod: int):
        source = tuple(float(value) for value in values)
        output: list[float] = []
        for index in range(len(source)):
            window = source[max(0, index - timeperiod + 1) : index + 1]
            if index < timeperiod - 1 or any(math.isnan(value) for value in window):
                output.append(math.nan)
            else:
                output.append(sum(window) / timeperiod)
        return output


def data_profile(*, volume_in_hands: bool = False) -> TdxDataSemanticProfileVersion:
    mappings = tuple(
        TdxDataFieldMapping(
            (name.upper(),),
            name,
            f"eod.{name}/1.0.0",
            "CNY_PER_SHARE",
            "CNY_PER_SHARE",
            "1",
            (f"dataset-profile:{name}:cny-per-share",),
        )
        for name in ("open", "high", "low", "close")
    )
    volume = TdxDataFieldMapping(
        ("VOL",),
        "volume_hands" if volume_in_hands else "volume",
        "eod.volume-hands/1.0.0" if volume_in_hands else "eod.volume-shares/1.0.0",
        "HAND" if volume_in_hands else "SHARES",
        "HAND",
        "1" if volume_in_hands else "0.01",
        ("dataset-profile:volume-unit-observed",),
    )
    amount = TdxDataFieldMapping(
        ("AMOUNT", "AMO"),
        "amount",
        "eod.amount-cny/1.0.0",
        "CNY",
        "CNY",
        "1",
        ("dataset-profile:amount-currency-cny",),
    )
    return TdxDataSemanticProfileVersion.create((*mappings, volume, amount))


class TdxCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = signal_compatible_operator_registry()
        self.translator = TdxTranslator(self.registry)
        self.profile = data_profile()

    def test_parser_supports_script_grammar_chinese_identifiers_and_is_deterministic(self) -> None:
        source = "价格:=(-收盘+OPEN*2)/3; 信号:NOT 价格<=10 OR CLOSE!=OPEN;"
        first = TdxParser().parse(source)
        second = TdxParser().parse(source)
        self.assertEqual(first, second)
        self.assertEqual(first.declared_names, ("价格", "信号"))
        with self.assertRaisesRegex(TdxFormulaError, "TDX_PARSE_ERROR"):
            TdxParser().parse("A:=MA(CLOSE,5)")

    def test_compatibility_profile_closes_supported_and_unsupported_functions(self) -> None:
        profile = self.translator.compatibility
        self.assertEqual(profile.operator_registry_version, self.registry.registry_version)
        self.assertIs(profile.resolve("MA").status, TdxFunctionStatus.SUPPORTED)
        self.assertIs(profile.resolve("CROSS").status, TdxFunctionStatus.SUPPORTED)
        for name in ("EMA", "REF", "HHV", "LLV", "SUM", "STD", "COUNT", "EVERY", "EXIST", "IF", "MAX", "MIN", "ABS"):
            self.assertIs(profile.resolve(name).status, TdxFunctionStatus.UNSUPPORTED_CANONICAL_OPERATOR)
        self.assertIs(profile.resolve("SMA").status, TdxFunctionStatus.SEMANTICS_UNRESOLVED)
        with self.assertRaisesRegex(TdxFormulaError, "UNSUPPORTED_TDX_OPERATOR"):
            self.translator.translate("X:EMA(CLOSE,5);", data_profile=self.profile, provenance_ref="user:test")
        with self.assertRaisesRegex(TdxFormulaError, "UNSUPPORTED_TDX_OPERATOR"):
            self.translator.translate("X:SMA(CLOSE,5,2);", data_profile=self.profile, provenance_ref="user:test")

    def test_data_profile_requires_complete_evidence_and_exact_tdx_units(self) -> None:
        self.assertEqual(self.profile.resolve("VOL").canonical_unit, "SHARES")
        self.assertEqual(self.profile.resolve("VOL").tdx_unit, "HAND")
        self.assertEqual(self.profile.resolve("VOL").canonical_to_tdx_multiplier, "0.01")
        self.assertEqual(self.profile.resolve("AMOUNT"), self.profile.resolve("AMO"))
        with self.assertRaisesRegex(TdxFormulaError, "TDX_DATA_SEMANTIC_UNRESOLVED"):
            TdxDataFieldMapping(
                ("VOL",), "volume", "eod.volume/1", "SHARES", "HAND", "1", ("evidence",)
            )
        with self.assertRaisesRegex(TdxFormulaError, "TDX_DATA_SEMANTIC_UNRESOLVED"):
            TdxDataSemanticProfileVersion.create((self.profile.resolve("VOL"), self.profile.resolve("AMOUNT")))

    def test_user_formula_reaches_canonical_factor_definitions_and_existing_evaluator(self) -> None:
        result = self.translator.translate(
            USER_FORMULA,
            data_profile=self.profile,
            provenance_ref="user-supplied:round5-w0-fixture",
        )
        self.assertEqual(result.document.named_outputs, ("MJ", "MA5", "MA20", "MA60", "GOLDEN"))
        self.assertEqual(result.static_analysis.input_data_dependencies, ("amount", "volume"))
        self.assertEqual(result.static_analysis.max_lookback, 60)
        self.assertEqual(result.output("MA5").definition.metadata.output_type, ValueType.FLOAT_SERIES)
        self.assertEqual(result.output("MA20").definition.metadata.output_type, ValueType.FLOAT_SERIES)
        self.assertEqual(result.output("MA60").definition.metadata.output_type, ValueType.FLOAT_SERIES)
        self.assertEqual(result.output("GOLDEN").definition.metadata.output_type, ValueType.BOOLEAN_SERIES)
        self.assertIn("CROSS@1.0.0", result.output("GOLDEN").definition.metadata.operator_keys)
        evaluator = DeterministicReferenceEvaluator(
            self.registry,
            (TalibOperatorAdapter(FakeTalibProvider()),),
        )
        prices = [100.0] * 60 + [200.0] * 40
        volume = [10_000.0] * len(prices)
        amount = [price * shares for price, shares in zip(prices, volume, strict=True)]
        features = {"amount": amount, "volume": volume}
        for output_name in ("MA5", "MA20", "MA60"):
            evaluated = evaluator.evaluate(result.output(output_name).definition, features)
            self.assertIs(evaluated.output_type, ValueType.FLOAT_SERIES)
        golden = evaluator.evaluate(result.output("GOLDEN").definition, features)
        self.assertIs(golden.output_type, ValueType.BOOLEAN_SERIES)
        self.assertTrue(all(value is None or isinstance(value, bool) for value in golden.values))
        self.assertIs(golden.values[60], True)
        mj = evaluator.evaluate(result.output("MJ").definition, features)
        self.assertEqual(mj.values[0], 100.0)

    def test_same_source_different_valid_unit_profiles_change_translation_identity(self) -> None:
        shares = self.translator.translate(USER_FORMULA, data_profile=self.profile, provenance_ref="user:test")
        hands_profile = data_profile(volume_in_hands=True)
        hands = self.translator.translate(USER_FORMULA, data_profile=hands_profile, provenance_ref="user:test")
        self.assertNotEqual(self.profile.data_semantic_profile_id, hands_profile.data_semantic_profile_id)
        self.assertNotEqual(
            shares.output("MJ").definition.factor_definition_version_id,
            hands.output("MJ").definition.factor_definition_version_id,
        )
        first_receipt = FactorImportReceipt.create(
            source_item_digest=shares.document.source_sha256,
            pack_manifest_version_id=None,
            source_revision="user-source-sha256:" + shares.document.source_sha256,
            license_provenance_ref="user-authored",
            translator_version=self.translator.translator_version,
            operator_registry_version=self.registry.registry_version,
            data_semantic_profile_id=self.profile.data_semantic_profile_id,
            definition=shares.output("MJ").definition,
            status=FactorImportStatus.ADMITTED,
        )
        second_receipt = FactorImportReceipt.create(
            source_item_digest=hands.document.source_sha256,
            pack_manifest_version_id=None,
            source_revision="user-source-sha256:" + hands.document.source_sha256,
            license_provenance_ref="user-authored",
            translator_version=self.translator.translator_version,
            operator_registry_version=self.registry.registry_version,
            data_semantic_profile_id=hands_profile.data_semantic_profile_id,
            definition=hands.output("MJ").definition,
            status=FactorImportStatus.ADMITTED,
        )
        self.assertNotEqual(first_receipt.factor_import_receipt_id, second_receipt.factor_import_receipt_id)

    def test_operator_registry_version_changes_compatibility_profile_identity(self) -> None:
        alternate_registry = OperatorRegistry(
            (
                OperatorSpec(
                    "DUMMY",
                    "1.0.0",
                    1,
                    (ValueType.FLOAT_SERIES,),
                    ValueType.FLOAT_SERIES,
                    0,
                    0,
                    MissingSemantics.PROPAGATE,
                    True,
                    True,
                    BackendBinding.NATIVE_REFERENCE,
                ),
            )
        )
        alternate = TdxCompatibilityProfileVersion.create_default(alternate_registry)
        self.assertNotEqual(alternate.compatibility_profile_id, self.translator.compatibility.compatibility_profile_id)

    def test_drawing_statements_and_style_metadata_are_separate_from_factor_math(self) -> None:
        result = self.translator.translate(
            "LINE:CLOSE,COLORRED,LINETHICK2; DRAWTEXT(CLOSE>OPEN,CLOSE);",
            data_profile=self.profile,
            provenance_ref="user:drawing",
        )
        self.assertEqual(result.output("LINE").definition.metadata.input_features, ("close",))
        self.assertEqual(
            result.drawing_metadata,
            (
                ("LINE", ("COLORRED", "LINETHICK2")),
                ("DRAWTEXT", ("UNSUPPORTED_NON_COMPUTATIONAL_STATEMENT",)),
            ),
        )


class FactorAssetCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = signal_compatible_operator_registry()
        self.profile = data_profile()
        self.translation = TdxTranslator(self.registry).translate(
            USER_FORMULA,
            data_profile=self.profile,
            provenance_ref="user-supplied:round5-w0-fixture",
        )

    def _receipt(self, output_name: str) -> FactorImportReceipt:
        return FactorImportReceipt.create(
            source_item_digest=self.translation.document.source_sha256,
            pack_manifest_version_id=None,
            source_revision="user-source-sha256:" + self.translation.document.source_sha256,
            license_provenance_ref="user-authored",
            translator_version="v3-tdx-to-factor-ir/1.0.0",
            operator_registry_version=self.registry.registry_version,
            data_semantic_profile_id=self.profile.data_semantic_profile_id,
            definition=self.translation.output(output_name).definition,
            status=FactorImportStatus.ADMITTED,
        )

    def _asset(self, output_name: str) -> FactorAssetVersion:
        output = self.translation.output(output_name)
        return FactorAssetVersion.create(
            asset_key=f"user.round5.{output_name.lower()}",
            definition=output.definition,
            source_family="TDX_USER_FORMULA",
            output_binding=output.binding,
            display_name=output_name,
            tags=("round5", "tdx"),
            categories=("signal",) if output_name == "GOLDEN" else ("price",),
            frequency="1d",
            lifecycle=FactorAssetLifecycle.CANDIDATE,
            import_receipt=self._receipt(output_name),
            formula_document=self.translation.document,
        )

    def test_asset_binding_catalog_snapshot_and_queries_are_deterministic(self) -> None:
        assets = (self._asset("MA20"), self._asset("GOLDEN"))
        snapshot = FactorCatalogSnapshotVersion.create(assets)
        clone = FactorCatalogSnapshotVersion.create(tuple(reversed(assets)))
        self.assertEqual(snapshot, clone)
        catalog = FactorAssetCatalogService(snapshot, assets)
        self.assertEqual(len(catalog.query(CatalogQuery(tag="tdx")).assets), 2)
        result = catalog.query(
            CatalogQuery(
                source_family="TDX_USER_FORMULA",
                category="signal",
                output_type=ValueType.BOOLEAN_SERIES,
                max_lookback=60,
                frequency="1d",
                lifecycle=FactorAssetLifecycle.CANDIDATE,
                operator_dependency="CROSS@1.0.0",
                compatibility_status=FactorPackItemStatus.SUPPORTED,
            )
        )
        self.assertEqual(tuple(value.asset_key for value in result.assets), ("user.round5.golden",))
        self.assertEqual(result.performance_status, "NOT_EVALUATED")
        with self.assertRaisesRegex(FactorAssetError, "EVALUATION_CONTEXT_REQUIRED"):
            catalog.require_evaluation_context(None)
        self.assertFalse(hasattr(assets[0], "evaluate"))

    def test_duplicate_asset_key_and_stale_definition_bindings_fail_closed(self) -> None:
        ma20 = self._asset("MA20")
        golden = self._asset("GOLDEN")
        duplicate = FactorAssetVersion.create(
            asset_key=ma20.asset_key,
            definition=golden and self.translation.output("GOLDEN").definition,
            source_family="TDX_USER_FORMULA",
            output_binding=self.translation.output("GOLDEN").binding,
            display_name="duplicate",
            tags=(),
            categories=(),
            frequency="1d",
            lifecycle=FactorAssetLifecycle.DRAFT,
            formula_document=self.translation.document,
        )
        with self.assertRaisesRegex(FactorAssetError, "DUPLICATE_FACTOR_ASSET_KEY"):
            FactorCatalogSnapshotVersion.create((ma20, duplicate))
        with self.assertRaisesRegex(FactorAssetError, "FACTOR_DEFINITION_BINDING_MISMATCH"):
            FactorAssetVersion.create(
                asset_key="wrong",
                definition=self.translation.output("MA20").definition,
                source_family="TDX_USER_FORMULA",
                output_binding=self.translation.output("GOLDEN").binding,
                display_name="wrong",
                tags=(),
                categories=(),
                frequency="1d",
                lifecycle=FactorAssetLifecycle.DRAFT,
            )

    def test_pack_manifest_records_revision_license_and_explicit_item_status(self) -> None:
        item = FactorPackItem(
            "Alpha001",
            "sha256:item",
            ("RANK",),
            ("close",),
            "PIT unresolved for source dataset",
            FactorPackItemStatus.REFERENCE_ONLY,
        )
        manifest = FactorPackManifestVersion.create(
            pack_name="reference-smoke",
            source_project_or_publication="WorldQuant Alpha101 publication",
            exact_source_revision="publication:exact-edition",
            license_identifier="REFERENCE_ONLY",
            license_evidence_ref="docs/research/round5-w0/REUSE_ADOPTION_MATRIX.md",
            import_mode="REFERENCE_ONLY",
            items=(item,),
        )
        clone = FactorPackManifestVersion.create(
            pack_name="reference-smoke",
            source_project_or_publication="WorldQuant Alpha101 publication",
            exact_source_revision="publication:exact-edition",
            license_identifier="REFERENCE_ONLY",
            license_evidence_ref="docs/research/round5-w0/REUSE_ADOPTION_MATRIX.md",
            import_mode="REFERENCE_ONLY",
            items=(item,),
        )
        self.assertEqual(manifest, clone)
        self.assertIs(manifest.items[0].compatibility_status, FactorPackItemStatus.REFERENCE_ONLY)
        with self.assertRaisesRegex(FactorAssetError, "FACTOR_PACK_SOURCE_REVISION_MISSING"):
            FactorPackManifestVersion.create(
                pack_name="bad", source_project_or_publication="bad", exact_source_revision="",
                license_identifier="MIT", license_evidence_ref="evidence", import_mode="ADAPTER", items=(item,)
            )
        with self.assertRaisesRegex(FactorAssetError, "FACTOR_PACK_LICENSE_BLOCKED"):
            FactorPackManifestVersion.create(
                pack_name="bad", source_project_or_publication="bad", exact_source_revision="sha",
                license_identifier="", license_evidence_ref="", import_mode="ADAPTER", items=(item,)
            )

    def test_import_receipt_exactly_binds_result_and_rejects_warnings(self) -> None:
        receipt = self._receipt("GOLDEN")
        self.assertEqual(
            receipt.resulting_factor_definition_version_id,
            self.translation.output("GOLDEN").definition.factor_definition_version_id,
        )
        with self.assertRaisesRegex(FactorAssetError, "FACTOR_IMPORT_NOT_ADMITTED"):
            FactorImportReceipt.create(
                source_item_digest="sha256:item",
                pack_manifest_version_id=None,
                source_revision="revision",
                license_provenance_ref="license",
                translator_version="translator",
                operator_registry_version=self.registry.registry_version,
                data_semantic_profile_id=self.profile.data_semantic_profile_id,
                definition=self.translation.output("GOLDEN").definition,
                warnings=("unsupported",),
                status=FactorImportStatus.ADMITTED,
            )

    def test_ai_and_mining_inputs_remain_drafts_until_canonical_translation(self) -> None:
        ai_tdx = FactorDraftProposal.create(
            natural_language_intent="Create a golden cross signal",
            draft_kind="TDX",
            draft_payload=USER_FORMULA,
            rationale="User requested TDX compatibility",
            expected_inputs=("AMOUNT", "VOL"),
            expected_output="BOOLEAN_SERIES",
        )
        ai_ir = FactorDraftProposal.create(
            natural_language_intent="Create a factor",
            draft_kind="V3_FACTOR_IR",
            draft_payload="draft-only",
            rationale="Requires deterministic validation",
            expected_inputs=("close",),
            expected_output="FLOAT_SERIES",
        )
        candidate = MiningFactorCandidate.create(USER_FORMULA)
        self.assertEqual((ai_tdx.authority_status, ai_ir.authority_status, candidate.authority_status), ("NON_CANONICAL",) * 3)
        translated = TdxTranslator(self.registry).translate(
            candidate.expression_source,
            data_profile=self.profile,
            provenance_ref="mining-candidate:test",
        )
        self.assertTrue(translated.output("GOLDEN").definition.factor_definition_version_id.startswith("fdv_sha256_"))
        with self.assertRaisesRegex(TdxFormulaError, "UNSUPPORTED_TDX_OPERATOR"):
            TdxTranslator(self.registry).translate(
                "BAD:EMA(CLOSE,5);", data_profile=self.profile, provenance_ref="ai-draft:test"
            )

    def test_parse_failure_cannot_bind_or_enter_catalog(self) -> None:
        failed = FormulaDocumentVersion.create(
            language="TDX",
            source_text="BAD:=;",
            compatibility_profile_id=self.translation.document.compatibility_profile_id,
            parse_status=FormulaParseStatus.PARSE_ERROR,
            ast_digest=None,
            named_outputs=(),
            provenance_ref="user:bad",
        )
        with self.assertRaisesRegex(FactorAssetError, "TDX_PARSE_ERROR"):
            FormulaOutputBinding.create(
                failed,
                "BAD",
                "NAMED_OUTPUT",
                self.translation.output("GOLDEN").definition,
            )

    def test_integrated_fixture_ends_in_not_run_research_action(self) -> None:
        asset = self._asset("GOLDEN")
        snapshot = FactorCatalogSnapshotVersion.create((asset,))
        definition_ref = FactorAssetCatalogService(snapshot, (asset,)).get_factor_definition_ref(asset.asset_key)
        budget = ResearchLoopBudgetVersion.create(
            max_iterations=BudgetLimit.finite(1),
            max_actions=BudgetLimit.finite(1),
            max_candidates=BudgetLimit.finite(1),
            max_experiments=BudgetLimit.finite(1),
            max_model_calls=BudgetLimit.finite(1),
            resource_profile_ref="resource-profile:w0-smoke",
        )
        action = ResearchActionDraft.create(
            action_type=ResearchActionType.FACTOR_EVALUATE,
            exact_input_refs=(definition_ref,),
            requested_capability="factor.evaluate",
            expected_output_kind="FactorEvaluation",
            resource_profile_ref="resource-profile:w0-smoke",
            budget_version_id=budget.budget_version_id,
        )
        self.assertEqual(action.state.value, "NOT_RUN")
        self.assertEqual(action.exact_input_refs, (asset.factor_definition_version_id,))


if __name__ == "__main__":
    unittest.main()
