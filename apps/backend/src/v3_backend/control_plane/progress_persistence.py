"""SQLite owners for durable progress, dispatch holds, generations and receipts."""

from __future__ import annotations

import json
import hashlib
import sqlite3
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .persistence import ConcurrentStateChange
from .resource_governor import ZERO_HASH
from v3_backend.adapters.sqlite.connection import connect_catalog


PROGRESS_PHASES = frozenset(
    {
        # The isolated worker transport already exposed these pipeline phases
        # before PR03.  Keep them admitted at the persistence boundary while
        # the domain execution context uses the more specific phases below.
        "DISPATCHED",
        "EXECUTING",
        "PUBLISHED",
        "ACQUIRING",
        "VALIDATING",
        "COMPUTING",
        "PUBLISHING",
        "RECONCILING",
    }
)
DISPATCH_STATES = frozenset({"HOLD", "READY", "DISPATCHED", "TERMINAL"})
RECEIPT_STATES = frozenset(
    {"ACCEPTED", "RUNNING", "PRE_COMMIT_ABORTED", "COMMITTED", "SUCCEEDED", "FAILED"}
)
_DISPATCH_TRANSITIONS = {
    ("HOLD", "READY"),
    ("HOLD", "TERMINAL"),
    ("READY", "DISPATCHED"),
    ("READY", "HOLD"),
    ("DISPATCHED", "TERMINAL"),
}
_RECEIPT_TRANSITIONS = {
    ("ACCEPTED", "RUNNING"),
    ("ACCEPTED", "PRE_COMMIT_ABORTED"),
    ("ACCEPTED", "FAILED"),
    ("RUNNING", "PRE_COMMIT_ABORTED"),
    ("RUNNING", "COMMITTED"),
    ("RUNNING", "FAILED"),
    ("COMMITTED", "SUCCEEDED"),
}


class ProgressConflict(RuntimeError):
    """Progress sequence was missing, reordered or had a conflicting payload."""


class DispatchStateConflict(RuntimeError):
    pass


class ReceiptStateConflict(RuntimeError):
    pass


class RuntimeResolutionConflict(RuntimeError):
    """A Run was already bound to a different execution resolution."""


_TERMINAL_RECEIPT_STATES = frozenset({"PRE_COMMIT_ABORTED", "SUCCEEDED", "FAILED"})
_DEFAULT_RESOLUTION = (
    "1.0.0",
    "1.0.0",
    "{}",
    ZERO_HASH,
    ZERO_HASH,
)


def _wire_time(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("execution control timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)


def _identity(prefix: str) -> str:
    # Catalog IDs only require the canonical prefix at this layer.  Product
    # callers inject mint_v3_id so all normal IDs retain the V3 Crockford form.
    return prefix + uuid.uuid4().hex[:26].upper()


def _bounded_text(value: object, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{name} must be a bounded non-empty string")
    return value


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(char in "0123456789abcdef" for char in value)
    )


def _validate_strict_json(value: object, *, name: str) -> None:
    """Reject Python values that ``json.dumps`` would silently coerce.

    ``json.dumps`` accepts integer mapping keys and converts them to strings.
    That is unsafe at a durable protocol boundary because the value read back
    from SQLite would no longer equal the value that was admitted.  Walk the
    complete value first, then let the encoder reject non-finite numbers and
    unsupported objects.
    """

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


_PROGRESS_COUNTERS_MAX_BYTES = 32768


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    """Decode JSON objects without silently accepting duplicate keys."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant is not admitted: {value}")


def _decode_progress_counters(raw: object) -> dict[str, object]:
    """Read a Catalog counter object with the same rules as its writer.

    SQLite's ``json_valid`` check only proves that a value parses as JSON.  It
    does not reject a scalar, duplicate keys, non-canonical whitespace or
    non-finite constants.  A Catalog can also be inspected after an external
    copy/repair, so every read must re-establish the durable boundary before a
    worker or queue consumer uses the counters.
    """

    if not isinstance(raw, str) or not raw:
        raise ProgressConflict("durable progress counters are not a JSON object")
    try:
        if len(raw.encode("utf-8")) > _PROGRESS_COUNTERS_MAX_BYTES:
            raise ValueError("counter payload exceeds the Catalog bound")
        decoded = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
        if not isinstance(decoded, dict):
            raise ValueError("counter payload must be a JSON object")
        if any(not key or len(key) > 128 for key in decoded):
            raise ValueError("counter object keys are outside the admitted bound")
        _validate_strict_json(decoded, name="durable progress counters")
        canonical = json.dumps(
            decoded,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if raw != canonical:
            raise ValueError("counter payload is not canonical JSON")
        return decoded
    except ProgressConflict:
        raise
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise ProgressConflict(
            "durable progress counters are not strict canonical JSON"
        ) from error


def compatibility_hash_for_context(
    *,
    input_hash: str,
    code_version: str,
    environment_profile: str,
    operation_id: str,
    operation_schema_version: str,
    resource_policy_version: str,
    resolved_resource_hash: str,
) -> str:
    """Hash the immutable execution identity used by dispatch and resume."""

    for name, value in (
        ("input_hash", input_hash),
        ("resolved_resource_hash", resolved_resource_hash),
    ):
        if not _is_sha256(value):
            raise ValueError(f"{name} must be a lowercase SHA-256")
    for name, value, maximum in (
        ("code_version", code_version, 256),
        ("environment_profile", environment_profile, 256),
        ("operation_id", operation_id, 256),
        ("operation_schema_version", operation_schema_version, 128),
        ("resource_policy_version", resource_policy_version, 128),
    ):
        _bounded_text(value, name, maximum)
    payload = {
        "code_version": code_version,
        "environment_profile": environment_profile,
        "input_hash": input_hash,
        "operation_id": operation_id,
        "operation_schema_version": operation_schema_version,
        "resolved_resource_hash": resolved_resource_hash,
        "resource_policy_version": resource_policy_version,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class ProgressRecord:
    attempt_id: str
    sequence: int
    phase: str
    completed_units: int
    total_units: int
    work_unit: str
    counters: Mapping[str, object]
    occurred_at: datetime
    persisted_at: datetime

    def payload(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "completed_units": self.completed_units,
            "total_units": self.total_units,
            "work_unit": self.work_unit,
            "counters": dict(self.counters),
        }


@dataclass(frozen=True)
class DispatchControl:
    task_id: str
    state: str
    hold_reason: str | None
    user_confirmed_at: datetime | None
    state_version: int
    updated_at: datetime


@dataclass(frozen=True)
class RuntimeGenerationRebind:
    attempt_id: str
    previous_runtime_generation_id: str | None
    runtime_generation_id: str
    receipt_rebound: bool


@dataclass(frozen=True)
class OperationReceipt:
    operation_receipt_id: str
    correlation_id: str
    operation_id: str
    project_id: str
    task_id: str | None
    run_id: str | None
    attempt_id: str | None
    deadline_at: datetime
    runtime_generation_id: str | None
    state: str
    commit_boundary_at: datetime | None
    outcome_json: str | None
    outcome_artifact_id: str | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    terminal_at: datetime | None
    state_version: int


class ProgressPersistence:
    """Single sidecar owner for the PR03 durable execution-control tables."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        identity_new: Callable[[str], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.database_path = Path(database_path).resolve()
        self.identity_new = identity_new or _identity
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _event_id(self) -> str:
        return self.identity_new("tev_")

    @staticmethod
    def _progress_from_row(row: Any) -> ProgressRecord:
        try:
            attempt_id = row[0]
            sequence = row[1]
            phase = row[2]
            completed_units = row[3]
            total_units = row[4]
            work_unit = row[5]
            occurred_at_wire = row[7]
            persisted_at_wire = row[8]
            if (
                not isinstance(attempt_id, str)
                or not attempt_id
                or len(attempt_id) > 128
                or not isinstance(sequence, int)
                or isinstance(sequence, bool)
                or sequence < 1
                or not isinstance(phase, str)
                or phase not in PROGRESS_PHASES
                or not isinstance(completed_units, int)
                or isinstance(completed_units, bool)
                or not isinstance(total_units, int)
                or isinstance(total_units, bool)
                or total_units < 1
                or completed_units < 0
                or completed_units > total_units
                or not isinstance(work_unit, str)
                or not work_unit
                or len(work_unit) > 128
                or not isinstance(occurred_at_wire, str)
                or not isinstance(persisted_at_wire, str)
            ):
                raise ValueError("progress row fields are outside the admitted bounds")
            occurred_at = _parse_time(occurred_at_wire)
            persisted_at = _parse_time(persisted_at_wire)
            if (
                occurred_at.tzinfo is None
                or occurred_at.utcoffset() is None
                or persisted_at.tzinfo is None
                or persisted_at.utcoffset() is None
            ):
                raise ValueError("progress timestamps must include a timezone")
            counters = _decode_progress_counters(row[6])
            return ProgressRecord(
                attempt_id=attempt_id,
                sequence=sequence,
                phase=phase,
                completed_units=completed_units,
                total_units=total_units,
                work_unit=work_unit,
                counters=counters,
                occurred_at=occurred_at,
                persisted_at=persisted_at,
            )
        except ProgressConflict:
            raise
        except (IndexError, TypeError, ValueError, OverflowError) as error:
            raise ProgressConflict("durable progress row is invalid") from error

    def ensure_dispatch_hold(
        self,
        task_id: str,
        *,
        hold_reason: str = "ACCEPTED_NOT_STARTED",
        updated_at: datetime | None = None,
    ) -> DispatchControl:
        now = _wire_time(updated_at or self.clock())
        connection = connect_catalog(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO task_dispatch_control(task_id,state,hold_reason,state_version,updated_at)
                VALUES(?, 'HOLD', ?, 0, ?)
                ON CONFLICT(task_id) DO NOTHING
                """,
                (task_id, hold_reason, now),
            )
            row = connection.execute(
                """
                SELECT task_id,state,hold_reason,user_confirmed_at,state_version,updated_at
                FROM task_dispatch_control WHERE task_id=?
                """,
                (task_id,),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            connection.commit()
            return self._dispatch_from_row(row)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _dispatch_from_row(row: Any) -> DispatchControl:
        return DispatchControl(
            task_id=str(row[0]),
            state=str(row[1]),
            hold_reason=None if row[2] is None else str(row[2]),
            user_confirmed_at=None if row[3] is None else _parse_time(str(row[3])),
            state_version=int(row[4]),
            updated_at=_parse_time(str(row[5])),
        )

    def transition_dispatch(
        self,
        task_id: str,
        *,
        expected_state: str,
        new_state: str,
        hold_reason: str | None = None,
        user_confirmed_at: datetime | None = None,
    ) -> DispatchControl:
        if expected_state not in DISPATCH_STATES or new_state not in DISPATCH_STATES:
            raise ValueError("unknown dispatch control state")
        if expected_state != new_state and (expected_state, new_state) not in _DISPATCH_TRANSITIONS:
            raise DispatchStateConflict(f"dispatch transition {expected_state}->{new_state} is not admitted")
        now_dt = self.clock()
        now = _wire_time(now_dt)
        connection = connect_catalog(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = self._dispatch_row_on_connection(connection, task_id)
            if current is None:
                raise KeyError(task_id)
            if expected_state == new_state:
                if str(current[1]) != expected_state:
                    raise DispatchStateConflict(
                        f"dispatch state changed: {task_id}"
                    )
                # A same-state CAS is an idempotent read.  In particular, it
                # must not clear the confirmation evidence on DISPATCHED.
                connection.commit()
                return self._dispatch_from_row(current)
            if new_state == "READY":
                if expected_state != "HOLD" or user_confirmed_at is None:
                    raise DispatchStateConflict(
                        "READY requires an explicit user confirmation"
                    )
                confirmed = _wire_time(user_confirmed_at)
                if _parse_time(confirmed) > now_dt.astimezone(timezone.utc):
                    raise DispatchStateConflict(
                        "user confirmation cannot be dated in the future"
                    )
            elif expected_state == "READY" and new_state == "DISPATCHED":
                if current[3] is None:
                    raise DispatchStateConflict(
                        "DISPATCHED requires a prior user-confirmed READY state"
                    )
                # Confirmation is immutable evidence of the READY admission;
                # a DISPATCHED transition must not replace or clear it.
                confirmed = str(current[3])
            else:
                confirmed = None
            cursor = connection.execute(
                """
                UPDATE task_dispatch_control
                SET state=?, hold_reason=?, user_confirmed_at=?,
                    state_version=state_version+1, updated_at=?
                WHERE task_id=? AND state=?
                """,
                (new_state, hold_reason, confirmed, now, task_id, expected_state),
            )
            if cursor.rowcount != 1:
                raise DispatchStateConflict(f"dispatch state changed: {task_id}")
            row = connection.execute(
                """
                SELECT task_id,state,hold_reason,user_confirmed_at,state_version,updated_at
                FROM task_dispatch_control WHERE task_id=?
                """,
                (task_id,),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            connection.commit()
            return self._dispatch_from_row(row)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def transition_dispatch_in_transaction(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        *,
        expected_state: str,
        new_state: str,
        expected_state_version: int,
        hold_reason: str | None = None,
        user_confirmed_at: datetime | None = None,
    ) -> DispatchControl:
        """CAS dispatch state inside a caller-owned Catalog transaction.

        TaskControl uses this form to bind the user-confirmed HOLD -> READY
        admission to the same transaction that re-reads the Task, Run and
        Attempt.  Dispatch remains owned by this sidecar; the caller only
        supplies the surrounding transaction.
        """

        if expected_state not in DISPATCH_STATES or new_state not in DISPATCH_STATES:
            raise ValueError("unknown dispatch control state")
        if expected_state != new_state and (expected_state, new_state) not in _DISPATCH_TRANSITIONS:
            raise DispatchStateConflict(
                f"dispatch transition {expected_state}->{new_state} is not admitted"
            )
        if (
            isinstance(expected_state_version, bool)
            or not isinstance(expected_state_version, int)
            or expected_state_version < 0
        ):
            raise ValueError("expected dispatch state version is invalid")
        now_dt = self.clock()
        now = _wire_time(now_dt)
        current = self._dispatch_row_on_connection(connection, task_id)
        if current is None:
            raise KeyError(task_id)
        if str(current[1]) != expected_state or int(current[4]) != expected_state_version:
            raise DispatchStateConflict(f"dispatch state or version is stale: {task_id}")
        if expected_state == new_state:
            return self._dispatch_from_row(current)
        if new_state == "READY":
            if expected_state != "HOLD" or user_confirmed_at is None:
                raise DispatchStateConflict(
                    "READY requires an explicit user confirmation"
                )
            confirmed = _wire_time(user_confirmed_at)
            if _parse_time(confirmed) > now_dt.astimezone(timezone.utc):
                raise DispatchStateConflict(
                    "user confirmation cannot be dated in the future"
                )
        elif expected_state == "READY" and new_state == "DISPATCHED":
            if current[3] is None:
                raise DispatchStateConflict(
                    "DISPATCHED requires a prior user-confirmed READY state"
                )
            confirmed = str(current[3])
        else:
            confirmed = None
        cursor = connection.execute(
            """
            UPDATE task_dispatch_control
            SET state=?, hold_reason=?, user_confirmed_at=?,
                state_version=state_version+1, updated_at=?
            WHERE task_id=? AND state=? AND state_version=?
            """,
            (
                new_state,
                hold_reason,
                confirmed,
                now,
                task_id,
                expected_state,
                expected_state_version,
            ),
        )
        if cursor.rowcount != 1:
            raise DispatchStateConflict(f"dispatch state changed: {task_id}")
        row = self._dispatch_row_on_connection(connection, task_id)
        if row is None:
            raise KeyError(task_id)
        return self._dispatch_from_row(row)

    def rebind_queued_attempt_generation_in_transaction(
        self,
        connection: sqlite3.Connection,
        attempt_id: str,
        *,
        runtime_generation_id: str,
    ) -> RuntimeGenerationRebind:
        """Bind a restart-held Attempt to the generation that will execute it.

        Acceptance records the generation that created an Attempt, but a
        queued Attempt may survive that process.  Only an explicit start may
        replace that pre-execution binding, and only while the Attempt is
        QUEUED, its dispatch row is HOLD, and any linked receipt is ACCEPTED.
        The caller's transaction then records the generation change together
        with the HOLD -> READY admission.
        """

        _bounded_text(attempt_id, "attempt_id", 128)
        _bounded_text(runtime_generation_id, "runtime_generation_id", 128)
        generation = connection.execute(
            """
            SELECT 1
            FROM runtime_generation
            WHERE runtime_generation_id=? AND clean_shutdown_at IS NULL
            """,
            (runtime_generation_id,),
        ).fetchone()
        if generation is None:
            raise RuntimeResolutionConflict(
                "target runtime generation identity is not open"
            )
        row = connection.execute(
            """
            SELECT a.state,a.runtime_generation_id,t.state,c.state,
                   o.operation_receipt_id,o.state,o.runtime_generation_id
            FROM task_attempt AS a
            JOIN run AS r ON r.run_id=a.run_id
            JOIN task AS t ON t.task_id=r.task_id
            JOIN task_dispatch_control AS c ON c.task_id=t.task_id
            LEFT JOIN control_operation_receipt AS o ON o.attempt_id=a.attempt_id
            WHERE a.attempt_id=?
            ORDER BY o.created_at DESC, o.operation_receipt_id DESC
            LIMIT 1
            """,
            (attempt_id,),
        ).fetchone()
        if row is None:
            raise KeyError(attempt_id)
        if str(row[0]) != "QUEUED" or str(row[2]) not in {"QUEUED", "PAUSED"}:
            raise RuntimeResolutionConflict(
                "only a queued restart-held Attempt may change runtime generation"
            )
        if str(row[3]) != "HOLD":
            raise RuntimeResolutionConflict(
                "runtime generation may only change while dispatch control is HOLD"
            )
        active_lease = connection.execute(
            """
            SELECT 1 FROM worker_lease
            WHERE attempt_id=? AND state IN ('GRANTED','RENEWED','EXPIRED')
            LIMIT 1
            """,
            (attempt_id,),
        ).fetchone()
        if active_lease is not None:
            raise RuntimeResolutionConflict(
                "runtime generation cannot change while an Attempt has an active lease"
            )
        receipt_id = None if row[4] is None else str(row[4])
        receipt_state = None if row[5] is None else str(row[5])
        receipt_generation = None if row[6] is None else str(row[6])
        if receipt_id is not None and receipt_state != "ACCEPTED":
            raise RuntimeResolutionConflict(
                "runtime generation cannot change after a receipt leaves ACCEPTED"
            )
        previous = None if row[1] is None else str(row[1])
        attempt_updated = connection.execute(
            """
            UPDATE task_attempt
            SET runtime_generation_id=?
            WHERE attempt_id=? AND state='QUEUED'
            """,
            (runtime_generation_id, attempt_id),
        )
        if attempt_updated.rowcount != 1:
            raise RuntimeResolutionConflict(
                "Attempt changed while rebinding its runtime generation"
            )
        receipt_rebound = False
        if receipt_id is not None and receipt_generation != runtime_generation_id:
            receipt_updated = connection.execute(
                """
                UPDATE control_operation_receipt
                SET runtime_generation_id=?,updated_at=?
                WHERE operation_receipt_id=? AND state='ACCEPTED'
                """,
                (runtime_generation_id, _wire_time(self.clock()), receipt_id),
            )
            if receipt_updated.rowcount != 1:
                raise RuntimeResolutionConflict(
                    "operation receipt changed while rebinding its runtime generation"
                )
            receipt_rebound = True
        return RuntimeGenerationRebind(
            attempt_id=attempt_id,
            previous_runtime_generation_id=previous,
            runtime_generation_id=runtime_generation_id,
            receipt_rebound=receipt_rebound,
        )

    def dispatch_control(self, task_id: str) -> DispatchControl:
        connection = connect_catalog(self.database_path, read_only=True)
        try:
            row = connection.execute(
                "SELECT task_id,state,hold_reason,user_confirmed_at,state_version,updated_at FROM task_dispatch_control WHERE task_id=?",
                (task_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(task_id)
        return self._dispatch_from_row(row)

    def task_id_for_attempt(self, attempt_id: str) -> str:
        """Resolve the canonical Task owner for a worker Attempt."""

        _bounded_text(attempt_id, "attempt_id", 128)
        connection = connect_catalog(self.database_path, read_only=True)
        try:
            row = connection.execute(
                """
                SELECT r.task_id
                FROM task_attempt AS a
                JOIN run AS r ON r.run_id=a.run_id
                WHERE a.attempt_id=?
                """,
                (attempt_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(attempt_id)
        return str(row[0])

    def execution_context_for_attempt(self, attempt_id: str) -> dict[str, object]:
        """Read the immutable Run/Task context before a worker is admitted."""

        _bounded_text(attempt_id, "attempt_id", 128)
        connection = connect_catalog(self.database_path, read_only=True)
        try:
            row = connection.execute(
                """
                SELECT a.attempt_id,a.run_id,r.task_id,t.operation_id,
                       r.input_hash,r.code_version,r.environment_profile_id,
                       r.operation_schema_version,r.resource_policy_version,
                       r.resolved_resource_hash,r.compatibility_hash,
                       r.canonical_input_json,t.execution_deadline_at,
                       a.execution_deadline_at,a.runtime_generation_id
                FROM task_attempt AS a
                JOIN run AS r ON r.run_id=a.run_id
                JOIN task AS t ON t.task_id=r.task_id
                WHERE a.attempt_id=?
                """,
                (attempt_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(attempt_id)
        try:
            canonical_input = json.loads(str(row[11]))
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeResolutionConflict(
                "Run canonical_input_json is not valid JSON"
            ) from error
        if not isinstance(canonical_input, dict):
            raise RuntimeResolutionConflict("Run canonical_input_json must be an object")
        try:
            _validate_strict_json(canonical_input, name="Run canonical_input_json")
        except ValueError as error:
            raise RuntimeResolutionConflict(
                "Run canonical_input_json is not strict JSON"
            ) from error
        return {
            "attempt_id": str(row[0]),
            "run_id": str(row[1]),
            "task_id": str(row[2]),
            "operation_id": str(row[3]),
            "input_hash": str(row[4]),
            "code_version": str(row[5]),
            "environment_profile": str(row[6]),
            "operation_schema_version": str(row[7]),
            "resource_policy_version": str(row[8]),
            "resolved_resource_hash": str(row[9]),
            "compatibility_hash": str(row[10]),
            "canonical_input": canonical_input,
            "task_deadline_at": None if row[12] is None else str(row[12]),
            "attempt_deadline_at": None if row[13] is None else str(row[13]),
            "runtime_generation_id": None if row[14] is None else str(row[14]),
        }

    @staticmethod
    def _dispatch_row_on_connection(
        connection: sqlite3.Connection, task_id: str
    ) -> Any:
        return connection.execute(
            """
            SELECT task_id,state,hold_reason,user_confirmed_at,state_version,updated_at
            FROM task_dispatch_control WHERE task_id=?
            """,
            (task_id,),
        ).fetchone()

    def mark_dispatched_in_transaction(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        *,
        user_confirmed_at: datetime | None = None,
    ) -> DispatchControl:
        """Record the admitted start and dispatch in one caller-owned UoW.

        The two state changes remain separate SQL CAS updates even though the
        caller commits them atomically. This leaves an auditable HOLD -> READY
        -> DISPATCHED path and prevents a direct queue bypass.
        """

        _bounded_text(task_id, "task_id", 128)
        now_dt = self.clock()
        now = _wire_time(now_dt)
        row = self._dispatch_row_on_connection(connection, task_id)
        if row is None:
            raise KeyError(task_id)
        state = str(row[1])
        if state == "TERMINAL":
            raise DispatchStateConflict("terminal task cannot be dispatched")
        if state == "DISPATCHED":
            if row[3] is None:
                raise DispatchStateConflict(
                    "DISPATCHED requires a prior user-confirmed READY state"
                )
            return self._dispatch_from_row(row)
        if state not in {"HOLD", "READY"}:
            raise DispatchStateConflict(f"dispatch state cannot start: {state}")
        if state == "HOLD":
            confirmed = _wire_time(user_confirmed_at or now_dt)
            if _parse_time(confirmed) > now_dt.astimezone(timezone.utc):
                raise DispatchStateConflict(
                    "user confirmation cannot be dated in the future"
                )
            cursor = connection.execute(
                """
                UPDATE task_dispatch_control
                SET state='READY', hold_reason=NULL, user_confirmed_at=?,
                    state_version=state_version+1, updated_at=?
                WHERE task_id=? AND state='HOLD' AND state_version=?
                """,
                (confirmed, now, task_id, int(row[4])),
            )
            if cursor.rowcount != 1:
                raise DispatchStateConflict(f"dispatch state changed: {task_id}")
            row = self._dispatch_row_on_connection(connection, task_id)
            if row is None:
                raise KeyError(task_id)
        elif row[3] is None:
            raise DispatchStateConflict(
                "DISPATCHED requires a prior user-confirmed READY state"
            )
        cursor = connection.execute(
            """
            UPDATE task_dispatch_control
            SET state='DISPATCHED', hold_reason=NULL,
                state_version=state_version+1, updated_at=?
            WHERE task_id=? AND state='READY' AND state_version=?
            """,
            (now, task_id, int(row[4])),
        )
        if cursor.rowcount != 1:
            raise DispatchStateConflict(f"dispatch state changed: {task_id}")
        updated = self._dispatch_row_on_connection(connection, task_id)
        if updated is None:
            raise KeyError(task_id)
        return self._dispatch_from_row(updated)

    def mark_dispatched(self, task_id: str) -> DispatchControl:
        """CAS the accepted queue item through READY to DISPATCHED.

        The public product path historically starts an accepted task in the
        same call that creates it, while the durable contract still requires a
        HOLD at acceptance.  Keeping both transitions in one transaction
        preserves that history without admitting a direct HOLD->DISPATCHED
        bypass.
        """

        connection = connect_catalog(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            updated = self.mark_dispatched_in_transaction(
                connection, task_id, user_confirmed_at=self.clock()
            )
            connection.commit()
            return updated
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def hold_after_restart(self, task_id: str) -> DispatchControl:
        """Rebuild a queue item as a user-visible HOLD after a crash."""

        now = _wire_time(self.clock())
        connection = connect_catalog(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT task_id,state,hold_reason,user_confirmed_at,state_version,updated_at
                FROM task_dispatch_control WHERE task_id=?
                """,
                (task_id,),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            if str(row[1]) == "TERMINAL":
                connection.commit()
                return self._dispatch_from_row(row)
            cursor = connection.execute(
                """
                UPDATE task_dispatch_control
                SET state='HOLD', hold_reason='HOLD_AFTER_RESTART',
                    user_confirmed_at=NULL,
                    state_version=state_version+1, updated_at=?
                WHERE task_id=? AND state<> 'TERMINAL'
                """,
                (now, task_id),
            )
            if cursor.rowcount != 1:
                raise DispatchStateConflict(f"dispatch state changed: {task_id}")
            updated = connection.execute(
                """
                SELECT task_id,state,hold_reason,user_confirmed_at,state_version,updated_at
                FROM task_dispatch_control WHERE task_id=?
                """,
                (task_id,),
            ).fetchone()
            if updated is None:
                raise KeyError(task_id)
            connection.commit()
            return self._dispatch_from_row(updated)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_dispatch_controls(
        self, project_id: str, *, states: tuple[str, ...] = DISPATCH_STATES
    ) -> tuple[DispatchControl, ...]:
        if not states or any(state not in DISPATCH_STATES for state in states):
            raise ValueError("invalid dispatch state filter")
        placeholders = ",".join("?" for _ in states)
        connection = connect_catalog(self.database_path, read_only=True)
        try:
            rows = connection.execute(
                f"""
                SELECT control.task_id,control.state,control.hold_reason,
                       control.user_confirmed_at,control.state_version,control.updated_at
                FROM task_dispatch_control AS control
                JOIN task ON task.task_id=control.task_id
                WHERE task.project_id=? AND control.state IN ({placeholders})
                ORDER BY control.updated_at,control.task_id
                """,
                (project_id, *states),
            ).fetchall()
        finally:
            connection.close()
        return tuple(self._dispatch_from_row(row) for row in rows)

    def list_dispatch_controls_page(
        self,
        project_id: str,
        *,
        states: tuple[str, ...] = tuple(sorted(DISPATCH_STATES)),
        page_size: int = 200,
        after: tuple[str, str] | None = None,
    ) -> tuple[dict[str, object], ...]:
        """Read a bounded, project-scoped queue page from the control owner.

        ``after`` is the decoded ``(updated_at, task_id)`` sort key from the
        facade's opaque cursor.  The query returns one extra row so the
        caller can decide whether another page exists without an unbounded
        count query or loading the whole queue into memory.
        """

        if not isinstance(project_id, str) or not project_id:
            raise ValueError("project_id must be a non-empty string")
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or not 1 <= page_size <= 200
        ):
            raise ValueError("page_size must be between 1 and 200")
        if (
            not states
            or len(set(states)) != len(states)
            or any(state not in DISPATCH_STATES for state in states)
        ):
            raise ValueError("invalid dispatch state filter")
        if after is not None:
            if (
                not isinstance(after, tuple)
                or len(after) != 2
                or not isinstance(after[0], str)
                or not isinstance(after[1], str)
                or not after[1]
                or len(after[1]) > 128
            ):
                raise ValueError("queue cursor sort key is invalid")
            try:
                _parse_time(after[0])
            except (TypeError, ValueError) as error:
                raise ValueError("queue cursor timestamp is invalid") from error
        placeholders = ",".join("?" for _ in states)
        after_sql = ""
        parameters: list[object] = [project_id, *states]
        if after is not None:
            after_sql = (
                "AND (control.updated_at > ? "
                "OR (control.updated_at = ? AND control.task_id > ?)) "
            )
            parameters.extend((after[0], after[0], after[1]))
        parameters.append(page_size + 1)
        connection = connect_catalog(self.database_path, read_only=True)
        try:
            rows = connection.execute(
                f"""
                SELECT control.task_id AS task_id,
                       control.state AS dispatch_state,
                       control.hold_reason AS hold_reason,
                       control.user_confirmed_at AS user_confirmed_at,
                       control.state_version AS dispatch_state_version,
                       control.updated_at AS dispatch_updated_at,
                       task.operation_id AS operation_id,
                       task.state AS task_state,
                       task.state_version AS task_state_version,
                       task.execution_deadline_at AS execution_deadline_at,
                       run.run_id AS run_id,
                       attempt.attempt_id AS attempt_id,
                       attempt.state AS attempt_state,
                       progress.sequence AS progress_sequence,
                       progress.phase AS progress_phase,
                       progress.completed_units AS progress_completed_units,
                       progress.total_units AS progress_total_units,
                       progress.work_unit AS progress_work_unit,
                       progress.occurred_at AS progress_occurred_at
                FROM task_dispatch_control AS control
                JOIN task ON task.task_id=control.task_id
                LEFT JOIN run
                  ON run.task_id=task.task_id
                 AND run.run_no=(
                    SELECT MAX(latest_run.run_no)
                    FROM run AS latest_run
                    WHERE latest_run.task_id=task.task_id
                 )
                LEFT JOIN task_attempt AS attempt
                  ON attempt.run_id=run.run_id
                 AND attempt.attempt_no=(
                    SELECT MAX(latest_attempt.attempt_no)
                    FROM task_attempt AS latest_attempt
                    WHERE latest_attempt.run_id=run.run_id
                 )
                LEFT JOIN attempt_progress AS progress
                  ON progress.attempt_id=attempt.attempt_id
                 AND progress.sequence=(
                    SELECT MAX(latest_progress.sequence)
                    FROM attempt_progress AS latest_progress
                    WHERE latest_progress.attempt_id=attempt.attempt_id
                 )
                WHERE task.project_id=?
                  AND control.state IN ({placeholders})
                  {after_sql}
                ORDER BY control.updated_at,control.task_id
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        finally:
            connection.close()
        return tuple(dict(row) for row in rows)

    @staticmethod
    def _validate_progress_payload(
        *,
        phase: str,
        completed_units: int,
        total_units: int,
        work_unit: str,
        counters: Mapping[str, object] | None,
        sequence: int | None,
    ) -> tuple[dict[str, object], str]:
        if phase not in PROGRESS_PHASES:
            raise ValueError("Task progress phase is not admitted")
        if (
            isinstance(completed_units, bool)
            or not isinstance(completed_units, int)
            or isinstance(total_units, bool)
            or not isinstance(total_units, int)
            or total_units < 1
            or completed_units < 0
            or completed_units > total_units
        ):
            raise ValueError("Task progress units are invalid")
        _bounded_text(work_unit, "work_unit", 128)
        if counters is not None and not isinstance(counters, Mapping):
            raise ValueError("Task progress counters must be an object")
        counter_map = dict(counters or {})
        if any(
            not isinstance(key, str) or not key or len(key) > 128
            for key in counter_map
        ):
            raise ValueError("Task progress counter keys are invalid")
        try:
            _validate_strict_json(counter_map, name="Task progress counters")
            encoded_counters = json.dumps(
                counter_map,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as error:
            raise ValueError("Task progress counters are not strict JSON") from error
        if len(encoded_counters.encode("utf-8")) > _PROGRESS_COUNTERS_MAX_BYTES:
            raise ValueError("Task progress counters exceed the Catalog bound")
        return counter_map, encoded_counters

    def record_progress(
        self,
        attempt_id: str,
        *,
        phase: str,
        completed_units: int,
        total_units: int,
        work_unit: str,
        counters: Mapping[str, object] | None = None,
        sequence: int | None = None,
        occurred_at: datetime | None = None,
    ) -> ProgressRecord:
        connection = connect_catalog(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            result = self.record_progress_in_transaction(
                connection,
                attempt_id,
                phase=phase,
                completed_units=completed_units,
                total_units=total_units,
                work_unit=work_unit,
                counters=counters,
                sequence=sequence,
                occurred_at=occurred_at,
            )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def record_progress_in_transaction(
        self,
        connection: sqlite3.Connection,
        attempt_id: str,
        *,
        phase: str,
        completed_units: int,
        total_units: int,
        work_unit: str,
        counters: Mapping[str, object] | None = None,
        sequence: int | None = None,
        occurred_at: datetime | None = None,
    ) -> ProgressRecord:
        """Append progress while the caller owns the Task Catalog UoW.

        The final progress record must be committed in the same transaction as
        the Attempt/Task/receipt terminal state.  Opening a second connection
        here would allow a worker to observe ``SUCCEEDED`` with a missing or
        late ``PUBLISHED`` record.
        """

        _bounded_text(attempt_id, "attempt_id", 128)
        counter_map, encoded_counters = self._validate_progress_payload(
            phase=phase,
            completed_units=completed_units,
            total_units=total_units,
            work_unit=work_unit,
            counters=counters,
            sequence=sequence,
        )
        occurred = occurred_at or self.clock()
        occurred_wire = _wire_time(occurred)
        persisted_wire = _wire_time(self.clock())
        owner = connection.execute(
            """
            SELECT a.state,t.project_id,t.task_id,a.run_id,a.progress_sequence
            FROM task_attempt AS a
            JOIN run AS r ON r.run_id=a.run_id
            JOIN task AS t ON t.task_id=r.task_id
            WHERE a.attempt_id=?
            """,
            (attempt_id,),
        ).fetchone()
        if owner is None:
            raise KeyError(attempt_id)
        if str(owner[0]) in {"SUCCEEDED", "FAILED", "CANCELLED", "LOST"}:
            raise ProgressConflict("terminal Attempt cannot advance progress")
        current_sequence = int(owner[4])
        target_sequence = current_sequence + 1 if sequence is None else sequence
        if not isinstance(target_sequence, int) or isinstance(target_sequence, bool) or target_sequence < 1:
            raise ValueError("progress sequence must be a positive integer")
        existing = connection.execute(
            """
            SELECT attempt_id,sequence,phase,completed_units,total_units,work_unit,
                   counters_json,occurred_at,persisted_at
            FROM attempt_progress WHERE attempt_id=? AND sequence=?
            """,
            (attempt_id, target_sequence),
        ).fetchone()
        candidate_payload = {
            "phase": phase,
            "completed_units": completed_units,
            "total_units": total_units,
            "work_unit": work_unit,
            "counters": counter_map,
        }
        if existing is not None:
            existing_record = self._progress_from_row(existing)
            if existing_record.payload() != candidate_payload:
                raise ProgressConflict("same progress sequence has a different payload")
            return existing_record
        if target_sequence != current_sequence + 1:
            raise ProgressConflict("progress sequence is not strictly monotonic")
        connection.execute(
            """
            INSERT INTO attempt_progress(
              attempt_id,sequence,phase,completed_units,total_units,work_unit,
              counters_json,occurred_at,persisted_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                attempt_id,
                target_sequence,
                phase,
                completed_units,
                total_units,
                work_unit,
                encoded_counters,
                occurred_wire,
                persisted_wire,
            ),
        )
        connection.execute(
            """
            UPDATE task_attempt
            SET progress_sequence=?,last_progress_at=?
            WHERE attempt_id=? AND progress_sequence=?
            """,
            (target_sequence, persisted_wire, attempt_id, current_sequence),
        )
        if connection.execute("SELECT changes()").fetchone()[0] != 1:
            raise ConcurrentStateChange(f"Attempt progress changed concurrently: {attempt_id}")
        event_payload = {
            "sequence": target_sequence,
            "phase": phase,
            "completed_units": completed_units,
            "total_units": total_units,
            "work_unit": work_unit,
            "counters": counter_map,
        }
        project_sequence = int(
            connection.execute(
                "SELECT COALESCE(MAX(project_sequence),0)+1 FROM task_event WHERE project_id=?",
                (str(owner[1]),),
            ).fetchone()[0]
        )
        connection.execute(
            """
            INSERT INTO task_event(
              task_event_id,project_id,project_sequence,task_id,run_id,attempt_id,
              event_type,event_version,payload_json,occurred_at,persisted_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                self._event_id(),
                str(owner[1]),
                project_sequence,
                str(owner[2]),
                str(owner[3]),
                attempt_id,
                "TASK_PROGRESS",
                1,
                json.dumps(event_payload, sort_keys=True, separators=(",", ":"), allow_nan=False),
                occurred_wire,
                persisted_wire,
            ),
        )
        return ProgressRecord(
            attempt_id=attempt_id,
            sequence=target_sequence,
            phase=phase,
            completed_units=completed_units,
            total_units=total_units,
            work_unit=work_unit,
            counters=counter_map,
            occurred_at=occurred,
            persisted_at=_parse_time(persisted_wire),
        )

    def mark_progress_stalled(
        self,
        attempt_id: str,
        *,
        reason: str = "PROGRESS_STALLED",
    ) -> bool:
        """Persist one idempotent stall signal for a non-terminal Attempt."""

        _bounded_text(attempt_id, "attempt_id", 128)
        _bounded_text(reason, "progress stall reason", 128)
        now = _wire_time(self.clock())
        connection = connect_catalog(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            owner = connection.execute(
                """
                SELECT a.state,a.interruption_reason,a.run_id,
                       r.task_id,t.project_id
                FROM task_attempt AS a
                JOIN run AS r ON r.run_id=a.run_id
                JOIN task AS t ON t.task_id=r.task_id
                WHERE a.attempt_id=?
                """,
                (attempt_id,),
            ).fetchone()
            if owner is None:
                raise KeyError(attempt_id)
            if str(owner[0]) in {"SUCCEEDED", "FAILED", "CANCELLED", "LOST"}:
                connection.commit()
                return False
            existing = connection.execute(
                "SELECT 1 FROM task_event WHERE attempt_id=? AND event_type='PROGRESS_STALLED' LIMIT 1",
                (attempt_id,),
            ).fetchone()
            if existing is not None:
                connection.commit()
                return False
            if owner[1] is not None and str(owner[1]) != reason:
                raise ProgressConflict("Attempt interruption reason already differs")
            cursor = connection.execute(
                """
                UPDATE task_attempt
                SET interruption_reason=COALESCE(interruption_reason,?)
                WHERE attempt_id=? AND state NOT IN ('SUCCEEDED','FAILED','CANCELLED','LOST')
                """,
                (reason, attempt_id),
            )
            if cursor.rowcount != 1:
                raise ProgressConflict("Attempt became terminal while marking stall")
            project_sequence = int(
                connection.execute(
                    "SELECT COALESCE(MAX(project_sequence),0)+1 FROM task_event WHERE project_id=?",
                    (str(owner[4]),),
                ).fetchone()[0]
            )
            payload = json.dumps(
                {"reason_code": reason},
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            connection.execute(
                """
                INSERT INTO task_event(
                  task_event_id,project_id,project_sequence,task_id,run_id,attempt_id,
                  event_type,event_version,payload_json,occurred_at,persisted_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    self._event_id(),
                    str(owner[4]),
                    project_sequence,
                    str(owner[3]),
                    str(owner[2]),
                    attempt_id,
                    "PROGRESS_STALLED",
                    1,
                    payload,
                    now,
                    now,
                ),
            )
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def latest_progress(self, attempt_id: str) -> ProgressRecord | None:
        connection = connect_catalog(self.database_path, read_only=True)
        try:
            row = connection.execute(
                """
                SELECT attempt_id,sequence,phase,completed_units,total_units,work_unit,
                       counters_json,occurred_at,persisted_at
                FROM attempt_progress WHERE attempt_id=? ORDER BY sequence DESC LIMIT 1
                """,
                (attempt_id,),
            ).fetchone()
        finally:
            connection.close()
        return None if row is None else self._progress_from_row(row)

    def progress_timeline(self, attempt_id: str) -> tuple[ProgressRecord, ...]:
        connection = connect_catalog(self.database_path, read_only=True)
        try:
            rows = connection.execute(
                """
                SELECT attempt_id,sequence,phase,completed_units,total_units,work_unit,
                       counters_json,occurred_at,persisted_at
                FROM attempt_progress WHERE attempt_id=? ORDER BY sequence
                """,
                (attempt_id,),
            ).fetchall()
        finally:
            connection.close()
        return tuple(self._progress_from_row(row) for row in rows)

    def bind_runtime_resolution(
        self,
        *,
        run_id: str,
        attempt_id: str,
        operation_schema_version: str,
        resource_policy_version: str,
        resolved_resource_json: str,
        resolved_resource_hash: str,
        compatibility_hash: str,
        runtime_generation_id: str | None,
    ) -> None:
        """Persist the exact resolution used by Run, Attempt and Lease.

        Admission happens before the child is allowed to ACK.  Binding these
        values in one Catalog transaction makes a later restart compare the
        durable Run context with the exact lease that admitted it.
        """

        for name, value in (
            ("operation_schema_version", operation_schema_version),
            ("resource_policy_version", resource_policy_version),
        ):
            _bounded_text(value, name, 128)
        if not isinstance(resolved_resource_json, str):
            raise ValueError("resolved resource JSON must be a string")
        if not _is_sha256(resolved_resource_hash) or not _is_sha256(compatibility_hash):
            raise ValueError("runtime resolution hashes must be lowercase SHA-256")
        try:
            decoded = json.loads(resolved_resource_json)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("resolved resource JSON is invalid") from error
        if not isinstance(decoded, Mapping):
            raise ValueError("resolved resource JSON must be an object")
        try:
            _validate_strict_json(decoded, name="resolved resource JSON")
        except ValueError as error:
            raise ValueError("resolved resource JSON is not strict JSON") from error
        canonical_json = json.dumps(
            decoded,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if resolved_resource_json != canonical_json:
            raise ValueError("resolved resource JSON must use canonical JSON encoding")
        if len(resolved_resource_json.encode("utf-8")) > 65536:
            raise ValueError("resolved resource JSON exceeds the Catalog bound")
        if hashlib.sha256(resolved_resource_json.encode("utf-8")).hexdigest() != resolved_resource_hash:
            raise ValueError("resolved resource JSON hash does not match resolved_resource_hash")
        connection = connect_catalog(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT r.operation_schema_version,r.resource_policy_version,
                       r.resolved_resource_json,r.resolved_resource_hash,
                       r.compatibility_hash,r.input_hash,r.code_version,
                       r.environment_profile_id,t.operation_id,t.project_id,
                       a.runtime_generation_id
                FROM run AS r
                JOIN task AS t ON t.task_id=r.task_id
                JOIN task_attempt AS a ON a.run_id=r.run_id
                WHERE r.run_id=? AND a.attempt_id=?
                """,
                (run_id, attempt_id),
            ).fetchone()
            if existing is None:
                raise KeyError(f"run/attempt binding not found: {run_id}/{attempt_id}")
            existing_values = tuple(
                None if value is None else str(value) for value in existing[:5]
            )
            if existing_values != _DEFAULT_RESOLUTION and existing_values != (
                operation_schema_version,
                resource_policy_version,
                resolved_resource_json,
                resolved_resource_hash,
                compatibility_hash,
            ):
                raise RuntimeResolutionConflict(
                    f"Run execution resolution is already bound: {run_id}"
                )
            expected_compatibility = compatibility_hash_for_context(
                input_hash=str(existing[5]),
                code_version=str(existing[6]),
                environment_profile=str(existing[7]),
                operation_id=str(existing[8]),
                operation_schema_version=operation_schema_version,
                resource_policy_version=resource_policy_version,
                resolved_resource_hash=resolved_resource_hash,
            )
            if compatibility_hash != expected_compatibility:
                raise RuntimeResolutionConflict(
                    "runtime resolution compatibility hash does not match immutable Run context"
                )
            existing_generation = existing[10]
            if existing_generation is not None and str(existing_generation) != runtime_generation_id:
                raise RuntimeResolutionConflict(
                    f"Attempt runtime generation is already bound: {attempt_id}"
                )
            run_updated = connection.execute(
                """
                UPDATE run
                SET operation_schema_version=?,resource_policy_version=?,
                    resolved_resource_json=?,resolved_resource_hash=?,compatibility_hash=?
                WHERE run_id=?
                """,
                (
                    operation_schema_version,
                    resource_policy_version,
                    resolved_resource_json,
                    resolved_resource_hash,
                    compatibility_hash,
                    run_id,
                ),
            )
            if run_updated.rowcount != 1:
                raise KeyError(run_id)
            if runtime_generation_id is not None:
                attempt_updated = connection.execute(
                    """
                    UPDATE task_attempt
                    SET runtime_generation_id=?
                    WHERE attempt_id=? AND run_id=?
                    """,
                    (runtime_generation_id, attempt_id, run_id),
                )
                if attempt_updated.rowcount != 1:
                    raise KeyError(attempt_id)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_generation(
        self,
        runtime_generation_id: str,
        *,
        process_identity_hash: str,
        started_at: datetime | None = None,
    ) -> None:
        if (
            not isinstance(runtime_generation_id, str)
            or not 4 <= len(runtime_generation_id) <= 128
            or len(process_identity_hash) != 64
            or process_identity_hash.lower() != process_identity_hash
            or any(char not in "0123456789abcdef" for char in process_identity_hash)
        ):
            raise ValueError("process_identity_hash must be a lowercase SHA-256")
        connection = connect_catalog(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO runtime_generation(runtime_generation_id,process_identity_hash,started_at) VALUES(?,?,?)",
                (runtime_generation_id, process_identity_hash, _wire_time(started_at or self.clock())),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def close_generation(
        self, runtime_generation_id: str, *, clean_shutdown_at: datetime | None = None
    ) -> None:
        connection = connect_catalog(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE runtime_generation SET clean_shutdown_at=? WHERE runtime_generation_id=? AND clean_shutdown_at IS NULL",
                (_wire_time(clean_shutdown_at or self.clock()), runtime_generation_id),
            )
            if cursor.rowcount != 1:
                existing = connection.execute(
                    "SELECT runtime_generation_id FROM runtime_generation WHERE runtime_generation_id=?",
                    (runtime_generation_id,),
                ).fetchone()
                if existing is not None:
                    connection.commit()
                    return
                raise ConcurrentStateChange(f"runtime generation is unknown: {runtime_generation_id}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _receipt_from_row(row: Any) -> OperationReceipt:
        return OperationReceipt(
            operation_receipt_id=str(row[0]),
            correlation_id=str(row[1]),
            operation_id=str(row[2]),
            project_id=str(row[3]),
            task_id=None if row[4] is None else str(row[4]),
            run_id=None if row[5] is None else str(row[5]),
            attempt_id=None if row[6] is None else str(row[6]),
            deadline_at=_parse_time(str(row[7])),
            runtime_generation_id=None if row[8] is None else str(row[8]),
            state=str(row[9]),
            commit_boundary_at=None if row[10] is None else _parse_time(str(row[10])),
            outcome_json=None if row[11] is None else str(row[11]),
            outcome_artifact_id=None if row[12] is None else str(row[12]),
            error_code=None if row[13] is None else str(row[13]),
            created_at=_parse_time(str(row[14])),
            updated_at=_parse_time(str(row[15])),
            terminal_at=None if row[16] is None else _parse_time(str(row[16])),
            state_version=int(row[17]),
        )

    @staticmethod
    def _receipt_select() -> str:
        return """
          SELECT operation_receipt_id,correlation_id,operation_id,project_id,
                 task_id,run_id,attempt_id,deadline_at,runtime_generation_id,state,
                 commit_boundary_at,outcome_json,outcome_artifact_id,error_code,
                 created_at,updated_at,terminal_at,state_version
          FROM control_operation_receipt
        """

    def create_receipt(
        self,
        *,
        operation_receipt_id: str,
        correlation_id: str,
        operation_id: str,
        project_id: str,
        deadline_at: datetime,
        runtime_generation_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        attempt_id: str | None = None,
    ) -> OperationReceipt:
        connection = connect_catalog(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            receipt = self.create_receipt_in_transaction(
                connection,
                operation_receipt_id=operation_receipt_id,
                correlation_id=correlation_id,
                operation_id=operation_id,
                project_id=project_id,
                deadline_at=deadline_at,
                runtime_generation_id=runtime_generation_id,
                task_id=task_id,
                run_id=run_id,
                attempt_id=attempt_id,
            )
            connection.commit()
            return receipt
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _validate_receipt_binding(
        connection: sqlite3.Connection,
        *,
        operation_id: str,
        project_id: str,
        task_id: str | None,
        run_id: str | None,
        attempt_id: str | None,
        runtime_generation_id: str | None,
    ) -> None:
        """Verify every supplied receipt identity against its Catalog owner.

        Foreign keys only prove that each individual identifier exists.  They
        do not prevent a caller from combining a project from Task A with the
        Run or Attempt belonging to Task B.  Receipt finality would then be a
        misleading authority record, so the whole identity tuple is checked
        before the insert or idempotent re-read.
        """

        if task_id is not None:
            task_row = connection.execute(
                "SELECT project_id,operation_id FROM task WHERE task_id=?",
                (task_id,),
            ).fetchone()
            if task_row is None:
                raise RuntimeResolutionConflict("receipt task identity does not exist")
            if str(task_row[0]) != project_id or str(task_row[1]) != operation_id:
                raise RuntimeResolutionConflict("receipt task binding does not match operation/project")

        if run_id is not None:
            run_row = connection.execute(
                """
                SELECT r.task_id,t.project_id,t.operation_id
                FROM run AS r JOIN task AS t ON t.task_id=r.task_id
                WHERE r.run_id=?
                """,
                (run_id,),
            ).fetchone()
            if run_row is None:
                raise RuntimeResolutionConflict("receipt run identity does not exist")
            if (
                task_id is not None and str(run_row[0]) != task_id
            ) or str(run_row[1]) != project_id or str(run_row[2]) != operation_id:
                raise RuntimeResolutionConflict("receipt run binding does not match operation/project/task")
        elif attempt_id is not None:
            raise RuntimeResolutionConflict("receipt Attempt binding requires its Run")

        if attempt_id is not None:
            attempt_row = connection.execute(
                """
                SELECT a.run_id,r.task_id,t.project_id,t.operation_id,
                       a.runtime_generation_id
                FROM task_attempt AS a
                JOIN run AS r ON r.run_id=a.run_id
                JOIN task AS t ON t.task_id=r.task_id
                WHERE a.attempt_id=?
                """,
                (attempt_id,),
            ).fetchone()
            if attempt_row is None:
                raise RuntimeResolutionConflict("receipt Attempt identity does not exist")
            if (
                run_id != str(attempt_row[0])
                or task_id != str(attempt_row[1])
                or project_id != str(attempt_row[2])
                or operation_id != str(attempt_row[3])
            ):
                raise RuntimeResolutionConflict("receipt Attempt binding does not match operation/project/task/run")
            attempt_generation = None if attempt_row[4] is None else str(attempt_row[4])
            if runtime_generation_id != attempt_generation:
                raise RuntimeResolutionConflict("receipt runtime generation does not match Attempt")

        if runtime_generation_id is not None:
            generation = connection.execute(
                "SELECT 1 FROM runtime_generation WHERE runtime_generation_id=?",
                (runtime_generation_id,),
            ).fetchone()
            if generation is None:
                raise RuntimeResolutionConflict("receipt runtime generation identity does not exist")

    def create_receipt_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        operation_receipt_id: str,
        correlation_id: str,
        operation_id: str,
        project_id: str,
        deadline_at: datetime,
        runtime_generation_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        attempt_id: str | None = None,
    ) -> OperationReceipt:
        """Insert or re-read a receipt while the caller owns a Catalog UoW."""

        _bounded_text(operation_receipt_id, "operation_receipt_id", 128)
        _bounded_text(correlation_id, "correlation_id", 256)
        _bounded_text(operation_id, "operation_id", 256)
        _bounded_text(project_id, "project_id", 128)
        for name, value, maximum in (
            ("task_id", task_id, 128),
            ("run_id", run_id, 128),
            ("attempt_id", attempt_id, 128),
            ("runtime_generation_id", runtime_generation_id, 128),
        ):
            if value is not None:
                _bounded_text(value, name, maximum)
        self._validate_receipt_binding(
            connection,
            operation_id=operation_id,
            project_id=project_id,
            task_id=task_id,
            run_id=run_id,
            attempt_id=attempt_id,
            runtime_generation_id=runtime_generation_id,
        )
        now = _wire_time(self.clock())
        deadline_wire = _wire_time(deadline_at)
        existing = connection.execute(
            self._receipt_select()
            + " WHERE operation_receipt_id=? OR correlation_id=?",
            (operation_receipt_id, correlation_id),
        ).fetchone()
        if existing is not None:
            existing_receipt = self._receipt_from_row(existing)
            immutable = (
                existing_receipt.operation_receipt_id == operation_receipt_id
                and existing_receipt.correlation_id == correlation_id
                and existing_receipt.operation_id == operation_id
                and existing_receipt.project_id == project_id
                and existing_receipt.task_id == task_id
                and existing_receipt.run_id == run_id
                and existing_receipt.attempt_id == attempt_id
                and str(existing[7]) == deadline_wire
                and existing_receipt.runtime_generation_id == runtime_generation_id
            )
            if not immutable:
                raise RuntimeResolutionConflict(
                    "operation receipt identity is already bound to different context"
                )
            return existing_receipt
        connection.execute(
            """
            INSERT INTO control_operation_receipt(
              operation_receipt_id,correlation_id,operation_id,project_id,
              task_id,run_id,attempt_id,deadline_at,runtime_generation_id,state,
              created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,'ACCEPTED',?,?)
            """,
            (
                operation_receipt_id,
                correlation_id,
                operation_id,
                project_id,
                task_id,
                run_id,
                attempt_id,
                deadline_wire,
                runtime_generation_id,
                now,
                now,
            ),
        )
        row = connection.execute(
            self._receipt_select() + " WHERE operation_receipt_id=?",
            (operation_receipt_id,),
        ).fetchone()
        if row is None:
            raise KeyError(operation_receipt_id)
        return self._receipt_from_row(row)

    def receipt(self, operation_receipt_id: str) -> OperationReceipt:
        connection = connect_catalog(self.database_path, read_only=True)
        try:
            row = connection.execute(
                self._receipt_select() + " WHERE operation_receipt_id=?",
                (operation_receipt_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(operation_receipt_id)
        return self._receipt_from_row(row)

    def receipt_by_correlation(self, correlation_id: str) -> OperationReceipt:
        connection = connect_catalog(self.database_path, read_only=True)
        try:
            row = connection.execute(
                self._receipt_select() + " WHERE correlation_id=?",
                (correlation_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(correlation_id)
        return self._receipt_from_row(row)

    def receipt_for_attempt(self, attempt_id: str) -> OperationReceipt:
        """Return the newest control receipt linked to an Attempt."""

        _bounded_text(attempt_id, "attempt_id", 128)
        connection = connect_catalog(self.database_path, read_only=True)
        try:
            row = connection.execute(
                self._receipt_select()
                + " WHERE attempt_id=? ORDER BY created_at DESC, operation_receipt_id DESC LIMIT 1",
                (attempt_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(attempt_id)
        return self._receipt_from_row(row)

    def receipt_for_task(self, task_id: str) -> OperationReceipt:
        """Return the newest control receipt linked to a Task."""

        _bounded_text(task_id, "task_id", 128)
        connection = connect_catalog(self.database_path, read_only=True)
        try:
            row = connection.execute(
                self._receipt_select()
                + " WHERE task_id=? ORDER BY created_at DESC, operation_receipt_id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(task_id)
        return self._receipt_from_row(row)

    @staticmethod
    def _receipt_row_on_connection(
        connection: sqlite3.Connection, operation_receipt_id: str
    ) -> Any:
        return connection.execute(
            ProgressPersistence._receipt_select() + " WHERE operation_receipt_id=?",
            (operation_receipt_id,),
        ).fetchone()

    @staticmethod
    def _artifact_reachable_from_project(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        artifact_id: str,
    ) -> bool:
        """Keep an artifact receipt inside its Product project's graph.

        The Artifact foreign key proves existence only.  Product reads apply
        the stronger Project -> owner -> Artifact reachability rule, so a
        durable receipt must enforce that same rule before it records a
        committed artifact outcome.
        """

        row = connection.execute(
            """
            SELECT 1
            FROM artifact_reference AS ar
            WHERE ar.artifact_id=? AND ar.state='ACTIVE' AND (
              (ar.owner_type='Project' AND ar.owner_id=? )
              OR (ar.owner_type='Task' AND ar.owner_id IN (
                SELECT task_id FROM task WHERE project_id=?
              ))
              OR (ar.owner_type='Run' AND ar.owner_id IN (
                SELECT r.run_id FROM run AS r
                JOIN task AS t ON t.task_id=r.task_id
                WHERE t.project_id=?
              ))
              OR (ar.owner_type='TaskAttempt' AND ar.owner_id IN (
                SELECT a.attempt_id FROM task_attempt AS a
                JOIN run AS r ON r.run_id=a.run_id
                JOIN task AS t ON t.task_id=r.task_id
                WHERE t.project_id=?
              ))
              OR (ar.owner_type='Result' AND ar.owner_id IN (
                SELECT result_id FROM result WHERE project_id=?
              ))
            )
            LIMIT 1
            """,
            (artifact_id, project_id, project_id, project_id, project_id, project_id),
        ).fetchone()
        return row is not None

    @classmethod
    def _transition_receipt_on_connection(
        cls,
        connection: sqlite3.Connection,
        operation_receipt_id: str,
        *,
        expected_state: str,
        new_state: str,
        outcome: Mapping[str, object] | None = None,
        outcome_artifact_id: str | None = None,
        error_code: str | None = None,
        commit_boundary_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> OperationReceipt:
        if expected_state not in RECEIPT_STATES or new_state not in RECEIPT_STATES:
            raise ValueError("unknown operation receipt state")
        if expected_state != new_state and (expected_state, new_state) not in _RECEIPT_TRANSITIONS:
            raise ReceiptStateConflict(
                f"receipt transition {expected_state}->{new_state} is not admitted"
            )
        row = cls._receipt_row_on_connection(connection, operation_receipt_id)
        if row is None:
            raise KeyError(operation_receipt_id)
        current = cls._receipt_from_row(row)
        if expected_state == new_state:
            if current.state != expected_state:
                raise ReceiptStateConflict(
                    f"operation receipt state changed: {operation_receipt_id}"
                )
            return current
        if outcome is not None and outcome_artifact_id is not None:
            raise ValueError("receipt may use JSON outcome or artifact outcome, not both")
        if new_state in {"COMMITTED", "SUCCEEDED"} and commit_boundary_at is None:
            if current.commit_boundary_at is None:
                raise ValueError("committed receipt requires commit_boundary_at")
        if new_state == "FAILED" and not error_code:
            raise ValueError("failed receipt requires error_code")
        if new_state == "PRE_COMMIT_ABORTED" and not error_code:
            raise ValueError("pre-commit aborted receipt requires error_code")
        if error_code is not None:
            _bounded_text(error_code, "error_code", 128)
        outcome_json = None
        if outcome is not None:
            if not isinstance(outcome, Mapping):
                raise ValueError("receipt outcome must be a JSON object")
            try:
                _validate_strict_json(outcome, name="receipt outcome")
                outcome_json = json.dumps(
                    dict(outcome), sort_keys=True, separators=(",", ":"), allow_nan=False
                )
            except ValueError as error:
                raise ValueError("receipt outcome is not strict JSON") from error
            if len(outcome_json.encode("utf-8")) > 65536:
                raise ValueError("receipt outcome exceeds the Catalog bound")
        if outcome_artifact_id is not None:
            if (
                not isinstance(outcome_artifact_id, str)
                or not outcome_artifact_id.startswith("art_sha256_")
                or not _is_sha256(outcome_artifact_id.removeprefix("art_sha256_"))
            ):
                raise ValueError(
                    "outcome_artifact_id must be a canonical art_sha256_ identity"
                )
            artifact = connection.execute(
                "SELECT sha256,state FROM artifact WHERE artifact_id=?",
                (outcome_artifact_id,),
            ).fetchone()
            if artifact is None:
                raise ValueError("outcome_artifact_id does not resolve to an Artifact")
            if (
                str(artifact[0]) != outcome_artifact_id.removeprefix("art_sha256_")
                or str(artifact[1]) != "PUBLISHED"
            ):
                raise ValueError(
                    "outcome_artifact_id must resolve to the exact PUBLISHED Artifact"
                )
        committed_artifact_id = outcome_artifact_id or current.outcome_artifact_id
        if (
            new_state in {"COMMITTED", "SUCCEEDED"}
            and committed_artifact_id is not None
            and not cls._artifact_reachable_from_project(
                connection,
                project_id=current.project_id,
                artifact_id=committed_artifact_id,
            )
        ):
            raise ValueError(
                "outcome Artifact is not project-reachable from the receipt project"
            )
        now = _wire_time(updated_at or datetime.now(timezone.utc))
        # The caller owns the transaction clock for ordinary transitions.  The
        # sidecar's public wrapper supplies its configured clock separately;
        # this helper is only used by an already-open Catalog UoW.
        commit_wire = None if commit_boundary_at is None else _wire_time(commit_boundary_at)
        terminal_wire = now if new_state in _TERMINAL_RECEIPT_STATES else None
        cursor = connection.execute(
            """
            UPDATE control_operation_receipt
            SET state=?,commit_boundary_at=COALESCE(?,commit_boundary_at),
                outcome_json=COALESCE(?,outcome_json),
                outcome_artifact_id=COALESCE(?,outcome_artifact_id),
                error_code=COALESCE(?,error_code),
                updated_at=?,terminal_at=COALESCE(?,terminal_at),
                state_version=state_version+1
            WHERE operation_receipt_id=? AND state=?
            """,
            (
                new_state,
                commit_wire,
                outcome_json,
                outcome_artifact_id,
                error_code,
                now,
                terminal_wire,
                operation_receipt_id,
                expected_state,
            ),
        )
        if cursor.rowcount != 1:
            raise ReceiptStateConflict(
                f"operation receipt state changed: {operation_receipt_id}"
            )
        updated = cls._receipt_row_on_connection(connection, operation_receipt_id)
        if updated is None:
            raise KeyError(operation_receipt_id)
        return cls._receipt_from_row(updated)

    def mark_receipt_running_in_transaction(
        self, connection: sqlite3.Connection, attempt_id: str
    ) -> OperationReceipt | None:
        """Advance an Attempt's receipt while the caller owns its UoW."""

        _bounded_text(attempt_id, "attempt_id", 128)
        try:
            receipt = self.receipt_for_attempt_on_connection(connection, attempt_id)
        except KeyError:
            return None
        if receipt.state == "RUNNING":
            return receipt
        if receipt.state != "ACCEPTED":
            raise ReceiptStateConflict(
                f"receipt cannot enter RUNNING from {receipt.state}"
            )
        return self._transition_receipt_on_connection(
            connection,
            receipt.operation_receipt_id,
            expected_state="ACCEPTED",
            new_state="RUNNING",
            updated_at=self.clock(),
        )

    def mark_receipt_running(self, attempt_id: str) -> OperationReceipt | None:
        """Advance an Attempt's receipt to RUNNING when one was created."""

        connection = connect_catalog(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            result = self.mark_receipt_running_in_transaction(connection, attempt_id)
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def abort_receipt_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        attempt_id: str,
        error_code: str,
    ) -> OperationReceipt | None:
        """Close a pre-commit operation without fabricating a commit result."""

        _bounded_text(attempt_id, "attempt_id", 128)
        _bounded_text(error_code, "error_code", 128)
        try:
            receipt = self.receipt_for_attempt_on_connection(connection, attempt_id)
        except KeyError:
            return None
        if receipt.state in _TERMINAL_RECEIPT_STATES or receipt.state == "COMMITTED":
            return receipt
        if receipt.state not in {"ACCEPTED", "RUNNING"}:
            raise ReceiptStateConflict(
                f"receipt cannot be aborted from {receipt.state}"
            )
        return self._transition_receipt_on_connection(
            connection,
            receipt.operation_receipt_id,
            expected_state=receipt.state,
            new_state="PRE_COMMIT_ABORTED",
            error_code=error_code,
            updated_at=self.clock(),
        )

    def abort_receipt(
        self, attempt_id: str, *, error_code: str
    ) -> OperationReceipt | None:
        connection = connect_catalog(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            receipt = self.abort_receipt_in_transaction(
                connection, attempt_id=attempt_id, error_code=error_code
            )
            connection.commit()
            return receipt
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def finalize_receipt_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        attempt_id: str,
        success: bool,
        outcome: Mapping[str, object] | None = None,
        outcome_artifact_id: str | None = None,
        error_code: str | None = None,
        commit_boundary_at: datetime | None = None,
        complete: bool = True,
    ) -> OperationReceipt | None:
        """Finalize a linked receipt without opening a second transaction.

        A missing receipt is allowed for direct in-process compatibility paths;
        a caller that supplied a receipt ID must use the strict
        ``ExecutionControlContext`` gate before committing.
        """

        try:
            receipt = self.receipt_for_attempt_on_connection(connection, attempt_id)
        except KeyError:
            return None
        if success:
            if receipt.state == "SUCCEEDED":
                return receipt
            if receipt.state == "COMMITTED":
                if not complete:
                    return receipt
                return self._transition_receipt_on_connection(
                    connection,
                    receipt.operation_receipt_id,
                    expected_state="COMMITTED",
                    new_state="SUCCEEDED",
                    commit_boundary_at=commit_boundary_at,
                    updated_at=self.clock(),
                )
            if receipt.state == "ACCEPTED":
                receipt = self._transition_receipt_on_connection(
                    connection,
                    receipt.operation_receipt_id,
                    expected_state="ACCEPTED",
                    new_state="RUNNING",
                    updated_at=self.clock(),
                )
            if receipt.state != "RUNNING":
                raise ReceiptStateConflict(
                    f"successful terminal state cannot follow {receipt.state}"
                )
            receipt = self._transition_receipt_on_connection(
                connection,
                receipt.operation_receipt_id,
                expected_state="RUNNING",
                new_state="COMMITTED",
                outcome=outcome,
                outcome_artifact_id=outcome_artifact_id,
                commit_boundary_at=commit_boundary_at or self.clock(),
                updated_at=self.clock(),
            )
            if not complete:
                return receipt
            return self._transition_receipt_on_connection(
                connection,
                receipt.operation_receipt_id,
                expected_state="COMMITTED",
                new_state="SUCCEEDED",
                commit_boundary_at=commit_boundary_at or self.clock(),
                updated_at=self.clock(),
            )
        if receipt.state in _TERMINAL_RECEIPT_STATES:
            return receipt
        if receipt.state == "COMMITTED":
            # A durable commit wins over a late worker failure.
            return receipt
        if receipt.state == "ACCEPTED":
            receipt = self._transition_receipt_on_connection(
                connection,
                receipt.operation_receipt_id,
                expected_state="ACCEPTED",
                new_state="RUNNING",
                updated_at=self.clock(),
            )
        if receipt.state != "RUNNING":
            raise ReceiptStateConflict(
                f"failed terminal state cannot follow {receipt.state}"
            )
        return self._transition_receipt_on_connection(
            connection,
            receipt.operation_receipt_id,
            expected_state="RUNNING",
            new_state="FAILED",
            error_code=error_code or "EXECUTION_FAILED",
            updated_at=self.clock(),
        )

    def complete_receipt(self, operation_receipt_id: str) -> OperationReceipt:
        """Advance a durable COMMITTED receipt to its terminal SUCCEEDED state.

        The business commit and the COMMITTED marker are written in the
        caller's transaction.  This second, idempotent transition closes the
        receipt after that commit, leaving COMMITTED visible if the process
        crashes in between instead of losing the finality boundary.
        """

        current = self.receipt(operation_receipt_id)
        if current.state == "SUCCEEDED":
            return current
        if current.state != "COMMITTED":
            raise ReceiptStateConflict(
                f"receipt cannot complete from {current.state}: {operation_receipt_id}"
            )
        try:
            return self.transition_receipt(
                operation_receipt_id,
                expected_state="COMMITTED",
                new_state="SUCCEEDED",
            )
        except ReceiptStateConflict:
            # Another observer may have completed it between the read and the
            # CAS.  Only the same terminal success is an idempotent outcome;
            # every other state remains an explicit conflict.
            latest = self.receipt(operation_receipt_id)
            if latest.state == "SUCCEEDED":
                return latest
            raise

    def complete_receipt_in_transaction(
        self,
        connection: sqlite3.Connection,
        operation_receipt_id: str,
        *,
        updated_at: datetime | None = None,
    ) -> OperationReceipt:
        """Complete a COMMITTED receipt while the caller owns its UoW.

        Startup reconciliation uses this form so a receipt left at the
        durable COMMITTED boundary can be closed without opening a nested
        SQLite transaction (and without treating a successful Task as an
        incomplete operation forever).
        """

        current = self._receipt_row_on_connection(connection, operation_receipt_id)
        if current is None:
            raise KeyError(operation_receipt_id)
        receipt = self._receipt_from_row(current)
        if receipt.state == "SUCCEEDED":
            return receipt
        if receipt.state != "COMMITTED":
            raise ReceiptStateConflict(
                f"receipt cannot complete from {receipt.state}: {operation_receipt_id}"
            )
        return self._transition_receipt_on_connection(
            connection,
            operation_receipt_id,
            expected_state="COMMITTED",
            new_state="SUCCEEDED",
            updated_at=updated_at or self.clock(),
        )

    @classmethod
    def receipt_for_attempt_on_connection(
        cls, connection: sqlite3.Connection, attempt_id: str
    ) -> OperationReceipt:
        row = connection.execute(
            cls._receipt_select()
            + " WHERE attempt_id=? ORDER BY created_at DESC, operation_receipt_id DESC LIMIT 1",
            (attempt_id,),
        ).fetchone()
        if row is None:
            raise KeyError(attempt_id)
        return cls._receipt_from_row(row)

    def transition_receipt(
        self,
        operation_receipt_id: str,
        *,
        expected_state: str,
        new_state: str,
        outcome: Mapping[str, object] | None = None,
        outcome_artifact_id: str | None = None,
        error_code: str | None = None,
        commit_boundary_at: datetime | None = None,
    ) -> OperationReceipt:
        if expected_state not in RECEIPT_STATES or new_state not in RECEIPT_STATES:
            raise ValueError("unknown operation receipt state")
        if expected_state != new_state and (expected_state, new_state) not in _RECEIPT_TRANSITIONS:
            raise ReceiptStateConflict(f"receipt transition {expected_state}->{new_state} is not admitted")
        connection = connect_catalog(self.database_path)
        row = None
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._transition_receipt_on_connection(
                connection,
                operation_receipt_id,
                expected_state=expected_state,
                new_state=new_state,
                outcome=outcome,
                outcome_artifact_id=outcome_artifact_id,
                error_code=error_code,
                commit_boundary_at=commit_boundary_at,
                updated_at=self.clock(),
            )
            row = self._receipt_row_on_connection(connection, operation_receipt_id)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        if row is None:
            raise KeyError(operation_receipt_id)
        return self._receipt_from_row(row)


__all__ = [
    "compatibility_hash_for_context",
    "DISPATCH_STATES",
    "DispatchControl",
    "DispatchStateConflict",
    "OperationReceipt",
    "ProgressConflict",
    "ProgressPersistence",
    "ProgressRecord",
    "ReceiptStateConflict",
    "RuntimeResolutionConflict",
]
