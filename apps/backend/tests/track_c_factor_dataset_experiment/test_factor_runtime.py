from __future__ import annotations

import math
import unittest

from v3_backend.adapters.talib import TalibOperatorAdapter
from v3_backend.domain.factors import (
    DeterministicReferenceEvaluator,
    FactorDefinitionVersion,
    FactorEvaluationError,
    FactorIrError,
    FactorTypeError,
    FeatureNode,
    MissingSemantics,
    OperatorNode,
    NumericLiteralNode,
    UnknownOperator,
    UnsafeFactorExpression,
    ValueType,
    default_operator_registry,
    signal_compatible_operator_registry,
)


class FakeTalibProvider:
    wrapper_version = "0.7.1"
    core_version = "0.7.1-test-double"

    def __init__(self) -> None:
        self.observed: tuple[tuple[float, ...], int] | None = None

    def sma(self, values, timeperiod: int):
        values = tuple(float(value) for value in values)
        self.observed = (values, timeperiod)
        result: list[float] = []
        poisoned = False
        for index in range(len(values)):
            window = values[max(0, index - timeperiod + 1) : index + 1]
            if any(math.isnan(value) for value in window):
                poisoned = True
            if index < timeperiod - 1 or poisoned:
                result.append(math.nan)
            else:
                result.append(sum(window) / timeperiod)
        return result


class FactorIrTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = signal_compatible_operator_registry()
        self.close = FeatureNode("close", "eod.close/1.0.0")

    def test_closed_ast_rejects_unknown_operator(self) -> None:
        node = OperatorNode("UNKNOWN", "1.0.0", (self.close,), {})
        with self.assertRaises(UnknownOperator):
            FactorDefinitionVersion.create("unknown", node, self.registry)

    def test_lookahead_unsafe_expression_is_rejected(self) -> None:
        node = OperatorNode("LEAD", "1.0.0", (self.close,), {})
        with self.assertRaises(UnsafeFactorExpression):
            FactorDefinitionVersion.create("future", node, self.registry)

    def test_operator_lookback_lag_and_complexity_propagate(self) -> None:
        lagged = OperatorNode("LAG", "1.0.0", (self.close,), {"periods": 2})
        smoothed = OperatorNode(
            "SMA", "1.0.0", (lagged,), {"timeperiod": 3}
        )
        root = OperatorNode(
            "ADD",
            "1.0.0",
            (smoothed, FeatureNode("volume", "eod.volume/1.0.0")),
            {},
        )
        definition = FactorDefinitionVersion.create("smoothed", root, self.registry)
        self.assertEqual(definition.metadata.lookback, 4)
        self.assertEqual(definition.metadata.lag, 2)
        self.assertEqual(definition.metadata.complexity, 6)
        self.assertEqual(definition.metadata.input_features, ("close", "volume"))

    def test_numeric_literal_is_canonical_and_constant_only_root_fails_closed(self) -> None:
        self.assertEqual(NumericLiteralNode.create("1.000").canonical_decimal, "1")
        self.assertEqual(NumericLiteralNode.create(1), NumericLiteralNode.create(1.0))
        with self.assertRaises(FactorIrError):
            NumericLiteralNode.create(True)
        with self.assertRaises(FactorIrError):
            NumericLiteralNode.create(float("inf"))
        with self.assertRaisesRegex(FactorIrError, "evaluation domain"):
            FactorDefinitionVersion.create(
                "constant", NumericLiteralNode.create(1), self.registry
            )

    def test_signal_types_are_closed_and_propagate_to_metadata(self) -> None:
        threshold = OperatorNode(
            "GT", "1.0.0", (self.close, NumericLiteralNode.create(10)), {}
        )
        definition = FactorDefinitionVersion.create("above_ten", threshold, self.registry)
        self.assertIs(definition.metadata.output_type, ValueType.BOOLEAN_SERIES)
        with self.assertRaises(FactorTypeError):
            FactorDefinitionVersion.create(
                "invalid_and",
                OperatorNode("AND", "1.0.0", (self.close, threshold), {}),
                self.registry,
            )
        with self.assertRaises(FactorTypeError):
            FactorDefinitionVersion.create(
                "invalid_add",
                OperatorNode("ADD", "1.0.0", (threshold, threshold), {}),
                self.registry,
            )

    def test_cross_has_one_observation_lookback_and_no_future_dependency(self) -> None:
        cross = OperatorNode(
            "CROSS",
            "1.0.0",
            (self.close, FeatureNode("open", "eod.open/1.0.0")),
            {},
        )
        definition = FactorDefinitionVersion.create("cross", cross, self.registry)
        self.assertEqual(definition.metadata.lookback, 1)
        self.assertEqual(definition.metadata.lag, 0)
        self.assertIs(definition.metadata.output_type, ValueType.BOOLEAN_SERIES)


class ReferenceEvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = signal_compatible_operator_registry()

    def test_deterministic_native_evaluation_and_missing_semantics(self) -> None:
        left = FeatureNode("left", "field/1.0.0")
        right = FeatureNode("right", "field/1.0.0")
        definition = FactorDefinitionVersion.create(
            "ratio",
            OperatorNode("DIVIDE", "1.0.0", (left, right), {}),
            self.registry,
        )
        evaluator = DeterministicReferenceEvaluator(self.registry)
        features = {"left": [2, None, 6, 8], "right": [1, 2, 0, 4]}
        first = evaluator.evaluate(definition, features)
        second = evaluator.evaluate(definition, features)
        self.assertEqual(first, second)
        self.assertEqual(first.values, (2.0, None, None, 2.0))
        self.assertIs(first.output_type, ValueType.FLOAT_SERIES)
        self.assertEqual(first.evaluator_version, "v3-factor-reference-evaluator/1.1.0")

    def test_legacy_numeric_registry_and_evaluator_identity_remain_exact(self) -> None:
        legacy_registry = default_operator_registry()
        self.assertNotEqual(legacy_registry.registry_version, self.registry.registry_version)
        definition = FactorDefinitionVersion.create(
            "legacy_close", FeatureNode("close", "field/1.0.0"), legacy_registry
        )
        legacy = DeterministicReferenceEvaluator(legacy_registry)
        self.assertEqual(
            legacy.evaluate(definition, {"close": [1, 2]}).evaluator_version,
            "v3-factor-reference-evaluator/1.0.0",
        )
        with self.assertRaisesRegex(FactorEvaluationError, "registry version mismatch"):
            DeterministicReferenceEvaluator(self.registry).evaluate(
                definition, {"close": [1, 2]}
            )

    def test_literal_comparison_boolean_and_cross_execute_without_numeric_coercion(self) -> None:
        left = FeatureNode("left", "field/1.0.0")
        right = FeatureNode("right", "field/1.0.0")
        cross = OperatorNode("CROSS", "1.0.0", (left, right), {})
        above_zero = OperatorNode(
            "GT", "1.0.0", (left, NumericLiteralNode.create("0.0")), {}
        )
        root = OperatorNode("AND", "1.0.0", (cross, above_zero), {})
        definition = FactorDefinitionVersion.create("signal", root, self.registry)
        result = DeterministicReferenceEvaluator(self.registry).evaluate(
            definition,
            {
                "left": [0, 1, 3, None, 5],
                "right": [1, 1, 2, 2, 4],
            },
        )
        self.assertIs(result.output_type, ValueType.BOOLEAN_SERIES)
        self.assertEqual(result.values, (None, False, True, None, None))
        self.assertTrue(all(value is None or isinstance(value, bool) for value in result.values))

    def test_cross_parity_and_missing_semantics_are_explicit(self) -> None:
        definition = FactorDefinitionVersion.create(
            "cross",
            OperatorNode(
                "CROSS",
                "1.0.0",
                (
                    FeatureNode("left", "field/1.0.0"),
                    FeatureNode("right", "field/1.0.0"),
                ),
                {},
            ),
            self.registry,
        )
        result = DeterministicReferenceEvaluator(self.registry).evaluate(
            definition,
            {
                "left": [0, 2, 3, 4, None, 6],
                "right": [1, 1, 2, 3, 4, 5],
            },
        )
        # formula-go@511fd6e and MyTT@7cd36ae agree on prev <= / current >.
        # V3 intentionally keeps first/missing history as None instead of their 0/False fallback.
        self.assertEqual(result.values, (None, True, False, False, None, None))

    def test_boolean_feature_validation_rejects_numeric_truthiness(self) -> None:
        flag = FeatureNode("flag", "signal/1.0.0", ValueType.BOOLEAN_SERIES)
        definition = FactorDefinitionVersion.create(
            "not_flag", OperatorNode("NOT", "1.0.0", (flag,), {}), self.registry
        )
        evaluator = DeterministicReferenceEvaluator(self.registry)
        self.assertEqual(
            evaluator.evaluate(definition, {"flag": [True, False, None]}).values,
            (False, True, None),
        )
        with self.assertRaises(FactorEvaluationError):
            evaluator.evaluate(definition, {"flag": [1, 0]})

    def test_non_finite_input_is_not_silently_coerced(self) -> None:
        feature = FeatureNode("close", "field/1.0.0")
        definition = FactorDefinitionVersion.create("close", feature, self.registry)
        evaluator = DeterministicReferenceEvaluator(self.registry)
        with self.assertRaises(FactorEvaluationError):
            evaluator.evaluate(definition, {"close": [1.0, math.nan]})

    def test_talib_result_adapter_semantics(self) -> None:
        provider = FakeTalibProvider()
        adapter = TalibOperatorAdapter(provider)
        output = adapter.execute(
            "SMA",
            ((1.0, 2.0, 3.0, None, 4.0, 5.0, 6.0),),
            {"timeperiod": 3},
            MissingSemantics.PROPAGATE,
        )
        self.assertEqual(output, (None, None, 2.0, None, None, None, None))
        assert provider.observed is not None
        self.assertTrue(math.isnan(provider.observed[0][3]))
        self.assertEqual(provider.observed[1], 3)
        self.assertEqual(adapter.dependency_evidence.wrapper_version, "0.7.1")
        self.assertEqual(
            adapter.dependency_evidence.authority,
            "NON_AUTHORITATIVE_COMPUTE_BACKEND",
        )

    def test_real_talib_adapter_when_dependency_is_available(self) -> None:
        try:
            adapter = TalibOperatorAdapter()
        except RuntimeError as error:
            self.skipTest(str(error))
        output = adapter.execute(
            "SMA",
            ((1.0, 2.0, 3.0, None, 4.0, 5.0, 6.0),),
            {"timeperiod": 3},
            MissingSemantics.PROPAGATE,
        )
        self.assertEqual(output, (None, None, 2.0, None, None, None, None))


if __name__ == "__main__":
    unittest.main()
