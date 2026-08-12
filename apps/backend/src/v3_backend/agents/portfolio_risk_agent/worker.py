from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, version

from pydantic_ai import Agent
from pydantic_ai.models import Model

from v3_backend.agents.contracts import AgentKind, AgentProvenance, PermissionLevel, deterministic_json
from v3_backend.agents.permissions import require_permission
from v3_backend.agents.pydantic_worker import AgentOutputRejected, PYDANTIC_AI_VERIFIED_VERSION
from v3_backend.domain.backtest_runtime import BacktestRunSpec
from v3_backend.domain.risk_runtime import RiskPolicySetVersion
from v3_backend.domain.weights import RiskAdjustedWeightVector, RuntimeIdentity, TargetWeightVector

from .contracts import (
    PortfolioRiskNarrative,
    PortfolioRiskProposal,
    PortfolioRiskScenarioContext,
)
from .service import (
    _compare_resolved_scenarios,
    build_portfolio_risk_proposal,
    draft_backtest_run,
    draft_portfolio_construct,
    draft_risk_apply,
    resolve_scenario_evidence,
)
from .tools import PortfolioRiskReadTools
from .trusted import ScenarioResolutionRequest


_INSTRUCTION_VERSION = "round5-r-portfolio-risk-agent/1.1"
_INSTRUCTIONS = (
    "Call only the exact read tools listed in the prompt for the exact objects in the "
    "request. Return only typed research rationale and explicitly labeled next-action "
    "proposals. Do not compute or propose weights, risk metrics, analytics, exposure, "
    "covariance, or causal claims; do not execute construction, risk application, or "
    "backtests; do not mint TargetWeightVector, RiskAdjustedWeightVector, "
    "RiskModelVersion, or CostPolicy; do not waive A-share or canonical constraints; "
    "do not invent comparison values absent from the exact ScenarioComparison evidence; "
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
        allowed_tools: tuple[tuple[str, str], ...],
    ) -> PortfolioRiskNarrative:
        require_permission(self._permission, PermissionLevel.L1_DRAFT)
        request = {
            "task": task,
            "research_goal": research_goal,
            "portfolio_intent_id": context.portfolio_intent_id,
            "required_tool_call": required_tool[0],
            "allowed_evidence": [list(item) for item in allowed_tools],
        }
        prompt = deterministic_json(request)
        self._read_tools.begin((required_tool, *allowed_tools))
        tools = [getattr(self._read_tools, name) for name in {item[0] for item in (required_tool, *allowed_tools)}]
        agent: Agent[None, PortfolioRiskNarrative] = Agent(
            self._model,
            output_type=PortfolioRiskNarrative,
            instructions=_INSTRUCTIONS,
            tools=tools,
            retries={"output": 1},
        )
        try:
            result = agent.run_sync(prompt)
            narrative = PortfolioRiskNarrative.model_validate(result.output)
            if required_tool not in self._read_tools.called:
                raise AgentOutputRejected("Portfolio/Risk Agent must consume the exact required evidence tool")
        except Exception as exc:
            raise AgentOutputRejected("structured Portfolio/Risk Agent proposal failed closed") from exc
        return narrative

    def _provenance(self, prompt_sha256: str) -> AgentProvenance:
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
            allowed_tools=(),
        )
        prompt = deterministic_json({"task": "PORTFOLIO_CONSTRUCT_PROPOSAL", "research_goal": research_goal, "portfolio_intent_id": context.portfolio_intent_id})
        provenance = self._provenance(hashlib.sha256(prompt.encode("utf-8")).hexdigest())
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
        policy_set: RiskPolicySetVersion,
        runtime_identity: RuntimeIdentity,
    ) -> PortfolioRiskProposal:
        if context.source_target_weight_vector_id is None:
            raise AgentOutputRejected("risk proposal requires an exact source TargetWeightVector")
        target_evidence = ("get_target_weight_evidence", source_target.target_weight_vector_id)
        policy_evidence = ("get_risk_policy_set", policy_set.risk_policy_set_version_id)
        for tool, object_id in (target_evidence, policy_evidence):
            if not self._read_tools.has(tool, object_id):
                raise AgentOutputRejected(f"risk proposal requires exact {tool} evidence")
        narrative = self._run_proposal(
            task="RISK_APPLY_PROPOSAL",
            research_goal=research_goal,
            context=context,
            required_tool=("get_portfolio_intent", context.portfolio_intent_id),
            allowed_tools=(target_evidence, policy_evidence),
        )
        prompt = deterministic_json({"task": "RISK_APPLY_PROPOSAL", "research_goal": research_goal, "portfolio_intent_id": context.portfolio_intent_id, "source_target_weight_vector_id": context.source_target_weight_vector_id})
        provenance = self._provenance(hashlib.sha256(prompt.encode("utf-8")).hexdigest())
        draft = draft_risk_apply(
            context=context,
            source_target=source_target,
            policy_set=policy_set,
            runtime_identity=runtime_identity,
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

    def run_backtest_proposal(
        self,
        *,
        research_goal: str,
        context: PortfolioRiskScenarioContext,
        risk_adjusted: RiskAdjustedWeightVector,
        spec: BacktestRunSpec,
    ) -> PortfolioRiskProposal:
        if context.risk_adjusted_weight_vector_id is None:
            raise AgentOutputRejected("backtest proposal requires an exact RiskAdjustedWeightVector")
        adjusted_evidence = ("get_risk_adjusted_evidence", risk_adjusted.risk_adjusted_weight_vector_id)
        cost_evidence = ("get_cost_policy", spec.cost_policy.policy_id)
        for tool, object_id in (adjusted_evidence, cost_evidence):
            if not self._read_tools.has(tool, object_id):
                raise AgentOutputRejected(f"backtest proposal requires exact {tool} evidence")
        narrative = self._run_proposal(
            task="BACKTEST_RUN_PROPOSAL",
            research_goal=research_goal,
            context=context,
            required_tool=("get_portfolio_intent", context.portfolio_intent_id),
            allowed_tools=(adjusted_evidence, cost_evidence),
        )
        prompt = deterministic_json({"task": "BACKTEST_RUN_PROPOSAL", "research_goal": research_goal, "portfolio_intent_id": context.portfolio_intent_id, "risk_adjusted_weight_vector_id": context.risk_adjusted_weight_vector_id})
        provenance = self._provenance(hashlib.sha256(prompt.encode("utf-8")).hexdigest())
        draft = draft_backtest_run(
            context=context,
            risk_adjusted=risk_adjusted,
            spec=spec,
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

    def run_compare_proposal(
        self,
        *,
        research_goal: str,
        left: ScenarioResolutionRequest,
        right: ScenarioResolutionRequest,
        objective_metric: str | None = None,
        objective_direction: str | None = None,
    ) -> PortfolioRiskNarrative:
        """Evidence-grounded compare proposal.

        The worker accepts canonical resolution requests only: both scenarios
        are resolved through the canonical resolver at this trusted boundary,
        the deterministic comparison is computed system-side, and the model
        MUST consume the exact compare_scenarios tool result.  Caller-supplied
        resolved bundles are not accepted; no evidence tool call => fail
        closed.
        """

        require_permission(self._permission, PermissionLevel.L1_DRAFT)
        if type(left) is not ScenarioResolutionRequest or type(right) is not ScenarioResolutionRequest:
            raise TypeError(
                "compare proposal requires exact ScenarioResolutionRequest inputs "
                "(canonical owner objects); caller-supplied resolved evidence is not authority"
            )
        left_resolved = resolve_scenario_evidence(**left.to_kwargs())
        right_resolved = resolve_scenario_evidence(**right.to_kwargs())
        left_id = left_resolved.deterministic_sha256
        right_id = right_resolved.deterministic_sha256
        for tool, object_id in (("get_scenario_bundle", left_id), ("get_scenario_bundle", right_id)):
            if not self._read_tools.has(tool, object_id):
                raise AgentOutputRejected("compare proposal requires exact scenario bundle evidence")
        comparison = _compare_resolved_scenarios(
            left_resolved,
            right_resolved,
            objective_metric=objective_metric,
            objective_direction=objective_direction,
        )
        key = f"{left_id}|{right_id}|{objective_metric or ''}|{objective_direction or ''}"
        required_tool = ("compare_scenarios", key)
        request = {
            "task": "RESULT_COMPARE_PROPOSAL",
            "research_goal": research_goal,
            "left_bundle_sha256": left_id,
            "right_bundle_sha256": right_id,
            "comparison_key": key,
            "comparison_status": comparison.status.value,
            "objective_metric": objective_metric,
            "objective_direction": objective_direction,
            "required_tool_call": "compare_scenarios",
        }
        prompt = deterministic_json(request)
        self._read_tools.begin((required_tool,))
        agent: Agent[None, PortfolioRiskNarrative] = Agent(
            self._model,
            output_type=PortfolioRiskNarrative,
            instructions=_INSTRUCTIONS,
            tools=[self._read_tools.compare_scenarios],
            retries={"output": 1},
        )
        try:
            result = agent.run_sync(prompt)
            narrative = PortfolioRiskNarrative.model_validate(result.output)
            if required_tool not in self._read_tools.called:
                raise AgentOutputRejected("compare proposal must consume the exact ScenarioComparison evidence")
        except Exception as exc:
            raise AgentOutputRejected("structured compare proposal failed closed") from exc
        return narrative


__all__ = ["PortfolioRiskAgentWorker"]
