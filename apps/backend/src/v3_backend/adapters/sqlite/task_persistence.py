"""WS-D Task persistence implemented by the single WS-B SQLite Catalog."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from v3_backend.control_plane.persistence import ConcurrentStateChange
from v3_backend.domain.tasks.entities import (
    ATTEMPT_TERMINAL_STATES,
    AttemptState,
    Run,
    RunIdentity,
    RunState,
    Task,
    TaskAttempt,
    TaskState,
)
from v3_backend.domain.tasks.events import PendingTaskEvent, TaskEvent
from v3_backend.repositories.unit_of_work import TransactionMode

from .connection import connect_catalog
from .repositories import SQLiteRepositoryRegistry
from .unit_of_work import SQLiteUnitOfWork


_EVENT_VERSION = re.compile(r"(?P<major>[0-9]+)\.(?P<minor>[0-9]+)\.(?P<patch>[0-9]+)")
_TASK_TERMINAL = {state.value for state in (TaskState.SUCCEEDED, TaskState.FAILED, TaskState.CANCELLED, TaskState.PARTIAL)}


def _wire_time(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Task Catalog timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)


def _event_version_to_catalog(value: str) -> int:
    match = _EVENT_VERSION.fullmatch(value)
    if match is None:
        raise ValueError("Task event version must be semantic major.minor.patch")
    major, minor, patch = (int(match[name]) for name in ("major", "minor", "patch"))
    if major > 999 or minor > 999 or patch > 999:
        raise ValueError("Task event version component exceeds the Catalog encoding bound")
    return major * 1_000_000 + minor * 1_000 + patch


def _event_version_from_catalog(value: int) -> str:
    major, remainder = divmod(value, 1_000_000)
    minor, patch = divmod(remainder, 1_000)
    return f"{major}.{minor}.{patch}"


def _operation_service(operation_id: str) -> str:
    service, separator, _ = operation_id.partition(".")
    if not separator or not service:
        raise ValueError("operation_id must identify a frozen service operation")
    return service


class SQLiteTaskPersistence:
    """Durable WS-D port; every operation opens the same V3 Catalog file."""

    def __init__(
        self,
        database_path: str | Path,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.database_path = Path(database_path).resolve()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.trace: list[str] = []

    def begin(self) -> "SQLiteTaskUnitOfWork":
        return SQLiteTaskUnitOfWork(
            connect_catalog(self.database_path),
            clock=self.clock,
            trace=self.trace,
        )

    def replay(self, project_id: str, after_sequence: int, limit: int) -> tuple[TaskEvent, ...]:
        if after_sequence < 0 or not 1 <= limit <= 1000:
            raise ValueError("invalid replay bounds")
        connection = connect_catalog(self.database_path, read_only=True)
        unit = SQLiteUnitOfWork(connection, TransactionMode.READ_ONLY)
        try:
            unit.begin()
            rows = SQLiteRepositoryRegistry(unit).task.list_replay(
                project_id, after_sequence=after_sequence, limit=limit
            )
            unit.commit()
            return tuple(_task_event_from_row(row) for row in rows)
        finally:
            if unit.active:
                unit.rollback()
            connection.close()

    def read_task(self, task_id: str) -> Task:
        with self.begin() as unit:
            task = unit.require_task(task_id)
            unit.commit()
            return task

    def latest_attempt(self, task_id: str) -> TaskAttempt:
        with self.begin() as unit:
            row = unit.connection.execute(
                """
                SELECT attempt_id FROM task_attempt
                JOIN run USING(run_id)
                WHERE task_id=? ORDER BY attempt_no DESC LIMIT 1
                """,
                (task_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"no Attempt for Task: {task_id}")
            attempt = unit.require_attempt(str(row[0]))
            unit.commit()
            return attempt


class SQLiteTaskUnitOfWork:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        clock: Callable[[], datetime],
        trace: list[str],
    ) -> None:
        self.connection = connection
        self.clock = clock
        self.trace = trace
        self.catalog = SQLiteUnitOfWork(connection)
        self.registry = SQLiteRepositoryRegistry(self.catalog)
        self.persisted_events: tuple[TaskEvent, ...] = ()
        self._pending: list[PendingTaskEvent] = []
        self._committed = False

    def __enter__(self) -> "SQLiteTaskUnitOfWork":
        self.catalog.begin()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        try:
            if self.catalog.active:
                self.catalog.rollback()
        finally:
            self.connection.close()

    def add_task(self, task: Task) -> None:
        now = _wire_time(self.clock())
        self.registry.task.table("task").add_new(
            {
                "task_id": task.task_id,
                "project_id": task.project_id,
                "parent_task_id": None,
                "service_name": _operation_service(task.operation_id),
                "operation_id": task.operation_id,
                "task_type": "BATCH" if task.is_batch else "SINGLE",
                "display_name": task.operation_id,
                "truth_state": "UNAVAILABLE",
                "state": task.state.value,
                "state_version": task.state_version,
                "created_by": "TaskControlPlane",
                "created_at": now,
                "updated_at": now,
                "terminal_at": None,
            }
        )
        for child_task_id in task.child_task_ids:
            self.registry.task.table("task_dependency").add_new(
                {
                    "task_id": task.task_id,
                    "depends_on_task_id": child_task_id,
                    "required_terminal_state": "TERMINAL_ANY",
                }
            )
        self.trace.append("aggregate_mutated")

    def add_run(self, run: Run) -> None:
        run_no = int(
            self.connection.execute(
                "SELECT COALESCE(MAX(run_no),0)+1 FROM run WHERE task_id=?", (run.task_id,)
            ).fetchone()[0]
        )
        identity = run.identity
        self.registry.task.table("run").add_new(
            {
                "run_id": run.run_id,
                "task_id": run.task_id,
                "run_no": run_no,
                "project_context_revision_id": identity.project_context_revision_id,
                "canonical_input_json": {
                    "normalized_input_hash": identity.normalized_input_hash,
                    "service_contract_version": identity.service_contract_version,
                },
                "input_hash": identity.normalized_input_hash,
                "code_version": identity.code_version,
                "environment_profile_id": identity.environment_profile,
                "state": run.state.value,
                "created_at": _wire_time(self.clock()),
                "terminal_at": None,
            }
        )
        self.trace.append("aggregate_mutated")

    def add_attempt(self, attempt: TaskAttempt) -> None:
        self.registry.task.create_attempt(
            {
                "attempt_id": attempt.attempt_id,
                "run_id": attempt.run_id,
                "attempt_no": attempt.ordinal,
                "retry_of_attempt_id": None,
                "resume_checkpoint_artifact_id": attempt.resume_checkpoint_artifact_id,
                "worker_id": None,
                "lease_id": attempt.lease_id,
                "state": attempt.state.value,
                "error_code": attempt.terminal_error_category,
                "error_detail_artifact_id": None,
                "started_at": None,
                "heartbeat_at": None,
                "finished_at": None,
            }
        )
        self.trace.append("aggregate_mutated")

    def require_task(self, task_id: str) -> Task:
        row = self.registry.task.table("task").require(task_id)
        run_row = self.connection.execute(
            "SELECT run_id FROM run WHERE task_id=? ORDER BY run_no DESC LIMIT 1", (task_id,)
        ).fetchone()
        if run_row is None:
            raise KeyError(f"Task has no Run: {task_id}")
        children = tuple(
            str(item[0])
            for item in self.connection.execute(
                "SELECT depends_on_task_id FROM task_dependency WHERE task_id=? ORDER BY depends_on_task_id",
                (task_id,),
            )
        )
        attempt_count = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM task_attempt JOIN run USING(run_id) WHERE task_id=?", (task_id,)
            ).fetchone()[0]
        )
        return Task(
            task_id=str(row["task_id"]),
            project_id=str(row["project_id"]),
            operation_id=str(row["operation_id"]),
            active_run_id=str(run_row[0]),
            state=TaskState(str(row["state"])),
            state_version=int(row["state_version"]),
            execution_epoch=max(0, attempt_count - 1),
            is_batch=bool(children),
            child_task_ids=children,
        )

    def require_run(self, run_id: str) -> Run:
        row = self.registry.task.table("run").require(run_id)
        canonical = json.loads(str(row["canonical_input_json"]))
        state = RunState(str(row["state"]))
        return Run(
            run_id=str(row["run_id"]),
            task_id=str(row["task_id"]),
            identity=RunIdentity(
                project_context_revision_id=str(row["project_context_revision_id"]),
                normalized_input_hash=str(row["input_hash"]),
                code_version=str(row["code_version"]),
                environment_profile=str(row["environment_profile_id"]),
                service_contract_version=str(canonical["service_contract_version"]),
            ),
            state=state,
            state_version={RunState.SEALED: 0, RunState.ACTIVE: 1, RunState.TERMINAL: 2}[state],
        )

    def _attempt_version(self, attempt_id: str) -> int:
        return int(
            self.connection.execute(
                "SELECT COUNT(*) FROM task_event WHERE attempt_id=? AND event_type<>'ATTEMPT_CREATED'",
                (attempt_id,),
            ).fetchone()[0]
        )

    def require_attempt(self, attempt_id: str) -> TaskAttempt:
        row = self.registry.task.table("task_attempt").require(attempt_id)
        task_row = self.connection.execute("SELECT task_id FROM run WHERE run_id=?", (row["run_id"],)).fetchone()
        if task_row is None:
            raise KeyError(f"Attempt has no Run: {attempt_id}")
        return TaskAttempt(
            attempt_id=str(row["attempt_id"]),
            task_id=str(task_row[0]),
            run_id=str(row["run_id"]),
            ordinal=int(row["attempt_no"]),
            state=AttemptState(str(row["state"])),
            state_version=self._attempt_version(attempt_id),
            lease_id=None if row["lease_id"] is None else str(row["lease_id"]),
            resume_checkpoint_artifact_id=(
                None if row["resume_checkpoint_artifact_id"] is None else str(row["resume_checkpoint_artifact_id"])
            ),
            terminal_error_category=None if row["error_code"] is None else str(row["error_code"]),
        )

    def attempts_for_run(self, run_id: str) -> tuple[TaskAttempt, ...]:
        rows = self.connection.execute(
            "SELECT attempt_id FROM task_attempt WHERE run_id=? ORDER BY attempt_no", (run_id,)
        ).fetchall()
        return tuple(self.require_attempt(str(row[0])) for row in rows)

    def save_task(self, task: Task, expected_version: int) -> None:
        now = _wire_time(self.clock())
        self.registry.task.table("task").save(
            task.task_id,
            {
                "state": task.state.value,
                "updated_at": now,
                "terminal_at": now if task.state.value in _TASK_TERMINAL else None,
            },
            expected_version=expected_version,
        )
        task.state_version = expected_version + 1
        self.trace.append("aggregate_mutated")

    def save_run(self, run: Run, expected_version: int) -> None:
        current = self.require_run(run.run_id)
        if current.state_version != expected_version:
            raise ConcurrentStateChange(f"expected version {expected_version} for {run.run_id}")
        cursor = self.connection.execute(
            "UPDATE run SET state=?, terminal_at=? WHERE run_id=? AND state=?",
            (
                run.state.value,
                _wire_time(self.clock()) if run.state is RunState.TERMINAL else None,
                run.run_id,
                current.state.value,
            ),
        )
        if cursor.rowcount != 1:
            raise ConcurrentStateChange(f"Run state changed concurrently: {run.run_id}")
        run.state_version = expected_version + 1
        self.trace.append("aggregate_mutated")

    def save_attempt(self, attempt: TaskAttempt, expected_version: int) -> None:
        if self._attempt_version(attempt.attempt_id) != expected_version:
            raise ConcurrentStateChange(f"expected version {expected_version} for {attempt.attempt_id}")
        current = self.registry.task.table("task_attempt").require(attempt.attempt_id)
        cursor = self.connection.execute(
            """
            UPDATE task_attempt SET state=?, lease_id=?, resume_checkpoint_artifact_id=?,
                error_code=?, started_at=COALESCE(started_at,?), finished_at=?
            WHERE attempt_id=? AND state=?
            """,
            (
                attempt.state.value,
                attempt.lease_id,
                attempt.resume_checkpoint_artifact_id,
                attempt.terminal_error_category,
                _wire_time(self.clock()) if attempt.state is not AttemptState.QUEUED else None,
                _wire_time(self.clock()) if attempt.state in ATTEMPT_TERMINAL_STATES else None,
                attempt.attempt_id,
                current["state"],
            ),
        )
        if cursor.rowcount != 1:
            raise ConcurrentStateChange(f"Attempt state changed concurrently: {attempt.attempt_id}")
        attempt.state_version = expected_version + 1
        self.trace.append("aggregate_mutated")

    def append_event(self, event: PendingTaskEvent) -> None:
        if any(item.event_id == event.event_id for item in self._pending):
            raise ConcurrentStateChange(f"event already pending: {event.event_id}")
        exists = self.connection.execute(
            "SELECT 1 FROM task_event WHERE task_event_id=?", (event.event_id,)
        ).fetchone()
        if exists is not None:
            raise ConcurrentStateChange(f"event already exists: {event.event_id}")
        self._pending.append(event)
        self.trace.append("event_appended")

    def commit(self) -> None:
        if self._committed:
            raise RuntimeError("unit of work already committed")
        sequence_by_project: dict[str, int] = {}
        persisted_rows: list[dict[str, object]] = []
        for pending in self._pending:
            expected = sequence_by_project.get(pending.project_id)
            if expected is None:
                expected = int(
                    self.connection.execute(
                        "SELECT COALESCE(MAX(project_sequence),0) FROM task_event WHERE project_id=?",
                        (pending.project_id,),
                    ).fetchone()[0]
                )
            row = self.registry.task.append_event(
                {
                    "task_event_id": pending.event_id,
                    "project_id": pending.project_id,
                    "task_id": pending.task_id,
                    "run_id": pending.run_id,
                    "attempt_id": pending.attempt_id,
                    "event_type": pending.event_type,
                    "event_version": _event_version_to_catalog(pending.event_version),
                    "payload_json": dict(pending.payload),
                    "occurred_at": _wire_time(pending.occurred_at),
                    "persisted_at": _wire_time(self.clock()),
                },
                expected_stream_sequence=expected,
            )
            persisted_rows.append(row)
            sequence_by_project[pending.project_id] = expected + 1
        self.catalog.commit()
        self.persisted_events = tuple(_task_event_from_row(row) for row in persisted_rows)
        self._committed = True
        self.trace.append("commit")


def _task_event_from_row(row: dict[str, object]) -> TaskEvent:
    payload = row["payload_json"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return TaskEvent(
        event_id=str(row["task_event_id"]),
        event_version=_event_version_from_catalog(int(row["event_version"])),
        project_id=str(row["project_id"]),
        project_sequence=int(row["project_sequence"]),
        task_id=str(row["task_id"]),
        run_id=None if row["run_id"] is None else str(row["run_id"]),
        attempt_id=None if row["attempt_id"] is None else str(row["attempt_id"]),
        event_type=str(row["event_type"]),
        occurred_at=_parse_time(str(row["occurred_at"])),
        persisted_at=_parse_time(str(row["persisted_at"])),
        payload=payload,  # type: ignore[arg-type]
    )
