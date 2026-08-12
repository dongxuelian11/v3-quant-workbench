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
    NumericLiteralNode,
    OperatorNode,
    OperatorRegistry,
    ValueType,
)


FloatScalar = float | None
BooleanScalar = bool | None
FactorScalar = float | bool | None
FloatSeries = tuple[FloatScalar, ...]
BooleanSeries = tuple[BooleanScalar, ...]
FactorSeries = tuple[FactorScalar, ...]

# Backward-compatible aliases for numeric-only operator backends.
Scalar = FloatScalar
Series = FloatSeries


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


def _validate_float_series(
    values: Sequence[float | int | None], name: str
) -> FloatSeries:
    result: list[FloatScalar] = []
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


def _validate_boolean_series(
    values: Sequence[bool | None], name: str
) -> BooleanSeries:
    result: list[BooleanScalar] = []
    for index, value in enumerate(values):
        if value is None or isinstance(value, bool):
            result.append(value)
            continue
        raise FactorEvaluationError(f"{name}[{index}] must be bool or None")
    return tuple(result)


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    values: FactorSeries
    output_type: ValueType
    evaluator_version: str


class DeterministicReferenceEvaluator:
    evaluator_version = "v3-factor-reference-evaluator/1.1.1"

    def __init__(
        self,
        registry: OperatorRegistry,
        backends: tuple[OperatorBackend, ...] = (),
    ) -> None:
        self._registry = registry
        from .ir import default_operator_registry, signal_compatible_operator_registry

        legacy = default_operator_registry()
        signal = signal_compatible_operator_registry()
        if registry.to_wire() == legacy.to_wire():
            self.evaluator_version = "v3-factor-reference-evaluator/1.0.0"
        elif registry.to_wire() == signal.to_wire():
            self.evaluator_version = "v3-factor-reference-evaluator/1.1.1"
        else:
            raise FactorEvaluationError(
                "OPERATOR_EXECUTION_SEMANTICS_MISMATCH: registry is not an exact V3 native implementation registry"
            )
        mapping = {backend.backend_binding: backend for backend in backends}
        if len(mapping) != len(backends):
            raise FactorEvaluationError("only one backend per binding is allowed")
        self._backends = mapping

    def evaluate(
        self,
        definition: FactorDefinitionVersion,
        features: Mapping[str, Sequence[float | int | bool | None]],
    ) -> EvaluationResult:
        if definition.operator_registry_version != self._registry.registry_version:
            raise FactorEvaluationError("definition/operator registry version mismatch")
        expected_types = self._feature_types(definition.root)
        expected = set(expected_types)
        normalized: dict[str, FactorSeries] = {}
        for name, values in features.items():
            value_type = expected_types.get(name)
            if value_type is ValueType.FLOAT_SERIES:
                normalized[name] = _validate_float_series(values, name)  # type: ignore[arg-type]
            elif value_type is ValueType.BOOLEAN_SERIES:
                normalized[name] = _validate_boolean_series(values, name)  # type: ignore[arg-type]
            else:
                normalized[name] = tuple(values)
        if set(normalized) != expected:
            raise FactorEvaluationError(
                f"features must be exactly {sorted(expected)}"
            )
        lengths = {len(values) for values in normalized.values()}
        if len(lengths) != 1:
            raise FactorEvaluationError("all feature series must have equal length")
        domain_length = next(iter(lengths))
        values, output_type = self._evaluate_node(
            definition.root, normalized, domain_length
        )
        if output_type is not definition.metadata.output_type:
            raise FactorEvaluationError("evaluated output type changed from canonical metadata")
        return EvaluationResult(
            values=values,
            output_type=output_type,
            evaluator_version=self.evaluator_version,
        )

    @staticmethod
    def _feature_types(node) -> dict[str, ValueType]:
        observed: dict[str, ValueType] = {}

        def visit(value) -> None:
            if isinstance(value, FeatureNode):
                prior = observed.get(value.feature_name)
                if prior is not None and prior is not value.value_type:
                    raise FactorEvaluationError(
                        f"feature {value.feature_name} has conflicting canonical types"
                    )
                observed[value.feature_name] = value.value_type
            elif isinstance(value, OperatorNode):
                for child in value.inputs:
                    visit(child)
            elif not isinstance(value, NumericLiteralNode):
                raise FactorEvaluationError("unexpected Factor IR node")

        visit(node)
        return observed

    def _evaluate_node(
        self,
        node,
        features: Mapping[str, FactorSeries],
        domain_length: int,
    ) -> tuple[FactorSeries, ValueType]:
        if isinstance(node, FeatureNode):
            return features[node.feature_name], node.value_type
        if isinstance(node, NumericLiteralNode):
            value = float(node.decimal_value)
            if not math.isfinite(value):
                raise FactorEvaluationError("numeric literal cannot be represented finitely")
            return (value,) * domain_length, ValueType.FLOAT_SERIES
        if not isinstance(node, OperatorNode):
            raise FactorEvaluationError("unexpected Factor IR node")
        spec = self._registry.resolve(
            node.operator_name, node.operator_semantic_version
        )
        parameters = spec.validate_parameters(node.parameters)
        evaluated = tuple(
            self._evaluate_node(value, features, domain_length) for value in node.inputs
        )
        inputs = tuple(value[0] for value in evaluated)
        observed_types = tuple(value[1] for value in evaluated)
        if observed_types != spec.input_types:
            raise FactorEvaluationError("runtime input types changed from canonical IR")
        if spec.backend_binding is BackendBinding.NATIVE_REFERENCE:
            result = self._execute_native(spec.name, inputs, parameters)
            if len(result) != len(inputs[0]):
                raise FactorEvaluationError("native operator changed series length")
            if spec.output_type is ValueType.FLOAT_SERIES:
                validated: FactorSeries = _validate_float_series(result, spec.key)  # type: ignore[arg-type]
            elif spec.output_type is ValueType.BOOLEAN_SERIES:
                validated = _validate_boolean_series(result, spec.key)  # type: ignore[arg-type]
            else:  # pragma: no cover - ValueType is deliberately closed.
                raise FactorEvaluationError("unsupported native output type")
            return validated, spec.output_type
        try:
            backend = self._backends[spec.backend_binding]
        except KeyError as error:
            raise FactorEvaluationError(
                f"backend {spec.backend_binding.value} is required for {spec.key}"
            ) from error
        if any(value is not ValueType.FLOAT_SERIES for value in spec.input_types):
            raise FactorEvaluationError("external operator backends are numeric-only")
        result = backend.execute(  # type: ignore[arg-type]
            spec.name, inputs, parameters, spec.missing_semantics  # type: ignore[arg-type]
        )
        if len(result) != len(inputs[0]):
            raise FactorEvaluationError("operator backend changed series length")
        return _validate_float_series(result, spec.key), spec.output_type

    @staticmethod
    def _execute_native(
        name: str, inputs: tuple[FactorSeries, ...], parameters: Mapping[str, int]
    ) -> FactorSeries:
        if name == "LAG":
            periods = parameters["periods"]
            source = inputs[0]
            return (None,) * periods + source[: len(source) - periods] if periods else source
        if name in {"GT", "GTE", "LT", "LTE", "EQ", "NE"}:
            left, right = inputs
            output: list[BooleanScalar] = []
            for lhs, rhs in zip(left, right, strict=True):
                if lhs is None or rhs is None:
                    output.append(None)
                elif isinstance(lhs, bool) or isinstance(rhs, bool):
                    raise FactorEvaluationError("comparison inputs must be numeric")
                elif name == "GT":
                    output.append(lhs > rhs)
                elif name == "GTE":
                    output.append(lhs >= rhs)
                elif name == "LT":
                    output.append(lhs < rhs)
                elif name == "LTE":
                    output.append(lhs <= rhs)
                elif name == "EQ":
                    output.append(lhs == rhs)
                else:
                    output.append(lhs != rhs)
            return tuple(output)
        if name in {"AND", "OR"}:
            left, right = inputs
            boolean_output: list[BooleanScalar] = []
            for lhs, rhs in zip(left, right, strict=True):
                if lhs is None or rhs is None:
                    boolean_output.append(None)
                elif not isinstance(lhs, bool) or not isinstance(rhs, bool):
                    raise FactorEvaluationError("boolean operators require bool inputs")
                else:
                    boolean_output.append(lhs and rhs if name == "AND" else lhs or rhs)
            return tuple(boolean_output)
        if name == "NOT":
            output = []
            for value in inputs[0]:
                if value is None:
                    output.append(None)
                elif not isinstance(value, bool):
                    raise FactorEvaluationError("NOT requires bool inputs")
                else:
                    output.append(not value)
            return tuple(output)
        if name == "CROSS":
            left, right = inputs
            crossed: list[BooleanScalar] = [None]
            for index in range(1, len(left)):
                values = (left[index - 1], right[index - 1], left[index], right[index])
                if any(value is None for value in values):
                    crossed.append(None)
                elif any(isinstance(value, bool) for value in values):
                    raise FactorEvaluationError("CROSS inputs must be numeric")
                else:
                    prior_left, prior_right, current_left, current_right = values
                    crossed.append(
                        bool(prior_left <= prior_right and current_left > current_right)  # type: ignore[operator]
                    )
            return tuple(crossed)
        if name not in {"ADD", "SUBTRACT", "MULTIPLY", "DIVIDE"}:
            raise FactorEvaluationError(f"unsupported native operator: {name}")
        left, right = inputs
        numeric_output: list[FloatScalar] = []
        for lhs, rhs in zip(left, right, strict=True):
            if lhs is None or rhs is None:
                numeric_output.append(None)
            elif isinstance(lhs, bool) or isinstance(rhs, bool):
                raise FactorEvaluationError("arithmetic inputs must be numeric")
            elif name == "ADD":
                numeric_output.append(lhs + rhs)
            elif name == "SUBTRACT":
                numeric_output.append(lhs - rhs)
            elif name == "MULTIPLY":
                numeric_output.append(lhs * rhs)
            elif rhs == 0:
                numeric_output.append(None)
            else:
                numeric_output.append(lhs / rhs)
        if any(value is not None and not math.isfinite(value) for value in numeric_output):
            raise FactorEvaluationError("native operator produced a non-finite value")
        return tuple(numeric_output)


__all__ = [
    "DeterministicReferenceEvaluator",
    "BooleanScalar",
    "BooleanSeries",
    "EvaluationResult",
    "FactorScalar",
    "FactorSeries",
    "FactorEvaluationError",
    "FloatScalar",
    "FloatSeries",
    "OperatorBackend",
    "Scalar",
    "Series",
]
