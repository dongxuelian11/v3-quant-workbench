from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, version

from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.models import Model

from v3_backend.agents.contracts import AgentKind, AgentProvenance, PermissionLevel
from v3_backend.agents.permissions import require_permission
from v3_backend.agents.pydantic_worker import PYDANTIC_AI_VERIFIED_VERSION

from .contracts import FactorDraftPayload, FactorDraftResponse


class FactorStructuredOutputRejected(RuntimeError):
    pass


class FactorDraftWorker:
    """Typed PydanticAI L1 adapter. It has no callable tools and cannot apply a preview."""

    instruction_version = "round5-p-factor-draft/1.0.0"
    instructions = (
        "Return only a typed NON_CANONICAL factor draft. Prefer TDX when the intent is representable. "
        "Never execute, allocate canonical IDs, claim evaluation performance, review, promote, publish, "
        "write Python, call eval, or silently repair unsupported semantics."
    )

    def __init__(
        self,
        *,
        model: Model,
        permission: object,
        model_name: str,
        provider_name: str,
        prompt_version: str,
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

    @staticmethod
    def validate_payload(value: object) -> FactorDraftPayload:
        try:
            return FactorDraftPayload.model_validate(value)
        except ValidationError as exc:
            raise FactorStructuredOutputRejected("structured Factor Agent output failed closed") from exc

    def draft(self, natural_language_intent: str) -> FactorDraftResponse:
        decision = require_permission(self._permission, PermissionLevel.L1_DRAFT)
        if not natural_language_intent or natural_language_intent != natural_language_intent.strip():
            raise FactorStructuredOutputRejected("natural-language intent is required")
        agent: Agent[None, FactorDraftPayload] = Agent(
            self._model,
            output_type=FactorDraftPayload,
            instructions=self.instructions,
            tools=(),
            retries={"output": 1},
        )
        try:
            result = agent.run_sync(natural_language_intent)
            payload = FactorDraftPayload.model_validate(result.output)
        except Exception as exc:
            raise FactorStructuredOutputRejected("structured Factor Agent output failed closed") from exc
        provenance = AgentProvenance(
            agent_kind=AgentKind.RESEARCH,
            sdk_version=PYDANTIC_AI_VERIFIED_VERSION,
            model_name=self._model_name,
            provider_name=self._provider_name,
            prompt_version=self._prompt_version,
            instruction_version=self.instruction_version,
            input_sha256=hashlib.sha256(natural_language_intent.encode("utf-8")).hexdigest(),
        )
        return FactorDraftResponse(permission_decision=decision, provenance=provenance, payload=payload)
