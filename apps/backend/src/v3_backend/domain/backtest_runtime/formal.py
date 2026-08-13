"""Formal Backtest entry that resolves canonical payloads before pure simulation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import InvalidOperation
from typing import ClassVar, Protocol

from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
from v3_backend.domain.data_truth import TradingStatus
from v3_backend.domain.payload_authority import (
    CanonicalPayloadResolver,
    PayloadResolutionRequest,
    PayloadResolutionResult,
)
from v3_backend.domain.weights import RiskAdjustedWeightVector, RuntimeIdentity
from v3_backend.provenance.canonical_hash import canonical_json_bytes, canonical_sha256

from .engine import DeterministicAshareBacktestEngine
from .model import (
    AshareTradingRuleProfileVersion,
    BacktestContractError,
    BacktestRunResult,
    BacktestRunSpec,
    Board,
    CorporateAction,
    CorporateActionType,
    CostPolicyVersion,
    DailyMarketState,
    ExactInputReference,
    ExecutionTimingProfileVersion,
    InitialHolding,
    InstrumentDefinition,
    MarketSession,
    ScheduledWeights,
    _d,
    _text,
    decimal_text,
)


SNAPSHOT_ROLE = "SNAPSHOT_CONTEXT"
MARKET_ROLE = "MARKET_STATE"
CALENDAR_ROLE = "TRADING_CALENDAR"
CORPORATE_ACTION_ROLE = "CORPORATE_ACTIONS"
UNIVERSE_ROLE = "HISTORICAL_UNIVERSE"
WEIGHT_ROLE = "RISK_ADJUSTED_WEIGHT_VECTOR"

SNAPSHOT_SCHEMA = "v3.backtest_snapshot_context/1.0.0"
MARKET_SCHEMA = "v3.backtest_market_state/1.0.0"
CALENDAR_SCHEMA = "v3.backtest_trading_calendar/1.0.0"
CORPORATE_ACTION_SCHEMA = "v3.backtest_corporate_actions/1.0.0"
UNIVERSE_SCHEMA = "v3.backtest_historical_universe/1.0.0"
FORMAL_REQUEST_SCHEMA = "v3.formal_backtest_request/1.0.0"
FORMAL_RESULT_SCHEMA = "v3.formal_backtest_result/1.0.0"

_ROLE_POLICY = {
    SNAPSHOT_ROLE: ("DATA_TRUTH", SNAPSHOT_SCHEMA, "SNAPSHOT"),
    MARKET_ROLE: ("DATA_TRUTH", MARKET_SCHEMA, "MARKET_DATA"),
    CALENDAR_ROLE: ("DATA_TRUTH", CALENDAR_SCHEMA, "TRADING_CALENDAR"),
    CORPORATE_ACTION_ROLE: (
        "DATA_TRUTH",
        CORPORATE_ACTION_SCHEMA,
        "CORPORATE_ACTIONS",
    ),
    UNIVERSE_ROLE: ("UNIVERSE", UNIVERSE_SCHEMA, "UNIVERSE"),
    WEIGHT_ROLE: (
        "RISK",
        RiskAdjustedWeightVector.schema_version,
        "RISK_ADJUSTED_WEIGHT",
    ),
}


class FormalBacktestPayloadError(BacktestContractError):
    """A verified byte payload is malformed or cross-bound to the wrong context."""


class CanonicalWeightUnavailable(FormalBacktestPayloadError):
    pass


class CanonicalWeightContentMismatch(FormalBacktestPayloadError):
    pass


class RiskAdjustedWeightVectorResolver(Protocol):
    """Risk-owner port; the returned W0 object is still byte-verified before use."""

    def resolve(self, risk_adjusted_weight_vector_id: str) -> RiskAdjustedWeightVector | None: ...


def _require_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise FormalBacktestPayloadError(f"{field} must be boolean")
    return value


def _require_int(value: object, field: str, *, non_negative: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise FormalBacktestPayloadError(f"{field} must be an integer")
    if non_negative and value < 0:
        raise FormalBacktestPayloadError(f"{field} must be non-negative")
    return value


def _require_dict(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise FormalBacktestPayloadError(f"{field} must be an object")
    return value


def _require_list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise FormalBacktestPayloadError(f"{field} must be an array")
    return value


def _keys(value: dict[str, object], expected: set[str], field: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise FormalBacktestPayloadError(
            f"{field} keys mismatch; missing={missing}, extra={extra}"
        )


def _date(value: object, field: str) -> date:
    if not isinstance(value, str):
        raise FormalBacktestPayloadError(f"{field} must be an ISO date")
    try:
        observed = date.fromisoformat(value)
    except ValueError as exc:
        raise FormalBacktestPayloadError(f"{field} must be an ISO date") from exc
    if observed.isoformat() != value:
        raise FormalBacktestPayloadError(f"{field} must be canonical ISO date text")
    return observed


def _datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise FormalBacktestPayloadError(f"{field} must be an ISO datetime")
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FormalBacktestPayloadError(f"{field} must be an ISO datetime") from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise FormalBacktestPayloadError(f"{field} must be timezone-aware")
    return observed


def _decimal(value: object, field: str, *, positive: bool = False) -> str:
    if not isinstance(value, str):
        raise FormalBacktestPayloadError(f"{field} must be an exact decimal string")
    try:
        normalized = decimal_text(value, field, non_negative=True)
    except BacktestContractError as exc:
        raise FormalBacktestPayloadError(str(exc)) from exc
    if normalized != value:
        raise FormalBacktestPayloadError(f"{field} must use canonical decimal text")
    if positive and _d(normalized) <= 0:
        raise FormalBacktestPayloadError(f"{field} must be positive")
    return normalized


def _strict_json(payload: bytes) -> dict[str, object]:
    def closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        decoded = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=closed_object,
            parse_float=lambda value: (_ for _ in ()).throw(
                ValueError(f"JSON float is forbidden: {value}")
            ),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON is forbidden: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise FormalBacktestPayloadError("payload must be strict UTF-8 canonical JSON") from exc
    result = _require_dict(decoded, "payload")
    if canonical_json_bytes(result) != payload:
        raise FormalBacktestPayloadError("payload bytes are not canonical JSON")
    return result


@dataclass(frozen=True, slots=True)
class BacktestPayloadReference:
    owner_namespace: str
    owner_id: str
    owner_version: str
    payload_role: str
    context_identity: str
    max_bytes: int

    def __post_init__(self) -> None:
        for field in (
            "owner_namespace",
            "owner_id",
            "owner_version",
            "payload_role",
            "context_identity",
        ):
            _text(getattr(self, field), field)
        if self.payload_role not in _ROLE_POLICY:
            raise FormalBacktestPayloadError("unsupported formal Backtest payload role")
        expected_namespace = _ROLE_POLICY[self.payload_role][0]
        if self.owner_namespace != expected_namespace:
            raise FormalBacktestPayloadError(
                f"{self.payload_role} must be owned by {expected_namespace}"
            )
        if (
            not isinstance(self.max_bytes, int)
            or isinstance(self.max_bytes, bool)
            or self.max_bytes <= 0
        ):
            raise FormalBacktestPayloadError("max_bytes must be a positive integer")

    @property
    def schema_fingerprint(self) -> str:
        return _ROLE_POLICY[self.payload_role][1]

    @property
    def exact_reference_kind(self) -> str:
        return _ROLE_POLICY[self.payload_role][2]

    def to_request(self) -> PayloadResolutionRequest:
        return PayloadResolutionRequest(
            owner_namespace=self.owner_namespace,
            owner_id=self.owner_id,
            owner_version=self.owner_version,
            payload_role=self.payload_role,
            context_identity=self.context_identity,
            max_bytes=self.max_bytes,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "owner_namespace": self.owner_namespace,
            "owner_id": self.owner_id,
            "owner_version": self.owner_version,
            "payload_role": self.payload_role,
            "context_identity": self.context_identity,
            "max_bytes": self.max_bytes,
        }


@dataclass(frozen=True, slots=True)
class ScheduledWeightPayloadReference:
    effective_at: datetime
    payload_reference: BacktestPayloadReference

    def __post_init__(self) -> None:
        if self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None:
            raise FormalBacktestPayloadError("scheduled weight effective_at must be aware")
        if self.payload_reference.payload_role != WEIGHT_ROLE:
            raise FormalBacktestPayloadError("scheduled weight must use the Risk owner role")

    def to_wire(self) -> dict[str, object]:
        return {
            "effective_at": self.effective_at,
            "payload_reference": self.payload_reference.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class FormalBacktestRunRequest:
    formal_request_id: str
    content_sha256: str
    snapshot: BacktestPayloadReference
    market_data: BacktestPayloadReference
    calendar: BacktestPayloadReference
    corporate_actions: BacktestPayloadReference
    universe: BacktestPayloadReference
    scheduled_weights: tuple[ScheduledWeightPayloadReference, ...]
    session_start: date
    session_end: date
    initial_cash: str
    initial_holdings: tuple[InitialHolding, ...]
    rule_profile: AshareTradingRuleProfileVersion
    cost_policy: CostPolicyVersion
    execution_timing_profile: ExecutionTimingProfileVersion
    runtime_identity: RuntimeIdentity
    engine_version: str

    schema_version: ClassVar[str] = FORMAL_REQUEST_SCHEMA

    @classmethod
    def create(
        cls,
        *,
        snapshot: BacktestPayloadReference,
        market_data: BacktestPayloadReference,
        calendar: BacktestPayloadReference,
        corporate_actions: BacktestPayloadReference,
        universe: BacktestPayloadReference,
        scheduled_weights: tuple[ScheduledWeightPayloadReference, ...],
        session_start: date,
        session_end: date,
        initial_cash: str,
        initial_holdings: tuple[InitialHolding, ...],
        rule_profile: AshareTradingRuleProfileVersion,
        cost_policy: CostPolicyVersion,
        execution_timing_profile: ExecutionTimingProfileVersion,
        runtime_identity: RuntimeIdentity,
        engine_version: str = "v3.a_share_daily_eod_engine/0.2.0",
    ) -> "FormalBacktestRunRequest":
        role_refs = {
            SNAPSHOT_ROLE: snapshot,
            MARKET_ROLE: market_data,
            CALENDAR_ROLE: calendar,
            CORPORATE_ACTION_ROLE: corporate_actions,
            UNIVERSE_ROLE: universe,
        }
        if any(ref.payload_role != role for role, ref in role_refs.items()):
            raise FormalBacktestPayloadError("formal request payload roles are cross-bound")
        contexts = {ref.context_identity for ref in role_refs.values()}
        contexts.update(item.payload_reference.context_identity for item in scheduled_weights)
        if len(contexts) != 1:
            raise FormalBacktestPayloadError("all formal payload references must share exact context")
        ordered_weights = tuple(sorted(scheduled_weights, key=lambda item: item.effective_at))
        if not ordered_weights:
            raise FormalBacktestPayloadError("formal request requires scheduled Risk weights")
        if len({item.effective_at for item in ordered_weights}) != len(ordered_weights):
            raise FormalBacktestPayloadError("scheduled effective_at values must be unique")
        if len({item.payload_reference.owner_id for item in ordered_weights}) != len(ordered_weights):
            raise FormalBacktestPayloadError("scheduled Risk owner IDs must be unique")
        if session_end < session_start:
            raise FormalBacktestPayloadError("session range is reversed")
        cash = decimal_text(initial_cash, "initial_cash", non_negative=True)
        holdings = tuple(sorted(initial_holdings, key=lambda item: item.instrument_id))
        if len({item.instrument_id for item in holdings}) != len(holdings):
            raise FormalBacktestPayloadError("initial holdings must be unique")
        rule_profile.assert_canonical()
        cost_policy.assert_canonical()
        execution_timing_profile.assert_canonical()
        if not isinstance(runtime_identity, RuntimeIdentity):
            raise TypeError("runtime_identity must be RuntimeIdentity")
        _text(engine_version, "engine_version")
        payload = cls._payload(
            snapshot,
            market_data,
            calendar,
            corporate_actions,
            universe,
            ordered_weights,
            session_start,
            session_end,
            cash,
            holdings,
            rule_profile,
            cost_policy,
            execution_timing_profile,
            runtime_identity,
            engine_version,
        )
        digest = canonical_sha256(payload)
        return cls(
            "fbtrq_sha256_" + digest,
            digest,
            snapshot,
            market_data,
            calendar,
            corporate_actions,
            universe,
            ordered_weights,
            session_start,
            session_end,
            cash,
            holdings,
            rule_profile,
            cost_policy,
            execution_timing_profile,
            runtime_identity,
            engine_version,
        )

    @classmethod
    def _payload(
        cls,
        snapshot,
        market_data,
        calendar,
        corporate_actions,
        universe,
        scheduled_weights,
        session_start,
        session_end,
        initial_cash,
        initial_holdings,
        rule_profile,
        cost_policy,
        timing,
        runtime,
        engine_version,
    ) -> dict[str, object]:
        return {
            "schema_version": cls.schema_version,
            "snapshot": snapshot.to_wire(),
            "market_data": market_data.to_wire(),
            "calendar": calendar.to_wire(),
            "corporate_actions": corporate_actions.to_wire(),
            "universe": universe.to_wire(),
            "scheduled_weights": [item.to_wire() for item in scheduled_weights],
            "session_start": session_start.isoformat(),
            "session_end": session_end.isoformat(),
            "initial_cash": initial_cash,
            "initial_holdings": [item.to_wire() for item in initial_holdings],
            "rule_profile_id": rule_profile.profile_id,
            "rule_profile_sha256": rule_profile.content_sha256,
            "cost_policy_id": cost_policy.policy_id,
            "cost_policy_sha256": cost_policy.content_sha256,
            "execution_timing_profile_id": timing.profile_id,
            "execution_timing_profile_sha256": timing.content_sha256,
            "runtime_identity": runtime.to_wire(),
            "engine_version": engine_version,
        }

    def assert_canonical(self) -> None:
        rebuilt = type(self).create(
            snapshot=self.snapshot,
            market_data=self.market_data,
            calendar=self.calendar,
            corporate_actions=self.corporate_actions,
            universe=self.universe,
            scheduled_weights=self.scheduled_weights,
            session_start=self.session_start,
            session_end=self.session_end,
            initial_cash=self.initial_cash,
            initial_holdings=self.initial_holdings,
            rule_profile=self.rule_profile,
            cost_policy=self.cost_policy,
            execution_timing_profile=self.execution_timing_profile,
            runtime_identity=self.runtime_identity,
            engine_version=self.engine_version,
        )
        if rebuilt != self:
            raise FormalBacktestPayloadError("formal request identity/content mismatch")

    def to_wire(self) -> dict[str, object]:
        return {
            "formal_request_id": self.formal_request_id,
            "content_sha256": self.content_sha256,
            **self._payload(
                self.snapshot,
                self.market_data,
                self.calendar,
                self.corporate_actions,
                self.universe,
                self.scheduled_weights,
                self.session_start,
                self.session_end,
                self.initial_cash,
                self.initial_holdings,
                self.rule_profile,
                self.cost_policy,
                self.execution_timing_profile,
                self.runtime_identity,
                self.engine_version,
            ),
        }


@dataclass(frozen=True, slots=True)
class FormalResolutionEvidence:
    payload_role: str
    owner_namespace: str
    owner_id: str
    owner_version: str
    artifact_id: str
    actual_sha256: str
    actual_byte_size: int
    context_identity: str
    receipt_id: str

    @classmethod
    def from_result(
        cls,
        reference: BacktestPayloadReference,
        result: PayloadResolutionResult,
    ) -> "FormalResolutionEvidence":
        payload = result.verified_payload
        receipt = result.receipt
        return cls(
            reference.payload_role,
            reference.owner_namespace,
            reference.owner_id,
            reference.owner_version,
            payload.artifact_id,
            payload.actual_sha256,
            payload.actual_byte_size,
            payload.context_identity,
            receipt.receipt_identity,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "payload_role": self.payload_role,
            "owner_namespace": self.owner_namespace,
            "owner_id": self.owner_id,
            "owner_version": self.owner_version,
            "artifact_id": self.artifact_id,
            "actual_sha256": self.actual_sha256,
            "actual_byte_size": self.actual_byte_size,
            "context_identity": self.context_identity,
            "receipt_id": self.receipt_id,
        }


@dataclass(frozen=True, slots=True)
class FormalBacktestRunResult:
    formal_result_id: str
    content_sha256: str
    formal_request_id: str
    formal_request_content_sha256: str
    run_spec_id: str
    run_spec_content_sha256: str
    pure_result: BacktestRunResult
    resolution_evidence: tuple[FormalResolutionEvidence, ...]
    engine_version: str
    runtime_identity: RuntimeIdentity
    rule_profile_id: str
    rule_profile_sha256: str
    cost_policy_id: str
    cost_policy_sha256: str
    execution_timing_profile_id: str
    execution_timing_profile_sha256: str

    schema_version: ClassVar[str] = FORMAL_RESULT_SCHEMA

    @classmethod
    def create(
        cls,
        request: FormalBacktestRunRequest,
        spec: BacktestRunSpec,
        pure_result: BacktestRunResult,
        evidence: tuple[FormalResolutionEvidence, ...],
    ) -> "FormalBacktestRunResult":
        if pure_result.run_spec_id != spec.run_spec_id:
            raise FormalBacktestPayloadError("pure result does not bind the resolved RunSpec")
        ordered = tuple(
            sorted(
                evidence,
                key=lambda item: (item.payload_role, item.owner_namespace, item.owner_id),
            )
        )
        required_roles = {
            SNAPSHOT_ROLE,
            MARKET_ROLE,
            CALENDAR_ROLE,
            CORPORATE_ACTION_ROLE,
            UNIVERSE_ROLE,
            WEIGHT_ROLE,
        }
        if required_roles - {item.payload_role for item in ordered}:
            raise FormalBacktestPayloadError("formal result lacks required resolution evidence")
        if len({item.receipt_id for item in ordered}) != len(ordered):
            raise FormalBacktestPayloadError("resolution receipt IDs must be unique")
        payload = cls._payload(
            request.formal_request_id,
            request.content_sha256,
            spec.run_spec_id,
            spec.content_sha256,
            pure_result,
            ordered,
            request.engine_version,
            request.runtime_identity,
            request.rule_profile.profile_id,
            request.rule_profile.content_sha256,
            request.cost_policy.policy_id,
            request.cost_policy.content_sha256,
            request.execution_timing_profile.profile_id,
            request.execution_timing_profile.content_sha256,
        )
        digest = canonical_sha256(payload)
        return cls(
            "fbtrr_sha256_" + digest,
            digest,
            request.formal_request_id,
            request.content_sha256,
            spec.run_spec_id,
            spec.content_sha256,
            pure_result,
            ordered,
            request.engine_version,
            request.runtime_identity,
            request.rule_profile.profile_id,
            request.rule_profile.content_sha256,
            request.cost_policy.policy_id,
            request.cost_policy.content_sha256,
            request.execution_timing_profile.profile_id,
            request.execution_timing_profile.content_sha256,
        )

    @classmethod
    def _payload(
        cls,
        formal_request_id: str,
        formal_request_content_sha256: str,
        run_spec_id: str,
        run_spec_content_sha256: str,
        pure_result: BacktestRunResult,
        resolution_evidence: tuple[FormalResolutionEvidence, ...],
        engine_version: str,
        runtime_identity: RuntimeIdentity,
        rule_profile_id: str,
        rule_profile_sha256: str,
        cost_policy_id: str,
        cost_policy_sha256: str,
        execution_timing_profile_id: str,
        execution_timing_profile_sha256: str,
    ) -> dict[str, object]:
        return {
            "schema_version": cls.schema_version,
            "formal_request_id": formal_request_id,
            "formal_request_content_sha256": formal_request_content_sha256,
            "run_spec_id": run_spec_id,
            "run_spec_content_sha256": run_spec_content_sha256,
            "pure_result_id": pure_result.result_id,
            "pure_result_content_sha256": pure_result.content_sha256,
            "resolution_evidence": [item.to_wire() for item in resolution_evidence],
            "engine_version": engine_version,
            "runtime_identity": runtime_identity.to_wire(),
            "rule_profile_id": rule_profile_id,
            "rule_profile_sha256": rule_profile_sha256,
            "cost_policy_id": cost_policy_id,
            "cost_policy_sha256": cost_policy_sha256,
            "execution_timing_profile_id": execution_timing_profile_id,
            "execution_timing_profile_sha256": execution_timing_profile_sha256,
        }

    def assert_canonical(self) -> None:
        payload = self._payload(
            self.formal_request_id,
            self.formal_request_content_sha256,
            self.run_spec_id,
            self.run_spec_content_sha256,
            self.pure_result,
            self.resolution_evidence,
            self.engine_version,
            self.runtime_identity,
            self.rule_profile_id,
            self.rule_profile_sha256,
            self.cost_policy_id,
            self.cost_policy_sha256,
            self.execution_timing_profile_id,
            self.execution_timing_profile_sha256,
        )
        digest = canonical_sha256(payload)
        if self.content_sha256 != digest or self.formal_result_id != "fbtrr_sha256_" + digest:
            raise FormalBacktestPayloadError("formal result identity/content mismatch")

    def to_wire(self) -> dict[str, object]:
        return {
            "formal_result_id": self.formal_result_id,
            "content_sha256": self.content_sha256,
            **self._payload(
                self.formal_request_id,
                self.formal_request_content_sha256,
                self.run_spec_id,
                self.run_spec_content_sha256,
                self.pure_result,
                self.resolution_evidence,
                self.engine_version,
                self.runtime_identity,
                self.rule_profile_id,
                self.rule_profile_sha256,
                self.cost_policy_id,
                self.cost_policy_sha256,
                self.execution_timing_profile_id,
                self.execution_timing_profile_sha256,
            ),
        }


@dataclass(frozen=True, slots=True)
class FormalBacktestExecution:
    request: FormalBacktestRunRequest
    run_spec: BacktestRunSpec
    result: FormalBacktestRunResult


class FormalBacktestService:
    """Only A3 entry that can return a receipt-bound formal Backtest result."""

    def __init__(
        self,
        *,
        payload_resolver: CanonicalPayloadResolver,
        weight_resolver: RiskAdjustedWeightVectorResolver,
        engine: DeterministicAshareBacktestEngine | None = None,
    ) -> None:
        self._payload_resolver = payload_resolver
        self._weight_resolver = weight_resolver
        self._engine = engine or DeterministicAshareBacktestEngine()

    def execute(self, request: FormalBacktestRunRequest) -> FormalBacktestExecution:
        if not isinstance(request, FormalBacktestRunRequest):
            raise TypeError("formal Backtest requires FormalBacktestRunRequest")
        request.assert_canonical()

        resolved: list[tuple[BacktestPayloadReference, PayloadResolutionResult]] = []
        decoded: dict[str, dict[str, object]] = {}
        for reference in (
            request.snapshot,
            request.market_data,
            request.calendar,
            request.corporate_actions,
            request.universe,
        ):
            result = self._payload_resolver.resolve(reference.to_request())
            decoded[reference.payload_role] = self._decode(reference, result)
            resolved.append((reference, result))

        vectors: list[RiskAdjustedWeightVector] = []
        for scheduled_ref in request.scheduled_weights:
            reference = scheduled_ref.payload_reference
            result = self._payload_resolver.resolve(reference.to_request())
            wire = self._decode(reference, result)
            vector = self._weight_resolver.resolve(reference.owner_id)
            if vector is None:
                raise CanonicalWeightUnavailable(
                    f"Risk owner returned no vector: {reference.owner_id}"
                )
            if not isinstance(vector, RiskAdjustedWeightVector):
                raise TypeError("Risk owner returned a non-canonical weight object")
            vector.assert_canonical()
            if wire.get("risk_adjusted_weight_vector_id") != reference.owner_id:
                raise CanonicalWeightContentMismatch(
                    "verified Risk payload identifies a different vector"
                )
            if wire.get("content_sha256") != vector.content_sha256:
                raise CanonicalWeightContentMismatch(
                    "verified Risk payload content identity differs from owner object"
                )
            if canonical_json_bytes(vector.to_wire()) != result.verified_payload.payload:
                raise CanonicalWeightContentMismatch(
                    "canonical Risk owner object bytes differ from verified artifact bytes"
                )
            if scheduled_ref.effective_at != vector.source_target.rebalance_time:
                raise CanonicalWeightContentMismatch(
                    "scheduled effective_at differs from canonical Risk source target"
                )
            vectors.append(vector)
            resolved.append((reference, result))

        spec = self._build_spec(request, decoded, tuple(vectors), tuple(resolved))
        pure_result = self._engine.run(spec)
        evidence = tuple(
            FormalResolutionEvidence.from_result(reference, result)
            for reference, result in resolved
        )
        formal_result = FormalBacktestRunResult.create(
            request,
            spec,
            pure_result,
            evidence,
        )
        return FormalBacktestExecution(request, spec, formal_result)

    @staticmethod
    def _decode(
        reference: BacktestPayloadReference,
        result: PayloadResolutionResult,
    ) -> dict[str, object]:
        payload = result.verified_payload
        if payload.context_identity != reference.context_identity:
            raise FormalBacktestPayloadError("verified payload context mismatch")
        if payload.schema_fingerprint != reference.schema_fingerprint:
            raise FormalBacktestPayloadError(
                f"{reference.payload_role} schema fingerprint mismatch"
            )
        wire = _strict_json(payload.payload)
        if wire.get("schema_version") != reference.schema_fingerprint:
            raise FormalBacktestPayloadError(
                f"{reference.payload_role} schema version mismatch"
            )
        # The accepted W0 wire deliberately has no Backtest context field. Its
        # A3 context is owner-issued in the P1 binding and is cross-checked
        # against the vector's source Universe/effective time below.
        if (
            reference.payload_role != WEIGHT_ROLE
            and wire.get("context_identity") != reference.context_identity
        ):
            raise FormalBacktestPayloadError(
                f"{reference.payload_role} decoded context mismatch"
            )
        return wire

    @staticmethod
    def _build_spec(
        request: FormalBacktestRunRequest,
        decoded: dict[str, dict[str, object]],
        vectors: tuple[RiskAdjustedWeightVector, ...],
        resolved: tuple[tuple[BacktestPayloadReference, PayloadResolutionResult], ...],
    ) -> BacktestRunSpec:
        snapshot = _decode_snapshot(decoded[SNAPSHOT_ROLE], request)
        universe = _decode_universe(decoded[UNIVERSE_ROLE], request, snapshot)
        calendar = _decode_calendar(decoded[CALENDAR_ROLE], request, snapshot)
        market = _decode_market(decoded[MARKET_ROLE], request, snapshot, universe)
        actions = _decode_actions(
            decoded[CORPORATE_ACTION_ROLE], request, snapshot, universe
        )

        selected_sessions = tuple(
            item
            for item in calendar
            if request.session_start <= item[0] <= request.session_end
        )
        if not selected_sessions:
            raise FormalBacktestPayloadError("calendar has no sessions in requested range")
        if selected_sessions[0][0] != request.session_start:
            raise FormalBacktestPayloadError("session_start is absent from canonical calendar")
        if selected_sessions[-1][0] != request.session_end:
            raise FormalBacktestPayloadError("session_end is absent from canonical calendar")
        selected_dates = {item[0] for item in selected_sessions}
        if any(
            request.session_start <= action_date <= request.session_end
            and action_date not in selected_dates
            for action_date in actions
        ):
            raise FormalBacktestPayloadError(
                "corporate action in requested range is absent from canonical calendar"
            )

        instrument_ids = tuple(item[0] for item in universe)
        instrument_set = set(instrument_ids)
        for session_date, _ in selected_sessions:
            active = {
                instrument_id
                for instrument_id, _, effective_from, effective_to in universe
                if effective_from <= session_date
                and (effective_to is None or session_date < effective_to)
            }
            if active != instrument_set:
                raise FormalBacktestPayloadError(
                    "fixed-universe Backtest requires every member active on every session"
                )
        for vector in vectors:
            if set(vector.source_target.source.universe_instrument_ids) != instrument_set:
                raise FormalBacktestPayloadError(
                    "canonical Risk vector Universe differs from verified historical Universe"
                )

        market_keys = set(market)
        required_market_keys = {
            (session_date, instrument_id)
            for session_date, _ in selected_sessions
            for instrument_id in instrument_ids
        }
        if not required_market_keys.issubset(market_keys):
            raise FormalBacktestPayloadError(
                "market payload does not cover every calendar session and Universe member"
            )
        extra_selected = {
            key
            for key in market_keys
            if request.session_start <= key[0] <= request.session_end
            and key not in required_market_keys
        }
        if extra_selected:
            raise FormalBacktestPayloadError(
                "market payload contains out-of-Universe rows in the requested range"
            )

        sessions: list[MarketSession] = []
        for session_date, is_open in selected_sessions:
            states: list[DailyMarketState] = []
            for instrument_id, board, _, _ in universe:
                record = market[(session_date, instrument_id)]
                if record["board"] is not board:
                    raise FormalBacktestPayloadError(
                        "market board metadata differs from verified Universe"
                    )
                status: TradingStatus = record["open_trading_status"]
                session_available = record["session_available"]
                if is_open != session_available:
                    raise FormalBacktestPayloadError(
                        "market session availability differs from canonical calendar"
                    )
                if status is TradingStatus.DELISTED:
                    raise FormalBacktestPayloadError(
                        "verified Universe member cannot be DELISTED on an active membership session"
                    )
                tradable = is_open and status in {
                    TradingStatus.TRADING,
                    TradingStatus.LIMIT_UP,
                    TradingStatus.LIMIT_DOWN,
                }
                states.append(
                    DailyMarketState(
                        instrument_id=instrument_id,
                        raw_open=record["raw_open"],
                        raw_close=record["raw_close"],
                        suspended=status is TradingStatus.SUSPENDED,
                        tradable=tradable,
                        buy_restricted=record["buy_restricted"],
                        restricted_security=record["restricted_security"],
                        at_limit_up_open=status is TradingStatus.LIMIT_UP,
                        at_limit_down_open=status is TradingStatus.LIMIT_DOWN,
                        no_price_limit_session=record["no_price_limit_session"],
                    )
                )
            session_actions = tuple(actions.get(session_date, ()))
            sessions.append(MarketSession(session_date, is_open, tuple(states), session_actions))

        refs = [
            ExactInputReference(
                reference.exact_reference_kind,
                reference.owner_id,
                result.verified_payload.actual_sha256,
                PRE_ALPHA_CEILING,
            )
            for reference, result in resolved
        ]
        refs.extend(
            (
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
        )
        schedule = tuple(
            ScheduledWeights(item.effective_at, vector)
            for item, vector in zip(request.scheduled_weights, vectors, strict=True)
        )
        return BacktestRunSpec.create(
            initial_cash=request.initial_cash,
            initial_holdings=request.initial_holdings,
            instruments=tuple(
                InstrumentDefinition(instrument_id, board)
                for instrument_id, board, _, _ in universe
            ),
            sessions=tuple(sessions),
            schedule=schedule,
            rule_profile=request.rule_profile,
            cost_policy=request.cost_policy,
            execution_timing_profile=request.execution_timing_profile,
            exact_references=tuple(refs),
            runtime_identity=request.runtime_identity,
            engine_version=request.engine_version,
        )


def _decode_snapshot(
    wire: dict[str, object],
    request: FormalBacktestRunRequest,
) -> dict[str, object]:
    _keys(
        wire,
        {
            "schema_version",
            "context_identity",
            "snapshot_id",
            "knowledge_cutoff",
            "market_data_owner_id",
            "calendar_owner_id",
            "corporate_actions_owner_id",
            "universe_owner_id",
        },
        "snapshot payload",
    )
    if wire["snapshot_id"] != request.snapshot.owner_id:
        raise FormalBacktestPayloadError("snapshot owner ID mismatch")
    _datetime(wire["knowledge_cutoff"], "knowledge_cutoff")
    expected = {
        "market_data_owner_id": request.market_data.owner_id,
        "calendar_owner_id": request.calendar.owner_id,
        "corporate_actions_owner_id": request.corporate_actions.owner_id,
        "universe_owner_id": request.universe.owner_id,
    }
    if any(wire[key] != value for key, value in expected.items()):
        raise FormalBacktestPayloadError("snapshot payload cross-binding mismatch")
    return wire


def _decode_calendar(
    wire: dict[str, object],
    request: FormalBacktestRunRequest,
    snapshot: dict[str, object],
) -> tuple[tuple[date, bool], ...]:
    _keys(
        wire,
        {
            "schema_version",
            "context_identity",
            "calendar_version_id",
            "snapshot_id",
            "sessions",
        },
        "calendar payload",
    )
    if wire["calendar_version_id"] != request.calendar.owner_id:
        raise FormalBacktestPayloadError("calendar owner ID mismatch")
    if wire["snapshot_id"] != snapshot["snapshot_id"]:
        raise FormalBacktestPayloadError("calendar snapshot mismatch")
    sessions: list[tuple[date, bool]] = []
    for index, raw in enumerate(_require_list(wire["sessions"], "calendar.sessions")):
        item = _require_dict(raw, f"calendar.sessions[{index}]")
        _keys(item, {"session_date", "is_open"}, f"calendar.sessions[{index}]")
        sessions.append(
            (
                _date(item["session_date"], "session_date"),
                _require_bool(item["is_open"], "is_open"),
            )
        )
    if not sessions or tuple(sessions) != tuple(sorted(sessions, key=lambda item: item[0])):
        raise FormalBacktestPayloadError("calendar sessions must be non-empty and ordered")
    if len({item[0] for item in sessions}) != len(sessions):
        raise FormalBacktestPayloadError("calendar sessions must be unique")
    return tuple(sessions)


def _decode_universe(
    wire: dict[str, object],
    request: FormalBacktestRunRequest,
    snapshot: dict[str, object],
) -> tuple[tuple[str, Board, date, date | None], ...]:
    _keys(
        wire,
        {
            "schema_version",
            "context_identity",
            "universe_version_id",
            "snapshot_id",
            "instruments",
        },
        "universe payload",
    )
    if wire["universe_version_id"] != request.universe.owner_id:
        raise FormalBacktestPayloadError("Universe owner ID mismatch")
    if wire["snapshot_id"] != snapshot["snapshot_id"]:
        raise FormalBacktestPayloadError("Universe snapshot mismatch")
    instruments: list[tuple[str, Board, date, date | None]] = []
    for index, raw in enumerate(_require_list(wire["instruments"], "universe.instruments")):
        item = _require_dict(raw, f"universe.instruments[{index}]")
        _keys(
            item,
            {"instrument_id", "board", "effective_from", "effective_to"},
            f"universe.instruments[{index}]",
        )
        instrument_id = item["instrument_id"]
        if not isinstance(instrument_id, str):
            raise FormalBacktestPayloadError("instrument_id must be text")
        _text(instrument_id, "instrument_id")
        try:
            board = Board(item["board"])
        except (TypeError, ValueError) as exc:
            raise FormalBacktestPayloadError("Universe board is unsupported") from exc
        effective_from = _date(item["effective_from"], "effective_from")
        effective_to = (
            None if item["effective_to"] is None else _date(item["effective_to"], "effective_to")
        )
        if effective_to is not None and effective_to <= effective_from:
            raise FormalBacktestPayloadError("Universe membership interval is invalid")
        instruments.append((instrument_id, board, effective_from, effective_to))
    if not instruments or tuple(instruments) != tuple(sorted(instruments, key=lambda item: item[0])):
        raise FormalBacktestPayloadError("Universe instruments must be non-empty and ordered")
    if len({item[0] for item in instruments}) != len(instruments):
        raise FormalBacktestPayloadError("Universe instruments must be unique")
    return tuple(instruments)


def _decode_market(
    wire: dict[str, object],
    request: FormalBacktestRunRequest,
    snapshot: dict[str, object],
    universe: tuple[tuple[str, Board, date, date | None], ...],
) -> dict[tuple[date, str], dict[str, object]]:
    _keys(
        wire,
        {
            "schema_version",
            "context_identity",
            "market_data_version_id",
            "snapshot_id",
            "calendar_version_id",
            "universe_version_id",
            "records",
        },
        "market payload",
    )
    if wire["market_data_version_id"] != request.market_data.owner_id:
        raise FormalBacktestPayloadError("market-data owner ID mismatch")
    if wire["snapshot_id"] != snapshot["snapshot_id"]:
        raise FormalBacktestPayloadError("market snapshot mismatch")
    if wire["calendar_version_id"] != request.calendar.owner_id:
        raise FormalBacktestPayloadError("market calendar mismatch")
    if wire["universe_version_id"] != request.universe.owner_id:
        raise FormalBacktestPayloadError("market Universe mismatch")
    universe_boards = {item[0]: item[1] for item in universe}
    result: dict[tuple[date, str], dict[str, object]] = {}
    ordered_keys: list[tuple[date, str]] = []
    expected_keys = {
        "session_date",
        "instrument_id",
        "board",
        "raw_open",
        "raw_high",
        "raw_low",
        "raw_close",
        "volume",
        "amount",
        "open_trading_status",
        "session_available",
        "restricted_security",
        "buy_restricted",
        "no_price_limit_session",
    }
    for index, raw in enumerate(_require_list(wire["records"], "market.records")):
        item = _require_dict(raw, f"market.records[{index}]")
        _keys(item, expected_keys, f"market.records[{index}]")
        session_date = _date(item["session_date"], "session_date")
        instrument_id = item["instrument_id"]
        if not isinstance(instrument_id, str) or instrument_id not in universe_boards:
            raise FormalBacktestPayloadError("market instrument is outside verified Universe")
        try:
            board = Board(item["board"])
            status = TradingStatus(item["open_trading_status"])
        except (TypeError, ValueError) as exc:
            raise FormalBacktestPayloadError("market board/status is unsupported") from exc
        open_price = _decimal(item["raw_open"], "raw_open", positive=True)
        high = _decimal(item["raw_high"], "raw_high", positive=True)
        low = _decimal(item["raw_low"], "raw_low", positive=True)
        close = _decimal(item["raw_close"], "raw_close", positive=True)
        try:
            if _d(low) > min(_d(open_price), _d(close)) or _d(high) < max(
                _d(open_price), _d(close)
            ) or _d(low) > _d(high):
                raise FormalBacktestPayloadError("market OHLC envelope is inconsistent")
        except InvalidOperation as exc:
            raise FormalBacktestPayloadError("market OHLC is invalid") from exc
        record = {
            "board": board,
            "raw_open": open_price,
            "raw_close": close,
            "volume": _require_int(item["volume"], "volume", non_negative=True),
            "amount": _decimal(item["amount"], "amount"),
            "open_trading_status": status,
            "session_available": _require_bool(item["session_available"], "session_available"),
            "restricted_security": _require_bool(item["restricted_security"], "restricted_security"),
            "buy_restricted": _require_bool(item["buy_restricted"], "buy_restricted"),
            "no_price_limit_session": _require_bool(
                item["no_price_limit_session"], "no_price_limit_session"
            ),
        }
        key = (session_date, instrument_id)
        if key in result:
            raise FormalBacktestPayloadError("market records must be unique")
        result[key] = record
        ordered_keys.append(key)
    if not result or ordered_keys != sorted(ordered_keys):
        raise FormalBacktestPayloadError("market records must be non-empty and ordered")
    return result


def _decode_actions(
    wire: dict[str, object],
    request: FormalBacktestRunRequest,
    snapshot: dict[str, object],
    universe: tuple[tuple[str, Board, date, date | None], ...],
) -> dict[date, tuple[CorporateAction, ...]]:
    _keys(
        wire,
        {
            "schema_version",
            "context_identity",
            "corporate_action_set_id",
            "snapshot_id",
            "events",
        },
        "corporate-action payload",
    )
    if wire["corporate_action_set_id"] != request.corporate_actions.owner_id:
        raise FormalBacktestPayloadError("corporate-action owner ID mismatch")
    if wire["snapshot_id"] != snapshot["snapshot_id"]:
        raise FormalBacktestPayloadError("corporate-action snapshot mismatch")
    instrument_ids = {item[0] for item in universe}
    events: list[CorporateAction] = []
    expected_keys = {
        "action_id",
        "instrument_id",
        "ex_date",
        "action_type",
        "cash_per_share",
        "ratio_numerator",
        "ratio_denominator",
    }
    for index, raw in enumerate(_require_list(wire["events"], "corporate_actions.events")):
        item = _require_dict(raw, f"corporate_actions.events[{index}]")
        _keys(item, expected_keys, f"corporate_actions.events[{index}]")
        instrument_id = item["instrument_id"]
        if not isinstance(instrument_id, str) or instrument_id not in instrument_ids:
            raise FormalBacktestPayloadError("corporate action is outside verified Universe")
        try:
            action_type = CorporateActionType(item["action_type"])
        except (TypeError, ValueError) as exc:
            raise FormalBacktestPayloadError("corporate-action type is unsupported") from exc
        action_id = item["action_id"]
        if not isinstance(action_id, str):
            raise FormalBacktestPayloadError("action_id must be text")
        events.append(
            CorporateAction(
                action_id=action_id,
                instrument_id=instrument_id,
                ex_date=_date(item["ex_date"], "ex_date"),
                action_type=action_type,
                cash_per_share=_decimal(item["cash_per_share"], "cash_per_share"),
                ratio_numerator=_require_int(item["ratio_numerator"], "ratio_numerator"),
                ratio_denominator=_require_int(item["ratio_denominator"], "ratio_denominator"),
            )
        )
    if events != sorted(events, key=lambda item: (item.ex_date, item.action_id)):
        raise FormalBacktestPayloadError("corporate actions must be canonically ordered")
    if len({item.action_id for item in events}) != len(events):
        raise FormalBacktestPayloadError("corporate-action IDs must be unique")
    grouped: dict[date, list[CorporateAction]] = {}
    for event in events:
        grouped.setdefault(event.ex_date, []).append(event)
    return {key: tuple(value) for key, value in grouped.items()}


__all__ = [
    "CALENDAR_ROLE",
    "CALENDAR_SCHEMA",
    "CORPORATE_ACTION_ROLE",
    "CORPORATE_ACTION_SCHEMA",
    "CanonicalWeightContentMismatch",
    "CanonicalWeightUnavailable",
    "FormalBacktestExecution",
    "FormalBacktestPayloadError",
    "FormalBacktestRunRequest",
    "FormalBacktestRunResult",
    "FormalBacktestService",
    "FormalResolutionEvidence",
    "MARKET_ROLE",
    "MARKET_SCHEMA",
    "SNAPSHOT_ROLE",
    "SNAPSHOT_SCHEMA",
    "ScheduledWeightPayloadReference",
    "BacktestPayloadReference",
    "UNIVERSE_ROLE",
    "UNIVERSE_SCHEMA",
    "WEIGHT_ROLE",
    "RiskAdjustedWeightVectorResolver",
]
