from __future__ import annotations

from v3_backend.domain.tasks.events import TaskEvent

from .persistence import TaskPersistencePort


class EventReplay:
    def __init__(self, persistence: TaskPersistencePort) -> None:
        self._persistence = persistence

    def after(self, project_id: str, sequence: int, limit: int = 1000) -> tuple[TaskEvent, ...]:
        events = self._persistence.replay(project_id, sequence, limit)
        if any(left.project_sequence >= right.project_sequence for left, right in zip(events, events[1:])):
            raise RuntimeError("persistence returned non-monotonic event replay")
        return events
