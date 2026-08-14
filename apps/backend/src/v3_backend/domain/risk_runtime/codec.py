"""Strict canonical codec for persisted RiskPolicySetVersion owner state."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from v3_backend.contracts.common.truth_admission import TruthAdmissionState
from v3_backend.domain.weights import ReferenceKind
from v3_backend.provenance.canonical_hash import canonical_json

from .model import (
    PolicyType,
    PitRequirement,
    RiskPolicyDefinition,
    RiskPolicySetVersion,
    RiskRuntimeError,
    RiskStateRequirement,
)


MAX_POLICY_SET_BYTES = 64 * 1024


def canonical_policy_set_bytes(policy_set: RiskPolicySetVersion) -> bytes:
    if not isinstance(policy_set, RiskPolicySetVersion):
        raise TypeError("policy_set must be RiskPolicySetVersion")
    policy_set.assert_canonical()
    return canonical_json(policy_set.to_wire()).encode("utf-8")


def _closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RiskRuntimeError(f"duplicate policy JSON key: {key}")
        result[key] = value
    return result


def _parse(payload: bytes) -> dict[str, Any]:
    if not isinstance(payload, bytes):
        raise TypeError("canonical policy-set payload must be bytes")
    if len(payload) > MAX_POLICY_SET_BYTES:
        raise RiskRuntimeError("policy-set payload exceeds the canonical read bound")
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_closed_object,
            parse_float=lambda value: (_ for _ in ()).throw(ValueError("floats forbidden")),
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError("non-finite forbidden")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RiskRuntimeError("invalid canonical policy-set JSON") from exc
    if not isinstance(value, dict) or canonical_json(value).encode("utf-8") != payload:
        raise RiskRuntimeError("policy-set bytes are not canonical JSON")
    return value


def _object(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RiskRuntimeError(f"{field} must be an object")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RiskRuntimeError(f"{field} must be non-empty text")
    return value


def _requirements(value: object) -> tuple[RiskStateRequirement, ...]:
    if not isinstance(value, list):
        raise RiskRuntimeError("required_state_inputs must be an array")
    result: list[RiskStateRequirement] = []
    for item in value:
        wire = _object(item, "required_state_input")
        result.append(
            RiskStateRequirement(
                input_key=_text(wire.get("input_key"), "input_key"),
                reference_kind=ReferenceKind(
                    _text(wire.get("reference_kind"), "reference_kind")
                ),
                pit_requirement=PitRequirement(
                    _text(wire.get("pit_requirement"), "pit_requirement")
                ),
            )
        )
    return tuple(result)


def _policy(value: object) -> RiskPolicyDefinition:
    wire = _object(value, "policy")
    policy_type = PolicyType(_text(wire.get("policy_type"), "policy_type"))
    truth = TruthAdmissionState.from_wire(wire.get("truth_admission"))
    common = {
        "code_version": _text(wire.get("code_version"), "code_version"),
        "runtime_profile_id": _text(
            wire.get("runtime_profile_id"), "runtime_profile_id"
        ),
        "backend": _text(wire.get("backend"), "backend"),
        "policy_version": _text(wire.get("policy_version"), "policy_version"),
        "truth_admission": truth,
    }
    parameters_value = wire.get("parameters")
    if not isinstance(parameters_value, list):
        raise RiskRuntimeError("policy parameters must be an array")
    parameters: dict[str, str] = {}
    for pair in parameters_value:
        if not isinstance(pair, list) or len(pair) != 2:
            raise RiskRuntimeError("policy parameter must be a key/value pair")
        key = _text(pair[0], "parameter key")
        if key in parameters:
            raise RiskRuntimeError("duplicate policy parameter")
        parameters[key] = _text(pair[1], "parameter value")
    requirements = _requirements(wire.get("required_state_inputs"))
    if policy_type is PolicyType.PASS_THROUGH:
        policy = RiskPolicyDefinition.pass_through(**common)
    elif policy_type is PolicyType.MAX_SINGLE_NAME:
        policy = RiskPolicyDefinition.max_single_name(
            max_weight=parameters.get("max_weight", ""),
            required_state_inputs=requirements,
            **common,
        )
    elif policy_type is PolicyType.GROSS_NET_EXPOSURE_VALIDATE:
        policy = RiskPolicyDefinition.gross_net_exposure_validate(
            max_gross=parameters.get("max_gross", ""),
            min_net=parameters.get("min_net", ""),
            max_net=parameters.get("max_net", ""),
            required_state_inputs=requirements,
            **common,
        )
    else:
        raise RiskRuntimeError("unsupported persisted Risk policy type")
    if policy.to_wire() != dict(wire):
        raise RiskRuntimeError("RiskPolicyDefinition wire/identity mismatch")
    return policy


def risk_policy_set_from_bytes(payload: bytes) -> RiskPolicySetVersion:
    wire = _parse(payload)
    policies_wire = wire.get("ordered_policies")
    if not isinstance(policies_wire, list):
        raise RiskRuntimeError("ordered_policies must be an array")
    policy_set = RiskPolicySetVersion.create(tuple(_policy(item) for item in policies_wire))
    if policy_set.to_wire() != wire:
        raise RiskRuntimeError("RiskPolicySetVersion wire/identity mismatch")
    return policy_set


__all__ = ["MAX_POLICY_SET_BYTES", "canonical_policy_set_bytes", "risk_policy_set_from_bytes"]
