from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from .ir import (
    BackendBinding,
    FactorDefinitionVersion,
    FeatureNode,
    MissingSemantics,
    OperatorNode,
    OperatorRegistry,
)


Scalar = float | None
Series = tuple[Scalar, ...]


class FactorEvaluationError(ValueError):
    pass


class OperatorBackend(Protocol):
    backend_binding: BackendBinding

    def execute(
        self,
        operator_name: str,
        inputs: tuple[Series, ...],
        parameters: Mapping[str, int],
        missing_semantics: MissingSemantics,
    ) -> Series: ...


def _validated_series(values: Sequence[float | int | None], name: str) -> Series:
    result: list[Scalar] = []
    for index, value in enumerate(values):
        if value is None:
            result.append(None)
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FactorEvaluationError(f"{name}[{index}] must be numeric or None")
        normalized = float(value)
        if not math.isfinite(normalized):
            raise FactorEvaluationError(
                f"{name}[{index}] is non-finite; missing values must be explicit None"
            )
        result.append(normalized)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    values: Series
    evaluator_version: str


class DeterministicReferenceEvaluator:
    evaluator_version = "v3-factor-reference-evaluator/1.0.0"

    def __init__(
        self,
        registry: OperatorRegistry,
        backends: tuple[OperatorBackend, ...] = (),
    ) -> None:
        self._registry = registry
        mapping = {backend.backend_binding: backend for backend in backends}
        if len(mapping) != len(backends):
            raise FactorEvaluationError("only one backend per binding is allowed")
        self._backends = mapping

    def evaluate(
        self,
        definition: FactorDefinitionVersion,
        features: Mapping[str, Sequence[float | int | None]],
    ) -> EvaluationResult:
        if definition.operator_registry_version != self._registry.registry_version:
            raise FactorEvaluationError("definition/operator registry version mismatch")
        normalized = {
            name: _validated_series(values, name) for name, values in features.items()
        }
        expected = set(definition.metadata.input_features)
        if set(normalized) != expected:
            raise FactorEvaluationError(
                f"features must be exactly {sorted(expected)}"
            )
        lengths = {len(values) for values in normalized.values()}
        if len(lengths) != 1:
            raise FactorEvaluationError("all feature series must have equal length")
        values = self._evaluate_node(definition.root, normalized)
        return EvaluationResult(values=values, evaluator_version=self.evaluator_version)

    def _evaluate_node(self, node, features: Mapping[str, Series]) -> Series:
        if isinstance(node, FeatureNode):
            return features[node.feature_name]
        if not isinstance(node, OperatorNode):
            raise FactorEvaluationError("unexpected Factor IR node")
        spec = self._registry.resolve(
            node.operator_name, node.operator_semantic_version
        )
        parameters = spec.validate_parameters(node.parameters)
        inputs = tuple(self._evaluate_node(value, features) for value in node.inputs)
        if spec.backend_binding is BackendBinding.NATIVE_REFERENCE:
            return self._execute_native(spec.name, inputs, parameters)
        try:
            backend = self._backends[spec.backend_binding]
        except KeyError as error:
            raise FactorEvaluationError(
                f"backend {spec.backend_binding.value} is required for {spec.key}"
            ) from error
        result = backend.execute(
            spec.name, inputs, parameters, spec.missing_semantics
        )
        if len(result) != len(inputs[0]):
            raise FactorEvaluationError("operator backend changed series length")
        return _validated_series(result, spec.key)

    @staticmethod
    def _execute_native(
        name: str, inputs: tuple[Series, ...], parameters: Mapping[str, int]
    ) -> Series:
        if name == "LAG":
            periods = parameters["periods"]
            source = inputs[0]
            return (None,) * periods + source[: len(source) - periods] if periods else source
        if name not in {"ADD", "SUBTRACT", "MULTIPLY", "DIVIDE"}:
            raise FactorEvaluationError(f"unsupported native operator: {name}")
        left, right = inputs
        output: list[Scalar] = []
        for lhs, rhs in zip(left, right, strict=True):
            if lhs is None or rhs is None:
                output.append(None)
            elif name == "ADD":
                output.append(lhs + rhs)
            elif name == "SUBTRACT":
                output.append(lhs - rhs)
            elif name == "MULTIPLY":
                output.append(lhs * rhs)
            elif rhs == 0:
                output.append(None)
            else:
                output.append(lhs / rhs)
        if any(value is not None and not math.isfinite(value) for value in output):
            raise FactorEvaluationError("native operator produced a non-finite value")
        return tuple(output)


__all__ = [
    "DeterministicReferenceEvaluator",
    "EvaluationResult",
    "FactorEvaluationError",
    "OperatorBackend",
    "Scalar",
    "Series",
]
