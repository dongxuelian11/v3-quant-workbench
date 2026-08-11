from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, Protocol, TypeAlias

from v3_backend.provenance.canonical_hash import canonical_sha256


class FactorIrError(ValueError):
    """Base error for closed Factor IR validation failures."""


class UnknownOperator(FactorIrError):
    pass


class UnsafeFactorExpression(FactorIrError):
    pass


class FactorTypeError(FactorIrError):
    pass


class ValueType(StrEnum):
    FLOAT_SERIES = "FLOAT_SERIES"


class AvailabilitySemantics(StrEnum):
    OBSERVATION_AVAILABLE_TIME = "OBSERVATION_AVAILABLE_TIME"


class MissingSemantics(StrEnum):
    PROPAGATE = "PROPAGATE"
    DIVIDE_BY_ZERO_IS_MISSING = "DIVIDE_BY_ZERO_IS_MISSING"


class BackendBinding(StrEnum):
    NATIVE_REFERENCE = "NATIVE_REFERENCE"
    TA_LIB = "TA_LIB"


class ParameterKind(StrEnum):
    INTEGER = "INTEGER"


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    name: str
    kind: ParameterKind
    minimum: int
    maximum: int

    def __post_init__(self) -> None:
        if not self.name or self.name != self.name.strip():
            raise FactorIrError("parameter name must be non-empty without edge whitespace")
        if self.minimum > self.maximum:
            raise FactorIrError("parameter bounds are reversed")

    def validate(self, value: object) -> int:
        if self.kind is not ParameterKind.INTEGER:
            raise FactorIrError(f"unsupported parameter kind: {self.kind}")
        if not isinstance(value, int) or isinstance(value, bool):
            raise FactorIrError(f"parameter {self.name} must be an integer")
        if value < self.minimum or value > self.maximum:
            raise FactorIrError(
                f"parameter {self.name} must be in [{self.minimum}, {self.maximum}]"
            )
        return value

    def to_wire(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "minimum": self.minimum,
            "maximum": self.maximum,
        }


@dataclass(frozen=True, slots=True)
class OperatorSpec:
    name: str
    semantic_version: str
    arity: int
    input_types: tuple[ValueType, ...]
    output_type: ValueType
    fixed_lookback: int
    fixed_lag: int
    missing_semantics: MissingSemantics
    pit_safe: bool
    deterministic: bool
    backend_binding: BackendBinding
    parameters: tuple[ParameterSpec, ...] = ()
    lookback_parameter: str | None = None
    lag_parameter: str | None = None
    complexity_weight: int = 1

    def __post_init__(self) -> None:
        if not self.name or not self.semantic_version:
            raise FactorIrError("operator name and semantic_version are required")
        if self.arity < 1 or len(self.input_types) != self.arity:
            raise FactorIrError("operator arity must match input_types")
        if self.fixed_lookback < 0:
            raise FactorIrError("operator fixed_lookback must be non-negative")
        if self.pit_safe and self.fixed_lag < 0:
            raise FactorIrError("PIT-safe operator cannot have a negative lag")
        if not self.deterministic:
            raise FactorIrError("V0 operator registry accepts deterministic operators only")
        parameter_names = tuple(parameter.name for parameter in self.parameters)
        if len(parameter_names) != len(set(parameter_names)):
            raise FactorIrError("operator parameter names must be unique")
        for field_name, parameter_name in (
            ("lookback_parameter", self.lookback_parameter),
            ("lag_parameter", self.lag_parameter),
        ):
            if parameter_name is not None and parameter_name not in parameter_names:
                raise FactorIrError(f"{field_name} must name a declared parameter")
        if self.complexity_weight < 1:
            raise FactorIrError("operator complexity_weight must be positive")

    @property
    def key(self) -> str:
        return f"{self.name}@{self.semantic_version}"

    def validate_parameters(self, values: Mapping[str, object]) -> dict[str, int]:
        expected = {parameter.name for parameter in self.parameters}
        if set(values) != expected:
            raise FactorIrError(
                f"operator {self.key} parameters must be exactly {sorted(expected)}"
            )
        return {
            parameter.name: parameter.validate(values[parameter.name])
            for parameter in self.parameters
        }

    def resolved_lookback(self, values: Mapping[str, int]) -> int:
        if self.lookback_parameter is None:
            return self.fixed_lookback
        return self.fixed_lookback + values[self.lookback_parameter] - 1

    def resolved_lag(self, values: Mapping[str, int]) -> int:
        if self.lag_parameter is None:
            return self.fixed_lag
        return self.fixed_lag + values[self.lag_parameter]

    def to_wire(self) -> dict[str, object]:
        return {
            "name": self.name,
            "semantic_version": self.semantic_version,
            "arity": self.arity,
            "input_types": [value.value for value in self.input_types],
            "output_type": self.output_type.value,
            "fixed_lookback": self.fixed_lookback,
            "fixed_lag": self.fixed_lag,
            "missing_semantics": self.missing_semantics.value,
            "pit_safe": self.pit_safe,
            "deterministic": self.deterministic,
            "backend_binding": self.backend_binding.value,
            "parameters": [parameter.to_wire() for parameter in self.parameters],
            "lookback_parameter": self.lookback_parameter,
            "lag_parameter": self.lag_parameter,
            "complexity_weight": self.complexity_weight,
        }


class OperatorRegistry:
    def __init__(self, specs: tuple[OperatorSpec, ...]) -> None:
        if not specs:
            raise FactorIrError("operator registry cannot be empty")
        by_key = {spec.key: spec for spec in specs}
        if len(by_key) != len(specs):
            raise FactorIrError("operator registry keys must be unique")
        self._specs = MappingProxyType(by_key)
        self._registry_version = "opreg_sha256_" + canonical_sha256(
            [by_key[key].to_wire() for key in sorted(by_key)]
        )

    @property
    def registry_version(self) -> str:
        return self._registry_version

    def resolve(self, name: str, semantic_version: str) -> OperatorSpec:
        key = f"{name}@{semantic_version}"
        try:
            return self._specs[key]
        except KeyError as error:
            raise UnknownOperator(f"unknown closed-world operator: {key}") from error

    def to_wire(self) -> dict[str, object]:
        return {
            "registry_version": self.registry_version,
            "operators": [self._specs[key].to_wire() for key in sorted(self._specs)],
        }


@dataclass(frozen=True, slots=True)
class FeatureNode:
    feature_name: str
    field_semantic_version: str
    value_type: ValueType = ValueType.FLOAT_SERIES
    availability_semantics: AvailabilitySemantics = (
        AvailabilitySemantics.OBSERVATION_AVAILABLE_TIME
    )
    missing_semantics: MissingSemantics = MissingSemantics.PROPAGATE

    def __post_init__(self) -> None:
        if not self.feature_name or not self.field_semantic_version:
            raise FactorIrError("feature name and field semantic version are required")

    def to_wire(self) -> dict[str, object]:
        return {
            "node_type": "FEATURE",
            "feature_name": self.feature_name,
            "field_semantic_version": self.field_semantic_version,
            "value_type": self.value_type.value,
            "availability_semantics": self.availability_semantics.value,
            "missing_semantics": self.missing_semantics.value,
        }


@dataclass(frozen=True, slots=True)
class OperatorNode:
    operator_name: str
    operator_semantic_version: str
    inputs: tuple[FactorNode, ...]
    parameters: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.operator_name or not self.operator_semantic_version:
            raise FactorIrError("operator node requires an exact operator version")
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))

    def to_wire(self) -> dict[str, object]:
        return {
            "node_type": "OPERATOR",
            "operator_name": self.operator_name,
            "operator_semantic_version": self.operator_semantic_version,
            "inputs": [value.to_wire() for value in self.inputs],
            "parameters": dict(self.parameters),
        }


FactorNode: TypeAlias = FeatureNode | OperatorNode


@dataclass(frozen=True, slots=True)
class FactorMetadata:
    output_type: ValueType
    lookback: int
    lag: int
    complexity: int
    input_features: tuple[str, ...]
    operator_keys: tuple[str, ...]
    missing_semantics: tuple[MissingSemantics, ...]

    def to_wire(self) -> dict[str, object]:
        return {
            "output_type": self.output_type.value,
            "lookback": self.lookback,
            "lag": self.lag,
            "complexity": self.complexity,
            "input_features": list(self.input_features),
            "operator_keys": list(self.operator_keys),
            "missing_semantics": [value.value for value in self.missing_semantics],
        }


def validate_factor_node(node: FactorNode, registry: OperatorRegistry) -> FactorMetadata:
    if isinstance(node, FeatureNode):
        return FactorMetadata(
            output_type=node.value_type,
            lookback=0,
            lag=0,
            complexity=1,
            input_features=(node.feature_name,),
            operator_keys=(),
            missing_semantics=(node.missing_semantics,),
        )
    if not isinstance(node, OperatorNode):
        raise FactorIrError("closed Factor IR accepts FeatureNode or OperatorNode only")
    spec = registry.resolve(node.operator_name, node.operator_semantic_version)
    if not spec.pit_safe:
        raise UnsafeFactorExpression(f"operator {spec.key} is not PIT-safe")
    if len(node.inputs) != spec.arity:
        raise FactorIrError(f"operator {spec.key} expects {spec.arity} inputs")
    parameters = spec.validate_parameters(node.parameters)
    children = tuple(validate_factor_node(value, registry) for value in node.inputs)
    observed_types = tuple(child.output_type for child in children)
    if observed_types != spec.input_types:
        raise FactorTypeError(
            f"operator {spec.key} expected {spec.input_types}, observed {observed_types}"
        )
    intrinsic_lookback = spec.resolved_lookback(parameters)
    intrinsic_lag = spec.resolved_lag(parameters)
    if intrinsic_lag < 0:
        raise UnsafeFactorExpression(f"operator {spec.key} resolves to future data")
    return FactorMetadata(
        output_type=spec.output_type,
        lookback=max(child.lookback for child in children)
        + intrinsic_lookback
        + intrinsic_lag,
        lag=max(child.lag for child in children) + intrinsic_lag,
        complexity=spec.complexity_weight + sum(child.complexity for child in children),
        input_features=tuple(
            sorted({name for child in children for name in child.input_features})
        ),
        operator_keys=tuple(
            sorted(
                {spec.key, *(key for child in children for key in child.operator_keys)}
            )
        ),
        missing_semantics=tuple(
            sorted(
                {spec.missing_semantics, *(value for child in children for value in child.missing_semantics)},
                key=lambda value: value.value,
            )
        ),
    )


@dataclass(frozen=True, slots=True)
class FactorDefinitionVersion:
    factor_definition_version_id: str
    logical_name: str
    operator_registry_version: str
    root: FactorNode
    metadata: FactorMetadata

    @classmethod
    def create(
        cls, logical_name: str, root: FactorNode, registry: OperatorRegistry
    ) -> FactorDefinitionVersion:
        if not logical_name or logical_name != logical_name.strip():
            raise FactorIrError("logical_name must be non-empty without edge whitespace")
        metadata = validate_factor_node(root, registry)
        semantics = {
            "logical_name": logical_name,
            "operator_registry_version": registry.registry_version,
            "root": root.to_wire(),
            "metadata": metadata.to_wire(),
        }
        return cls(
            factor_definition_version_id="fdv_sha256_" + canonical_sha256(semantics),
            logical_name=logical_name,
            operator_registry_version=registry.registry_version,
            root=root,
            metadata=metadata,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "factor_definition_version_id": self.factor_definition_version_id,
            "logical_name": self.logical_name,
            "operator_registry_version": self.operator_registry_version,
            "root": self.root.to_wire(),
            "metadata": self.metadata.to_wire(),
        }


class ExternalExpressionTranslator(Protocol):
    """Boundary only: external syntax must translate into closed V3 IR before use."""

    source_format: str
    translator_version: str

    def translate(self, payload: str) -> FactorNode: ...


def default_operator_registry() -> OperatorRegistry:
    series = ValueType.FLOAT_SERIES
    specs = (
        OperatorSpec(
            "ADD",
            "1.0.0",
            2,
            (series, series),
            series,
            0,
            0,
            MissingSemantics.PROPAGATE,
            True,
            True,
            BackendBinding.NATIVE_REFERENCE,
        ),
        OperatorSpec(
            "SUBTRACT",
            "1.0.0",
            2,
            (series, series),
            series,
            0,
            0,
            MissingSemantics.PROPAGATE,
            True,
            True,
            BackendBinding.NATIVE_REFERENCE,
        ),
        OperatorSpec(
            "MULTIPLY",
            "1.0.0",
            2,
            (series, series),
            series,
            0,
            0,
            MissingSemantics.PROPAGATE,
            True,
            True,
            BackendBinding.NATIVE_REFERENCE,
        ),
        OperatorSpec(
            "DIVIDE",
            "1.0.0",
            2,
            (series, series),
            series,
            0,
            0,
            MissingSemantics.DIVIDE_BY_ZERO_IS_MISSING,
            True,
            True,
            BackendBinding.NATIVE_REFERENCE,
        ),
        OperatorSpec(
            "LAG",
            "1.0.0",
            1,
            (series,),
            series,
            0,
            0,
            MissingSemantics.PROPAGATE,
            True,
            True,
            BackendBinding.NATIVE_REFERENCE,
            parameters=(ParameterSpec("periods", ParameterKind.INTEGER, 0, 250),),
            lag_parameter="periods",
        ),
        OperatorSpec(
            "SMA",
            "1.0.0",
            1,
            (series,),
            series,
            0,
            0,
            MissingSemantics.PROPAGATE,
            True,
            True,
            BackendBinding.TA_LIB,
            parameters=(ParameterSpec("timeperiod", ParameterKind.INTEGER, 2, 250),),
            lookback_parameter="timeperiod",
            complexity_weight=2,
        ),
        OperatorSpec(
            "LEAD",
            "1.0.0",
            1,
            (series,),
            series,
            0,
            -1,
            MissingSemantics.PROPAGATE,
            False,
            True,
            BackendBinding.NATIVE_REFERENCE,
        ),
    )
    return OperatorRegistry(specs)


__all__ = [
    "AvailabilitySemantics",
    "BackendBinding",
    "ExternalExpressionTranslator",
    "FactorDefinitionVersion",
    "FactorIrError",
    "FactorMetadata",
    "FactorNode",
    "FactorTypeError",
    "FeatureNode",
    "MissingSemantics",
    "OperatorNode",
    "OperatorRegistry",
    "OperatorSpec",
    "ParameterKind",
    "ParameterSpec",
    "UnknownOperator",
    "UnsafeFactorExpression",
    "ValueType",
    "default_operator_registry",
    "validate_factor_node",
]
