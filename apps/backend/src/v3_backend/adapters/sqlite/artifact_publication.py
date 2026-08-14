"""Bind WS-C artifact publication to the single WS-B SQLite Catalog."""

from __future__ import annotations

from datetime import datetime, timezone

from v3_backend.domain.artifacts.model import ArtifactReference
from v3_backend.domain.artifacts.publication import ArtifactPublication
from v3_backend.repositories.unit_of_work import TransactionMode

from .repositories import SQLiteRepositoryRegistry
from .unit_of_work import SQLiteUnitOfWork


_OWNER_TYPES = {
    "tsk_": "Task",
    "run_": "Run",
    "att_": "TaskAttempt",
    "prj_": "Project",
    "res_": "Result",
    "twv_sha256_": "TargetWeightVector",
    "rar_sha256_": "RiskApplicationReceipt",
    "rawv_sha256_": "RiskAdjustedWeightVector",
    "rpsv_sha256_": "RiskPolicySetVersion",
}


def _wire_time(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Catalog timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _owner_type(reference: ArtifactReference) -> str:
    for prefix, owner_type in _OWNER_TYPES.items():
        if reference.owner_id.startswith(prefix):
            return owner_type
    raise ValueError(f"unsupported ArtifactReference owner identity: {reference.owner_id!r}")


class SQLiteArtifactPublicationPort:
    """Persist one WS-C publication through the active WS-B PUBLISH transaction."""

    def __init__(self, unit_of_work: SQLiteUnitOfWork) -> None:
        if unit_of_work.mode is not TransactionMode.PUBLISH:
            raise ValueError("artifact publication requires a PUBLISH UnitOfWork")
        if not unit_of_work.active:
            raise RuntimeError("artifact publication requires an active UnitOfWork")
        self.unit_of_work = unit_of_work
        self.registry = SQLiteRepositoryRegistry(unit_of_work)

    def publish(self, publication: ArtifactPublication) -> None:
        descriptor = publication.descriptor
        artifact_row = {
            "artifact_id": descriptor.artifact_id,
            "sha256": descriptor.sha256,
            "byte_size": descriptor.byte_size,
            "media_type": descriptor.media_type,
            "semantic_role": descriptor.role,
            "storage_key": descriptor.storage_key,
            "safe_format_id": descriptor.safe_format_id,
            "schema_fingerprint": descriptor.schema_fingerprint,
            "state": "STAGED",
            "created_at": _wire_time(descriptor.created_at),
        }
        repository = self.registry.artifact.table("artifact")
        existing = repository.get(descriptor.artifact_id)
        if existing is None:
            self.registry.artifact.declare_staged(artifact_row)
            self.registry.artifact.publish_verified(
                descriptor.artifact_id,
                sha256=descriptor.sha256,
                published_at=_wire_time(descriptor.published_at),
            )
        else:
            expected = {
                "sha256": descriptor.sha256,
                "byte_size": descriptor.byte_size,
                "media_type": descriptor.media_type,
                "semantic_role": descriptor.role,
                "storage_key": descriptor.storage_key,
                "safe_format_id": descriptor.safe_format_id,
                "schema_fingerprint": descriptor.schema_fingerprint,
                "state": "PUBLISHED",
            }
            if any(existing.get(key) != value for key, value in expected.items()):
                raise ValueError(
                    "existing published Artifact metadata conflicts with exact bytes"
                )
        for reference in publication.active_references:
            self.registry.artifact.add_reference(
                {
                    "artifact_reference_id": reference.reference_id,
                    "owner_type": _owner_type(reference),
                    "owner_id": reference.owner_id,
                    "role": reference.role,
                    "artifact_id": reference.artifact_id,
                    "state": reference.state,
                    "created_at": _wire_time(reference.created_at),
                }
            )
