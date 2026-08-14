"""Strict canonical JSON codecs for persisted W0 weight artifacts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from v3_backend.contracts.common.truth_admission import TruthAdmissionState
from v3_backend.provenance.canonical_hash import canonical_json

from .model import (
    PortfolioIntentSource,
    ReferenceKind,
    RiskAdjustedWeightVector,
    RiskApplicationReceipt,
    RiskDecision,
    RiskDecisionReason,
    RiskStageEvidence,
    RuntimeIdentity,
    TargetWeightRow,
    TargetWeightVector,
    UnresolvedExactReference,
    WeightContractError,
)


MAX_WEIGHT_ARTIFACT_BYTES = 16 * 1024 * 1024


def canonical_weight_bytes(
    value: TargetWeightVector | RiskApplicationReceipt | RiskAdjustedWeightVector,
) -> bytes:
    if not isinstance(
        value,
        (TargetWeightVector, RiskApplicationReceipt, RiskAdjustedWeightVector),
    ):
        raise TypeError("canonical weight bytes require a W0 weight artifact")
    return canonical_json(value.to_wire()).encode("utf-8")


def _closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WeightContractError(f"duplicate canonical JSON key: {key}")
        result[key] = value
    return result


def _parse(payload: bytes) -> dict[str, Any]:
    if not isinstance(payload, bytes):
        raise TypeError("canonical artifact payload must be bytes")
    if len(payload) > MAX_WEIGHT_ARTIFACT_BYTES:
        raise WeightContractError("weight artifact exceeds the canonical read bound")
    try:
        parsed = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_closed_object,
            parse_float=lambda value: (_ for _ in ()).throw(
                ValueError("floating-point JSON numbers are forbidden")
            ),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError("non-finite JSON values are forbidden")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise WeightContractError("invalid canonical weight JSON") from exc
    if not isinstance(parsed, dict):
        raise WeightContractError("canonical weight artifact must be an object")
    if canonical_json(parsed).encode("utf-8") != payload:
        raise WeightContractError("weight artifact bytes are not canonical JSON")
    return parsed


def _object(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WeightContractError(f"{field} must be an object")
    return value


def _array(value: object, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise WeightContractError(f"{field} must be an array")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise WeightContractError(f"{field} must be non-empty text")
    return value


def _instant(value: object, field: str) -> datetime:
    text = _text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WeightContractError(f"{field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise WeightContractError(f"{field} must be timezone-aware")
    return parsed


def _truth(value: object) -> TruthAdmissionState:
    return TruthAdmissionState.from_wire(value)


def _runtime(value: object) -> RuntimeIdentity:
    wire = _object(value, "runtime_identity")
    return RuntimeIdentity(
        code_version=_text(wire.get("code_version"), "code_version"),
        runtime_profile_id=_text(
            wire.get("runtime_profile_id"), "runtime_profile_id"
        ),
        environment_fingerprint=_text(
            wire.get("environment_fingerprint"), "environment_fingerprint"
        ),
    )


def _reference(value: object) -> UnresolvedExactReference:
    wire = _object(value, "exact_reference")
    try:
        kind = ReferenceKind(_text(wire.get("reference_kind"), "reference_kind"))
    except ValueError as exc:
        raise WeightContractError("unknown exact reference kind") from exc
    return UnresolvedExactReference(
        reference_kind=kind,
        source_id=_text(wire.get("source_id"), "source_id"),
        content_sha256=_text(wire.get("content_sha256"), "content_sha256"),
        truth_admission=_truth(wire.get("truth_admission")),
        owner_receipt_resolution=_text(
            wire.get("owner_receipt_resolution"), "owner_receipt_resolution"
        ),
    )


def _source(value: object) -> PortfolioIntentSource:
    wire = _object(value, "source")
    members = tuple(
        _text(item, "universe_instrument_id")
        for item in _array(wire.get("universe_instrument_ids"), "universe_instrument_ids")
    )
    source = PortfolioIntentSource(
        portfolio_intent_id=_text(
            wire.get("portfolio_intent_id"), "portfolio_intent_id"
        ),
        portfolio_intent_content_sha256=_text(
            wire.get("portfolio_intent_content_sha256"),
            "portfolio_intent_content_sha256",
        ),
        portfolio_intent_provenance_sha256=_text(
            wire.get("portfolio_intent_provenance_sha256"),
            "portfolio_intent_provenance_sha256",
        ),
        strategy_definition_version_id=_text(
            wire.get("strategy_definition_version_id"),
            "strategy_definition_version_id",
        ),
        strategy_definition_content_sha256=_text(
            wire.get("strategy_definition_content_sha256"),
            "strategy_definition_content_sha256",
        ),
        strategy_evaluation_binding_version_id=_text(
            wire.get("strategy_evaluation_binding_version_id"),
            "strategy_evaluation_binding_version_id",
        ),
        strategy_evaluation_binding_content_sha256=_text(
            wire.get("strategy_evaluation_binding_content_sha256"),
            "strategy_evaluation_binding_content_sha256",
        ),
        universe_version_id=_text(
            wire.get("universe_version_id"), "universe_version_id"
        ),
        universe_definition_sha256=_text(
            wire.get("universe_definition_sha256"), "universe_definition_sha256"
        ),
        membership_artifact_id=_text(
            wire.get("membership_artifact_id"), "membership_artifact_id"
        ),
        membership_sha256=_text(
            wire.get("membership_sha256"), "membership_sha256"
        ),
        universe_instrument_ids=members,
        source_reference_sha256=_text(
            wire.get("source_reference_sha256"), "source_reference_sha256"
        ),
        truth_admission=_truth(wire.get("truth_admission")),
        owner_receipt_resolution=_text(
            wire.get("owner_receipt_resolution"), "owner_receipt_resolution"
        ),
    )
    source.assert_canonical()
    return source


def target_weight_vector_from_bytes(payload: bytes) -> TargetWeightVector:
    wire = _parse(payload)
    if wire.get("artifact_type") != "TargetWeightVector":
        raise WeightContractError("artifact is not a TargetWeightVector")
    source = _source(wire.get("source"))
    target = TargetWeightVector.create(
        source=source,
        construction_spec=_reference(wire.get("construction_spec")),
        evidence_refs=tuple(
            _reference(item)
            for item in _array(wire.get("evidence_refs"), "evidence_refs")
        ),
        runtime_identity=_runtime(wire.get("runtime_identity")),
        base_currency=_text(wire.get("base_currency"), "base_currency"),
        as_of=_instant(wire.get("as_of"), "as_of"),
        decision_time=_instant(wire.get("decision_time"), "decision_time"),
        rebalance_time=_instant(wire.get("rebalance_time"), "rebalance_time"),
        valid_until=_instant(wire.get("valid_until"), "valid_until"),
        cash_weight=_text(wire.get("cash_weight"), "cash_weight"),
        rows=tuple(
            TargetWeightRow(
                _text(_object(item, "row").get("instrument_id"), "instrument_id"),
                _text(_object(item, "row").get("target_weight"), "target_weight"),
            )
            for item in _array(wire.get("rows"), "rows")
        ),
    )
    if target.to_wire() != wire:
        raise WeightContractError("TargetWeightVector wire/identity mismatch")
    return target


def risk_application_receipt_from_bytes(
    payload: bytes,
    *,
    source_target: TargetWeightVector,
) -> RiskApplicationReceipt:
    wire = _parse(payload)
    if wire.get("artifact_type") != "RiskApplicationReceipt":
        raise WeightContractError("artifact is not a RiskApplicationReceipt")
    receipt = RiskApplicationReceipt.create(
        source_target=source_target,
        risk_policy_set=_reference(wire.get("risk_policy_set")),
        decision=RiskDecision(_text(wire.get("decision"), "decision")),
        decision_reason=RiskDecisionReason(
            _text(wire.get("decision_reason"), "decision_reason")
        ),
        stages=tuple(
            RiskStageEvidence(
                stage_order=int(_object(item, "stage").get("stage_order")),
                stage_id=_text(_object(item, "stage").get("stage_id"), "stage_id"),
                policy_id=_text(_object(item, "stage").get("policy_id"), "policy_id"),
                evidence_sha256=_text(
                    _object(item, "stage").get("evidence_sha256"),
                    "evidence_sha256",
                ),
            )
            for item in _array(wire.get("stages"), "stages")
        ),
        supporting_refs=tuple(
            _reference(item)
            for item in _array(wire.get("supporting_refs"), "supporting_refs")
        ),
        runtime_identity=_runtime(wire.get("runtime_identity")),
    )
    if receipt.to_wire() != wire:
        raise WeightContractError("RiskApplicationReceipt wire/identity mismatch")
    return receipt


def risk_adjusted_weight_vector_from_bytes(
    payload: bytes,
    *,
    source_target: TargetWeightVector,
    risk_application: RiskApplicationReceipt,
) -> RiskAdjustedWeightVector:
    wire = _parse(payload)
    if wire.get("artifact_type") != "RiskAdjustedWeightVector":
        raise WeightContractError("artifact is not a RiskAdjustedWeightVector")
    adjusted = RiskAdjustedWeightVector.create(
        source_target=source_target,
        risk_application=risk_application,
        runtime_identity=_runtime(wire.get("runtime_identity")),
        cash_weight=_text(wire.get("cash_weight"), "cash_weight"),
        rows=tuple(
            TargetWeightRow(
                _text(_object(item, "row").get("instrument_id"), "instrument_id"),
                _text(_object(item, "row").get("target_weight"), "target_weight"),
            )
            for item in _array(wire.get("rows"), "rows")
        ),
    )
    if adjusted.to_wire() != wire:
        raise WeightContractError("RiskAdjustedWeightVector wire/identity mismatch")
    return adjusted


__all__ = [
    "MAX_WEIGHT_ARTIFACT_BYTES",
    "canonical_weight_bytes",
    "risk_adjusted_weight_vector_from_bytes",
    "risk_application_receipt_from_bytes",
    "target_weight_vector_from_bytes",
]
