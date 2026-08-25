"""SQLite-backed live WorkerLease persistence for the Product composition.

The control-plane LeaseManager remains the policy owner.  This adapter only
maps its typed lease aggregate onto the canonical worker/worker_lease tables;
it does not introduce a second task or lease state machine.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from v3_backend.control_plane.lease_manager import LeaseState, WorkerLease
from v3_backend.control_plane.resource_governor import ResourceGrant

from .connection import connect_catalog


def _wire_time(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("lease timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)


class SQLiteLeasePersistence:
    """Persist live control-plane leases in the single V3 Catalog."""

    def __init__(
        self,
        database_path: str | Path,
        identity_new: Callable[[str], str],
        *,
        environment_profile_id: str,
    ) -> None:
        self.database_path = Path(database_path).resolve()
        self.identity_new = identity_new
        self.environment_profile_id = environment_profile_id
        self._worker_ids: dict[str, str] = {}
        self._grants: dict[str, ResourceGrant] = {}
        self._tokens: dict[str, str] = {}
        self._heartbeat_sequences: dict[str, int] = {}

    def save(self, lease: WorkerLease) -> None:
        connection = connect_catalog(self.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT worker_id FROM worker_lease WHERE lease_id=?",
                (lease.lease_id,),
            ).fetchone()
            if existing is None:
                worker_id = self.identity_new("Worker")
                connection.execute(
                    """
                    INSERT INTO worker(worker_id, worker_kind, process_id,
                                       environment_profile_id, state, started_at)
                    VALUES(?, 'PRODUCT_RESEARCH_PROCESS_V1', NULL, ?, 'STARTING', ?)
                    """,
                    (worker_id, self.environment_profile_id, _wire_time(lease.issued_at)),
                )
                connection.execute(
                    """
                    INSERT INTO worker_lease(
                      lease_id, attempt_id, worker_id, cpu_slots,
                      memory_limit_bytes, gpu_device, scratch_limit_bytes,
                      state, granted_at, expires_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        lease.lease_id,
                        lease.attempt_id,
                        worker_id,
                        lease.grant.cpu_slots,
                        lease.grant.memory_hard_limit_bytes,
                        lease.grant.gpu_device,
                        lease.grant.scratch_budget_bytes,
                        lease.state.value,
                        _wire_time(lease.issued_at),
                        _wire_time(lease.expires_at),
                    ),
                )
            else:
                worker_id = str(existing[0])
                released_at = (
                    _wire_time(datetime.now(timezone.utc))
                    if lease.state in {LeaseState.RELEASED, LeaseState.REVOKED, LeaseState.EXPIRED}
                    else None
                )
                connection.execute(
                    """
                    UPDATE worker_lease
                    SET state=?, expires_at=?, renewed_at=?, released_at=?
                    WHERE lease_id=?
                    """,
                    (
                        lease.state.value,
                        _wire_time(lease.expires_at),
                        None if lease.last_heartbeat_at is None else _wire_time(lease.last_heartbeat_at),
                        released_at,
                        lease.lease_id,
                    ),
                )
                if lease.last_heartbeat_at is not None:
                    connection.execute(
                        "UPDATE worker SET state='BUSY', heartbeat_at=? WHERE worker_id=?",
                        (_wire_time(lease.last_heartbeat_at), worker_id),
                    )
                if released_at is not None:
                    worker_state = "LOST" if lease.state is LeaseState.EXPIRED else "STOPPED"
                    connection.execute(
                        "UPDATE worker SET state=?, stopped_at=? WHERE worker_id=?",
                        (worker_state, released_at, worker_id),
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        self._worker_ids[lease.lease_id] = worker_id
        self._grants[lease.lease_id] = lease.grant
        self._tokens[lease.lease_id] = lease.lease_token
        self._heartbeat_sequences[lease.lease_id] = lease.last_heartbeat_sequence

    def require(self, lease_id: str) -> WorkerLease:
        connection = connect_catalog(self.database_path, read_only=True)
        try:
            row = connection.execute(
                """
                SELECT attempt_id, cpu_slots, memory_limit_bytes, gpu_device,
                       scratch_limit_bytes, state, granted_at, expires_at, renewed_at
                FROM worker_lease WHERE lease_id=?
                """,
                (lease_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(lease_id)
        grant = self._grants.get(lease_id)
        if grant is None:
            raise KeyError(f"live lease policy metadata is unavailable: {lease_id}")
        renewed_at = None if row[8] is None else _parse_time(str(row[8]))
        return WorkerLease(
            lease_id=lease_id,
            attempt_id=str(row[0]),
            grant=grant,
            issued_at=_parse_time(str(row[6])),
            expires_at=_parse_time(str(row[7])),
            lease_token=self._tokens[lease_id],
            state=LeaseState(str(row[5])),
            last_heartbeat_sequence=self._heartbeat_sequences.get(lease_id, 0),
            last_heartbeat_at=renewed_at,
        )

    def active(self) -> tuple[WorkerLease, ...]:
        connection = connect_catalog(self.database_path, read_only=True)
        try:
            lease_ids = tuple(
                str(row[0])
                for row in connection.execute(
                    "SELECT lease_id FROM worker_lease WHERE state IN ('GRANTED','RENEWED') ORDER BY lease_id"
                )
            )
        finally:
            connection.close()
        return tuple(self.require(lease_id) for lease_id in lease_ids if lease_id in self._grants)

    def set_process_id(self, lease_id: str, process_id: int) -> None:
        connection = connect_catalog(self.database_path)
        try:
            connection.execute(
                """
                UPDATE worker SET process_id=?, state='BUSY'
                WHERE worker_id=(SELECT worker_id FROM worker_lease WHERE lease_id=?)
                """,
                (process_id, lease_id),
            )
            connection.commit()
        finally:
            connection.close()
