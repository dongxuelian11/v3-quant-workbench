from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping

from v3_backend.contracts.common.ids import validate_v3_id


MAX_EVENT_PAYLOAD_BYTES = 64 * 1024


@dataclass(frozen=True)
class PendingTaskEvent:
    event_id: str
    event_version: str
    project_id: str
    task_id: str
    event_type: str
    occurred_at: datetime
    payload: Mapping[str, Any]
    run_id: str | None = None
    attempt_id: str | None = None

    def __post_init__(self) -> None:
        validate_v3_id(self.event_id, "TaskEvent")
        validate_v3_id(self.project_id, "Project")
        validate_v3_id(self.task_id, "Task")
        if self.run_id is not None:
            validate_v3_id(self.run_id, "Run")
        if self.attempt_id is not None:
            validate_v3_id(self.attempt_id, "TaskAttempt")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamps must be timezone-aware")
        if not self.event_type or not self.event_version:
            raise ValueError("event type/version must not be empty")
        try:
            encoded = json.dumps(self.payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("event payload must be JSON serializable") from exc
        if len(encoded) > MAX_EVENT_PAYLOAD_BYTES:
            raise ValueError("event payload exceeds 64 KiB")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True)
class TaskEvent:
    event_id: str
    event_version: str
    project_id: str
    project_sequence: int
    task_id: str
    event_type: str
    occurred_at: datetime
    persisted_at: datetime
    payload: Mapping[str, Any]
    run_id: str | None = None
    attempt_id: str | None = None

    def __post_init__(self) -> None:
        if self.project_sequence < 1:
            raise ValueError("project sequence starts at one")
        if self.persisted_at.tzinfo is None:
            raise ValueError("persisted_at must be timezone-aware")
