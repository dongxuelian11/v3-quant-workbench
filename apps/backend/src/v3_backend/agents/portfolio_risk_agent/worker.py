from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, version

from pydantic_ai import Agent
from pydantic_ai.models import Model

from v3_backend.agents.contracts import AgentKind, AgentProvenance, PermissionLevel, deterministic_json
from v3_backend.agents.permissions import require_permission
from v3_backend.agents.pydantic_worker import AgentOutputRejected, PYDANTIC_AI_VERIFIED_VERSION
from v3_backend.domain.weights import RiskAdjustedWeightVector, TargetWeightVector

from .contracts import (
    PortfolioRiskNarrative,
    PortfolioRiskProposal,
    PortfolioRiskScenarioContext,
)
from .service import (
    build_portfolio_risk_proposal,
    draft_backtest_run,
    draft_portfolio_construct,
    draft_risk_apply,
)
from .tools import PortfolioRiskReadTools


_INSTRUCTION_VERSION = "round5-r-portfolio-risk-agent/1.0"
_INSTRUCTIONS = (
    "Call get_portfolio_intent (and, when available, the scenario bundle) for the exact "
    "PortfolioIntent in the request. Return only typed research rationale and explicitly "
    "labeled next-action proposals. Do not compute or propose weights, risk metrics, "
    "analytics, exposure, covariance, or causal claims; do not execute construction, risk "
    "application, or backtests; do not mint TargetWeightVector, RiskAdjustedWeightVector, "
    "RiskModelVersion, or CostPolicy; do not waive A-share or canonical constraints; "
    "do not admit truth or publish."
)


class PortfolioRiskAgentWorker:
    """PydanticAI narrative adapter around system-owned deterministic R drafts."""

    def __init__(
        self,
        *,
        model: Model,
        permission: object,
        model_name: str,
        provider_name: str,
        prompt_version: str,
        read_tools: PortfolioRiskReadTools,
    ) -> None:
        try:
            installed = version("pydantic-ai-slim")
        except PackageNotFoundError as exc:
            raise RuntimeError("pydantic-ai-slim is required") from exc
        if installed != PYDANTIC_AI_VERIFIED_VERSION:
            raise RuntimeError(f"pydantic-ai-slim version mismatch: expected {PYDANTIC_AI_VERIFIED_VERSION}, got {installed}")
        if type(read_tools) is not PortfolioRiskReadTools:
            raise TypeError("exact R PortfolioRiskReadTools is required")
        self._model = model
        self._permission = permission
        self._model_name = model_name
        self._provider_name = provider_name
        self._prompt_version = prompt_version
        self._read_tools = read_tools

    @property
    def visible_tool_names(self) -> tuple[str, ...]:
        return self._read_tools.visible_tool_names

    def _run_proposal(
        self,
        *,
        task: str,
        research_goal: str,
        context: PortfolioRiskScenarioContext,
        required_tool: tuple[str, str],
    ) -> PortfolioRiskNarrative:
        decision = require_permission(self._permission, PermissionLevel.L1_DRAFT)
        request = {
            "task": task,
            "research_goal": research_goal,
            "portfolio_intent_id": context.portfolio_intent_id,
            "risk_policy_set_version_id": context.risk_policy_set_version_id,
            "required_tool_call": required_tool[0],
        }
        prompt = deterministic_json(request)
        self._read_tools.begin((required_tool,))
        agent: Agent[None, PortfolioRiskNarrative] = Agent(
            self._model,
            output_type=PortfolioRiskNarrative,
            instructions=_INSTRUCTIONS,
            tools=[getattr(self._read_tools, required_tool[0])],
            retries={"output": 1},
        )
        try:
            result = agent.run_sync(prompt)
            narrative = PortfolioRiskNarrative.model_validate(result.output)
            if required_tool not in self._read_tools.called:
                raise AgentOutputRejected("Portfolio/Risk Agent must consume exact PortfolioIntent evidence")
        except Exception as exc:
            raise AgentOutputRejected("structured Portfolio/Risk Agent proposal failed closed") from exc
        return narrative

    def _provenance(self, prompt_sha256: str, task: str) -> AgentProvenance:
        return AgentProvenance(
            agent_kind=AgentKind.RESEARCH,
            sdk_version=PYDANTIC_AI_VERIFIED_VERSION,
            model_name=self._model_name,
            provider_name=self._provider_name,
            prompt_version=self._prompt_version,
            instruction_version=_INSTRUCTION_VERSION,
            input_sha256=prompt_sha256,
        )

    def run_construct_proposal(self, *, research_goal: str, context: PortfolioRiskScenarioContext) -> PortfolioRiskProposal:
        narrative = self._run_proposal(
            task="PORTFOLIO_CONSTRUCT_PROPOSAL",
            research_goal=research_goal,
            context=context,
            required_tool=("get_portfolio_intent", context.portfolio_intent_id),
        )
        prompt = deterministic_json({"task": "PORTFOLIO_CONSTRUCT_PROPOSAL", "research_goal": research_goal, "portfolio_intent_id": context.portfolio_intent_id})
        provenance = self._provenance(hashlib.sha256(prompt.encode("utf-8")).hexdigest(), "PORTFOLIO_CONSTRUCT_PROPOSAL")
        draft = draft_portfolio_construct(context=context, provenance=provenance)
        proposals = tuple(f"PROPOSAL: {value}" for value in narrative.next_action_proposals)
        return build_portfolio_risk_proposal(
            research_goal=research_goal,
            agent_rationale=narrative.rationale,
            context=context,
            action_drafts=(draft,),
            next_action_proposals=proposals,
        )

    def run_risk_proposal(
        self,
        *,
        research_goal: str,
        context: PortfolioRiskScenarioContext,
        source_target: TargetWeightVector,
    ) -> PortfolioRiskProposal:
        if context.source_target_weight_vector_id is None:
            raise AgentOutputRejected("risk proposal requires an exact source TargetWeightVector")
        narrative = self._run_proposal(
            task="RISK_APPLY_PROPOSAL",
            research_goal=research_goal,
            context=context,
            required_tool=("get_portfolio_intent", context.portfolio_intent_id),
        )
        prompt = deterministic_json({"task": "RISK_APPLY_PROPOSAL", "research_goal": research_goal, "portfolio_intent_id": context.portfolio_intent_id, "source_target_weight_vector_id": context.source_target_weight_vector_id})
        provenance = self._provenance(hashlib.sha256(prompt.encode("utf-8")).hexdigest(), "RISK_APPLY_PROPOSAL")
        draft = draft_risk_apply(context=context, source_target=source_target, provenance=provenance)
        proposals = tuple(f"PROPOSAL: {value}" for value in narrative.next_action_proposals)
        return build_portfolio_risk_proposal(
            research_goal=research_goal,
            agent_rationale=narrative.rationale,
            context=context,
            action_drafts=(draft,),
            next_action_proposals=proposals,
        )

    def run_backtest_proposal(
        self,
        *,
        research_goal: str,
        context: PortfolioRiskScenarioContext,
        risk_adjusted: RiskAdjustedWeightVector,
        initial_cash: str,
        engine_version: str,
    ) -> PortfolioRiskProposal:
        if context.risk_adjusted_weight_vector_id is None:
            raise AgentOutputRejected("backtest proposal requires an exact RiskAdjustedWeightVector")
        narrative = self._run_proposal(
            task="BACKTEST_RUN_PROPOSAL",
            research_goal=research_goal,
            context=context,
            required_tool=("get_portfolio_intent", context.portfolio_intent_id),
        )
        prompt = deterministic_json({"task": "BACKTEST_RUN_PROPOSAL", "research_goal": research_goal, "portfolio_intent_id": context.portfolio_intent_id, "risk_adjusted_weight_vector_id": context.risk_adjusted_weight_vector_id})
        provenance = self._provenance(hashlib.sha256(prompt.encode("utf-8")).hexdigest(), "BACKTEST_RUN_PROPOSAL")
        draft = draft_backtest_run(
            context=context,
            risk_adjusted=risk_adjusted,
            initial_cash=initial_cash,
            engine_version=engine_version,
            provenance=provenance,
        )
        proposals = tuple(f"PROPOSAL: {value}" for value in narrative.next_action_proposals)
        return build_portfolio_risk_proposal(
            research_goal=research_goal,
            agent_rationale=narrative.rationale,
            context=context,
            action_drafts=(draft,),
            next_action_proposals=proposals,
        )

    def run_compare_proposal(self, *, research_goal: str, left_analytics_id: str, right_analytics_id: str) -> PortfolioRiskNarrative:
        require_permission(self._permission, PermissionLevel.L1_DRAFT)
        prompt = deterministic_json({"task": "RESULT_COMPARE_PROPOSAL", "research_goal": research_goal, "left_analytics_id": left_analytics_id, "right_analytics_id": right_analytics_id})
        agent: Agent[None, PortfolioRiskNarrative] = Agent(
            self._model,
            output_type=PortfolioRiskNarrative,
            instructions=_INSTRUCTIONS,
            retries={"output": 1},
        )
        try:
            result = agent.run_sync(prompt)
            return PortfolioRiskNarrative.model_validate(result.output)
        except Exception as exc:
            raise AgentOutputRejected("structured compare proposal failed closed") from exc


__all__ = ["PortfolioRiskAgentWorker"]
