from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Mapping, TypeVar

from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.models import Model

from .contracts import (
    AgentKind,
    AgentProvenance,
    DataFindingsPayload,
    DataReviewDraft,
    PermissionLevel,
    ProposalBoundary,
    ResearchDraft,
    ResearchPayload,
    ReviewerFindingsPayload,
    ReviewerReviewDraft,
    StrictAgentModel,
    deterministic_json,
)
from .permissions import require_permission
from .tools import TrustedToolBindings, UntrustedToolBindingError, filter_tool_bindings


PYDANTIC_AI_VERIFIED_VERSION = "2.27.0"
_PayloadT = TypeVar("_PayloadT", bound=StrictAgentModel)


class AgentOutputRejected(RuntimeError):
    """PydanticAI failed to return the exact Track D typed payload."""


_INSTRUCTIONS = {
    AgentKind.RESEARCH: (
        "track-d-research-v0.1",
        "Return only a typed, non-executable research intent payload. Do not allocate IDs, execute workers, admit truth, or publish.",
    ),
    AgentKind.DATA: (
        "track-d-data-v0.1",
        "Review only the supplied structured evidence and return typed data-quality findings. Findings are evidence, never admission decisions.",
    ),
    AgentKind.REVIEWER: (
        "track-d-reviewer-v0.1",
        "Review only the supplied proposal evidence and return typed research-risk findings. Do not execute, admit, or publish.",
    ),
}


class PydanticAgentWorker:
    """Bounded PydanticAI adapter; V3 retains permission and lifecycle authority."""

    def __init__(
        self,
        *,
        model: Model,
        permission: object,
        model_name: str,
        provider_name: str,
        prompt_version: str,
        tool_registry: TrustedToolBindings | None = None,
        requested_tool_names: tuple[str, ...] = (),
    ) -> None:
        try:
            installed = version("pydantic-ai-slim")
        except PackageNotFoundError as exc:
            raise RuntimeError("pydantic-ai-slim is required") from exc
        if installed != PYDANTIC_AI_VERIFIED_VERSION:
            raise RuntimeError(
                f"pydantic-ai-slim version mismatch: expected {PYDANTIC_AI_VERIFIED_VERSION}, got {installed}"
            )
        self._model = model
        self._permission = permission
        self._model_name = model_name
        self._provider_name = provider_name
        self._prompt_version = prompt_version
        if tool_registry is None:
            if requested_tool_names:
                raise UntrustedToolBindingError("tool requests require a V3 trusted registry")
            self._tool_bindings = ()
        else:
            if type(tool_registry) is not TrustedToolBindings:
                raise UntrustedToolBindingError(
                    "an exact V3 TrustedToolBindings authority is required"
                )
            resolved_bindings = tool_registry.resolve(requested_tool_names)
            self._tool_bindings = filter_tool_bindings(
                permission,
                resolved_bindings,
                registry=tool_registry,
            )

    @property
    def visible_tool_names(self) -> tuple[str, ...]:
        return tuple(item.descriptor.name for item in self._tool_bindings)

    def inspect_structured_input(self, value: Mapping[str, Any]) -> str:
        require_permission(self._permission, PermissionLevel.L0_READ)
        if not isinstance(value, Mapping):
            raise AgentOutputRejected("structured input must be a mapping")
        try:
            return deterministic_json(dict(value))
        except (TypeError, ValueError) as exc:
            raise AgentOutputRejected("structured input is not deterministic JSON") from exc

    def _provenance(self, kind: AgentKind, instruction_version: str, prompt: str) -> AgentProvenance:
        return AgentProvenance(
            agent_kind=kind,
            sdk_version=PYDANTIC_AI_VERIFIED_VERSION,
            model_name=self._model_name,
            provider_name=self._provider_name,
            prompt_version=self._prompt_version,
            instruction_version=instruction_version,
            input_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        )

    def _run_payload(self, kind: AgentKind, payload_type: type[_PayloadT], prompt: str) -> _PayloadT:
        require_permission(self._permission, PermissionLevel.L1_DRAFT)
        instruction_version, instructions = _INSTRUCTIONS[kind]
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
            return payload_type.model_validate(result.output)
        except Exception as exc:
            raise AgentOutputRejected("structured Agent output failed closed") from exc

    @staticmethod
    def validate_payload(payload_type: type[_PayloadT], value: object) -> _PayloadT:
        try:
            return payload_type.model_validate(value)
        except ValidationError as exc:
            raise AgentOutputRejected("structured Agent output failed closed") from exc

    def run_research(self, hypothesis: str) -> ResearchDraft:
        decision = require_permission(self._permission, PermissionLevel.L1_DRAFT)
        payload = self._run_payload(AgentKind.RESEARCH, ResearchPayload, hypothesis)
        instruction_version = _INSTRUCTIONS[AgentKind.RESEARCH][0]
        return ResearchDraft(
            permission_decision=decision,
            provenance=self._provenance(AgentKind.RESEARCH, instruction_version, hypothesis),
            payload=payload,
        )

    def run_data_review(self, structured_input: Mapping[str, Any]) -> DataReviewDraft:
        decision = require_permission(self._permission, PermissionLevel.L1_DRAFT)
        prompt = self.inspect_structured_input(structured_input)
        payload = self._run_payload(AgentKind.DATA, DataFindingsPayload, prompt)
        instruction_version = _INSTRUCTIONS[AgentKind.DATA][0]
        return DataReviewDraft(
            permission_decision=decision,
            provenance=self._provenance(AgentKind.DATA, instruction_version, prompt),
            reviewed_input_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            payload=payload,
        )

    def run_reviewer(self, proposal: ProposalBoundary) -> ReviewerReviewDraft:
        decision = require_permission(self._permission, PermissionLevel.L1_DRAFT)
        if not isinstance(proposal, ProposalBoundary):
            raise AgentOutputRejected("reviewer input must be a non-canonical proposal")
        prompt = proposal.to_deterministic_json()
        payload = self._run_payload(AgentKind.REVIEWER, ReviewerFindingsPayload, prompt)
        instruction_version = _INSTRUCTIONS[AgentKind.REVIEWER][0]
        return ReviewerReviewDraft(
            permission_decision=decision,
            provenance=self._provenance(AgentKind.REVIEWER, instruction_version, prompt),
            reviewed_proposal_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            payload=payload,
        )
