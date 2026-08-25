"""Operational health projection with no business truth ownership."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass
class RuntimeHealth:
    backend_instance_id: str
    backend_version: str = "UNAVAILABLE"
    build_manifest: Mapping[str, Any] | None = None
    started_monotonic: float = 0.0
    accepting_requests: bool = True

    def __post_init__(self) -> None:
        if self.started_monotonic == 0.0:
            self.started_monotonic = time.monotonic()

    def snapshot(self, *, control_request_id: str, runtime_generation: int) -> dict[str, Any]:
        manifest = dict(self.build_manifest or {})
        return {
            "kind": "runtime.health",
            "control_request_id": control_request_id,
            "runtime_generation": runtime_generation,
            "backend_instance_id": self.backend_instance_id,
            "backend_version": self.backend_version,
            "state": "READY" if self.accepting_requests else "DRAINING",
            "uptime_seconds": max(0.0, time.monotonic() - self.started_monotonic),
            "build_manifest_id": manifest.get("build_manifest_id"),
            "build_identity_state": manifest.get("build_identity_state", "UNAVAILABLE"),
            "build_manifest": manifest.get("build_manifest"),
            "execution_mode": "SYNCHRONOUS_IN_PROCESS",
            "checkpoint_resume": "UNAVAILABLE",
        }
