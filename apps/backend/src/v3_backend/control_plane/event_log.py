from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeVar

from v3_backend.domain.tasks.events import TaskEvent

from .persistence import TaskPersistencePort, TaskUnitOfWork


T = TypeVar("T")


class EventPublisher(Protocol):
    def publish(self, event: TaskEvent) -> None: ...


class DurableEventLog:
    """Runs a Catalog mutation and notifies only after its commit succeeds."""

    def __init__(self, persistence: TaskPersistencePort, publisher: EventPublisher) -> None:
        self.persistence = persistence
        self.publisher = publisher

    def transact(self, mutation: Callable[[TaskUnitOfWork], T]) -> T:
        with self.persistence.begin() as unit:
            result = mutation(unit)
            unit.commit()
            persisted = unit.persisted_events
        for event in persisted:
            trace = getattr(self.persistence, "trace", None)
            if isinstance(trace, list):
                trace.append("notify")
            self.publisher.publish(event)
        return result


class CollectingPublisher:
    def __init__(self) -> None:
        self.events: list[TaskEvent] = []

    def publish(self, event: TaskEvent) -> None:
        self.events.append(event)
