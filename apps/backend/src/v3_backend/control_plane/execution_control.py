"""Mandatory execution-control context for long-running domain work.

The context is deliberately small and dependency-inverted.  Domain owners do
not receive a database connection or a worker process; they receive ports for
cooperative cancellation, durable progress, checkpoint requests and parent
resource observations.  The context owns the only pre-commit gate so a late
deadline/cancel cannot be confused with a commit that already happened.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


DEADLINE_EXCEEDED_PRE_COMMIT = "DEADLINE_EXCEEDED_PRE_COMMIT"
EXECUTION_CANCELLED_PRE_COMMIT = "EXECUTION_CANCELLED_PRE_COMMIT"
RESOURCE_EXHAUSTED_MEMORY = "RESOURCE_EXHAUSTED_MEMORY"
RESOURCE_EXHAUSTED_SCRATCH = "RESOURCE_EXHAUSTED_SCRATCH"
PROGRESS_STALLED = "PROGRESS_STALLED"
RUNTIME_GENERATION_MISMATCH = "RUNTIME_GENERATION_MISMATCH"
OPERATION_RECEIPT_REQUIRED = "OPERATION_RECEIPT_REQUIRED"
OPERATION_RECEIPT_NOT_RUNNING = "OPERATION_RECEIPT_NOT_RUNNING"
_CANONICAL_UTC_DEADLINE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)


def _parse_deadline(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif (
        isinstance(value, str)
        and len(value) <= 64
        and _CANONICAL_UTC_DEADLINE.fullmatch(value) is not None
    ):
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        except ValueError as error:
            raise ValueError("absolute_deadline_at must be RFC3339 UTC") from error
    else:
        raise ValueError("absolute_deadline_at must be RFC3339 UTC")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("absolute_deadline_at must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _wire_time(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("execution-control time must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(char in "0123456789abcdef" for char in value)
    )


def _validate_strict_json(value: object, *, name: str) -> None:
    if isinstance(value, tuple):
        raise ValueError(f"{name} must use JSON arrays, not tuples")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError(f"{name} object keys must be non-empty strings")
            _validate_strict_json(child, name=name)
    elif isinstance(value, list):
        for child in value:
            _validate_strict_json(child, name=name)
    try:
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be strict JSON") from error


class ExecutionControlError(RuntimeError):
    """Stable, non-secret control failure with an optional receipt identity."""

    def __init__(self, code: str, message: str, *, receipt_id: str | None = None) -> None:
        self.code = code
        self.receipt_id = receipt_id
        super().__init__(message)


class CancellationPort(Protocol):
    def is_cancelled(self) -> bool: ...


class ProgressPort(Protocol):
    def record_progress(self, **kwargs: Any) -> Any: ...

    def latest_progress(self, attempt_id: str) -> Any: ...


class CheckpointPort(Protocol):
    def request_checkpoint(self, *, reason: str, deadline_at: str) -> None: ...


class ScratchPort(Protocol):
    def sample(self) -> Mapping[str, object] | None: ...


class GenerationPort(Protocol):
    def is_current(self, runtime_generation_id: str) -> bool: ...


class _NeverCancelled:
    def is_cancelled(self) -> bool:
        return False


class _NoopCheckpoint:
    def request_checkpoint(self, *, reason: str, deadline_at: str) -> None:
        return None


class _NoopScratch:
    def sample(self) -> Mapping[str, object] | None:
        return None


@dataclass(frozen=True)
class ScratchObservation:
    observed: int
    soft_limit: int
    hard_limit: int

    @classmethod
    def from_value(cls, value: Mapping[str, object]) -> "ScratchObservation":
        try:
            observed = value.get("observed", value.get("observed_bytes"))
            soft_limit = value.get("soft_limit", value.get("soft_limit_bytes"))
            hard_limit = value.get("hard_limit", value.get("hard_limit_bytes"))
        except AttributeError as error:
            raise ValueError("scratch observation must be an object") from error
        if any(
            isinstance(item, bool) or not isinstance(item, int) or item < 0
            for item in (observed, soft_limit, hard_limit)
        ) or int(soft_limit) > int(hard_limit):
            raise ValueError("scratch observation limits are invalid")
        return cls(int(observed), int(soft_limit), int(hard_limit))


@dataclass(frozen=True)
class CommitReceipt:
    operation_receipt_id: str
    state: str
    commit_boundary_at: datetime
    outcome: Mapping[str, object] | None = None
    outcome_artifact_id: str | None = None


class ExecutionControlContext:
    """Shared cancellation/deadline/progress/finality gate.

    ``safe_point`` may be called after every bounded unit.  It persists the
    progress record through ``progress_port`` and then returns the durable
    record.  ``before_irreversible_commit`` is the final abortable operation;
    callers must invoke ``mark_committed`` immediately after the owner commits.
    """

    def __init__(
        self,
        correlation_id: str,
        operation_receipt_id: str,
        absolute_deadline_at: str | datetime,
        cancellation_port: CancellationPort | None,
        progress_port: ProgressPort | None,
        checkpoint_port: CheckpointPort | None,
        scratch_port: ScratchPort | None,
        runtime_generation_id: str,
        *,
        attempt_id: str | None = None,
        receipt_persistence: Any | None = None,
        generation_port: GenerationPort | None = None,
        clock: Callable[[], datetime] | None = None,
        progress_stall_seconds: int | None = None,
    ) -> None:
        if not isinstance(correlation_id, str) or not 1 <= len(correlation_id) <= 256:
            raise ValueError("correlation_id is not bounded")
        if not isinstance(operation_receipt_id, str) or not 1 <= len(operation_receipt_id) <= 128:
            raise ValueError("operation_receipt_id is not bounded")
        if not isinstance(runtime_generation_id, str) or not 1 <= len(runtime_generation_id) <= 128:
            raise ValueError("runtime_generation_id is not bounded")
        if attempt_id is not None and (
            not isinstance(attempt_id, str) or not 1 <= len(attempt_id) <= 128
        ):
            raise ValueError("attempt_id is not bounded")
        if progress_port is not None and attempt_id is None:
            raise ValueError("attempt_id is required when progress persistence is configured")
        if progress_stall_seconds is not None and (
            isinstance(progress_stall_seconds, bool)
            or not isinstance(progress_stall_seconds, int)
            or progress_stall_seconds <= 0
        ):
            raise ValueError("progress_stall_seconds must be positive")
        self.correlation_id = correlation_id
        self.operation_receipt_id = operation_receipt_id
        self.absolute_deadline_at = _parse_deadline(absolute_deadline_at)
        self.absolute_deadline_wire = (
            absolute_deadline_at
            if isinstance(absolute_deadline_at, str)
            else _wire_time(self.absolute_deadline_at)
        )
        self.cancellation_port = cancellation_port or _NeverCancelled()
        self.progress_port = progress_port
        self.checkpoint_port = checkpoint_port or _NoopCheckpoint()
        self.scratch_port = scratch_port or _NoopScratch()
        self.runtime_generation_id = runtime_generation_id
        self.attempt_id = attempt_id
        self.receipt_persistence = receipt_persistence
        self.generation_port = generation_port
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.progress_stall_seconds = progress_stall_seconds
        self._last_progress_at: datetime | None = None
        self._last_progress_payload: tuple[object, ...] | None = None
        self._checkpoint_requested = False
        self._commit_armed = False
        self._expected_commit_hash: str | None = None
        self._committed = False

    @property
    def committed(self) -> bool:
        return self._committed

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("execution-control clock must return timezone-aware time")
        return now.astimezone(timezone.utc)

    def _raise_if_cancelled_or_expired(self) -> None:
        if self._committed:
            return
        if self.cancellation_port.is_cancelled():
            raise ExecutionControlError(
                EXECUTION_CANCELLED_PRE_COMMIT,
                "operation was cancelled before irreversible commit",
                receipt_id=self.operation_receipt_id,
            )
        if self._now() >= self.absolute_deadline_at:
            raise ExecutionControlError(
                DEADLINE_EXCEEDED_PRE_COMMIT,
                "operation deadline expired before irreversible commit",
                receipt_id=self.operation_receipt_id,
            )
        if self.generation_port is not None and not self.generation_port.is_current(
            self.runtime_generation_id
        ):
            raise ExecutionControlError(
                RUNTIME_GENERATION_MISMATCH,
                "runtime generation is no longer current",
                receipt_id=self.operation_receipt_id,
            )

    def _sample_scratch(self) -> ScratchObservation | None:
        raw = self.scratch_port.sample()
        if raw is None:
            return None
        if isinstance(raw, ScratchObservation):
            return raw
        return ScratchObservation.from_value(raw)

    def _request_checkpoint(self, reason: str) -> None:
        if self._checkpoint_requested:
            return
        self._checkpoint_requested = True
        try:
            self.checkpoint_port.request_checkpoint(
                reason=reason,
                deadline_at=self.absolute_deadline_wire,
            )
        except Exception:
            # A failed request must not permanently suppress a later bounded
            # retry, and it must remain visible to the caller as a fail-closed
            # control error rather than a successful checkpoint request.
            self._checkpoint_requested = False
            raise

    def _enforce_scratch(self) -> None:
        observation = self._sample_scratch()
        if observation is None:
            return
        if observation.observed >= observation.hard_limit:
            raise ExecutionControlError(
                RESOURCE_EXHAUSTED_SCRATCH,
                "scratch quota reached before irreversible commit",
                receipt_id=self.operation_receipt_id,
            )
        if observation.observed >= observation.soft_limit:
            self._request_checkpoint("SCRATCH_PRESSURE")

    def _assert_receipt_binding(self, receipt: object) -> None:
        """Keep a durable receipt tied to this control context when exposed."""

        missing = object()
        operation_receipt_id = getattr(receipt, "operation_receipt_id", missing)
        if operation_receipt_id != self.operation_receipt_id:
            raise ExecutionControlError(
                OPERATION_RECEIPT_REQUIRED,
                "operation receipt identity does not match execution context",
                receipt_id=self.operation_receipt_id,
            )
        correlation_id = getattr(receipt, "correlation_id", missing)
        if correlation_id != self.correlation_id:
            raise ExecutionControlError(
                OPERATION_RECEIPT_REQUIRED,
                "operation receipt correlation does not match execution context",
                receipt_id=self.operation_receipt_id,
            )
        generation_id = getattr(receipt, "runtime_generation_id", missing)
        if generation_id != self.runtime_generation_id:
            raise ExecutionControlError(
                RUNTIME_GENERATION_MISMATCH,
                "operation receipt runtime generation does not match execution context",
                receipt_id=self.operation_receipt_id,
            )
        attempt_id = getattr(receipt, "attempt_id", missing)
        if attempt_id != self.attempt_id:
            raise ExecutionControlError(
                OPERATION_RECEIPT_REQUIRED,
                "operation receipt Attempt does not match execution context",
                receipt_id=self.operation_receipt_id,
            )
        deadline_at = getattr(receipt, "deadline_at", missing)
        try:
            receipt_deadline = _parse_deadline(deadline_at)
        except (TypeError, ValueError) as error:
            raise ExecutionControlError(
                OPERATION_RECEIPT_REQUIRED,
                "operation receipt deadline is invalid",
                receipt_id=self.operation_receipt_id,
            ) from error
        if receipt_deadline != self.absolute_deadline_at:
            raise ExecutionControlError(
                OPERATION_RECEIPT_REQUIRED,
                "operation receipt deadline does not match execution context",
                receipt_id=self.operation_receipt_id,
            )
        if not isinstance(getattr(receipt, "state", missing), str):
            raise ExecutionControlError(
                OPERATION_RECEIPT_REQUIRED,
                "operation receipt state is missing or invalid",
                receipt_id=self.operation_receipt_id,
            )

    def safe_point(
        self,
        phase: str,
        completed: int,
        total: int,
        counters: Mapping[str, object] | None = None,
        *,
        work_unit: str = "units",
        sequence: int | None = None,
    ) -> Any:
        if self._committed:
            raise ExecutionControlError(
                OPERATION_RECEIPT_REQUIRED,
                "operation is already committed; query its durable receipt",
                receipt_id=self.operation_receipt_id,
            )
        self._raise_if_cancelled_or_expired()
        self._enforce_scratch()
        if self.progress_port is None:
            raise ExecutionControlError(
                "PROGRESS_PERSISTENCE_REQUIRED",
                "execution control requires a durable progress port",
                receipt_id=self.operation_receipt_id,
            )
        payload = (phase, completed, total, work_unit, json_fingerprint(counters or {}))
        now = self._now()
        if (
            self.progress_stall_seconds is not None
            and self._last_progress_at is not None
            and self._last_progress_payload == payload
            and (now - self._last_progress_at).total_seconds() >= self.progress_stall_seconds
        ):
            self._request_checkpoint("PROGRESS_STALLED")
            raise ExecutionControlError(
                PROGRESS_STALLED,
                "progress has not advanced within the configured stall window",
                receipt_id=self.operation_receipt_id,
            )
        result = self.progress_port.record_progress(
            attempt_id=self.attempt_id,
            phase=phase,
            completed_units=completed,
            total_units=total,
            work_unit=work_unit,
            counters=dict(counters or {}),
            sequence=sequence,
            occurred_at=now,
        )
        if self._last_progress_payload != payload or self._last_progress_at is None:
            self._last_progress_at = now
        self._last_progress_payload = payload
        return result

    def check_stall(self) -> None:
        """Run the watchdog without fabricating a progress record."""

        if self._committed:
            return
        self._raise_if_cancelled_or_expired()
        self._enforce_scratch()
        if self.progress_stall_seconds is None or self._last_progress_at is None:
            return
        if (self._now() - self._last_progress_at).total_seconds() >= self.progress_stall_seconds:
            self._request_checkpoint("PROGRESS_STALLED")
            raise ExecutionControlError(
                PROGRESS_STALLED,
                "progress watchdog detected a stalled operation",
                receipt_id=self.operation_receipt_id,
            )

    def before_irreversible_commit(self, commit_kind: str, expected_hash: str) -> None:
        if not isinstance(commit_kind, str) or not 1 <= len(commit_kind) <= 128:
            raise ValueError("commit_kind is not bounded")
        if not _is_sha256(expected_hash):
            raise ValueError("expected_hash must be a lowercase SHA-256")
        if (
            self._expected_commit_hash is not None
            and self._expected_commit_hash != expected_hash
        ):
            raise ExecutionControlError(
                OPERATION_RECEIPT_REQUIRED,
                "irreversible commit hash changed after the pre-commit gate",
                receipt_id=self.operation_receipt_id,
            )
        if self._committed:
            raise ExecutionControlError(
                OPERATION_RECEIPT_REQUIRED,
                "irreversible commit was already recorded; query its durable receipt",
                receipt_id=self.operation_receipt_id,
            )
        self._raise_if_cancelled_or_expired()
        self._enforce_scratch()
        if self.receipt_persistence is not None:
            try:
                receipt = self.receipt_persistence.receipt(self.operation_receipt_id)
            except KeyError as error:
                raise ExecutionControlError(
                    OPERATION_RECEIPT_REQUIRED,
                    "irreversible commit requires a durable operation receipt",
                    receipt_id=self.operation_receipt_id,
                ) from error
            self._assert_receipt_binding(receipt)
            if receipt.state in {"COMMITTED", "SUCCEEDED"}:
                raise ExecutionControlError(
                    OPERATION_RECEIPT_REQUIRED,
                    "irreversible commit already has durable finality; query its receipt",
                    receipt_id=self.operation_receipt_id,
                )
            if receipt.state not in {"ACCEPTED", "RUNNING"}:
                raise ExecutionControlError(
                    OPERATION_RECEIPT_NOT_RUNNING,
                    f"receipt is not pre-commit: {receipt.state}",
                    receipt_id=self.operation_receipt_id,
                )
        # This flag is set only after every abortable pre-commit gate passes.
        # mark_committed() is the post-owner-commit marker and cannot replace
        # the final cancellation/deadline/generation/receipt check.
        self._expected_commit_hash = expected_hash
        self._commit_armed = True

    def mark_committed(
        self,
        commit_receipt: Mapping[str, object] | str | None = None,
    ) -> CommitReceipt | Any:
        """Persist COMMITTED before constructing a response.

        A caller may pass an outcome mapping or an already published artifact
        identity.  The durable receipt store is authoritative when provided;
        a missing store is deliberately an error rather than a false success.
        """

        if self._committed:
            if self.receipt_persistence is None:
                return commit_receipt
            return self.receipt_persistence.receipt(self.operation_receipt_id)
        now = self._now()
        outcome: Mapping[str, object] | None = None
        outcome_artifact_id: str | None = None
        if isinstance(commit_receipt, Mapping):
            _validate_strict_json(commit_receipt, name="commit outcome")
            outcome = dict(commit_receipt)
        elif isinstance(commit_receipt, str):
            if not commit_receipt.startswith("art_sha256_") or not _is_sha256(
                commit_receipt.removeprefix("art_sha256_")
            ):
                raise ValueError("commit outcome artifact identity must be canonical SHA-256")
            outcome_artifact_id = commit_receipt
        if not self._commit_armed:
            raise ExecutionControlError(
                OPERATION_RECEIPT_REQUIRED,
                "commit must be armed by before_irreversible_commit first",
                receipt_id=self.operation_receipt_id,
            )
        observed_hash = (
            json_fingerprint(outcome)
            if outcome is not None
            else (
                None
                if outcome_artifact_id is None
                else outcome_artifact_id.removeprefix("art_sha256_")
            )
        )
        if observed_hash != self._expected_commit_hash:
            raise ExecutionControlError(
                OPERATION_RECEIPT_REQUIRED,
                "commit receipt does not match the pre-commit expected hash",
                receipt_id=self.operation_receipt_id,
            )
        if self.receipt_persistence is None:
            raise ExecutionControlError(
                OPERATION_RECEIPT_REQUIRED,
                "commit cannot be acknowledged without a durable operation receipt",
                receipt_id=self.operation_receipt_id,
            )
        try:
            current = self.receipt_persistence.receipt(self.operation_receipt_id)
        except KeyError as error:
            raise ExecutionControlError(
                OPERATION_RECEIPT_REQUIRED,
                "commit cannot be acknowledged without a durable operation receipt",
                receipt_id=self.operation_receipt_id,
            ) from error
        self._assert_receipt_binding(current)
        if current.state in {"COMMITTED", "SUCCEEDED"}:
            raise ExecutionControlError(
                OPERATION_RECEIPT_REQUIRED,
                "operation commit already has durable finality; query its receipt",
                receipt_id=self.operation_receipt_id,
            )
        if current.state == "ACCEPTED":
            current = self.receipt_persistence.transition_receipt(
                self.operation_receipt_id,
                expected_state="ACCEPTED",
                new_state="RUNNING",
            )
        if current.state != "RUNNING":
            raise ExecutionControlError(
                OPERATION_RECEIPT_NOT_RUNNING,
                f"receipt is not running: {current.state}",
                receipt_id=self.operation_receipt_id,
            )
        result = self.receipt_persistence.transition_receipt(
            self.operation_receipt_id,
            expected_state="RUNNING",
            new_state="COMMITTED",
            outcome=outcome,
            outcome_artifact_id=outcome_artifact_id,
            commit_boundary_at=now,
        )
        self._committed = True
        return result


def json_fingerprint(value: Mapping[str, object]) -> str:
    _validate_strict_json(value, name="execution-control JSON")
    encoded = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CancellationPort",
    "CheckpointPort",
    "CommitReceipt",
    "DEADLINE_EXCEEDED_PRE_COMMIT",
    "EXECUTION_CANCELLED_PRE_COMMIT",
    "ExecutionControlContext",
    "ExecutionControlError",
    "GenerationPort",
    "OPERATION_RECEIPT_NOT_RUNNING",
    "OPERATION_RECEIPT_REQUIRED",
    "PROGRESS_STALLED",
    "ProgressPort",
    "RESOURCE_EXHAUSTED_MEMORY",
    "RESOURCE_EXHAUSTED_SCRATCH",
    "RUNTIME_GENERATION_MISMATCH",
    "ScratchObservation",
    "ScratchPort",
]
