"""Authenticated, fail-closed local runtime handshake."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from v3_backend.contracts.registry import SERVICE_CONTRACTS

from .framed_stdio import MAX_FRAME_BYTES, ProtocolViolation

PROTOCOL_VERSION = "v3.local/1.0"
SCHEMA_MIN = "1.0.0"
SCHEMA_MAX = "1.0.0"
SUPERVISOR_TOKEN_BYTES = 32
SUPERVISOR_TOKEN_FD = 3
_VERSION_RE = re.compile(r"^(?:v3\.local/)?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


@dataclass(frozen=True)
class Capability:
    code: str
    truth_state: str
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.truth_state not in {"FORMAL", "DEMO", "UNAVAILABLE"}:
            raise ValueError("invalid capability truth state")
        if self.truth_state == "FORMAL" and self.reason_code is not None:
            raise ValueError("FORMAL capability cannot have a downgrade reason")

    def to_wire(self) -> dict[str, str]:
        value = {"code": self.code, "truth_state": self.truth_state}
        if self.reason_code is not None:
            value["reason_code"] = self.reason_code
        return value


@dataclass(frozen=True)
class AcceptedSupervisor:
    desktop_version: str
    project_id: str | None
    project_context_revision_id: str | None
    last_project_event_sequence: int


def read_supervisor_token(fd: int = SUPERVISOR_TOKEN_FD) -> bytes:
    try:
        chunks = bytearray()
        while len(chunks) <= SUPERVISOR_TOKEN_BYTES:
            chunk = os.read(fd, SUPERVISOR_TOKEN_BYTES + 1 - len(chunks))
            if not chunk:
                break
            chunks.extend(chunk)
        os.close(fd)
    except OSError as exc:
        raise ProtocolViolation("supervisor token handle is unavailable") from exc
    token = bytes(chunks)
    if len(token) != SUPERVISOR_TOKEN_BYTES:
        raise ProtocolViolation("supervisor token must be exactly 256 bits")
    return token


def create_hello(
    backend_instance_id: str,
    pid: int,
    backend_version: str,
    capabilities: Sequence[Capability],
    nonce: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": "backend.hello",
        "protocol": PROTOCOL_VERSION,
        "backend_instance_id": backend_instance_id,
        "pid": pid,
        "backend_version": backend_version,
        "asl_versions": {service: contract.api_version for service, contract in SERVICE_CONTRACTS.items()},
        "schema_compatibility": {"min": SCHEMA_MIN, "max": SCHEMA_MAX},
        "capabilities": [item.to_wire() for item in capabilities],
        "max_frame_bytes": MAX_FRAME_BYTES,
        "event_replay": True,
        "nonce": nonce or secrets.token_hex(32),
    }


def token_proof(token: bytes, nonce: str) -> str:
    return hmac.new(token, nonce.encode("ascii"), hashlib.sha256).hexdigest()


def _major_minor(value: str) -> tuple[int, int]:
    match = _VERSION_RE.fullmatch(value)
    if match is None:
        raise ProtocolViolation(f"invalid protocol version: {value!r}")
    return int(match.group(1)), int(match.group(2))


def verify_supervisor_accept(
    message: Mapping[str, Any], token: bytes, nonce: str
) -> AcceptedSupervisor:
    required = {
        "kind",
        "token_proof",
        "requested_protocol",
        "requested_asl_versions",
        "desktop_version",
        "project_id",
        "project_context_revision_id",
        "last_project_event_sequence",
    }
    if set(message) != required:
        raise ProtocolViolation("supervisor.accept fields are not the closed wire shape")
    if message["kind"] != "supervisor.accept":
        raise ProtocolViolation("expected supervisor.accept")
    requested_major, requested_minor = _major_minor(str(message["requested_protocol"]))
    offered_major, offered_minor = _major_minor(PROTOCOL_VERSION)
    if requested_major != offered_major or requested_minor > offered_minor:
        raise ProtocolViolation("incompatible local runtime protocol")
    proof = message["token_proof"]
    if not isinstance(proof, str) or not hmac.compare_digest(proof, token_proof(token, nonce)):
        raise ProtocolViolation("supervisor token proof failed")
    versions = message["requested_asl_versions"]
    if not isinstance(versions, Mapping) or set(versions) != set(SERVICE_CONTRACTS):
        raise ProtocolViolation("requested ASL service set does not match the frozen registry")
    for service, requested in versions.items():
        offered = SERVICE_CONTRACTS[service].api_version
        requested_text = str(requested)
        if re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))?", requested_text) is None:
            raise ProtocolViolation(f"invalid ASL version for {service}")
        requested_parts = requested_text.split(".")
        offered_parts = offered.split(".")
        if len(requested_parts) < 2 or requested_parts[0] != offered_parts[0]:
            raise ProtocolViolation(f"incompatible ASL major for {service}")
        if int(requested_parts[1]) > int(offered_parts[1]):
            raise ProtocolViolation(f"unsupported ASL minor for {service}")
    last_sequence = message["last_project_event_sequence"]
    if not isinstance(last_sequence, int) or isinstance(last_sequence, bool) or last_sequence < 0:
        raise ProtocolViolation("last project event sequence must be a non-negative integer")
    project_id = message["project_id"]
    revision_id = message["project_context_revision_id"]
    if project_id is not None and not isinstance(project_id, str):
        raise ProtocolViolation("project_id must be a string or null")
    if revision_id is not None and not isinstance(revision_id, str):
        raise ProtocolViolation("project_context_revision_id must be a string or null")
    if not isinstance(message["desktop_version"], str) or not message["desktop_version"]:
        raise ProtocolViolation("desktop_version is required")
    return AcceptedSupervisor(
        desktop_version=message["desktop_version"],
        project_id=project_id,
        project_context_revision_id=revision_id,
        last_project_event_sequence=last_sequence,
    )


def create_ready(backend_instance_id: str) -> dict[str, Any]:
    return {
        "kind": "backend.ready",
        "backend_instance_id": backend_instance_id,
        "protocol": PROTOCOL_VERSION,
        "schema_version": SCHEMA_MAX,
    }
