from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Protocol

from v3_backend.contracts.common.ids import validate_v3_id

from .persistence import ConcurrentStateChange
from .resource_governor import ResourceGrant


def _require_aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _require_non_negative_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


class LeaseState(StrEnum):
    GRANTED = "GRANTED"
    RENEWED = "RENEWED"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"
    REVOKED = "REVOKED"


class ParentResourceExceeded(MemoryError):
    """A parent-owned resource observation crossed a hard lease limit."""

    def __init__(self, kind: str, message: str = "") -> None:
        self.kind = kind
        super().__init__(message or kind)


@dataclass
class WorkerLease:
    lease_id: str
    attempt_id: str
    grant: ResourceGrant
    issued_at: datetime
    expires_at: datetime
    lease_token: str
    state: LeaseState = LeaseState.GRANTED
    last_heartbeat_sequence: int = 0
    last_heartbeat_at: datetime | None = None
    worker_rss_bytes: int = 0
    worker_scratch_bytes: int = 0
    parent_sample_memory_bytes: int | None = None
    parent_sample_scratch_bytes: int | None = None
    parent_sample_at: datetime | None = None

    def __post_init__(self) -> None:
        validate_v3_id(self.lease_id, "WorkerLease")
        validate_v3_id(self.attempt_id, "TaskAttempt")
        _require_aware(self.issued_at, "issued_at")
        _require_aware(self.expires_at, "expires_at")
        if self.expires_at < self.issued_at:
            raise ValueError("lease expiry cannot precede issuance")
        if not isinstance(self.lease_token, str) or not 1 <= len(self.lease_token) <= 256:
            raise ValueError("lease_token must be a bounded non-empty string")
        if not isinstance(self.state, LeaseState):
            raise ValueError("lease state is invalid")
        _require_non_negative_int(self.last_heartbeat_sequence, "heartbeat sequence")
        _require_non_negative_int(self.worker_rss_bytes, "worker telemetry RSS")
        _require_non_negative_int(self.worker_scratch_bytes, "worker telemetry scratch")
        if self.last_heartbeat_at is not None:
            _require_aware(self.last_heartbeat_at, "last_heartbeat_at")
        if self.parent_sample_memory_bytes is not None:
            _require_non_negative_int(self.parent_sample_memory_bytes, "parent memory sample")
        if self.parent_sample_scratch_bytes is not None:
            _require_non_negative_int(self.parent_sample_scratch_bytes, "parent scratch sample")
        if self.parent_sample_at is not None:
            _require_aware(self.parent_sample_at, "parent_sample_at")


class LeasePersistencePort(Protocol):
    def save(self, lease: WorkerLease) -> None: ...
    def require(self, lease_id: str) -> WorkerLease: ...
    def active(self) -> tuple[WorkerLease, ...]: ...


class InMemoryLeasePersistence:
    def __init__(self) -> None:
        self.items: dict[str, WorkerLease] = {}
        self.trace: list[str] = []

    def save(self, lease: WorkerLease) -> None:
        self.items[lease.lease_id] = copy.deepcopy(lease)
        self.trace.append(f"persist:{lease.state}")

    def require(self, lease_id: str) -> WorkerLease:
        return copy.deepcopy(self.items[lease_id])

    def active(self) -> tuple[WorkerLease, ...]:
        return tuple(
            copy.deepcopy(item)
            for item in self.items.values()
            if item.state in {LeaseState.GRANTED, LeaseState.RENEWED}
        )


class LeaseManager:
    def __init__(
        self,
        persistence: LeasePersistencePort,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.persistence = persistence
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def grant(
        self, lease_id: str, attempt_id: str, grant: ResourceGrant, *, lease_token: str
    ) -> WorkerLease:
        now = _require_aware(self.clock(), "lease clock")
        if not isinstance(lease_token, str) or not 1 <= len(lease_token) <= 256:
            raise ValueError("lease_token must be a bounded non-empty string")
        expiry_seconds = (
            grant.lease_expiry_seconds
            if grant.lease_expiry_seconds is not None
            else grant.heartbeat_interval_seconds * 3
        )
        if expiry_seconds < grant.heartbeat_interval_seconds:
            raise ValueError("lease expiry must not be shorter than heartbeat interval")
        lease = WorkerLease(
            lease_id,
            attempt_id,
            grant,
            now,
            now + timedelta(seconds=expiry_seconds),
            lease_token,
        )
        self.persistence.save(lease)
        return lease

    def heartbeat(
        self,
        lease_id: str,
        sequence: int,
        *,
        rss_bytes: int,
        scratch_bytes: int,
    ) -> WorkerLease:
        lease = self.persistence.require(lease_id)
        now = _require_aware(self.clock(), "lease clock")
        if lease.state not in {LeaseState.GRANTED, LeaseState.RENEWED} or now >= lease.expires_at:
            raise ValueError("lease is not renewable")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= lease.last_heartbeat_sequence:
            raise ValueError("heartbeat sequence must be monotonic")
        _require_non_negative_int(rss_bytes, "worker telemetry RSS")
        _require_non_negative_int(scratch_bytes, "worker telemetry scratch")
        lease.last_heartbeat_sequence = sequence
        lease.last_heartbeat_at = now
        lease.worker_rss_bytes = rss_bytes
        lease.worker_scratch_bytes = scratch_bytes
        lease.state = LeaseState.RENEWED
        expiry_seconds = (
            lease.grant.lease_expiry_seconds
            if lease.grant.lease_expiry_seconds is not None
            else lease.grant.heartbeat_interval_seconds * 3
        )
        lease.expires_at = now + timedelta(seconds=expiry_seconds)
        self.persistence.save(lease)
        return lease

    def record_parent_sample(
        self,
        lease_id: str,
        *,
        memory_bytes: int,
        scratch_bytes: int,
        sampled_at: datetime | None = None,
    ) -> WorkerLease:
        """Persist an authoritative parent observation and enforce hard limits."""

        _require_non_negative_int(memory_bytes, "parent memory sample")
        _require_non_negative_int(scratch_bytes, "parent scratch sample")
        lease = self.persistence.require(lease_id)
        now = _require_aware(self.clock(), "lease clock")
        if lease.state not in {LeaseState.GRANTED, LeaseState.RENEWED} or now >= lease.expires_at:
            raise ValueError("lease is not sampleable")
        sampled_time = _require_aware(sampled_at or now, "parent sample timestamp")
        if sampled_time > now:
            raise ValueError("parent sample timestamp cannot be in the future")
        lease.parent_sample_memory_bytes = memory_bytes
        lease.parent_sample_scratch_bytes = scratch_bytes
        lease.parent_sample_at = sampled_time
        self.persistence.save(lease)
        if memory_bytes >= lease.grant.memory_hard_limit_bytes:
            raise ParentResourceExceeded(
                "RESOURCE_EXHAUSTED_MEMORY",
                "parent memory sample reached the Job Object hard limit",
            )
        if scratch_bytes >= lease.grant.scratch_budget_bytes:
            raise ParentResourceExceeded(
                "RESOURCE_EXHAUSTED_SCRATCH",
                "parent scratch sample reached the hard quota",
            )
        return lease

    def suspect(self, lease: WorkerLease) -> bool:
        reference = lease.last_heartbeat_at or lease.issued_at
        return _require_aware(self.clock(), "lease clock") >= reference + timedelta(seconds=lease.grant.heartbeat_interval_seconds * 2)

    def expire_due(self) -> tuple[WorkerLease, ...]:
        expired: list[WorkerLease] = []
        now = _require_aware(self.clock(), "lease clock")
        for lease in self.persistence.active():
            if now >= lease.expires_at:
                lease.state = LeaseState.EXPIRED
                try:
                    self.persistence.save(lease)
                except ConcurrentStateChange:
                    # A heartbeat or another terminal observer may have won
                    # the CAS after ``active()`` returned its snapshot.  Do
                    # not stop the monitor on that expected race: re-read
                    # durable truth and only hand an actually expired lease
                    # back to the supervisor for worker fencing.
                    try:
                        current = self.persistence.require(lease.lease_id)
                    except KeyError:
                        continue
                    if current.state is LeaseState.EXPIRED:
                        expired.append(current)
                    continue
                expired.append(lease)
        return tuple(expired)

    def revoke(self, lease_id: str) -> WorkerLease:
        lease = self.persistence.require(lease_id)
        if lease.state in {
            LeaseState.EXPIRED,
            LeaseState.RELEASED,
            LeaseState.REVOKED,
        }:
            # Terminal lease truth is monotonic.  A late cleanup or restart
            # observer must not rewrite EXPIRED into REVOKED or otherwise
            # create a false second terminal transition.
            return lease
        lease.state = LeaseState.REVOKED
        try:
            self.persistence.save(lease)
            return lease
        except ConcurrentStateChange:
            current = self.persistence.require(lease_id)
            if current.state in {
                LeaseState.EXPIRED,
                LeaseState.RELEASED,
                LeaseState.REVOKED,
            }:
                return current
            raise

    def release(self, lease_id: str) -> WorkerLease:
        lease = self.persistence.require(lease_id)
        if lease.state in {
            LeaseState.EXPIRED,
            LeaseState.RELEASED,
            LeaseState.REVOKED,
        }:
            return lease
        lease.state = LeaseState.RELEASED
        try:
            self.persistence.save(lease)
            return lease
        except ConcurrentStateChange:
            current = self.persistence.require(lease_id)
            if current.state in {
                LeaseState.EXPIRED,
                LeaseState.RELEASED,
                LeaseState.REVOKED,
            }:
                return current
            raise
