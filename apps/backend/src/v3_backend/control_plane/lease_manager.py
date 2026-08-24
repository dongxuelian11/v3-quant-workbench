from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Protocol

from v3_backend.contracts.common.ids import validate_v3_id

from .resource_governor import ResourceGrant


class LeaseState(StrEnum):
    GRANTED = "GRANTED"
    RENEWED = "RENEWED"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"
    REVOKED = "REVOKED"


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

    def __post_init__(self) -> None:
        validate_v3_id(self.lease_id, "WorkerLease")
        validate_v3_id(self.attempt_id, "TaskAttempt")


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
        now = self.clock()
        expiry_seconds = grant.lease_expiry_seconds or grant.heartbeat_interval_seconds * 3
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
        now = self.clock()
        if lease.state not in {LeaseState.GRANTED, LeaseState.RENEWED} or now > lease.expires_at:
            raise ValueError("lease is not renewable")
        if sequence <= lease.last_heartbeat_sequence:
            raise ValueError("heartbeat sequence must be monotonic")
        if rss_bytes > lease.grant.memory_hard_limit_bytes or scratch_bytes > lease.grant.scratch_budget_bytes:
            raise MemoryError("worker exceeded lease limit")
        lease.last_heartbeat_sequence = sequence
        lease.last_heartbeat_at = now
        lease.state = LeaseState.RENEWED
        expiry_seconds = (
            lease.grant.lease_expiry_seconds
            or lease.grant.heartbeat_interval_seconds * 3
        )
        lease.expires_at = now + timedelta(seconds=expiry_seconds)
        self.persistence.save(lease)
        return lease

    def suspect(self, lease: WorkerLease) -> bool:
        reference = lease.last_heartbeat_at or lease.issued_at
        return self.clock() > reference + timedelta(seconds=lease.grant.heartbeat_interval_seconds * 2)

    def expire_due(self) -> tuple[WorkerLease, ...]:
        expired: list[WorkerLease] = []
        now = self.clock()
        for lease in self.persistence.active():
            if now > lease.expires_at:
                lease.state = LeaseState.EXPIRED
                self.persistence.save(lease)
                expired.append(lease)
        return tuple(expired)

    def revoke(self, lease_id: str) -> WorkerLease:
        lease = self.persistence.require(lease_id)
        lease.state = LeaseState.REVOKED
        self.persistence.save(lease)
        return lease

    def release(self, lease_id: str) -> WorkerLease:
        lease = self.persistence.require(lease_id)
        lease.state = LeaseState.RELEASED
        self.persistence.save(lease)
        return lease
