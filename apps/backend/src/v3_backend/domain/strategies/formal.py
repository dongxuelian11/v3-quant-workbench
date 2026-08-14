"""Formal Strategy evaluation over score bytes admitted by the shared P1 resolver."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from types import MappingProxyType

from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    UpstreamRequirement,
    propagate_downstream_ceiling,
)
from v3_backend.domain.payload_authority import (
    CanonicalPayloadResolver,
    PayloadResolutionRequest,
    PayloadResolutionResult,
)
from v3_backend.adapters.sqlite.repositories import SQLiteRepositoryRegistry
from v3_backend.domain.payload_authority.ports import VerifiedArtifactByteReader
from v3_backend.repositories.unit_of_work import TransactionMode
from v3_backend.provenance.canonical_hash import canonical_sha256

from .artifacts import (
    InputArtifactEvidence,
    PortfolioIntent,
    SelectionArtifact,
    SignalArtifact,
    _strategy_output_truth,
)
from .binding import (
    BoundInputReference,
    ExternalReferenceResolution,
    StrategyEvaluationBindingVersion,
)
from .evaluator import CrossSectionInputArtifact, DeterministicStrategyEvaluator, StrategyEvaluationResult
from .ir import StrategyDefinitionVersion, normalize_decimal_string


FORMAL_EVALUATION_CONTRACT_VERSION = "v3.strategy-formal-evaluation/1.0.0"
SCORE_PAYLOAD_SCHEMA_VERSION = "v3.strategy-score-vector/1.0.0"
SCORE_PAYLOAD_ROLE = "STRATEGY_SCORE_VECTOR"
SCORE_PAYLOAD_SCHEMA_FINGERPRINT = "schema_sha256_" + canonical_sha256(
    {
        "schema_version": SCORE_PAYLOAD_SCHEMA_VERSION,
        "ordered_fields": [
            "schema_version",
            "strategy_definition_version_id",
            "binding_key",
            "payload_role",
            "decision_time",
            "universe_version_id",
            "membership_artifact_id",
            "membership_sha256",
            "instrument_ids",
            "values",
        ],
        "values": "finite decimal string or null, positionally aligned to instrument_ids",
    }
)


class FormalStrategyEvaluationError(ValueError):
    """Formal input/context/provenance admission failed before output publication."""


def _wire_time(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FormalStrategyEvaluationError("decision_time must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def strategy_payload_context_identity(
    *,
    definition: StrategyDefinitionVersion,
    binding: StrategyEvaluationBindingVersion,
    input_reference: BoundInputReference,
    decision_time: datetime,
) -> str:
    """Exact material Strategy context supplied to P1 by the Strategy owner."""

    return "strategy_ctx_sha256_" + canonical_sha256(
        {
            "contract_version": FORMAL_EVALUATION_CONTRACT_VERSION,
            "strategy_definition_version_id": definition.strategy_definition_version_id,
            "strategy_evaluation_binding_version_id": binding.strategy_evaluation_binding_version_id,
            "dataset_version_id": binding.dataset_version_id,
            "factor_evaluation_ids": list(binding.factor_evaluation_ids),
            "feature_materialization_ids": list(binding.feature_materialization_ids),
            "binding_key": input_reference.binding_key,
            "artifact_kind": input_reference.artifact_kind,
            "source_id": input_reference.source_id,
            "artifact_id": input_reference.artifact_id,
            "content_sha256": input_reference.content_sha256,
            "snapshot": binding.snapshot.to_wire(),
            "universe": binding.universe.to_wire(),
            "period": binding.period.to_wire(),
            "knowledge_cutoff": _wire_time(binding.knowledge_cutoff),
            "calendar": binding.calendar.to_wire(),
            "decision_time": _wire_time(decision_time),
            "compiler_version": binding.compiler_version,
            "runtime_profile_id": binding.runtime_profile_id,
            "environment_fingerprint": binding.environment_fingerprint,
        }
    )


@dataclass(frozen=True, slots=True)
class FormalStrategyInputRequest:
    """Untrusted resolution intent; numeric values are deliberately absent."""

    binding_key: str
    owner_namespace: str
    owner_id: str
    owner_version: str
    payload_role: str
    decision_time: datetime
    max_bytes: int
    expected_schema_fingerprint: str = SCORE_PAYLOAD_SCHEMA_FINGERPRINT

    def __post_init__(self) -> None:
        for name in (
            "binding_key",
            "owner_namespace",
            "owner_id",
            "owner_version",
            "payload_role",
            "expected_schema_fingerprint",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise FormalStrategyEvaluationError(f"{name} must be exact non-empty text")
        _wire_time(self.decision_time)
        if (
            not isinstance(self.max_bytes, int)
            or isinstance(self.max_bytes, bool)
            or self.max_bytes <= 0
        ):
            raise FormalStrategyEvaluationError("max_bytes must be a positive integer")


@dataclass(frozen=True, slots=True)
class FormalStrategyEvaluationRequest:
    definition: StrategyDefinitionVersion
    binding: StrategyEvaluationBindingVersion
    inputs: tuple[FormalStrategyInputRequest, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.definition, StrategyDefinitionVersion):
            raise TypeError("definition must be StrategyDefinitionVersion")
        if not isinstance(self.binding, StrategyEvaluationBindingVersion):
            raise TypeError("binding must be StrategyEvaluationBindingVersion")
        if self.binding.strategy_definition_version_id != self.definition.strategy_definition_version_id:
            raise FormalStrategyEvaluationError("definition/binding identity mismatch")
        if not self.inputs or any(
            not isinstance(value, FormalStrategyInputRequest) for value in self.inputs
        ):
            raise FormalStrategyEvaluationError(
                "formal request requires typed input resolution intents"
            )


def encode_score_payload(
    *,
    definition: StrategyDefinitionVersion,
    binding: StrategyEvaluationBindingVersion,
    binding_key: str,
    decision_time: datetime,
    values: tuple[str | None, ...],
) -> bytes:
    """Canonical test/owner helper; publication still belongs to the Artifact Store."""

    if len(values) != len(binding.universe.instrument_ids):
        raise FormalStrategyEvaluationError("score values must match exact Universe length")
    normalized: list[str | None] = []
    for value in values:
        if value is None:
            normalized.append(None)
            continue
        try:
            decimal = Decimal(value)
        except (InvalidOperation, TypeError) as exc:
            raise FormalStrategyEvaluationError("score value must be a decimal string") from exc
        if not decimal.is_finite():
            raise FormalStrategyEvaluationError("score value must be finite")
        normalized.append(normalize_decimal_string(value, "score value"))
    payload = {
        "schema_version": SCORE_PAYLOAD_SCHEMA_VERSION,
        "strategy_definition_version_id": definition.strategy_definition_version_id,
        "binding_key": binding_key,
        "payload_role": SCORE_PAYLOAD_ROLE,
        "decision_time": _wire_time(decision_time),
        "universe_version_id": binding.universe.universe_version_id,
        "membership_artifact_id": binding.universe.membership_artifact_id,
        "membership_sha256": binding.universe.membership_sha256,
        "instrument_ids": list(binding.universe.instrument_ids),
        "values": normalized,
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _decode_score_payload(
    *,
    resolution: PayloadResolutionResult,
    definition: StrategyDefinitionVersion,
    binding: StrategyEvaluationBindingVersion,
    input_reference: BoundInputReference,
    request: FormalStrategyInputRequest,
    context_identity: str,
) -> CrossSectionInputArtifact:
    payload = resolution.verified_payload
    receipt = resolution.receipt
    if payload.context_identity != context_identity or receipt.context_identity != context_identity:
        raise FormalStrategyEvaluationError("P1 result context identity mismatch")
    if payload.artifact_id != input_reference.artifact_id or payload.actual_sha256 != input_reference.content_sha256:
        raise FormalStrategyEvaluationError("P1 result does not match exact Strategy input reference")
    if payload.schema_fingerprint != request.expected_schema_fingerprint:
        raise FormalStrategyEvaluationError("verified score payload schema fingerprint mismatch")
    try:
        decoded = json.loads(payload.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FormalStrategyEvaluationError("verified score payload is not canonical JSON") from exc
    expected_keys = {
        "schema_version",
        "strategy_definition_version_id",
        "binding_key",
        "payload_role",
        "decision_time",
        "universe_version_id",
        "membership_artifact_id",
        "membership_sha256",
        "instrument_ids",
        "values",
    }
    if not isinstance(decoded, dict) or set(decoded) != expected_keys:
        raise FormalStrategyEvaluationError("score payload fields do not match the exact schema")
    expected_scalars = {
        "schema_version": SCORE_PAYLOAD_SCHEMA_VERSION,
        "strategy_definition_version_id": definition.strategy_definition_version_id,
        "binding_key": input_reference.binding_key,
        "payload_role": request.payload_role,
        "decision_time": _wire_time(request.decision_time),
        "universe_version_id": binding.universe.universe_version_id,
        "membership_artifact_id": binding.universe.membership_artifact_id,
        "membership_sha256": binding.universe.membership_sha256,
    }
    for name, expected in expected_scalars.items():
        if decoded[name] != expected:
            raise FormalStrategyEvaluationError(f"score payload {name} mismatch")
    if decoded["instrument_ids"] != list(binding.universe.instrument_ids):
        raise FormalStrategyEvaluationError("score payload Universe/instrument order mismatch")
    raw_values = decoded["values"]
    if not isinstance(raw_values, list) or len(raw_values) != len(binding.universe.instrument_ids):
        raise FormalStrategyEvaluationError("score payload values do not align to Universe")
    values: dict[str, str | None] = {}
    for instrument_id, raw in zip(binding.universe.instrument_ids, raw_values, strict=True):
        if raw is None:
            values[instrument_id] = None
            continue
        if not isinstance(raw, str):
            raise FormalStrategyEvaluationError("score payload values must be decimal strings or null")
        try:
            decimal = Decimal(raw)
        except InvalidOperation as exc:
            raise FormalStrategyEvaluationError("score payload value is not decimal") from exc
        if not decimal.is_finite():
            raise FormalStrategyEvaluationError("score payload value must be finite")
        canonical = normalize_decimal_string(raw, "score payload value")
        if canonical != raw:
            raise FormalStrategyEvaluationError("score payload decimal value is not canonical")
        values[instrument_id] = canonical
    return CrossSectionInputArtifact(
        binding_key=input_reference.binding_key,
        artifact_id=payload.artifact_id,
        content_sha256=payload.actual_sha256,
        decision_time=request.decision_time,
        values=values,
    )


class FormalStrategyEvaluationService:
    """The only Strategy path that can mint P1-receipt-bound formal outputs."""

    contract_version = FORMAL_EVALUATION_CONTRACT_VERSION

    def __init__(
        self,
        *,
        repositories: SQLiteRepositoryRegistry,
        byte_reader: VerifiedArtifactByteReader,
        evaluator: DeterministicStrategyEvaluator | None = None,
    ) -> None:
        if not isinstance(repositories, SQLiteRepositoryRegistry):
            raise TypeError("repositories must be SQLiteRepositoryRegistry")
        if not repositories.artifact.uow.active or repositories.artifact.uow.mode is not TransactionMode.READ_ONLY:
            raise FormalStrategyEvaluationError(
                "formal evaluation requires an active READ_ONLY canonical Catalog"
            )
        if not hasattr(byte_reader, "read_bytes"):
            raise TypeError("byte_reader must implement VerifiedArtifactByteReader")
        self._repositories = repositories
        self._byte_reader = byte_reader
        self._evaluator = evaluator or DeterministicStrategyEvaluator()

    def evaluate(self, request: FormalStrategyEvaluationRequest) -> StrategyEvaluationResult:
        if not isinstance(request, FormalStrategyEvaluationRequest):
            raise TypeError("formal evaluation requires FormalStrategyEvaluationRequest")
        if request.binding.generic_artifact_references:
            if any(
                value.resolution is ExternalReferenceResolution.UNRESOLVED_CALLER_ASSERTED
                for value in request.binding.generic_artifact_references
            ):
                raise FormalStrategyEvaluationError(
                    "UNRESOLVED_CALLER_ASSERTED inputs are NON_FORMAL and cannot enter formal evaluation"
                )
        if not request.binding.canonical_owner_references:
            raise FormalStrategyEvaluationError(
                "formal evaluation requires canonical owner reference intent"
            )
        from v3_backend.adapters.strategy_payload import StrategyPayloadBindingResolver

        payload_resolver = CanonicalPayloadResolver(
            binding_resolver=StrategyPayloadBindingResolver(
                binding=request.binding,
                repositories=self._repositories,
            ),
            byte_reader=self._byte_reader,
        )
        references = {value.binding_key: value for value in request.binding.input_references}
        intents = {value.binding_key: value for value in request.inputs}
        if len(intents) != len(request.inputs) or set(intents) != set(references):
            raise FormalStrategyEvaluationError(
                "formal input intents must exactly match Strategy binding inputs"
            )
        runtime_inputs: list[CrossSectionInputArtifact] = []
        evidence: list[InputArtifactEvidence] = []
        for binding_key in sorted(references):
            reference = references[binding_key]
            intent = intents[binding_key]
            if intent.owner_id != reference.source_id:
                raise FormalStrategyEvaluationError("formal input owner does not match bound source")
            if intent.payload_role != SCORE_PAYLOAD_ROLE:
                raise FormalStrategyEvaluationError("formal input payload role is unsupported")
            if not request.binding.period.start <= intent.decision_time <= request.binding.period.end:
                raise FormalStrategyEvaluationError("decision_time is outside bound period")
            if intent.decision_time > request.binding.knowledge_cutoff:
                raise FormalStrategyEvaluationError("decision_time exceeds knowledge cutoff")
            context_identity = strategy_payload_context_identity(
                definition=request.definition,
                binding=request.binding,
                input_reference=reference,
                decision_time=intent.decision_time,
            )
            resolution = payload_resolver.resolve(
                PayloadResolutionRequest(
                    owner_namespace=intent.owner_namespace,
                    owner_id=intent.owner_id,
                    owner_version=intent.owner_version,
                    payload_role=intent.payload_role,
                    context_identity=context_identity,
                    max_bytes=intent.max_bytes,
                )
            )
            runtime_inputs.append(
                _decode_score_payload(
                    resolution=resolution,
                    definition=request.definition,
                    binding=request.binding,
                    input_reference=reference,
                    request=intent,
                    context_identity=context_identity,
                )
            )
            evidence.append(
                InputArtifactEvidence.from_resolution(
                    binding_key=binding_key,
                    resolution=resolution,
                    canonical_owner_namespace=intent.owner_namespace,
                    canonical_owner_id=intent.owner_id,
                    canonical_owner_version=intent.owner_version,
                    payload_role=intent.payload_role,
                )
            )
        pure = self._evaluator.evaluate(
            definition=request.definition,
            binding=request.binding,
            inputs=tuple(runtime_inputs),
        )
        ordered_evidence = tuple(evidence)
        def materialize(cls, /, **values):
            expected = {value.name for value in cls.__dataclass_fields__.values()}
            if set(values) != expected:
                raise FormalStrategyEvaluationError(
                    "formal Strategy output materialization fields are incomplete"
                )
            artifact = object.__new__(cls)
            for name, value in values.items():
                object.__setattr__(artifact, name, value)
            post_init = getattr(artifact, "__post_init__", None)
            if post_init is not None:
                post_init()
            return artifact

        # Formal objects are constructed only inside this live execution path.
        # No artifact/evidence factory accepts caller-supplied proof.  Every call
        # above has just re-established Catalog owner authority and P1 bytes.
        signal: SignalArtifact | None = None
        if pure.signal_artifact is not None:
            signal_truth = _strategy_output_truth(
                definition=request.definition,
                binding=request.binding,
                input_artifacts=ordered_evidence,
            )
            signal_provenance = {
                "strategy_definition_version_id": request.definition.strategy_definition_version_id,
                "strategy_evaluation_binding_version_id": request.binding.strategy_evaluation_binding_version_id,
                "input_artifacts": [value.to_wire() for value in ordered_evidence],
                "compiler_version": request.definition.compiler_version,
                "runtime_profile_id": request.definition.runtime_profile_id,
                "universe_version_id": request.binding.universe.universe_version_id,
                "membership_sha256": request.binding.universe.membership_sha256,
                "formal_execution_contract_version": self.contract_version,
            }
            signal_provenance_sha256 = canonical_sha256(signal_provenance)
            signal_payload = {
                **signal_provenance,
                "decision_time": _wire_time(pure.signal_artifact.decision_time),
                "rows": [value.to_wire() for value in pure.signal_artifact.rows],
                "missing_instrument_ids": list(pure.signal_artifact.missing_instrument_ids),
                "truth_admission": signal_truth.to_wire(),
                "provenance_sha256": signal_provenance_sha256,
            }
            signal = materialize(
                SignalArtifact,
                signal_artifact_id="sig_sha256_" + canonical_sha256(signal_payload),
                strategy_definition_version_id=request.definition.strategy_definition_version_id,
                strategy_evaluation_binding_version_id=request.binding.strategy_evaluation_binding_version_id,
                input_artifacts=ordered_evidence,
                decision_time=pure.signal_artifact.decision_time,
                rows=pure.signal_artifact.rows,
                missing_instrument_ids=pure.signal_artifact.missing_instrument_ids,
                truth_admission=signal_truth,
                compiler_version=request.definition.compiler_version,
                runtime_profile_id=request.definition.runtime_profile_id,
                provenance_sha256=signal_provenance_sha256,
                formal_execution_contract_version=self.contract_version,
            )
        selection: SelectionArtifact | None = None
        if pure.selection_artifact is not None:
            if signal is None:
                raise FormalStrategyEvaluationError(
                    "formal SelectionArtifact requires exact live SignalArtifact"
                )
            selection_truth = _strategy_output_truth(
                definition=request.definition,
                binding=request.binding,
                input_artifacts=ordered_evidence,
                extra_requirements=(
                    UpstreamRequirement(signal.signal_artifact_id, signal.truth_admission),
                ),
            )
            selection_provenance = {
                "strategy_definition_version_id": request.definition.strategy_definition_version_id,
                "strategy_evaluation_binding_version_id": request.binding.strategy_evaluation_binding_version_id,
                "input_artifacts": [value.to_wire() for value in ordered_evidence],
                "universe_version_id": request.binding.universe.universe_version_id,
                "membership_artifact_id": request.binding.universe.membership_artifact_id,
                "membership_sha256": request.binding.universe.membership_sha256,
                "source_signal_artifact_id": signal.signal_artifact_id,
                "source_signal_provenance_sha256": signal.provenance_sha256,
                "formal_execution_contract_version": self.contract_version,
            }
            selection_provenance_sha256 = canonical_sha256(selection_provenance)
            selection_payload = {
                **selection_provenance,
                "entries": [value.to_wire() for value in pure.selection_artifact.entries],
                "excluded_instrument_ids": list(pure.selection_artifact.excluded_instrument_ids),
                "truth_admission": selection_truth.to_wire(),
                "provenance_sha256": selection_provenance_sha256,
            }
            selection = materialize(
                SelectionArtifact,
                selection_artifact_id="sel_sha256_" + canonical_sha256(selection_payload),
                strategy_definition_version_id=request.definition.strategy_definition_version_id,
                strategy_evaluation_binding_version_id=request.binding.strategy_evaluation_binding_version_id,
                universe_version_id=request.binding.universe.universe_version_id,
                membership_artifact_id=request.binding.universe.membership_artifact_id,
                membership_sha256=request.binding.universe.membership_sha256,
                input_artifacts=ordered_evidence,
                entries=pure.selection_artifact.entries,
                excluded_instrument_ids=pure.selection_artifact.excluded_instrument_ids,
                truth_admission=selection_truth,
                provenance_sha256=selection_provenance_sha256,
                source_signal_artifact_id=signal.signal_artifact_id,
                source_signal_provenance_sha256=signal.provenance_sha256,
                formal_execution_contract_version=self.contract_version,
            )
        intent: PortfolioIntent | None = None
        if pure.portfolio_intent is not None:
            if selection is None:
                raise FormalStrategyEvaluationError(
                    "formal PortfolioIntent requires formal SelectionArtifact"
                )
            if signal is None:
                raise FormalStrategyEvaluationError(
                    "formal PortfolioIntent requires exact live SignalArtifact"
                )
            intent_truth = propagate_downstream_ceiling(
                FORMAL_ADMITTED_CEILING,
                (
                    UpstreamRequirement(request.definition.strategy_definition_version_id, request.definition.truth_admission),
                    UpstreamRequirement(request.binding.strategy_evaluation_binding_version_id, request.binding.truth_admission),
                    UpstreamRequirement(selection.selection_artifact_id, selection.truth_admission),
                    UpstreamRequirement(signal.signal_artifact_id, signal.truth_admission),
                ),
            )
            intent_provenance = {
                "strategy_definition_version_id": request.definition.strategy_definition_version_id,
                "strategy_evaluation_binding_version_id": request.binding.strategy_evaluation_binding_version_id,
                "source_signal_artifact_id": signal.signal_artifact_id,
                "source_selection_artifact_id": selection.selection_artifact_id,
                "source_signal_provenance_sha256": signal.provenance_sha256,
                "source_selection_provenance_sha256": selection.provenance_sha256,
                "input_artifacts": [value.to_wire() for value in ordered_evidence],
                "publisher_boundary": "PORTFOLIO_SERVICE_IS_SOLE_TARGET_WEIGHT_VECTOR_PUBLISHER",
            }
            intent_provenance_sha256 = canonical_sha256(intent_provenance)
            intent_payload = {
                **intent_provenance,
                "exposure_mode": pure.portfolio_intent.exposure_mode,
                "cash_policy": pure.portfolio_intent.cash_policy,
                "rebalance_intent": pure.portfolio_intent.rebalance_intent,
                "items": [value.to_wire() for value in pure.portfolio_intent.items],
                "constraints": dict(pure.portfolio_intent.constraints),
                "truth_admission": intent_truth.to_wire(),
                "provenance_sha256": intent_provenance_sha256,
            }
            intent = materialize(
                PortfolioIntent,
                portfolio_intent_id="pint_sha256_" + canonical_sha256(intent_payload),
                strategy_definition_version_id=request.definition.strategy_definition_version_id,
                strategy_evaluation_binding_version_id=request.binding.strategy_evaluation_binding_version_id,
                source_signal_artifact_id=signal.signal_artifact_id,
                source_selection_artifact_id=selection.selection_artifact_id,
                source_signal_provenance_sha256=signal.provenance_sha256,
                source_selection_provenance_sha256=selection.provenance_sha256,
                input_artifacts=ordered_evidence,
                exposure_mode=pure.portfolio_intent.exposure_mode,
                cash_policy=pure.portfolio_intent.cash_policy,
                rebalance_intent=pure.portfolio_intent.rebalance_intent,
                items=pure.portfolio_intent.items,
                constraints=MappingProxyType(dict(pure.portfolio_intent.constraints)),
                truth_admission=intent_truth,
                provenance_sha256=intent_provenance_sha256,
                formal_execution_contract_version=self.contract_version,
            )
        return StrategyEvaluationResult(signal, selection, intent)


__all__ = (
    "FORMAL_EVALUATION_CONTRACT_VERSION",
    "SCORE_PAYLOAD_ROLE",
    "SCORE_PAYLOAD_SCHEMA_FINGERPRINT",
    "SCORE_PAYLOAD_SCHEMA_VERSION",
    "FormalStrategyEvaluationError",
    "FormalStrategyEvaluationRequest",
    "FormalStrategyEvaluationService",
    "FormalStrategyInputRequest",
    "encode_score_payload",
    "strategy_payload_context_identity",
)
