from __future__ import annotations

"""R-C final authority model: canonical resolution requests and resolved values.

Trust is derived from canonical resolution performed **at the trusted
consumer boundary**, never from the pedigree of a caller-supplied Python
object.  This module therefore contains no authority tokens, no private
secrets and no caller-settable trust flags.

- `ScenarioResolutionRequest` is the bounded public input of every trusted
  entry point: it carries only canonical owner objects (plus exact canonical
  references) that the system resolver re-validates.
- `ResolvedScenarioEvidenceBundle` is an intermediate value produced by
  `resolve_scenario_evidence`.  Possession of this type grants nothing: no
  trusted entry point (compare / explain / read tools / compare worker)
  accepts caller-supplied resolved bundles as proof of provenance.  It is
  constructible only for inspection/rendering convenience and is never an
  authority credential.
"""

from dataclasses import dataclass

from v3_backend.domain.backtest_runtime import (
    BacktestRunResult,
    BacktestRunSpec,
    CostPolicyVersion,
)
from v3_backend.domain.result_analytics import BacktestResultAnalytics
from v3_backend.domain.reviewer_integration import ResearchReviewReport
from v3_backend.domain.risk_runtime import RiskDecisionReport, RiskPolicySetVersion
from v3_backend.domain.strategies import (
    PortfolioIntent,
    StrategyEvaluationBindingVersion,
)
from v3_backend.domain.weights import (
    PortfolioIntentSource,
    RiskAdjustedWeightVector,
    TargetWeightVector,
    UnresolvedExactReference,
)

from .contracts import ScenarioComparisonInvariant, ScenarioEvidenceBundle


@dataclass(frozen=True, slots=True)
class ScenarioResolutionRequest:
    """Bounded canonical resolution request for one scenario.

    Fields are exact canonical owner objects (or exact canonical references);
    arbitrary prebuilt evidence projections are not accepted here.  The
    trusted consumer boundary hands this request to `resolve_scenario_evidence`
    and re-establishes the canonical chain before any comparison or
    explanation result is produced.
    """

    intent: PortfolioIntent
    source: PortfolioIntentSource
    binding: StrategyEvaluationBindingVersion
    construction_spec: UnresolvedExactReference
    risk_policy_set: RiskPolicySetVersion
    cost_policy: CostPolicyVersion
    base_currency: str
    target: TargetWeightVector | None = None
    risk_adjusted: RiskAdjustedWeightVector | None = None
    decision_report: RiskDecisionReport | None = None
    backtest_result: BacktestRunResult | None = None
    backtest_spec: BacktestRunSpec | None = None
    analytics: BacktestResultAnalytics | None = None
    reviewer_reports: tuple[ResearchReviewReport, ...] = ()

    def __post_init__(self) -> None:
        for name, value, expected in (
            ("intent", self.intent, PortfolioIntent),
            ("source", self.source, PortfolioIntentSource),
            ("binding", self.binding, StrategyEvaluationBindingVersion),
            ("construction_spec", self.construction_spec, UnresolvedExactReference),
            ("risk_policy_set", self.risk_policy_set, RiskPolicySetVersion),
            ("cost_policy", self.cost_policy, CostPolicyVersion),
        ):
            if not isinstance(value, expected):
                raise TypeError(f"{name} must be the canonical {expected.__name__} object")
        if not isinstance(self.base_currency, str) or not self.base_currency.strip():
            raise TypeError("base_currency must be exact non-empty text")
        for name, value, expected in (
            ("target", self.target, TargetWeightVector),
            ("risk_adjusted", self.risk_adjusted, RiskAdjustedWeightVector),
            ("decision_report", self.decision_report, RiskDecisionReport),
            ("backtest_result", self.backtest_result, BacktestRunResult),
            ("backtest_spec", self.backtest_spec, BacktestRunSpec),
            ("analytics", self.analytics, BacktestResultAnalytics),
        ):
            if value is not None and not isinstance(value, expected):
                raise TypeError(f"{name} must be the canonical {expected.__name__} object or None")
        if not isinstance(self.reviewer_reports, tuple) or any(
            not isinstance(report, ResearchReviewReport) for report in self.reviewer_reports
        ):
            raise TypeError("reviewer_reports must contain canonical ResearchReviewReport objects")

    def to_kwargs(self) -> dict[str, object]:
        """Resolver keyword arguments for this exact request."""

        return {
            "intent": self.intent,
            "source": self.source,
            "binding": self.binding,
            "construction_spec": self.construction_spec,
            "risk_policy_set": self.risk_policy_set,
            "cost_policy": self.cost_policy,
            "base_currency": self.base_currency,
            "target": self.target,
            "risk_adjusted": self.risk_adjusted,
            "decision_report": self.decision_report,
            "backtest_result": self.backtest_result,
            "backtest_spec": self.backtest_spec,
            "analytics": self.analytics,
            "reviewer_reports": self.reviewer_reports,
        }

    def resolve(self) -> "ResolvedScenarioEvidenceBundle":
        from .service import resolve_scenario_evidence

        return resolve_scenario_evidence(**self.to_kwargs())


@dataclass(frozen=True, slots=True)
class ResolvedScenarioEvidenceBundle:
    """Intermediate resolved evidence value produced by the system resolver.

    This is NOT an authority credential.  No public trusted entry point
    accepts a caller-supplied instance as proof of provenance; trusted
    compare/explain/tools/worker paths accept canonical inputs or
    `ScenarioResolutionRequest` objects and perform canonical resolution at
    the trusted consumer boundary.  Deterministic hash equality, empty
    binding gaps, or exact type identity grant nothing.
    """

    payload: ScenarioEvidenceBundle
    comparison_invariant: ScenarioComparisonInvariant | None

    @property
    def deterministic_sha256(self) -> str:
        """Deterministic identity covering payload and comparison invariant."""

        import hashlib

        from v3_backend.agents.contracts import deterministic_json

        return hashlib.sha256(
            deterministic_json(
                {
                    "payload_sha256": self.payload.deterministic_sha256,
                    "comparison_invariant_id": (
                        self.comparison_invariant.invariant_id
                        if self.comparison_invariant is not None
                        else None
                    ),
                }
            ).encode("utf-8")
        ).hexdigest()

    @property
    def binding_gaps(self) -> tuple[str, ...]:
        return self.payload.binding_gaps

    @property
    def intent(self) -> object:
        return self.payload.intent

    @property
    def construction_spec_version_id(self) -> str:
        return self.payload.construction_spec_version_id

    @property
    def construction_spec_content_sha256(self) -> str:
        return self.payload.construction_spec_content_sha256

    @property
    def risk_policy_set(self) -> object:
        return self.payload.risk_policy_set

    @property
    def cost_policy(self) -> object:
        return self.payload.cost_policy

    @property
    def target(self) -> object | None:
        return self.payload.target

    @property
    def risk_adjusted(self) -> object | None:
        return self.payload.risk_adjusted

    @property
    def backtest(self) -> object | None:
        return self.payload.backtest

    @property
    def analytics(self) -> object | None:
        return self.payload.analytics

    @property
    def reviewer_reports(self) -> tuple[object, ...]:
        return self.payload.reviewer_reports

    @property
    def treatment_context_key(self) -> tuple[tuple[str, str], ...]:
        return self.payload.treatment_context_key


__all__ = ["ResolvedScenarioEvidenceBundle", "ScenarioResolutionRequest"]
