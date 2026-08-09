from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from v3_backend.contracts.common.ids import validate_v3_id


PROTOCOL_VERSION = "1.0.0"
MAX_BOUNDED_JSON_BYTES = 64 * 1024
FORBIDDEN_WORKER_FIELDS = frozenset(
    {
        "artifact_id",
        "instrument_id",
        "task_id",
        "project_id",
        "truth_state",
        "registry",
        "catalog",
        "publish",
        "repository",
    }
)


def _forbidden_keys(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in FORBIDDEN_WORKER_FIELDS:
                found.add(str(key))
            found.update(_forbidden_keys(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            found.update(_forbidden_keys(child))
    return found


def _validate_bounded_json(value: Mapping[str, Any]) -> None:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_BOUNDED_JSON_BYTES:
        raise ValueError("bounded JSON exceeds 64 KiB")
    forbidden = _forbidden_keys(value)
    if forbidden:
        raise ValueError(f"worker protocol contains forbidden authority fields: {sorted(forbidden)}")


@dataclass(frozen=True)
class WorkerRequest:
    attempt_id: str
    run_id: str
    operation_id: str
    canonical_input: Mapping[str, Any]
    input_hash: str
    read_tickets: tuple[str, ...]
    staging_namespace: str
    resource_lease_token: str
    cancellation_channel: str
    checkpoint_policy: str
    protocol_version: str = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        validate_v3_id(self.attempt_id, "TaskAttempt")
        validate_v3_id(self.run_id, "Run")
        if self.protocol_version != PROTOCOL_VERSION:
            raise ValueError("worker protocol version mismatch")
        if len(self.input_hash) != 64 or any(ch not in "0123456789abcdef" for ch in self.input_hash):
            raise ValueError("input hash must be lowercase SHA-256")
        _validate_bounded_json(self.canonical_input)
        for value in (
            self.operation_id,
            self.staging_namespace,
            self.resource_lease_token,
            self.cancellation_channel,
            self.checkpoint_policy,
        ):
            if not value:
                raise ValueError("worker request fields must not be empty")


@dataclass(frozen=True)
class Progress:
    completed: int
    total: int
    counters: Mapping[str, int]


@dataclass(frozen=True)
class CheckpointProposal:
    staged_name: str
    sha256: str
    compatibility_hash: str
    metadata: Mapping[str, str]


@dataclass(frozen=True)
class StagedOutputProposal:
    staged_name: str
    role: str
    media_type: str
    byte_size: int
    sha256: str


@dataclass(frozen=True)
class WorkerTerminal:
    status: str
    error_category: str | None = None
    safe_message: str | None = None


WorkerResponse = Progress | CheckpointProposal | StagedOutputProposal | WorkerTerminal


def validate_response(response: WorkerResponse) -> WorkerResponse:
    payload = dict(vars(response))
    _validate_bounded_json(payload)
    if isinstance(response, Progress):
        if response.completed < 0 or response.total < 0 or response.completed > response.total:
            raise ValueError("invalid progress counters")
    elif isinstance(response, (CheckpointProposal, StagedOutputProposal)):
        if not response.staged_name or response.staged_name.startswith(("/", "\\")) or ".." in response.staged_name:
            raise ValueError("staged output must be namespace-relative")
        if len(response.sha256) != 64 or any(ch not in "0123456789abcdef" for ch in response.sha256):
            raise ValueError("staged output hash must be lowercase SHA-256")
        if isinstance(response, CheckpointProposal):
            if len(response.compatibility_hash) != 64 or any(
                ch not in "0123456789abcdef" for ch in response.compatibility_hash
            ):
                raise ValueError("checkpoint compatibility hash must be lowercase SHA-256")
        elif response.byte_size < 0:
            raise ValueError("staged output byte size must not be negative")
    elif isinstance(response, WorkerTerminal):
        if response.status not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            raise ValueError("invalid worker terminal status")
    return response
