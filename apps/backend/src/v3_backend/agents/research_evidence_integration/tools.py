from __future__ import annotations

import hashlib
from types import MappingProxyType
from typing import Any

from v3_backend.agents.contracts import StrictAgentModel, deterministic_json
from v3_backend.agents.tools import (
    RESEARCH_EVIDENCE_READ_TOOL_CATALOG,
    ToolBinding,
    ToolDescriptor,
    TrustedToolBindings,
    UntrustedToolBindingError,
)

from .adapter import ResearchEvidenceReadAdapter
from .contracts import (
    AgentEvidenceTrace,
    DatasetLookup,
    EvidenceToolCall,
    ExperimentLookup,
    MissingEvidence,
    ProvenanceLookup,
    ReviewerEvidenceLookup,
    RewardVectorLookup,
    SnapshotLookup,
)


class EvidenceToolRequestRejected(UntrustedToolBindingError):
    """The model requested evidence outside the system-owned exact input set."""


def _descriptor(name: str) -> ToolDescriptor:
    return next(
        item for item in RESEARCH_EVIDENCE_READ_TOOL_CATALOG if item.name == name
    )


def _collect_object_ids(value: Any) -> tuple[str, ...]:
    found: set[str] = set()

    def visit(item: Any, key: str | None = None) -> None:
        if isinstance(item, dict):
            for child_key, child_value in item.items():
                visit(child_value, str(child_key))
            return
        if isinstance(item, (list, tuple)):
            for child in item:
                visit(child, key)
            return
        if isinstance(item, str) and key is not None:
            if key.endswith("_id") or key.endswith("_ids") or key == "provenance_refs":
                found.add(item)

    visit(value)
    return tuple(sorted(found))[:128]


class ResearchEvidenceToolComposition:
    """V3-owned registry plus bounded receipts for exact read-only evidence calls."""

    __slots__ = (
        "_adapter",
        "_registry",
        "_allowed_calls",
        "_recorded",
        "_active",
    )

    def __init__(self, adapter: ResearchEvidenceReadAdapter) -> None:
        if type(adapter) is not ResearchEvidenceReadAdapter:
            raise TypeError("exact V3 ResearchEvidenceReadAdapter is required")
        self._adapter = adapter
        self._allowed_calls: MappingProxyType[str, frozenset[str]] = MappingProxyType({})
        self._recorded: list[EvidenceToolCall] = []
        self._active = False

        def get_snapshot_evidence(snapshot_id: str) -> SnapshotLookup:
            """Return bounded metadata for one exact V3 Snapshot identity."""

            return self._invoke(
                "get_snapshot_evidence", snapshot_id, self._adapter.get_snapshot
            )

        def get_dataset_evidence(dataset_version_id: str) -> DatasetLookup:
            """Return bounded split and factor-membership metadata for one DatasetVersion."""

            return self._invoke(
                "get_dataset_evidence",
                dataset_version_id,
                self._adapter.get_dataset,
            )

        def get_experiment_evidence(experiment_run_id: str) -> ExperimentLookup:
            """Return one exact ExperimentRun and its bounded Attempt summaries."""

            return self._invoke(
                "get_experiment_evidence",
                experiment_run_id,
                self._adapter.get_experiment,
            )

        def get_reward_vector_evidence(reward_vector_id: str) -> RewardVectorLookup:
            """Return one exact RewardVector and its evaluation evidence."""

            return self._invoke(
                "get_reward_vector_evidence",
                reward_vector_id,
                self._adapter.get_reward_vector,
            )

        def get_provenance_refs(object_id: str) -> ProvenanceLookup:
            """Return bounded provenance references for one exact V3 object identity."""

            return self._invoke(
                "get_provenance_refs", object_id, self._adapter.get_provenance
            )

        def get_known_reviewer_evidence(
            reviewer_evidence_id: str,
        ) -> ReviewerEvidenceLookup:
            """Return bounded known ReviewerEvidence without making an admission decision."""

            return self._invoke(
                "get_known_reviewer_evidence",
                reviewer_evidence_id,
                self._adapter.get_reviewer_evidence,
            )

        functions = {
            "get_snapshot_evidence": get_snapshot_evidence,
            "get_dataset_evidence": get_dataset_evidence,
            "get_experiment_evidence": get_experiment_evidence,
            "get_reward_vector_evidence": get_reward_vector_evidence,
            "get_provenance_refs": get_provenance_refs,
            "get_known_reviewer_evidence": get_known_reviewer_evidence,
        }
        self._registry = TrustedToolBindings(
            tuple(
                ToolBinding(_descriptor(name), functions[name])
                for name in (
                    "get_snapshot_evidence",
                    "get_dataset_evidence",
                    "get_experiment_evidence",
                    "get_reward_vector_evidence",
                    "get_provenance_refs",
                    "get_known_reviewer_evidence",
                )
            )
        )

    @property
    def registry(self) -> TrustedToolBindings:
        return self._registry

    def begin_trace(self, allowed_calls: tuple[tuple[str, str], ...]) -> None:
        if self._active:
            raise RuntimeError("an evidence trace is already active")
        permitted_names = set(self._registry.registered_names)
        grouped: dict[str, set[str]] = {}
        for name, object_id in allowed_calls:
            if name not in permitted_names or not object_id:
                raise EvidenceToolRequestRejected("invalid exact evidence call boundary")
            grouped.setdefault(name, set()).add(object_id)
        if len(allowed_calls) != sum(len(values) for values in grouped.values()):
            raise EvidenceToolRequestRejected("duplicate exact evidence calls fail closed")
        self._allowed_calls = MappingProxyType(
            {name: frozenset(values) for name, values in grouped.items()}
        )
        self._recorded = []
        self._active = True

    def abort_trace(self) -> None:
        self._allowed_calls = MappingProxyType({})
        self._recorded = []
        self._active = False

    def _invoke(
        self,
        tool_name: str,
        object_id: str,
        function: Any,
    ) -> Any:
        if not self._active:
            raise EvidenceToolRequestRejected("evidence tools require an active V3 trace")
        if object_id not in self._allowed_calls.get(tool_name, frozenset()):
            raise EvidenceToolRequestRejected(
                f"evidence object is outside the exact system input set: {tool_name}"
            )
        if any(
            item.tool_name == tool_name and item.requested_object_id == object_id
            for item in self._recorded
        ):
            raise EvidenceToolRequestRejected("duplicate evidence calls fail closed")
        result = function(object_id)
        if not isinstance(result, StrictAgentModel):
            raise TypeError("trusted evidence tools must return typed V3 models")
        wire = result.model_dump(mode="json")
        response_sha256 = hashlib.sha256(
            deterministic_json(wire).encode("utf-8")
        ).hexdigest()
        evidence_ids = _collect_object_ids(wire)
        if object_id not in evidence_ids:
            evidence_ids = tuple(sorted(set((object_id, *evidence_ids))))[:128]
        provenance = wire.get("provenance_refs", ())
        provenance_refs = tuple(sorted(set(provenance)))[:128]
        self._recorded.append(
            EvidenceToolCall(
                tool_name=tool_name,
                requested_object_id=object_id,
                lookup_status="MISSING" if isinstance(result, MissingEvidence) else "FOUND",
                response_sha256=response_sha256,
                evidence_object_ids=evidence_ids,
                provenance_refs=provenance_refs,
            )
        )
        return result

    def complete_trace(
        self,
        *,
        input_object_ids: tuple[str, ...],
        request_wire: dict[str, object],
    ) -> AgentEvidenceTrace:
        if not self._active:
            raise RuntimeError("no active evidence trace")
        expected = {
            (name, object_id)
            for name, object_ids in self._allowed_calls.items()
            for object_id in object_ids
        }
        observed = {
            (item.tool_name, item.requested_object_id) for item in self._recorded
        }
        if observed != expected:
            self.abort_trace()
            raise EvidenceToolRequestRejected(
                "Agent did not consume every exact required evidence input"
            )
        calls = tuple(
            sorted(
                self._recorded,
                key=lambda item: (item.tool_name, item.requested_object_id),
            )
        )
        input_ids = tuple(input_object_ids)
        evidence_refs = tuple(
            sorted(
                {
                    ref
                    for item in calls
                    for ref in (*item.evidence_object_ids, *item.provenance_refs)
                }
            )
        )[:256]
        evidenced_input_ids = {
            object_id for item in calls for object_id in item.evidence_object_ids
        }
        missing = tuple(
            sorted(
                {
                    *(
                        item.requested_object_id
                        for item in calls
                        if item.lookup_status == "MISSING"
                    ),
                    *(value for value in input_ids if value not in evidenced_input_ids),
                }
            )
        )
        input_sha256 = hashlib.sha256(
            deterministic_json(
                {
                    "request": request_wire,
                    "tool_calls": [item.model_dump(mode="json") for item in calls],
                }
            ).encode("utf-8")
        ).hexdigest()
        trace = AgentEvidenceTrace(
            input_object_ids=input_ids,
            input_sha256=input_sha256,
            tool_calls=calls,
            evidence_refs=evidence_refs,
            missing_evidence_ids=missing,
        )
        self.abort_trace()
        return trace


__all__ = [
    "EvidenceToolRequestRejected",
    "ResearchEvidenceToolComposition",
]
