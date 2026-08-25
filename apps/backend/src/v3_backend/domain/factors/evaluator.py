from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Protocol

from .ir import (
    BackendBinding,
    EvaluationAxis,
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


@dataclass(frozen=True, slots=True)
class PanelInputRow:
    session_date: date
    instrument_id: str
    features: Mapping[str, float | int | bool | None]
    missing_reasons: Mapping[str, str]
    source_partition_artifact_id: str
    source_partition_sha256: str

    def __post_init__(self) -> None:
        if not self.instrument_id or self.instrument_id != self.instrument_id.strip():
            raise FactorEvaluationError("panel instrument_id is invalid")
        if self.source_partition_artifact_id != "art_sha256_" + self.source_partition_sha256:
            raise FactorEvaluationError("panel source partition identity mismatch")
        if len(self.source_partition_sha256) != 64:
            raise FactorEvaluationError("panel source partition SHA-256 is invalid")
        object.__setattr__(self, "features", MappingProxyType(dict(self.features)))
        object.__setattr__(self, "missing_reasons", MappingProxyType(dict(self.missing_reasons)))


@dataclass(frozen=True, slots=True)
class PanelValueRow:
    session_date: date
    instrument_id: str
    value: FactorScalar
    missing_reason: str | None
    factor_definition_version_id: str
    source_partition_artifact_id: str
    source_partition_sha256: str


@dataclass(frozen=True, slots=True)
class PanelEvaluationResult:
    rows: tuple[PanelValueRow, ...]
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
        from .ir import (
            default_operator_registry,
            panel_operator_registry,
            signal_compatible_operator_registry,
        )

        legacy = default_operator_registry()
        signal = signal_compatible_operator_registry()
        panel = panel_operator_registry()
        if registry.to_wire() == legacy.to_wire():
            self.evaluator_version = "v3-factor-reference-evaluator/1.0.0"
        elif registry.to_wire() == signal.to_wire():
            self.evaluator_version = "v3-factor-reference-evaluator/1.1.1"
        elif registry.to_wire() == panel.to_wire():
            self.evaluator_version = "v3-factor-panel-evaluator-core/1.1.0"
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
        if name in {"SMA", "EMA", "HHV", "LLV", "SUM", "STD"}:
            source = inputs[0]
            timeperiod = parameters["timeperiod"]
            if name == "EMA":
                alpha = 2.0 / (timeperiod + 1.0)
                exponential: list[FloatScalar] = []
                seed: list[float] = []
                prior: float | None = None
                for value in source:
                    if value is None:
                        exponential.append(None)
                        seed = []
                        prior = None
                    elif isinstance(value, bool):
                        raise FactorEvaluationError("EMA input must be numeric")
                    elif prior is None:
                        seed.append(value)
                        if len(seed) < timeperiod:
                            exponential.append(None)
                        else:
                            prior = sum(seed[-timeperiod:]) / timeperiod
                            exponential.append(prior)
                    else:
                        prior = alpha * value + (1.0 - alpha) * prior
                        exponential.append(prior)
                return tuple(exponential)
            rolling: list[FloatScalar] = []
            for index in range(len(source)):
                if index < timeperiod - 1:
                    rolling.append(None)
                    continue
                window = source[index - timeperiod + 1 : index + 1]
                if any(value is None for value in window):
                    rolling.append(None)
                    continue
                if any(isinstance(value, bool) for value in window):
                    raise FactorEvaluationError(f"{name} input must be numeric")
                values = tuple(float(value) for value in window)
                if name == "SMA":
                    rolling.append(sum(values) / timeperiod)
                elif name == "HHV":
                    rolling.append(max(values))
                elif name == "LLV":
                    rolling.append(min(values))
                elif name == "SUM":
                    rolling.append(sum(values))
                else:
                    mean = sum(values) / timeperiod
                    rolling.append(math.sqrt(sum((value - mean) ** 2 for value in values) / timeperiod))
            return tuple(rolling)
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
        if name == "IF":
            condition, when_true, when_false = inputs
            output: list[FloatScalar] = []
            for predicate, yes, no in zip(condition, when_true, when_false, strict=True):
                if predicate is None:
                    output.append(None)
                elif not isinstance(predicate, bool):
                    raise FactorEvaluationError("IF condition must be boolean")
                else:
                    selected = yes if predicate else no
                    if selected is not None and isinstance(selected, bool):
                        raise FactorEvaluationError("IF branches must be numeric")
                    output.append(selected)  # type: ignore[arg-type]
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
        if name == "RANK":
            raise FactorEvaluationError("CROSS_SECTION_OPERATOR_REQUIRES_PANEL_EVALUATOR")
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


class DeterministicPanelEvaluator:
    """Evaluate the V1.1 canonical table without mixing instrument/date axes."""

    evaluator_version = "v3-factor-panel-evaluator/1.0.0"

    def __init__(self, registry: OperatorRegistry) -> None:
        from .ir import panel_operator_registry

        if registry.to_wire() != panel_operator_registry().to_wire():
            raise FactorEvaluationError(
                "OPERATOR_EXECUTION_SEMANTICS_MISMATCH: panel evaluation requires the exact V1.1 registry"
            )
        self._registry = registry
        self._reference = DeterministicReferenceEvaluator(registry)

    def evaluate(
        self,
        definition: FactorDefinitionVersion,
        rows: Sequence[PanelInputRow],
    ) -> PanelEvaluationResult:
        if definition.operator_registry_version != self._registry.registry_version:
            raise FactorEvaluationError("definition/operator registry version mismatch")
        canonical_rows = tuple(rows)
        if not canonical_rows:
            raise FactorEvaluationError("panel evaluation requires at least one row")
        keys = tuple((row.session_date, row.instrument_id) for row in canonical_rows)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise FactorEvaluationError(
                "panel rows must be uniquely sorted by session_date, instrument_id"
            )
        values, reasons, output_type = self._evaluate_node(definition.root, canonical_rows)
        if output_type is not definition.metadata.output_type:
            raise FactorEvaluationError("panel output type changed from canonical metadata")
        output_rows = tuple(
            PanelValueRow(
                session_date=row.session_date,
                instrument_id=row.instrument_id,
                value=value,
                missing_reason=None if value is not None else reason or "INPUT_MISSING",
                factor_definition_version_id=definition.factor_definition_version_id,
                source_partition_artifact_id=row.source_partition_artifact_id,
                source_partition_sha256=row.source_partition_sha256,
            )
            for row, value, reason in zip(canonical_rows, values, reasons, strict=True)
        )
        return PanelEvaluationResult(output_rows, output_type, self.evaluator_version)

    def _evaluate_node(
        self,
        node,
        rows: tuple[PanelInputRow, ...],
    ) -> tuple[FactorSeries, tuple[str | None, ...], ValueType]:
        if isinstance(node, FeatureNode):
            raw = tuple(row.features.get(node.feature_name) for row in rows)
            if node.value_type is ValueType.FLOAT_SERIES:
                values: FactorSeries = _validate_float_series(raw, node.feature_name)  # type: ignore[arg-type]
            else:
                values = _validate_boolean_series(raw, node.feature_name)  # type: ignore[arg-type]
            reasons = tuple(
                None if value is not None else row.missing_reasons.get(node.feature_name, "SOURCE_VALUE_MISSING")
                for row, value in zip(rows, values, strict=True)
            )
            return values, reasons, node.value_type
        if isinstance(node, NumericLiteralNode):
            value = float(node.decimal_value)
            return (value,) * len(rows), (None,) * len(rows), ValueType.FLOAT_SERIES
        if not isinstance(node, OperatorNode):
            raise FactorEvaluationError("unexpected Factor IR node")
        spec = self._registry.resolve(node.operator_name, node.operator_semantic_version)
        parameters = spec.validate_parameters(node.parameters)
        evaluated = tuple(self._evaluate_node(value, rows) for value in node.inputs)
        inputs = tuple(value[0] for value in evaluated)
        observed_types = tuple(value[2] for value in evaluated)
        if observed_types != spec.input_types:
            raise FactorEvaluationError("runtime input types changed from canonical IR")
        if spec.backend_binding is not BackendBinding.NATIVE_REFERENCE:
            raise FactorEvaluationError("panel registry contains a non-native operator")
        if spec.evaluation_axis is EvaluationAxis.ELEMENTWISE:
            output = self._reference._execute_native(spec.name, inputs, parameters)
        elif spec.evaluation_axis is EvaluationAxis.TIME_SERIES_PER_INSTRUMENT:
            output = self._evaluate_grouped(rows, inputs, parameters, spec.name, by="instrument")
        elif spec.evaluation_axis is EvaluationAxis.CROSS_SECTION_PER_DATE:
            if spec.name != "RANK":
                raise FactorEvaluationError("unsupported cross-section operator")
            output = self._rank_by_date(rows, inputs[0])
        else:
            raise FactorEvaluationError("operator evaluation_axis is unresolved")
        if spec.output_type is ValueType.FLOAT_SERIES:
            validated: FactorSeries = _validate_float_series(output, spec.key)  # type: ignore[arg-type]
        else:
            validated = _validate_boolean_series(output, spec.key)  # type: ignore[arg-type]
        instrument_counts: dict[str, int] = {}
        instrument_positions: list[int] = []
        for row in rows:
            position = instrument_counts.get(row.instrument_id, 0)
            instrument_positions.append(position)
            instrument_counts[row.instrument_id] = position + 1
        reasons = tuple(
            self._missing_reason(
                spec.name, index, instrument_positions[index], inputs, evaluated, parameters
            )
            if value is None
            else None
            for index, value in enumerate(validated)
        )
        return validated, reasons, spec.output_type

    def _evaluate_grouped(
        self,
        rows: tuple[PanelInputRow, ...],
        inputs: tuple[FactorSeries, ...],
        parameters: Mapping[str, int],
        name: str,
        *,
        by: str,
    ) -> FactorSeries:
        groups: dict[object, list[int]] = {}
        for index, row in enumerate(rows):
            key = row.instrument_id if by == "instrument" else row.session_date
            groups.setdefault(key, []).append(index)
        output: list[FactorScalar] = [None] * len(rows)
        for indices in groups.values():
            grouped_inputs = tuple(tuple(values[index] for index in indices) for values in inputs)
            grouped_output = self._reference._execute_native(name, grouped_inputs, parameters)
            for index, value in zip(indices, grouped_output, strict=True):
                output[index] = value
        return tuple(output)

    @staticmethod
    def _rank_by_date(rows: tuple[PanelInputRow, ...], source: FactorSeries) -> FactorSeries:
        groups: dict[date, list[int]] = {}
        for index, row in enumerate(rows):
            groups.setdefault(row.session_date, []).append(index)
        output: list[FactorScalar] = [None] * len(rows)
        for indices in groups.values():
            valid = [index for index in indices if source[index] is not None]
            if any(isinstance(source[index], bool) for index in valid):
                raise FactorEvaluationError("RANK input must be numeric")
            ordered = sorted(valid, key=lambda index: (float(source[index]), rows[index].instrument_id))  # type: ignore[arg-type]
            denominator = max(1, len(ordered) - 1)
            cursor = 0
            while cursor < len(ordered):
                end = cursor + 1
                while end < len(ordered) and source[ordered[end]] == source[ordered[cursor]]:
                    end += 1
                average_position = (cursor + end - 1) / 2.0
                percentile = 0.0 if len(ordered) == 1 else average_position / denominator
                for position in range(cursor, end):
                    output[ordered[position]] = percentile
                cursor = end
        return tuple(output)

    @staticmethod
    def _missing_reason(
        name: str,
        index: int,
        instrument_position: int,
        inputs: tuple[FactorSeries, ...],
        evaluated: tuple[tuple[FactorSeries, tuple[str | None, ...], ValueType], ...],
        parameters: Mapping[str, int],
    ) -> str:
        if name == "DIVIDE":
            return "DIVIDE_BY_ZERO_OR_MISSING"
        if name in {"SMA", "EMA", "HHV", "LLV", "SUM", "STD"}:
            period = parameters["timeperiod"]
            if instrument_position < period - 1:
                return "WARMUP"
        inherited = next(
            (
                child[1][index]
                for child in evaluated
                if child[0][index] is None and child[1][index] is not None
            ),
            None,
        )
        return inherited or "INPUT_MISSING_OR_WARMUP"


__all__ = [
    "DeterministicReferenceEvaluator",
    "BooleanScalar",
    "BooleanSeries",
    "EvaluationResult",
    "DeterministicPanelEvaluator",
    "FactorScalar",
    "FactorSeries",
    "FactorEvaluationError",
    "FloatScalar",
    "FloatSeries",
    "PanelEvaluationResult",
    "PanelInputRow",
    "PanelValueRow",
    "OperatorBackend",
    "Scalar",
    "Series",
]
