from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol

from v3_backend.domain.tasks.entities import Run, Task, TaskAttempt
from v3_backend.domain.tasks.events import PendingTaskEvent, TaskEvent


class ConcurrentStateChange(RuntimeError):
    pass


class TaskUnitOfWork(Protocol):
    persisted_events: tuple[TaskEvent, ...]

    def __enter__(self) -> "TaskUnitOfWork": ...
    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...
    def add_task(self, task: Task) -> None: ...
    def add_run(self, run: Run) -> None: ...
    def add_attempt(self, attempt: TaskAttempt) -> None: ...
    def require_task(self, task_id: str) -> Task: ...
    def require_run(self, run_id: str) -> Run: ...
    def require_attempt(self, attempt_id: str) -> TaskAttempt: ...
    def attempts_for_run(self, run_id: str) -> tuple[TaskAttempt, ...]: ...
    def save_task(self, task: Task, expected_version: int) -> None: ...
    def save_run(self, run: Run, expected_version: int) -> None: ...
    def save_attempt(self, attempt: TaskAttempt, expected_version: int) -> None: ...
    def append_event(self, event: PendingTaskEvent) -> None: ...
    def commit(self) -> None: ...


class TaskPersistencePort(Protocol):
    def begin(self) -> TaskUnitOfWork: ...
    def replay(self, project_id: str, after_sequence: int, limit: int) -> tuple[TaskEvent, ...]: ...
    def read_task(self, task_id: str) -> Task: ...
    def latest_attempt(self, task_id: str) -> TaskAttempt: ...


class InMemoryTaskPersistence:
    """Deterministic fake that models mutation -> append -> commit ordering."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self.tasks: dict[str, Task] = {}
        self.runs: dict[str, Run] = {}
        self.attempts: dict[str, TaskAttempt] = {}
        self.events: list[TaskEvent] = []
        self.trace: list[str] = []
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def begin(self) -> "InMemoryTaskUnitOfWork":
        return InMemoryTaskUnitOfWork(self)

    def replay(self, project_id: str, after_sequence: int, limit: int) -> tuple[TaskEvent, ...]:
        if after_sequence < 0 or not 1 <= limit <= 1000:
            raise ValueError("invalid replay bounds")
        return tuple(
            event
            for event in self.events
            if event.project_id == project_id and event.project_sequence > after_sequence
        )[:limit]

    def read_task(self, task_id: str) -> Task:
        return copy.deepcopy(self.tasks[task_id])

    def latest_attempt(self, task_id: str) -> TaskAttempt:
        return copy.deepcopy(
            max(
                (item for item in self.attempts.values() if item.task_id == task_id),
                key=lambda item: item.ordinal,
            )
        )


class InMemoryTaskUnitOfWork:
    def __init__(self, owner: InMemoryTaskPersistence) -> None:
        self._owner = owner
        self._tasks = copy.deepcopy(owner.tasks)
        self._runs = copy.deepcopy(owner.runs)
        self._attempts = copy.deepcopy(owner.attempts)
        self._pending: list[PendingTaskEvent] = []
        self.persisted_events: tuple[TaskEvent, ...] = ()
        self._committed = False

    def __enter__(self) -> "InMemoryTaskUnitOfWork":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def _add(self, collection: dict[str, object], key: str, value: object) -> None:
        if key in collection:
            raise ConcurrentStateChange(f"identity already exists: {key}")
        collection[key] = copy.deepcopy(value)
        self._owner.trace.append("aggregate_mutated")

    def add_task(self, task: Task) -> None:
        self._add(self._tasks, task.task_id, task)

    def add_run(self, run: Run) -> None:
        self._add(self._runs, run.run_id, run)

    def add_attempt(self, attempt: TaskAttempt) -> None:
        self._add(self._attempts, attempt.attempt_id, attempt)

    @staticmethod
    def _require(collection: dict[str, object], key: str) -> object:
        try:
            return copy.deepcopy(collection[key])
        except KeyError as exc:
            raise KeyError(f"not found: {key}") from exc

    def require_task(self, task_id: str) -> Task:
        return self._require(self._tasks, task_id)  # type: ignore[return-value]

    def require_run(self, run_id: str) -> Run:
        return self._require(self._runs, run_id)  # type: ignore[return-value]

    def require_attempt(self, attempt_id: str) -> TaskAttempt:
        return self._require(self._attempts, attempt_id)  # type: ignore[return-value]

    def attempts_for_run(self, run_id: str) -> tuple[TaskAttempt, ...]:
        return tuple(
            copy.deepcopy(attempt)
            for attempt in sorted(self._attempts.values(), key=lambda item: item.ordinal)
            if attempt.run_id == run_id
        )

    def _save(
        self,
        collection: dict[str, object],
        key: str,
        value: Task | Run | TaskAttempt,
        expected_version: int,
    ) -> None:
        current = collection.get(key)
        if current is None or getattr(current, "state_version") != expected_version:
            raise ConcurrentStateChange(f"expected version {expected_version} for {key}")
        value.state_version = expected_version + 1
        collection[key] = copy.deepcopy(value)
        self._owner.trace.append("aggregate_mutated")

    def save_task(self, task: Task, expected_version: int) -> None:
        self._save(self._tasks, task.task_id, task, expected_version)

    def save_run(self, run: Run, expected_version: int) -> None:
        self._save(self._runs, run.run_id, run, expected_version)

    def save_attempt(self, attempt: TaskAttempt, expected_version: int) -> None:
        self._save(self._attempts, attempt.attempt_id, attempt, expected_version)

    def append_event(self, event: PendingTaskEvent) -> None:
        if any(item.event_id == event.event_id for item in self._owner.events) or any(
            item.event_id == event.event_id for item in self._pending
        ):
            raise ConcurrentStateChange(f"event already exists: {event.event_id}")
        self._pending.append(event)
        self._owner.trace.append("event_appended")

    def commit(self) -> None:
        if self._committed:
            raise RuntimeError("unit of work already committed")
        next_by_project: dict[str, int] = {}
        persisted: list[TaskEvent] = []
        for pending in self._pending:
            current = next_by_project.get(
                pending.project_id,
                max(
                    (item.project_sequence for item in self._owner.events if item.project_id == pending.project_id),
                    default=0,
                ),
            )
            sequence = current + 1
            next_by_project[pending.project_id] = sequence
            persisted.append(
                TaskEvent(
                    event_id=pending.event_id,
                    event_version=pending.event_version,
                    project_id=pending.project_id,
                    project_sequence=sequence,
                    task_id=pending.task_id,
                    run_id=pending.run_id,
                    attempt_id=pending.attempt_id,
                    event_type=pending.event_type,
                    occurred_at=pending.occurred_at,
                    persisted_at=self._owner.clock(),
                    payload=pending.payload,
                )
            )
        self._owner.tasks = copy.deepcopy(self._tasks)
        self._owner.runs = copy.deepcopy(self._runs)
        self._owner.attempts = copy.deepcopy(self._attempts)
        self._owner.events.extend(persisted)
        self.persisted_events = tuple(persisted)
        self._committed = True
        self._owner.trace.append("commit")
