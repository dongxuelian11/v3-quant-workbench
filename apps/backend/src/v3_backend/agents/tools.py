from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Literal

from .contracts import PermissionDecision, PermissionLevel, ShortText, StrictAgentModel
from .permissions import decide_permission


class ToolEffect(str, Enum):
    READ = "READ"
    DRAFT = "DRAFT"
    EXECUTE = "EXECUTE"
    PUBLISH = "PUBLISH"
    CANONICAL_ID = "CANONICAL_ID"
    CANONICAL_TRUTH = "CANONICAL_TRUTH"
    DURABLE_TASK_AUTHORITY = "DURABLE_TASK_AUTHORITY"


class ToolDescriptor(StrictAgentModel):
    name: ShortText
    required_permission: PermissionLevel
    effect: ToolEffect
    control_plane_owned: Literal[True] = True


class ToolExposure(StrictAgentModel):
    permission_decision: PermissionDecision
    visible_tools: tuple[ToolDescriptor, ...]


DEFAULT_TOOL_CATALOG = (
    ToolDescriptor(name="read_structured_input", required_permission=PermissionLevel.L0_READ, effect=ToolEffect.READ),
    ToolDescriptor(name="draft_research_spec", required_permission=PermissionLevel.L1_DRAFT, effect=ToolEffect.DRAFT),
    ToolDescriptor(name="draft_data_findings", required_permission=PermissionLevel.L1_DRAFT, effect=ToolEffect.DRAFT),
    ToolDescriptor(name="draft_reviewer_findings", required_permission=PermissionLevel.L1_DRAFT, effect=ToolEffect.DRAFT),
    ToolDescriptor(name="execute_task", required_permission=PermissionLevel.L2_EXECUTE, effect=ToolEffect.EXECUTE),
    ToolDescriptor(name="publish_artifact", required_permission=PermissionLevel.L3_PUBLISH, effect=ToolEffect.PUBLISH),
    ToolDescriptor(name="allocate_canonical_id", required_permission=PermissionLevel.L3_PUBLISH, effect=ToolEffect.CANONICAL_ID),
    ToolDescriptor(name="promote_canonical_truth", required_permission=PermissionLevel.L3_PUBLISH, effect=ToolEffect.CANONICAL_TRUTH),
    ToolDescriptor(name="own_durable_task", required_permission=PermissionLevel.L2_EXECUTE, effect=ToolEffect.DURABLE_TASK_AUTHORITY),
)


_SAFE_EFFECTS = frozenset({ToolEffect.READ, ToolEffect.DRAFT})


def filter_tools(
    requested_permission: object,
    catalog: tuple[ToolDescriptor, ...] = DEFAULT_TOOL_CATALOG,
) -> ToolExposure:
    decision = decide_permission(requested_permission)
    if not decision.allowed:
        return ToolExposure(permission_decision=decision, visible_tools=())
    permitted_levels = {PermissionLevel.L0_READ}
    if decision.normalized is PermissionLevel.L1_DRAFT:
        permitted_levels.add(PermissionLevel.L1_DRAFT)
    visible = tuple(
        tool
        for tool in catalog
        if tool.effect in _SAFE_EFFECTS and tool.required_permission in permitted_levels
    )
    return ToolExposure(permission_decision=decision, visible_tools=visible)


@dataclass(frozen=True)
class ToolBinding:
    descriptor: ToolDescriptor
    function: Callable[..., Any]

    def __post_init__(self) -> None:
        if not callable(self.function):
            raise TypeError("tool binding function must be callable")


class UntrustedToolBindingError(ValueError):
    """A tool name, descriptor, or callable is outside the V3 trusted registry."""


class TrustedToolBindings:
    """Immutable V3-owned mapping from registered names to canonical bindings."""

    __slots__ = ("_bindings_by_name",)

    def __init__(self, registrations: tuple[ToolBinding, ...]) -> None:
        catalog_by_name = {descriptor.name: descriptor for descriptor in DEFAULT_TOOL_CATALOG}
        bindings_by_name: dict[str, ToolBinding] = {}
        for registration in registrations:
            name = registration.descriptor.name
            if name in bindings_by_name:
                raise UntrustedToolBindingError("duplicate tool binding names fail closed")
            catalog_descriptor = catalog_by_name.get(name)
            if catalog_descriptor is None or registration.descriptor != catalog_descriptor:
                raise UntrustedToolBindingError(f"tool descriptor is not in the V3 catalog: {name}")
            bindings_by_name[name] = ToolBinding(catalog_descriptor, registration.function)
        self._bindings_by_name = MappingProxyType(bindings_by_name)

    @property
    def registered_names(self) -> tuple[str, ...]:
        return tuple(self._bindings_by_name)

    def resolve(self, requested_names: tuple[str, ...]) -> tuple[ToolBinding, ...]:
        if any(not isinstance(name, str) or not name for name in requested_names):
            raise UntrustedToolBindingError("tool requests must use non-empty registered names")
        if len(requested_names) != len(set(requested_names)):
            raise UntrustedToolBindingError("duplicate tool binding names fail closed")
        resolved: list[ToolBinding] = []
        for name in requested_names:
            binding = self._bindings_by_name.get(name)
            if binding is None:
                raise UntrustedToolBindingError(f"tool name is not registered: {name}")
            resolved.append(binding)
        return tuple(resolved)

    def require_canonical(self, binding: ToolBinding) -> ToolBinding:
        canonical = self._bindings_by_name.get(binding.descriptor.name)
        if canonical is None:
            raise UntrustedToolBindingError(
                f"tool binding is not registered: {binding.descriptor.name}"
            )
        if binding is not canonical or binding.function is not canonical.function:
            raise UntrustedToolBindingError(
                f"tool binding is not the canonical V3 registration: {binding.descriptor.name}"
            )
        return canonical


def filter_tool_bindings(
    requested_permission: object,
    bindings: tuple[ToolBinding, ...],
    *,
    registry: TrustedToolBindings,
) -> tuple[ToolBinding, ...]:
    if type(registry) is not TrustedToolBindings:
        raise UntrustedToolBindingError("an exact V3 TrustedToolBindings authority is required")
    names = tuple(item.descriptor.name for item in bindings)
    if len(names) != len(set(names)):
        raise UntrustedToolBindingError("duplicate tool binding names fail closed")
    canonical_bindings = tuple(registry.require_canonical(item) for item in bindings)
    exposure = filter_tools(
        requested_permission,
        tuple(item.descriptor for item in canonical_bindings),
    )
    return tuple(
        item for item in canonical_bindings if item.descriptor in exposure.visible_tools
    )
