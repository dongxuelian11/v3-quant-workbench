from __future__ import annotations

import heapq
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, TypeAlias

from v3_backend.contracts.common.truth_admission import (
    PRE_ALPHA_CEILING,
    TruthAdmissionState,
)
from v3_backend.provenance.canonical_hash import canonical_sha256


class StrategyIrError(ValueError):
    """Base error for closed Strategy IR compilation failures."""


class UnknownComponent(StrategyIrError):
    pass


class StrategyPortError(StrategyIrError):
    pass


class StrategyCycleError(StrategyIrError):
    pass


class ComponentRole(StrEnum):
    INPUT_REFERENCE = "INPUT_REFERENCE"
    CONDITION_GATE = "CONDITION_GATE"
    RANK_SELECT = "RANK_SELECT"
    COMBINE_PRIORITY = "COMBINE_PRIORITY"
    SIGNAL_OUTPUT = "SIGNAL_OUTPUT"
    INTENT_OUTPUT = "INTENT_OUTPUT"


class PortValueType(StrEnum):
    SCORE_MAP = "SCORE_MAP"
    BOOLEAN_MAP = "BOOLEAN_MAP"
    RANKED_INSTRUMENTS = "RANKED_INSTRUMENTS"
    SELECTION = "SELECTION"
    SIGNAL_ARTIFACT = "SIGNAL_ARTIFACT"
    SELECTION_ARTIFACT = "SELECTION_ARTIFACT"
    PORTFOLIO_INTENT = "PORTFOLIO_INTENT"


class PortCardinality(StrEnum):
    CROSS_SECTION = "CROSS_SECTION"
    ARTIFACT = "ARTIFACT"


class MissingSemantics(StrEnum):
    EXPLICIT = "EXPLICIT"
    EXCLUDE = "EXCLUDE"
    PROPAGATE = "PROPAGATE"
    FIRST_NON_MISSING = "FIRST_NON_MISSING"


class ParameterKind(StrEnum):
    BOOLEAN = "BOOLEAN"
    INTEGER = "INTEGER"
    DECIMAL_STRING = "DECIMAL_STRING"
    ENUM = "ENUM"


_NODE_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise StrategyIrError(f"{name} must be non-empty without edge whitespace")


def normalize_decimal_string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise StrategyIrError(f"{name} must be a decimal string")
    try:
        decimal = Decimal(value)
    except InvalidOperation as error:
        raise StrategyIrError(f"{name} must be a finite decimal string") from error
    if not decimal.is_finite():
        raise StrategyIrError(f"{name} must be a finite decimal string")
    if decimal == 0:
        return "0"
    normalized = format(decimal.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized


def _deep_freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _deep_thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class PortSpec:
    value_type: PortValueType
    cardinality: PortCardinality
    time_basis: str
    universe_basis: str
    missing_semantics: MissingSemantics

    def __post_init__(self) -> None:
        if not isinstance(self.value_type, PortValueType):
            raise TypeError("value_type must be PortValueType")
        if not isinstance(self.cardinality, PortCardinality):
            raise TypeError("cardinality must be PortCardinality")
        if not isinstance(self.missing_semantics, MissingSemantics):
            raise TypeError("missing_semantics must be MissingSemantics")
        _require_text(self.time_basis, "time_basis")
        _require_text(self.universe_basis, "universe_basis")

    def compatible_with(self, other: PortSpec) -> bool:
        return self == other

    def to_wire(self) -> dict[str, str]:
        return {
            "value_type": self.value_type.value,
            "cardinality": self.cardinality.value,
            "time_basis": self.time_basis,
            "universe_basis": self.universe_basis,
            "missing_semantics": self.missing_semantics.value,
        }


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    name: str
    kind: ParameterKind
    default: object
    minimum: int | None = None
    maximum: int | None = None
    allowed_values: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.name, "parameter name")
        if not isinstance(self.kind, ParameterKind):
            raise TypeError("kind must be ParameterKind")
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise StrategyIrError("parameter bounds are reversed")
        if self.kind is ParameterKind.ENUM and not self.allowed_values:
            raise StrategyIrError("enum parameters require allowed_values")
        self.validate(self.default)

    def validate(self, value: object) -> object:
        if self.kind is ParameterKind.BOOLEAN:
            if not isinstance(value, bool):
                raise StrategyIrError(f"parameter {self.name} must be boolean")
            return value
        if self.kind is ParameterKind.INTEGER:
            if not isinstance(value, int) or isinstance(value, bool):
                raise StrategyIrError(f"parameter {self.name} must be integer")
            if self.minimum is not None and value < self.minimum:
                raise StrategyIrError(f"parameter {self.name} is below its minimum")
            if self.maximum is not None and value > self.maximum:
                raise StrategyIrError(f"parameter {self.name} exceeds its maximum")
            return value
        if self.kind is ParameterKind.DECIMAL_STRING:
            return normalize_decimal_string(value, f"parameter {self.name}")
        if self.kind is ParameterKind.ENUM:
            if not isinstance(value, str) or value not in self.allowed_values:
                raise StrategyIrError(
                    f"parameter {self.name} must be one of {list(self.allowed_values)}"
                )
            return value
        raise StrategyIrError(f"unsupported parameter kind: {self.kind.value}")

    def to_wire(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "default": self.validate(self.default),
            "minimum": self.minimum,
            "maximum": self.maximum,
            "allowed_values": list(self.allowed_values),
        }


@dataclass(frozen=True, slots=True)
class ComponentDescriptor:
    component_type: str
    semantic_version: str
    role: ComponentRole
    input_ports: Mapping[str, PortSpec]
    output_ports: Mapping[str, PortSpec]
    parameters: tuple[ParameterSpec, ...]
    missing_semantics: MissingSemantics
    lookback: int
    lag: int
    deterministic: bool
    truth_requirements: tuple[str, ...]
    conflict_semantics: str
    capabilities: tuple[str, ...] = ("EXACT_BOUND_INPUT_ONLY",)

    def __post_init__(self) -> None:
        _require_text(self.component_type, "component_type")
        if not _SEMVER.fullmatch(self.semantic_version):
            raise StrategyIrError("component semantic_version must be exact semver")
        if not isinstance(self.role, ComponentRole):
            raise TypeError("role must be ComponentRole")
        if not isinstance(self.missing_semantics, MissingSemantics):
            raise TypeError("missing_semantics must be MissingSemantics")
        if self.lookback < 0 or self.lag < 0:
            raise StrategyIrError("lookback and lag must be non-negative")
        if not self.deterministic:
            raise StrategyIrError("V0 registry accepts deterministic components only")
        if not self.truth_requirements:
            raise StrategyIrError("truth requirements must be explicit")
        _require_text(self.conflict_semantics, "conflict_semantics")
        input_ports = dict(self.input_ports)
        output_ports = dict(self.output_ports)
        if not output_ports:
            raise StrategyIrError("component must declare at least one output port")
        for name in (*input_ports, *output_ports):
            _require_text(name, "port name")
        parameter_names = tuple(value.name for value in self.parameters)
        if len(parameter_names) != len(set(parameter_names)):
            raise StrategyIrError("component parameter names must be unique")
        forbidden = {"DB", "NETWORK", "BACKTEST", "ORDER", "FILL", "LIVE_ACCOUNT"}
        if forbidden.intersection(self.capabilities):
            raise StrategyIrError("forbidden strategy capability declared")
        object.__setattr__(self, "input_ports", MappingProxyType(input_ports))
        object.__setattr__(self, "output_ports", MappingProxyType(output_ports))

    @property
    def key(self) -> str:
        return f"{self.component_type}@{self.semantic_version}"

    def expand_parameters(self, values: Mapping[str, object]) -> dict[str, object]:
        specs = {value.name: value for value in self.parameters}
        unknown = set(values) - set(specs)
        if unknown:
            raise StrategyIrError(
                f"component {self.key} has unknown parameters {sorted(unknown)}"
            )
        return {
            name: spec.validate(values[name] if name in values else spec.default)
            for name, spec in sorted(specs.items())
        }

    def to_wire(self) -> dict[str, object]:
        return {
            "component_type": self.component_type,
            "semantic_version": self.semantic_version,
            "role": self.role.value,
            "input_ports": {
                name: self.input_ports[name].to_wire() for name in sorted(self.input_ports)
            },
            "output_ports": {
                name: self.output_ports[name].to_wire() for name in sorted(self.output_ports)
            },
            "parameters": [value.to_wire() for value in self.parameters],
            "missing_semantics": self.missing_semantics.value,
            "lookback": self.lookback,
            "lag": self.lag,
            "deterministic": self.deterministic,
            "truth_requirements": list(self.truth_requirements),
            "conflict_semantics": self.conflict_semantics,
            "capabilities": list(self.capabilities),
        }


class ComponentRegistry:
    semantic_api = "v3.strategy-components/1.0"

    def __init__(self, descriptors: tuple[ComponentDescriptor, ...]) -> None:
        if not descriptors:
            raise StrategyIrError("component registry cannot be empty")
        by_key = {value.key: value for value in descriptors}
        if len(by_key) != len(descriptors):
            raise StrategyIrError("component registry keys must be unique")
        self._descriptors = MappingProxyType(by_key)
        self._registry_version = "screg_sha256_" + canonical_sha256(
            [by_key[key].to_wire() for key in sorted(by_key)]
        )

    @property
    def registry_version(self) -> str:
        return self._registry_version

    def resolve(self, component_type: str, semantic_version: str) -> ComponentDescriptor:
        key = f"{component_type}@{semantic_version}"
        try:
            return self._descriptors[key]
        except KeyError as error:
            raise UnknownComponent(f"unknown closed-world component: {key}") from error

    def to_wire(self) -> dict[str, object]:
        return {
            "semantic_api": self.semantic_api,
            "registry_version": self.registry_version,
            "components": [
                self._descriptors[key].to_wire() for key in sorted(self._descriptors)
            ],
        }


@dataclass(frozen=True, slots=True)
class BindingSlot:
    binding_key: str
    artifact_kind: str
    port: PortSpec

    def __post_init__(self) -> None:
        _require_text(self.binding_key, "binding_key")
        _require_text(self.artifact_kind, "artifact_kind")
        if not isinstance(self.port, PortSpec):
            raise TypeError("binding slot port must be PortSpec")

    def to_wire(self) -> dict[str, object]:
        return {
            "binding_key": self.binding_key,
            "artifact_kind": self.artifact_kind,
            "port": self.port.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class NodeOutputRef:
    node_id: str
    port: str

    def __post_init__(self) -> None:
        if not _NODE_ID.fullmatch(self.node_id):
            raise StrategyIrError("node reference uses an invalid semantic node ID")
        _require_text(self.port, "node output port")

    def to_wire(self) -> dict[str, str]:
        return {"kind": "NODE", "node_id": self.node_id, "port": self.port}


@dataclass(frozen=True, slots=True)
class BindingInputRef:
    binding_key: str

    def __post_init__(self) -> None:
        _require_text(self.binding_key, "binding_key")

    def to_wire(self) -> dict[str, str]:
        return {"kind": "BINDING", "binding_key": self.binding_key}


StrategyInputRef: TypeAlias = NodeOutputRef | BindingInputRef


@dataclass(frozen=True, slots=True)
class StrategyNode:
    node_id: str
    component_type: str
    component_version: str
    inputs: Mapping[str, StrategyInputRef]
    parameters: Mapping[str, object]
    display_metadata: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not _NODE_ID.fullmatch(self.node_id):
            raise StrategyIrError("semantic node ID must be stable lowercase dotted text")
        _require_text(self.component_type, "component_type")
        if not _SEMVER.fullmatch(self.component_version):
            raise StrategyIrError("component_version must be exact semver")
        inputs = dict(self.inputs)
        if any(not isinstance(value, (NodeOutputRef, BindingInputRef)) for value in inputs.values()):
            raise TypeError("node inputs must be typed references")
        object.__setattr__(self, "inputs", MappingProxyType(inputs))
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        object.__setattr__(
            self,
            "display_metadata",
            MappingProxyType(dict(self.display_metadata or {})),
        )


@dataclass(frozen=True, slots=True)
class StrategySemantics:
    numeric_profile: str = "decimal128-v1"
    missing_policy: str = "EXPLICIT"
    stable_order: tuple[str, ...] = ("instrument_id",)
    conflict_policy: str = "EXPLICIT_COMPONENT_PRIORITY"

    def __post_init__(self) -> None:
        for name in ("numeric_profile", "missing_policy", "conflict_policy"):
            _require_text(getattr(self, name), name)
        if self.stable_order != ("instrument_id",):
            raise StrategyIrError("V0 stable order must be canonical instrument_id")

    def to_wire(self) -> dict[str, object]:
        return {
            "numeric_profile": self.numeric_profile,
            "missing_policy": self.missing_policy,
            "stable_order": list(self.stable_order),
            "conflict_policy": self.conflict_policy,
            "random": None,
        }


@dataclass(frozen=True, slots=True)
class StrategyIr:
    required_bindings: tuple[BindingSlot, ...]
    nodes: tuple[StrategyNode, ...]
    outputs: Mapping[str, NodeOutputRef]
    semantics: StrategySemantics = StrategySemantics()
    ir_schema: str = "v3.strategy-ir/1.0"
    projection_metadata: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not self.required_bindings:
            raise StrategyIrError("Strategy IR requires at least one exact binding slot")
        if not self.nodes:
            raise StrategyIrError("Strategy IR requires at least one component node")
        outputs = dict(self.outputs)
        allowed_outputs = {"signal", "selection", "portfolio_intent"}
        if not outputs or set(outputs) - allowed_outputs:
            raise StrategyIrError("Strategy IR outputs must be Signal/Selection/PortfolioIntent")
        if any(not isinstance(value, NodeOutputRef) for value in outputs.values()):
            raise TypeError("Strategy IR outputs must be NodeOutputRef")
        object.__setattr__(self, "outputs", MappingProxyType(outputs))
        object.__setattr__(
            self,
            "projection_metadata",
            MappingProxyType(dict(self.projection_metadata or {})),
        )


@dataclass(frozen=True, slots=True)
class StrategyDefinitionVersion:
    strategy_definition_version_id: str
    canonical_ir_sha256: str
    canonical_ir: Mapping[str, object]
    component_registry_version: str
    compiler_version: str
    runtime_profile_id: str
    custom_dependency_refs: tuple[str, ...]
    topological_order: tuple[str, ...]
    validation_state: str
    truth_admission: TruthAdmissionState

    def to_wire(self) -> dict[str, object]:
        return {
            "strategy_definition_version_id": self.strategy_definition_version_id,
            "canonical_ir_sha256": self.canonical_ir_sha256,
            "canonical_ir": _deep_thaw(self.canonical_ir),
            "component_registry_version": self.component_registry_version,
            "compiler_version": self.compiler_version,
            "runtime_profile_id": self.runtime_profile_id,
            "custom_dependency_refs": list(self.custom_dependency_refs),
            "topological_order": list(self.topological_order),
            "validation_state": self.validation_state,
            "truth_admission": self.truth_admission.to_wire(),
        }


class StrategyCompiler:
    compiler_version = "v3-strategy-compiler/1.0.0"
    runtime_profile_id = "v3-strategy-deterministic-batch/1.0.0"

    _OUTPUT_TYPES = {
        "signal": PortValueType.SIGNAL_ARTIFACT,
        "selection": PortValueType.SELECTION_ARTIFACT,
        "portfolio_intent": PortValueType.PORTFOLIO_INTENT,
    }

    def __init__(self, registry: ComponentRegistry) -> None:
        self.registry = registry

    def compile(
        self,
        ir: StrategyIr,
        *,
        custom_dependency_refs: tuple[str, ...] = (),
    ) -> StrategyDefinitionVersion:
        binding_by_key = {value.binding_key: value for value in ir.required_bindings}
        if len(binding_by_key) != len(ir.required_bindings):
            raise StrategyIrError("binding keys must be unique")
        node_by_id = {value.node_id: value for value in ir.nodes}
        if len(node_by_id) != len(ir.nodes):
            raise StrategyIrError("semantic node IDs must be unique")
        dependency_refs = tuple(sorted(custom_dependency_refs))
        if len(dependency_refs) != len(set(dependency_refs)):
            raise StrategyIrError("custom dependency references must be unique")
        descriptors = {
            node_id: self.registry.resolve(node.component_type, node.component_version)
            for node_id, node in node_by_id.items()
        }
        adjacency = {node_id: set() for node_id in node_by_id}
        indegree = {node_id: 0 for node_id in node_by_id}
        canonical_nodes: list[dict[str, object]] = []

        for node_id in sorted(node_by_id):
            node = node_by_id[node_id]
            descriptor = descriptors[node_id]
            if set(node.inputs) != set(descriptor.input_ports):
                raise StrategyPortError(
                    f"node {node_id} inputs must be exactly {sorted(descriptor.input_ports)}"
                )
            canonical_inputs: dict[str, object] = {}
            for input_name in sorted(node.inputs):
                expected_port = descriptor.input_ports[input_name]
                reference = node.inputs[input_name]
                if isinstance(reference, BindingInputRef):
                    try:
                        slot = binding_by_key[reference.binding_key]
                    except KeyError as error:
                        raise StrategyPortError(
                            f"node {node_id} has dangling binding {reference.binding_key}"
                        ) from error
                    if not slot.port.compatible_with(expected_port):
                        raise StrategyPortError(
                            f"node {node_id} binding port {input_name} is incompatible"
                        )
                else:
                    try:
                        source_descriptor = descriptors[reference.node_id]
                    except KeyError as error:
                        raise StrategyPortError(
                            f"node {node_id} has dangling source {reference.node_id}"
                        ) from error
                    try:
                        source_port = source_descriptor.output_ports[reference.port]
                    except KeyError as error:
                        raise StrategyPortError(
                            f"node {node_id} references unknown port {reference.port}"
                        ) from error
                    if not source_port.compatible_with(expected_port):
                        raise StrategyPortError(
                            f"node {node_id} input {input_name} has incompatible port type"
                        )
                    if node_id not in adjacency[reference.node_id]:
                        adjacency[reference.node_id].add(node_id)
                        indegree[node_id] += 1
                canonical_inputs[input_name] = reference.to_wire()
            canonical_nodes.append(
                {
                    "node_id": node_id,
                    "component_type": node.component_type,
                    "component_version": node.component_version,
                    "inputs": canonical_inputs,
                    "parameters": descriptor.expand_parameters(node.parameters),
                }
            )

        ready = [node_id for node_id, count in indegree.items() if count == 0]
        heapq.heapify(ready)
        topological: list[str] = []
        while ready:
            node_id = heapq.heappop(ready)
            topological.append(node_id)
            for target in sorted(adjacency[node_id]):
                indegree[target] -= 1
                if indegree[target] == 0:
                    heapq.heappush(ready, target)
        if len(topological) != len(node_by_id):
            raise StrategyCycleError("Strategy IR graph must be acyclic")

        canonical_outputs: dict[str, object] = {}
        if "portfolio_intent" in ir.outputs and "selection" not in ir.outputs:
            raise StrategyPortError(
                "PortfolioIntent requires an explicitly published SelectionArtifact"
            )
        for output_name in sorted(ir.outputs):
            reference = ir.outputs[output_name]
            try:
                descriptor = descriptors[reference.node_id]
                port = descriptor.output_ports[reference.port]
            except KeyError as error:
                raise StrategyPortError(f"declared output {output_name} is dangling") from error
            if port.value_type is not self._OUTPUT_TYPES[output_name]:
                raise StrategyPortError(
                    f"declared output {output_name} has incompatible artifact type"
                )
            canonical_outputs[output_name] = reference.to_wire()

        canonical_ir = {
            "ir_schema": ir.ir_schema,
            "semantic_api": self.registry.semantic_api,
            "required_bindings": [
                binding_by_key[key].to_wire() for key in sorted(binding_by_key)
            ],
            "semantics": ir.semantics.to_wire(),
            "nodes": canonical_nodes,
            "outputs": canonical_outputs,
        }
        canonical_ir_sha256 = canonical_sha256(canonical_ir)
        identity_payload = {
            "canonical_ir_sha256": canonical_ir_sha256,
            "canonical_ir": canonical_ir,
            "component_registry_version": self.registry.registry_version,
            "compiler_version": self.compiler_version,
            "runtime_profile_id": self.runtime_profile_id,
            "custom_dependency_refs": list(dependency_refs),
        }
        return StrategyDefinitionVersion(
            strategy_definition_version_id="sdv_sha256_"
            + canonical_sha256(identity_payload),
            canonical_ir_sha256=canonical_ir_sha256,
            canonical_ir=_deep_freeze(canonical_ir),  # type: ignore[arg-type]
            component_registry_version=self.registry.registry_version,
            compiler_version=self.compiler_version,
            runtime_profile_id=self.runtime_profile_id,
            custom_dependency_refs=dependency_refs,
            topological_order=tuple(topological),
            validation_state="PASSED_NOT_ADMITTED",
            truth_admission=PRE_ALPHA_CEILING,
        )


def _cross_section(value_type: PortValueType, missing: MissingSemantics) -> PortSpec:
    return PortSpec(
        value_type=value_type,
        cardinality=PortCardinality.CROSS_SECTION,
        time_basis="BOUND_DECISION_TIME",
        universe_basis="BOUND_UNIVERSE_MEMBERSHIP",
        missing_semantics=missing,
    )


def _artifact(value_type: PortValueType) -> PortSpec:
    return PortSpec(
        value_type=value_type,
        cardinality=PortCardinality.ARTIFACT,
        time_basis="BOUND_DECISION_TIME",
        universe_basis="BOUND_UNIVERSE_MEMBERSHIP",
        missing_semantics=MissingSemantics.EXPLICIT,
    )


def default_component_registry() -> ComponentRegistry:
    score = _cross_section(PortValueType.SCORE_MAP, MissingSemantics.EXPLICIT)
    eligible = _cross_section(PortValueType.BOOLEAN_MAP, MissingSemantics.EXCLUDE)
    ranked = _cross_section(PortValueType.RANKED_INSTRUMENTS, MissingSemantics.EXCLUDE)
    selection = _cross_section(PortValueType.SELECTION, MissingSemantics.EXCLUDE)
    common_truth = (
        "EXACT_INPUT_ARTIFACTS",
        "PIT_KNOWLEDGE_CUTOFF",
        "UPSTREAM_TRUTH_MEET",
    )
    return ComponentRegistry(
        (
            ComponentDescriptor(
                "v3.strategy.input.bound_scores",
                "1.0.0",
                ComponentRole.INPUT_REFERENCE,
                {"artifact": score},
                {"scores": score},
                (),
                MissingSemantics.EXPLICIT,
                0,
                0,
                True,
                common_truth,
                "NO_CONFLICT",
            ),
            ComponentDescriptor(
                "v3.strategy.condition.minimum",
                "1.0.0",
                ComponentRole.CONDITION_GATE,
                {"scores": score},
                {"eligible": eligible},
                (
                    ParameterSpec("threshold", ParameterKind.DECIMAL_STRING, "0"),
                    ParameterSpec("inclusive", ParameterKind.BOOLEAN, True),
                ),
                MissingSemantics.EXCLUDE,
                0,
                0,
                True,
                common_truth,
                "MISSING_IS_INELIGIBLE",
            ),
            ComponentDescriptor(
                "v3.strategy.combine.priority",
                "1.0.0",
                ComponentRole.COMBINE_PRIORITY,
                {"fallback": score, "primary": score},
                {"scores": score},
                (),
                MissingSemantics.FIRST_NON_MISSING,
                0,
                0,
                True,
                common_truth,
                "PRIMARY_THEN_FALLBACK_BY_NAMED_PORT",
            ),
            ComponentDescriptor(
                "v3.strategy.rank.score",
                "1.0.0",
                ComponentRole.RANK_SELECT,
                {"eligible": eligible, "scores": score},
                {"ranked": ranked},
                (
                    ParameterSpec("descending", ParameterKind.BOOLEAN, True),
                    ParameterSpec(
                        "missing_policy",
                        ParameterKind.ENUM,
                        "EXCLUDE",
                        allowed_values=("EXCLUDE",),
                    ),
                ),
                MissingSemantics.EXCLUDE,
                0,
                0,
                True,
                common_truth,
                "SCORE_THEN_CANONICAL_INSTRUMENT_ID",
            ),
            ComponentDescriptor(
                "v3.strategy.select.top_n",
                "1.0.0",
                ComponentRole.RANK_SELECT,
                {"ranked": ranked},
                {"selection": selection},
                (ParameterSpec("count", ParameterKind.INTEGER, 10, 1, 100000),),
                MissingSemantics.EXCLUDE,
                0,
                0,
                True,
                common_truth,
                "RANK_ORDER_THEN_CANONICAL_INSTRUMENT_ID",
            ),
            ComponentDescriptor(
                "v3.strategy.output.signal",
                "1.0.0",
                ComponentRole.SIGNAL_OUTPUT,
                {"scores": score},
                {"artifact": _artifact(PortValueType.SIGNAL_ARTIFACT)},
                (
                    ParameterSpec(
                        "signal_kind",
                        ParameterKind.ENUM,
                        "SCORE",
                        allowed_values=("SCORE", "DIRECTIONAL_SCORE"),
                    ),
                ),
                MissingSemantics.EXPLICIT,
                0,
                0,
                True,
                common_truth,
                "ONE_ROW_PER_BOUND_INSTRUMENT",
            ),
            ComponentDescriptor(
                "v3.strategy.output.selection",
                "1.0.0",
                ComponentRole.SIGNAL_OUTPUT,
                {"selection": selection},
                {"artifact": _artifact(PortValueType.SELECTION_ARTIFACT)},
                (),
                MissingSemantics.EXCLUDE,
                0,
                0,
                True,
                common_truth,
                "PRESERVE_STABLE_RANK_ORDER",
            ),
            ComponentDescriptor(
                "v3.strategy.output.portfolio_intent",
                "1.0.0",
                ComponentRole.INTENT_OUTPUT,
                {"scores": score, "selection": selection},
                {"artifact": _artifact(PortValueType.PORTFOLIO_INTENT)},
                (
                    ParameterSpec("gross_exposure", ParameterKind.DECIMAL_STRING, "1"),
                    ParameterSpec(
                        "exposure_mode",
                        ParameterKind.ENUM,
                        "ABSOLUTE_DESIRED_EXPOSURE",
                        allowed_values=(
                            "ABSOLUTE_DESIRED_EXPOSURE",
                            "RELATIVE_DESIRED_EXPOSURE",
                        ),
                    ),
                    ParameterSpec(
                        "cash_policy",
                        ParameterKind.ENUM,
                        "RESIDUAL",
                        allowed_values=("RESIDUAL", "UNCHANGED"),
                    ),
                    ParameterSpec(
                        "rebalance_intent",
                        ParameterKind.ENUM,
                        "AT_BOUND_DECISION_TIME",
                        allowed_values=("AT_BOUND_DECISION_TIME",),
                    ),
                ),
                MissingSemantics.EXCLUDE,
                0,
                0,
                True,
                common_truth,
                "SELECTION_MEMBERS_ONLY_EQUAL_PROPOSED_EXPOSURE",
            ),
        )
    )


__all__ = [
    "BindingInputRef",
    "BindingSlot",
    "ComponentDescriptor",
    "ComponentRegistry",
    "ComponentRole",
    "MissingSemantics",
    "NodeOutputRef",
    "ParameterKind",
    "ParameterSpec",
    "PortCardinality",
    "PortSpec",
    "PortValueType",
    "StrategyCompiler",
    "StrategyCycleError",
    "StrategyDefinitionVersion",
    "StrategyInputRef",
    "StrategyIr",
    "StrategyIrError",
    "StrategyNode",
    "StrategyPortError",
    "StrategySemantics",
    "UnknownComponent",
    "default_component_registry",
    "normalize_decimal_string",
]
