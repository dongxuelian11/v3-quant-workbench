"""Runnable Strategy -> Portfolio -> Risk -> research Backtest composition.

This module deliberately does not provide a second financial engine or a Formal
market-data shortcut.  It composes accepted owners, then assembles explicit
PRE_ALPHA research observations for the existing pure Backtest engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol

from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
from v3_backend.domain.backtest_runtime import (
    AshareTradingRuleProfileVersion,
    BacktestRunResult,
    BacktestRunSpec,
    Board,
    CorporateAction,
    CostPolicyVersion,
    DailyMarketState,
    DeterministicAshareBacktestEngine,
    ExactInputReference,
    ExecutionTimingProfileVersion,
    InitialHolding,
    InstrumentDefinition,
    MarketSession,
    ScheduledWeights,
)
from v3_backend.domain.portfolio_construction import (
    CanonicalPortfolioOwnerService,
    OptimizerCandidate,
    PortfolioConstructionSpecVersion,
)
from v3_backend.domain.risk_runtime import (
    CanonicalRiskApplicationRequest,
    CanonicalRiskApplicationService,
)
from v3_backend.domain.strategies import (
    FormalStrategyEvaluationRequest,
    FormalStrategyEvaluationService,
)
from v3_backend.domain.weights import RiskAdjustedWeightVector, RuntimeIdentity
from v3_backend.provenance.canonical_hash import canonical_json_bytes, canonical_sha256


RESEARCH_ASSUMPTION_PROFILE_ID = "RESEARCH_FREE_DATA_V1"
RESEARCH_ASSUMPTION_CODES = (
    "BAR_PRESENT_ASSUMED_TRADABLE",
    "SUSPENSION_NOT_MODELLED",
    "PRICE_LIMIT_NOT_MODELLED",
    "ST_RESTRICTION_NOT_MODELLED",
    "CORPORATE_ACTION_LIMITED_TO_AVAILABLE_DATA",
)
RESEARCH_BACKTEST_RESULT_ROLE = "RESEARCH_BACKTEST_RESULT"
RESEARCH_BACKTEST_RESULT_SCHEMA_VERSION = "v3.research-backtest-result/1.0.0"
RESEARCH_BACKTEST_RESULT_SCHEMA_FINGERPRINT = "schema_sha256_" + canonical_sha256(
    {
        "schema_version": RESEARCH_BACKTEST_RESULT_SCHEMA_VERSION,
        "ordered_fields": [
            "schema_version",
            "research_classification",
            "assumption_profile",
            "run_receipt",
            "backtest_result",
        ],
    }
)


class ResearchPipelineStatus(StrEnum):
    SUCCESS = "SUCCESS"
    STRATEGY_FAILED = "STRATEGY_FAILED"
    PORTFOLIO_FAILED = "PORTFOLIO_FAILED"
    RISK_FAILED = "RISK_FAILED"
    BACKTEST_FAILED = "BACKTEST_FAILED"
    RESULT_PUBLICATION_FAILED = "RESULT_PUBLICATION_FAILED"


class ResearchPipelineContractError(ValueError):
    """The bounded research request or explicit assumption profile is invalid."""


@dataclass(frozen=True, slots=True)
class ResearchExecutionAssumptionProfile:
    profile_id: str
    assumption_codes: tuple[str, ...]
    research_classification: tuple[str, ...]

    @classmethod
    def free_data_v1(cls) -> "ResearchExecutionAssumptionProfile":
        return cls(
            profile_id=RESEARCH_ASSUMPTION_PROFILE_ID,
            assumption_codes=RESEARCH_ASSUMPTION_CODES,
            research_classification=("RESEARCH_ONLY", "APPROXIMATE"),
        )

    def __post_init__(self) -> None:
        if self.profile_id != RESEARCH_ASSUMPTION_PROFILE_ID:
            raise ResearchPipelineContractError("unsupported research assumption profile")
        if self.assumption_codes != RESEARCH_ASSUMPTION_CODES:
            raise ResearchPipelineContractError(
                "RESEARCH_FREE_DATA_V1 must record every missing market semantic"
            )
        if self.research_classification != ("RESEARCH_ONLY", "APPROXIMATE"):
            raise ResearchPipelineContractError(
                "research classification must remain RESEARCH_ONLY / APPROXIMATE"
            )

    @property
    def identity(self) -> str:
        return "reas_sha256_" + canonical_sha256(self.to_wire())

    def to_wire(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "assumption_codes": list(self.assumption_codes),
            "research_classification": list(self.research_classification),
            "truth_admission": PRE_ALPHA_CEILING.to_wire(),
            "semantics": "explicit research assumptions; not market truth",
        }


@dataclass(frozen=True, slots=True)
class ResearchBarObservation:
    instrument_id: str
    board: Board
    raw_open: str
    raw_close: str

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, str) or not self.instrument_id.strip():
            raise ResearchPipelineContractError("instrument_id must be non-empty")
        if not isinstance(self.board, Board):
            raise TypeError("board must be Board")

    def to_wire(self) -> dict[str, str]:
        return {
            "instrument_id": self.instrument_id,
            "board": self.board.value,
            "raw_open": self.raw_open,
            "raw_close": self.raw_close,
        }


@dataclass(frozen=True, slots=True)
class ResearchSessionObservation:
    session_date: date
    is_open: bool
    bars: tuple[ResearchBarObservation, ...]
    available_corporate_actions: tuple[CorporateAction, ...] = ()

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.bars, key=lambda value: value.instrument_id))
        if not ordered or len({value.instrument_id for value in ordered}) != len(ordered):
            raise ResearchPipelineContractError(
                "research session bars must be non-empty and unique"
            )
        if any(action.ex_date != self.session_date for action in self.available_corporate_actions):
            raise ResearchPipelineContractError(
                "available corporate actions must match the research session date"
            )
        object.__setattr__(self, "bars", ordered)
        object.__setattr__(
            self,
            "available_corporate_actions",
            tuple(sorted(self.available_corporate_actions, key=lambda value: value.action_id)),
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "session_date": self.session_date.isoformat(),
            "is_open": self.is_open,
            "bars": [value.to_wire() for value in self.bars],
            "available_corporate_actions": [
                value.to_wire() for value in self.available_corporate_actions
            ],
        }


@dataclass(frozen=True, slots=True)
class ResearchPipelineRequest:
    project_id: str
    project_context_revision_id: str
    strategy_request: FormalStrategyEvaluationRequest
    construction_spec: PortfolioConstructionSpecVersion
    risk_policy_set_version_id: str
    runtime_identity: RuntimeIdentity
    base_currency: str
    as_of: datetime
    decision_time: datetime
    rebalance_time: datetime
    valid_until: datetime
    published_at: datetime
    assumption_profile: ResearchExecutionAssumptionProfile
    observations: tuple[ResearchSessionObservation, ...]
    initial_cash: str
    initial_holdings: tuple[InitialHolding, ...]
    rule_profile: AshareTradingRuleProfileVersion
    cost_policy: CostPolicyVersion
    execution_timing_profile: ExecutionTimingProfileVersion
    optimizer_candidate: OptimizerCandidate | None = None

    def __post_init__(self) -> None:
        if not self.project_id.startswith("prj_"):
            raise ResearchPipelineContractError("project_id is not canonical")
        if not self.project_context_revision_id.startswith("pcr_"):
            raise ResearchPipelineContractError(
                "project_context_revision_id is not canonical"
            )
        if not isinstance(self.strategy_request, FormalStrategyEvaluationRequest):
            raise TypeError("strategy_request must be FormalStrategyEvaluationRequest")
        if not isinstance(self.assumption_profile, ResearchExecutionAssumptionProfile):
            raise TypeError("assumption_profile must be explicit")
        if not self.observations:
            raise ResearchPipelineContractError("research observations are required")
        for field_name in (
            "as_of",
            "decision_time",
            "rebalance_time",
            "valid_until",
            "published_at",
        ):
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ResearchPipelineContractError(f"{field_name} must be timezone-aware")


class AdjustedWeightOwnerPort(Protocol):
    def require_adjusted_weight_vector(
        self, risk_adjusted_weight_vector_id: str
    ) -> RiskAdjustedWeightVector: ...


class ResultArtifactStorePort(Protocol):
    def stage_bytes(self, payload: bytes): ...

    def publish(self, staging_token: str, **kwargs): ...

    def read_bytes(self, artifact_id: str, *, max_bytes: int | None = None) -> bytes: ...


@dataclass(frozen=True, slots=True)
class CoreResearchPipelineResult:
    status: ResearchPipelineStatus
    completed_stages: tuple[str, ...]
    failed_stage: str | None
    error_type: str | None
    error_message: str | None
    run_id: str | None
    strategy_output_id: str | None
    portfolio_intent_id: str | None
    target_weight_vector_id: str | None
    risk_application_receipt_id: str | None
    risk_adjusted_weight_vector_id: str | None
    backtest_result_id: str | None
    run_receipt_id: str | None
    result_artifact_id: str | None
    result_artifact_sha256: str | None
    result_artifact_readable: bool
    assumption_profile_identity: str
    assumption_profile_id: str
    assumption_codes: tuple[str, ...]
    research_classification: tuple[str, ...]
    canonical_truth_state: str
    canonical_admission_state: str

    @property
    def succeeded(self) -> bool:
        return self.status is ResearchPipelineStatus.SUCCESS

    def to_wire(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "completed_stages": list(self.completed_stages),
            "failed_stage": self.failed_stage,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "run_id": self.run_id,
            "strategy_output_id": self.strategy_output_id,
            "portfolio_intent_id": self.portfolio_intent_id,
            "target_weight_vector_id": self.target_weight_vector_id,
            "risk_application_receipt_id": self.risk_application_receipt_id,
            "risk_adjusted_weight_vector_id": self.risk_adjusted_weight_vector_id,
            "backtest_result_id": self.backtest_result_id,
            "run_receipt_id": self.run_receipt_id,
            "result_artifact_id": self.result_artifact_id,
            "result_artifact_sha256": self.result_artifact_sha256,
            "result_artifact_readable": self.result_artifact_readable,
            "truth": {
                "canonical_truth_state": self.canonical_truth_state,
                "canonical_admission_state": self.canonical_admission_state,
                "research_classification": list(self.research_classification),
            },
            "research_assumption_profile": {
                "profile_id": self.assumption_profile_id,
                "identity": self.assumption_profile_identity,
                "assumption_codes": list(self.assumption_codes),
            },
        }


class ResearchBacktestAssembler:
    """Maps explicitly classified research observations to the existing engine input."""

    def assemble(
        self,
        *,
        request: ResearchPipelineRequest,
        adjusted_weights: RiskAdjustedWeightVector,
    ) -> BacktestRunSpec:
        profile = request.assumption_profile
        expected_instruments = tuple(
            sorted(adjusted_weights.source_target.source.universe_instrument_ids)
        )
        observed_sessions = tuple(
            sorted(request.observations, key=lambda value: value.session_date)
        )
        if len({value.session_date for value in observed_sessions}) != len(observed_sessions):
            raise ResearchPipelineContractError("research session dates must be unique")
        for session in observed_sessions:
            observed = tuple(value.instrument_id for value in session.bars)
            if observed != expected_instruments:
                raise ResearchPipelineContractError(
                    "every research session must contain the exact Portfolio universe"
                )

        sessions = tuple(
            MarketSession(
                session_date=value.session_date,
                is_open=value.is_open,
                states=tuple(
                    DailyMarketState(
                        instrument_id=bar.instrument_id,
                        raw_open=bar.raw_open,
                        raw_close=bar.raw_close,
                        suspended=False,
                        tradable=True,
                        buy_restricted=False,
                        restricted_security=False,
                        at_limit_up_open=False,
                        at_limit_down_open=False,
                        no_price_limit_session=False,
                    )
                    for bar in value.bars
                ),
                corporate_actions=value.available_corporate_actions,
            )
            for value in observed_sessions
        )
        boards: dict[str, Board] = {}
        for session in observed_sessions:
            for bar in session.bars:
                prior = boards.setdefault(bar.instrument_id, bar.board)
                if prior is not bar.board:
                    raise ResearchPipelineContractError(
                        "research board metadata must be stable across sessions"
                    )

        observation_wire = [value.to_wire() for value in observed_sessions]
        market_digest = canonical_sha256(
            {"observations": observation_wire, "assumption_profile": profile.to_wire()}
        )
        calendar_digest = canonical_sha256(
            [
                {"session_date": value.session_date.isoformat(), "is_open": value.is_open}
                for value in observed_sessions
            ]
        )
        universe_digest = canonical_sha256(
            [{"instrument_id": value, "board": boards[value].value} for value in expected_instruments]
        )
        corporate_action_digest = canonical_sha256(
            [
                action.to_wire()
                for session in observed_sessions
                for action in session.available_corporate_actions
            ]
        )
        references = (
            ExactInputReference(
                "SNAPSHOT",
                "research_snapshot_sha256_" + market_digest,
                market_digest,
                PRE_ALPHA_CEILING,
            ),
            ExactInputReference(
                "MARKET_DATA",
                "research_market_sha256_" + market_digest,
                market_digest,
                PRE_ALPHA_CEILING,
            ),
            ExactInputReference(
                "TRADING_CALENDAR",
                "research_calendar_sha256_" + calendar_digest,
                calendar_digest,
                PRE_ALPHA_CEILING,
            ),
            ExactInputReference(
                "UNIVERSE",
                "research_universe_sha256_" + universe_digest,
                universe_digest,
                PRE_ALPHA_CEILING,
            ),
            ExactInputReference(
                "CORPORATE_ACTIONS",
                "research_actions_sha256_" + corporate_action_digest,
                corporate_action_digest,
                PRE_ALPHA_CEILING,
            ),
            ExactInputReference(
                "OFFICIAL_TRADING_HOURS",
                request.execution_timing_profile.profile_id,
                request.execution_timing_profile.content_sha256,
                PRE_ALPHA_CEILING,
            ),
            ExactInputReference(
                "OFFICIAL_COST_RULES",
                request.cost_policy.policy_id,
                request.cost_policy.content_sha256,
                PRE_ALPHA_CEILING,
            ),
        )
        return BacktestRunSpec.create(
            initial_cash=request.initial_cash,
            initial_holdings=request.initial_holdings,
            instruments=tuple(
                InstrumentDefinition(instrument_id, boards[instrument_id])
                for instrument_id in expected_instruments
            ),
            sessions=sessions,
            schedule=(
                ScheduledWeights(
                    adjusted_weights.source_target.rebalance_time,
                    adjusted_weights,
                ),
            ),
            rule_profile=request.rule_profile,
            cost_policy=request.cost_policy,
            execution_timing_profile=request.execution_timing_profile,
            exact_references=references,
            runtime_identity=request.runtime_identity,
        )


class CoreResearchPipelineService:
    """Thin composition service; every numeric stage remains owned by its existing owner."""

    service_version = "v3.core-research-pipeline/1.0.0"

    def __init__(
        self,
        *,
        strategy: FormalStrategyEvaluationService,
        portfolio: CanonicalPortfolioOwnerService,
        risk: CanonicalRiskApplicationService,
        adjusted_weight_owner: AdjustedWeightOwnerPort,
        result_artifact_store: ResultArtifactStorePort,
        backtest: DeterministicAshareBacktestEngine | None = None,
        assembler: ResearchBacktestAssembler | None = None,
    ) -> None:
        self._strategy = strategy
        self._portfolio = portfolio
        self._risk = risk
        self._adjusted_weight_owner = adjusted_weight_owner
        self._result_artifact_store = result_artifact_store
        self._backtest = backtest or DeterministicAshareBacktestEngine()
        self._assembler = assembler or ResearchBacktestAssembler()

    def run(self, request: ResearchPipelineRequest) -> CoreResearchPipelineResult:
        if not isinstance(request, ResearchPipelineRequest):
            raise TypeError("run requires ResearchPipelineRequest")
        completed: list[str] = []
        state: dict[str, str | None] = {
            "strategy_output_id": None,
            "portfolio_intent_id": None,
            "target_weight_vector_id": None,
            "risk_application_receipt_id": None,
            "risk_adjusted_weight_vector_id": None,
            "backtest_result_id": None,
            "run_id": None,
            "run_receipt_id": None,
        }

        try:
            strategy_result = self._strategy.evaluate(request.strategy_request)
            if (
                strategy_result.signal_artifact is None
                or strategy_result.selection_artifact is None
                or strategy_result.portfolio_intent is None
            ):
                raise ResearchPipelineContractError(
                    "Strategy did not produce Signal, Selection and PortfolioIntent"
                )
            state["strategy_output_id"] = strategy_result.signal_artifact.signal_artifact_id
            state["portfolio_intent_id"] = strategy_result.portfolio_intent.portfolio_intent_id
            completed.append("STRATEGY")
        except Exception as error:
            return self._failure(
                ResearchPipelineStatus.STRATEGY_FAILED, completed, state, request, error
            )

        try:
            target = self._portfolio.construct_and_publish(
                project_id=request.project_id,
                project_context_revision_id=request.project_context_revision_id,
                intent=strategy_result.portfolio_intent,
                definition=request.strategy_request.definition,
                binding=request.strategy_request.binding,
                construction_spec=request.construction_spec,
                runtime_identity=request.runtime_identity,
                base_currency=request.base_currency,
                as_of=request.as_of,
                decision_time=request.decision_time,
                rebalance_time=request.rebalance_time,
                valid_until=request.valid_until,
                published_at=request.published_at,
                optimizer_candidate=request.optimizer_candidate,
            )
            state["target_weight_vector_id"] = (
                target.construction.target.target_weight_vector_id
            )
            completed.extend(("PORTFOLIO", "TARGET_WEIGHT"))
        except Exception as error:
            return self._failure(
                ResearchPipelineStatus.PORTFOLIO_FAILED, completed, state, request, error
            )

        try:
            risk_publication = self._risk.apply_and_publish(
                CanonicalRiskApplicationRequest(
                    project_id=request.project_id,
                    project_context_revision_id=request.project_context_revision_id,
                    source_target_weight_vector_id=target.construction.target.target_weight_vector_id,
                    risk_policy_set_version_id=request.risk_policy_set_version_id,
                    runtime_identity=request.runtime_identity,
                    context_identity=target.publication.context_identity,
                ),
                published_at=request.published_at,
            )
            state["risk_application_receipt_id"] = (
                risk_publication.risk_application_receipt_id
            )
            state["risk_adjusted_weight_vector_id"] = (
                risk_publication.risk_adjusted_weight_vector_id
            )
            adjusted = self._adjusted_weight_owner.require_adjusted_weight_vector(
                risk_publication.risk_adjusted_weight_vector_id
            )
            completed.extend(("RISK", "RISK_ADJUSTED_WEIGHT"))
        except Exception as error:
            return self._failure(
                ResearchPipelineStatus.RISK_FAILED, completed, state, request, error
            )

        try:
            backtest_spec = self._assembler.assemble(
                request=request,
                adjusted_weights=adjusted,
            )
            backtest_result = self._backtest.run(backtest_spec)
            state["backtest_result_id"] = backtest_result.result_id
            completed.append("BACKTEST")
        except Exception as error:
            return self._failure(
                ResearchPipelineStatus.BACKTEST_FAILED, completed, state, request, error
            )

        try:
            publication = self._publish_result(
                request=request,
                state=state,
                backtest_result=backtest_result,
            )
            state["run_id"] = publication["run_id"]
            state["run_receipt_id"] = publication["run_receipt_id"]
            completed.append("RESULT")
            return self._success(
                completed=completed,
                state=state,
                request=request,
                result_artifact_id=publication["artifact_id"],
                result_artifact_sha256=publication["artifact_sha256"],
            )
        except Exception as error:
            return self._failure(
                ResearchPipelineStatus.RESULT_PUBLICATION_FAILED,
                completed,
                state,
                request,
                error,
            )

    def _publish_result(
        self,
        *,
        request: ResearchPipelineRequest,
        state: dict[str, str | None],
        backtest_result: BacktestRunResult,
    ) -> dict[str, str]:
        profile = request.assumption_profile
        run_payload = {
            "service_version": self.service_version,
            "strategy_output_id": state["strategy_output_id"],
            "portfolio_intent_id": state["portfolio_intent_id"],
            "target_weight_vector_id": state["target_weight_vector_id"],
            "risk_application_receipt_id": state["risk_application_receipt_id"],
            "risk_adjusted_weight_vector_id": state["risk_adjusted_weight_vector_id"],
            "backtest_result_id": backtest_result.result_id,
            "backtest_result_sha256": backtest_result.content_sha256,
            "assumption_profile_identity": profile.identity,
            "truth_admission": PRE_ALPHA_CEILING.to_wire(),
        }
        run_id = "rprun_sha256_" + canonical_sha256(run_payload)
        receipt_payload = {"run_id": run_id, **run_payload}
        run_receipt_id = "rprc_sha256_" + canonical_sha256(receipt_payload)
        envelope = {
            "schema_version": RESEARCH_BACKTEST_RESULT_SCHEMA_VERSION,
            "research_classification": {
                "labels": list(profile.research_classification),
                "truth_admission": PRE_ALPHA_CEILING.to_wire(),
                "formal_market_truth": False,
            },
            "assumption_profile": profile.to_wire(),
            "run_receipt": {
                "run_receipt_id": run_receipt_id,
                **receipt_payload,
            },
            "backtest_result": backtest_result.to_wire(),
        }
        payload = canonical_json_bytes(envelope)
        stage = self._result_artifact_store.stage_bytes(payload)
        result = self._result_artifact_store.publish(
            stage.staging_token,
            expected_sha256=stage.sha256,
            expected_byte_size=stage.byte_size,
            media_type="application/json",
            role=RESEARCH_BACKTEST_RESULT_ROLE,
            provenance_entity_id=run_receipt_id,
            schema_fingerprint=RESEARCH_BACKTEST_RESULT_SCHEMA_FINGERPRINT,
            semantic_fingerprint=profile.identity,
            published_at=request.published_at,
        )
        observed = self._result_artifact_store.read_bytes(
            result.descriptor.artifact_id,
            max_bytes=len(payload),
        )
        if observed != payload:
            raise ResearchPipelineContractError(
                "published research result is not readable byte-for-byte"
            )
        return {
            "run_id": run_id,
            "run_receipt_id": run_receipt_id,
            "artifact_id": result.descriptor.artifact_id,
            "artifact_sha256": result.descriptor.sha256,
        }

    @staticmethod
    def _common(
        request: ResearchPipelineRequest,
        status: ResearchPipelineStatus,
        completed: list[str],
        state: dict[str, str | None],
        *,
        failed_stage: str | None,
        error: Exception | None,
        result_artifact_id: str | None,
        result_artifact_sha256: str | None,
        result_artifact_readable: bool,
    ) -> CoreResearchPipelineResult:
        truth = PRE_ALPHA_CEILING.to_wire()
        return CoreResearchPipelineResult(
            status=status,
            completed_stages=tuple(completed),
            failed_stage=failed_stage,
            error_type=None if error is None else type(error).__name__,
            error_message=None if error is None else str(error),
            run_id=state["run_id"],
            strategy_output_id=state["strategy_output_id"],
            portfolio_intent_id=state["portfolio_intent_id"],
            target_weight_vector_id=state["target_weight_vector_id"],
            risk_application_receipt_id=state["risk_application_receipt_id"],
            risk_adjusted_weight_vector_id=state["risk_adjusted_weight_vector_id"],
            backtest_result_id=state["backtest_result_id"],
            run_receipt_id=state["run_receipt_id"],
            result_artifact_id=result_artifact_id,
            result_artifact_sha256=result_artifact_sha256,
            result_artifact_readable=result_artifact_readable,
            assumption_profile_identity=request.assumption_profile.identity,
            assumption_profile_id=request.assumption_profile.profile_id,
            assumption_codes=request.assumption_profile.assumption_codes,
            research_classification=request.assumption_profile.research_classification,
            canonical_truth_state=truth["canonical_truth_state"],
            canonical_admission_state=truth["canonical_admission_state"],
        )

    def _failure(
        self,
        status: ResearchPipelineStatus,
        completed: list[str],
        state: dict[str, str | None],
        request: ResearchPipelineRequest,
        error: Exception,
    ) -> CoreResearchPipelineResult:
        return self._common(
            request,
            status,
            completed,
            state,
            failed_stage=status.value.removesuffix("_FAILED"),
            error=error,
            result_artifact_id=None,
            result_artifact_sha256=None,
            result_artifact_readable=False,
        )

    def _success(
        self,
        *,
        completed: list[str],
        state: dict[str, str | None],
        request: ResearchPipelineRequest,
        result_artifact_id: str,
        result_artifact_sha256: str,
    ) -> CoreResearchPipelineResult:
        return self._common(
            request,
            ResearchPipelineStatus.SUCCESS,
            completed,
            state,
            failed_stage=None,
            error=None,
            result_artifact_id=result_artifact_id,
            result_artifact_sha256=result_artifact_sha256,
            result_artifact_readable=True,
        )


__all__ = [
    "RESEARCH_ASSUMPTION_CODES",
    "RESEARCH_ASSUMPTION_PROFILE_ID",
    "RESEARCH_BACKTEST_RESULT_ROLE",
    "RESEARCH_BACKTEST_RESULT_SCHEMA_FINGERPRINT",
    "CoreResearchPipelineResult",
    "CoreResearchPipelineService",
    "ResearchBacktestAssembler",
    "ResearchBarObservation",
    "ResearchExecutionAssumptionProfile",
    "ResearchPipelineContractError",
    "ResearchPipelineRequest",
    "ResearchPipelineStatus",
    "ResearchSessionObservation",
]
