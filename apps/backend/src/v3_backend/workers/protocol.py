from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from v3_backend.contracts.common.ids import validate_v3_id


PROTOCOL_VERSION = "1.0.0"
MAX_BOUNDED_JSON_BYTES = 64 * 1024
_WIRE_DEADLINE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
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
    elif isinstance(value, list):
        for child in value:
            found.update(_forbidden_keys(child))
    return found


def _validate_json_object_keys(value: object) -> None:
    if isinstance(value, tuple):
        raise ValueError("bounded JSON arrays must be lists, not tuples")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError("bounded JSON object keys must be non-empty strings")
            _validate_json_object_keys(child)
    elif isinstance(value, list):
        for child in value:
            _validate_json_object_keys(child)


def _validate_bounded_json(value: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping):
        raise ValueError("bounded JSON must be an object")
    _validate_json_object_keys(value)
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("bounded JSON must be strict JSON") from error
    if len(encoded) > MAX_BOUNDED_JSON_BYTES:
        raise ValueError("bounded JSON exceeds 64 KiB")
    forbidden = _forbidden_keys(value)
    if forbidden:
        raise ValueError(f"worker protocol contains forbidden authority fields: {sorted(forbidden)}")


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"worker protocol contains duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"worker protocol contains non-standard JSON constant: {value}")


def _encode_wire_message(kind: str, payload: Mapping[str, Any]) -> bytes:
    wire = {"kind": kind, **dict(payload)}
    _validate_bounded_json(wire)
    try:
        encoded = json.dumps(
            wire,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("worker protocol message must be strict JSON") from error
    if len(encoded) > MAX_BOUNDED_JSON_BYTES:
        raise ValueError("worker protocol message exceeds 64 KiB")
    return encoded


def _decode_wire_message(frame: bytes | bytearray | memoryview) -> dict[str, Any]:
    if not isinstance(frame, (bytes, bytearray, memoryview)):
        raise ValueError("worker protocol frame must be bytes")
    raw = bytes(frame)
    if not raw or len(raw) > MAX_BOUNDED_JSON_BYTES:
        raise ValueError("worker protocol frame is empty or exceeds 64 KiB")
    try:
        decoded = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("worker protocol frame is not strict JSON") from error
    if not isinstance(decoded, dict):
        raise ValueError("worker protocol frame must be a JSON object")
    _validate_bounded_json(decoded)
    return decoded


def _require_wire_shape(
    wire: Mapping[str, Any],
    *,
    kind: str,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> None:
    allowed = {"kind", *required, *optional}
    if wire.get("kind") != kind or set(wire) - allowed or required - set(wire):
        raise ValueError(f"worker protocol {kind} wire shape is invalid")


def encode_command(command: WorkerCommand) -> bytes:
    """Encode a validated command without invoking Python object deserialization."""

    checked = validate_command(command)
    if isinstance(checked, WorkerAcknowledge):
        return _encode_wire_message(
            "WorkerAcknowledge",
            {
                "protocol_version": checked.protocol_version,
                "resource_lease_token": checked.resource_lease_token,
            },
        )
    if isinstance(checked, WorkerCancel):
        return _encode_wire_message("WorkerCancel", {"reason": checked.reason})
    if isinstance(checked, WorkerCheckpointRequest):
        return _encode_wire_message(
            "WorkerCheckpointRequest",
            {"reason": checked.reason, "deadline_at": checked.deadline_at},
        )
    if isinstance(checked, WorkerPause):
        return _encode_wire_message("WorkerPause", {"reason": checked.reason})
    if isinstance(checked, WorkerProgressAck):
        return _encode_wire_message("WorkerProgressAck", {"sequence": checked.sequence})
    if isinstance(checked, WorkerResourcePressure):
        return _encode_wire_message(
            "WorkerResourcePressure",
            {
                "pressure_kind": checked.kind,
                "observed": checked.observed,
                "soft_limit": checked.soft_limit,
                "hard_limit": checked.hard_limit,
            },
        )
    raise ValueError("unknown worker command")


def decode_command(frame: bytes | bytearray | memoryview) -> WorkerCommand:
    """Decode a bounded JSON command before constructing any typed object."""

    wire = _decode_wire_message(frame)
    kind = wire.get("kind")
    if kind == "WorkerAcknowledge":
        _require_wire_shape(
            wire,
            kind=kind,
            required=frozenset({"protocol_version", "resource_lease_token"}),
        )
        command: WorkerCommand = WorkerAcknowledge(
            wire["protocol_version"], wire["resource_lease_token"]
        )
    elif kind == "WorkerCancel":
        _require_wire_shape(wire, kind=kind, required=frozenset({"reason"}))
        command = WorkerCancel(wire["reason"])
    elif kind == "WorkerCheckpointRequest":
        _require_wire_shape(
            wire,
            kind=kind,
            required=frozenset({"reason", "deadline_at"}),
        )
        command = WorkerCheckpointRequest(wire["reason"], wire["deadline_at"])
    elif kind == "WorkerPause":
        _require_wire_shape(wire, kind=kind, required=frozenset({"reason"}))
        command = WorkerPause(wire["reason"])
    elif kind == "WorkerProgressAck":
        _require_wire_shape(wire, kind=kind, required=frozenset({"sequence"}))
        command = WorkerProgressAck(wire["sequence"])
    elif kind == "WorkerResourcePressure":
        _require_wire_shape(
            wire,
            kind=kind,
            required=frozenset({"pressure_kind", "observed", "soft_limit", "hard_limit"}),
        )
        command = WorkerResourcePressure(
            wire["pressure_kind"],
            wire["observed"],
            wire["soft_limit"],
            wire["hard_limit"],
        )
    else:
        raise ValueError("unknown worker command kind")
    return validate_command(command)


def encode_response(response: WorkerResponse) -> bytes:
    """Encode a validated response as bounded JSON bytes."""

    checked = validate_response(response)
    if isinstance(checked, WorkerHello):
        return _encode_wire_message(
            "WorkerHello",
            {
                "protocol_version": checked.protocol_version,
                "resource_lease_token": checked.resource_lease_token,
            },
        )
    if isinstance(checked, WorkerHeartbeat):
        return _encode_wire_message(
            "WorkerHeartbeat",
            {
                "sequence": checked.sequence,
                "rss_bytes": checked.rss_bytes,
                "scratch_bytes": checked.scratch_bytes,
            },
        )
    if isinstance(checked, Progress):
        payload: dict[str, Any] = {
            "completed": checked.completed,
            "total": checked.total,
            "counters": dict(checked.counters),
            "phase": checked.phase,
            "work_unit": checked.work_unit,
        }
        if checked.sequence is not None:
            payload["sequence"] = checked.sequence
        return _encode_wire_message("Progress", payload)
    if isinstance(checked, CheckpointProposal):
        return _encode_wire_message(
            "CheckpointProposal",
            {
                "staged_name": checked.staged_name,
                "sha256": checked.sha256,
                "compatibility_hash": checked.compatibility_hash,
                "metadata": dict(checked.metadata),
            },
        )
    if isinstance(checked, StagedOutputProposal):
        return _encode_wire_message(
            "StagedOutputProposal",
            {
                "staged_name": checked.staged_name,
                "role": checked.role,
                "media_type": checked.media_type,
                "byte_size": checked.byte_size,
                "sha256": checked.sha256,
            },
        )
    if isinstance(checked, WorkerTerminal):
        payload = {"status": checked.status}
        if checked.error_category is not None:
            payload["error_category"] = checked.error_category
        if checked.safe_message is not None:
            payload["safe_message"] = checked.safe_message
        return _encode_wire_message("WorkerTerminal", payload)
    raise ValueError("unknown worker response")


def decode_response(frame: bytes | bytearray | memoryview) -> WorkerResponse:
    """Decode a bounded JSON response before constructing any typed object."""

    wire = _decode_wire_message(frame)
    kind = wire.get("kind")
    if kind == "WorkerHello":
        _require_wire_shape(
            wire,
            kind=kind,
            required=frozenset({"protocol_version", "resource_lease_token"}),
        )
        response: WorkerResponse = WorkerHello(
            wire["protocol_version"], wire["resource_lease_token"]
        )
    elif kind == "WorkerHeartbeat":
        _require_wire_shape(
            wire,
            kind=kind,
            required=frozenset({"sequence", "rss_bytes", "scratch_bytes"}),
        )
        response = WorkerHeartbeat(
            wire["sequence"], wire["rss_bytes"], wire["scratch_bytes"]
        )
    elif kind == "Progress":
        _require_wire_shape(
            wire,
            kind=kind,
            required=frozenset({"completed", "total", "counters", "phase", "work_unit"}),
            optional=frozenset({"sequence"}),
        )
        response = Progress(
            wire["completed"],
            wire["total"],
            wire["counters"],
            wire["phase"],
            wire["work_unit"],
            wire.get("sequence"),
        )
    elif kind == "CheckpointProposal":
        _require_wire_shape(
            wire,
            kind=kind,
            required=frozenset({"staged_name", "sha256", "compatibility_hash", "metadata"}),
        )
        response = CheckpointProposal(
            wire["staged_name"],
            wire["sha256"],
            wire["compatibility_hash"],
            wire["metadata"],
        )
    elif kind == "StagedOutputProposal":
        _require_wire_shape(
            wire,
            kind=kind,
            required=frozenset({"staged_name", "role", "media_type", "byte_size", "sha256"}),
        )
        response = StagedOutputProposal(
            wire["staged_name"],
            wire["role"],
            wire["media_type"],
            wire["byte_size"],
            wire["sha256"],
        )
    elif kind == "WorkerTerminal":
        _require_wire_shape(
            wire,
            kind=kind,
            required=frozenset({"status"}),
            optional=frozenset({"error_category", "safe_message"}),
        )
        response = WorkerTerminal(
            wire["status"], wire.get("error_category"), wire.get("safe_message")
        )
    else:
        raise ValueError("unknown worker response kind")
    return validate_response(response)


def _optional_bounded_text(value: object, name: str, maximum: int = 256) -> None:
    if value is not None and (not isinstance(value, str) or not value or len(value) > maximum):
        raise ValueError(f"{name} must be a bounded non-empty string when present")


def _required_bounded_text(value: object, name: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{name} must be a bounded non-empty string")
    return value


def _required_int(value: object, name: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _validate_counter_map(value: object) -> None:
    if not isinstance(value, Mapping) or len(value) > 128:
        raise ValueError("progress counters must be a bounded object")
    for key, counter in value.items():
        _required_bounded_text(key, "progress counter name", 128)
        _required_int(counter, "progress counter", minimum=0)


def _optional_sha256(value: object, name: str) -> None:
    if value is not None and (
        not isinstance(value, str)
        or len(value) != 64
        or value.lower() != value
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 when present")


def _required_sha256(value: object, name: str) -> str:
    _optional_sha256(value, name)
    if value is None:
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


def _optional_deadline(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, str) or len(value) > 64 or not _WIRE_DEADLINE.fullmatch(value):
        raise ValueError("deadline_at must be bounded RFC3339 UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError("deadline_at must be bounded RFC3339 UTC") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("deadline_at must include UTC")


def _required_deadline(value: object) -> str:
    _optional_deadline(value)
    if value is None:
        raise ValueError("deadline_at is required")
    return value


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
    correlation_id: str | None = None
    operation_receipt_id: str | None = None
    deadline_at: str | None = None
    runtime_generation_id: str | None = None
    operation_schema_version: str | None = None
    resource_policy_version: str | None = None
    resolved_resource_hash: str | None = None
    compatibility_hash: str | None = None
    code_version: str | None = None
    environment_profile_id: str | None = None

    def __post_init__(self) -> None:
        validate_v3_id(self.attempt_id, "TaskAttempt")
        validate_v3_id(self.run_id, "Run")
        if self.protocol_version != PROTOCOL_VERSION:
            raise ValueError("worker protocol version mismatch")
        _required_sha256(self.input_hash, "input_hash")
        _validate_bounded_json(self.canonical_input)
        _required_bounded_text(self.operation_id, "operation_id")
        _required_bounded_text(self.staging_namespace, "staging_namespace")
        _required_bounded_text(self.resource_lease_token, "resource_lease_token")
        _required_bounded_text(self.cancellation_channel, "cancellation_channel")
        _required_bounded_text(self.checkpoint_policy, "checkpoint_policy", 128)
        if not isinstance(self.read_tickets, tuple) or len(self.read_tickets) > 128:
            raise ValueError("read_tickets must be a bounded tuple")
        for ticket in self.read_tickets:
            _required_bounded_text(ticket, "read_ticket")
        _optional_bounded_text(self.correlation_id, "correlation_id")
        _optional_bounded_text(self.operation_receipt_id, "operation_receipt_id")
        _optional_deadline(self.deadline_at)
        _optional_bounded_text(self.runtime_generation_id, "runtime_generation_id", 128)
        _optional_bounded_text(self.operation_schema_version, "operation_schema_version", 128)
        _optional_bounded_text(self.resource_policy_version, "resource_policy_version", 128)
        _optional_bounded_text(self.code_version, "code_version")
        _optional_bounded_text(self.environment_profile_id, "environment_profile_id", 128)
        _optional_sha256(self.resolved_resource_hash, "resolved_resource_hash")
        _optional_sha256(self.compatibility_hash, "compatibility_hash")


@dataclass(frozen=True)
class Progress:
    completed: int
    total: int
    counters: Mapping[str, int]
    phase: str = "UNSPECIFIED"
    work_unit: str = "items"
    sequence: int | None = None


@dataclass(frozen=True)
class WorkerHello:
    protocol_version: str
    resource_lease_token: str


@dataclass(frozen=True)
class WorkerHeartbeat:
    sequence: int
    rss_bytes: int
    scratch_bytes: int


@dataclass(frozen=True)
class WorkerAcknowledge:
    protocol_version: str
    resource_lease_token: str


@dataclass(frozen=True)
class WorkerCancel:
    reason: str


@dataclass(frozen=True)
class WorkerCheckpointRequest:
    reason: str
    deadline_at: str


@dataclass(frozen=True)
class WorkerPause:
    reason: str


@dataclass(frozen=True)
class WorkerProgressAck:
    sequence: int


@dataclass(frozen=True)
class WorkerResourcePressure:
    kind: str
    observed: int
    soft_limit: int
    hard_limit: int


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


WorkerResponse = (
    WorkerHello
    | WorkerHeartbeat
    | Progress
    | CheckpointProposal
    | StagedOutputProposal
    | WorkerTerminal
)
WorkerCommand = (
    WorkerAcknowledge
    | WorkerCancel
    | WorkerCheckpointRequest
    | WorkerPause
    | WorkerProgressAck
    | WorkerResourcePressure
)


def validate_command(command: WorkerCommand) -> WorkerCommand:
    if not isinstance(
        command,
        (
            WorkerAcknowledge,
            WorkerCancel,
            WorkerCheckpointRequest,
            WorkerPause,
            WorkerProgressAck,
            WorkerResourcePressure,
        ),
    ):
        raise ValueError("unknown worker command")
    payload = dict(vars(command))
    _validate_bounded_json(payload)
    if isinstance(command, WorkerAcknowledge):
        if (
            command.protocol_version != PROTOCOL_VERSION
            or not isinstance(command.resource_lease_token, str)
            or not 1 <= len(command.resource_lease_token) <= 256
        ):
            raise ValueError("invalid worker acknowledgement")
    elif isinstance(command, WorkerCancel):
        if not isinstance(command.reason, str) or not 1 <= len(command.reason) <= 256:
            raise ValueError("invalid worker cancellation")
    elif isinstance(command, WorkerCheckpointRequest):
        if not isinstance(command.reason, str) or not 1 <= len(command.reason) <= 256:
            raise ValueError("invalid worker checkpoint request")
        _required_deadline(command.deadline_at)
    elif isinstance(command, WorkerPause):
        if not isinstance(command.reason, str) or not 1 <= len(command.reason) <= 256:
            raise ValueError("invalid worker pause")
    elif isinstance(command, WorkerProgressAck):
        _required_int(command.sequence, "worker progress acknowledgement", minimum=1)
        if command.sequence < 1:
            raise ValueError("invalid worker progress acknowledgement")
    elif isinstance(command, WorkerResourcePressure):
        _required_bounded_text(command.kind, "worker resource pressure kind", 128)
        _required_int(command.observed, "worker pressure observed")
        _required_int(command.soft_limit, "worker pressure soft limit")
        _required_int(command.hard_limit, "worker pressure hard limit")
        if command.hard_limit < command.soft_limit:
            raise ValueError("invalid worker resource pressure values")
    return command


def validate_response(response: WorkerResponse) -> WorkerResponse:
    if not isinstance(
        response,
        (
            WorkerHello,
            WorkerHeartbeat,
            Progress,
            CheckpointProposal,
            StagedOutputProposal,
            WorkerTerminal,
        ),
    ):
        raise ValueError("unknown worker response")
    payload = dict(vars(response))
    _validate_bounded_json(payload)
    if isinstance(response, WorkerHello):
        if (
            response.protocol_version != PROTOCOL_VERSION
            or not isinstance(response.resource_lease_token, str)
            or not 1 <= len(response.resource_lease_token) <= 256
        ):
            raise ValueError("invalid worker hello")
    elif isinstance(response, WorkerHeartbeat):
        _required_int(response.sequence, "worker heartbeat sequence", minimum=1)
        _required_int(response.rss_bytes, "worker heartbeat RSS")
        _required_int(response.scratch_bytes, "worker heartbeat scratch")
        if response.sequence < 1 or response.rss_bytes < 0 or response.scratch_bytes < 0:
            raise ValueError("invalid worker heartbeat")
    elif isinstance(response, Progress):
        _required_int(response.completed, "progress completed")
        # total=0 was accepted by the v1 worker wire contract for an empty
        # workload.  Keep decoding that frame for protocol compatibility;
        # the durable attempt_progress owner still requires total >= 1.
        _required_int(response.total, "progress total")
        if response.completed < 0 or response.total < 0 or response.completed > response.total:
            raise ValueError("invalid progress counters")
        _required_bounded_text(response.phase, "progress phase", 128)
        _required_bounded_text(response.work_unit, "progress work unit", 128)
        _validate_counter_map(response.counters)
        if response.sequence is not None and (
            not isinstance(response.sequence, int)
            or isinstance(response.sequence, bool)
            or response.sequence < 1
        ):
            raise ValueError("progress sequence must be a positive integer when present")
    elif isinstance(response, (CheckpointProposal, StagedOutputProposal)):
        _required_bounded_text(response.staged_name, "staged output name", 512)
        if response.staged_name.startswith(("/", "\\")) or ".." in response.staged_name:
            raise ValueError("staged output must be namespace-relative")
        _required_sha256(response.sha256, "staged output hash")
        if isinstance(response, CheckpointProposal):
            _required_sha256(response.compatibility_hash, "checkpoint compatibility hash")
            if not isinstance(response.metadata, Mapping) or len(response.metadata) > 32:
                raise ValueError("checkpoint metadata must be a bounded object")
            for key, value in response.metadata.items():
                _required_bounded_text(key, "checkpoint metadata key", 128)
                _required_bounded_text(value, "checkpoint metadata value", 1024)
        if isinstance(response, StagedOutputProposal):
            _required_int(response.byte_size, "staged output byte size")
    elif isinstance(response, WorkerTerminal):
        if not isinstance(response.status, str) or response.status not in {
            "SUCCEEDED",
            "FAILED",
            "CANCELLED",
        }:
            raise ValueError("invalid worker terminal status")
        _optional_bounded_text(response.error_category, "terminal error category", 128)
        _optional_bounded_text(response.safe_message, "terminal safe message", 2048)
        if response.status in {"SUCCEEDED", "CANCELLED"} and (
            response.error_category is not None or response.safe_message is not None
        ):
            raise ValueError("successful or cancelled terminal cannot carry failure fields")
    return response
