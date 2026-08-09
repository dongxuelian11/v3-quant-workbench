"""Operational health projection with no business truth ownership."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class RuntimeHealth:
    backend_instance_id: str
    started_monotonic: float = 0.0
    accepting_requests: bool = True

    def __post_init__(self) -> None:
        if self.started_monotonic == 0.0:
            self.started_monotonic = time.monotonic()

    def snapshot(self) -> dict[str, Any]:
        return {
            "kind": "runtime.health",
            "backend_instance_id": self.backend_instance_id,
            "state": "READY" if self.accepting_requests else "DRAINING",
            "uptime_seconds": max(0.0, time.monotonic() - self.started_monotonic),
        }
