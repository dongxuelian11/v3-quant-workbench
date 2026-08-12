from __future__ import annotations

from types import MappingProxyType

from v3_backend.agents.contracts import PermissionLevel
from v3_backend.agents.permissions import require_permission

from .contracts import (
    BacktestResultEvidenceView,
    CostPolicyEvidenceView,
    PortfolioIntentEvidenceView,
    ResultAnalyticsEvidenceView,
    ReviewerEvidenceView,
    RiskAdjustedEvidenceView,
    RiskPolicySetEvidenceView,
    ScenarioComparison,
    ScenarioEvidenceBundle,
    TargetWeightEvidenceView,
)
from .service import compare_scenarios


class PortfolioRiskAgentToolError(ValueError):
    pass


class PortfolioRiskReadTools:
    """R-local exact-object L0 tools; no execution, minting, or publication surface."""

    __slots__ = (
        "_intents",
        "_targets",
        "_policy_sets",
        "_adjusted",
        "_cost_policies",
        "_results",
        "_analytics",
        "_reviews",
        "_bundles",
        "_allowed",
        "_called",
    )

    def __init__(
        self,
        *,
        intents: tuple[PortfolioIntentEvidenceView, ...] = (),
        targets: tuple[TargetWeightEvidenceView, ...] = (),
        policy_sets: tuple[RiskPolicySetEvidenceView, ...] = (),
        adjusted: tuple[RiskAdjustedEvidenceView, ...] = (),
        cost_policies: tuple[CostPolicyEvidenceView, ...] = (),
        results: tuple[BacktestResultEvidenceView, ...] = (),
        analytics: tuple[ResultAnalyticsEvidenceView, ...] = (),
        reviews: tuple[ReviewerEvidenceView, ...] = (),
        bundles: tuple[ScenarioEvidenceBundle, ...] = (),
    ) -> None:
        self._intents = MappingProxyType({value.portfolio_intent_id: value for value in intents})
        self._targets = MappingProxyType({value.target_weight_vector_id: value for value in targets})
        self._policy_sets = MappingProxyType({value.risk_policy_set_version_id: value for value in policy_sets})
        self._adjusted = MappingProxyType({value.risk_adjusted_weight_vector_id: value for value in adjusted})
        self._cost_policies = MappingProxyType({value.policy_id: value for value in cost_policies})
        self._results = MappingProxyType({value.result_id: value for value in results})
        self._analytics = MappingProxyType({value.analytics_id: value for value in analytics})
        self._reviews = MappingProxyType({value.review_report_id: value for value in reviews})
        self._bundles = MappingProxyType({value.deterministic_sha256: value for value in bundles})
        sizes = (
            (len(self._intents), len(intents)),
            (len(self._targets), len(targets)),
            (len(self._policy_sets), len(policy_sets)),
            (len(self._adjusted), len(adjusted)),
            (len(self._cost_policies), len(cost_policies)),
            (len(self._results), len(results)),
            (len(self._analytics), len(analytics)),
            (len(self._reviews), len(reviews)),
            (len(self._bundles), len(bundles)),
        )
        if any(stored != given for stored, given in sizes):
            raise PortfolioRiskAgentToolError("duplicate exact object identities fail closed")
        self._allowed: frozenset[tuple[str, str]] = frozenset()
        self._called: list[tuple[str, str]] = []

    @property
    def visible_tool_names(self) -> tuple[str, ...]:
        return (
            "get_portfolio_intent",
            "get_target_weight_evidence",
            "get_risk_policy_set",
            "get_risk_adjusted_evidence",
            "get_cost_policy",
            "get_backtest_result",
            "get_result_analytics",
            "get_reviewer_report",
            "get_scenario_bundle",
            "compare_scenarios",
        )

    @property
    def called(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._called)

    def has(self, name: str, object_id: str) -> bool:
        """Evidence-inventory check without permission side effects."""

        stores = {
            "get_portfolio_intent": self._intents,
            "get_target_weight_evidence": self._targets,
            "get_risk_policy_set": self._policy_sets,
            "get_risk_adjusted_evidence": self._adjusted,
            "get_cost_policy": self._cost_policies,
            "get_backtest_result": self._results,
            "get_result_analytics": self._analytics,
            "get_reviewer_report": self._reviews,
            "get_scenario_bundle": self._bundles,
        }
        store = stores.get(name)
        if store is None:
            return False
        return object_id in store

    def begin(self, allowed: tuple[tuple[str, str], ...]) -> None:
        self._allowed = frozenset(allowed)
        self._called.clear()

    def _admit(self, name: str, object_id: str) -> None:
        require_permission(PermissionLevel.L0_READ, PermissionLevel.L0_READ)
        if (name, object_id) not in self._allowed:
            raise PortfolioRiskAgentToolError("agent requested evidence outside exact system-owned bindings")
        self._called.append((name, object_id))

    def _fetch(self, name: str, object_id: str, store: MappingProxyType[str, object]) -> object:
        self._admit(name, object_id)
        try:
            return store[object_id]
        except KeyError as exc:
            raise PortfolioRiskAgentToolError(f"exact object evidence is unavailable for {object_id}") from exc

    def get_portfolio_intent(self, portfolio_intent_id: str) -> PortfolioIntentEvidenceView:
        return self._fetch("get_portfolio_intent", portfolio_intent_id, self._intents)

    def get_target_weight_evidence(self, target_weight_vector_id: str) -> TargetWeightEvidenceView:
        return self._fetch("get_target_weight_evidence", target_weight_vector_id, self._targets)

    def get_risk_policy_set(self, risk_policy_set_version_id: str) -> RiskPolicySetEvidenceView:
        return self._fetch("get_risk_policy_set", risk_policy_set_version_id, self._policy_sets)

    def get_risk_adjusted_evidence(self, risk_adjusted_weight_vector_id: str) -> RiskAdjustedEvidenceView:
        return self._fetch("get_risk_adjusted_evidence", risk_adjusted_weight_vector_id, self._adjusted)

    def get_cost_policy(self, cost_policy_id: str) -> CostPolicyEvidenceView:
        return self._fetch("get_cost_policy", cost_policy_id, self._cost_policies)

    def get_backtest_result(self, result_id: str) -> BacktestResultEvidenceView:
        return self._fetch("get_backtest_result", result_id, self._results)

    def get_result_analytics(self, analytics_id: str) -> ResultAnalyticsEvidenceView:
        return self._fetch("get_result_analytics", analytics_id, self._analytics)

    def get_reviewer_report(self, review_report_id: str) -> ReviewerEvidenceView:
        return self._fetch("get_reviewer_report", review_report_id, self._reviews)

    def get_scenario_bundle(self, bundle_sha256: str) -> ScenarioEvidenceBundle:
        return self._fetch("get_scenario_bundle", bundle_sha256, self._bundles)

    def compare_scenarios(self, comparison_key: str) -> ScenarioComparison:
        self._admit("compare_scenarios", comparison_key)
        parts = comparison_key.split("|", 3)
        if len(parts) != 4:
            raise PortfolioRiskAgentToolError("comparison key must bind left, right, metric and direction")
        left_id, right_id, metric, direction = parts
        try:
            left = self._bundles[left_id]
            right = self._bundles[right_id]
        except KeyError as exc:
            raise PortfolioRiskAgentToolError("scenario bundle evidence is unavailable") from exc
        return compare_scenarios(
            left,
            right,
            objective_metric=metric or None,
            objective_direction=direction or None,
        )


__all__ = ["PortfolioRiskAgentToolError", "PortfolioRiskReadTools"]
