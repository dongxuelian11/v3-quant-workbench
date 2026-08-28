from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from enum import StrEnum
from pathlib import Path
from typing import Mapping, Protocol

from .host_resource_probe import (
    HostResourceProbe,
    HostResourceProbeError,
    HostResourceSnapshot,
)


RESOURCE_ADMISSION_UNAVAILABLE = "RESOURCE_ADMISSION_UNAVAILABLE"
ZERO_HASH = "0" * 64
MAX_RESOURCE_EVENTS = 1024


def _validate_strict_json(value: object, *, name: str) -> None:
    """Reject values that a JSON encoder would silently coerce."""

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
    lease_expiry_seconds: int | None = None
    gpu_device: str | None = None
    resumable: bool = False
    preset: str | None = None
    progress_stall_seconds: int | None = None


@dataclass(frozen=True)
class ResourceSample:
    pressure: PressureLevel = PressureLevel.NORMAL
    available_memory_bytes: int = 1 << 60
    reason: str = ""
    total_memory_bytes: int | None = None
    logical_cpu_count: int | None = None
    scratch_free_bytes: int | None = None
    host_snapshot_hash: str = ZERO_HASH
    probe_available: bool = True
    sampled_at: str | None = None


@dataclass(frozen=True)
class ResourceGrant:
    resource_class: str
    cpu_slots: int
    memory_hard_limit_bytes: int
    scratch_budget_bytes: int
    wall_clock_seconds: int
    heartbeat_interval_seconds: int
    lease_expiry_seconds: int | None
    gpu_device: str | None
    policy_version: str = "legacy"
    preset: str = "CUSTOM"
    host_snapshot_hash: str = ZERO_HASH
    resolved_resource_json: str = "{}"
    resolved_resource_hash: str = ZERO_HASH
    job_cpu_rate_per_10000: int | None = None
    runtime_generation_id: str | None = None
    scratch_root: str | None = None
    enforcement_state: str = "NOT_CONFIGURED"

    def __post_init__(self) -> None:
        if not isinstance(self.resource_class, str) or not 1 <= len(self.resource_class) <= 128:
            raise ValueError("resource_class must be a bounded non-empty string")
        for name in (
            "cpu_slots",
            "memory_hard_limit_bytes",
            "scratch_budget_bytes",
            "wall_clock_seconds",
            "heartbeat_interval_seconds",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.lease_expiry_seconds is not None and (
            not isinstance(self.lease_expiry_seconds, int)
            or isinstance(self.lease_expiry_seconds, bool)
            or self.lease_expiry_seconds < self.heartbeat_interval_seconds
        ):
            raise ValueError("lease_expiry_seconds must not be shorter than heartbeat_interval_seconds")
        if self.gpu_device is not None and (
            not isinstance(self.gpu_device, str) or not 1 <= len(self.gpu_device) <= 128
        ):
            raise ValueError("gpu_device must be bounded when present")
        for name, maximum in (
            ("policy_version", 128),
            ("preset", 32),
            ("enforcement_state", 32),
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not 1 <= len(value) <= maximum:
                raise ValueError(f"{name} must be a bounded non-empty string")
        if self.preset not in {"CONSERVATIVE", "STANDARD", "HIGH", "CUSTOM"}:
            raise ValueError("unknown resource preset")
        if self.enforcement_state not in {"PENDING", "VERIFIED", "FAILED", "NOT_CONFIGURED"}:
            raise ValueError("unknown resource enforcement state")
        if not isinstance(self.resolved_resource_json, str) or len(self.resolved_resource_json.encode("utf-8")) > 65536:
            raise ValueError("resolved_resource_json exceeds the Catalog bound")
        try:
            decoded = json.loads(self.resolved_resource_json)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("resolved_resource_json must be valid JSON") from error
        if not isinstance(decoded, Mapping):
            raise ValueError("resolved_resource_json must be an object")
        _validate_strict_json(decoded, name="resolved_resource_json")
        canonical_json = json.dumps(
            decoded,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if self.resolved_resource_json != canonical_json:
            raise ValueError("resolved_resource_json must use canonical JSON encoding")
        for name, value in (
            ("host_snapshot_hash", self.host_snapshot_hash),
            ("resolved_resource_hash", self.resolved_resource_hash),
        ):
            if not isinstance(value, str) or len(value) != 64 or value != value.lower() or any(
                char not in "0123456789abcdef" for char in value
            ):
                raise ValueError(f"{name} must be a lowercase SHA-256")
        if not (
            self.resolved_resource_json == "{}"
            and self.resolved_resource_hash == ZERO_HASH
        ) and hashlib.sha256(
            self.resolved_resource_json.encode("utf-8")
        ).hexdigest() != self.resolved_resource_hash:
            raise ValueError("resolved_resource_json hash does not match its content")
        if self.job_cpu_rate_per_10000 is not None and (
            not isinstance(self.job_cpu_rate_per_10000, int)
            or isinstance(self.job_cpu_rate_per_10000, bool)
            or not 1 <= self.job_cpu_rate_per_10000 <= 10000
        ):
            raise ValueError("job_cpu_rate_per_10000 must be between 1 and 10000")
        for name, value, maximum in (
            ("runtime_generation_id", self.runtime_generation_id, 128),
            ("scratch_root", self.scratch_root, 4096),
        ):
            if value is not None and (not isinstance(value, str) or not 1 <= len(value) <= maximum):
                raise ValueError(f"{name} must be bounded when present")


class ResourceSampler(Protocol):
    def sample(self) -> ResourceSample: ...


@dataclass(frozen=True)
class RuntimeResourcePolicy:
    """Validated, immutable view of runtime_resource_policy.v1.json."""

    schema_id: str
    soft_pressure_ratio: Decimal
    minimum_admission: Mapping[str, int]
    presets: Mapping[str, Mapping[str, int]]
    host_reserve: Mapping[str, int | Decimal]
    operation_stall_seconds: Mapping[str, int]
    cancellation_seconds: Mapping[str, int]
    content_hash: str

    @property
    def version(self) -> str:
        return self.schema_id.rsplit(":", 1)[-1]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "RuntimeResourcePolicy":
        if not isinstance(raw, Mapping):
            raise ValueError("runtime resource policy must be an object")
        expected_top_level = {
            "schema_id",
            "soft_pressure_ratio",
            "minimum_admission",
            "presets",
            "host_reserve",
            "operation_stall_seconds",
            "cancellation_seconds",
        }
        if set(raw) != expected_top_level or any(
            not isinstance(key, str) for key in raw
        ):
            raise ValueError("runtime resource policy top-level keys drifted")
        schema_id = raw.get("schema_id")
        if schema_id != "urn:v3:runtime-resource-policy:1.0.0":
            raise ValueError("runtime resource policy schema_id is not admitted")

        def require_ints(name: str, value: object) -> dict[str, int]:
            if not isinstance(value, Mapping):
                raise ValueError(f"runtime resource policy {name} must be an object")
            parsed: dict[str, int] = {}
            for key, item in value.items():
                if not isinstance(key, str) or not isinstance(item, int) or isinstance(item, bool):
                    raise ValueError(f"runtime resource policy {name} contains a non-integer")
                if item < 0:
                    raise ValueError(f"runtime resource policy {name} contains a negative value")
                parsed[key] = item
            return parsed

        minimum = require_ints("minimum_admission", raw.get("minimum_admission"))
        if set(minimum) != {"cpu_slots", "memory_bytes", "scratch_bytes"}:
            raise ValueError("runtime resource policy minimum_admission keys drifted")
        if any(value <= 0 for value in minimum.values()):
            raise ValueError("runtime resource policy minimum_admission must be positive")
        raw_presets = raw.get("presets")
        if not isinstance(raw_presets, Mapping):
            raise ValueError("runtime resource policy presets must be an object")
        if any(not isinstance(key, str) for key in raw_presets):
            raise ValueError("runtime resource policy preset keys must be strings")
        presets = {key: require_ints(f"preset:{key}", value) for key, value in raw_presets.items()}
        if set(presets) != {"CONSERVATIVE", "STANDARD", "HIGH"}:
            raise ValueError("runtime resource policy preset set drifted")
        for name, preset in presets.items():
            if set(preset) != {"cpu_slots", "memory_bytes", "scratch_bytes"}:
                raise ValueError(f"runtime resource policy {name} keys drifted")
            if any(value <= 0 for value in preset.values()):
                raise ValueError(f"runtime resource policy {name} values must be positive")

        ratio = raw.get("soft_pressure_ratio")
        if not isinstance(ratio, str):
            raise ValueError("runtime resource policy ratio must be a decimal string")
        try:
            soft_ratio = Decimal(ratio)
        except (InvalidOperation, ValueError) as error:
            raise ValueError("runtime resource policy ratio is invalid") from error
        if not soft_ratio.is_finite():
            raise ValueError("runtime resource policy ratio must be finite")
        if not Decimal("0") < soft_ratio <= Decimal("1"):
            raise ValueError("runtime resource policy ratio is out of range")

        raw_reserve = raw.get("host_reserve")
        if not isinstance(raw_reserve, Mapping):
            raise ValueError("runtime resource policy host_reserve must be an object")
        reserve: dict[str, int | Decimal] = {}
        for key, item in raw_reserve.items():
            if key in {"memory_total_ratio", "volume_free_ratio"}:
                if not isinstance(item, str):
                    raise ValueError(f"runtime resource policy {key} must be a decimal string")
                try:
                    parsed = Decimal(item)
                except (InvalidOperation, ValueError) as error:
                    raise ValueError(f"runtime resource policy {key} is invalid") from error
                if not parsed.is_finite() or not Decimal("0") < parsed <= Decimal("1"):
                    raise ValueError(f"runtime resource policy {key} is out of range")
                reserve[key] = parsed
            elif isinstance(item, int) and not isinstance(item, bool) and item >= 0:
                reserve[key] = item
            else:
                raise ValueError(f"runtime resource policy {key} must be a non-negative integer")
        required_reserve = {
            "memory_min_bytes",
            "memory_total_ratio",
            "memory_available_min_bytes",
            "volume_min_free_bytes",
            "volume_free_ratio",
        }
        if set(reserve) != required_reserve:
            raise ValueError("runtime resource policy host_reserve keys drifted")

        stall = require_ints("operation_stall_seconds", raw.get("operation_stall_seconds"))
        cancellation = require_ints("cancellation_seconds", raw.get("cancellation_seconds"))
        if set(stall) != {
            "RESEARCH",
            "LOCAL_DATA_IMPORT",
            "FACTOR_STUDY",
            "RESEARCH_BACKTEST",
            "STRATEGY_AUTHORING",
            "RESULT_VERIFY",
        } or any(value <= 0 for value in stall.values()):
            raise ValueError("runtime resource policy operation stall keys drifted")
        if set(cancellation) != {
            "stall_checkpoint_grace",
            "cooperative_cancel",
            "terminate_wait",
            "kill_wait",
        } or any(value <= 0 for value in cancellation.values()):
            raise ValueError("runtime resource policy cancellation keys drifted")
        encoded = json.dumps(
            raw, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        return cls(
            schema_id=str(schema_id),
            soft_pressure_ratio=soft_ratio,
            minimum_admission=minimum,
            presets=presets,
            host_reserve=reserve,
            operation_stall_seconds=stall,
            cancellation_seconds=cancellation,
            content_hash=hashlib.sha256(encoded).hexdigest(),
        )


DEFAULT_RESOURCE_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "runtime" / "runtime_resource_policy.v1.json"
)


def load_resource_policy(path: str | Path | None = None) -> RuntimeResourcePolicy:
    policy_path = Path(path or DEFAULT_RESOURCE_POLICY_PATH)
    try:
        raw = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ResourceRejected(f"{RESOURCE_ADMISSION_UNAVAILABLE}: policy unavailable") from error
    if not isinstance(raw, Mapping):
        raise ResourceRejected(f"{RESOURCE_ADMISSION_UNAVAILABLE}: policy is not an object")
    try:
        return RuntimeResourcePolicy.from_mapping(raw)
    except ValueError as error:
        raise ResourceRejected(f"{RESOURCE_ADMISSION_UNAVAILABLE}: policy invalid") from error


def _ceil_ratio(value: int, ratio: Decimal) -> int:
    return int((Decimal(value) * ratio).to_integral_value(rounding=ROUND_CEILING))


class ResourceGovernor:
    """Resolve bounded resource grants from parent-owned host observations.

    The legacy sampler path remains available for deterministic unit tests.
    A production caller supplies ``host_probe``; that path computes all three
    host budgets and refuses admission when a trustworthy observation is not
    available. Worker heartbeat numbers are intentionally not consumed here as
    an authority for the host budget.
    """

    def __init__(
        self,
        sampler: ResourceSampler | None = None,
        hardware: HardwareProfile | None = None,
        *,
        host_probe: HostResourceProbe | None = None,
        policy: RuntimeResourcePolicy | None = None,
        policy_path: str | Path | None = None,
        scratch_root: str | Path | None = None,
        runtime_generation_id: str | None = None,
    ) -> None:
        if sampler is None and host_probe is None:
            raise ValueError("ResourceGovernor requires a sampler or host_probe")
        self.sampler = sampler
        self.host_probe = host_probe
        self.policy = (
            policy or load_resource_policy(policy_path)
        ) if host_probe is not None else policy
        self.hardware = hardware
        # Preserve the lexical path so the supervisor/probe can reject a
        # symlink or Windows reparse point rather than resolving it away.
        self.scratch_root = None if scratch_root is None else str(Path(scratch_root).absolute())
        self.runtime_generation_id = runtime_generation_id
        self.legacy_test_mode = host_probe is None
        self.concurrency_limit = (
            max(1, hardware.max_concurrency)
            if hardware and hardware.admitted
            else 1
        )
        self.active: dict[str, ResourceGrant] = {}
        self.paused_classes: set[str] = set()
        self.resource_events: list[dict[str, object]] = []
        self._pressure_concurrency_limit: int | None = None

    def _record(self, action: str, resource_class: str, reason: str) -> None:
        self.record_event(
            {"action": action, "resource_class": resource_class, "reason": reason}
        )

    def record_event(self, event: Mapping[str, object]) -> None:
        """Record a bounded diagnostic event without growing forever.

        Resource events are local diagnostics, not durable execution truth. Keep
        the newest fixed-size window so pressure observations cannot become a
        memory leak. Callers still receive a normal event-shaped dictionary;
        only the oldest observations are evicted when the window is full.
        """

        if not isinstance(event, Mapping):
            raise ValueError("resource event must be a mapping")
        self.resource_events.append(dict(event))
        overflow = len(self.resource_events) - MAX_RESOURCE_EVENTS
        if overflow > 0:
            del self.resource_events[:overflow]

    def _sample(self) -> ResourceSample:
        if self.host_probe is not None:
            try:
                snapshot = self.host_probe.sample()
            except HostResourceProbeError:
                raise
            except Exception as error:
                raise HostResourceProbeError("host resource probe failed") from error
            if not isinstance(snapshot, HostResourceSnapshot):
                raise HostResourceProbeError("host resource probe returned an invalid snapshot")
            if (
                snapshot.logical_cpu_count < 1
                or snapshot.total_physical_memory_bytes < 1
                or snapshot.available_physical_memory_bytes < 0
                or snapshot.available_physical_memory_bytes > snapshot.total_physical_memory_bytes
                or snapshot.scratch_free_bytes < 0
            ):
                raise HostResourceProbeError("host resource probe returned invalid bounds")
            assert self.policy is not None
            minimum_memory = int(self.policy.minimum_admission["memory_bytes"])
            minimum_scratch = int(self.policy.minimum_admission["scratch_bytes"])
            memory_ratio = (
                snapshot.available_physical_memory_bytes / snapshot.total_physical_memory_bytes
                if snapshot.total_physical_memory_bytes
                else 0
            )
            scratch_ratio = snapshot.scratch_free_bytes / max(1, minimum_scratch)
            if (
                snapshot.available_physical_memory_bytes < minimum_memory
                or snapshot.scratch_free_bytes < minimum_scratch
            ):
                pressure = PressureLevel.CRITICAL
                reason = "host budget below minimum admission"
            elif memory_ratio < (1 - float(self.policy.soft_pressure_ratio)) or scratch_ratio < 1.25:
                pressure = PressureLevel.PRESSURED
                reason = "host headroom is under the soft pressure threshold"
            else:
                pressure = PressureLevel.NORMAL
                reason = ""
            return ResourceSample(
                pressure=pressure,
                available_memory_bytes=snapshot.available_physical_memory_bytes,
                reason=reason,
                total_memory_bytes=snapshot.total_physical_memory_bytes,
                logical_cpu_count=snapshot.logical_cpu_count,
                scratch_free_bytes=snapshot.scratch_free_bytes,
                host_snapshot_hash=snapshot.content_hash,
                sampled_at=snapshot.sampled_at,
            )
        assert self.sampler is not None
        sample = self.sampler.sample()
        if not isinstance(sample, ResourceSample):
            raise HostResourceProbeError("resource sampler returned an invalid sample")
        return sample

    def observe_pressure(self, resource_class: str) -> ResourceSample:
        try:
            sample = self._sample()
        except HostResourceProbeError as error:
            self._record("ADMISSION_UNAVAILABLE", resource_class, str(error))
            raise ResourceRejected(f"{RESOURCE_ADMISSION_UNAVAILABLE}: host probe unavailable") from error
        if sample.pressure is PressureLevel.PRESSURED:
            current_limit = self._pressure_concurrency_limit or self.concurrency_limit
            self._pressure_concurrency_limit = max(1, current_limit - 1)
            self.concurrency_limit = self._pressure_concurrency_limit
            self._record("REDUCE_FUTURE_CONCURRENCY", resource_class, sample.reason)
            self._record("REQUEST_SPILL_OR_CHECKPOINT", resource_class, sample.reason)
        elif sample.pressure is PressureLevel.CRITICAL:
            self._pressure_concurrency_limit = 1
            self.concurrency_limit = 1
            self._record("REDUCE_FUTURE_CONCURRENCY", resource_class, sample.reason)
            self._record("REQUEST_SPILL_OR_CHECKPOINT", resource_class, sample.reason)
            self.paused_classes.add(resource_class)
            self._record("PAUSE_ADMISSION", resource_class, sample.reason)
        return sample

    def _real_host_budgets(self, sample: ResourceSample) -> tuple[int, int, int]:
        assert self.policy is not None
        if not sample.probe_available:
            raise ResourceRejected(f"{RESOURCE_ADMISSION_UNAVAILABLE}: host probe unavailable")
        if (
            sample.total_memory_bytes is None
            or sample.logical_cpu_count is None
            or sample.scratch_free_bytes is None
        ):
            raise ResourceRejected(f"{RESOURCE_ADMISSION_UNAVAILABLE}: incomplete host snapshot")
        reserve = self.policy.host_reserve
        memory_reserve = max(
            int(reserve["memory_min_bytes"]),
            _ceil_ratio(sample.total_memory_bytes, Decimal(reserve["memory_total_ratio"])),
        )
        memory_host_budget = min(
            max(0, sample.total_memory_bytes - memory_reserve),
            max(0, sample.available_memory_bytes - int(reserve["memory_available_min_bytes"])),
        )
        scratch_reserve = max(
            int(reserve["volume_min_free_bytes"]),
            _ceil_ratio(sample.scratch_free_bytes, Decimal(reserve["volume_free_ratio"])),
        )
        scratch_host_budget = max(0, sample.scratch_free_bytes - scratch_reserve)
        cpu_host_budget = max(1, sample.logical_cpu_count - 1)
        committed_cpu = sum(grant.cpu_slots for grant in self.active.values())
        committed_memory = sum(grant.memory_hard_limit_bytes for grant in self.active.values())
        committed_scratch = sum(grant.scratch_budget_bytes for grant in self.active.values())
        return (
            max(0, cpu_host_budget - committed_cpu),
            max(0, memory_host_budget - committed_memory),
            max(0, scratch_host_budget - committed_scratch),
        )

    def _desired_limits(self, profile: OperationProfile) -> tuple[str, int, int, int]:
        preset = profile.preset or "CUSTOM"
        if self.host_probe is not None and profile.preset is not None:
            assert self.policy is not None
            values = self.policy.presets.get(profile.preset)
            if values is None:
                raise ResourceRejected(f"{RESOURCE_ADMISSION_UNAVAILABLE}: unknown resource preset")
            return (
                preset,
                int(values["cpu_slots"]),
                int(values["memory_bytes"]),
                int(values["scratch_bytes"]),
            )
        return (
            preset,
            profile.cpu_slots,
            profile.memory_hard_limit_bytes,
            profile.scratch_budget_bytes,
        )

    def admit(self, lease_id: str, profile: OperationProfile) -> ResourceGrant:
        sample = self.observe_pressure(profile.resource_class)
        if profile.resource_class in self.paused_classes or sample.pressure is PressureLevel.CRITICAL:
            raise ResourceRejected(f"{RESOURCE_ADMISSION_UNAVAILABLE}: resource class admission paused")

        preset, desired_cpu, desired_memory, desired_scratch = self._desired_limits(profile)
        if self.legacy_test_mode:
            if len(self.active) >= self.concurrency_limit:
                raise ResourceRejected("conservative concurrency limit reached")
            if sample.available_memory_bytes < desired_memory:
                raise ResourceRejected("insufficient admitted memory")
            if self.hardware and self.hardware.admitted:
                if desired_cpu > self.hardware.cpu_slots:
                    raise ResourceRejected("requested CPU slots exceed admitted hardware")
                if desired_memory > self.hardware.memory_bytes:
                    raise ResourceRejected("requested memory exceeds admitted hardware")
            if profile.gpu_device is not None:
                if not self.hardware or not self.hardware.admitted or profile.gpu_device not in self.hardware.gpu_devices:
                    raise ResourceRejected("explicit GPU device is not admitted")
            grant = ResourceGrant(
                resource_class=profile.resource_class,
                cpu_slots=desired_cpu,
                memory_hard_limit_bytes=desired_memory,
                scratch_budget_bytes=desired_scratch,
                wall_clock_seconds=profile.wall_clock_seconds,
                heartbeat_interval_seconds=profile.heartbeat_interval_seconds,
                lease_expiry_seconds=profile.lease_expiry_seconds,
                gpu_device=profile.gpu_device,
                preset=preset,
            )
            self.active[lease_id] = grant
            return grant

        cpu_budget, memory_budget, scratch_budget = self._real_host_budgets(sample)
        assert self.policy is not None
        minimum = self.policy.minimum_admission
        resolved_cpu = min(desired_cpu, cpu_budget)
        resolved_memory = min(desired_memory, memory_budget)
        resolved_scratch = min(desired_scratch, scratch_budget)
        if (
            resolved_cpu < int(minimum["cpu_slots"])
            or resolved_memory < int(minimum["memory_bytes"])
            or resolved_scratch < int(minimum["scratch_bytes"])
        ):
            self._record(
                "ADMISSION_UNAVAILABLE",
                profile.resource_class,
                "resolved host/global budget is below minimum admission",
            )
            raise ResourceRejected(f"{RESOURCE_ADMISSION_UNAVAILABLE}: resolved budget below minimum")

        assert sample.logical_cpu_count is not None
        job_cpu_rate = math.floor(10000 * resolved_cpu / sample.logical_cpu_count)
        job_cpu_rate = min(10000, max(1, job_cpu_rate))
        resolved = {
            "policy_version": self.policy.version,
            "policy_hash": self.policy.content_hash,
            "preset": preset,
            "host_snapshot_hash": sample.host_snapshot_hash,
            "logical_cpu_count": sample.logical_cpu_count,
            "resolved_cpu_slots": resolved_cpu,
            "resolved_memory_bytes": resolved_memory,
            "resolved_scratch_bytes": resolved_scratch,
            "job_cpu_rate_per_10000": job_cpu_rate,
        }
        resolved_json = json.dumps(resolved, sort_keys=True, separators=(",", ":"))
        resolved_hash = hashlib.sha256(resolved_json.encode("utf-8")).hexdigest()
        derived_concurrency = min(
            cpu_budget // max(1, int(minimum["cpu_slots"])),
            memory_budget // max(1, int(minimum["memory_bytes"])),
            scratch_budget // max(1, int(minimum["scratch_bytes"])),
        )
        capacity_limit = len(self.active) + derived_concurrency
        admission_limit = capacity_limit
        if self._pressure_concurrency_limit is not None:
            admission_limit = min(admission_limit, self._pressure_concurrency_limit)
        if len(self.active) >= admission_limit:
            raise ResourceRejected("conservative concurrency limit reached")
        self.concurrency_limit = max(1, admission_limit)
        grant = ResourceGrant(
            resource_class=profile.resource_class,
            cpu_slots=resolved_cpu,
            memory_hard_limit_bytes=resolved_memory,
            scratch_budget_bytes=resolved_scratch,
            wall_clock_seconds=profile.wall_clock_seconds,
            heartbeat_interval_seconds=profile.heartbeat_interval_seconds,
            lease_expiry_seconds=profile.lease_expiry_seconds,
            gpu_device=profile.gpu_device,
            policy_version=self.policy.version,
            preset=preset,
            host_snapshot_hash=sample.host_snapshot_hash,
            resolved_resource_json=resolved_json,
            resolved_resource_hash=resolved_hash,
            job_cpu_rate_per_10000=job_cpu_rate,
            scratch_root=self.scratch_root,
            runtime_generation_id=self.runtime_generation_id,
            enforcement_state="PENDING",
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


__all__ = [
    "DEFAULT_RESOURCE_POLICY_PATH",
    "FakeResourceSampler",
    "HardwareProfile",
    "MAX_RESOURCE_EVENTS",
    "OperationProfile",
    "PressureLevel",
    "RESOURCE_ADMISSION_UNAVAILABLE",
    "ResourceGrant",
    "ResourceGovernor",
    "ResourceRejected",
    "ResourceSample",
    "RuntimeResourcePolicy",
    "load_resource_policy",
]
