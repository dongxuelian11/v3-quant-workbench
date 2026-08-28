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
from v3_backend.control_plane.persistence import ConcurrentStateChange
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
        _enforcement_writer: object,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if _enforcement_writer is None:
            raise ValueError("_enforcement_writer is required")
        self.database_path = Path(database_path).resolve()
        self.identity_new = identity_new
        self.environment_profile_id = environment_profile_id
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._enforcement_writer = _enforcement_writer
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
                      state, granted_at, expires_at,
                      resource_policy_version, resource_class, resource_preset,
                      wall_clock_seconds, heartbeat_interval_seconds, lease_expiry_seconds,
                      host_snapshot_hash, resolved_resource_json, resolved_resource_hash,
                      job_cpu_rate_per_10000, runtime_generation_id, process_identity_hash,
                      scratch_root, job_object_identity, enforcement_state,
                      last_heartbeat_sequence, last_heartbeat_at,
                      worker_rss_bytes, worker_scratch_bytes,
                      parent_sample_memory_bytes, parent_sample_scratch_bytes, parent_sample_at
                    ) VALUES(
                      ?,?,?,?,?,?,?,?,
                      ?,?,?,?,?,?,?,?,
                      ?,?,?,?,?,?,?,?,
                      ?,?,?,?,?,?,?,?
                    )
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
                        lease.grant.policy_version,
                        lease.grant.resource_class,
                        lease.grant.preset,
                        lease.grant.wall_clock_seconds,
                        lease.grant.heartbeat_interval_seconds,
                        lease.grant.lease_expiry_seconds,
                        lease.grant.host_snapshot_hash,
                        lease.grant.resolved_resource_json,
                        lease.grant.resolved_resource_hash,
                        lease.grant.job_cpu_rate_per_10000,
                        lease.grant.runtime_generation_id,
                        None,
                        lease.grant.scratch_root,
                        None,
                        lease.grant.enforcement_state,
                        lease.last_heartbeat_sequence,
                        None if lease.last_heartbeat_at is None else _wire_time(lease.last_heartbeat_at),
                        lease.worker_rss_bytes,
                        lease.worker_scratch_bytes,
                        lease.parent_sample_memory_bytes,
                        lease.parent_sample_scratch_bytes,
                        None if lease.parent_sample_at is None else _wire_time(lease.parent_sample_at),
                    ),
                )
            else:
                worker_id = str(existing[0])
                current = connection.execute(
                    """
                    SELECT state,last_heartbeat_sequence
                    FROM worker_lease WHERE lease_id=?
                    """,
                    (lease.lease_id,),
                ).fetchone()
                if current is None:
                    raise KeyError(lease.lease_id)
                current_state = LeaseState(str(current[0]))
                current_sequence = int(current[1])
                terminal_states = {
                    LeaseState.EXPIRED,
                    LeaseState.RELEASED,
                    LeaseState.REVOKED,
                }
                incoming_terminal = lease.state in terminal_states
                if current_state in terminal_states:
                    if not incoming_terminal:
                        raise ConcurrentStateChange(
                            f"active lease save would reopen terminal lease: {lease.lease_id}"
                        )
                    # Terminal lease truth is monotonic.  A late release or
                    # revoke may race an expiry, but it must not rewrite the
                    # durable terminal classification.
                    connection.commit()
                    return
                if not incoming_terminal and (
                    lease.last_heartbeat_sequence < current_sequence
                    or (
                        lease.last_heartbeat_sequence == current_sequence
                        and current_state is LeaseState.RENEWED
                        and lease.state is LeaseState.GRANTED
                    )
                ):
                    raise ConcurrentStateChange(
                        f"stale active lease save: {lease.lease_id}"
                    )
                released_at = (
                    _wire_time(self.clock())
                    if incoming_terminal
                    else None
                )
                cursor = connection.execute(
                    """
                    UPDATE worker_lease
                    SET state=?, expires_at=?, renewed_at=?, released_at=?,
                        resource_policy_version=?, resource_class=?, resource_preset=?,
                        wall_clock_seconds=?, heartbeat_interval_seconds=?, lease_expiry_seconds=?,
                        host_snapshot_hash=?, resolved_resource_json=?, resolved_resource_hash=?,
                        job_cpu_rate_per_10000=?, runtime_generation_id=?, scratch_root=?,
                        enforcement_state=?, last_heartbeat_sequence=?, last_heartbeat_at=?,
                        worker_rss_bytes=?, worker_scratch_bytes=?,
                        parent_sample_memory_bytes=?, parent_sample_scratch_bytes=?, parent_sample_at=?
                    WHERE lease_id=?
                      AND state IN ('GRANTED','RENEWED')
                      AND last_heartbeat_sequence<=?
                    """,
                    (
                        lease.state.value,
                        _wire_time(lease.expires_at),
                        None if lease.last_heartbeat_at is None else _wire_time(lease.last_heartbeat_at),
                        released_at,
                        lease.grant.policy_version,
                        lease.grant.resource_class,
                        lease.grant.preset,
                        lease.grant.wall_clock_seconds,
                        lease.grant.heartbeat_interval_seconds,
                        lease.grant.lease_expiry_seconds,
                        lease.grant.host_snapshot_hash,
                        lease.grant.resolved_resource_json,
                        lease.grant.resolved_resource_hash,
                        lease.grant.job_cpu_rate_per_10000,
                        lease.grant.runtime_generation_id,
                        lease.grant.scratch_root,
                        lease.grant.enforcement_state,
                        lease.last_heartbeat_sequence,
                        None if lease.last_heartbeat_at is None else _wire_time(lease.last_heartbeat_at),
                        lease.worker_rss_bytes,
                        lease.worker_scratch_bytes,
                        lease.parent_sample_memory_bytes,
                        lease.parent_sample_scratch_bytes,
                        None if lease.parent_sample_at is None else _wire_time(lease.parent_sample_at),
                        lease.lease_id,
                        lease.last_heartbeat_sequence,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ConcurrentStateChange(
                        f"lease state changed concurrently: {lease.lease_id}"
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
                       scratch_limit_bytes, state, granted_at, expires_at, renewed_at,
                       resource_policy_version, resource_class, resource_preset,
                       wall_clock_seconds, heartbeat_interval_seconds, lease_expiry_seconds,
                       host_snapshot_hash, resolved_resource_json, resolved_resource_hash,
                       job_cpu_rate_per_10000, runtime_generation_id, scratch_root,
                       enforcement_state, last_heartbeat_sequence, last_heartbeat_at,
                       worker_rss_bytes, worker_scratch_bytes,
                       parent_sample_memory_bytes, parent_sample_scratch_bytes, parent_sample_at
                FROM worker_lease WHERE lease_id=?
                """,
                (lease_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(lease_id)
        renewed_at = None if row[8] is None else _parse_time(str(row[8]))
        last_heartbeat_at = None if row[23] is None else _parse_time(str(row[23]))
        parent_sample_at = None if row[28] is None else _parse_time(str(row[28]))
        grant = ResourceGrant(
            resource_class=str(row[10]),
            cpu_slots=int(row[1]),
            memory_hard_limit_bytes=int(row[2]),
            scratch_budget_bytes=int(row[4]),
            wall_clock_seconds=int(row[12]),
            heartbeat_interval_seconds=int(row[13]),
            lease_expiry_seconds=None if row[14] is None else int(row[14]),
            gpu_device=None if row[3] is None else str(row[3]),
            policy_version=str(row[9]),
            preset=str(row[11]),
            host_snapshot_hash=str(row[15]),
            resolved_resource_json=str(row[16]),
            resolved_resource_hash=str(row[17]),
            job_cpu_rate_per_10000=None if row[18] is None else int(row[18]),
            runtime_generation_id=None if row[19] is None else str(row[19]),
            scratch_root=None if row[20] is None else str(row[20]),
            enforcement_state=str(row[21]),
        )
        return WorkerLease(
            lease_id=lease_id,
            attempt_id=str(row[0]),
            grant=grant,
            issued_at=_parse_time(str(row[6])),
            expires_at=_parse_time(str(row[7])),
            lease_token=self._tokens.get(lease_id, "RECOVERY_TOKEN_UNAVAILABLE"),
            state=LeaseState(str(row[5])),
            last_heartbeat_sequence=int(row[22]),
            last_heartbeat_at=last_heartbeat_at or renewed_at,
            worker_rss_bytes=int(row[24]),
            worker_scratch_bytes=int(row[25]),
            parent_sample_memory_bytes=None if row[26] is None else int(row[26]),
            parent_sample_scratch_bytes=None if row[27] is None else int(row[27]),
            parent_sample_at=parent_sample_at,
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
        return tuple(self.require(lease_id) for lease_id in lease_ids)

    def set_process_id(self, lease_id: str, process_id: int) -> None:
        if not isinstance(process_id, int) or isinstance(process_id, bool) or process_id <= 0:
            raise ValueError("process_id must be a positive integer")
        connection = connect_catalog(self.database_path)
        try:
            cursor = connection.execute(
                """
                UPDATE worker SET process_id=?, state='BUSY'
                WHERE worker_id=(
                    SELECT worker_id FROM worker_lease
                    WHERE lease_id=? AND state IN ('GRANTED','RENEWED')
                )
                  AND state IN ('STARTING','IDLE','BUSY','DRAINING')
                """,
                (process_id, lease_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(lease_id)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def set_process_identity(
        self,
        lease_id: str,
        *,
        process_id: int,
        process_identity_hash: str,
    ) -> None:
        if (
            not isinstance(process_id, int)
            or isinstance(process_id, bool)
            or process_id <= 0
            or not isinstance(process_identity_hash, str)
            or len(process_identity_hash) != 64
            or process_identity_hash != process_identity_hash.lower()
            or any(char not in "0123456789abcdef" for char in process_identity_hash)
        ):
            raise ValueError("process_identity_hash must be a SHA-256")
        connection = connect_catalog(self.database_path)
        try:
            cursor = connection.execute(
                """
                UPDATE worker_lease SET process_identity_hash=? WHERE lease_id=?
                  AND state IN ('GRANTED','RENEWED')
                """,
                (process_identity_hash, lease_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(lease_id)
            cursor = connection.execute(
                """
                UPDATE worker SET process_id=?
                WHERE worker_id=(
                    SELECT worker_id FROM worker_lease
                    WHERE lease_id=? AND state IN ('GRANTED','RENEWED')
                )
                  AND state IN ('STARTING','IDLE','BUSY','DRAINING')
                """,
                (process_id, lease_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(lease_id)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _set_enforcement(
        self,
        lease_id: str,
        *,
        _writer: object,
        state: str,
        job_object_identity: str | None = None,
    ) -> None:
        if _writer is not self._enforcement_writer:
            raise PermissionError("resource enforcement writes are manager-owned")
        if state not in {"PENDING", "VERIFIED", "FAILED", "NOT_CONFIGURED"}:
            raise ValueError("unknown resource enforcement state")
        if state == "VERIFIED" and (
            not isinstance(job_object_identity, str)
            or not 1 <= len(job_object_identity) <= 256
        ):
            raise ValueError("VERIFIED enforcement requires a Job Object identity")
        if job_object_identity is not None and (
            not isinstance(job_object_identity, str)
            or not 1 <= len(job_object_identity) <= 256
        ):
            raise ValueError("job_object_identity must be bounded when present")
        connection = connect_catalog(self.database_path)
        try:
            cursor = connection.execute(
                """
                UPDATE worker_lease
                SET enforcement_state=?, job_object_identity=?
                WHERE lease_id=? AND state IN ('GRANTED','RENEWED')
                """,
                (state, job_object_identity, lease_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(lease_id)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
