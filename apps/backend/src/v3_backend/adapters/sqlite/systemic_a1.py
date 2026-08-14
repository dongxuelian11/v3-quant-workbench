"""SQLite-backed A1 projections and immutable formal owner persistence."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    PRE_ALPHA_CEILING,
    TruthAdmissionState,
)
from v3_backend.domain.artifacts.model import ArtifactDescriptor
from v3_backend.domain.data_truth.formal import (
    CanonicalSnapshotVersion,
    CanonicalUniverseVersion,
)
from v3_backend.domain.datasets.formal import (
    CanonicalLabelPayloadVersion,
    FormalDatasetVersion,
)
from v3_backend.domain.factors.formal import FormalFeatureMaterialization
from v3_backend.domain.payload_authority import PayloadResolutionReceipt
from v3_backend.errors.exceptions import ConflictError
from v3_backend.provenance.canonical_hash import canonical_sha256

from ..systemic_a1_payload import FileSystemCanonicalJsonArtifactPublisher
from .repositories import SQLiteDataTruthRepository, SQLiteTableRepository
from .unit_of_work import SQLiteUnitOfWork


_OWNER_SCHEMA_FINGERPRINT = "sch_sha256_" + canonical_sha256(
    {"schema_version": "v3.systemic-a1-canonical-owner/1.0.0", "encoding": "canonical-json"}
)
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _reference_id(owner_type: str, owner_id: str, artifact_id: str) -> str:
    value = int(canonical_sha256([owner_type, owner_id, artifact_id]), 16) >> 128
    encoded = ""
    for _ in range(26):
        encoded = _CROCKFORD[value & 31] + encoded
        value >>= 5
    return "arf_" + encoded


def _time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("persisted A1 timestamp must be timezone-aware")
    return parsed


def _truth(value: object) -> TruthAdmissionState:
    return TruthAdmissionState.from_wire(value)


def _receipt(value: object) -> PayloadResolutionReceipt:
    if not isinstance(value, dict):
        raise ValueError("persisted P1 receipt must be an object")
    return PayloadResolutionReceipt(**value)


def _descriptor(value: object) -> ArtifactDescriptor:
    if not isinstance(value, dict):
        raise ValueError("persisted Artifact descriptor must be an object")
    payload = dict(value)
    payload["created_at"] = _parse_time(str(payload["created_at"]))
    payload["published_at"] = _parse_time(str(payload["published_at"]))
    return ArtifactDescriptor(**payload)


class SQLiteA1CanonicalOwnerRepository:
    """One adapter over existing Catalog/Artifact/PIT owners; no second database."""

    owner_record_version = "v3.systemic-a1-canonical-owner/1.0.0"

    def __init__(self, unit_of_work: SQLiteUnitOfWork, artifact_store) -> None:
        self.uow = unit_of_work
        self._store = artifact_store
        self.artifact_publisher = FileSystemCanonicalJsonArtifactPublisher(
            artifact_store, descriptor_sink=self
        )

    def register_descriptor(self, descriptor: ArtifactDescriptor) -> None:
        repository = SQLiteTableRepository(self.uow, "artifact")
        existing = repository.get(descriptor.artifact_id)
        expected = {
            "sha256": descriptor.sha256,
            "byte_size": descriptor.byte_size,
            "media_type": descriptor.media_type,
            "semantic_role": descriptor.role,
            "storage_key": descriptor.storage_key,
            "schema_fingerprint": descriptor.schema_fingerprint,
            "state": "PUBLISHED",
        }
        if existing is not None:
            if any(existing.get(key) != value for key, value in expected.items()):
                raise ConflictError("published Artifact descriptor conflicts with Catalog")
            return
        repository.add_new(
            {
                "artifact_id": descriptor.artifact_id,
                "sha256": descriptor.sha256,
                "byte_size": descriptor.byte_size,
                "media_type": descriptor.media_type,
                "semantic_role": descriptor.role,
                "storage_key": descriptor.storage_key,
                "safe_format_id": descriptor.safe_format_id,
                "schema_fingerprint": descriptor.schema_fingerprint,
                "state": "PUBLISHED",
                "created_at": _time(descriptor.created_at),
                "published_at": _time(descriptor.published_at),
            },
            idempotent=False,
        )

    def get_snapshot(self, snapshot_id: str) -> CanonicalSnapshotVersion | None:
        self._assert_active()
        rows = self.uow.connection.execute(
            """
            SELECT snapshot.snapshot_id,snapshot.connector_version_id,
                   COALESCE(snapshot.max_effective_time,partition.max_effective_time),
                   COALESCE(snapshot.max_available_time,partition.max_available_time),
                   profile.admission_state,calendar.calendar_version_id,
                   partition.parquet_artifact_id,partition.schema_fingerprint,
                   artifact.sha256,artifact.byte_size
            FROM data_snapshot AS snapshot
            JOIN snapshot_validation_binding AS binding
              ON binding.snapshot_id=snapshot.snapshot_id
            JOIN snapshot_validation_profile AS profile
              ON profile.validation_profile_id=binding.validation_profile_id
            JOIN snapshot_calendar AS calendar ON calendar.snapshot_id=snapshot.snapshot_id
            JOIN snapshot_partition AS partition ON partition.snapshot_id=snapshot.snapshot_id
            JOIN artifact ON artifact.artifact_id=partition.parquet_artifact_id
            WHERE snapshot.snapshot_id=? AND snapshot.state='PUBLISHED'
              AND artifact.state='PUBLISHED'
            """,
            (snapshot_id,),
        ).fetchall()
        admitted = [row for row in rows if len(str(row[7])) == 64]
        if len(admitted) != 1 or admitted[0][2] is None or admitted[0][3] is None:
            return None
        row = admitted[0]
        sources = tuple(
            (str(value[0]), str(value[1]))
            for value in self.uow.connection.execute(
                """
                SELECT source.raw_capture_id,capture.content_hash
                FROM snapshot_raw_capture AS source
                JOIN raw_capture AS capture ON capture.raw_capture_id=source.raw_capture_id
                WHERE source.snapshot_id=? AND capture.state='ACCEPTED'
                ORDER BY source.raw_capture_id
                """,
                (snapshot_id,),
            )
        )
        if not sources:
            return None
        ceiling = (
            FORMAL_ADMITTED_CEILING
            if str(row[4]) == "FORMAL_ADMITTED"
            else PRE_ALPHA_CEILING
        )
        return CanonicalSnapshotVersion(
            snapshot_id=str(row[0]),
            source_data_truth_id="dtr_sha256_" + canonical_sha256(sources),
            as_of=_parse_time(str(row[2])).date(),
            knowledge_cutoff=_parse_time(str(row[3])),
            calendar_version_id=str(row[5]),
            payload_artifact_id=str(row[6]),
            payload_sha256=str(row[8]),
            payload_byte_size=int(row[9]),
            schema_fingerprint="sch_sha256_" + str(row[7]),
            truth_admission=ceiling,
        )

    def get_universe(self, universe_version_id: str) -> CanonicalUniverseVersion | None:
        self._assert_active()
        row = self.uow.connection.execute(
            """
            SELECT universe.snapshot_id,universe.knowledge_cutoff,
                   universe.membership_artifact_id,member.state,
                   universe.audit_artifact_id,audit.state
            FROM universe_version AS universe
            LEFT JOIN artifact AS member ON member.artifact_id=universe.membership_artifact_id
            LEFT JOIN artifact AS audit ON audit.artifact_id=universe.audit_artifact_id
            WHERE universe.universe_version_id=? AND universe.state='PUBLISHED'
            """,
            (universe_version_id,),
        ).fetchone()
        if row is None or str(row[3]) != "PUBLISHED" or str(row[5]) != "PUBLISHED":
            return None
        snapshot = self.get_snapshot(str(row[0]))
        if snapshot is None:
            return None
        resolution = SQLiteDataTruthRepository(self.uow).resolve_members_as_of(
            universe_version_id,
            as_of=snapshot.as_of.isoformat(),
            decision_time=str(row[1]),
            strict=True,
        )
        instruments = tuple(str(member["instrument_id"]) for member in resolution.members)
        return CanonicalUniverseVersion.create(
            universe_version_id=universe_version_id,
            snapshot_id=snapshot.snapshot_id,
            as_of=snapshot.as_of,
            knowledge_cutoff=_parse_time(str(row[1])),
            instrument_ids=instruments,
            truth_admission=snapshot.truth_admission,
        )

    def publish_materialization(
        self, materialization: FormalFeatureMaterialization
    ) -> FormalFeatureMaterialization:
        existing = self.get_materialization(materialization.feature_materialization_id)
        if existing is not None:
            if existing.to_wire() != materialization.to_wire():
                raise ConflictError("conflicting FeatureMaterialization canonical owner")
            return existing
        self._persist_owner(
            "A1FeatureMaterialization",
            materialization.feature_materialization_id,
            self._materialization_record(materialization),
        )
        return materialization

    def get_materialization(self, identity: str) -> FormalFeatureMaterialization | None:
        record = self._load_owner("A1FeatureMaterialization", identity)
        if record is None:
            return None
        return FormalFeatureMaterialization(
            record["feature_materialization_id"],
            record["factor_definition_version_id"],
            record["snapshot_id"],
            record["universe_version_id"],
            record["universe_membership_identity"],
            record["knowledge_cutoff"],
            record["evaluator_version"],
            _receipt(record["input_receipt"]),
            _descriptor(record["output_descriptor"]),
            record["output_schema_fingerprint"],
            int(record["row_count"]),
            int(record["missing_count"]),
            _truth(record["truth_admission"]),
        )

    def publish_label_payload(
        self, owner: CanonicalLabelPayloadVersion
    ) -> CanonicalLabelPayloadVersion:
        existing = self.get_label_payload(owner.label_payload_id)
        if existing is not None:
            if self._label_stable(existing) != self._label_stable(owner):
                raise ConflictError("conflicting canonical Label owner")
            return existing
        self._persist_owner("A1CanonicalLabel", owner.label_payload_id, self._label_record(owner))
        return owner

    def get_label_payload(
        self, identity: str, context_identity: str | None = None
    ) -> CanonicalLabelPayloadVersion | None:
        if identity.startswith("clp_sha256_"):
            record = self._load_owner("A1CanonicalLabel", identity)
        else:
            record = self._find_label_record(identity, context_identity)
        if record is None:
            return None
        return CanonicalLabelPayloadVersion(
            record["label_payload_id"],
            record["label_spec_id"],
            record["snapshot_id"],
            record["universe_version_id"],
            record["calendar_version_id"],
            record["context_identity"],
            _receipt(record["source_receipt"]),
            record["engine_version"],
            record["artifact_id"],
            record["sha256"],
            int(record["byte_size"]),
            record["schema_fingerprint"],
            _truth(record["truth_admission"]),
        )

    def publish_dataset(self, dataset: FormalDatasetVersion) -> FormalDatasetVersion:
        existing = self.get_dataset(dataset.dataset_version_id)
        if existing is not None:
            if existing.to_wire() != dataset.to_wire():
                raise ConflictError("conflicting formal Dataset canonical owner")
            return existing
        self._persist_owner("A1FormalDataset", dataset.dataset_version_id, self._dataset_record(dataset))
        return dataset

    def get_dataset(self, identity: str) -> FormalDatasetVersion | None:
        record = self._load_owner("A1FormalDataset", identity)
        if record is None:
            return None
        return FormalDatasetVersion(
            record["dataset_version_id"],
            tuple(record["feature_materialization_ids"]),
            tuple(_receipt(value) for value in record["feature_receipts"]),
            record["label_spec_id"],
            record["label_payload_id"],
            _receipt(record["label_receipt"]),
            record["split_spec_id"],
            record["snapshot_id"],
            record["universe_version_id"],
            record["universe_membership_identity"],
            _descriptor(record["dataset_descriptor"]),
            record["dataset_schema_fingerprint"],
            int(record["sample_count"]),
            _truth(record["truth_admission"]),
        )

    def _assert_active(self) -> None:
        if not self.uow.active:
            raise RuntimeError("A1 canonical owner access requires an active UnitOfWork")

    def _persist_owner(self, owner_type: str, owner_id: str, owner: dict[str, object]) -> None:
        descriptor = self.artifact_publisher.publish_canonical_json(
            {"schema_version": self.owner_record_version, "owner_type": owner_type, "owner": owner},
            semantic_role="CANONICAL_OWNER_RECORD",
            provenance_entity_id=owner_id,
            schema_fingerprint=_OWNER_SCHEMA_FINGERPRINT,
        )
        self._bind_owner(owner_type, owner_id, descriptor.artifact_id)

    def _bind_owner(self, owner_type: str, owner_id: str, artifact_id: str) -> None:
        existing = self.uow.connection.execute(
            """
            SELECT artifact_id FROM artifact_reference
            WHERE owner_type=? AND owner_id=? AND role='CANONICAL_OWNER' AND state='ACTIVE'
            """,
            (owner_type, owner_id),
        ).fetchall()
        if existing:
            if len(existing) != 1 or str(existing[0][0]) != artifact_id:
                raise ConflictError("canonical A1 owner overwrite is forbidden")
            return
        SQLiteTableRepository(self.uow, "artifact_reference").add_new(
            {
                "artifact_reference_id": _reference_id(owner_type, owner_id, artifact_id),
                "owner_type": owner_type,
                "owner_id": owner_id,
                "role": "CANONICAL_OWNER",
                "artifact_id": artifact_id,
                "state": "ACTIVE",
                "created_at": _time(datetime.now(timezone.utc)),
            },
            idempotent=True,
        )

    def _load_owner(self, owner_type: str, owner_id: str) -> dict[str, object] | None:
        self._assert_active()
        rows = self.uow.connection.execute(
            """
            SELECT reference.artifact_id FROM artifact_reference AS reference
            JOIN artifact ON artifact.artifact_id=reference.artifact_id
            WHERE reference.owner_type=? AND reference.owner_id=?
              AND reference.role='CANONICAL_OWNER' AND reference.state='ACTIVE'
              AND artifact.state='PUBLISHED'
            """,
            (owner_type, owner_id),
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise ConflictError("canonical A1 owner has ambiguous active records")
        root = json.loads(self._store.read_bytes(str(rows[0][0])).decode("utf-8"))
        if root.get("schema_version") != self.owner_record_version or root.get("owner_type") != owner_type:
            raise ValueError("canonical A1 owner record schema/type mismatch")
        owner = root.get("owner")
        if not isinstance(owner, dict):
            raise ValueError("canonical A1 owner record is invalid")
        return owner

    def _find_label_record(self, label_spec_id: str, context_identity: str | None) -> dict[str, object] | None:
        self._assert_active()
        rows = self.uow.connection.execute(
            """
            SELECT reference.owner_id FROM artifact_reference AS reference
            WHERE reference.owner_type='A1CanonicalLabel'
              AND reference.role='CANONICAL_OWNER' AND reference.state='ACTIVE'
            ORDER BY reference.owner_id
            """
        ).fetchall()
        matches = []
        for row in rows:
            record = self._load_owner("A1CanonicalLabel", str(row[0]))
            if record is not None and record.get("label_spec_id") == label_spec_id and (
                context_identity is None or record.get("context_identity") == context_identity
            ):
                matches.append(record)
        if len(matches) > 1:
            raise ConflictError("canonical Label lookup is ambiguous without exact context")
        return None if not matches else matches[0]

    @staticmethod
    def _materialization_record(value: FormalFeatureMaterialization) -> dict[str, object]:
        return {
            "feature_materialization_id": value.feature_materialization_id,
            "factor_definition_version_id": value.factor_definition_version_id,
            "snapshot_id": value.snapshot_id,
            "universe_version_id": value.universe_version_id,
            "universe_membership_identity": value.universe_membership_identity,
            "knowledge_cutoff": value.knowledge_cutoff,
            "evaluator_version": value.evaluator_version,
            "input_receipt": value.input_receipt.to_identity_wire(),
            "output_descriptor": value.output_descriptor.to_wire(),
            "output_schema_fingerprint": value.output_schema_fingerprint,
            "row_count": value.row_count,
            "missing_count": value.missing_count,
            "truth_admission": value.truth_admission.to_wire(),
        }

    @staticmethod
    def _label_stable(value: CanonicalLabelPayloadVersion) -> dict[str, object]:
        return {
            "label_payload_id": value.label_payload_id,
            "label_spec_id": value.label_spec_id,
            "snapshot_id": value.snapshot_id,
            "universe_version_id": value.universe_version_id,
            "calendar_version_id": value.calendar_version_id,
            "context_identity": value.context_identity,
            "source_receipt_id": value.source_receipt.receipt_identity,
            "engine_version": value.engine_version,
            "artifact_id": value.artifact_id,
            "sha256": value.sha256,
            "byte_size": value.byte_size,
            "schema_fingerprint": value.schema_fingerprint,
            "truth_admission": value.truth_admission.to_wire(),
        }

    @classmethod
    def _label_record(cls, value: CanonicalLabelPayloadVersion) -> dict[str, object]:
        return {**cls._label_stable(value), "source_receipt": value.source_receipt.to_identity_wire()}

    @staticmethod
    def _dataset_record(value: FormalDatasetVersion) -> dict[str, object]:
        return {
            "dataset_version_id": value.dataset_version_id,
            "feature_materialization_ids": list(value.feature_materialization_ids),
            "feature_receipts": [item.to_identity_wire() for item in value.feature_receipts],
            "label_spec_id": value.label_spec_id,
            "label_payload_id": value.label_payload_id,
            "label_receipt": value.label_receipt.to_identity_wire(),
            "split_spec_id": value.split_spec_id,
            "snapshot_id": value.snapshot_id,
            "universe_version_id": value.universe_version_id,
            "universe_membership_identity": value.universe_membership_identity,
            "dataset_descriptor": value.dataset_descriptor.to_wire(),
            "dataset_schema_fingerprint": value.dataset_schema_fingerprint,
            "sample_count": value.sample_count,
            "truth_admission": value.truth_admission.to_wire(),
        }


__all__ = ["SQLiteA1CanonicalOwnerRepository"]
