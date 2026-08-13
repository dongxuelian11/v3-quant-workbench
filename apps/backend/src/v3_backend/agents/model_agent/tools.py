from __future__ import annotations

from types import MappingProxyType

from v3_backend.agents.contracts import PermissionLevel
from v3_backend.agents.permissions import require_permission

from .contracts import ModelComparison, ModelEvidenceView, ModelResearchContext
from .service import compare_model_evidence


class ModelAgentToolError(ValueError):
    pass


class ModelAgentReadTools:
    """Q-local exact-object L0 tools; no execution or publication surface."""

    __slots__ = ("_contexts", "_evidence", "_allowed", "_called")

    def __init__(self, *, contexts: tuple[ModelResearchContext, ...], evidence: tuple[ModelEvidenceView, ...] = ()) -> None:
        self._contexts = MappingProxyType({value.dataset_version_id: value for value in contexts})
        self._evidence = MappingProxyType({value.model_version_id: value for value in evidence})
        if len(self._contexts) != len(contexts) or len(self._evidence) != len(evidence):
            raise ModelAgentToolError("duplicate exact object identities fail closed")
        self._allowed: frozenset[tuple[str, str]] = frozenset()
        self._called: list[tuple[str, str]] = []

    @property
    def visible_tool_names(self) -> tuple[str, ...]:
        return ("get_model_dataset_context", "get_model_evidence", "compare_model_evidence")

    @property
    def called(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._called)

    def begin(self, allowed: tuple[tuple[str, str], ...]) -> None:
        self._allowed = frozenset(allowed)
        self._called.clear()

    def _admit(self, name: str, object_id: str) -> None:
        require_permission(PermissionLevel.L0_READ, PermissionLevel.L0_READ)
        if (name, object_id) not in self._allowed:
            raise ModelAgentToolError("model requested evidence outside exact system-owned bindings")
        self._called.append((name, object_id))

    def get_model_dataset_context(self, dataset_version_id: str) -> ModelResearchContext:
        self._admit("get_model_dataset_context", dataset_version_id)
        try:
            return self._contexts[dataset_version_id]
        except KeyError as exc:
            raise ModelAgentToolError("exact DatasetVersion context is unavailable") from exc

    def get_model_evidence(self, model_version_id: str) -> ModelEvidenceView:
        self._admit("get_model_evidence", model_version_id)
        try:
            return self._evidence[model_version_id]
        except KeyError as exc:
            raise ModelAgentToolError("exact ModelVersion evidence is unavailable") from exc

    def compare_model_evidence(self, comparison_key: str) -> ModelComparison:
        self._admit("compare_model_evidence", comparison_key)
        parts = comparison_key.split("|", 4)
        if len(parts) != 5:
            raise ModelAgentToolError("comparison key must bind models, metric, split and direction")
        left_id, right_id, metric, split_role, direction = parts
        try:
            left, right = self._evidence[left_id], self._evidence[right_id]
        except KeyError as exc:
            raise ModelAgentToolError("comparison model evidence is unavailable") from exc
        return compare_model_evidence(left, right, objective_metric=metric, objective_split_role=split_role, objective_direction=direction)


__all__ = ["ModelAgentReadTools", "ModelAgentToolError"]
