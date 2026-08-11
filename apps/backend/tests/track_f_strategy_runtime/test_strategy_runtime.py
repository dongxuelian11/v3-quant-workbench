from __future__ import annotations

import dataclasses
import inspect
import unittest

import v3_backend.domain.strategies.evaluator as evaluator_module
from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    PRE_ALPHA_CEILING,
)
from v3_backend.domain.strategies import (
    CrossSectionInputArtifact,
    DeterministicStrategyEvaluator,
    ExactCalendarReference,
    ExactSnapshotReference,
    ExactUniverseReference,
    GenericAdmittedArtifactReference,
    InputArtifactEvidence,
    PortfolioIntent,
    SelectionArtifact,
    SignalArtifact,
    StrategyArtifactError,
    StrategyBindingError,
    StrategyCompiler,
    StrategyEvaluationError,
    default_component_registry,
)

from .helpers import (
    build_runtime_fixture,
    build_strategy_ir,
    rebuild_binding,
    sha,
)


def all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {str(key) for key in value}.union(
            *(all_keys(item) for item in value.values())
        )
    if isinstance(value, list):
        return set().union(*(all_keys(item) for item in value)) if value else set()
    return set()


class StrategyBindingTests(unittest.TestCase):
    def test_caller_asserted_external_references_are_unresolved_and_capped(self) -> None:
        snapshot = ExactSnapshotReference(
            "snapshot-1", sha("1"), FORMAL_ADMITTED_CEILING
        )
        universe = ExactUniverseReference(
            "universe-1",
            sha("2"),
            "art_sha256_" + sha("f"),
            sha("f"),
            ("000001.SZ",),
            FORMAL_ADMITTED_CEILING,
        )
        calendar = ExactCalendarReference(
            "calendar-1", sha("3"), "Asia/Shanghai", FORMAL_ADMITTED_CEILING
        )
        generic = GenericAdmittedArtifactReference(
            "FUTURE_PREDICTION_ARTIFACT",
            "prediction-source-1",
            "art_sha256_" + sha("4"),
            sha("4"),
            FORMAL_ADMITTED_CEILING,
        )
        for reference in (snapshot, universe, calendar, generic):
            self.assertEqual(reference.truth_admission, PRE_ALPHA_CEILING)
            wire = reference.to_wire()
            self.assertEqual(wire["resolution"], "UNRESOLVED_CALLER_ASSERTED")
            self.assertNotIn("OWNER_REFERENCE", str(wire))

        fixture = build_runtime_fixture(reference_truth=FORMAL_ADMITTED_CEILING)
        self.assertEqual(fixture.binding.truth_admission, PRE_ALPHA_CEILING)
        with_generic = rebuild_binding(
            fixture, generic_artifact_references=(generic,)
        )
        self.assertEqual(with_generic.truth_admission, PRE_ALPHA_CEILING)

    def test_dataset_snapshot_or_time_changes_binding_not_definition(self) -> None:
        first = build_runtime_fixture()
        changed_snapshot = build_runtime_fixture(
            snapshot_id="snapshot-2", definition=first.definition
        )
        changed_time = build_runtime_fixture(
            cutoff_hour=17, definition=first.definition
        )
        self.assertEqual(
            first.definition.strategy_definition_version_id,
            changed_snapshot.definition.strategy_definition_version_id,
        )
        self.assertEqual(
            first.definition.strategy_definition_version_id,
            changed_time.definition.strategy_definition_version_id,
        )
        self.assertEqual(
            len(
                {
                    first.binding.strategy_evaluation_binding_version_id,
                    changed_snapshot.binding.strategy_evaluation_binding_version_id,
                    changed_time.binding.strategy_evaluation_binding_version_id,
                }
            ),
            3,
        )

    def test_latest_and_unresolved_references_are_rejected(self) -> None:
        with self.assertRaises(StrategyBindingError):
            ExactSnapshotReference("latest", sha("1"), PRE_ALPHA_CEILING)
        with self.assertRaises(StrategyBindingError):
            ExactSnapshotReference("unresolved", sha("1"), PRE_ALPHA_CEILING)

    def test_snapshot_and_universe_ids_must_match_dataset(self) -> None:
        fixture = build_runtime_fixture()
        with self.assertRaisesRegex(StrategyBindingError, "Snapshot reference"):
            rebuild_binding(
                fixture,
                snapshot=dataclasses.replace(
                    fixture.binding.snapshot, snapshot_id="snapshot-other"
                ),
            )
        with self.assertRaisesRegex(StrategyBindingError, "Universe reference"):
            rebuild_binding(
                fixture,
                universe=dataclasses.replace(
                    fixture.binding.universe, universe_version_id="universe-other"
                ),
            )

    def test_unresolved_universe_membership_changes_binding_identity(self) -> None:
        first = build_runtime_fixture(membership_character="f")
        changed = build_runtime_fixture(
            membership_character="9", definition=first.definition
        )
        self.assertEqual(
            first.binding.universe.universe_version_id,
            changed.binding.universe.universe_version_id,
        )
        self.assertNotEqual(
            first.binding.strategy_evaluation_binding_version_id,
            changed.binding.strategy_evaluation_binding_version_id,
        )
        self.assertEqual(
            first.binding.universe.to_wire()["resolution"],
            "UNRESOLVED_CALLER_ASSERTED",
        )

    def test_every_required_input_must_resolve_exactly(self) -> None:
        fixture = build_runtime_fixture()
        with self.assertRaisesRegex(StrategyEvaluationError, "exactly match"):
            DeterministicStrategyEvaluator().evaluate(
                definition=fixture.definition,
                binding=fixture.binding,
                inputs=(),
            )


class DeterministicRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = build_runtime_fixture()
        self.evaluator = DeterministicStrategyEvaluator()

    def evaluate(self):
        return self.evaluator.evaluate(
            definition=self.fixture.definition,
            binding=self.fixture.binding,
            inputs=(self.fixture.runtime_input,),
        )

    def test_same_exact_inputs_produce_identical_outputs(self) -> None:
        first = self.evaluate()
        second = self.evaluate()
        self.assertEqual(first, second)
        self.assertEqual(first.to_wire(), second.to_wire())

    def test_missing_policy_is_explicit_and_tie_break_is_stable(self) -> None:
        result = self.evaluate()
        assert result.signal_artifact is not None
        assert result.selection_artifact is not None
        self.assertEqual(
            result.signal_artifact.missing_instrument_ids, ("000004.SZ",)
        )
        self.assertEqual(
            tuple(value.instrument_id for value in result.selection_artifact.entries),
            ("000001.SZ", "000002.SZ"),
        )
        self.assertEqual(
            tuple(value.rank for value in result.selection_artifact.entries), (1, 2)
        )

    def test_out_of_universe_input_is_rejected(self) -> None:
        values = dict(self.fixture.runtime_input.values)
        values["NOT-IN-UNIVERSE"] = "99"
        poisoned = CrossSectionInputArtifact(
            binding_key=self.fixture.runtime_input.binding_key,
            artifact_id=self.fixture.runtime_input.artifact_id,
            content_sha256=self.fixture.runtime_input.content_sha256,
            decision_time=self.fixture.runtime_input.decision_time,
            values=values,
        )
        with self.assertRaisesRegex(StrategyEvaluationError, "out-of-universe"):
            self.evaluator.evaluate(
                definition=self.fixture.definition,
                binding=self.fixture.binding,
                inputs=(poisoned,),
            )

    def test_signal_identity_binds_definition_binding_and_input_artifact(self) -> None:
        result = self.evaluate()
        assert result.signal_artifact is not None
        signal = result.signal_artifact
        self.assertEqual(
            signal.strategy_definition_version_id,
            self.fixture.definition.strategy_definition_version_id,
        )
        self.assertEqual(
            signal.strategy_evaluation_binding_version_id,
            self.fixture.binding.strategy_evaluation_binding_version_id,
        )
        self.assertEqual(signal.input_artifacts[0].artifact_id, self.fixture.runtime_input.artifact_id)
        changed = build_runtime_fixture(
            factor_values=(4.0, 3.0, 2.0, None),
            runtime_values={
                "000001.SZ": "4",
                "000002.SZ": "3",
                "000003.SZ": "2",
                "000004.SZ": None,
            },
            definition=self.fixture.definition,
        )
        changed_result = self.evaluator.evaluate(
            definition=changed.definition,
            binding=changed.binding,
            inputs=(changed.runtime_input,),
        )
        assert changed_result.signal_artifact is not None
        self.assertNotEqual(
            signal.signal_artifact_id,
            changed_result.signal_artifact.signal_artifact_id,
        )

    def test_signal_factory_requires_exact_binding_input_evidence(self) -> None:
        result = self.evaluate()
        signal = result.signal_artifact
        assert signal is not None
        recreated = SignalArtifact.create(
            definition=self.fixture.definition,
            binding=self.fixture.binding,
            input_artifacts=signal.input_artifacts,
            decision_time=signal.decision_time,
            rows=signal.rows,
            missing_instrument_ids=signal.missing_instrument_ids,
        )
        self.assertEqual(recreated.signal_artifact_id, signal.signal_artifact_id)

        original = signal.input_artifacts[0]
        cases = (
            (dataclasses.replace(original, artifact_id="art_sha256_" + sha("9")),),
            (dataclasses.replace(original, content_sha256=sha("9")),),
            (),
            (
                original,
                InputArtifactEvidence("extra", "art_sha256_" + sha("8"), sha("8")),
            ),
        )
        for evidence in cases:
            with self.subTest(evidence=evidence):
                with self.assertRaisesRegex(StrategyArtifactError, "exactly match"):
                    SignalArtifact.create(
                        definition=self.fixture.definition,
                        binding=self.fixture.binding,
                        input_artifacts=evidence,
                        decision_time=signal.decision_time,
                        rows=signal.rows,
                        missing_instrument_ids=signal.missing_instrument_ids,
                    )

    def test_selection_factory_closes_definition_and_input_provenance(self) -> None:
        result = self.evaluate()
        selection = result.selection_artifact
        assert selection is not None
        recreated = SelectionArtifact.create(
            definition=self.fixture.definition,
            binding=self.fixture.binding,
            entries=selection.entries,
            excluded_instrument_ids=selection.excluded_instrument_ids,
            input_artifacts=selection.input_artifacts,
        )
        self.assertEqual(
            recreated.selection_artifact_id, selection.selection_artifact_id
        )

        other_definition = StrategyCompiler(default_component_registry()).compile(
            build_strategy_ir(selection_count=1)
        )
        with self.assertRaisesRegex(StrategyArtifactError, "definition/binding mismatch"):
            SelectionArtifact.create(
                definition=other_definition,
                binding=self.fixture.binding,
                entries=selection.entries,
                excluded_instrument_ids=selection.excluded_instrument_ids,
                input_artifacts=selection.input_artifacts,
            )
        fake = (
            dataclasses.replace(
                selection.input_artifacts[0], content_sha256=sha("9")
            ),
        )
        with self.assertRaisesRegex(StrategyArtifactError, "exactly match"):
            SelectionArtifact.create(
                definition=self.fixture.definition,
                binding=self.fixture.binding,
                entries=selection.entries,
                excluded_instrument_ids=selection.excluded_instrument_ids,
                input_artifacts=fake,
            )

    def test_portfolio_intent_factory_requires_exact_source_artifacts(self) -> None:
        result = self.evaluate()
        signal = result.signal_artifact
        selection = result.selection_artifact
        intent = result.portfolio_intent
        assert signal is not None and selection is not None and intent is not None
        create_parameters = inspect.signature(PortfolioIntent.create).parameters
        self.assertIn("selection_artifact", create_parameters)
        self.assertIn("signal_artifact", create_parameters)
        self.assertNotIn("source_selection_artifact_id", create_parameters)
        self.assertNotIn("source_signal_artifact_id", create_parameters)
        self.assertNotIn("input_artifacts", create_parameters)

        def recreate(
            *,
            source_selection: SelectionArtifact = selection,
            source_signal: SignalArtifact | None = signal,
        ) -> PortfolioIntent:
            return PortfolioIntent.create(
                definition=self.fixture.definition,
                binding=self.fixture.binding,
                selection_artifact=source_selection,
                signal_artifact=source_signal,
                exposure_mode=intent.exposure_mode,
                cash_policy=intent.cash_policy,
                rebalance_intent=intent.rebalance_intent,
                items=intent.items,
                constraints=intent.constraints,
            )

        self.assertEqual(recreate().portfolio_intent_id, intent.portfolio_intent_id)
        self.assertEqual(recreate(), recreate())
        self.assertEqual(
            intent.source_selection_provenance_sha256, selection.provenance_sha256
        )
        self.assertEqual(intent.source_signal_provenance_sha256, signal.provenance_sha256)
        without_signal = recreate(source_signal=None)
        self.assertIsNone(without_signal.source_signal_artifact_id)
        self.assertIsNone(without_signal.source_signal_provenance_sha256)
        with self.assertRaisesRegex(StrategyArtifactError, "exactly match source"):
            PortfolioIntent.create(
                definition=self.fixture.definition,
                binding=self.fixture.binding,
                selection_artifact=selection,
                signal_artifact=signal,
                exposure_mode=intent.exposure_mode,
                cash_policy=intent.cash_policy,
                rebalance_intent=intent.rebalance_intent,
                items=intent.items[:-1],
                constraints=intent.constraints,
            )
        with self.assertRaisesRegex(StrategyArtifactError, "canonical exact source"):
            recreate(
                source_selection=dataclasses.replace(
                    selection, selection_artifact_id="sel_sha256_" + sha("0")
                )
            )
        with self.assertRaisesRegex(StrategyArtifactError, "canonical exact source"):
            recreate(
                source_signal=dataclasses.replace(
                    signal, signal_artifact_id="sig_sha256_" + sha("0")
                )
            )

        other_binding_fixture = build_runtime_fixture(
            snapshot_id="snapshot-2", definition=self.fixture.definition
        )
        other_binding_result = self.evaluator.evaluate(
            definition=other_binding_fixture.definition,
            binding=other_binding_fixture.binding,
            inputs=(other_binding_fixture.runtime_input,),
        )
        assert other_binding_result.selection_artifact is not None
        assert other_binding_result.signal_artifact is not None
        with self.assertRaisesRegex(StrategyArtifactError, "SelectionArtifact.*binding"):
            recreate(source_selection=other_binding_result.selection_artifact)
        with self.assertRaisesRegex(StrategyArtifactError, "SignalArtifact.*binding"):
            recreate(source_signal=other_binding_result.signal_artifact)

        other_definition = StrategyCompiler(default_component_registry()).compile(
            build_strategy_ir(selection_count=1)
        )
        other_definition_fixture = build_runtime_fixture(definition=other_definition)
        other_definition_result = self.evaluator.evaluate(
            definition=other_definition_fixture.definition,
            binding=other_definition_fixture.binding,
            inputs=(other_definition_fixture.runtime_input,),
        )
        assert other_definition_result.selection_artifact is not None
        assert other_definition_result.signal_artifact is not None
        with self.assertRaisesRegex(StrategyArtifactError, "SelectionArtifact.*definition"):
            recreate(source_selection=other_definition_result.selection_artifact)
        with self.assertRaisesRegex(StrategyArtifactError, "SignalArtifact.*definition"):
            recreate(source_signal=other_definition_result.signal_artifact)

    def test_pre_alpha_ceiling_propagates_to_all_outputs(self) -> None:
        result = self.evaluate()
        self.assertEqual(self.fixture.binding.truth_admission, PRE_ALPHA_CEILING)
        self.assertEqual(result.signal_artifact.truth_admission, PRE_ALPHA_CEILING)  # type: ignore[union-attr]
        self.assertEqual(result.selection_artifact.truth_admission, PRE_ALPHA_CEILING)  # type: ignore[union-attr]
        self.assertEqual(result.portfolio_intent.truth_admission, PRE_ALPHA_CEILING)  # type: ignore[union-attr]

    def test_strategy_has_no_db_network_backtest_or_live_trading_capability(self) -> None:
        registry = default_component_registry().to_wire()
        capabilities = {
            capability
            for component in registry["components"]
            for capability in component["capabilities"]
        }
        self.assertEqual(capabilities, {"EXACT_BOUND_INPUT_ONLY"})
        signature = inspect.signature(DeterministicStrategyEvaluator.evaluate)
        self.assertEqual(
            set(signature.parameters), {"self", "definition", "binding", "inputs"}
        )
        source = inspect.getsource(evaluator_module)
        for forbidden_import in (
            "v3_backend.repositories",
            "v3_backend.contracts.backtest",
            "BacktestService",
            "TradeManager",
            "send_order",
        ):
            self.assertNotIn(forbidden_import, source)

    def test_outputs_are_only_signal_selection_and_portfolio_intent(self) -> None:
        result = self.evaluate()
        self.assertEqual(
            set(result.to_wire()),
            {"signal_artifact", "selection_artifact", "portfolio_intent"},
        )
        keys = {key.lower() for key in all_keys(result.to_wire())}
        self.assertFalse({"order", "orders", "fill", "fills"}.intersection(keys))

    def test_portfolio_intent_cannot_masquerade_as_target_weight_vector(self) -> None:
        result = self.evaluate()
        assert result.portfolio_intent is not None
        wire = result.portfolio_intent.to_wire()
        self.assertEqual(wire["artifact_type"], "PortfolioIntent")
        keys = {key.lower() for key in all_keys(wire)}
        self.assertNotIn("target_weight_vector", keys)
        self.assertEqual(
            wire["publisher_boundary"],
            "PORTFOLIO_SERVICE_IS_SOLE_TARGET_WEIGHT_VECTOR_PUBLISHER",
        )
        with self.assertRaises(StrategyArtifactError):
            dataclasses.replace(
                result.portfolio_intent,
                constraints={"target_weight_vector": []},
            )

    def test_output_instruments_are_within_exact_universe(self) -> None:
        result = self.evaluate()
        universe = set(self.fixture.binding.universe.instrument_ids)
        self.assertTrue(
            {value.instrument_id for value in result.signal_artifact.rows}.issubset(universe)  # type: ignore[union-attr]
        )
        self.assertTrue(
            {
                value.instrument_id
                for value in result.selection_artifact.entries  # type: ignore[union-attr]
            }.issubset(universe)
        )
        self.assertTrue(
            {
                value.instrument_id
                for value in result.portfolio_intent.items  # type: ignore[union-attr]
            }.issubset(universe)
        )


if __name__ == "__main__":
    unittest.main()
