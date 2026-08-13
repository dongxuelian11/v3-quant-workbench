from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, version

from pydantic_ai import Agent
from pydantic_ai.models import Model

from v3_backend.agents.contracts import AgentKind, AgentProvenance, PermissionLevel, deterministic_json
from v3_backend.agents.permissions import require_permission
from v3_backend.agents.pydantic_worker import AgentOutputRejected, PYDANTIC_AI_VERIFIED_VERSION
from v3_backend.domain.models import TrainingSpecVersion

from .contracts import ModelProposalNarrative, ModelResearchContext, ModelResearchProposal
from .service import build_model_research_proposal, draft_model_train
from .tools import ModelAgentReadTools


_INSTRUCTION_VERSION = "round5-q-model-agent/1.0"
_INSTRUCTIONS = (
    "Call get_model_dataset_context for the exact DatasetVersion in the request. "
    "Return only typed research rationale and explicitly labeled next-action proposals. "
    "Do not execute training or prediction, allocate a ModelVersion, claim missing metrics, "
    "invent feature importance/SHAP/IC/attribution/robustness/causality, admit truth, or publish."
)


class ModelAgentWorker:
    """PydanticAI narrative adapter around system-owned deterministic Q drafts."""

    def __init__(self, *, model: Model, permission: object, model_name: str, provider_name: str, prompt_version: str, read_tools: ModelAgentReadTools) -> None:
        try:
            installed = version("pydantic-ai-slim")
        except PackageNotFoundError as exc:
            raise RuntimeError("pydantic-ai-slim is required") from exc
        if installed != PYDANTIC_AI_VERIFIED_VERSION:
            raise RuntimeError(f"pydantic-ai-slim version mismatch: expected {PYDANTIC_AI_VERIFIED_VERSION}, got {installed}")
        if type(read_tools) is not ModelAgentReadTools:
            raise TypeError("exact Q ModelAgentReadTools is required")
        self._model = model
        self._permission = permission
        self._model_name = model_name
        self._provider_name = provider_name
        self._prompt_version = prompt_version
        self._read_tools = read_tools

    @property
    def visible_tool_names(self) -> tuple[str, ...]:
        return self._read_tools.visible_tool_names

    def run_train_proposal(self, *, research_goal: str, context: ModelResearchContext, spec: TrainingSpecVersion, requested_metrics: tuple[str, ...]) -> ModelResearchProposal:
        decision = require_permission(self._permission, PermissionLevel.L1_DRAFT)
        request = {
            "task": "MODEL_TRAIN_PROPOSAL",
            "research_goal": research_goal,
            "dataset_version_id": context.dataset_version_id,
            "training_spec_version_id": spec.training_spec_version_id,
            "requested_metrics": list(sorted(requested_metrics)),
            "required_tool_call": "get_model_dataset_context",
        }
        prompt = deterministic_json(request)
        self._read_tools.begin((("get_model_dataset_context", context.dataset_version_id),))
        agent: Agent[None, ModelProposalNarrative] = Agent(
            self._model,
            output_type=ModelProposalNarrative,
            instructions=_INSTRUCTIONS,
            tools=[self._read_tools.get_model_dataset_context],
            retries={"output": 1},
        )
        try:
            result = agent.run_sync(prompt)
            narrative = ModelProposalNarrative.model_validate(result.output)
            if ("get_model_dataset_context", context.dataset_version_id) not in self._read_tools.called:
                raise AgentOutputRejected("Model Agent must consume exact DatasetVersion evidence")
        except Exception as exc:
            raise AgentOutputRejected("structured Model Agent proposal failed closed") from exc
        provenance = AgentProvenance(
            agent_kind=AgentKind.RESEARCH,
            sdk_version=PYDANTIC_AI_VERIFIED_VERSION,
            model_name=self._model_name,
            provider_name=self._provider_name,
            prompt_version=self._prompt_version,
            instruction_version=_INSTRUCTION_VERSION,
            input_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        )
        draft = draft_model_train(context=context, spec=spec, requested_metrics=requested_metrics, provenance=provenance)
        proposals = tuple(f"PROPOSAL: {value}" for value in narrative.next_action_proposals)
        return build_model_research_proposal(research_goal=research_goal, agent_rationale=narrative.rationale, context=context, action_drafts=(draft,), next_action_proposals=proposals)


__all__ = ["ModelAgentWorker"]
