"""V1.1 bounded Strategy authoring over verified local Factor materializations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from v3_backend.adapters.sqlite.portfolio_risk_owner import SQLitePortfolioRiskPolicyOwner
from v3_backend.adapters.sqlite.risk_application import SQLiteRiskApplicationRepository
from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
from v3_backend.domain.backtest_runtime import (
    cn_a_share_2023_08_28_cost_policy,
    cn_a_share_2026_07_06_execution_timing_profile,
)
from v3_backend.domain.artifacts.exceptions import ArtifactError
from v3_backend.domain.datasets import (
    DatasetBinding,
    DatasetVersion,
    FeatureSetVersion,
    LabelSpec,
    SplitSpec,
)
from v3_backend.domain.factors import (
    DeterministicReferenceEvaluator,
    FactorDefinitionVersion,
    FactorEvaluation,
    FactorEvaluationContext,
    FeatureMaterialization,
    FeatureNode,
    UnresolvedIdUpstreamTruthBinding,
    default_operator_registry,
)
from v3_backend.domain.portfolio_construction import (
    CanonicalPortfolioOwnerService,
    ConstructionMethod,
    PortfolioConstructionSpecVersion,
)
from v3_backend.domain.risk_runtime import (
    CanonicalRiskApplicationRequest,
    CanonicalRiskApplicationService,
    CanonicalRiskPolicyAuthoringService,
    PassThroughPolicyInput,
    RiskPolicyDefinition,
    RiskPolicySetVersion,
)
from v3_backend.domain.strategies import (
    BindingInputRef,
    BindingSlot,
    BoundInputReference,
    CrossSectionInputArtifact,
    DeterministicStrategyEvaluator,
    EvaluationPeriod,
    ExactCalendarReference,
    ExactSnapshotReference,
    ExactUniverseReference,
    MissingSemantics,
    NodeOutputRef,
    PortCardinality,
    PortSpec,
    PortValueType,
    StrategyCompiler,
    StrategyDefinitionVersion,
    StrategyEvaluationBindingVersion,
    StrategyIr,
    StrategyNode,
    default_component_registry,
)
from v3_backend.domain.weights import RuntimeIdentity
from v3_backend.errors.exceptions import (
    ArtifactNotPublishedError,
    CapabilityUnavailableError,
    ConflictError,
    InvalidArgumentError,
    NotFoundError,
    TruthPreconditionFailedError,
)
from v3_backend.provenance.canonical_hash import canonical_json_bytes, canonical_sha256

from .product_factor import ProductFactorStudyService
from .product_runtime import (
    ProductRuntime,
    _accept_outcome_json,
    _canonical_request_hash,
    classify_execution_error,
    connect_catalog,
    mint_v3_id,
)


_READ_MODEL_SCHEMA = "v3.product-strategy-read-model/1.0.0"
_SPEC_SCHEMA = "v3.research-strategy-spec/1.0.0"
_STATE_SCHEMA = "v3.research-strategy-state-materialization/1.0.0"
_VALIDATION_SCHEMA = "v3.product-strategy-validation/1.0.0"
_FACTOR_MANIFEST_SCHEMA = "v3.factor-materialization-manifest/1.0.0"
_FACTOR_PARTITION_SCHEMA = "v3.factor-materialization-partition/1.0.0"
_SPEC_ROLE = "PRODUCT_RESEARCH_STRATEGY_SPEC"
_DEFINITION_ROLE = "PRODUCT_STRATEGY_DEFINITION"
_VALIDATION_ROLE = "PRODUCT_STRATEGY_VALIDATION"
_STATE_ROLE = "PRODUCT_STRATEGY_STATE_MATERIALIZATION"
_READ_MODEL_ROLE = "PRODUCT_STRATEGY_READ_MODEL"
_DECISION_INPUT_ROLE = "PRODUCT_STRATEGY_DECISION_INPUT"
_DATASET_ROLE = "PRODUCT_STRATEGY_DECISION_DATASET"
_SIGNAL_ROLE = "PRODUCT_STRATEGY_SIGNAL"
_SELECTION_ROLE = "PRODUCT_STRATEGY_SELECTION"
_INTENT_ROLE = "PRODUCT_STRATEGY_PORTFOLIO_INTENT"
_MAX_OWNER_BYTES = 8 * 1024 * 1024
_MAX_DECISIONS = 3_000
_MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")
_RUNTIME = RuntimeIdentity(
    code_version="v3-v1.1-product-strategy",
    runtime_profile_id="v3.product-strategy/1.0.0",
    environment_fingerprint="cpython-3.14-v3-product-strategy",
)
PRODUCT_STRATEGY_OPERATION = "ProductEntryService.v1.publishResearchStrategy"
_STRATEGY_CONTEXT_SCHEMA = "v3.product-strategy-context/1.1.0"


def _decimal(value: str, name: str, *, positive: bool = False) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise TruthPreconditionFailedError(f"{name} must be canonical decimal text")
    try:
        observed = Decimal(value)
    except InvalidOperation as error:
        raise TruthPreconditionFailedError(f"{name} must be canonical decimal text") from error
    if not observed.is_finite() or (positive and observed <= 0):
        raise TruthPreconditionFailedError(f"{name} is outside the admitted range")
    normalized = format(observed.normalize(), "f")
    if normalized == "-0":
        normalized = "0"
    return normalized


def _closed(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise TruthPreconditionFailedError(f"{label} shape is not closed")
    return value


_ASSUMPTION_MODES = ("RESEARCH_APPROXIMATE", "STRICT_FAIL_CLOSED")


def _assumption_profile_id(mode: str) -> str:
    if mode not in _ASSUMPTION_MODES:
        raise TruthPreconditionFailedError("assumption profile mode is not admitted")
    return "assumption_sha256_" + canonical_sha256(
        {
            "schema_version": "v3.research-assumption-profile/1.0.0",
            "profile": mode,
            "truth": "NOT_FORMAL",
            "admission": "PRE_ALPHA",
        }
    )


def _profile_values(
    assumption_mode: str = "RESEARCH_APPROXIMATE",
) -> dict[str, str]:
    cost = cn_a_share_2023_08_28_cost_policy(
        commission_rate="0.0003", minimum_commission="5"
    )
    timing = cn_a_share_2026_07_06_execution_timing_profile()
    policy = RiskPolicySetVersion.create(
        (
            RiskPolicyDefinition.pass_through(
                code_version=_RUNTIME.code_version,
                runtime_profile_id=_RUNTIME.runtime_profile_id,
            ),
        )
    )
    assumption_id = _assumption_profile_id(assumption_mode)
    return {
        "cost_policy_version_id": cost.policy_id,
        "execution_policy_version_id": timing.profile_id,
        "risk_policy_set_version_id": policy.risk_policy_set_version_id,
        "assumption_profile_id": assumption_id,
    }


@dataclass(frozen=True, slots=True)
class ResearchStrategySpecV1:
    research_strategy_spec_id: str
    universe_version_id: str
    entry_signal_factor_version_id: str
    exit_signal_factor_version_id: str
    position_sizing: str
    max_positions: int
    gross_exposure: str
    rebalance: str
    cost_policy_version_id: str
    execution_policy_version_id: str
    risk_policy_set_version_id: str
    initial_cash: str
    assumption_profile_id: str

    @classmethod
    def create(
        cls,
        *,
        universe_version_id: str,
        entry_signal_factor_version_id: str,
        exit_signal_factor_version_id: str,
        position_sizing: str,
        max_positions: int,
        gross_exposure: str,
        rebalance: str,
        cost_policy_version_id: str,
        execution_policy_version_id: str,
        risk_policy_set_version_id: str,
        initial_cash: str,
        assumption_profile_id: str,
    ) -> ResearchStrategySpecV1:
        for name, value, prefix in (
            ("universe_version_id", universe_version_id, "unv_"),
            ("entry_signal_factor_version_id", entry_signal_factor_version_id, "fdv_sha256_"),
            ("exit_signal_factor_version_id", exit_signal_factor_version_id, "fdv_sha256_"),
            ("cost_policy_version_id", cost_policy_version_id, "cost_sha256_"),
            ("execution_policy_version_id", execution_policy_version_id, "timing_sha256_"),
            ("risk_policy_set_version_id", risk_policy_set_version_id, "rpsv_sha256_"),
            ("assumption_profile_id", assumption_profile_id, "assumption_sha256_"),
        ):
            if not isinstance(value, str) or not value.startswith(prefix):
                raise TruthPreconditionFailedError(f"{name} is not canonical")
        if position_sizing not in {
            "SINGLE_ASSET_FULL_WEIGHT",
            "EQUAL_WEIGHT_ACTIVE_SIGNALS",
        }:
            raise TruthPreconditionFailedError("position_sizing is unsupported")
        if not isinstance(max_positions, int) or isinstance(max_positions, bool) or not 1 <= max_positions <= 20:
            raise TruthPreconditionFailedError("max_positions must be in 1..20")
        if position_sizing == "SINGLE_ASSET_FULL_WEIGHT" and max_positions != 1:
            raise TruthPreconditionFailedError("single-asset sizing requires max_positions=1")
        gross = _decimal(gross_exposure, "gross_exposure")
        if not Decimal(0) <= Decimal(gross) <= Decimal(1):
            raise TruthPreconditionFailedError("gross_exposure must be in 0..1")
        cash = _decimal(initial_cash, "initial_cash", positive=True)
        if rebalance != "NEXT_OPEN_AFTER_SIGNAL":
            raise TruthPreconditionFailedError("rebalance is unsupported")
        payload = {
            "schema_version": _SPEC_SCHEMA,
            "universe_version_id": universe_version_id,
            "entry_signal_factor_version_id": entry_signal_factor_version_id,
            "exit_signal_factor_version_id": exit_signal_factor_version_id,
            "position_sizing": position_sizing,
            "max_positions": max_positions,
            "gross_exposure": gross,
            "rebalance": rebalance,
            "cost_policy_version_id": cost_policy_version_id,
            "execution_policy_version_id": execution_policy_version_id,
            "risk_policy_set_version_id": risk_policy_set_version_id,
            "initial_cash": cash,
            "assumption_profile_id": assumption_profile_id,
        }
        return cls(
            research_strategy_spec_id="rssv_sha256_" + canonical_sha256(payload),
            universe_version_id=universe_version_id,
            entry_signal_factor_version_id=entry_signal_factor_version_id,
            exit_signal_factor_version_id=exit_signal_factor_version_id,
            position_sizing=position_sizing,
            max_positions=max_positions,
            gross_exposure=gross,
            rebalance=rebalance,
            cost_policy_version_id=cost_policy_version_id,
            execution_policy_version_id=execution_policy_version_id,
            risk_policy_set_version_id=risk_policy_set_version_id,
            initial_cash=cash,
            assumption_profile_id=assumption_profile_id,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "schema_version": _SPEC_SCHEMA,
            "research_strategy_spec_id": self.research_strategy_spec_id,
            "universe_version_id": self.universe_version_id,
            "entry_signal_factor_version_id": self.entry_signal_factor_version_id,
            "exit_signal_factor_version_id": self.exit_signal_factor_version_id,
            "position_sizing": self.position_sizing,
            "max_positions": self.max_positions,
            "gross_exposure": self.gross_exposure,
            "rebalance": self.rebalance,
            "cost_policy_version_id": self.cost_policy_version_id,
            "execution_policy_version_id": self.execution_policy_version_id,
            "risk_policy_set_version_id": self.risk_policy_set_version_id,
            "initial_cash": self.initial_cash,
            "assumption_profile_id": self.assumption_profile_id,
        }


@dataclass(frozen=True, slots=True)
class _FactorRows:
    reference: dict[str, str]
    rows: Mapping[tuple[date, str], bool | None]


@dataclass(frozen=True, slots=True)
class _OwnerContext:
    snapshot_id: str
    snapshot_sha256: str
    universe_version_id: str
    universe_definition_sha256: str
    membership_artifact_id: str
    membership_sha256: str
    instrument_ids: tuple[str, ...]
    calendar_version_id: str
    calendar_sha256: str
    session_dates: tuple[date, ...]


def _score_port() -> PortSpec:
    return PortSpec(
        value_type=PortValueType.SCORE_MAP,
        cardinality=PortCardinality.CROSS_SECTION,
        time_basis="BOUND_DECISION_TIME",
        universe_basis="BOUND_UNIVERSE_MEMBERSHIP",
        missing_semantics=MissingSemantics.EXPLICIT,
    )


def _strategy_definition(spec: ResearchStrategySpecV1) -> StrategyDefinitionVersion:
    nodes = (
        StrategyNode(
            "input.state",
            "v3.strategy.input.bound_scores",
            "1.0.0",
            {"artifact": BindingInputRef("scores")},
            {},
            {},
        ),
        StrategyNode(
            "gate.active",
            "v3.strategy.condition.minimum",
            "1.0.0",
            {"scores": NodeOutputRef("input.state", "scores")},
            {"threshold": "0", "inclusive": False},
            {},
        ),
        StrategyNode(
            "rank.active",
            "v3.strategy.rank.score",
            "1.0.0",
            {
                "scores": NodeOutputRef("input.state", "scores"),
                "eligible": NodeOutputRef("gate.active", "eligible"),
            },
            {"descending": True, "missing_policy": "EXCLUDE"},
            {},
        ),
        StrategyNode(
            "select.active",
            "v3.strategy.select.top_n",
            "1.0.0",
            {"ranked": NodeOutputRef("rank.active", "ranked")},
            {"count": spec.max_positions},
            {},
        ),
        StrategyNode(
            "output.signal",
            "v3.strategy.output.signal",
            "1.0.0",
            {"scores": NodeOutputRef("input.state", "scores")},
            {"signal_kind": "DIRECTIONAL_SCORE"},
            {},
        ),
        StrategyNode(
            "output.selection",
            "v3.strategy.output.selection",
            "1.0.0",
            {"selection": NodeOutputRef("select.active", "selection")},
            {},
            {},
        ),
        StrategyNode(
            "output.intent",
            "v3.strategy.output.portfolio_intent",
            "1.0.0",
            {
                "scores": NodeOutputRef("input.state", "scores"),
                "selection": NodeOutputRef("select.active", "selection"),
            },
            {
                "gross_exposure": spec.gross_exposure,
                "exposure_mode": "ABSOLUTE_DESIRED_EXPOSURE",
                "cash_policy": "RESIDUAL",
                "rebalance_intent": "AT_BOUND_DECISION_TIME",
            },
            {},
        ),
    )
    ir = StrategyIr(
        required_bindings=(BindingSlot("scores", "FEATURE_MATERIALIZATION", _score_port()),),
        nodes=nodes,
        outputs={
            "signal": NodeOutputRef("output.signal", "artifact"),
            "selection": NodeOutputRef("output.selection", "artifact"),
            "portfolio_intent": NodeOutputRef("output.intent", "artifact"),
        },
        projection_metadata={"product_surface": "V1_1_BOUNDED_FORM"},
    )
    return StrategyCompiler(default_component_registry()).compile(ir)


class ProductStrategyService:
    """Product Strategy owner; numeric truth remains in existing canonical owners."""

    def __init__(self, product: ProductRuntime) -> None:
        self.product = product

    @staticmethod
    def bounded_profile_ids() -> dict[str, str]:
        return _profile_values()

    @staticmethod
    def bounded_assumption_profiles() -> tuple[dict[str, str], ...]:
        return tuple(
            {
                "mode": mode,
                "assumption_profile_id": _assumption_profile_id(mode),
            }
            for mode in _ASSUMPTION_MODES
        )

    @staticmethod
    def assumption_mode(assumption_profile_id: str) -> str:
        for item in ProductStrategyService.bounded_assumption_profiles():
            if item["assumption_profile_id"] == assumption_profile_id:
                return item["mode"]
        raise TruthPreconditionFailedError("assumption profile identity is not admitted")

    @classmethod
    def bounded_authoring_profile(cls) -> dict[str, Any]:
        """Return the closed product choices plus backend-owned canonical refs."""
        return {
            "schema_version": "v3.product-strategy-authoring-profile/1.0.0",
            "truth": "NOT_FORMAL",
            "admission": "PRE_ALPHA",
            "position_sizing_options": [
                "SINGLE_ASSET_FULL_WEIGHT",
                "EQUAL_WEIGHT_ACTIVE_SIGNALS",
            ],
            "max_positions_min": 1,
            "max_positions_max": 20,
            "gross_exposure_min": "0",
            "gross_exposure_max": "1",
            "rebalance": "NEXT_OPEN_AFTER_SIGNAL",
            "profile_refs": cls.bounded_profile_ids(),
            "assumption_profiles": list(cls.bounded_assumption_profiles()),
        }

    def _prepare_submission(
        self,
        submission: ProductStrategySubmission,
    ) -> _PreparedStrategyRequest:
        context = self.product.require_project_context_ownership(
            submission.project_id,
            submission.project_context_revision_id,
        )
        current = self.product.current_revision(submission.project_id)
        if current["project_context_revision_id"] != context["project_context_revision_id"]:
            raise ConflictError(
                "Strategy authoring requires the current project context revision"
            )
        if (
            not isinstance(submission.idempotency_key, str)
            or not submission.idempotency_key.strip()
        ):
            raise InvalidArgumentError("idempotency_key is required")
        spec = ResearchStrategySpecV1.create(
            universe_version_id=submission.universe_version_id,
            entry_signal_factor_version_id=submission.entry_signal_factor_version_id,
            exit_signal_factor_version_id=submission.exit_signal_factor_version_id,
            position_sizing=submission.position_sizing,
            max_positions=submission.max_positions,
            gross_exposure=submission.gross_exposure,
            rebalance=submission.rebalance,
            cost_policy_version_id=submission.cost_policy_version_id,
            execution_policy_version_id=submission.execution_policy_version_id,
            risk_policy_set_version_id=submission.risk_policy_set_version_id,
            initial_cash=submission.initial_cash,
            assumption_profile_id=submission.assumption_profile_id,
        )
        if context.get("universe_version_id") != spec.universe_version_id:
            raise TruthPreconditionFailedError(
                "Strategy Universe is not the exact current context"
            )
        semantic = {
            "project_id": submission.project_id,
            "project_context_revision_id": submission.project_context_revision_id,
            "spec": spec.to_wire(),
        }
        request_hash = _canonical_request_hash(PRODUCT_STRATEGY_OPERATION, semantic)
        return _PreparedStrategyRequest(
            project_id=submission.project_id,
            project_context_revision_id=submission.project_context_revision_id,
            spec=spec,
            semantic=semantic,
            request_hash=request_hash,
            scope=self.product.idempotency.scope_key(
                PRODUCT_STRATEGY_OPERATION,
                submission.project_id,
                submission.idempotency_key,
            ),
            execution_deadline_at=submission.execution_deadline_at,
        )

    def preview(self, submission: ProductStrategySubmission) -> dict[str, Any]:
        """Resolve and compile exact owner inputs without publishing or creating a Task."""
        request = self._prepare_submission(submission)
        owner = self._owner_context(
            project_id=request.project_id,
            project_context_revision_id=request.project_context_revision_id,
        )
        entry = self._factor_rows(
            project_id=request.project_id,
            project_context_revision_id=request.project_context_revision_id,
            owner=owner,
            factor_definition_version_id=request.spec.entry_signal_factor_version_id,
        )
        exit_signal = self._factor_rows(
            project_id=request.project_id,
            project_context_revision_id=request.project_context_revision_id,
            owner=owner,
            factor_definition_version_id=request.spec.exit_signal_factor_version_id,
        )
        _state_wire, transitions = self._reduce_state(
            request.spec, owner, entry, exit_signal
        )
        if len(transitions) > _MAX_DECISIONS:
            raise TruthPreconditionFailedError(
                "Strategy decisions exceed the admitted bound"
            )
        definition = _strategy_definition(request.spec)
        profiles = {
            **self.bounded_profile_ids(),
            "assumption_profile_id": request.spec.assumption_profile_id,
        }
        return {
            "schema_version": "v3.product-strategy-preview/1.0.0",
            "maturity": "PRODUCT_CONNECTED",
            "truth": "NOT_FORMAL",
            "admission": "PRE_ALPHA",
            "project_id": request.project_id,
            "project_context_revision_id": request.project_context_revision_id,
            "snapshot_id": owner.snapshot_id,
            "universe_version_id": owner.universe_version_id,
            "research_strategy_spec_id": request.spec.research_strategy_spec_id,
            "strategy_definition_version_id": definition.strategy_definition_version_id,
            "entry_signal_factor_version_id": request.spec.entry_signal_factor_version_id,
            "exit_signal_factor_version_id": request.spec.exit_signal_factor_version_id,
            "profile_refs": profiles,
            "assumption_mode": self.assumption_mode(request.spec.assumption_profile_id),
            "transition_count": len(transitions),
            "planned_decision_chain_count": len(transitions),
            "side_effects": "NONE",
        }

    @staticmethod
    def _accepted_outcome(
        task_id: str,
        run_id: str,
        request: _PreparedStrategyRequest,
        *,
        event_cursor: int | None = None,
    ) -> dict[str, Any]:
        outcome: dict[str, Any] = {
            "task_id": task_id,
            "run_id": run_id,
            "accepted_state": "QUEUED",
            "maturity": "PRODUCT_CONNECTED",
            "truth": "NOT_FORMAL",
            "admission": "PRE_ALPHA",
            "checkpoint_resume": "UNAVAILABLE",
            "retry": "NEW_ATTEMPT_SAME_RUN_FROM_START",
            "research_strategy_spec_id": request.spec.research_strategy_spec_id,
        }
        if event_cursor is not None:
            outcome["event_cursor"] = event_cursor
        return outcome

    def _accept_request(
        self,
        request: _PreparedStrategyRequest,
    ) -> _StrategyTaskHandles:
        context_artifact_id = self.product.execution._persist_context_artifact(
            {
                "schema_version": _STRATEGY_CONTEXT_SCHEMA,
                "context_kind": "PRODUCT_RESEARCH_STRATEGY",
                **request.semantic,
                "truth": "NOT_FORMAL",
                "admission": "PRE_ALPHA",
                "execution_state": "QUEUED_BEFORE_STRATEGY_PUBLICATION",
            },
            provenance="prv_product_strategy_intent_" + request.request_hash,
        )
        return _StrategyTaskHandles(
            *self.product.execution._create_task(
                operation_id=PRODUCT_STRATEGY_OPERATION,
                project_id=request.project_id,
                project_context_revision_id=request.project_context_revision_id,
                normalized_input_hash=canonical_sha256(request.semantic),
                context_artifact_id=context_artifact_id,
                idempotency=(request.scope, request.request_hash, _accept_outcome_json),
                execution_deadline_at=request.execution_deadline_at,
                inline_worker=False,
                service_contract_version="1.1.0",
            )
        )

    def submit(self, submission: ProductStrategySubmission) -> dict[str, Any]:
        request = self._prepare_submission(submission)
        existing = self.product.idempotency.lookup(
            self.product,
            request.scope,
            request.request_hash,
        )
        if existing is not None:
            return self._accepted_outcome(
                str(existing["task_id"]),
                str(existing["run_id"]),
                request,
            )
        workers = getattr(self.product, "product_workers", None)
        if workers is None:
            raise CapabilityUnavailableError(
                "isolated Product worker is unavailable for Strategy authoring",
                details={"reason_code": "PRODUCT_WORKER_NOT_AVAILABLE"},
            )
        reservation = workers.reserve_capacity()
        handles: _StrategyTaskHandles | None = None
        try:
            handles = self._accept_request(request)
            workers.start(
                request,
                handles,
                reservation_token=reservation,
                operation_id=PRODUCT_STRATEGY_OPERATION,
                work_kind="STRATEGY_AUTHORING",
                resource_class="PRODUCT_STRATEGY_CPU",
            )
        except Exception as error:
            workers.release_capacity(reservation)
            if handles is not None:
                self.product.execution._finish_failure(
                    handles.task,
                    handles.run,
                    handles.attempt,
                    error=error,
                    category=classify_execution_error(error),
                )
            raise
        return self._accepted_outcome(
            handles.task.task_id,
            handles.run.run_id,
            request,
            event_cursor=self.product.latest_event_sequence(request.project_id),
        )

    def execute_accepted(
        self,
        request: _PreparedStrategyRequest,
        handles: _StrategyTaskHandles,
    ) -> dict[str, Any]:
        try:
            read_model = self.publish_strategy(
                project_id=request.project_id,
                project_context_revision_id=request.project_context_revision_id,
                spec=request.spec,
            )
            if (
                read_model["research_strategy_spec_id"]
                != request.spec.research_strategy_spec_id
            ):
                raise TruthPreconditionFailedError(
                    "queued ResearchStrategySpec identity drifted"
                )
            self.product.execution._finish_success(
                handles.task,
                handles.run,
                handles.attempt,
                outputs={
                    "research_strategy_spec_id": read_model[
                        "research_strategy_spec_id"
                    ],
                    "strategy_definition_version_id": read_model[
                        "strategy_definition_version_id"
                    ],
                    "state_materialization_id": read_model[
                        "state_materialization_id"
                    ],
                },
            )
            return read_model
        except Exception as error:
            self.product.execution._finish_failure(
                handles.task,
                handles.run,
                handles.attempt,
                error=error,
                category=classify_execution_error(error),
            )
            raise

    def publish_strategy(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        spec: ResearchStrategySpecV1,
    ) -> dict[str, Any]:
        if not isinstance(spec, ResearchStrategySpecV1):
            raise TypeError("spec must be ResearchStrategySpecV1")
        self.product.require_project(project_id)
        context = self.product.require_project_context_ownership(
            project_id, project_context_revision_id
        )
        if context.get("universe_version_id") != spec.universe_version_id:
            raise TruthPreconditionFailedError("Strategy Universe is not the exact current context")
        profiles = {
            **self.bounded_profile_ids(),
            "assumption_profile_id": spec.assumption_profile_id,
        }
        fixed_profiles = {
            key: value
            for key, value in profiles.items()
            if key != "assumption_profile_id"
        }
        if any(
            getattr(spec, key) != value for key, value in fixed_profiles.items()
        ) or spec.assumption_profile_id not in {
            item["assumption_profile_id"]
            for item in self.bounded_assumption_profiles()
        }:
            raise TruthPreconditionFailedError("Strategy profile identity is not admitted")
        owner = self._owner_context(
            project_id=project_id,
            project_context_revision_id=project_context_revision_id,
        )
        entry = self._factor_rows(
            project_id=project_id,
            project_context_revision_id=project_context_revision_id,
            owner=owner,
            factor_definition_version_id=spec.entry_signal_factor_version_id,
        )
        exit_signal = self._factor_rows(
            project_id=project_id,
            project_context_revision_id=project_context_revision_id,
            owner=owner,
            factor_definition_version_id=spec.exit_signal_factor_version_id,
        )
        state_wire, transitions = self._reduce_state(spec, owner, entry, exit_signal)
        if len(transitions) > _MAX_DECISIONS:
            raise TruthPreconditionFailedError("Strategy decisions exceed the admitted bound")
        state_id = "rsm_sha256_" + canonical_sha256(state_wire)
        state_descriptor = self._publish_json(
            project_id, _STATE_ROLE, _STATE_SCHEMA, state_id, {"state_materialization_id": state_id, **state_wire}
        )
        definition = _strategy_definition(spec)
        definition_descriptor = self._publish_json(
            project_id,
            _DEFINITION_ROLE,
            "v3.strategy-definition-version/1.0.0",
            definition.strategy_definition_version_id,
            {
                "schema_version": "v3.strategy-definition-version/1.0.0",
                **definition.to_wire(),
            },
        )
        strategy_version_id, validation_descriptor = self._publish_strategy_version(
            project_id=project_id,
            definition=definition,
            definition_artifact_id=definition_descriptor.artifact_id,
            published_at=datetime.now(timezone.utc),
        )
        spec_descriptor = self._publish_json(
            project_id, _SPEC_ROLE, _SPEC_SCHEMA, spec.research_strategy_spec_id, spec.to_wire()
        )
        policy_owner = SQLitePortfolioRiskPolicyOwner(
            self.product.database_path, self.product.artifact_root
        )
        published_at = datetime.now(timezone.utc)
        policy_result = CanonicalRiskPolicyAuthoringService(policy_owner).author_and_publish(
            project_id=project_id,
            project_context_revision_id=project_context_revision_id,
            definitions=(PassThroughPolicyInput(),),
            runtime_identity=_RUNTIME,
            published_at=published_at,
        )
        if policy_result.policy_set.risk_policy_set_version_id != spec.risk_policy_set_version_id:
            raise TruthPreconditionFailedError("authored RiskPolicy identity drifted")

        chains = tuple(
            self._decision_chain(
                project_id=project_id,
                project_context_revision_id=project_context_revision_id,
                owner=owner,
                definition=definition,
                transition=transition,
                policy_owner=policy_owner,
                risk_policy_set_version_id=spec.risk_policy_set_version_id,
                gross_exposure=spec.gross_exposure,
                published_at=published_at,
                state_provenance_artifact_id=state_descriptor.artifact_id,
            )
            for transition in transitions
        )
        read_model: dict[str, Any] = {
            "schema_version": _READ_MODEL_SCHEMA,
            "truth": "NOT_FORMAL",
            "admission": "PRE_ALPHA",
            "project_id": project_id,
            "project_context_revision_id": project_context_revision_id,
            "snapshot_id": owner.snapshot_id,
            "universe_version_id": owner.universe_version_id,
            "research_strategy_spec_id": spec.research_strategy_spec_id,
            "research_strategy_spec_artifact_id": spec_descriptor.artifact_id,
            "strategy_version_id": strategy_version_id,
            "strategy_definition_version_id": definition.strategy_definition_version_id,
            "strategy_definition_artifact_id": definition_descriptor.artifact_id,
            "strategy_validation_artifact_id": validation_descriptor.artifact_id,
            "state_materialization_id": state_id,
            "state_materialization_artifact_id": state_descriptor.artifact_id,
            "entry_signal_ref": entry.reference,
            "exit_signal_ref": exit_signal.reference,
            "profile_refs": profiles,
            "transition_count": len(transitions),
            "decision_chain_count": len(chains),
            "decision_chain_id_prefixes": [
                "pint_sha256_", "rar_sha256_", "rawv_sha256_", "sel_sha256_", "sig_sha256_", "twv_sha256_"
            ],
            "decision_chains": list(chains),
        }
        self._publish_json(
            project_id,
            _READ_MODEL_ROLE,
            _READ_MODEL_SCHEMA,
            spec.research_strategy_spec_id,
            read_model,
        )
        return json.loads(json.dumps(read_model, ensure_ascii=False, allow_nan=False))

    def get_strategy(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        research_strategy_spec_id: str,
    ) -> dict[str, Any]:
        self.product.require_project_context_ownership(project_id, project_context_revision_id)
        connection = connect_catalog(self.product.database_path, read_only=True)
        try:
            rows = connection.execute(
                """
                SELECT a.artifact_id,a.byte_size FROM artifact AS a
                JOIN artifact_reference AS r ON r.artifact_id=a.artifact_id
                WHERE r.owner_type='Project' AND r.owner_id=? AND r.role=?
                  AND r.state='ACTIVE' AND a.state='PUBLISHED'
                ORDER BY r.created_at DESC,r.artifact_reference_id DESC
                """,
                (project_id, _READ_MODEL_ROLE),
            ).fetchall()
        finally:
            connection.close()
        for artifact_id, byte_size in rows:
            if int(byte_size) > _MAX_OWNER_BYTES:
                raise TruthPreconditionFailedError("Strategy read model exceeds its bound")
            try:
                value = json.loads(self.product.read_verified_bytes(str(artifact_id)).decode("utf-8"))
            except (
                ArtifactNotPublishedError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                OSError,
                ValueError,
            ) as error:
                raise TruthPreconditionFailedError("Strategy read-model bytes are invalid") from error
            if (
                isinstance(value, dict)
                and value.get("project_id") == project_id
                and value.get("project_context_revision_id") == project_context_revision_id
                and value.get("research_strategy_spec_id") == research_strategy_spec_id
            ):
                self._verify_read_model(value)
                owner = self._owner_context(
                    project_id=project_id,
                    project_context_revision_id=project_context_revision_id,
                )
                for key in ("entry_signal_ref", "exit_signal_ref"):
                    reference = value.get(key)
                    if not isinstance(reference, dict):
                        raise TruthPreconditionFailedError(
                            "Strategy Factor reference is invalid"
                        )
                    factor_definition_version_id = reference.get(
                        "factor_definition_version_id"
                    )
                    if not isinstance(factor_definition_version_id, str):
                        raise TruthPreconditionFailedError(
                            "Strategy FactorVersion identity is invalid"
                        )
                    resolved = self._factor_rows(
                        project_id=project_id,
                        project_context_revision_id=project_context_revision_id,
                        owner=owner,
                        factor_definition_version_id=factor_definition_version_id,
                    )
                    if resolved.reference != reference:
                        raise TruthPreconditionFailedError(
                            "Strategy Factor reference binding drifted"
                        )
                return value
        raise NotFoundError("Product Strategy read model is unavailable")

    def get_latest_strategy(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
    ) -> dict[str, Any]:
        """Return the newest Strategy only after the normal owner readback passes."""
        self.product.require_project_context_ownership(
            project_id, project_context_revision_id
        )
        connection = connect_catalog(self.product.database_path, read_only=True)
        try:
            row = connection.execute(
                """
                SELECT a.artifact_id,a.byte_size FROM artifact AS a
                JOIN artifact_reference AS r ON r.artifact_id=a.artifact_id
                WHERE r.owner_type='Project' AND r.owner_id=? AND r.role=?
                  AND r.state='ACTIVE' AND a.state='PUBLISHED'
                ORDER BY r.created_at DESC,r.artifact_reference_id DESC
                LIMIT 1
                """,
                (project_id, _READ_MODEL_ROLE),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise NotFoundError("Product Strategy read model is unavailable")
        if int(row[1]) > _MAX_OWNER_BYTES:
            raise TruthPreconditionFailedError("Strategy read model exceeds its bound")
        try:
            candidate = json.loads(
                self.product.read_verified_bytes(str(row[0])).decode("utf-8")
            )
        except (
            ArtifactNotPublishedError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            OSError,
            ValueError,
        ) as error:
            raise TruthPreconditionFailedError(
                "Strategy read-model bytes are invalid"
            ) from error
        strategy_id = candidate.get("research_strategy_spec_id") if isinstance(candidate, dict) else None
        if not isinstance(strategy_id, str):
            raise TruthPreconditionFailedError("Strategy read-model identity is invalid")
        return self.get_strategy(
            project_id=project_id,
            project_context_revision_id=project_context_revision_id,
            research_strategy_spec_id=strategy_id,
        )

    def _owner_context(
        self, *, project_id: str, project_context_revision_id: str
    ) -> _OwnerContext:
        context = self.product.require_project_context_ownership(
            project_id, project_context_revision_id
        )
        snapshot_id = context.get("snapshot_id")
        universe_id = context.get("universe_version_id")
        if not isinstance(snapshot_id, str) or not isinstance(universe_id, str):
            raise TruthPreconditionFailedError("Project context lacks Snapshot/Universe")
        connection = connect_catalog(self.product.database_path, read_only=True)
        try:
            row = connection.execute(
                """
                SELECT s.content_hash,d.canonical_hash,u.membership_artifact_id,
                       c.calendar_version_id,c.content_hash
                FROM data_snapshot AS s
                JOIN universe_version AS u ON u.snapshot_id=s.snapshot_id
                JOIN universe_definition AS d ON d.universe_definition_id=u.universe_definition_id
                JOIN snapshot_calendar AS sc ON sc.snapshot_id=s.snapshot_id
                JOIN trading_calendar_version AS c ON c.calendar_version_id=sc.calendar_version_id
                WHERE s.snapshot_id=? AND u.universe_version_id=? AND d.project_id=?
                  AND s.state='PUBLISHED' AND u.state='PUBLISHED'
                """,
                (snapshot_id, universe_id, project_id),
            ).fetchone()
            sessions = connection.execute(
                """SELECT session_date FROM trading_session
                   WHERE calendar_version_id=? AND is_trading_day=1 ORDER BY session_ordinal""",
                (() if row is None else (str(row[3]),)),
            ).fetchall() if row is not None else ()
        finally:
            connection.close()
        if row is None or not sessions:
            raise TruthPreconditionFailedError("Strategy owner context is unavailable")
        membership_id = str(row[2])
        membership = json.loads(self.product.read_verified_bytes(membership_id).decode("utf-8"))
        membership = _closed(
            membership,
            {"schema_version", "snapshot_id", "role", "instrument_ids"},
            "Universe membership",
        )
        ids = membership["instrument_ids"]
        if not isinstance(ids, list) or not ids or any(not isinstance(value, str) for value in ids):
            raise TruthPreconditionFailedError("Universe membership is invalid")
        return _OwnerContext(
            snapshot_id=snapshot_id,
            snapshot_sha256=str(row[0]),
            universe_version_id=universe_id,
            universe_definition_sha256=str(row[1]),
            membership_artifact_id=membership_id,
            membership_sha256=membership_id.removeprefix("art_sha256_"),
            instrument_ids=tuple(sorted(ids)),
            calendar_version_id=str(row[3]),
            calendar_sha256=str(row[4]),
            session_dates=tuple(date.fromisoformat(str(value[0])) for value in sessions),
        )

    def _factor_rows(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        owner: _OwnerContext,
        factor_definition_version_id: str,
    ) -> _FactorRows:
        study = ProductFactorStudyService(self.product).get_latest_factor_study(
            project_id=project_id,
            project_context_revision_id=project_context_revision_id,
            snapshot_id=owner.snapshot_id,
            factor_definition_version_id=factor_definition_version_id,
        )
        matches = [value for value in study["outputs"].values() if value["factor_definition_version_id"] == factor_definition_version_id]
        if len(matches) != 1:
            raise TruthPreconditionFailedError("boolean FactorVersion is not in the exact study")
        output = matches[0]
        if output["output_type"] != "BOOLEAN_SERIES":
            raise TruthPreconditionFailedError("entry/exit FactorVersion must be BOOLEAN_SERIES")
        try:
            raw_manifest = self.product.read_verified_bytes(
                str(output["materialization_artifact_id"])
            )
        except (ArtifactError, ArtifactNotPublishedError, OSError, ValueError) as error:
            raise TruthPreconditionFailedError(
                "Factor materialization manifest bytes are unavailable"
            ) from error
        if len(raw_manifest) > _MAX_OWNER_BYTES:
            raise TruthPreconditionFailedError("Factor materialization manifest exceeds its bound")
        manifest = _closed(
            json.loads(raw_manifest.decode("utf-8")),
            {
                "materialization_id", "schema_version", "snapshot_id", "universe_version_id",
                "factor_definition_version_id", "evaluator_version", "output_type", "row_count", "partitions",
            },
            "Factor materialization manifest",
        )
        if (
            manifest["schema_version"] != _FACTOR_MANIFEST_SCHEMA
            or manifest["snapshot_id"] != owner.snapshot_id
            or manifest["universe_version_id"] != owner.universe_version_id
            or manifest["factor_definition_version_id"] != factor_definition_version_id
            or manifest["materialization_id"] != output["materialization_id"]
            or manifest["output_type"] != "BOOLEAN_SERIES"
            or not isinstance(manifest["partitions"], list)
        ):
            raise TruthPreconditionFailedError("Factor materialization binding drifted")
        resolved: dict[tuple[date, str], bool | None] = {}
        for expected_ordinal, raw_part in enumerate(manifest["partitions"]):
            part = _closed(
                raw_part,
                {"partition_key", "artifact_id", "sha256", "byte_size", "row_count", "min_session_date", "max_session_date"},
                "Factor partition descriptor",
            )
            if part["partition_key"] != f"{expected_ordinal:08d}" or part["artifact_id"] != "art_sha256_" + str(part["sha256"]):
                raise TruthPreconditionFailedError("Factor partition identity drifted")
            try:
                raw = self.product.read_verified_bytes(str(part["artifact_id"]))
            except (ArtifactError, ArtifactNotPublishedError, OSError, ValueError) as error:
                raise TruthPreconditionFailedError(
                    "Factor partition bytes are unavailable"
                ) from error
            if len(raw) != part["byte_size"] or len(raw) > _MAX_OWNER_BYTES:
                raise TruthPreconditionFailedError("Factor partition byte size drifted")
            payload = _closed(
                json.loads(raw.decode("utf-8")),
                {"schema_version", "snapshot_id", "universe_version_id", "factor_definition_version_id", "partition_key", "rows"},
                "Factor partition",
            )
            if (
                payload["schema_version"] != _FACTOR_PARTITION_SCHEMA
                or payload["snapshot_id"] != owner.snapshot_id
                or payload["universe_version_id"] != owner.universe_version_id
                or payload["factor_definition_version_id"] != factor_definition_version_id
                or payload["partition_key"] != part["partition_key"]
                or not isinstance(payload["rows"], list)
                or len(payload["rows"]) != part["row_count"]
            ):
                raise TruthPreconditionFailedError("Factor partition binding drifted")
            for raw_row in payload["rows"]:
                row = _closed(
                    raw_row,
                    {"session_date", "instrument_id", "value", "missing_reason", "source_partition_artifact_id", "source_partition_sha256"},
                    "Factor value row",
                )
                value = row["value"]
                if value is not None and not isinstance(value, bool):
                    raise TruthPreconditionFailedError("boolean Factor contains a non-boolean value")
                key = (date.fromisoformat(str(row["session_date"])), str(row["instrument_id"]))
                if key in resolved or key[1] not in owner.instrument_ids:
                    raise TruthPreconditionFailedError("Factor row key is duplicate or outside Universe")
                resolved[key] = value
        expected_keys = {(session, instrument) for session in owner.session_dates for instrument in owner.instrument_ids}
        if set(resolved) != expected_keys or len(resolved) != manifest["row_count"]:
            raise TruthPreconditionFailedError("Factor rows do not cover the exact calendar/Universe")
        return _FactorRows(
            reference={
                "factor_definition_version_id": factor_definition_version_id,
                "materialization_id": str(output["materialization_id"]),
                "materialization_artifact_id": str(output["materialization_artifact_id"]),
            },
            rows=resolved,
        )

    @staticmethod
    def _reduce_state(
        spec: ResearchStrategySpecV1,
        owner: _OwnerContext,
        entry: _FactorRows,
        exit_signal: _FactorRows,
    ) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
        active = {instrument: False for instrument in owner.instrument_ids}
        rows: list[dict[str, Any]] = []
        transitions: list[dict[str, Any]] = []
        for session_index, session in enumerate(owner.session_dates):
            changed = False
            for instrument in owner.instrument_ids:
                before = active[instrument]
                enter = entry.rows[(session, instrument)]
                leave = exit_signal.rows[(session, instrument)]
                if enter is True and leave is True:
                    raise TruthPreconditionFailedError("entry and exit cannot both be true")
                diagnostic = "NO_SIGNAL"
                if enter is None or leave is None:
                    diagnostic = "MISSING_SIGNAL_NO_ACTION"
                elif enter and before:
                    diagnostic = "REPEATED_ENTRY_NO_OP"
                elif leave and not before:
                    diagnostic = "REPEATED_EXIT_NO_OP"
                elif enter:
                    active[instrument] = True
                    changed = True
                    diagnostic = "ENTER_LONG"
                elif leave:
                    active[instrument] = False
                    changed = True
                    diagnostic = "EXIT_LONG"
                rows.append(
                    {
                        "session_date": session.isoformat(),
                        "instrument_id": instrument,
                        "previous_active": before,
                        "entry_signal": enter,
                        "exit_signal": leave,
                        "next_active": active[instrument],
                        "diagnostic": diagnostic,
                    }
                )
            if changed:
                if session_index + 1 >= len(owner.session_dates):
                    rows.append(
                        {
                            "session_date": session.isoformat(),
                            "instrument_id": "__PORTFOLIO__",
                            "previous_active": None,
                            "entry_signal": None,
                            "exit_signal": None,
                            "next_active": None,
                            "diagnostic": "NO_NEXT_ADMITTED_OPEN",
                        }
                    )
                    continue
                transitions.append(
                    {
                        "decision_date": session,
                        "effective_date": owner.session_dates[session_index + 1],
                        "active": tuple(instrument for instrument in owner.instrument_ids if active[instrument]),
                    }
                )
        wire = {
            "schema_version": _STATE_SCHEMA,
            "research_strategy_spec_id": spec.research_strategy_spec_id,
            "snapshot_id": owner.snapshot_id,
            "universe_version_id": owner.universe_version_id,
            "entry_signal_ref": entry.reference,
            "exit_signal_ref": exit_signal.reference,
            "missing_policy": "MISSING_SIGNAL_NO_ACTION",
            "rows": rows,
        }
        return wire, tuple(transitions)

    def _decision_chain(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        owner: _OwnerContext,
        definition: StrategyDefinitionVersion,
        transition: Mapping[str, Any],
        policy_owner: SQLitePortfolioRiskPolicyOwner,
        risk_policy_set_version_id: str,
        gross_exposure: str,
        published_at: datetime,
        state_provenance_artifact_id: str,
    ) -> dict[str, str]:
        decision_date = transition["decision_date"]
        effective_date = transition["effective_date"]
        if not isinstance(decision_date, date) or not isinstance(effective_date, date):
            raise TruthPreconditionFailedError("Strategy transition dates are invalid")
        active = tuple(transition["active"])
        values = tuple(1.0 if instrument in active else -1.0 for instrument in owner.instrument_ids)
        factor_registry = default_operator_registry()
        state_definition = FactorDefinitionVersion.create(
            "research_strategy_state",
            FeatureNode("research_strategy_state", "v3.research-strategy-state/1.0.0"),
            factor_registry,
        )
        factor_evaluator = DeterministicReferenceEvaluator(factor_registry)
        result = factor_evaluator.evaluate(
            state_definition, {"research_strategy_state": list(values)}
        )
        decision_time = datetime.combine(decision_date, time(15), _MARKET_TIMEZONE)
        cutoff = decision_time
        factor_context = FactorEvaluationContext(
            snapshot_id=owner.snapshot_id,
            universe_version_id=owner.universe_version_id,
            snapshot_truth_binding=UnresolvedIdUpstreamTruthBinding.snapshot(
                owner.snapshot_id, PRE_ALPHA_CEILING
            ),
            universe_truth_binding=UnresolvedIdUpstreamTruthBinding.universe(
                owner.universe_version_id, PRE_ALPHA_CEILING
            ),
            knowledge_cutoff=cutoff,
            calendar_version_id=owner.calendar_version_id,
            schema_version_id=_STATE_SCHEMA,
            environment_fingerprint=_RUNTIME.environment_fingerprint,
            evaluator_version=factor_evaluator.evaluator_version,
        )
        materialization = FeatureMaterialization.create(
            state_definition,
            result,
            factor_context,
            state_provenance_artifact_id,
            PRE_ALPHA_CEILING,
        )
        input_descriptor = self._publish_json(
            project_id,
            _DECISION_INPUT_ROLE,
            "v3.feature-materialization-values/1.0.0",
            materialization.feature_materialization_id,
            {"values": list(result.values)},
        )
        if input_descriptor.artifact_id != materialization.output_artifact_id:
            raise TruthPreconditionFailedError("Strategy decision input Artifact identity drifted")
        runtime_values = self._verified_decision_values(
            artifact_id=input_descriptor.artifact_id,
            instrument_ids=owner.instrument_ids,
        )
        factor_evaluation = FactorEvaluation.create(
            state_definition,
            materialization,
            state_provenance_artifact_id,
            PRE_ALPHA_CEILING,
        )
        feature_set = FeatureSetVersion.create(
            (factor_evaluation,), state_provenance_artifact_id
        )
        label = LabelSpec.create("research_state_next_session", "state", 1, 0)
        split = SplitSpec.create(
            train_start=0,
            train_end=9,
            validation_start=12,
            validation_end=19,
            test_start=22,
            test_end=29,
            purge_observations=1,
            embargo_observations=1,
        )
        dataset_binding = DatasetBinding(
            snapshot_id=owner.snapshot_id,
            universe_version_id=owner.universe_version_id,
            snapshot_truth_binding=factor_context.snapshot_truth_binding,
            universe_truth_binding=factor_context.universe_truth_binding,
            knowledge_cutoff=cutoff,
            calendar_version_id=owner.calendar_version_id,
            schema_version_id=_STATE_SCHEMA,
            environment_fingerprint=_RUNTIME.environment_fingerprint,
            evaluator_version=factor_evaluator.evaluator_version,
        )
        dataset_descriptor = self._publish_json(
            project_id,
            _DATASET_ROLE,
            "v3.product-strategy-decision-dataset/1.0.0",
            factor_evaluation.factor_evaluation_id,
            {
                "feature_set": feature_set.to_wire(),
                "factor_evaluation": factor_evaluation.to_wire(),
                "label": label.to_wire(),
                "split": split.to_wire(),
                "binding": dataset_binding.to_wire(),
            },
        )
        dataset = DatasetVersion.create(
            feature_set=feature_set,
            evaluations=(factor_evaluation,),
            label_spec=label,
            split_spec=split,
            binding=dataset_binding,
            dataset_artifact_id=dataset_descriptor.artifact_id,
            provenance_artifact_id=state_provenance_artifact_id,
            proposed_state=PRE_ALPHA_CEILING,
        )
        exact_universe = ExactUniverseReference(
            owner.universe_version_id,
            owner.universe_definition_sha256,
            owner.membership_artifact_id,
            owner.membership_sha256,
            owner.instrument_ids,
            PRE_ALPHA_CEILING,
        )
        exact_snapshot = ExactSnapshotReference(
            owner.snapshot_id, owner.snapshot_sha256, PRE_ALPHA_CEILING
        )
        exact_calendar = ExactCalendarReference(
            owner.calendar_version_id,
            owner.calendar_sha256,
            "Asia/Shanghai",
            PRE_ALPHA_CEILING,
        )
        input_reference = BoundInputReference.from_feature_materialization(
            "scores", materialization
        )
        binding = StrategyEvaluationBindingVersion.create(
            definition=definition,
            dataset=dataset,
            factor_evaluations=(factor_evaluation,),
            feature_materializations=(materialization,),
            snapshot=exact_snapshot,
            universe=exact_universe,
            period=EvaluationPeriod(
                datetime.combine(owner.session_dates[0], time(15), _MARKET_TIMEZONE),
                cutoff,
            ),
            knowledge_cutoff=cutoff,
            calendar=exact_calendar,
            compiler_version=definition.compiler_version,
            runtime_profile_id=definition.runtime_profile_id,
            environment_fingerprint=_RUNTIME.environment_fingerprint,
            input_references=(input_reference,),
        )
        evaluation = DeterministicStrategyEvaluator().evaluate(
            definition=definition,
            binding=binding,
            inputs=(
                CrossSectionInputArtifact(
                    binding_key="scores",
                    artifact_id=materialization.output_artifact_id,
                    content_sha256=materialization.output_sha256,
                    decision_time=decision_time,
                    values=runtime_values,
                ),
            ),
        )
        if evaluation.signal_artifact is None or evaluation.selection_artifact is None or evaluation.portfolio_intent is None:
            raise TruthPreconditionFailedError("canonical Strategy evaluation is incomplete")
        signal_descriptor = self._publish_json(
            project_id,
            _SIGNAL_ROLE,
            "v3.strategy-signal-artifact/1.0.0",
            evaluation.signal_artifact.signal_artifact_id,
            evaluation.signal_artifact.to_wire(),
        )
        selection_descriptor = self._publish_json(
            project_id,
            _SELECTION_ROLE,
            "v3.strategy-selection-artifact/1.0.0",
            evaluation.selection_artifact.selection_artifact_id,
            evaluation.selection_artifact.to_wire(),
        )
        intent_descriptor = self._publish_json(
            project_id,
            _INTENT_ROLE,
            "v3.strategy-portfolio-intent/1.0.0",
            evaluation.portfolio_intent.portfolio_intent_id,
            evaluation.portfolio_intent.to_wire(),
        )
        target_cash = format(Decimal(1) - Decimal(gross_exposure), "f") if active else "1"
        construction_spec = PortfolioConstructionSpecVersion.create(
            method=ConstructionMethod.EQUAL_WEIGHT_SELECTED,
            method_version="1.0.0",
            target_cash_weight=target_cash,
            max_instrument_weight="1",
            max_gross_exposure=gross_exposure,
            max_net_exposure=gross_exposure,
            runtime_identity=_RUNTIME,
        )
        target = CanonicalPortfolioOwnerService(policy_owner).construct_and_publish(
            project_id=project_id,
            project_context_revision_id=project_context_revision_id,
            intent=evaluation.portfolio_intent,
            definition=definition,
            binding=binding,
            construction_spec=construction_spec,
            runtime_identity=_RUNTIME,
            base_currency="CNY",
            as_of=decision_time,
            decision_time=decision_time,
            # The accepted open-timing profile selects only vectors strictly
            # before 09:15 and executes them at 09:25.  A t-close decision is
            # therefore made eligible just before that cutoff on t+1; 09:30
            # would silently defer the same canonical decision to t+2.
            rebalance_time=datetime.combine(
                effective_date, time(9, 14, 59), _MARKET_TIMEZONE
            ),
            valid_until=datetime.combine(effective_date, time(15), _MARKET_TIMEZONE),
            published_at=published_at,
        )
        risk_repository = SQLiteRiskApplicationRepository(
            self.product.database_path, self.product.artifact_root
        )
        risk = CanonicalRiskApplicationService(risk_repository).apply_and_publish(
            CanonicalRiskApplicationRequest(
                project_id=project_id,
                project_context_revision_id=project_context_revision_id,
                source_target_weight_vector_id=target.construction.target.target_weight_vector_id,
                risk_policy_set_version_id=risk_policy_set_version_id,
                runtime_identity=_RUNTIME,
                context_identity=target.publication.context_identity,
            ),
            published_at=published_at,
        )
        return {
            "decision_time": decision_time.isoformat(),
            "effective_time": datetime.combine(
                effective_date, time(9, 14, 59), _MARKET_TIMEZONE
            ).isoformat(),
            "signal_artifact_id": evaluation.signal_artifact.signal_artifact_id,
            "signal_payload_artifact_id": signal_descriptor.artifact_id,
            "selection_artifact_id": evaluation.selection_artifact.selection_artifact_id,
            "selection_payload_artifact_id": selection_descriptor.artifact_id,
            "portfolio_intent_id": evaluation.portfolio_intent.portfolio_intent_id,
            "portfolio_intent_payload_artifact_id": intent_descriptor.artifact_id,
            "target_weight_vector_id": target.construction.target.target_weight_vector_id,
            "target_weight_payload_artifact_id": target.publication.artifact_id,
            "risk_application_receipt_id": risk.risk_application_receipt_id,
            "risk_application_receipt_artifact_id": risk.receipt_artifact_id,
            "risk_adjusted_weight_vector_id": risk.risk_adjusted_weight_vector_id,
            "risk_adjusted_weight_artifact_id": risk.adjusted_artifact_id,
            "context_identity": target.publication.context_identity,
        }

    def _verified_decision_values(
        self,
        *,
        artifact_id: str,
        instrument_ids: tuple[str, ...],
    ) -> dict[str, str]:
        try:
            payload = json.loads(
                self.product.read_verified_bytes(artifact_id).decode("utf-8")
            )
        except (
            ArtifactNotPublishedError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            OSError,
            ValueError,
        ) as error:
            raise TruthPreconditionFailedError(
                "Strategy decision input bytes are invalid"
            ) from error
        payload = _closed(payload, {"values"}, "Strategy decision input")
        values = payload["values"]
        if not isinstance(values, list) or len(values) != len(instrument_ids):
            raise TruthPreconditionFailedError(
                "Strategy decision input does not cover the exact Universe"
            )
        resolved: dict[str, str] = {}
        for instrument_id, value in zip(instrument_ids, values, strict=True):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value not in {-1, 1}:
                raise TruthPreconditionFailedError(
                    "Strategy decision input contains a non-state value"
                )
            resolved[instrument_id] = "1" if value == 1 else "-1"
        return resolved

    def _publish_json(
        self,
        project_id: str,
        role: str,
        schema_version: str,
        provenance: str,
        wire: Mapping[str, object],
    ):
        payload = canonical_json_bytes(dict(wire))
        if len(payload) > _MAX_OWNER_BYTES:
            raise TruthPreconditionFailedError(f"{role} exceeds the admitted byte bound")
        return self.product.execution._publish_artifact_batch(
            payloads=((provenance, payload, role, canonical_sha256({"schema_version": schema_version})),),
            references=((project_id, role, 0),),
        )[0].descriptor

    def _publish_strategy_version(
        self,
        *,
        project_id: str,
        definition: StrategyDefinitionVersion,
        definition_artifact_id: str,
        published_at: datetime,
    ):
        validation_wire = {
            "schema_version": _VALIDATION_SCHEMA,
            "strategy_definition_version_id": definition.strategy_definition_version_id,
            "canonical_ir_sha256": definition.canonical_ir_sha256,
            "component_registry_version": definition.component_registry_version,
            "compiler_version": definition.compiler_version,
            "runtime_profile_id": definition.runtime_profile_id,
            "validation_state": definition.validation_state,
            "truth_admission": definition.truth_admission.to_wire(),
        }
        validation_descriptor = self._publish_json(
            project_id,
            _VALIDATION_ROLE,
            _VALIDATION_SCHEMA,
            definition.strategy_definition_version_id,
            validation_wire,
        )
        candidate_id = mint_v3_id("stv_")
        connection = self.product._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT OR IGNORE INTO strategy_version(
                  strategy_version_id,project_id,strategy_ir_artifact_id,
                  validation_artifact_id,content_hash,compiler_profile_id,
                  state,published_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    candidate_id,
                    project_id,
                    definition_artifact_id,
                    validation_descriptor.artifact_id,
                    definition.canonical_ir_sha256,
                    definition.compiler_version,
                    "PUBLISHED",
                    published_at.isoformat().replace("+00:00", "Z"),
                ),
            )
            row = connection.execute(
                """
                SELECT strategy_version_id,strategy_ir_artifact_id,
                       validation_artifact_id,state
                FROM strategy_version
                WHERE project_id=? AND content_hash=? AND compiler_profile_id=?
                """,
                (
                    project_id,
                    definition.canonical_ir_sha256,
                    definition.compiler_version,
                ),
            ).fetchone()
            if row is None:
                raise TruthPreconditionFailedError(
                    "StrategyVersion publication was not persisted"
                )
            if (
                str(row[1]) != definition_artifact_id
                or str(row[2]) != validation_descriptor.artifact_id
                or str(row[3]) != "PUBLISHED"
            ):
                raise TruthPreconditionFailedError(
                    "StrategyVersion publication binding drifted"
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return str(row[0]), validation_descriptor

    def _read_project_artifact(
        self,
        *,
        project_id: str,
        artifact_id: str,
        role: str,
    ) -> bytes:
        connection = connect_catalog(self.product.database_path, read_only=True)
        try:
            row = connection.execute(
                """
                SELECT a.sha256,a.byte_size
                FROM artifact AS a
                JOIN artifact_reference AS r ON r.artifact_id=a.artifact_id
                WHERE a.artifact_id=? AND a.state='PUBLISHED' AND a.semantic_role=?
                  AND r.owner_type='Project' AND r.owner_id=? AND r.role=?
                  AND r.state='ACTIVE'
                """,
                (artifact_id, role, project_id, role),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise TruthPreconditionFailedError(
                f"Strategy artifact {role} is not project-reachable"
            )
        sha256, byte_size = str(row[0]), int(row[1])
        if artifact_id != "art_sha256_" + sha256 or not 0 < byte_size <= _MAX_OWNER_BYTES:
            raise TruthPreconditionFailedError(
                f"Strategy artifact {role} descriptor drifted"
            )
        try:
            raw = self.product.read_verified_bytes(artifact_id)
        except (ArtifactError, ArtifactNotPublishedError, OSError, ValueError) as error:
            raise TruthPreconditionFailedError(
                f"Strategy artifact {role} bytes are unavailable"
            ) from error
        if len(raw) != byte_size:
            raise TruthPreconditionFailedError(
                f"Strategy artifact {role} byte size drifted"
            )
        return raw

    def _read_canonical_owner_artifact(
        self,
        *,
        table: str,
        identity_column: str,
        identity: str,
        artifact_id: str,
        role: str,
        project_id: str,
        project_context_revision_id: str,
        context_identity: str,
    ) -> bytes:
        admitted = {
            (
                "target_weight_vector_publication",
                "target_weight_vector_id",
                "TARGET_WEIGHT_VECTOR",
            ),
            (
                "risk_application_receipt_publication",
                "risk_application_receipt_id",
                "RISK_APPLICATION_RECEIPT",
            ),
            (
                "risk_adjusted_weight_vector_publication",
                "risk_adjusted_weight_vector_id",
                "RISK_ADJUSTED_WEIGHT_VECTOR",
            ),
        }
        if (table, identity_column, role) not in admitted:
            raise TruthPreconditionFailedError("Strategy owner Artifact query is not admitted")
        connection = connect_catalog(self.product.database_path, read_only=True)
        try:
            row = connection.execute(
                f"""
                SELECT a.sha256,a.byte_size,a.semantic_role,r.role,r.state
                FROM {table} AS p
                JOIN artifact AS a ON a.artifact_id=p.artifact_id
                JOIN artifact_reference AS r
                  ON r.artifact_reference_id=p.artifact_reference_id
                WHERE p.{identity_column}=? AND p.project_id=?
                  AND p.project_context_revision_id=? AND p.context_identity=?
                  AND p.artifact_id=? AND a.state='PUBLISHED'
                """,
                (
                    identity,
                    project_id,
                    project_context_revision_id,
                    context_identity,
                    artifact_id,
                ),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise TruthPreconditionFailedError(
                f"Strategy canonical owner artifact {role} is unavailable"
            )
        sha256, byte_size = str(row[0]), int(row[1])
        if (
            artifact_id != "art_sha256_" + sha256
            or not 0 < byte_size <= _MAX_OWNER_BYTES
            or str(row[2]) != role
            or str(row[3]) != role
            or str(row[4]) != "ACTIVE"
        ):
            raise TruthPreconditionFailedError(
                f"Strategy canonical owner artifact {role} descriptor drifted"
            )
        try:
            raw = self.product.read_verified_bytes(artifact_id)
        except (ArtifactError, ArtifactNotPublishedError, OSError, ValueError) as error:
            raise TruthPreconditionFailedError(
                f"Strategy canonical owner artifact {role} bytes are unavailable"
            ) from error
        if len(raw) != byte_size:
            raise TruthPreconditionFailedError(
                f"Strategy canonical owner artifact {role} byte size drifted"
            )
        return raw

    def _verify_decision_chain_links(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        chain: Mapping[str, Any],
    ) -> None:
        for artifact_key, role, identity_key, artifact_type in (
            (
                "signal_payload_artifact_id",
                _SIGNAL_ROLE,
                "signal_artifact_id",
                "SignalArtifact",
            ),
            (
                "selection_payload_artifact_id",
                _SELECTION_ROLE,
                "selection_artifact_id",
                "SelectionArtifact",
            ),
            (
                "portfolio_intent_payload_artifact_id",
                _INTENT_ROLE,
                "portfolio_intent_id",
                "PortfolioIntent",
            ),
        ):
            artifact_id = chain.get(artifact_key)
            if not isinstance(artifact_id, str):
                raise TruthPreconditionFailedError(
                    "Strategy decision-chain payload identity is invalid"
                )
            raw = self._read_project_artifact(
                project_id=project_id,
                artifact_id=artifact_id,
                role=role,
            )
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise TruthPreconditionFailedError(
                    f"Strategy decision-chain artifact {role} JSON is invalid"
                ) from error
            if (
                not isinstance(payload, dict)
                or payload.get("artifact_type") != artifact_type
                or payload.get(identity_key) != chain.get(identity_key)
            ):
                raise TruthPreconditionFailedError(
                    f"Strategy decision-chain artifact {role} binding drifted"
                )

        context_identity = chain.get("context_identity")
        if not isinstance(context_identity, str):
            raise TruthPreconditionFailedError(
                "Strategy decision-chain context identity is invalid"
            )
        for table, identity_column, identity_key, artifact_key, role in (
            (
                "target_weight_vector_publication",
                "target_weight_vector_id",
                "target_weight_vector_id",
                "target_weight_payload_artifact_id",
                "TARGET_WEIGHT_VECTOR",
            ),
            (
                "risk_application_receipt_publication",
                "risk_application_receipt_id",
                "risk_application_receipt_id",
                "risk_application_receipt_artifact_id",
                "RISK_APPLICATION_RECEIPT",
            ),
            (
                "risk_adjusted_weight_vector_publication",
                "risk_adjusted_weight_vector_id",
                "risk_adjusted_weight_vector_id",
                "risk_adjusted_weight_artifact_id",
                "RISK_ADJUSTED_WEIGHT_VECTOR",
            ),
        ):
            identity = chain.get(identity_key)
            artifact_id = chain.get(artifact_key)
            if not isinstance(identity, str) or not isinstance(artifact_id, str):
                raise TruthPreconditionFailedError(
                    "Strategy canonical owner identity is invalid"
                )
            raw = self._read_canonical_owner_artifact(
                table=table,
                identity_column=identity_column,
                identity=identity,
                artifact_id=artifact_id,
                role=role,
                project_id=project_id,
                project_context_revision_id=project_context_revision_id,
                context_identity=context_identity,
            )
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise TruthPreconditionFailedError(
                    f"Strategy canonical owner artifact {role} JSON is invalid"
                ) from error
            if not isinstance(payload, dict) or payload.get(identity_key) != identity:
                raise TruthPreconditionFailedError(
                    f"Strategy canonical owner artifact {role} binding drifted"
                )

    def _verify_read_model(self, value: Mapping[str, Any]) -> None:
        value = _closed(
            value,
            {
                "schema_version",
                "truth",
                "admission",
                "project_id",
                "project_context_revision_id",
                "snapshot_id",
                "universe_version_id",
                "research_strategy_spec_id",
                "research_strategy_spec_artifact_id",
                "strategy_version_id",
                "strategy_definition_version_id",
                "strategy_definition_artifact_id",
                "strategy_validation_artifact_id",
                "state_materialization_id",
                "state_materialization_artifact_id",
                "entry_signal_ref",
                "exit_signal_ref",
                "profile_refs",
                "transition_count",
                "decision_chain_count",
                "decision_chain_id_prefixes",
                "decision_chains",
            },
            "Strategy read model",
        )
        if value.get("schema_version") != _READ_MODEL_SCHEMA or value.get("truth") != "NOT_FORMAL" or value.get("admission") != "PRE_ALPHA":
            raise TruthPreconditionFailedError("Strategy read-model truth drifted")
        project_id = value.get("project_id")
        project_context_revision_id = value.get("project_context_revision_id")
        if not isinstance(project_id, str) or not isinstance(
            project_context_revision_id, str
        ):
            raise TruthPreconditionFailedError("Strategy read-model project identity is invalid")
        linked = (
            (
                "research_strategy_spec_artifact_id",
                _SPEC_ROLE,
                "research_strategy_spec_id",
                _SPEC_SCHEMA,
            ),
            (
                "strategy_definition_artifact_id",
                _DEFINITION_ROLE,
                "strategy_definition_version_id",
                "v3.strategy-definition-version/1.0.0",
            ),
            (
                "strategy_validation_artifact_id",
                _VALIDATION_ROLE,
                "strategy_definition_version_id",
                _VALIDATION_SCHEMA,
            ),
            (
                "state_materialization_artifact_id",
                _STATE_ROLE,
                "state_materialization_id",
                _STATE_SCHEMA,
            ),
        )
        linked_payloads: dict[str, dict[str, Any]] = {}
        for artifact_key, role, identity_key, schema_version in linked:
            artifact_id = value.get(artifact_key)
            if not isinstance(artifact_id, str):
                raise TruthPreconditionFailedError(
                    "Strategy read-model Artifact identity is invalid"
                )
            raw = self._read_project_artifact(
                project_id=project_id,
                artifact_id=artifact_id,
                role=role,
            )
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise TruthPreconditionFailedError(
                    f"Strategy artifact {role} JSON is invalid"
                ) from error
            if (
                not isinstance(payload, dict)
                or payload.get("schema_version") != schema_version
                or payload.get(identity_key) != value.get(identity_key)
            ):
                raise TruthPreconditionFailedError(
                    f"Strategy artifact {role} binding drifted"
                )
            linked_payloads[role] = payload
        spec_payload = _closed(
            linked_payloads[_SPEC_ROLE],
            {
                "schema_version",
                "research_strategy_spec_id",
                "universe_version_id",
                "entry_signal_factor_version_id",
                "exit_signal_factor_version_id",
                "position_sizing",
                "max_positions",
                "gross_exposure",
                "rebalance",
                "cost_policy_version_id",
                "execution_policy_version_id",
                "risk_policy_set_version_id",
                "initial_cash",
                "assumption_profile_id",
            },
            "Research Strategy spec",
        )
        try:
            verified_spec = ResearchStrategySpecV1.create(
                universe_version_id=spec_payload["universe_version_id"],
                entry_signal_factor_version_id=spec_payload[
                    "entry_signal_factor_version_id"
                ],
                exit_signal_factor_version_id=spec_payload[
                    "exit_signal_factor_version_id"
                ],
                position_sizing=spec_payload["position_sizing"],
                max_positions=spec_payload["max_positions"],
                gross_exposure=spec_payload["gross_exposure"],
                rebalance=spec_payload["rebalance"],
                cost_policy_version_id=spec_payload["cost_policy_version_id"],
                execution_policy_version_id=spec_payload[
                    "execution_policy_version_id"
                ],
                risk_policy_set_version_id=spec_payload[
                    "risk_policy_set_version_id"
                ],
                initial_cash=spec_payload["initial_cash"],
                assumption_profile_id=spec_payload["assumption_profile_id"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise TruthPreconditionFailedError(
                "Research Strategy spec payload is invalid"
            ) from error
        if verified_spec.to_wire() != spec_payload:
            raise TruthPreconditionFailedError(
                "Research Strategy spec content identity drifted"
            )
        profile_refs = _closed(
            value.get("profile_refs"),
            {
                "cost_policy_version_id",
                "execution_policy_version_id",
                "risk_policy_set_version_id",
                "assumption_profile_id",
            },
            "Strategy profile refs",
        )
        expected_profile_refs = {
            "cost_policy_version_id": verified_spec.cost_policy_version_id,
            "execution_policy_version_id": verified_spec.execution_policy_version_id,
            "risk_policy_set_version_id": verified_spec.risk_policy_set_version_id,
            "assumption_profile_id": verified_spec.assumption_profile_id,
        }
        if (
            profile_refs != expected_profile_refs
            or verified_spec.assumption_profile_id
            not in {
                item["assumption_profile_id"]
                for item in self.bounded_assumption_profiles()
            }
            or value.get("universe_version_id") != verified_spec.universe_version_id
            or not isinstance(value.get("entry_signal_ref"), dict)
            or value["entry_signal_ref"].get("factor_definition_version_id")
            != verified_spec.entry_signal_factor_version_id
            or not isinstance(value.get("exit_signal_ref"), dict)
            or value["exit_signal_ref"].get("factor_definition_version_id")
            != verified_spec.exit_signal_factor_version_id
            or value.get("strategy_definition_version_id")
            != _strategy_definition(verified_spec).strategy_definition_version_id
        ):
            raise TruthPreconditionFailedError(
                "Strategy read model does not match its verified spec"
            )
        strategy_version_id = value.get("strategy_version_id")
        if not isinstance(strategy_version_id, str) or not strategy_version_id.startswith(
            "stv_"
        ):
            raise TruthPreconditionFailedError("StrategyVersion identity is invalid")
        connection = connect_catalog(self.product.database_path, read_only=True)
        try:
            version = connection.execute(
                """
                SELECT strategy_ir_artifact_id,validation_artifact_id,state
                FROM strategy_version
                WHERE strategy_version_id=? AND project_id=?
                """,
                (strategy_version_id, project_id),
            ).fetchone()
        finally:
            connection.close()
        if (
            version is None
            or str(version[0]) != value.get("strategy_definition_artifact_id")
            or str(version[1]) != value.get("strategy_validation_artifact_id")
            or str(version[2]) != "PUBLISHED"
        ):
            raise TruthPreconditionFailedError(
                "StrategyVersion Catalog binding drifted"
            )
        chains = value.get("decision_chains")
        if not isinstance(chains, list) or value.get("decision_chain_count") != len(chains):
            raise TruthPreconditionFailedError("Strategy decision-chain count drifted")
        prefixes = {
            "signal_artifact_id": "sig_sha256_",
            "selection_artifact_id": "sel_sha256_",
            "portfolio_intent_id": "pint_sha256_",
            "target_weight_vector_id": "twv_sha256_",
            "risk_application_receipt_id": "rar_sha256_",
            "risk_adjusted_weight_vector_id": "rawv_sha256_",
        }
        for chain in chains:
            if not isinstance(chain, dict) or any(
                not isinstance(chain.get(key), str) or not chain[key].startswith(prefix)
                for key, prefix in prefixes.items()
            ):
                raise TruthPreconditionFailedError("Strategy decision-chain identity drifted")
            self._verify_decision_chain_links(
                project_id=project_id,
                project_context_revision_id=project_context_revision_id,
                chain=chain,
            )


@dataclass(frozen=True, slots=True)
class ProductStrategySubmission:
    project_id: str
    project_context_revision_id: str
    universe_version_id: str
    entry_signal_factor_version_id: str
    exit_signal_factor_version_id: str
    position_sizing: str
    max_positions: int
    gross_exposure: str
    rebalance: str
    cost_policy_version_id: str
    execution_policy_version_id: str
    risk_policy_set_version_id: str
    initial_cash: str
    assumption_profile_id: str
    idempotency_key: str
    execution_deadline_at: str | None = None


@dataclass(frozen=True, slots=True)
class _PreparedStrategyRequest:
    project_id: str
    project_context_revision_id: str
    spec: ResearchStrategySpecV1
    semantic: dict[str, Any]
    request_hash: str
    scope: str
    execution_deadline_at: str | None


@dataclass(frozen=True, slots=True)
class _StrategyTaskHandles:
    task: Any
    run: Any
    attempt: Any


__all__ = [
    "PRODUCT_STRATEGY_OPERATION",
    "ProductStrategyService",
    "ProductStrategySubmission",
    "ResearchStrategySpecV1",
]
