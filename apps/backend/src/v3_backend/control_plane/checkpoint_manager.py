from __future__ import annotations

from pathlib import Path
from typing import Protocol

from v3_backend.adapters.sqlite.connection import connect_catalog
from v3_backend.contracts.common.ids import InvalidV3Id, validate_v3_id
from v3_backend.domain.tasks.entities import CheckpointMetadata, Run
from .progress_persistence import compatibility_hash_for_context


class CheckpointIncompatible(ValueError):
    pass


class CheckpointUnavailable(RuntimeError):
    """Checkpoint bytes/metadata are not an admitted recovery source."""


class CheckpointPort(Protocol):
    def save(self, checkpoint: CheckpointMetadata) -> None: ...
    def require(self, artifact_id: str) -> CheckpointMetadata: ...


class InMemoryCheckpointPort:
    def __init__(self) -> None:
        self.items: dict[str, CheckpointMetadata] = {}

    def save(self, checkpoint: CheckpointMetadata) -> None:
        if checkpoint.artifact_id in self.items and self.items[checkpoint.artifact_id] != checkpoint:
            raise ValueError("checkpoint artifact metadata is immutable")
        self.items[checkpoint.artifact_id] = checkpoint

    def require(self, artifact_id: str) -> CheckpointMetadata:
        try:
            return self.items[artifact_id]
        except KeyError as exc:
            raise KeyError(f"checkpoint not found: {artifact_id}") from exc


class SQLiteCheckpointPort:
    """Read only the PR02-published checkpoint closure from the Catalog.

    Metadata-only ``save`` is deliberately forbidden on the product port.  A
    checkpoint becomes resumable only after its Artifact is PUBLISHED and its
    final bytes can be re-hashed by the existing Artifact Store.
    """

    def __init__(self, database_path: str | Path, artifact_store: object | None = None) -> None:
        self.database_path = Path(database_path).resolve()
        self.artifact_store = artifact_store

    def save(self, checkpoint: CheckpointMetadata) -> None:
        raise CheckpointUnavailable(
            "CHECKPOINT_NOT_AVAILABLE: product checkpoint publication requires the Artifact UoW"
        )

    def require(self, artifact_id: str) -> CheckpointMetadata:
        try:
            validate_v3_id(artifact_id, "Artifact")
        except InvalidV3Id as error:
            raise CheckpointUnavailable(
                "CHECKPOINT_NOT_AVAILABLE: checkpoint Artifact identity is invalid"
            ) from error
        if not isinstance(artifact_id, str) or not artifact_id.startswith("art_sha256_"):
            raise CheckpointUnavailable("CHECKPOINT_NOT_AVAILABLE: checkpoint Artifact identity is invalid")
        connection = connect_catalog(self.database_path, read_only=True)
        try:
            row = connection.execute(
                """
                SELECT c.checkpoint_id,c.attempt_id,c.artifact_id,c.code_version,
                       c.environment_profile_id,c.input_hash,c.compatibility_hash,
                       r.run_id,r.input_hash AS run_input_hash,r.code_version AS run_code_version,
                       r.environment_profile_id AS run_environment_profile,
                       r.operation_schema_version,r.resource_policy_version,
                       r.resolved_resource_hash,r.compatibility_hash AS run_compatibility_hash,
                       t.operation_id,a.attempt_id AS created_by_attempt_id,
                       a.state AS attempt_state,ar.state AS artifact_state,
                       ar.sha256,ar.byte_size
                FROM checkpoint AS c
                JOIN task_attempt AS a ON a.attempt_id=c.attempt_id
                JOIN run AS r ON r.run_id=a.run_id
                JOIN task AS t ON t.task_id=r.task_id
                JOIN artifact AS ar ON ar.artifact_id=c.artifact_id
                WHERE c.artifact_id=?
                ORDER BY c.created_at DESC,c.checkpoint_id DESC
                LIMIT 1
                """,
                (artifact_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(f"checkpoint not found: {artifact_id}")
        if str(row[18]) != "PUBLISHED":
            raise CheckpointUnavailable(
                "CHECKPOINT_NOT_AVAILABLE: checkpoint Artifact is not PUBLISHED"
            )
        if (
            str(row[19]) != artifact_id[len("art_sha256_") :]
            or int(row[20]) < 0
            or str(row[5]) != str(row[8])
            or str(row[3]) != str(row[9])
            or str(row[4]) != str(row[10])
            or str(row[6]) != str(row[14])
        ):
            raise CheckpointUnavailable(
                "CHECKPOINT_NOT_AVAILABLE: checkpoint Artifact metadata is inconsistent"
            )
        verifier = getattr(self.artifact_store, "verify_final_bytes", None)
        if not callable(verifier):
            raise CheckpointUnavailable(
                "CHECKPOINT_NOT_AVAILABLE: Artifact byte verifier is unavailable"
            )
        try:
            observed_sha, observed_size = verifier(
                artifact_id, expected_byte_size=int(row[20])
            )
        except Exception as error:
            raise CheckpointUnavailable(
                "CHECKPOINT_NOT_AVAILABLE: checkpoint Artifact bytes are unavailable"
            ) from error
        if observed_sha != str(row[19]) or observed_size != int(row[20]):
            raise CheckpointUnavailable(
                "CHECKPOINT_NOT_AVAILABLE: checkpoint Artifact bytes changed"
            )
        bounded_metadata = {
            "checkpoint_id": str(row[0]),
            "operation_id": str(row[15]),
            "operation_schema_version": str(row[11]),
            "resource_policy_version": str(row[12]),
            "resolved_resource_hash": str(row[13]),
            "run_compatibility_hash": str(row[14]),
            "artifact_sha256": str(row[19]),
        }
        return CheckpointMetadata(
            artifact_id=str(row[2]),
            run_id=str(row[7]),
            input_hash=str(row[5]),
            code_version=str(row[3]),
            environment_profile=str(row[4]),
            compatibility_hash=str(row[6]),
            created_by_attempt_id=str(row[16]),
            bounded_metadata=bounded_metadata,
        )


class CheckpointManager:
    def __init__(self, port: CheckpointPort, *, require_complete_compatibility: bool = False) -> None:
        self.port = port
        self.require_complete_compatibility = require_complete_compatibility

    def publish(self, checkpoint: CheckpointMetadata) -> None:
        self.port.save(checkpoint)

    def validate_resume(
        self, artifact_id: str, run: Run, compatibility_hash: str
    ) -> CheckpointMetadata:
        checkpoint = self.port.require(artifact_id)
        expected = (
            checkpoint.run_id == run.run_id,
            checkpoint.input_hash == run.identity.normalized_input_hash,
            checkpoint.code_version == run.identity.code_version,
            checkpoint.environment_profile == run.identity.environment_profile,
            checkpoint.compatibility_hash == compatibility_hash,
        )
        if not all(expected):
            raise CheckpointIncompatible("CHECKPOINT_INCOMPATIBLE")
        if self.require_complete_compatibility:
            required = {
                "operation_id",
                "operation_schema_version",
                "resource_policy_version",
                "resolved_resource_hash",
            }
            if not required.issubset(checkpoint.bounded_metadata):
                raise CheckpointIncompatible("CHECKPOINT_INCOMPATIBLE")
            try:
                expected_hash = compatibility_hash_for_context(
                    input_hash=run.identity.normalized_input_hash,
                    code_version=run.identity.code_version,
                    environment_profile=run.identity.environment_profile,
                    operation_id=checkpoint.bounded_metadata["operation_id"],
                    operation_schema_version=checkpoint.bounded_metadata[
                        "operation_schema_version"
                    ],
                    resource_policy_version=checkpoint.bounded_metadata[
                        "resource_policy_version"
                    ],
                    resolved_resource_hash=checkpoint.bounded_metadata[
                        "resolved_resource_hash"
                    ],
                )
            except (KeyError, TypeError, ValueError) as error:
                raise CheckpointIncompatible("CHECKPOINT_INCOMPATIBLE") from error
            if checkpoint.compatibility_hash != expected_hash or compatibility_hash != expected_hash:
                raise CheckpointIncompatible("CHECKPOINT_INCOMPATIBLE")
        return checkpoint


__all__ = [
    "CheckpointIncompatible",
    "CheckpointManager",
    "CheckpointPort",
    "CheckpointUnavailable",
    "InMemoryCheckpointPort",
    "SQLiteCheckpointPort",
]
