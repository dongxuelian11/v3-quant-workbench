from __future__ import annotations

import dataclasses
import inspect
import unittest

import v3_backend.domain.strategies.evaluator as evaluator_module
from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
from v3_backend.domain.strategies import (
    CrossSectionInputArtifact,
    DeterministicStrategyEvaluator,
    ExactSnapshotReference,
    StrategyArtifactError,
    StrategyBindingError,
    StrategyEvaluationError,
    default_component_registry,
)

from .helpers import build_runtime_fixture, sha


def all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {str(key) for key in value}.union(
            *(all_keys(item) for item in value.values())
        )
    if isinstance(value, list):
        return set().union(*(all_keys(item) for item in value)) if value else set()
    return set()


class StrategyBindingTests(unittest.TestCase):
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
