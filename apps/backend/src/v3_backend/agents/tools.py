from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
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


def filter_tool_bindings(
    requested_permission: object,
    bindings: tuple[ToolBinding, ...],
) -> tuple[ToolBinding, ...]:
    names = tuple(item.descriptor.name for item in bindings)
    if len(names) != len(set(names)):
        raise ValueError("duplicate tool binding names fail closed")
    exposure = filter_tools(requested_permission)
    return tuple(item for item in bindings if item.descriptor in exposure.visible_tools)
