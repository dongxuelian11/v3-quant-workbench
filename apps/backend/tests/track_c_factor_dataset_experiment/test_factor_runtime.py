from __future__ import annotations

import math
import unittest

from v3_backend.adapters.talib import TalibOperatorAdapter
from v3_backend.domain.factors import (
    DeterministicReferenceEvaluator,
    FactorDefinitionVersion,
    FactorEvaluationError,
    FeatureNode,
    MissingSemantics,
    OperatorNode,
    UnknownOperator,
    UnsafeFactorExpression,
    default_operator_registry,
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
        self.registry = default_operator_registry()
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


class ReferenceEvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = default_operator_registry()

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
