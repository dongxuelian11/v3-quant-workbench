from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ResourceRejected(RuntimeError):
    pass


class PressureLevel(StrEnum):
    NORMAL = "NORMAL"
    PRESSURED = "PRESSURED"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class HardwareProfile:
    profile_id: str
    admitted: bool
    cpu_slots: int
    memory_bytes: int
    gpu_devices: tuple[str, ...] = ()
    max_concurrency: int = 1


@dataclass(frozen=True)
class OperationProfile:
    operation_id: str
    resource_class: str
    cpu_slots: int = 1
    memory_hard_limit_bytes: int = 512 * 1024 * 1024
    scratch_budget_bytes: int = 512 * 1024 * 1024
    wall_clock_seconds: int = 3600
    heartbeat_interval_seconds: int = 5
    gpu_device: str | None = None
    resumable: bool = False


@dataclass(frozen=True)
class ResourceSample:
    pressure: PressureLevel = PressureLevel.NORMAL
    available_memory_bytes: int = 1 << 60
    reason: str = ""


@dataclass(frozen=True)
class ResourceGrant:
    resource_class: str
    cpu_slots: int
    memory_hard_limit_bytes: int
    scratch_budget_bytes: int
    wall_clock_seconds: int
    heartbeat_interval_seconds: int
    gpu_device: str | None


class ResourceSampler(Protocol):
    def sample(self) -> ResourceSample: ...


class ResourceGovernor:
    """Policy-only governor; production hardware sampling is injected later."""

    def __init__(
        self,
        sampler: ResourceSampler,
        hardware: HardwareProfile | None = None,
    ) -> None:
        self.sampler = sampler
        self.hardware = hardware
        self.concurrency_limit = max(1, hardware.max_concurrency) if hardware and hardware.admitted else 1
        self.active: dict[str, ResourceGrant] = {}
        self.paused_classes: set[str] = set()
        self.resource_events: list[dict[str, object]] = []

    def _record(self, action: str, resource_class: str, reason: str) -> None:
        self.resource_events.append(
            {"action": action, "resource_class": resource_class, "reason": reason}
        )

    def observe_pressure(self, resource_class: str) -> ResourceSample:
        sample = self.sampler.sample()
        if sample.pressure is PressureLevel.PRESSURED:
            self.concurrency_limit = max(1, self.concurrency_limit - 1)
            self._record("REDUCE_FUTURE_CONCURRENCY", resource_class, sample.reason)
            self._record("REQUEST_SPILL_OR_CHECKPOINT", resource_class, sample.reason)
        elif sample.pressure is PressureLevel.CRITICAL:
            self.concurrency_limit = 1
            self._record("REDUCE_FUTURE_CONCURRENCY", resource_class, sample.reason)
            self._record("REQUEST_SPILL_OR_CHECKPOINT", resource_class, sample.reason)
            self.paused_classes.add(resource_class)
            self._record("PAUSE_ADMISSION", resource_class, sample.reason)
        return sample

    def admit(self, lease_id: str, profile: OperationProfile) -> ResourceGrant:
        sample = self.observe_pressure(profile.resource_class)
        if profile.resource_class in self.paused_classes or sample.pressure is PressureLevel.CRITICAL:
            raise ResourceRejected("resource class admission paused")
        if len(self.active) >= self.concurrency_limit:
            raise ResourceRejected("conservative concurrency limit reached")
        if sample.available_memory_bytes < profile.memory_hard_limit_bytes:
            raise ResourceRejected("insufficient admitted memory")
        if self.hardware and self.hardware.admitted:
            if profile.cpu_slots > self.hardware.cpu_slots:
                raise ResourceRejected("requested CPU slots exceed admitted hardware")
            if profile.memory_hard_limit_bytes > self.hardware.memory_bytes:
                raise ResourceRejected("requested memory exceeds admitted hardware")
        if profile.gpu_device is not None:
            if not self.hardware or not self.hardware.admitted or profile.gpu_device not in self.hardware.gpu_devices:
                raise ResourceRejected("explicit GPU device is not admitted")
        grant = ResourceGrant(
            resource_class=profile.resource_class,
            cpu_slots=profile.cpu_slots,
            memory_hard_limit_bytes=profile.memory_hard_limit_bytes,
            scratch_budget_bytes=profile.scratch_budget_bytes,
            wall_clock_seconds=profile.wall_clock_seconds,
            heartbeat_interval_seconds=profile.heartbeat_interval_seconds,
            gpu_device=profile.gpu_device,
        )
        self.active[lease_id] = grant
        return grant

    def release(self, lease_id: str) -> None:
        self.active.pop(lease_id, None)

    def worker_over_limit(self, lease_id: str, reason: str) -> None:
        grant = self.active.get(lease_id)
        if grant:
            self._record("TERMINATE_SPECIFIC_WORKER", grant.resource_class, reason)


class FakeResourceSampler:
    def __init__(self, sample: ResourceSample | None = None) -> None:
        self.current = sample or ResourceSample()

    def sample(self) -> ResourceSample:
        return self.current
