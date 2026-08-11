from __future__ import annotations

from typing import TypeVar

from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.models import Model

from v3_backend.agents.contracts import (
    AgentKind,
    AgentProvenance,
    FindingSeverity,
    PermissionLevel,
    ResearchPayload,
    StrictAgentModel,
    deterministic_json,
)
from v3_backend.agents.permissions import require_permission
from v3_backend.agents.pydantic_worker import (
    AgentOutputRejected,
    PYDANTIC_AI_VERIFIED_VERSION,
    PydanticAgentWorker,
)

from .contracts import (
    AgentEvidenceTrace,
    DataEvidenceFinding,
    DataEvidenceFindingKind,
    DataEvidenceFindingsPayload,
    DataEvidenceReviewDraft,
    DataFindingNarrativePayload,
    ResearchEvidenceDraft,
    ReviewerEvidenceFinding,
    ReviewerEvidenceFindingKind,
    ReviewerEvidenceFindingsPayload,
    ReviewerEvidenceReviewDraft,
    ReviewerFindingNarrativePayload,
)
from .tools import ResearchEvidenceToolComposition


_PayloadT = TypeVar("_PayloadT", bound=StrictAgentModel)
_ALL_EVIDENCE_TOOLS = (
    "get_snapshot_evidence",
    "get_dataset_evidence",
    "get_experiment_evidence",
    "get_reward_vector_evidence",
    "get_provenance_refs",
    "get_known_reviewer_evidence",
)

_INSTRUCTIONS = {
    AgentKind.RESEARCH: (
        "track-g-research-v1.0",
        "Call every exact V3 evidence tool requested in the structured input before returning the typed research payload. Produce only a non-canonical L1 draft. Never allocate IDs, execute, train, admit truth, or publish.",
    ),
    AgentKind.DATA: (
        "track-g-data-v1.0",
        "Call every exact V3 evidence tool requested in the structured input. Return typed data findings only. Unknown PIT or revision evidence is a warning; never claim PIT PASS from model text. Never mutate canonical truth.",
    ),
    AgentKind.REVIEWER: (
        "track-g-reviewer-v1.0",
        "Call every exact ExperimentRun, Attempt, RewardVector, and ReviewerEvidence tool requested in the structured input. Return typed reviewer findings only. A Reviewer Finding is never an Admission Decision.",
    ),
}


class ResearchEvidenceAgentWorker(PydanticAgentWorker):
    """Track G L1 adapter that forces exact L0 evidence consumption before drafting."""

    def __init__(
        self,
        *,
        model: Model,
        permission: object,
        model_name: str,
        provider_name: str,
        prompt_version: str,
        tool_composition: ResearchEvidenceToolComposition,
    ) -> None:
        if type(tool_composition) is not ResearchEvidenceToolComposition:
            raise TypeError("exact V3 ResearchEvidenceToolComposition is required")
        super().__init__(
            model=model,
            permission=permission,
            model_name=model_name,
            provider_name=provider_name,
            prompt_version=prompt_version,
            tool_registry=tool_composition.registry,
            requested_tool_names=_ALL_EVIDENCE_TOOLS,
        )
        self._evidence_composition = tool_composition
        self._track_g_model_name = model_name
        self._track_g_provider_name = provider_name
        self._track_g_prompt_version = prompt_version

    def _run_evidence_payload(
        self,
        *,
        kind: AgentKind,
        payload_type: type[_PayloadT],
        request_wire: dict[str, object],
        input_object_ids: tuple[str, ...],
        allowed_calls: tuple[tuple[str, str], ...],
    ) -> tuple[_PayloadT, AgentEvidenceTrace]:
        require_permission(self._permission, PermissionLevel.L1_DRAFT)
        instruction_version, instructions = _INSTRUCTIONS[kind]
        prompt = deterministic_json(request_wire)
        self._evidence_composition.begin_trace(allowed_calls)
        functions = [item.function for item in self._tool_bindings]
        agent: Agent[None, _PayloadT] = Agent(
            self._model,
            output_type=payload_type,
            instructions=instructions,
            tools=functions,
            retries={"output": 1},
        )
        try:
            result = agent.run_sync(prompt)
            payload = payload_type.model_validate(result.output)
            trace = self._evidence_composition.complete_trace(
                input_object_ids=input_object_ids,
                request_wire=request_wire,
            )
        except Exception as exc:
            self._evidence_composition.abort_trace()
            raise AgentOutputRejected(
                "structured Agent evidence integration failed closed"
            ) from exc
        return payload, trace

    def _provenance(
        self,
        *,
        kind: AgentKind,
        input_sha256: str,
    ) -> AgentProvenance:
        return AgentProvenance(
            agent_kind=kind,
            sdk_version=PYDANTIC_AI_VERIFIED_VERSION,
            model_name=self._track_g_model_name,
            provider_name=self._track_g_provider_name,
            prompt_version=self._track_g_prompt_version,
            instruction_version=_INSTRUCTIONS[kind][0],
            input_sha256=input_sha256,
        )

    def run_research_with_evidence(
        self,
        *,
        hypothesis: str,
        snapshot_id: str,
        dataset_version_id: str,
        experiment_run_id: str,
    ) -> ResearchEvidenceDraft:
        decision = require_permission(self._permission, PermissionLevel.L1_DRAFT)
        input_ids = (snapshot_id, dataset_version_id, experiment_run_id)
        request = {
            "task": "RESEARCH_EVIDENCE_DRAFT",
            "hypothesis": hypothesis,
            "exact_input_object_ids": list(input_ids),
            "required_tool_calls": [
                {"tool": "get_snapshot_evidence", "object_id": snapshot_id},
                {"tool": "get_dataset_evidence", "object_id": dataset_version_id},
                {"tool": "get_experiment_evidence", "object_id": experiment_run_id},
            ],
        }
        payload, trace = self._run_evidence_payload(
            kind=AgentKind.RESEARCH,
            payload_type=ResearchPayload,
            request_wire=request,
            input_object_ids=input_ids,
            allowed_calls=(
                ("get_snapshot_evidence", snapshot_id),
                ("get_dataset_evidence", dataset_version_id),
                ("get_experiment_evidence", experiment_run_id),
            ),
        )
        if trace.missing_evidence_ids:
            missing_questions = tuple(
                f"Required evidence is missing for exact object ID {value}."
                for value in trace.missing_evidence_ids
            )
            available = max(0, 64 - len(missing_questions))
            payload = payload.model_copy(
                update={
                    "open_questions": (
                        *payload.open_questions[:available],
                        *missing_questions,
                    )
                }
            )
        return ResearchEvidenceDraft(
            permission_decision=decision,
            provenance=self._provenance(
                kind=AgentKind.RESEARCH,
                input_sha256=trace.input_sha256,
            ),
            evidence_trace=trace,
            cited_evidence_object_ids=input_ids,
            payload=payload,
        )

    def run_data_review_with_evidence(
        self,
        *,
        snapshot_id: str,
        dataset_version_id: str,
    ) -> DataEvidenceReviewDraft:
        decision = require_permission(self._permission, PermissionLevel.L1_DRAFT)
        input_ids = (snapshot_id, dataset_version_id)
        request = {
            "task": "DATA_EVIDENCE_REVIEW",
            "exact_input_object_ids": list(input_ids),
            "required_tool_calls": [
                {"tool": "get_snapshot_evidence", "object_id": snapshot_id},
                {"tool": "get_dataset_evidence", "object_id": dataset_version_id},
            ],
        }
        narrative, trace = self._run_evidence_payload(
            kind=AgentKind.DATA,
            payload_type=DataFindingNarrativePayload,
            request_wire=request,
            input_object_ids=input_ids,
            allowed_calls=(
                ("get_snapshot_evidence", snapshot_id),
                ("get_dataset_evidence", dataset_version_id),
            ),
        )
        findings = [
            DataEvidenceFinding(
                **item.model_dump(mode="python"),
                evidence_object_ids=input_ids,
            )
            for item in narrative.findings
        ]
        for missing_id in trace.missing_evidence_ids:
            findings.append(
                DataEvidenceFinding(
                    kind=DataEvidenceFindingKind.MISSING_EVIDENCE,
                    severity=FindingSeverity.BLOCKING_EVIDENCE,
                    finding="Required data evidence is missing.",
                    reason=f"Exact object {missing_id} was not found by the trusted read adapter.",
                    recommended_next_check="Provide the exact upstream object before making a PIT or truth claim.",
                    evidence_object_ids=input_ids,
                )
            )
        findings = findings[:128]
        return DataEvidenceReviewDraft(
            permission_decision=decision,
            provenance=self._provenance(
                kind=AgentKind.DATA,
                input_sha256=trace.input_sha256,
            ),
            evidence_trace=trace,
            reviewed_input_sha256=trace.input_sha256,
            payload=DataEvidenceFindingsPayload(findings=tuple(findings)),
        )

    def run_reviewer_with_evidence(
        self,
        *,
        experiment_run_id: str,
        experiment_attempt_id: str,
        reward_vector_id: str,
        reviewer_evidence_id: str,
    ) -> ReviewerEvidenceReviewDraft:
        decision = require_permission(self._permission, PermissionLevel.L1_DRAFT)
        input_ids = (
            experiment_run_id,
            experiment_attempt_id,
            reward_vector_id,
            reviewer_evidence_id,
        )
        request = {
            "task": "REVIEWER_EVIDENCE_REVIEW",
            "exact_input_object_ids": list(input_ids),
            "required_tool_calls": [
                {"tool": "get_experiment_evidence", "object_id": experiment_run_id},
                {"tool": "get_reward_vector_evidence", "object_id": reward_vector_id},
                {"tool": "get_known_reviewer_evidence", "object_id": reviewer_evidence_id},
            ],
            "required_attempt_id_in_experiment_summary": experiment_attempt_id,
        }
        narrative, trace = self._run_evidence_payload(
            kind=AgentKind.REVIEWER,
            payload_type=ReviewerFindingNarrativePayload,
            request_wire=request,
            input_object_ids=input_ids,
            allowed_calls=(
                ("get_experiment_evidence", experiment_run_id),
                ("get_reward_vector_evidence", reward_vector_id),
                ("get_known_reviewer_evidence", reviewer_evidence_id),
            ),
        )
        experiment_call = next(
            item
            for item in trace.tool_calls
            if item.tool_name == "get_experiment_evidence"
        )
        attempt_is_cited = experiment_attempt_id in experiment_call.evidence_object_ids
        missing_ids = list(trace.missing_evidence_ids)
        if not attempt_is_cited:
            missing_ids.append(experiment_attempt_id)
        findings = [
            ReviewerEvidenceFinding(
                **item.model_dump(mode="python"),
                evidence_object_ids=input_ids,
            )
            for item in narrative.findings
        ]
        for missing_id in tuple(sorted(set(missing_ids))):
            findings.append(
                ReviewerEvidenceFinding(
                    kind=ReviewerEvidenceFindingKind.MISSING_EVIDENCE,
                    severity=FindingSeverity.BLOCKING_EVIDENCE,
                    finding="Required reviewer evidence is missing.",
                    reason=f"Exact object {missing_id} is absent from trusted Run/Attempt/Reward evidence.",
                    recommended_next_check="Supply the exact missing evidence before any admission review.",
                    evidence_object_ids=input_ids,
                )
            )
        findings = findings[:128]
        return ReviewerEvidenceReviewDraft(
            permission_decision=decision,
            provenance=self._provenance(
                kind=AgentKind.REVIEWER,
                input_sha256=trace.input_sha256,
            ),
            evidence_trace=trace,
            reviewed_evidence_sha256=trace.input_sha256,
            payload=ReviewerEvidenceFindingsPayload(findings=tuple(findings)),
        )

    @staticmethod
    def validate_model_payload(
        payload_type: type[_PayloadT], value: object
    ) -> _PayloadT:
        try:
            return payload_type.model_validate(value)
        except ValidationError as exc:
            raise AgentOutputRejected(
                "model output cannot control Track G system evidence fields"
            ) from exc


__all__ = ["ResearchEvidenceAgentWorker"]
