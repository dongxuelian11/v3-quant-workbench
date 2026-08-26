"""Bind WS-C artifact publication to the single WS-B SQLite Catalog."""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Mapping, Sequence

from v3_backend.adapters.artifact_store import (
    FileSystemArtifactStore,
    PublicationResult,
    StagingReceipt,
)
from v3_backend.domain.artifacts.exceptions import (
    ArtifactCollision,
    ArtifactScanLimitExceeded,
    ArtifactError,
    GarbageCollectionSafetyError,
    IntegrityMismatch,
    StagingNotFound,
)
from v3_backend.domain.artifacts.lifecycle import (
    ArtifactPromotionIntent,
    exact_artifact_ids_hash,
    gc_confirmation_hash,
)
from v3_backend.domain.artifacts.identity import (
    sha256_from_artifact_id,
    storage_key_for_sha256,
)
from v3_backend.domain.artifacts.model import ArtifactDescriptor
from v3_backend.domain.artifacts.model import ArtifactReference
from v3_backend.domain.artifacts.publication import ArtifactPublication
from v3_backend.domain.artifacts.reachability import (
    GarbageCollectionItem,
    GarbageCollectionPlan,
    ReachabilityGraph,
)
from v3_backend.errors.exceptions import ConflictError
from v3_backend.provenance.canonical_hash import canonical_json_bytes
from v3_backend.repositories.unit_of_work import TransactionMode

from .connection import connect_catalog
from .repositories import SQLiteRepositoryRegistry
from .unit_of_work import SQLiteUnitOfWork


_OWNER_TYPES = {
    "art_sha256_": "Artifact",
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


_ID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_OPEN_INTENT_STATES = ("STAGED_SYNCED", "FINAL_PRESENT", "CATALOG_COMMITTED", "CLEANUP_PENDING")


class _PublishedBytesUnavailable(ArtifactError):
    """The admitted bytes cannot be recovered without manual review."""


def _mint_id(prefix: str) -> str:
    return prefix + "".join(secrets.choice(_ID_ALPHABET) for _ in range(26))


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Catalog timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _canonical_text(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _namespace_locked(method):
    """Hold the store namespace lease across one complete lifecycle action."""

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self.store.namespace_lock():
            return method(self, *args, **kwargs)

    return wrapper


def _descriptor_wire(descriptor: ArtifactDescriptor) -> dict[str, Any]:
    value = descriptor.to_wire()
    value["storage_key"] = descriptor.storage_key
    return value


def _reference_wire(reference: ArtifactReference) -> dict[str, Any]:
    return {
        "artifact_reference_id": reference.reference_id,
        "owner_type": _owner_type(reference),
        "owner_id": reference.owner_id,
        "role": reference.role,
        "artifact_id": reference.artifact_id,
        "state": reference.state,
        "created_at": _wire_time(reference.created_at),
        "released_at": None,
    }


def _reference_set_signature(values: Sequence[Mapping[str, Any]]) -> tuple[tuple[Any, ...], ...]:
    """Canonicalize a reference set before it can cross the Catalog boundary."""

    return tuple(
        sorted(
            (
                (
                    str(value["artifact_reference_id"]),
                    str(value["owner_type"]),
                    str(value["owner_id"]),
                    str(value["role"]),
                    str(value["artifact_id"]),
                    str(value["state"]),
                    str(value["created_at"]),
                    value.get("released_at"),
                )
                for value in values
            )
        )
    )


def _reference_semantic_signature(
    values: Sequence[Mapping[str, Any]],
) -> tuple[tuple[Any, ...], ...]:
    """Compare retry semantics without treating a locally minted ID as input truth.

    A Product callback may be reconstructed after a process loss and mint a new
    local reference ID/timestamp for the same owner/role.  The durable
    promotion intent owns the actual reference identity and timestamp; the
    retry is allowed to reuse it only when all owner-facing reference
    semantics match.
    """

    return tuple(
        sorted(
            (
                (
                    str(value["owner_type"]),
                    str(value["owner_id"]),
                    str(value["role"]),
                    str(value["artifact_id"]),
                    str(value["state"]),
                    value.get("released_at"),
                )
                for value in values
            )
        )
    )


@dataclass(frozen=True, slots=True)
class PreparedArtifactPublication:
    promotion_intent_id: str
    staging: StagingReceipt
    # Re-entry must use the exact reference identities already admitted by
    # the durable intent.  A new callback object may mint different local
    # reference IDs for the same stage; returning the persisted set prevents
    # that retry from presenting a different Catalog publication.
    active_references: tuple[ArtifactReference, ...] = ()


class _NoopPublishCallbacks:
    """Catalog-only recovery transaction; it never owns filesystem bytes."""

    def verify_staged(self) -> None:
        return None

    def publish_staged(self) -> None:
        return None

    def compensate_unreferenced_staging(self) -> None:
        return None

    def notify_committed(self) -> None:
        return None


class ArtifactPublicationCoordinator:
    """Deep WS-C coordinator for durable bytes + Catalog publication.

    The public surface is intentionally small: prepare an intent, promote one
    prepared stage, finalize after Catalog commit, and reconcile on restart.
    All filesystem operations are verified before a Catalog state is advanced.
    """

    def __init__(self, database_path: str | Path, store: FileSystemArtifactStore) -> None:
        self.database_path = Path(database_path).resolve()
        self.store = store

    def _connection(self, *, read_only: bool = False) -> sqlite3.Connection:
        return connect_catalog(self.database_path, read_only=read_only)

    def _write(self, operation):
        connection = self._connection()
        uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
        try:
            uow.begin()
            result = operation(SQLiteRepositoryRegistry(uow).artifact)
            uow.commit()
            return result
        finally:
            if uow.active:
                uow.rollback()
            connection.close()

    def _record_error(
        self,
        *,
        intent_id: str | None,
        artifact_id: str | None,
        phase: str,
        error_code: str,
        observed_state: Mapping[str, Any],
    ) -> None:
        connection = self._connection()
        uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
        try:
            uow.begin()
            SQLiteRepositoryRegistry(uow).artifact.record_storage_error(
                {
                    "storage_error_id": _mint_id("ase_"),
                    "promotion_intent_id": intent_id,
                    "artifact_id": artifact_id,
                    "phase": phase,
                    "error_code": error_code,
                    "observed_state_json": _canonical_text(dict(observed_state)),
                    "created_at": _wire_time(datetime.now(timezone.utc)),
                    "resolved_at": None,
                }
            )
            uow.commit()
        finally:
            if uow.active:
                uow.rollback()
            connection.close()

    def _intent_by_stage(self, staging_token: str) -> dict[str, Any] | None:
        connection = self._connection(read_only=True)
        try:
            row = connection.execute(
                "SELECT * FROM artifact_promotion_intent WHERE staging_token=?",
                (staging_token,),
            ).fetchone()
            return None if row is None else dict(row)
        finally:
            connection.close()

    def _prepared_from_existing_intent(
        self,
        existing: Mapping[str, Any],
        *,
        staging: StagingReceipt,
        descriptor: ArtifactDescriptor,
        references: Sequence[Mapping[str, Any]],
    ) -> PreparedArtifactPublication:
        """Admit a retry only against the exact durable intent semantics."""

        expected = {
            "artifact_id": descriptor.artifact_id,
            "expected_sha256": staging.sha256,
            "expected_byte_size": staging.byte_size,
            "staging_token": staging.staging_token,
            "staging_key": f".staging/{staging.staging_token}.stage",
            "final_storage_key": descriptor.storage_key,
        }
        if any(str(existing.get(key)) != str(value) for key, value in expected.items()):
            raise ArtifactCollision("staging token is bound to a conflicting promotion intent")
        try:
            self._validate_intent(existing)
            existing_descriptor = json.loads(str(existing["descriptor_json"]))
            requested_descriptor = json.loads(_canonical_text(_descriptor_wire(descriptor)))
            existing_references = json.loads(str(existing["references_json"]))
            persisted_references = self._references_from_intent(existing)
        except ArtifactCollision:
            raise
        except Exception as exc:
            raise ArtifactCollision(
                "existing promotion intent metadata is malformed"
            ) from exc
        if not isinstance(existing_descriptor, Mapping) or not isinstance(
            requested_descriptor, Mapping
        ):
            raise ArtifactCollision("promotion intent descriptor shape is invalid")
        immutable_descriptor_fields = (
            "media_type",
            "role",
            "safe_format_id",
            "schema_fingerprint",
            "semantic_fingerprint",
            "provenance_entity_id",
        )
        if any(
            existing_descriptor.get(field) != requested_descriptor.get(field)
            for field in immutable_descriptor_fields
        ):
            raise ArtifactCollision("staging token is bound to conflicting Artifact metadata")
        if _reference_semantic_signature(existing_references) != _reference_semantic_signature(
            references
        ):
            raise ArtifactCollision("staging token is bound to conflicting Artifact references")
        return PreparedArtifactPublication(
            str(existing["promotion_intent_id"]),
            staging,
            persisted_references,
        )

    def _validate_intent(self, row: Mapping[str, Any]) -> ArtifactDescriptor:
        """Validate the durable intent's identity and store keys before use.

        The database row is recovery evidence, not an authority to redirect a
        caller to an arbitrary path.  Every path-bearing field is checked
        against the content identity and the canonical Artifact descriptor.
        """

        expected_sha256 = str(row["expected_sha256"])
        artifact_id = str(row["artifact_id"])
        if artifact_id != "art_sha256_" + expected_sha256:
            raise ArtifactCollision("promotion intent Artifact identity is inconsistent")
        staging_token = str(row["staging_token"])
        try:
            self.store.staging_path(staging_token)
        except Exception as exc:
            raise ArtifactCollision("promotion intent staging token is invalid") from exc
        if str(row["staging_key"]) != f".staging/{staging_token}.stage":
            raise ArtifactCollision("promotion intent staging key is not canonical")
        try:
            descriptor = self._descriptor_from_intent(row)
            references = self._references_from_intent(row)
            descriptor_value = json.loads(str(row["descriptor_json"]))
            if _canonical_text(descriptor_value) != _canonical_text(
                _descriptor_wire(descriptor)
            ):
                raise ArtifactCollision("promotion intent descriptor JSON is not canonical")
            if len({reference.reference_id for reference in references}) != len(references):
                raise ArtifactCollision("promotion intent contains duplicate references")
            semantic_keys = {
                (
                    _owner_type(reference),
                    reference.owner_id,
                    reference.role,
                    reference.artifact_id,
                )
                for reference in references
            }
            if len(semantic_keys) != len(references):
                raise ArtifactCollision("promotion intent contains duplicate owner bindings")
            if _canonical_text([_reference_wire(reference) for reference in references]) != str(
                row["references_json"]
            ):
                raise ArtifactCollision("promotion intent references JSON is not canonical")
        except ArtifactCollision:
            raise
        except Exception as exc:
            raise ArtifactCollision("promotion intent descriptor or references are malformed") from exc
        if (
            descriptor.artifact_id != artifact_id
            or descriptor.sha256 != expected_sha256
            or descriptor.byte_size != int(row["expected_byte_size"])
            or descriptor.storage_key != str(row["final_storage_key"])
        ):
            raise ArtifactCollision("promotion intent descriptor or final key is inconsistent")
        try:
            decision = self.store.policy.require_publishable(
                descriptor.role, descriptor.media_type
            )
        except Exception as exc:
            raise ArtifactCollision(
                "promotion intent role/media type is not publishable"
            ) from exc
        if descriptor.safe_format_id != decision.safe_format_id:
            raise ArtifactCollision(
                "promotion intent safe format is not authorized by the store policy"
            )
        return descriptor

    def _resolve_storage_errors(
        self, *, artifact_id: str | None = None, promotion_intent_id: str | None = None
    ) -> None:
        self._write(
            lambda repository: repository.resolve_storage_errors(
                artifact_id=artifact_id,
                promotion_intent_id=promotion_intent_id,
                resolved_at=_wire_time(datetime.now(timezone.utc)),
            )
        )

    @_namespace_locked
    def prepare(
        self,
        staging: StagingReceipt,
        *,
        media_type: str,
        role: str,
        provenance_entity_id: str,
        schema_fingerprint: str | None,
        semantic_fingerprint: str | None,
        published_at: datetime,
        active_references: tuple[ArtifactReference, ...],
    ) -> PreparedArtifactPublication:
        """Durably record STAGED_SYNCED before any final-path mutation."""

        if published_at.tzinfo is None or published_at.utcoffset() is None:
            raise ValueError("published_at must be timezone-aware")
        if not active_references:
            raise ValueError("Artifact publication requires an active reference")
        if any(reference.state != "ACTIVE" for reference in active_references):
            raise ValueError("promotion intent accepts active references only")
        artifact_id = "art_sha256_" + staging.sha256
        if any(reference.artifact_id != artifact_id for reference in active_references):
            raise ArtifactCollision("promotion references must target the staged Artifact")
        reference_semantic_keys = tuple(
            (
                _owner_type(reference),
                reference.owner_id,
                reference.role,
                reference.artifact_id,
            )
            for reference in active_references
        )
        if len(set(reference_semantic_keys)) != len(reference_semantic_keys):
            raise ArtifactCollision("promotion references contain duplicate owner bindings")
        decision = self.store.policy.require_publishable(role, media_type)
        descriptor = ArtifactDescriptor(
            artifact_id=artifact_id,
            sha256=staging.sha256,
            byte_size=staging.byte_size,
            media_type=media_type,
            role=role,
            safe_format_id=decision.safe_format_id,
            schema_fingerprint=schema_fingerprint,
            semantic_fingerprint=semantic_fingerprint,
            created_at=min(staging.created_at, published_at),
            published_at=published_at,
            provenance_entity_id=provenance_entity_id,
        )
        references = tuple(
            {
                "artifact_reference_id": reference.reference_id,
                "owner_type": _owner_type(reference),
                "owner_id": reference.owner_id,
                "role": reference.role,
                "artifact_id": reference.artifact_id,
                "state": reference.state,
                "created_at": _wire_time(reference.created_at),
                "released_at": None,
            }
            for reference in active_references
        )
        descriptor_json = _canonical_text(_descriptor_wire(descriptor))
        references_json = _canonical_text(list(references))
        existing = self._intent_by_stage(staging.staging_token)
        if existing is not None:
            return self._prepared_from_existing_intent(
                existing,
                staging=staging,
                descriptor=descriptor,
                references=references,
            )

        # The receipt is caller-supplied metadata, not byte authority. Verify
        # the closed stage before making a new durable intent visible; the
        # PUBLISH callback repeats this check immediately before promotion to
        # cover the verify-to-intent race.  Existing intents are handled above
        # from their durable identity so a retry can still recover after stage
        # cleanup or process loss.
        self.store.verify_staged(
            staging.staging_token,
            expected_sha256=staging.sha256,
            expected_byte_size=staging.byte_size,
            media_type=media_type,
            role=role,
        )

        intent_id = _mint_id("api_")
        row = {
            "promotion_intent_id": intent_id,
            "artifact_id": artifact_id,
            "expected_sha256": staging.sha256,
            "expected_byte_size": staging.byte_size,
            "staging_token": staging.staging_token,
            "staging_key": f".staging/{staging.staging_token}.stage",
            "final_storage_key": descriptor.storage_key,
            "state": "STAGED_SYNCED",
            "state_version": 1,
            "descriptor_json": descriptor_json,
            "references_json": references_json,
            "created_at": _wire_time(published_at),
            "updated_at": _wire_time(published_at),
            "finalized_at": None,
            "last_error_code": None,
            "last_error_detail_artifact_id": None,
        }
        connection = self._connection()
        uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
        try:
            uow.begin()
            SQLiteRepositoryRegistry(uow).artifact.create_promotion_intent(row)
            uow.commit()
        except ConflictError as exc:
            if uow.active:
                uow.rollback()
            # A different process may have won the unique staging-token race.
            # Re-read after rollback and admit only the exact same durable
            # intent semantics; all other conflicts remain failures.
            existing_after_race = self._intent_by_stage(staging.staging_token)
            if existing_after_race is not None:
                return self._prepared_from_existing_intent(
                    existing_after_race,
                    staging=staging,
                    descriptor=descriptor,
                    references=references,
                )
            try:
                self._record_error(
                    intent_id=None,
                    artifact_id=artifact_id,
                    phase="CATALOG",
                    error_code="ARTIFACT_PROMOTION_INTENT_NOT_DURABLE",
                    observed_state={"staging_token": staging.staging_token, "error": str(exc)},
                )
            except Exception:
                pass
            raise
        except Exception as exc:
            if uow.active:
                uow.rollback()
            try:
                self._record_error(
                    intent_id=None,
                    artifact_id=artifact_id,
                    phase="CATALOG",
                    error_code="ARTIFACT_PROMOTION_INTENT_NOT_DURABLE",
                    observed_state={"staging_token": staging.staging_token, "error": str(exc)},
                )
            except Exception:
                # The original exception remains authoritative when the Catalog
                # itself is unavailable; the stage is intentionally retained.
                pass
            raise
        finally:
            connection.close()
        return PreparedArtifactPublication(intent_id, staging, active_references)

    def _transition(
        self,
        intent_id: str,
        *,
        expected_state: str,
        expected_version: int,
        target_state: str,
        descriptor_json: str | None = None,
        references_json: str | None = None,
        finalized_at: str | None = None,
        last_error_code: str | None = None,
        last_error_detail_artifact_id: str | None = None,
    ) -> dict[str, Any]:
        connection = self._connection()
        uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
        try:
            uow.begin()
            row = SQLiteRepositoryRegistry(uow).artifact.transition_promotion_intent(
                intent_id,
                expected_state=expected_state,
                expected_state_version=expected_version,
                target_state=target_state,
                updated_at=_wire_time(datetime.now(timezone.utc)),
                finalized_at=finalized_at,
                last_error_code=last_error_code,
                last_error_detail_artifact_id=last_error_detail_artifact_id,
                descriptor_json=descriptor_json,
                references_json=references_json,
            )
            uow.commit()
            return row
        finally:
            if uow.active:
                uow.rollback()
            connection.close()

    @_namespace_locked
    def promote(
        self,
        prepared: PreparedArtifactPublication,
        *,
        media_type: str,
        role: str,
        provenance_entity_id: str,
        schema_fingerprint: str | None,
        semantic_fingerprint: str | None,
        published_at: datetime,
    ) -> PublicationResult:
        persisted = self._read_intent(prepared.promotion_intent_id)
        if persisted is None:
            raise StagingNotFound("promotion intent is missing")
        persisted_descriptor = self._validate_intent(persisted)
        if (
            str(persisted["artifact_id"]) != "art_sha256_" + prepared.staging.sha256
            or str(persisted["staging_token"]) != prepared.staging.staging_token
            or int(persisted["expected_byte_size"]) != prepared.staging.byte_size
            or str(persisted["expected_sha256"]) != prepared.staging.sha256
        ):
            raise ArtifactCollision("promotion intent and stage identities differ")
        if published_at.tzinfo is None or published_at.utcoffset() is None:
            raise ValueError("published_at must be timezone-aware")
        requested_descriptor = ArtifactDescriptor(
            artifact_id=persisted_descriptor.artifact_id,
            sha256=persisted_descriptor.sha256,
            byte_size=persisted_descriptor.byte_size,
            media_type=media_type,
            role=role,
            created_at=persisted_descriptor.created_at,
            # The durable intent owns timestamps as well as content identity.
            # A reconstructed callback may carry a fresh wall-clock value;
            # allowing it to rewrite the intent would make retry non-idempotent.
            published_at=persisted_descriptor.published_at,
            provenance_entity_id=provenance_entity_id,
            safe_format_id=persisted_descriptor.safe_format_id,
            schema_fingerprint=schema_fingerprint,
            semantic_fingerprint=semantic_fingerprint,
        )
        if _canonical_text(_descriptor_wire(requested_descriptor)) != _canonical_text(
            _descriptor_wire(persisted_descriptor)
        ):
            raise ArtifactCollision("promotion metadata is not authorized by the durable intent")

        state = str(persisted["state"])
        if state == "FAILED":
            raise ArtifactError("promotion intent is terminally failed")
        if state == "FINALIZED":
            self.store.verify_final_bytes(
                persisted_descriptor.artifact_id,
                expected_byte_size=persisted_descriptor.byte_size,
            )
            return PublicationResult(
                persisted_descriptor,
                True,
                persisted_descriptor.storage_key,
            )
        if state in {"FINAL_PRESENT", "CATALOG_COMMITTED", "CLEANUP_PENDING"}:
            try:
                self.store.verify_final_bytes(
                    persisted_descriptor.artifact_id,
                    expected_byte_size=persisted_descriptor.byte_size,
                )
            except (StagingNotFound, ArtifactCollision, IntegrityMismatch):
                pass
            else:
                self._resolve_storage_errors(
                    artifact_id=persisted_descriptor.artifact_id,
                    promotion_intent_id=prepared.promotion_intent_id,
                )
                return PublicationResult(
                    persisted_descriptor,
                    True,
                    persisted_descriptor.storage_key,
                )
        elif state != "STAGED_SYNCED":
            raise ArtifactError("promotion intent is not recoverable")
        result = self.store.promote_staged(
            prepared.staging.staging_token,
            promotion_intent_id=prepared.promotion_intent_id,
            expected_sha256=prepared.staging.sha256,
            expected_byte_size=prepared.staging.byte_size,
            media_type=media_type,
            role=role,
            provenance_entity_id=provenance_entity_id,
            schema_fingerprint=schema_fingerprint,
            semantic_fingerprint=semantic_fingerprint,
            published_at=persisted_descriptor.published_at,
        )
        try:
            connection = self._connection(read_only=True)
            try:
                row = connection.execute(
                    "SELECT state,state_version FROM artifact_promotion_intent WHERE promotion_intent_id=?",
                    (prepared.promotion_intent_id,),
                ).fetchone()
            finally:
                connection.close()
            if row is None:
                raise StagingNotFound("promotion intent disappeared during promotion")
            if str(row["state"]) == "STAGED_SYNCED":
                self._transition(
                    prepared.promotion_intent_id,
                    expected_state="STAGED_SYNCED",
                    expected_version=int(row["state_version"]),
                    target_state="FINAL_PRESENT",
                    # The filesystem result is byte evidence only.  Its
                    # mtime-derived descriptor must never rewrite the
                    # durable publication metadata captured by prepare().
                    descriptor_json=_canonical_text(_descriptor_wire(persisted_descriptor)),
                )
            elif str(row["state"]) not in {"FINAL_PRESENT", "CATALOG_COMMITTED", "CLEANUP_PENDING", "FINALIZED"}:
                raise ArtifactError("promotion intent is not recoverable")
        except Exception as exc:
            try:
                self._record_error(
                    intent_id=prepared.promotion_intent_id,
                    artifact_id=result.descriptor.artifact_id,
                    phase="PROMOTION",
                    error_code="ARTIFACT_PROMOTION_RECONCILIATION_REQUIRED",
                    observed_state={"state": "FINAL_PRESENT", "error": str(exc)},
                )
            except Exception:
                pass
            raise
        self._resolve_storage_errors(
            artifact_id=result.descriptor.artifact_id,
            promotion_intent_id=prepared.promotion_intent_id,
        )
        return PublicationResult(
            persisted_descriptor,
            result.deduplicated,
            persisted_descriptor.storage_key,
        )

    @_namespace_locked
    def note_callback_failure(self, prepared: PreparedArtifactPublication, exc: BaseException) -> None:
        """Persist the rollback evidence without deleting final bytes."""

        try:
            self._record_error(
                intent_id=prepared.promotion_intent_id,
                artifact_id="art_sha256_" + prepared.staging.sha256,
                phase="CATALOG",
                error_code="ARTIFACT_PROMOTION_RECONCILIATION_REQUIRED",
                observed_state={"error": str(exc)},
            )
        except Exception:
            pass

    @_namespace_locked
    def finalize(self, prepared: PreparedArtifactPublication) -> dict[str, Any]:
        connection = self._connection(read_only=True)
        try:
            row = connection.execute(
                "SELECT * FROM artifact_promotion_intent WHERE promotion_intent_id=?",
                (prepared.promotion_intent_id,),
            ).fetchone()
            current = None if row is None else dict(row)
        finally:
            connection.close()
        if current is None:
            raise StagingNotFound("promotion intent is missing")
        if current["state"] == "FINALIZED":
            return current
        if current["state"] not in {"CATALOG_COMMITTED", "CLEANUP_PENDING"}:
            raise ArtifactError("cannot finalize an uncommitted promotion intent")
        try:
            # A process may have crashed after the Catalog commit and before
            # the final rename became durable.  The retained stage is still
            # an admitted recovery source; do not terminally fail the intent
            # merely because the first final-byte read is missing or wrong.
            self._ensure_reconciled_bytes(current)
            self.store.verify_final_bytes(
                str(current["artifact_id"]),
                expected_byte_size=int(current["expected_byte_size"]),
            )
        except Exception as exc:
            error_code = (
                "ARTIFACT_CONTENT_ADDRESS_COLLISION_OR_CORRUPTION"
                if isinstance(exc, (ArtifactCollision, IntegrityMismatch))
                else "PUBLISHED_BYTES_UNAVAILABLE"
            )
            try:
                self._record_error(
                    intent_id=prepared.promotion_intent_id,
                    artifact_id=str(current["artifact_id"]),
                    phase="CLEANUP",
                    error_code=error_code,
                    observed_state={"state": current["state"], "error": str(exc)},
                )
            except Exception:
                pass
            if current["state"] == "CATALOG_COMMITTED":
                try:
                    self._transition(
                        prepared.promotion_intent_id,
                        expected_state="CATALOG_COMMITTED",
                        expected_version=int(current["state_version"]),
                        target_state="CLEANUP_PENDING",
                        last_error_code=error_code,
                        last_error_detail_artifact_id=str(current["artifact_id"]),
                    )
                except Exception:
                    pass
            raise _PublishedBytesUnavailable(
                f"published Artifact bytes are unavailable: {current['artifact_id']}"
            ) from exc
        try:
            cleaned = self.store.cleanup_staging(prepared.staging.staging_token)
            if not cleaned:
                raise OSError("stage cleanup did not confirm absence")
        except Exception as exc:
            try:
                self._record_error(
                    intent_id=prepared.promotion_intent_id,
                    artifact_id=str(current["artifact_id"]),
                    phase="CLEANUP",
                    error_code="ARTIFACT_STAGE_CLEANUP_PENDING",
                    observed_state={"state": current["state"], "error": str(exc)},
                )
            except Exception:
                pass
            if current["state"] == "CATALOG_COMMITTED":
                return self._transition(
                    prepared.promotion_intent_id,
                    expected_state="CATALOG_COMMITTED",
                    expected_version=int(current["state_version"]),
                    target_state="CLEANUP_PENDING",
                    last_error_code="ARTIFACT_STAGE_CLEANUP_PENDING",
                    last_error_detail_artifact_id=str(current["artifact_id"]),
                )
            return current
        return self._transition(
            prepared.promotion_intent_id,
            expected_state=str(current["state"]),
            expected_version=int(current["state_version"]),
            target_state="FINALIZED",
            finalized_at=_wire_time(datetime.now(timezone.utc)),
        )

    def _descriptor_from_intent(self, row: Mapping[str, Any]) -> ArtifactDescriptor:
        value = json.loads(str(row["descriptor_json"]))
        return ArtifactDescriptor(
            artifact_id=str(value["artifact_id"]),
            sha256=str(value["sha256"]),
            byte_size=int(value["byte_size"]),
            media_type=str(value["media_type"]),
            role=str(value["role"]),
            created_at=_parse_time(str(value["created_at"])),
            published_at=_parse_time(str(value["published_at"])),
            provenance_entity_id=str(value["provenance_entity_id"]),
            safe_format_id=None if value.get("safe_format_id") is None else str(value["safe_format_id"]),
            schema_fingerprint=None if value.get("schema_fingerprint") is None else str(value["schema_fingerprint"]),
            semantic_fingerprint=None if value.get("semantic_fingerprint") is None else str(value["semantic_fingerprint"]),
        )

    def _references_from_intent(self, row: Mapping[str, Any]) -> tuple[ArtifactReference, ...]:
        values = json.loads(str(row["references_json"]))
        if not isinstance(values, list) or not values:
            raise ArtifactCollision("promotion intent must contain a non-empty reference list")
        expected_keys = {
            "artifact_reference_id",
            "owner_type",
            "owner_id",
            "role",
            "artifact_id",
            "state",
            "created_at",
            "released_at",
        }
        references: list[ArtifactReference] = []
        semantic_keys: set[tuple[str, str, str, str]] = set()
        for value in values:
            if not isinstance(value, Mapping) or set(value) != expected_keys:
                raise ArtifactCollision("promotion intent reference shape is invalid")
            reference = ArtifactReference(
                reference_id=str(value["artifact_reference_id"]),
                owner_id=str(value["owner_id"]),
                artifact_id=str(value["artifact_id"]),
                role=str(value["role"]),
                created_at=_parse_time(str(value["created_at"])),
                state=str(value["state"]),
                released_at=None,
            )
            if (
                reference.state != "ACTIVE"
                or value["released_at"] is not None
                or str(value["owner_type"]) != _owner_type(reference)
                or reference.artifact_id != str(row["artifact_id"])
            ):
                raise ArtifactCollision("promotion intent reference is not authorized")
            semantic_key = (
                str(value["owner_type"]),
                reference.owner_id,
                reference.role,
                reference.artifact_id,
            )
            if semantic_key in semantic_keys:
                raise ArtifactCollision("promotion intent contains duplicate references")
            semantic_keys.add(semantic_key)
            references.append(reference)
        return tuple(references)

    def _catalog_commit(self, row: Mapping[str, Any]) -> None:
        # Re-validate all content-addressed fields immediately before the
        # Catalog boundary.  A durable intent is recovery evidence, not
        # permission to redirect publication to a mutated storage key.
        descriptor = self._validate_intent(row)
        references = self._references_from_intent(row)
        publication = ArtifactPublication(descriptor, references)
        connection = self._connection()
        uow = SQLiteUnitOfWork(
            connection,
            TransactionMode.PUBLISH,
            publish_callbacks=_NoopPublishCallbacks(),
        )
        try:
            uow.begin()
            SQLiteArtifactPublicationPort(uow).publish(
                publication,
                promotion_intent_id=str(row["promotion_intent_id"]),
            )
            uow.commit()
        finally:
            if uow.active:
                uow.rollback()
            connection.close()

    def _fail_intent(self, row: Mapping[str, Any], error_code: str, phase: str) -> None:
        intent_id = str(row["promotion_intent_id"])
        state = str(row["state"])
        if state not in {"FINALIZED", "FAILED"}:
            try:
                self._transition(
                    intent_id,
                    expected_state=state,
                    expected_version=int(row["state_version"]),
                    target_state="FAILED",
                    last_error_code=error_code,
                    last_error_detail_artifact_id=str(row["artifact_id"]),
                )
            except Exception:
                pass
        self._record_error(
            intent_id=intent_id,
            artifact_id=str(row["artifact_id"]),
            phase=phase,
            error_code=error_code,
            observed_state={"state": state, "state_version": int(row["state_version"])},
        )

    def _intent_for_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        connection = self._connection(read_only=True)
        try:
            row = connection.execute(
                """
                SELECT * FROM artifact_promotion_intent
                WHERE artifact_id=?
                ORDER BY CASE WHEN state IN (
                    'STAGED_SYNCED','FINAL_PRESENT','CATALOG_COMMITTED','CLEANUP_PENDING'
                ) THEN 0 ELSE 1 END,
                updated_at DESC, promotion_intent_id DESC LIMIT 1
                """,
                (artifact_id,),
            ).fetchone()
            return None if row is None else dict(row)
        finally:
            connection.close()

    def _prepared_from_intent(self, row: Mapping[str, Any]) -> PreparedArtifactPublication:
        return PreparedArtifactPublication(
            str(row["promotion_intent_id"]),
            StagingReceipt(
                str(row["staging_token"]),
                str(row["expected_sha256"]),
                int(row["expected_byte_size"]),
                _parse_time(str(row["created_at"])),
            ),
            self._references_from_intent(row),
        )

    def _promote_intent_stage(self, row: Mapping[str, Any]) -> dict[str, Any]:
        descriptor = self._validate_intent(row)
        self.store.verify_staged(
            str(row["staging_token"]),
            expected_sha256=str(row["expected_sha256"]),
            expected_byte_size=int(row["expected_byte_size"]),
            media_type=descriptor.media_type,
            role=descriptor.role,
        )
        self.store.promote_staged(
            str(row["staging_token"]),
            promotion_intent_id=str(row["promotion_intent_id"]),
            expected_sha256=str(row["expected_sha256"]),
            expected_byte_size=int(row["expected_byte_size"]),
            media_type=descriptor.media_type,
            role=descriptor.role,
            provenance_entity_id=descriptor.provenance_entity_id,
            schema_fingerprint=descriptor.schema_fingerprint,
            semantic_fingerprint=descriptor.semantic_fingerprint,
            published_at=descriptor.published_at,
        )
        current = self._read_intent(str(row["promotion_intent_id"]))
        if current is None:
            raise StagingNotFound("promotion intent disappeared during reconciliation")
        if str(current["state"]) == "STAGED_SYNCED":
            return self._transition(
                str(current["promotion_intent_id"]),
                expected_state="STAGED_SYNCED",
                expected_version=int(current["state_version"]),
                target_state="FINAL_PRESENT",
            )
        return current

    def _ensure_reconciled_bytes(self, row: Mapping[str, Any]) -> None:
        artifact_id = str(row["artifact_id"])
        descriptor = self._validate_intent(row)
        final_conflict = False
        promoting_entry = (
            f"{row['expected_sha256']}.promoting.{row['promotion_intent_id']}"
        )
        promoting_observed: tuple[str, int] | None = None
        try:
            promoting_observed = self.store.verify_promoting_entry(promoting_entry)
        except StagingNotFound:
            pass
        except (ArtifactCollision, IntegrityMismatch) as exc:
            # A stale or corrupted promoting remnant is not a recovery source,
            # but it must not be silently left in the content namespace.
            try:
                self._record_error(
                    intent_id=str(row["promotion_intent_id"]),
                    artifact_id=artifact_id,
                    phase="RECONCILIATION",
                    error_code="ARTIFACT_PROMOTING_BYTES_INVALID",
                    observed_state={"promoting_entry": promoting_entry, "error": str(exc)},
                )
                self.store.isolate_promoting_entry(
                    promoting_entry, reason="promotion-remnant-invalid"
                )
            except Exception:
                pass
        try:
            self.store.verify_final_bytes(
                artifact_id, expected_byte_size=int(row["expected_byte_size"])
            )
            if promoting_observed is not None:
                # A crash after a successful rename can leave the temporary
                # entry visible on some filesystems.  The final is already
                # verified, so only remove a matching remnant.
                self.store.recover_promoting_entry(promoting_entry)
            return
        except StagingNotFound:
            pass
        except (ArtifactCollision, IntegrityMismatch):
            final_conflict = True

        if promoting_observed is not None:
            if final_conflict:
                # The valid promoting copy is the only trusted recovery
                # source; isolate the conflicting final before replacing it.
                self.store.isolate_final_bytes(
                    artifact_id, reason="promotion-collision-promoting-source"
                )
            self.store.recover_promoting_entry(promoting_entry)
            self.store.verify_final_bytes(
                artifact_id, expected_byte_size=int(row["expected_byte_size"])
            )
            return

        stage = self.store.staging_path(str(row["staging_token"]))
        stage_entry_exists = False
        try:
            stage.lstat()
            stage_entry_exists = True
        except FileNotFoundError:
            pass
        if not stage_entry_exists:
            if final_conflict:
                self._record_error(
                    intent_id=str(row["promotion_intent_id"]),
                    artifact_id=artifact_id,
                    phase="RECONCILIATION",
                    error_code="ARTIFACT_CONTENT_ADDRESS_COLLISION_OR_CORRUPTION",
                    observed_state={"final": "wrong", "stage": "missing"},
                )
                self.store.isolate_final_bytes(
                    artifact_id, reason="promotion-collision-no-stage"
                )
            raise _PublishedBytesUnavailable(
                f"admitted Artifact bytes are unavailable: {artifact_id}"
            )

        # Validate the recovery source before moving a conflicting final file;
        # otherwise a bad stage could destroy the only reviewable evidence.
        self.store.verify_staged(
            str(row["staging_token"]),
            expected_sha256=str(row["expected_sha256"]),
            expected_byte_size=int(row["expected_byte_size"]),
            media_type=descriptor.media_type,
            role=descriptor.role,
        )
        if final_conflict:
            self._record_error(
                intent_id=str(row["promotion_intent_id"]),
                artifact_id=artifact_id,
                phase="RECONCILIATION",
                error_code="ARTIFACT_CONTENT_ADDRESS_COLLISION_OR_CORRUPTION",
                observed_state={"final": "wrong", "stage": "correct"},
            )
            self.store.isolate_final_bytes(artifact_id, reason="promotion-collision")
        self._promote_intent_stage(row)
        self.store.verify_final_bytes(
            artifact_id, expected_byte_size=int(row["expected_byte_size"])
        )

    def _ensure_catalog_boundary(self, row: Mapping[str, Any]) -> dict[str, Any]:
        current = self._read_intent(str(row["promotion_intent_id"]))
        if current is None:
            raise StagingNotFound("promotion intent disappeared during reconciliation")
        if str(current["state"]) == "STAGED_SYNCED":
            current = self._transition(
                str(current["promotion_intent_id"]),
                expected_state="STAGED_SYNCED",
                expected_version=int(current["state_version"]),
                target_state="FINAL_PRESENT",
            )
        if str(current["state"]) not in {
            "FINAL_PRESENT",
            "CATALOG_COMMITTED",
            "CLEANUP_PENDING",
            "FINALIZED",
        }:
            raise ArtifactError("promotion intent is not at the Catalog boundary")
        return current

    def _reconcile_published_integrity(
        self,
        *,
        limit: int,
        after_artifact_id: str | None = None,
    ) -> dict[str, Any]:
        """Boundedly verify Catalog PUBLISHED rows, including FINALIZED intents.

        The promotion-intent scan intentionally excludes terminal FINALIZED
        rows.  A separate Catalog-led scan is therefore required to detect a
        later missing, replaced, or non-regular final entry; otherwise startup
        would incorrectly treat a damaged published Artifact as healthy.
        """

        if after_artifact_id is not None:
            try:
                self.store.final_path(after_artifact_id)
            except Exception as exc:
                raise ValueError("published Artifact cursor is invalid") from exc
        connection = self._connection(read_only=True)
        try:
            if after_artifact_id is None:
                rows = tuple(
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM artifact WHERE state='PUBLISHED' "
                        "ORDER BY artifact_id LIMIT ?",
                        (limit + 1,),
                    )
                )
            else:
                rows = tuple(
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM artifact WHERE state='PUBLISHED' "
                        "AND artifact_id>? ORDER BY artifact_id LIMIT ?",
                        (after_artifact_id, limit + 1),
                    )
                )
        finally:
            connection.close()
        selected = rows[:limit]
        summary = {
            "published_artifacts_seen": len(selected),
            "published_artifacts_repaired": 0,
            "published_artifacts_unavailable": 0,
            "published_artifact_next_cursor": (
                None
                if len(rows) <= limit or not selected
                else str(selected[-1]["artifact_id"])
            ),
            "published_artifact_scan_blocked": False,
        }
        for catalog in selected:
            artifact_id = str(catalog["artifact_id"])
            intent = self._intent_for_artifact(artifact_id)
            try:
                self.store.verify_final_bytes(
                    artifact_id, expected_byte_size=int(catalog["byte_size"])
                )
                try:
                    self._resolve_storage_errors(artifact_id=artifact_id)
                except Exception as exc:
                    self._record_error(
                        intent_id=None
                        if intent is None
                        else str(intent["promotion_intent_id"]),
                        artifact_id=artifact_id,
                        phase="RECONCILIATION",
                        error_code="ARTIFACT_PROMOTION_RECONCILIATION_REQUIRED",
                        observed_state={"error": str(exc)},
                    )
                    summary["published_artifacts_unavailable"] += 1
                continue
            except Exception as initial_exc:
                failure = initial_exc

            repaired = False
            if intent is not None and str(intent["state"]) in _OPEN_INTENT_STATES:
                try:
                    descriptor = self._validate_intent(intent)
                    if not self._catalog_metadata_matches(catalog, descriptor):
                        raise ArtifactCollision(
                            "Catalog metadata conflicts with the promotion intent"
                        )
                    self._ensure_reconciled_bytes(intent)
                    self.store.verify_final_bytes(
                        artifact_id, expected_byte_size=int(catalog["byte_size"])
                    )
                    self._resolve_storage_errors(artifact_id=artifact_id)
                    summary["published_artifacts_repaired"] += 1
                    repaired = True
                except Exception as exc:
                    failure = exc
            if repaired:
                continue

            error_code = (
                "ARTIFACT_CONTENT_ADDRESS_COLLISION_OR_CORRUPTION"
                if isinstance(failure, (ArtifactCollision, IntegrityMismatch))
                else "PUBLISHED_BYTES_UNAVAILABLE"
            )
            quarantine_key = None
            isolate_final = isinstance(failure, ArtifactCollision)
            if isinstance(failure, IntegrityMismatch):
                # A byte-size-only Catalog mismatch must preserve bytes that
                # still hash to the Artifact ID; a non-regular final entry
                # remains eligible for safe entry-level isolation.
                try:
                    self.store.verify_final_bytes(artifact_id)
                except (ArtifactCollision, IntegrityMismatch):
                    isolate_final = True
            if isolate_final:
                try:
                    quarantine_key = self.store.isolate_final_bytes(
                        artifact_id, reason="published-integrity-failure"
                    )
                except Exception as isolate_exc:
                    failure = RuntimeError(f"{failure}; isolation failed: {isolate_exc}")
            try:
                self._record_error(
                    intent_id=(
                        None
                        if intent is None
                        else str(intent["promotion_intent_id"])
                    ),
                    artifact_id=artifact_id,
                    phase="RECONCILIATION",
                    error_code=error_code,
                    observed_state={
                        "catalog_state": str(catalog["state"]),
                        "intent_state": None
                        if intent is None
                        else str(intent["state"]),
                        "error": str(failure),
                        "quarantine_storage_key": quarantine_key,
                    },
                )
            except Exception:
                pass
            summary["published_artifacts_unavailable"] += 1
        return summary

    def _reconcile_orphans(
        self,
        *,
        limit: int,
        after_stage_token: str | None = None,
        after_promoting_entry_name: str | None = None,
        after_final_artifact_id: str | None = None,
    ) -> dict[str, Any]:
        stage_scan_blocked = False
        after_stage_entry_name = None
        if after_stage_token is not None:
            # A canonical token cursor is represented by its on-disk name;
            # malformed namespace entries use their raw entry name so the
            # bounded scan cannot skip names between ``entry`` and
            # ``entry.stage``.
            try:
                self.store.staging_path(after_stage_token)
            except StagingNotFound:
                after_stage_entry_name = after_stage_token
            else:
                after_stage_entry_name = after_stage_token + ".stage"
        try:
            stage_scan = self.store.iter_staging_entries(
                limit=limit + 1, after_entry_name=after_stage_entry_name
            )
        except ArtifactScanLimitExceeded as exc:
            stage_scan = ()
            stage_scan_blocked = True
            try:
                self._record_error(
                    intent_id=None,
                    artifact_id=None,
                    phase="RECONCILIATION",
                    error_code="ARTIFACT_ORPHAN_SCAN_LIMIT_EXCEEDED",
                    observed_state={"namespace": "staging", "error": str(exc)},
                )
            except Exception:
                pass
        stage_rows = stage_scan[:limit]
        promoting_scan_blocked = False
        try:
            promoting_scan = self.store.iter_promoting_entries(
                limit=limit + 1, after_entry_name=after_promoting_entry_name
            )
        except ArtifactScanLimitExceeded as exc:
            promoting_scan = ()
            promoting_scan_blocked = True
            try:
                self._record_error(
                    intent_id=None,
                    artifact_id=None,
                    phase="RECONCILIATION",
                    error_code="ARTIFACT_ORPHAN_SCAN_LIMIT_EXCEEDED",
                    observed_state={"namespace": "promoting", "error": str(exc)},
                )
            except Exception:
                pass
        promoting_rows = promoting_scan[:limit]
        final_scan_blocked = False
        try:
            final_scan = self.store.iter_final_artifact_ids(
                limit=limit + 1, after_artifact_id=after_final_artifact_id
            )
        except ArtifactScanLimitExceeded as exc:
            final_scan = ()
            final_scan_blocked = True
            try:
                self._record_error(
                    intent_id=None,
                    artifact_id=None,
                    phase="RECONCILIATION",
                    error_code="ARTIFACT_ORPHAN_SCAN_LIMIT_EXCEEDED",
                    observed_state={"namespace": "final", "error": str(exc)},
                )
            except Exception:
                pass
        final_rows = final_scan[:limit]
        restore_connection = self._connection(read_only=True)
        try:
            # RESTORED is a durable restore intent.  Its Catalog Artifact row
            # remains QUARANTINED until the final-byte move is committed, so a
            # valid final entry must not be classified as an orphan during
            # that crash window.
            restore_intent_ids = frozenset(
                str(row[0])
                for row in restore_connection.execute(
                    """
                    SELECT DISTINCT artifact_id
                    FROM artifact_quarantine
                    WHERE state='RESTORED'
                    """
                )
            )
        finally:
            restore_connection.close()
        summary = {
            "orphan_stages_seen": 0,
            "orphan_stages_quarantined": 0,
            "orphan_stages_failed": 0,
            "orphan_stage_next_cursor": (
                None
                if len(stage_scan) <= limit or not stage_rows
                else self._orphan_stage_cursor(stage_rows[-1])
            ),
            "orphan_stage_scan_blocked": stage_scan_blocked,
            "orphan_promoting_bytes_seen": 0,
            "orphan_promoting_bytes_isolated": 0,
            "orphan_promoting_bytes_failed": 0,
            "orphan_promoting_next_cursor": (
                None
                if len(promoting_scan) <= limit or not promoting_rows
                else str(promoting_rows[-1])
            ),
            "orphan_promoting_scan_blocked": promoting_scan_blocked,
            "orphan_final_bytes_seen": 0,
            "orphan_final_bytes_isolated": 0,
            "orphan_final_bytes_failed": 0,
            "orphan_final_next_cursor": (
                None
                if len(final_scan) <= limit or not final_rows
                else str(final_rows[-1])
            ),
            "orphan_final_scan_blocked": final_scan_blocked,
        }
        for entry_name in stage_rows:
            token = entry_name[: -len(".stage")] if entry_name.endswith(".stage") else None
            if token is not None:
                try:
                    self.store.staging_path(token)
                except StagingNotFound:
                    token = None
            intent = None if token is None else self._intent_by_stage(token)
            if intent is not None:
                continue
            summary["orphan_stages_seen"] += 1
            observed_artifact_id = None
            receipt_error = None
            if token is not None:
                try:
                    receipt = self.store.staging_receipt(token)
                    observed_artifact_id = "art_sha256_" + receipt.sha256
                except Exception as exc:
                    receipt_error = str(exc)
            try:
                quarantine_key = self.store.quarantine_orphan_stage_entry(entry_name)
                self._record_error(
                    intent_id=None,
                    artifact_id=observed_artifact_id,
                    phase="RECONCILIATION",
                    error_code="ARTIFACT_ORPHAN_STAGE_QUARANTINED",
                    observed_state={
                        "staging_entry": entry_name,
                        "staging_token": token,
                        "receipt_error": receipt_error,
                        "quarantine_storage_key": quarantine_key,
                    },
                )
                summary["orphan_stages_quarantined"] += 1
            except Exception as exc:
                summary["orphan_stages_failed"] += 1
                try:
                    self._record_error(
                        intent_id=None,
                        artifact_id=observed_artifact_id,
                        phase="RECONCILIATION",
                        error_code="ARTIFACT_ORPHAN_STAGE_RECONCILIATION_REQUIRED",
                        observed_state={"staging_entry": entry_name, "error": str(exc)},
                    )
                except Exception:
                    pass
        for entry_name in promoting_rows:
            summary["orphan_promoting_bytes_seen"] += 1
            try:
                artifact_id, intent_id = self.store.promoting_entry_identity(entry_name)
            except Exception as exc:
                summary["orphan_promoting_bytes_failed"] += 1
                try:
                    self._record_error(
                        intent_id=None,
                        artifact_id=None,
                        phase="RECONCILIATION",
                        error_code="ARTIFACT_ORPHAN_PROMOTING_RECONCILIATION_REQUIRED",
                        observed_state={"promoting_entry": entry_name, "error": str(exc)},
                    )
                except Exception:
                    pass
                continue
            intent = self._read_intent(intent_id)
            if (
                intent is not None
                and str(intent["artifact_id"]) == artifact_id
                and str(intent["state"]) in _OPEN_INTENT_STATES
            ):
                continue
            try:
                quarantine_key = self.store.isolate_promoting_entry(
                    entry_name, reason="unadmitted-promotion"
                )
                self._record_error(
                    intent_id=intent_id if intent is not None else None,
                    artifact_id=artifact_id,
                    phase="RECONCILIATION",
                    error_code="ARTIFACT_ORPHAN_PROMOTING_ISOLATED",
                    observed_state={
                        "promoting_entry": entry_name,
                        "intent_state": None if intent is None else str(intent["state"]),
                        "quarantine_storage_key": quarantine_key,
                    },
                )
                summary["orphan_promoting_bytes_isolated"] += 1
            except Exception as exc:
                summary["orphan_promoting_bytes_failed"] += 1
                try:
                    self._record_error(
                        intent_id=intent_id if intent is not None else None,
                        artifact_id=artifact_id,
                        phase="RECONCILIATION",
                        error_code="ARTIFACT_ORPHAN_PROMOTING_RECONCILIATION_REQUIRED",
                        observed_state={"promoting_entry": entry_name, "error": str(exc)},
                    )
                except Exception:
                    pass
        for artifact_id in final_rows:
            summary["orphan_final_bytes_seen"] += 1
            catalog = self._read_catalog_artifact(artifact_id)
            intent = self._intent_for_artifact(artifact_id)
            if catalog is not None and str(catalog["state"]) == "PUBLISHED":
                continue
            if artifact_id in restore_intent_ids:
                continue
            if intent is not None and str(intent["state"]) in _OPEN_INTENT_STATES:
                continue
            try:
                quarantine_key = self.store.isolate_final_bytes(
                    artifact_id, reason="unadmitted-final"
                )
                self._record_error(
                    intent_id=None if intent is None else str(intent["promotion_intent_id"]),
                    artifact_id=artifact_id,
                    phase="RECONCILIATION",
                    error_code="ARTIFACT_ORPHAN_FINAL_ISOLATED",
                    observed_state={
                        "catalog_state": None if catalog is None else str(catalog["state"]),
                        "intent_state": None if intent is None else str(intent["state"]),
                        "quarantine_storage_key": quarantine_key,
                    },
                )
                summary["orphan_final_bytes_isolated"] += 1
            except Exception as exc:
                summary["orphan_final_bytes_failed"] += 1
                try:
                    self._record_error(
                        intent_id=None if intent is None else str(intent["promotion_intent_id"]),
                        artifact_id=artifact_id,
                        phase="RECONCILIATION",
                        error_code="ARTIFACT_ORPHAN_FINAL_RECONCILIATION_REQUIRED",
                        observed_state={"error": str(exc)},
                    )
                except Exception:
                    pass
        return summary

    def _orphan_stage_cursor(self, entry_name: str) -> str:
        if not entry_name.endswith(".stage"):
            return entry_name
        token = entry_name[: -len(".stage")]
        try:
            self.store.staging_path(token)
        except StagingNotFound:
            return entry_name
        return token

    @_namespace_locked
    def reconcile(
        self,
        *,
        limit: int = 256,
        after_promotion_intent_id: str | None = None,
        after_orphan_stage_token: str | None = None,
        after_orphan_promoting_entry_name: str | None = None,
        after_orphan_final_artifact_id: str | None = None,
        after_published_artifact_id: str | None = None,
    ) -> dict[str, Any]:
        """Recover at most ``limit`` intents and bounded orphan scans."""

        if not 1 <= limit <= 1_000:
            raise ValueError("reconcile limit must be between 1 and 1000")
        if after_promotion_intent_id is not None and not after_promotion_intent_id:
            raise ValueError("promotion intent cursor must not be empty")
        connection = self._connection(read_only=True)
        try:
            # Terminal FAILED intents are retained as evidence and must not
            # consume the bounded cursor ahead of recoverable work.  A
            # restart reconciles only states that can still advance.
            where = "state IN ('STAGED_SYNCED','FINAL_PRESENT','CATALOG_COMMITTED','CLEANUP_PENDING')"
            parameters: list[Any] = []
            if after_promotion_intent_id is not None:
                where += " AND promotion_intent_id>?"
                parameters.append(after_promotion_intent_id)
            parameters.append(limit + 1)
            rows = tuple(
                dict(row)
                for row in connection.execute(
                    f"SELECT * FROM artifact_promotion_intent WHERE {where} "
                    "ORDER BY promotion_intent_id LIMIT ?",
                    tuple(parameters),
                )
            )
        finally:
            connection.close()
        intent_rows = rows[:limit]
        summary = {
            "promotion_intents_seen": len(intent_rows),
            "promotion_finalized": 0,
            "promotion_failed": 0,
            "promotion_bytes_unavailable": 0,
            "promotion_next_cursor": (
                None
                if len(rows) <= limit or not intent_rows
                else str(intent_rows[-1]["promotion_intent_id"])
            ),
        }
        for row in intent_rows:
            artifact_id = str(row["artifact_id"])
            try:
                catalog = self._read_catalog_artifact(artifact_id)
                descriptor = self._validate_intent(row)
                if catalog is not None:
                    if str(catalog["state"]) != "PUBLISHED":
                        self._fail_intent(row, "ARTIFACT_METADATA_CONFLICT", "CATALOG")
                        summary["promotion_failed"] += 1
                        continue
                    if not self._catalog_metadata_matches(catalog, descriptor):
                        self._fail_intent(row, "ARTIFACT_METADATA_CONFLICT", "CATALOG")
                        summary["promotion_failed"] += 1
                        continue
                self._ensure_reconciled_bytes(row)
                current = self._ensure_catalog_boundary(row)
                # The intent may enter CATALOG_COMMITTED only from the same
                # PUBLISH UoW that writes the Artifact row and references. A
                # reconciliation process therefore commits the Catalog while
                # the intent is FINAL_PRESENT; it must not advance that state
                # in a separate transaction first.
                if str(current["state"]) == "FINAL_PRESENT" or (
                    catalog is None
                    and str(current["state"])
                    in {"CATALOG_COMMITTED", "CLEANUP_PENDING"}
                ):
                    self._catalog_commit(current)
                    current = self._read_intent(str(row["promotion_intent_id"])) or current
                if str(current["state"]) in {"CATALOG_COMMITTED", "CLEANUP_PENDING"}:
                    self.finalize(self._prepared_from_intent(current))
                elif str(current["state"]) != "FINALIZED":
                    raise ArtifactError("promotion intent did not reach FINALIZED")
                summary["promotion_finalized"] += 1
            except _PublishedBytesUnavailable:
                self._fail_intent(row, "PUBLISHED_BYTES_UNAVAILABLE", "RECONCILIATION")
                summary["promotion_failed"] += 1
                summary["promotion_bytes_unavailable"] += 1
            except (ArtifactCollision, IntegrityMismatch):
                self._fail_intent(
                    row,
                    "ARTIFACT_CONTENT_ADDRESS_COLLISION_OR_CORRUPTION",
                    "RECONCILIATION",
                )
                summary["promotion_failed"] += 1
            except Exception as exc:
                try:
                    self._record_error(
                        intent_id=str(row["promotion_intent_id"]),
                        artifact_id=artifact_id,
                        phase="RECONCILIATION",
                        error_code="ARTIFACT_PROMOTION_RECONCILIATION_REQUIRED",
                        observed_state={"state": str(row["state"]), "error": str(exc)},
                    )
                except Exception:
                    pass
                summary["promotion_failed"] += 1
        summary.update(
            self._reconcile_published_integrity(
                limit=limit,
                after_artifact_id=after_published_artifact_id,
            )
        )
        summary.update(
            self._reconcile_orphans(
                limit=limit,
                after_stage_token=after_orphan_stage_token,
                after_promoting_entry_name=after_orphan_promoting_entry_name,
                after_final_artifact_id=after_orphan_final_artifact_id,
            )
        )
        return summary

    def _read_intent(self, intent_id: str) -> dict[str, Any] | None:
        connection = self._connection(read_only=True)
        try:
            row = connection.execute(
                "SELECT * FROM artifact_promotion_intent WHERE promotion_intent_id=?",
                (intent_id,),
            ).fetchone()
            return None if row is None else dict(row)
        finally:
            connection.close()

    def _read_catalog_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        connection = self._connection(read_only=True)
        try:
            row = connection.execute("SELECT * FROM artifact WHERE artifact_id=?", (artifact_id,)).fetchone()
            return None if row is None else dict(row)
        finally:
            connection.close()

    @staticmethod
    def _catalog_metadata_matches(row: Mapping[str, Any], descriptor: ArtifactDescriptor) -> bool:
        expected = {
            "artifact_id": descriptor.artifact_id,
            "sha256": descriptor.sha256,
            "byte_size": descriptor.byte_size,
            "media_type": descriptor.media_type,
            "semantic_role": descriptor.role,
            "storage_key": descriptor.storage_key,
            "safe_format_id": descriptor.safe_format_id,
            "schema_fingerprint": descriptor.schema_fingerprint,
            "state": "PUBLISHED",
        }
        return all(row.get(key) == value for key, value in expected.items())

    # -- two-phase garbage collection --------------------------------------

    @_namespace_locked
    def _current_gc_snapshot(
        self,
        scope_owner_id: str | None = None,
        *,
        exclude_artifact_ids: frozenset[str] = frozenset(),
    ) -> tuple[str, tuple[str, ...], frozenset[str], frozenset[str], frozenset[str]]:
        """Read one bounded-consistency GC snapshot from Catalog and storage."""

        connection = self._connection(read_only=True)
        try:
            reference_rows = tuple(
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM artifact_reference WHERE state='ACTIVE' "
                    "ORDER BY artifact_reference_id"
                )
            )
            references = tuple(
                ArtifactReference(
                    reference_id=str(row["artifact_reference_id"]),
                    owner_id=str(row["owner_id"]),
                    artifact_id=str(row["artifact_id"]),
                    role=str(row["role"]),
                    created_at=_parse_time(str(row["created_at"])),
                    state="ACTIVE",
                    released_at=None,
                )
                for row in reference_rows
                if str(row["artifact_id"]) not in exclude_artifact_ids
            )
            roots = tuple(
                sorted(
                    {scope_owner_id} | {reference.owner_id for reference in references}
                    if scope_owner_id is not None
                    else {reference.owner_id for reference in references}
                )
            )
            if not roots:
                roots = ("__gc_global_root__",)
            fingerprint = ReachabilityGraph(roots, references).fingerprint()
            open_rows = tuple(
                connection.execute(
                    """
                    SELECT promotion_intent_id, artifact_id FROM artifact_promotion_intent
                    WHERE state IN ('STAGED_SYNCED','FINAL_PRESENT','CATALOG_COMMITTED','CLEANUP_PENDING')
                    ORDER BY promotion_intent_id
                    """
                )
            )
            graph = ReachabilityGraph(roots, references)
            reachable = graph.reachable_artifacts()
            open_intents = frozenset(str(row[1]) for row in open_rows)
            open_intent_ids = tuple(str(row[0]) for row in open_rows)
        finally:
            connection.close()
        try:
            staged_entries = self.store.iter_staging_entries(limit=10_000)
        except ArtifactScanLimitExceeded as exc:
            raise GarbageCollectionSafetyError(
                "GC staging scan exceeded the bounded limit"
            ) from exc
        staged_receipts: list[StagingReceipt] = []
        for entry_name in staged_entries:
            if not entry_name.endswith(".stage"):
                raise GarbageCollectionSafetyError(
                    f"GC staging namespace contains an unexpected entry: {entry_name}"
                )
            token = entry_name[: -len(".stage")]
            try:
                self.store.staging_path(token)
            except StagingNotFound as exc:
                raise GarbageCollectionSafetyError(
                    f"GC staging namespace contains an invalid entry: {entry_name}"
                ) from exc
            try:
                staged_receipts.append(self.store.staging_receipt(token))
            except Exception as exc:
                raise GarbageCollectionSafetyError(
                    f"GC staging entry is not verifiably readable: {entry_name}"
                ) from exc
        staged = frozenset(
            "art_sha256_" + receipt.sha256 for receipt in staged_receipts
        )
        return fingerprint, open_intent_ids, reachable, open_intents, staged

    def current_gc_guard(self) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
        """Return active, open-intent, and staged Artifact identities."""

        _, _, reachable, open_intents, staged = self._current_gc_snapshot()
        return reachable, open_intents, staged

    def _validate_gc_plan_items_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        phase: str,
        plan_artifact_id: str,
        items: Sequence[GarbageCollectionItem],
        expected_state: str | None = None,
        check_state: bool = True,
    ) -> None:
        """Bind every destructive candidate to the current Catalog row.

        The plan Artifact is immutable, but the candidate Catalog rows remain
        mutable until the execution barrier.  A newly created batch must not
        record caller-supplied byte size, timestamp, or storage-key metadata
        that differs from the row it may later quarantine or purge.  The
        execution-time checks still recheck reachability and quarantine state;
        this admission check closes the initial plan-to-batch metadata gap.
        """

        catalog_state = expected_state
        if check_state and catalog_state is None:
            catalog_state = "PUBLISHED" if phase == "QUARANTINE" else "QUARANTINED"
        exact_ids = tuple(item.artifact_id for item in items)
        if plan_artifact_id in exact_ids:
            raise GarbageCollectionSafetyError(
                "GC plan Artifact cannot also be a destructive candidate"
            )
        if not exact_ids:
            return
        placeholders = ",".join("?" for _ in exact_ids)
        rows = tuple(
            dict(row)
            for row in connection.execute(
                f"SELECT * FROM artifact WHERE artifact_id IN ({placeholders})",
                exact_ids,
            )
        )
        by_artifact = {str(row["artifact_id"]): row for row in rows}
        if set(by_artifact) != set(exact_ids):
            missing = sorted(set(exact_ids) - set(by_artifact))
            raise GarbageCollectionSafetyError(
                "GC plan references an Artifact missing from the Catalog: "
                + ", ".join(missing)
            )
        for item in items:
            row = by_artifact[item.artifact_id]
            expected_sha256 = item.artifact_id.removeprefix("art_sha256_")
            if catalog_state is not None and str(row.get("state")) != catalog_state:
                raise GarbageCollectionSafetyError(
                    f"GC plan Artifact is not currently {catalog_state}: {item.artifact_id}"
                )
            if str(row.get("sha256")) != expected_sha256:
                raise GarbageCollectionSafetyError(
                    f"GC plan SHA-256 does not match Catalog identity: {item.artifact_id}"
                )
            try:
                catalog_byte_size = int(row["byte_size"])
            except (TypeError, ValueError) as exc:
                raise GarbageCollectionSafetyError(
                    f"GC plan Catalog byte size is invalid: {item.artifact_id}"
                ) from exc
            if catalog_byte_size != item.byte_size:
                raise GarbageCollectionSafetyError(
                    f"GC plan byte size does not match the Catalog: {item.artifact_id}"
                )
            if row.get("published_at") is None or str(row["published_at"]) != _wire_time(
                item.published_at
            ):
                raise GarbageCollectionSafetyError(
                    f"GC plan publication timestamp does not match the Catalog: {item.artifact_id}"
                )
            if str(row.get("storage_key")) != item.storage_key:
                raise GarbageCollectionSafetyError(
                    f"GC plan storage key does not match the Catalog: {item.artifact_id}"
                )

    @staticmethod
    def _is_lower_hex_digest(value: Any) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and value == value.lower()
            and all(character in "0123456789abcdef" for character in value)
        )

    def _validate_gc_plan_in_transaction(
        self,
        connection: sqlite3.Connection,
        row: Mapping[str, Any],
        *,
        expected_catalog_state: str | None,
    ) -> tuple[GarbageCollectionItem, ...]:
        """Verify the immutable plan Artifact and bind its items to Catalog rows.

        A GC batch stores a compact copy of the plan identity, but that copy is
        not a substitute for the content-addressed plan bytes.  Every later
        execution boundary re-reads the plan Artifact and checks the current
        Catalog rows under the same SQLite write transaction.  This keeps a
        hand-edited batch, a stale confirmation, or a metadata race from
        turning caller-supplied plan fields into deletion authority.
        """

        plan_artifact_id = str(row.get("plan_artifact_id", ""))
        try:
            expected_plan_sha256 = sha256_from_artifact_id(plan_artifact_id)
            expected_plan_storage_key = storage_key_for_sha256(expected_plan_sha256)
        except Exception as exc:
            raise GarbageCollectionSafetyError(
                "GC plan Artifact identity is not canonical"
            ) from exc
        plan_row = connection.execute(
            "SELECT * FROM artifact WHERE artifact_id=?", (plan_artifact_id,)
        ).fetchone()
        if plan_row is None:
            raise GarbageCollectionSafetyError("GC plan Artifact is missing from the Catalog")
        plan_catalog = dict(plan_row)
        expected_plan_fields = {
            "state": "PUBLISHED",
            "sha256": expected_plan_sha256,
            "media_type": "application/json",
            "semantic_role": "GC_PLAN",
            "storage_key": expected_plan_storage_key,
            "safe_format_id": "canonical-json-v1",
            "schema_fingerprint": "urn:v3:artifact-gc-plan:1.0.0",
        }
        if any(plan_catalog.get(key) != value for key, value in expected_plan_fields.items()):
            raise GarbageCollectionSafetyError(
                "GC plan Artifact metadata no longer matches the canonical plan"
            )
        try:
            plan_byte_size = int(plan_catalog["byte_size"])
        except (TypeError, ValueError) as exc:
            raise GarbageCollectionSafetyError("GC plan Artifact byte size is invalid") from exc
        if plan_byte_size < 0 or plan_byte_size > 65_536:
            raise GarbageCollectionSafetyError("GC plan Artifact exceeds the bounded metadata limit")
        try:
            plan_bytes = self.store.read_bytes(
                plan_artifact_id,
                max_bytes=65_536,
            )
        except Exception as exc:
            raise GarbageCollectionSafetyError(
                "GC plan Artifact bytes are not verifiably available"
            ) from exc
        if len(plan_bytes) != plan_byte_size:
            raise GarbageCollectionSafetyError("GC plan Artifact byte size changed")
        try:
            payload = json.loads(plan_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GarbageCollectionSafetyError("GC plan Artifact is not valid JSON") from exc
        if not isinstance(payload, Mapping):
            raise GarbageCollectionSafetyError("GC plan Artifact must be a JSON object")
        if _canonical_text(payload).encode("utf-8") != plan_bytes:
            raise GarbageCollectionSafetyError("GC plan Artifact JSON is not canonical")
        expected_keys = {
            "schema_id",
            "created_at",
            "phase",
            "grace_period_seconds",
            "reachability_fingerprint",
            "exact_artifact_ids_hash",
            "exact_byte_size",
            "expires_at",
            "open_promotion_intent_ids",
            "items",
        }
        if set(payload) != expected_keys:
            raise GarbageCollectionSafetyError("GC plan Artifact fields are not canonical")
        if payload["schema_id"] != "urn:v3:artifact-gc-plan:1.0.0":
            raise GarbageCollectionSafetyError("GC plan Artifact schema is not canonical")
        phase = str(row.get("phase", ""))
        if payload["phase"] != phase or phase not in {"QUARANTINE", "PURGE"}:
            raise GarbageCollectionSafetyError("GC plan phase does not match the durable batch")
        grace_period_seconds = payload["grace_period_seconds"]
        if (
            not isinstance(grace_period_seconds, int)
            or isinstance(grace_period_seconds, bool)
            or grace_period_seconds < 0
        ):
            raise GarbageCollectionSafetyError("GC plan grace period is invalid")
        reachability_fingerprint = payload["reachability_fingerprint"]
        if not self._is_lower_hex_digest(reachability_fingerprint):
            raise GarbageCollectionSafetyError("GC plan reachability fingerprint is invalid")
        if not isinstance(payload["created_at"], str) or not isinstance(
            payload["expires_at"], str
        ):
            raise GarbageCollectionSafetyError("GC plan timestamps are invalid")
        try:
            created_at = _parse_time(payload["created_at"])
            expires_at = _parse_time(payload["expires_at"])
        except Exception as exc:
            raise GarbageCollectionSafetyError("GC plan timestamps are invalid") from exc
        if _wire_time(expires_at) != _wire_time(created_at + timedelta(hours=1)):
            raise GarbageCollectionSafetyError("GC plan expiry is not canonical")
        if str(row.get("created_at")) != _wire_time(created_at):
            raise GarbageCollectionSafetyError("GC batch creation time differs from its plan")
        if str(row.get("expires_at")) != _wire_time(expires_at):
            raise GarbageCollectionSafetyError("GC batch expiry differs from its plan")
        if str(row.get("reachability_fingerprint")) != reachability_fingerprint:
            raise GarbageCollectionSafetyError(
                "GC batch reachability fingerprint differs from its plan"
            )

        raw_open_intent_ids = payload["open_promotion_intent_ids"]
        if not isinstance(raw_open_intent_ids, list) or any(
            not isinstance(value, str) or not value for value in raw_open_intent_ids
        ):
            raise GarbageCollectionSafetyError("GC plan open promotion intents are invalid")
        open_intent_ids = tuple(raw_open_intent_ids)
        if tuple(sorted(open_intent_ids)) != open_intent_ids or len(set(open_intent_ids)) != len(
            open_intent_ids
        ):
            raise GarbageCollectionSafetyError(
                "GC plan open promotion intents are not canonical"
            )
        if str(row.get("open_intent_ids_json")) != _canonical_text(list(open_intent_ids)):
            raise GarbageCollectionSafetyError(
                "GC batch open promotion intents differ from its plan"
            )

        raw_items = payload["items"]
        if not isinstance(raw_items, list):
            raise GarbageCollectionSafetyError("GC plan items must be a JSON array")
        items: list[GarbageCollectionItem] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, Mapping) or set(raw_item) != {
                "artifact_id",
                "byte_size",
                "published_at",
                "storage_key",
            }:
                raise GarbageCollectionSafetyError("GC plan item fields are not canonical")
            if (
                not isinstance(raw_item["artifact_id"], str)
                or not isinstance(raw_item["byte_size"], int)
                or isinstance(raw_item["byte_size"], bool)
                or not isinstance(raw_item["published_at"], str)
                or not isinstance(raw_item["storage_key"], str)
            ):
                raise GarbageCollectionSafetyError("GC plan item is invalid")
            try:
                item = GarbageCollectionItem(
                    artifact_id=raw_item["artifact_id"],
                    byte_size=raw_item["byte_size"],
                    published_at=_parse_time(raw_item["published_at"]),
                    storage_key=raw_item["storage_key"],
                )
            except Exception as exc:
                raise GarbageCollectionSafetyError("GC plan item is invalid") from exc
            if _wire_time(item.published_at) != raw_item["published_at"]:
                raise GarbageCollectionSafetyError("GC plan item timestamp is not canonical")
            items.append(item)
        parsed_items = tuple(items)
        if tuple(sorted(parsed_items, key=lambda item: item.artifact_id)) != parsed_items:
            raise GarbageCollectionSafetyError("GC plan items are not sorted")
        exact_ids = tuple(item.artifact_id for item in parsed_items)
        exact_ids_hash = exact_artifact_ids_hash(exact_ids)
        if payload["exact_artifact_ids_hash"] != exact_ids_hash:
            raise GarbageCollectionSafetyError("GC plan exact ID hash is not canonical")
        if (
            not isinstance(payload["exact_byte_size"], int)
            or isinstance(payload["exact_byte_size"], bool)
            or payload["exact_byte_size"] < 0
        ):
            raise GarbageCollectionSafetyError("GC plan exact byte size is invalid")
        if payload["exact_byte_size"] != sum(item.byte_size for item in parsed_items):
            raise GarbageCollectionSafetyError("GC plan exact byte size is not canonical")
        if str(row.get("exact_artifact_ids_hash")) != exact_ids_hash:
            raise GarbageCollectionSafetyError("GC batch exact ID hash differs from its plan")
        if str(row.get("exact_artifact_ids_json")) != _canonical_text(list(exact_ids)):
            raise GarbageCollectionSafetyError("GC batch exact IDs differ from its plan")
        self._validate_gc_plan_items_in_transaction(
            connection,
            phase=phase,
            plan_artifact_id=plan_artifact_id,
            items=parsed_items,
            expected_state=expected_catalog_state,
            check_state=expected_catalog_state is not None,
        )
        return parsed_items

    def _validate_gc_quarantine_records_in_transaction(
        self,
        connection: sqlite3.Connection,
        row: Mapping[str, Any],
        items: Sequence[GarbageCollectionItem],
        *,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Bind quarantine rows and retention to the exact plan items."""

        if now is not None and (now.tzinfo is None or now.utcoffset() is None):
            raise ValueError("GC execution time must be timezone-aware")
        ids = tuple(item.artifact_id for item in items)
        if not ids:
            return ()
        placeholders = ",".join("?" for _ in ids)
        phase = str(row.get("phase"))
        if phase == "QUARANTINE":
            records = tuple(
                dict(record)
                for record in connection.execute(
                    "SELECT * FROM artifact_quarantine WHERE gc_batch_id=? ORDER BY artifact_id",
                    (str(row["gc_batch_id"]),),
                )
            )
        elif phase == "PURGE":
            records = tuple(
                dict(record)
                for record in connection.execute(
                    f"""
                    SELECT * FROM artifact_quarantine
                    WHERE artifact_id IN ({placeholders}) AND state='QUARANTINED'
                    ORDER BY artifact_id,gc_batch_id
                    """,
                    ids,
                )
            )
        else:
            raise GarbageCollectionSafetyError("unknown GC phase")
        by_artifact: dict[str, dict[str, Any]] = {}
        for record in records:
            artifact_id = str(record.get("artifact_id"))
            if artifact_id not in ids or artifact_id in by_artifact:
                raise GarbageCollectionSafetyError(
                    f"GC quarantine records are ambiguous for {artifact_id}"
                )
            by_artifact[artifact_id] = record
        if set(by_artifact) != set(ids):
            raise GarbageCollectionSafetyError(
                "GC quarantine records do not cover the exact Artifact set"
            )
        item_by_artifact = {item.artifact_id: item for item in items}
        for artifact_id in ids:
            record = by_artifact[artifact_id]
            item = item_by_artifact[artifact_id]
            try:
                _, expected_quarantine_key = self.store.quarantine_path(
                    artifact_id, str(record["gc_batch_id"])
                )
                quarantined_at = _parse_time(str(record["quarantined_at"]))
                purge_not_before = _parse_time(str(record["purge_not_before"]))
            except Exception as exc:
                raise GarbageCollectionSafetyError(
                    f"GC quarantine metadata is invalid for {artifact_id}"
                ) from exc
            if str(record.get("original_storage_key")) != item.storage_key:
                raise GarbageCollectionSafetyError(
                    f"GC quarantine original key differs from the plan for {artifact_id}"
                )
            if str(record.get("quarantine_storage_key")) != expected_quarantine_key:
                raise GarbageCollectionSafetyError(
                    f"GC quarantine destination key is not canonical for {artifact_id}"
                )
            minimum_retention = quarantined_at + timedelta(days=30)
            if purge_not_before < minimum_retention:
                raise GarbageCollectionSafetyError(
                    f"GC quarantine retention metadata is too short for {artifact_id}"
                )
            if phase == "PURGE" and now is not None and now < max(
                purge_not_before, minimum_retention
            ):
                raise GarbageCollectionSafetyError(
                    f"quarantine retention period has not elapsed for {artifact_id}"
                )
            artifact = connection.execute(
                "SELECT state FROM artifact WHERE artifact_id=?", (artifact_id,)
            ).fetchone()
            if artifact is None:
                raise GarbageCollectionSafetyError(f"GC Artifact disappeared: {artifact_id}")
            artifact_state = str(artifact[0])
            record_state = str(record.get("state"))
            if phase == "QUARANTINE":
                if record_state not in {"MOVING", "QUARANTINED"}:
                    raise GarbageCollectionSafetyError(
                        f"GC quarantine record is not recoverable for {artifact_id}"
                    )
                expected_artifact_state = (
                    "PUBLISHED" if record_state == "MOVING" else "QUARANTINED"
                )
                if artifact_state != expected_artifact_state:
                    raise GarbageCollectionSafetyError(
                        f"GC quarantine Catalog state is inconsistent for {artifact_id}"
                    )
            elif artifact_state != "QUARANTINED":
                raise GarbageCollectionSafetyError(
                    f"PURGE Artifact is not QUARANTINED: {artifact_id}"
                )
        return tuple(by_artifact[artifact_id] for artifact_id in ids)

    def _validate_gc_batch_execution_in_transaction(
        self,
        connection: sqlite3.Connection,
        row: Mapping[str, Any],
        *,
        now: datetime | None = None,
        expected_catalog_state: str | None,
        require_quarantine_records: bool,
    ) -> tuple[GarbageCollectionItem, ...]:
        items = self._validate_gc_plan_in_transaction(
            connection,
            row,
            expected_catalog_state=expected_catalog_state,
        )
        if require_quarantine_records:
            self._validate_gc_quarantine_records_in_transaction(
                connection,
                row,
                items,
                now=now,
            )
        return items

    def _assert_no_existing_quarantine_records_in_transaction(
        self,
        connection: sqlite3.Connection,
        row: Mapping[str, Any],
    ) -> None:
        """Do not let a new QUARANTINE batch shadow an existing byte record."""

        ids = self._gc_ids(row)
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        existing = connection.execute(
            f"""
            SELECT artifact_id, gc_batch_id, state
            FROM artifact_quarantine
            WHERE artifact_id IN ({placeholders})
              AND state IN ('MOVING','QUARANTINED','RESTORED')
            ORDER BY artifact_id,gc_batch_id
            LIMIT 1
            """,
            ids,
        ).fetchone()
        if existing is not None:
            raise GarbageCollectionSafetyError(
                "GC target already has an active quarantine record: "
                + str(existing[0])
            )

    @_namespace_locked
    def record_gc_batch(
        self,
        *,
        phase: str,
        scope_owner_id: str,
        plan_artifact_id: str,
        plan: GarbageCollectionPlan,
    ) -> dict[str, Any]:
        if phase not in {"QUARANTINE", "PURGE"} or plan.phase != phase:
            raise ValueError("GC batch phase does not match its plan")
        exact_ids = plan.exact_artifact_ids
        ids_hash = exact_artifact_ids_hash(exact_ids)
        if ids_hash != plan.exact_artifact_ids_hash:
            raise GarbageCollectionSafetyError("GC plan exact ID hash is not canonical")
        plan_bytes = plan.canonical_bytes()
        if len(plan_bytes) > 65_536:
            raise GarbageCollectionSafetyError(
                "GC plan exceeds the bounded Catalog artifact metadata limit"
            )
        if plan_artifact_id != plan.plan_artifact_id:
            raise GarbageCollectionSafetyError(
                "GC plan Artifact ID does not match the canonical plan bytes"
            )
        try:
            expected_plan_sha256 = plan_artifact_id.removeprefix("art_sha256_")
            expected_plan_storage_key = storage_key_for_sha256(expected_plan_sha256)
        except Exception as exc:
            raise GarbageCollectionSafetyError(
                "GC plan Artifact identity is not canonical"
            ) from exc
        connection = self._connection()
        uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
        try:
            uow.begin()
            plan_row = connection.execute(
                "SELECT * FROM artifact WHERE artifact_id=?",
                (plan_artifact_id,),
            ).fetchone()
            if plan_row is None or str(plan_row["state"]) != "PUBLISHED":
                raise GarbageCollectionSafetyError("GC plan Artifact is not PUBLISHED")
            plan_row = dict(plan_row)
            expected_plan_fields = {
                "sha256": expected_plan_sha256,
                "byte_size": len(plan_bytes),
                "media_type": "application/json",
                "semantic_role": "GC_PLAN",
                "storage_key": expected_plan_storage_key,
                "safe_format_id": "canonical-json-v1",
                "schema_fingerprint": "urn:v3:artifact-gc-plan:1.0.0",
            }
            if any(plan_row.get(key) != value for key, value in expected_plan_fields.items()):
                raise GarbageCollectionSafetyError(
                    "GC plan Artifact metadata does not match the canonical plan"
                )
            try:
                self.store.verify_final_bytes(
                    plan_artifact_id, expected_byte_size=len(plan_bytes)
                )
            except Exception as exc:
                raise GarbageCollectionSafetyError(
                    "GC plan Artifact bytes are not verifiably canonical"
                ) from exc
            existing = connection.execute(
                """
                SELECT * FROM artifact_gc_batch
                WHERE phase=? AND plan_artifact_id=? AND exact_artifact_ids_hash=?
                """,
                (phase, plan_artifact_id, ids_hash),
            ).fetchone()
            if existing is not None:
                existing = dict(existing)
                expected_existing = {
                    "phase": phase,
                    "scope_owner_id": scope_owner_id,
                    "plan_artifact_id": plan_artifact_id,
                    "reachability_fingerprint": plan.reachability_fingerprint,
                    "exact_artifact_ids_hash": ids_hash,
                    "exact_artifact_ids_json": _canonical_text(list(exact_ids)),
                    "open_intent_ids_json": _canonical_text(
                        list(plan.open_promotion_intent_ids)
                    ),
                    "created_at": _wire_time(plan.created_at),
                    "expires_at": _wire_time(plan.expires_at),
                }
                if any(
                    existing.get(column) != value
                    for column, value in expected_existing.items()
                ):
                    raise GarbageCollectionSafetyError(
                        "existing GC batch conflicts with the exact plan"
                    )
                uow.rollback()
                return dict(existing)
            self._validate_gc_plan_items_in_transaction(
                connection,
                phase=phase,
                plan_artifact_id=plan_artifact_id,
                items=plan.items,
            )
            batch = SQLiteRepositoryRegistry(uow).artifact.create_gc_batch(
                {
                    "gc_batch_id": _mint_id("gcb_"),
                    "phase": phase,
                    "scope_owner_id": scope_owner_id,
                    "plan_artifact_id": plan_artifact_id,
                    "reachability_fingerprint": plan.reachability_fingerprint,
                    "exact_artifact_ids_hash": ids_hash,
                    "exact_artifact_ids_json": _canonical_text(list(exact_ids)),
                    "open_intent_ids_json": _canonical_text(list(plan.open_promotion_intent_ids)),
                    "confirmation_nonce": None,
                    "confirmation_hash": None,
                    "state": "PLANNED",
                    "created_at": _wire_time(plan.created_at),
                    "expires_at": _wire_time(plan.expires_at),
                    "confirmed_at": None,
                    "completed_at": None,
                }
            )
            uow.commit()
            return batch
        finally:
            if uow.active:
                uow.rollback()
            connection.close()

    def get_gc_batch(self, gc_batch_id: str) -> dict[str, Any] | None:
        connection = self._connection(read_only=True)
        try:
            row = connection.execute(
                "SELECT * FROM artifact_gc_batch WHERE gc_batch_id=?", (gc_batch_id,)
            ).fetchone()
            return None if row is None else dict(row)
        finally:
            connection.close()

    def _set_gc_state(
        self,
        gc_batch_id: str,
        *,
        expected_state: str,
        target_state: str,
        confirmed_at: str | None = None,
        completed_at: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        connection = self._connection()
        uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
        try:
            uow.begin()
            if target_state == "EXECUTING":
                current = connection.execute(
                    "SELECT * FROM artifact_gc_batch WHERE gc_batch_id=?",
                    (gc_batch_id,),
                ).fetchone()
                if current is None:
                    raise GarbageCollectionSafetyError("GC batch disappeared before execution")
                self._validate_gc_batch_execution_in_transaction(
                    connection,
                    dict(current),
                    now=now,
                    expected_catalog_state=(
                        "QUARANTINED"
                        if str(current["phase"]) == "PURGE"
                        else "PUBLISHED"
                    ),
                    require_quarantine_records=str(current["phase"]) == "PURGE",
                )
                self._assert_gc_targets_clear_in_transaction(connection, dict(current))
            row = SQLiteRepositoryRegistry(uow).artifact.transition_gc_batch(
                gc_batch_id,
                expected_state=expected_state,
                target_state=target_state,
                confirmed_at=confirmed_at,
                completed_at=completed_at,
            )
            uow.commit()
            return row
        finally:
            if uow.active:
                uow.rollback()
            connection.close()

    @_namespace_locked
    def confirm_gc_batch(
        self,
        *,
        gc_batch_id: str,
        plan_artifact_id: str,
        exact_ids_hash: str,
        confirmation_nonce: str,
        now: datetime,
    ) -> dict[str, Any]:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("GC confirmation time must be timezone-aware")
        with self.store.namespace_lock():
            row = self.get_gc_batch(gc_batch_id)
        if row is None:
            raise GarbageCollectionSafetyError("unknown GC batch")
        exact_ids = self._gc_ids(row)
        if str(row["plan_artifact_id"]) != plan_artifact_id:
            raise GarbageCollectionSafetyError("confirmation does not identify the exact plan Artifact")
        if str(row["exact_artifact_ids_hash"]) != exact_ids_hash:
            raise GarbageCollectionSafetyError("confirmation does not identify the exact Artifact set")
        if not isinstance(confirmation_nonce, str) or not 1 <= len(confirmation_nonce) <= 128:
            raise GarbageCollectionSafetyError("GC confirmation nonce is outside the bounded size")
        proof = gc_confirmation_hash(
            plan_artifact_id=plan_artifact_id,
            exact_ids_hash=exact_ids_hash,
            confirmation_nonce=confirmation_nonce,
        )
        if row["state"] != "PLANNED":
            if (
                row["state"] == "CONFIRMED"
                and row.get("confirmation_nonce") == confirmation_nonce
                and row.get("confirmation_hash") == proof
            ):
                return row
            raise GarbageCollectionSafetyError("GC batch is not awaiting confirmation")
        if _parse_time(str(row["expires_at"])) <= now:
            self._set_gc_state(gc_batch_id, expected_state="PLANNED", target_state="STALE")
            raise GarbageCollectionSafetyError("GC confirmation has expired")
        current_fingerprint, current_open_intent_ids, reachable, open_intents, staged = (
            self._current_gc_snapshot(
                str(row["scope_owner_id"]),
                exclude_artifact_ids=frozenset({plan_artifact_id}),
            )
        )
        planned_open_intent_ids = self._gc_open_intent_ids(row)
        if tuple(sorted(planned_open_intent_ids)) != current_open_intent_ids:
            self._set_gc_state(gc_batch_id, expected_state="PLANNED", target_state="STALE")
            raise GarbageCollectionSafetyError("GC promotion-intent exclusion set changed")
        if current_fingerprint != str(row["reachability_fingerprint"]):
            self._set_gc_state(gc_batch_id, expected_state="PLANNED", target_state="STALE")
            raise GarbageCollectionSafetyError("GC reachability fingerprint changed")
        blocked = (set(exact_ids) & (set(reachable) | set(open_intents) | set(staged)))
        if blocked:
            self._set_gc_state(gc_batch_id, expected_state="PLANNED", target_state="STALE")
            raise GarbageCollectionSafetyError(
                "GC exact set is no longer safe: " + ", ".join(sorted(blocked))
            )
        connection = self._connection()
        uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
        try:
            uow.begin()
            current = connection.execute(
                "SELECT * FROM artifact_gc_batch WHERE gc_batch_id=?",
                (gc_batch_id,),
            ).fetchone()
            if current is None:
                raise GarbageCollectionSafetyError("GC batch disappeared before confirmation")
            self._validate_gc_batch_execution_in_transaction(
                connection,
                dict(current),
                now=now,
                expected_catalog_state=(
                    "QUARANTINED"
                    if str(current["phase"]) == "PURGE"
                    else "PUBLISHED"
                ),
                require_quarantine_records=str(current["phase"]) == "PURGE",
            )
            cursor = connection.execute(
                """
                UPDATE artifact_gc_batch
                SET confirmation_nonce=?, confirmation_hash=?, confirmed_at=?, state='CONFIRMED'
                WHERE gc_batch_id=? AND state='PLANNED' AND expires_at>?
                """,
                (confirmation_nonce, proof, _wire_time(now), gc_batch_id, _wire_time(now)),
            )
            if cursor.rowcount != 1:
                raise GarbageCollectionSafetyError("GC confirmation lost a concurrent state race")
            uow.commit()
        finally:
            if uow.active:
                uow.rollback()
            connection.close()
        result = self.get_gc_batch(gc_batch_id)
        if result is None:
            raise GarbageCollectionSafetyError("confirmed GC batch disappeared")
        return result

    def _gc_ids(self, row: Mapping[str, Any]) -> tuple[str, ...]:
        try:
            raw_ids = json.loads(str(row["exact_artifact_ids_json"]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise GarbageCollectionSafetyError(
                "GC exact Artifact IDs are not valid JSON"
            ) from exc
        if not isinstance(raw_ids, list):
            raise GarbageCollectionSafetyError("GC exact Artifact IDs are not a JSON array")
        if any(not isinstance(value, str) for value in raw_ids):
            raise GarbageCollectionSafetyError("GC exact Artifact IDs must be strings")
        exact_ids = tuple(raw_ids)
        if tuple(sorted(exact_ids)) != exact_ids or len(set(exact_ids)) != len(exact_ids):
            raise GarbageCollectionSafetyError("GC exact Artifact ID set is not canonical")
        if exact_artifact_ids_hash(exact_ids) != str(row["exact_artifact_ids_hash"]):
            raise GarbageCollectionSafetyError("GC batch exact ID set is corrupted")
        if _canonical_text(list(exact_ids)) != str(row["exact_artifact_ids_json"]):
            raise GarbageCollectionSafetyError("GC exact Artifact IDs are not canonical JSON")
        return exact_ids

    def _gc_open_intent_ids(self, row: Mapping[str, Any]) -> tuple[str, ...]:
        try:
            raw_ids = json.loads(str(row["open_intent_ids_json"]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise GarbageCollectionSafetyError(
                "GC open promotion-intent IDs are not valid JSON"
            ) from exc
        if not isinstance(raw_ids, list) or any(
            not isinstance(value, str) for value in raw_ids
        ):
            raise GarbageCollectionSafetyError(
                "GC open promotion-intent IDs must be a JSON string array"
            )
        intent_ids = tuple(raw_ids)
        if tuple(sorted(intent_ids)) != intent_ids or len(set(intent_ids)) != len(intent_ids):
            raise GarbageCollectionSafetyError(
                "GC open promotion-intent IDs are not canonical"
            )
        if _canonical_text(list(intent_ids)) != str(row["open_intent_ids_json"]):
            raise GarbageCollectionSafetyError(
                "GC open promotion-intent IDs are not canonical JSON"
            )
        return intent_ids

    def _gc_records(self, gc_batch_id: str) -> tuple[dict[str, Any], ...]:
        connection = self._connection(read_only=True)
        try:
            return tuple(
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM artifact_quarantine WHERE gc_batch_id=? ORDER BY artifact_id",
                    (gc_batch_id,),
                )
            )
        finally:
            connection.close()

    def _purge_records(self, row: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
        """Resolve the current quarantine rows for a separately planned PURGE batch."""

        own_records = self._gc_records(str(row["gc_batch_id"]))
        if own_records:
            return own_records
        exact_ids = self._gc_ids(row)
        if not exact_ids:
            return ()
        placeholders = ",".join("?" for _ in exact_ids)
        connection = self._connection(read_only=True)
        try:
            records = tuple(
                dict(record)
                for record in connection.execute(
                    f"""
                    SELECT aq.*
                    FROM artifact_quarantine AS aq
                    WHERE aq.artifact_id IN ({placeholders})
                      AND aq.state='QUARANTINED'
                    ORDER BY aq.artifact_id, aq.gc_batch_id DESC
                    """,
                    exact_ids,
                )
            )
        finally:
            connection.close()
        by_artifact: dict[str, dict[str, Any]] = {}
        for record in records:
            artifact_id = str(record["artifact_id"])
            if artifact_id in by_artifact:
                raise GarbageCollectionSafetyError(
                    f"multiple active quarantine records exist for {artifact_id}"
                )
            by_artifact[artifact_id] = record
        if set(by_artifact) != set(exact_ids):
            raise GarbageCollectionSafetyError(
                "PURGE exact set does not resolve to the current quarantined bytes"
            )
        return tuple(by_artifact[artifact_id] for artifact_id in exact_ids)

    def _assert_gc_targets_clear_in_transaction(
        self, connection: sqlite3.Connection, row: Mapping[str, Any]
    ) -> None:
        """Recheck all mutable reachability inputs before EXECUTING is visible."""

        ids = self._gc_ids(row)
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        active_reference = connection.execute(
            f"""
            SELECT artifact_id
            FROM artifact_reference
            WHERE state='ACTIVE' AND artifact_id IN ({placeholders})
            ORDER BY artifact_id LIMIT 1
            """,
            ids,
        ).fetchone()
        if active_reference is not None:
            raise GarbageCollectionSafetyError(
                "GC target became reachable before execution: "
                + str(active_reference[0])
            )
        open_intent = connection.execute(
            f"""
            SELECT artifact_id
            FROM artifact_promotion_intent
            WHERE artifact_id IN ({placeholders})
              AND state IN ('STAGED_SYNCED','FINAL_PRESENT',
                            'CATALOG_COMMITTED','CLEANUP_PENDING')
            ORDER BY artifact_id, promotion_intent_id LIMIT 1
            """,
            ids,
        ).fetchone()
        if open_intent is not None:
            raise GarbageCollectionSafetyError(
                "GC target has an open promotion intent: " + str(open_intent[0])
            )
        if str(row.get("phase")) == "PURGE":
            quarantine_rows = tuple(
                connection.execute(
                    f"""
                    SELECT aq.artifact_id
                    FROM artifact_quarantine AS aq
                    JOIN artifact AS a ON a.artifact_id=aq.artifact_id
                    WHERE aq.artifact_id IN ({placeholders})
                      AND aq.state='QUARANTINED'
                      AND a.state='QUARANTINED'
                    """,
                    ids,
                )
            )
            if len(quarantine_rows) != len(ids) or {
                str(item[0]) for item in quarantine_rows
            } != set(ids):
                raise GarbageCollectionSafetyError(
                    "PURGE target does not have one current QUARANTINED record per Artifact"
                )
        try:
            stage_entries = self.store.iter_staging_entries(limit=10_000)
        except ArtifactScanLimitExceeded as exc:
            raise GarbageCollectionSafetyError(
                "GC staging scan exceeded the bounded limit"
            ) from exc
        target_ids = set(ids)
        for entry_name in stage_entries:
            if not entry_name.endswith(".stage"):
                raise GarbageCollectionSafetyError(
                    f"GC staging namespace contains an unexpected entry: {entry_name}"
                )
            token = entry_name[: -len(".stage")]
            try:
                self.store.staging_path(token)
            except StagingNotFound as exc:
                raise GarbageCollectionSafetyError(
                    f"GC staging namespace contains an invalid entry: {entry_name}"
                ) from exc
            try:
                receipt = self.store.staging_receipt(token)
            except Exception as exc:
                raise GarbageCollectionSafetyError(
                    f"GC staging entry is not verifiably readable: {entry_name}"
                ) from exc
            staged_artifact_id = "art_sha256_" + receipt.sha256
            if staged_artifact_id in target_ids:
                raise GarbageCollectionSafetyError(
                    "GC target has staged bytes awaiting publication: "
                    + staged_artifact_id
                )

    def _prepare_quarantine_records(self, row: Mapping[str, Any], now: datetime) -> tuple[dict[str, Any], ...]:
        ids = self._gc_ids(row)
        records: list[dict[str, Any]] = []
        connection = self._connection()
        uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
        try:
            uow.begin()
            repository = SQLiteRepositoryRegistry(uow).artifact
            self._validate_gc_batch_execution_in_transaction(
                connection,
                row,
                now=now,
                expected_catalog_state="PUBLISHED",
                require_quarantine_records=False,
            )
            self._assert_no_existing_quarantine_records_in_transaction(
                connection,
                row,
            )
            self._assert_gc_targets_clear_in_transaction(connection, row)
            for artifact_id in ids:
                artifact = repository.table("artifact").get(artifact_id)
                if artifact is None or artifact["state"] != "PUBLISHED":
                    raise GarbageCollectionSafetyError("GC target is not PUBLISHED")
                _, storage_key = self.store.quarantine_path(artifact_id, str(row["gc_batch_id"]))
                record = {
                    "artifact_id": artifact_id,
                    "gc_batch_id": str(row["gc_batch_id"]),
                    "quarantine_storage_key": storage_key,
                    "original_storage_key": str(artifact["storage_key"]),
                    "quarantined_at": _wire_time(now),
                    "purge_not_before": _wire_time(now + timedelta(days=30)),
                    "state": "MOVING",
                }
                records.append(repository.create_quarantine_record(record))
            repository.transition_gc_batch(
                str(row["gc_batch_id"]),
                expected_state="CONFIRMED",
                target_state="EXECUTING",
            )
            uow.commit()
        finally:
            if uow.active:
                uow.rollback()
            connection.close()
        return tuple(records)

    def _fresh_gc_failure(self, row: Mapping[str, Any]) -> set[str]:
        ids = set(self._gc_ids(row))
        reachable, open_intents, staged = self.current_gc_guard()
        return ids & (set(reachable) | set(open_intents) | set(staged))

    def _validate_confirmed_gc_batch(
        self, row: Mapping[str, Any], *, now: datetime
    ) -> None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("GC execution time must be timezone-aware")
        if _parse_time(str(row["expires_at"])) <= now:
            self._set_gc_state(
                str(row["gc_batch_id"]),
                expected_state="CONFIRMED",
                target_state="STALE",
            )
            raise GarbageCollectionSafetyError("GC confirmation has expired")
        nonce = row.get("confirmation_nonce")
        proof = row.get("confirmation_hash")
        expected_proof = gc_confirmation_hash(
            plan_artifact_id=str(row["plan_artifact_id"]),
            exact_ids_hash=str(row["exact_artifact_ids_hash"]),
            confirmation_nonce=str(nonce),
        )
        if not nonce or proof != expected_proof:
            raise GarbageCollectionSafetyError("GC confirmation proof is not valid")
        (
            current_fingerprint,
            current_open_intent_ids,
            reachable,
            open_intents,
            staged,
        ) = self._current_gc_snapshot(
            str(row["scope_owner_id"]),
            exclude_artifact_ids=frozenset({str(row["plan_artifact_id"])}),
        )
        planned_open_intent_ids = self._gc_open_intent_ids(row)
        blocked = set(self._gc_ids(row)) & (
            set(reachable) | set(open_intents) | set(staged)
        )
        if (
            current_fingerprint != str(row["reachability_fingerprint"])
            or current_open_intent_ids != tuple(sorted(planned_open_intent_ids))
            or blocked
        ):
            self._set_gc_state(
                str(row["gc_batch_id"]),
                expected_state="CONFIRMED",
                target_state="STALE",
            )
            details = "GC confirmation no longer matches the fresh Catalog/storage guard"
            if blocked:
                details += ": " + ", ".join(sorted(blocked))
            raise GarbageCollectionSafetyError(details)

    def _validated_gc_byte_sizes(
        self, records: Sequence[Mapping[str, Any]]
    ) -> dict[str, int]:
        sizes: dict[str, int] = {}
        for record in records:
            artifact_id = str(record["artifact_id"])
            sizes[artifact_id] = self._artifact_byte_size(artifact_id)
        return sizes

    def _create_gc_receipt(
        self,
        *,
        row: Mapping[str, Any],
        result: str,
        exact_bytes: int,
        reclaimed_bytes: int,
        details: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._write(
            lambda repository: repository.create_gc_receipt(
                {
                    "receipt_id": _mint_id("agr_"),
                    "gc_batch_id": str(row["gc_batch_id"]),
                    "result": result,
                    "exact_artifact_ids_hash": str(row["exact_artifact_ids_hash"]),
                    "exact_bytes": exact_bytes,
                    "reclaimed_bytes": reclaimed_bytes,
                    "created_at": _wire_time(datetime.now(timezone.utc)),
                    "details_json": _canonical_text(dict(details)),
                }
            )
        )

    @_namespace_locked
    def execute_quarantine(self, *, gc_batch_id: str, now: datetime) -> dict[str, Any]:
        """Move an exact confirmed set to quarantine; no permanent deletion occurs."""

        row = self.get_gc_batch(gc_batch_id)
        if row is None or row["phase"] != "QUARANTINE":
            raise GarbageCollectionSafetyError("unknown QUARANTINE GC batch")
        if row["state"] in {"COMPLETED", "FAILED"}:
            receipt = self._latest_gc_receipt(gc_batch_id)
            if receipt is None:
                raise GarbageCollectionSafetyError("terminal GC batch has no receipt")
            return receipt
        if row["state"] != "CONFIRMED":
            raise GarbageCollectionSafetyError("QUARANTINE batch is not confirmed")
        self._validate_confirmed_gc_batch(row, now=now)
        records = self._prepare_quarantine_records(row, now)
        byte_sizes = self._validated_gc_byte_sizes(records)
        moved: list[dict[str, Any]] = []
        errors: list[str] = []
        for record in records:
            try:
                storage_key = self.store.quarantine_published_bytes(
                    str(record["artifact_id"]),
                    gc_batch_id,
                    expected_byte_size=byte_sizes[str(record["artifact_id"])],
                )
                if storage_key is None:
                    raise StagingNotFound("GC target bytes are missing")
                moved.append(record)
            except Exception as exc:
                errors.append(f"{record['artifact_id']}: {exc}")
                break
        exact_bytes = sum(byte_sizes.values())
        if errors:
            self._finish_quarantine_batch(
                row,
                records=records,
                moved_records=moved,
                state="FAILED",
                receipt_result="PARTIAL" if moved else "FAILED",
                exact_bytes=exact_bytes,
                details={"errors": errors, "moved_artifact_ids": [item["artifact_id"] for item in moved]},
                now=now,
                byte_sizes=byte_sizes,
            )
            raise GarbageCollectionSafetyError("GC quarantine failed: " + "; ".join(errors))
        self._finish_quarantine_batch(
            row,
            records=moved,
            state="COMPLETED",
            receipt_result="QUARANTINED",
            exact_bytes=exact_bytes,
            details={"artifact_ids": [item["artifact_id"] for item in moved]},
            now=now,
            byte_sizes=byte_sizes,
        )
        receipt = self._latest_gc_receipt(gc_batch_id)
        if receipt is None:
            raise GarbageCollectionSafetyError("GC quarantine committed without a receipt")
        return receipt

    def _artifact_byte_size(self, artifact_id: str) -> int:
        connection = self._connection(read_only=True)
        try:
            row = connection.execute(
                "SELECT byte_size FROM artifact WHERE artifact_id=?", (artifact_id,)
            ).fetchone()
            if row is None:
                raise GarbageCollectionSafetyError("GC Artifact disappeared")
            return int(row[0])
        finally:
            connection.close()

    def _finish_quarantine_batch(
        self,
        row: Mapping[str, Any],
        *,
        records: Sequence[Mapping[str, Any]],
        state: str,
        receipt_result: str,
        exact_bytes: int,
        details: Mapping[str, Any],
        now: datetime,
        byte_sizes: Mapping[str, int] | None = None,
        moved_records: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        moved_ids = {
            str(item["artifact_id"])
            for item in (records if moved_records is None else moved_records)
        }
        connection = self._connection()
        uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
        try:
            uow.begin()
            repository = SQLiteRepositoryRegistry(uow).artifact
            self._validate_gc_batch_execution_in_transaction(
                connection,
                row,
                now=now,
                expected_catalog_state=None,
                require_quarantine_records=True,
            )
            if state == "COMPLETED":
                if byte_sizes is None:
                    raise GarbageCollectionSafetyError(
                        "completed GC quarantine requires exact byte sizes"
                    )
                expected_ids = set(self._gc_ids(row))
                if moved_ids != expected_ids:
                    raise GarbageCollectionSafetyError(
                        "completed GC quarantine does not cover the exact Artifact set"
                    )
                # Verify the destination while the Catalog write lock is held
                # and immediately before advancing either durable state.  A
                # prior move is not accepted merely because its row says
                # QUARANTINED; bytes remain the authority for the transition.
                for record in records:
                    artifact_id = str(record["artifact_id"])
                    self.store.verify_quarantine_bytes(
                        str(record["quarantine_storage_key"]),
                        artifact_id,
                        expected_byte_size=byte_sizes[artifact_id],
                    )
            if state == "FAILED" and byte_sizes is not None:
                for record in records:
                    artifact_id = str(record["artifact_id"])
                    if record["state"] != "MOVING" or artifact_id in moved_ids:
                        continue
                    try:
                        self.store.verify_quarantine_bytes(
                            str(record["quarantine_storage_key"]),
                            artifact_id,
                            expected_byte_size=byte_sizes[artifact_id],
                        )
                    except StagingNotFound:
                        connection.execute(
                            "DELETE FROM artifact_quarantine WHERE artifact_id=? AND gc_batch_id=? AND state='MOVING'",
                            (artifact_id, record["gc_batch_id"]),
                        )
                    except Exception:
                        # Retain a conflicting destination and its MOVING row
                        # as review evidence; never discard unknown bytes.
                        continue
                    else:
                        moved_ids.add(artifact_id)
            for artifact_id in self._gc_ids(row):
                if artifact_id in moved_ids:
                    connection.execute(
                        "UPDATE artifact SET state='QUARANTINED' WHERE artifact_id=? AND state='PUBLISHED'",
                        (artifact_id,),
                    )
                    connection.execute(
                        """
                        UPDATE artifact_quarantine SET state='QUARANTINED'
                        WHERE artifact_id=? AND gc_batch_id=? AND state='MOVING'
                        """,
                        (artifact_id, row["gc_batch_id"]),
                    )
            repository.transition_gc_batch(
                str(row["gc_batch_id"]),
                expected_state="EXECUTING",
                target_state=state,
                completed_at=_wire_time(now) if state == "COMPLETED" else None,
            )
            repository.create_gc_receipt(
                {
                    "receipt_id": _mint_id("agr_"),
                    "gc_batch_id": str(row["gc_batch_id"]),
                    "result": receipt_result,
                    "exact_artifact_ids_hash": str(row["exact_artifact_ids_hash"]),
                    "exact_bytes": exact_bytes,
                    "reclaimed_bytes": 0,
                    "created_at": _wire_time(now),
                    "details_json": _canonical_text(dict(details)),
                }
            )
            uow.commit()
        finally:
            if uow.active:
                uow.rollback()
            connection.close()

    def _latest_gc_receipt(self, gc_batch_id: str) -> dict[str, Any] | None:
        connection = self._connection(read_only=True)
        try:
            row = connection.execute(
                """
                SELECT * FROM artifact_gc_receipt
                WHERE gc_batch_id=? ORDER BY created_at DESC, receipt_id DESC LIMIT 1
                """,
                (gc_batch_id,),
            ).fetchone()
            return None if row is None else dict(row)
        finally:
            connection.close()

    def _validate_gc_batch_before_reconcile(
        self,
        row: Mapping[str, Any],
        *,
        now: datetime | None,
    ) -> tuple[GarbageCollectionItem, ...]:
        """Validate an EXECUTING batch before resuming any byte operation."""

        connection = self._connection()
        uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
        try:
            uow.begin()
            items = self._validate_gc_batch_execution_in_transaction(
                connection,
                row,
                now=now,
                expected_catalog_state=(
                    "QUARANTINED"
                    if str(row["phase"]) == "PURGE"
                    else None
                ),
                require_quarantine_records=True,
            )
            uow.commit()
            return items
        finally:
            if uow.active:
                uow.rollback()
            connection.close()

    @_namespace_locked
    def restore_quarantined_batch(self, *, gc_batch_id: str, now: datetime) -> dict[str, Any]:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("GC restore time must be timezone-aware")
        with self.store.namespace_lock():
            row = self.get_gc_batch(gc_batch_id)
            if (
                row is None
                or row["phase"] != "QUARANTINE"
                or row["state"] not in {"COMPLETED", "FAILED"}
            ):
                raise GarbageCollectionSafetyError("GC batch is not restorable")
            exact_ids = self._gc_ids(row)
            records = self._gc_records(gc_batch_id)
            by_artifact = {str(record["artifact_id"]): record for record in records}
            if len(by_artifact) != len(records):
                raise GarbageCollectionSafetyError("GC quarantine records are ambiguous")
            record_ids = set(by_artifact)
            exact_id_set = set(exact_ids)
            if not record_ids.issubset(exact_id_set):
                raise GarbageCollectionSafetyError(
                    "GC quarantine records contain an Artifact outside the exact plan"
                )
            if row["state"] == "COMPLETED" and record_ids != exact_id_set:
                raise GarbageCollectionSafetyError(
                    "completed GC batch does not contain one quarantine record per Artifact"
                )
            if any(str(record["state"]) == "PURGED" for record in records):
                raise GarbageCollectionSafetyError(
                    "purged quarantine bytes cannot be restored"
                )
            restorable_records = tuple(
                record
                for record in records
                if str(record["state"]) in {"QUARANTINED", "RESTORED"}
            )
            if not restorable_records:
                raise GarbageCollectionSafetyError(
                    "GC batch has no quarantined bytes available for restore"
                )
            byte_sizes = self._validated_gc_byte_sizes(records)

            # A successful restore is a durable idempotent result.  Return the
            # existing receipt after verifying the restored Catalog/storage
            # state rather than creating a new receipt on every retry.
            latest = self._latest_gc_receipt(gc_batch_id)
            if latest is not None and latest.get("result") == "RESTORED":
                try:
                    for record in restorable_records:
                        artifact_id = str(record["artifact_id"])
                        catalog = self._read_catalog_artifact(artifact_id)
                        if catalog is None or str(catalog["state"]) != "PUBLISHED":
                            raise GarbageCollectionSafetyError(
                                "restored Artifact is not PUBLISHED"
                            )
                        self.store.verify_final_bytes(
                            artifact_id,
                            expected_byte_size=byte_sizes[artifact_id],
                        )
                        if str(record["state"]) != "RESTORED":
                            raise GarbageCollectionSafetyError(
                                "restore receipt does not cover current quarantine state"
                            )
                    return latest
                except (StagingNotFound, ArtifactCollision, IntegrityMismatch, GarbageCollectionSafetyError):
                    pass

            # RESTORED is used as a durable restore intent.  Reserving all
            # currently quarantined rows before touching bytes makes restore
            # mutually exclusive with a later PURGE, including across process
            # boundaries where the Python lock is not shared.
            connection = self._connection()
            uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
            try:
                uow.begin()
                current = connection.execute(
                    "SELECT * FROM artifact_gc_batch WHERE gc_batch_id=?",
                    (gc_batch_id,),
                ).fetchone()
                if current is None or str(current["state"]) not in {"COMPLETED", "FAILED"}:
                    raise GarbageCollectionSafetyError("GC batch changed before restore")
                repository = SQLiteRepositoryRegistry(uow).artifact
                purge_rows = connection.execute(
                    """
                    SELECT purge.gc_batch_id, purge.state
                    FROM artifact_gc_batch AS purge
                    WHERE purge.phase='PURGE'
                      AND purge.state IN ('PLANNED','CONFIRMED','EXECUTING')
                      AND EXISTS (
                        SELECT 1
                        FROM json_each(purge.exact_artifact_ids_json) AS planned
                        JOIN json_each(?) AS target
                          ON target.value=planned.value
                      )
                    ORDER BY purge.gc_batch_id
                    """,
                    (_canonical_text(list(exact_ids)),),
                ).fetchall()
                for purge_row in purge_rows:
                    purge_batch_id = str(purge_row[0])
                    purge_state = str(purge_row[1])
                    if purge_state == "EXECUTING":
                        raise GarbageCollectionSafetyError(
                            "GC restore conflicts with an executing PURGE batch"
                        )
                    # A restore changes the exact Catalog state that a
                    # planned/confirmed PURGE depends on. Invalidate those
                    # batches under the same write lock so no confirmed
                    # purge can remain stuck against the restored bytes.
                    repository.transition_gc_batch(
                        purge_batch_id,
                        expected_state=purge_state,
                        target_state="STALE",
                    )
                reservable = [
                    record
                    for record in records
                    if str(record["state"]) == "QUARANTINED"
                ]
                for record in reservable:
                    artifact_id = str(record["artifact_id"])
                    # Validate both possible locations before reserving the
                    # row. A correct final is an idempotent prior move; a
                    # wrong final is never overwritten.
                    try:
                        self.store.verify_final_bytes(
                            artifact_id, expected_byte_size=byte_sizes[artifact_id]
                        )
                    except StagingNotFound:
                        pass
                    except (ArtifactCollision, IntegrityMismatch) as exc:
                        raise GarbageCollectionSafetyError(
                            f"restore final path conflicts for {artifact_id}"
                        ) from exc
                    try:
                        self.store.verify_quarantine_bytes(
                            str(record["quarantine_storage_key"]),
                            artifact_id,
                            expected_byte_size=byte_sizes[artifact_id],
                        )
                    except StagingNotFound:
                        try:
                            self.store.verify_final_bytes(
                                artifact_id,
                                expected_byte_size=byte_sizes[artifact_id],
                            )
                        except (ArtifactCollision, IntegrityMismatch) as exc:
                            raise GarbageCollectionSafetyError(
                                f"restore final path conflicts for {artifact_id}"
                            ) from exc
                    except (ArtifactCollision, IntegrityMismatch) as exc:
                        raise GarbageCollectionSafetyError(
                            f"restore quarantine bytes conflict for {artifact_id}"
                        ) from exc
                    connection.execute(
                        """
                        UPDATE artifact_quarantine SET state='RESTORED'
                        WHERE artifact_id=? AND gc_batch_id=? AND state='QUARANTINED'
                        """,
                        (artifact_id, gc_batch_id),
                    )
                uow.commit()
            finally:
                if uow.active:
                    uow.rollback()
                connection.close()

            restore_records = [
                record
                for record in records
                if str(record["state"]) in {"QUARANTINED", "RESTORED"}
            ]
            restored: list[str] = []
            try:
                for record in restore_records:
                    artifact_id = str(record["artifact_id"])
                    self.store.restore_quarantined_bytes(
                        artifact_id,
                        str(record["quarantine_storage_key"]),
                        expected_byte_size=byte_sizes[artifact_id],
                    )
                    self.store.verify_final_bytes(
                        artifact_id, expected_byte_size=byte_sizes[artifact_id]
                    )
                    restored.append(artifact_id)
            except Exception as exc:
                try:
                    self._record_error(
                        intent_id=None,
                        artifact_id=artifact_id,
                        phase="QUARANTINE",
                        error_code="ARTIFACT_GC_RESTORE_RECONCILIATION_REQUIRED",
                        observed_state={"gc_batch_id": gc_batch_id, "error": str(exc)},
                    )
                except Exception:
                    pass
                raise GarbageCollectionSafetyError(
                    "GC restore requires reconciliation: " + str(exc)
                ) from exc

            connection = self._connection()
            uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
            try:
                uow.begin()
                repository = SQLiteRepositoryRegistry(uow).artifact
                for artifact_id in restored:
                    connection.execute(
                        "UPDATE artifact SET state='PUBLISHED' WHERE artifact_id=? AND state='QUARANTINED'",
                        (artifact_id,),
                    )
                if restored:
                    repository.create_gc_receipt(
                        {
                            "receipt_id": _mint_id("agr_"),
                            "gc_batch_id": gc_batch_id,
                            "result": "RESTORED",
                            "exact_artifact_ids_hash": str(row["exact_artifact_ids_hash"]),
                            "exact_bytes": sum(byte_sizes[item] for item in restored),
                            "reclaimed_bytes": 0,
                            "created_at": _wire_time(now),
                            "details_json": _canonical_text(
                                {"restored_artifact_ids": restored}
                            ),
                        }
                    )
                uow.commit()
            finally:
                if uow.active:
                    uow.rollback()
                connection.close()
            result = self._latest_gc_receipt(gc_batch_id)
            if result is None or (restored and result["result"] != "RESTORED"):
                raise GarbageCollectionSafetyError("restore committed without a receipt")
            return result

    @_namespace_locked
    def execute_purge(self, *, gc_batch_id: str, now: datetime) -> dict[str, Any]:
        """Permanently remove only a separately planned and confirmed PURGE set."""

        row = self.get_gc_batch(gc_batch_id)
        if row is None or row["phase"] != "PURGE":
            raise GarbageCollectionSafetyError("PURGE batch is not confirmed")
        if row["state"] in {"COMPLETED", "FAILED"}:
            receipt = self._latest_gc_receipt(gc_batch_id)
            if receipt is None:
                raise GarbageCollectionSafetyError("terminal PURGE batch has no receipt")
            return receipt
        if row["state"] != "CONFIRMED":
            raise GarbageCollectionSafetyError("PURGE batch is not confirmed")
        self._validate_confirmed_gc_batch(row, now=now)
        records = self._purge_records(row)
        ids = set(self._gc_ids(row))
        if {str(item["artifact_id"]) for item in records if item["state"] == "QUARANTINED"} != ids:
            raise GarbageCollectionSafetyError("PURGE batch does not cover the exact quarantined set")
        for record in records:
            if _parse_time(str(record["purge_not_before"])) > now:
                raise GarbageCollectionSafetyError("quarantine retention period has not elapsed")
        byte_sizes = self._validated_gc_byte_sizes(records)
        self._set_gc_state(
            gc_batch_id,
            expected_state="CONFIRMED",
            target_state="EXECUTING",
            now=now,
        )
        exact_bytes = sum(byte_sizes.values())
        purged: list[str] = []
        errors: list[str] = []
        for record in records:
            try:
                if not self.store.purge_quarantined_bytes(
                    str(record["artifact_id"]),
                    str(record["quarantine_storage_key"]),
                    expected_byte_size=byte_sizes[str(record["artifact_id"])],
                ):
                    raise StagingNotFound("purge absence was not confirmed")
                purged.append(str(record["artifact_id"]))
            except Exception as exc:
                errors.append(f"{record['artifact_id']}: {exc}")
                break
        connection = self._connection()
        uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
        try:
            uow.begin()
            repository = SQLiteRepositoryRegistry(uow).artifact
            self._validate_gc_batch_execution_in_transaction(
                connection,
                row,
                now=now,
                expected_catalog_state="QUARANTINED",
                require_quarantine_records=True,
            )
            for record in records:
                artifact_id = str(record["artifact_id"])
                if artifact_id not in purged:
                    continue
                connection.execute(
                    "UPDATE artifact SET state='DELETED', deleted_at=? WHERE artifact_id=? AND state='QUARANTINED'",
                    (_wire_time(now), artifact_id),
                )
                connection.execute(
                    "UPDATE artifact_quarantine SET state='PURGED' WHERE artifact_id=? AND gc_batch_id=? AND state='QUARANTINED'",
                    (artifact_id, record["gc_batch_id"]),
                )
            target_state = "FAILED" if errors else "COMPLETED"
            repository.transition_gc_batch(
                gc_batch_id,
                expected_state="EXECUTING",
                target_state=target_state,
                completed_at=_wire_time(now) if not errors else None,
            )
            repository.create_gc_receipt(
                {
                    "receipt_id": _mint_id("agr_"),
                    "gc_batch_id": gc_batch_id,
                    "result": "PARTIAL" if errors else "PURGED",
                    "exact_artifact_ids_hash": str(row["exact_artifact_ids_hash"]),
                    "exact_bytes": exact_bytes,
                    "reclaimed_bytes": sum(byte_sizes[item] for item in purged),
                    "created_at": _wire_time(now),
                    "details_json": _canonical_text({"purged_artifact_ids": purged, "errors": errors}),
                }
            )
            uow.commit()
        finally:
            if uow.active:
                uow.rollback()
            connection.close()
        receipt = self._latest_gc_receipt(gc_batch_id)
        if receipt is None:
            raise GarbageCollectionSafetyError("PURGE committed without a receipt")
        if errors:
            raise GarbageCollectionSafetyError("GC purge failed: " + "; ".join(errors))
        return receipt

    def _gc_partial_evidence(
        self, row: Mapping[str, Any], records: Sequence[Mapping[str, Any]]
    ) -> tuple[dict[str, int], tuple[str, ...], tuple[str, ...]]:
        """Inspect durable byte locations after a recoverable reconciliation error."""

        byte_sizes: dict[str, int] = {}
        quarantined: list[str] = []
        purged: list[str] = []
        for record in records:
            artifact_id = str(record["artifact_id"])
            try:
                byte_sizes[artifact_id] = self._artifact_byte_size(artifact_id)
            except Exception:
                byte_sizes[artifact_id] = 0
            if row["phase"] == "QUARANTINE":
                try:
                    self.store.verify_quarantine_bytes(
                        str(record["quarantine_storage_key"]),
                        artifact_id,
                        expected_byte_size=byte_sizes[artifact_id],
                    )
                except Exception:
                    continue
                quarantined.append(artifact_id)
            elif record["state"] == "PURGED":
                purged.append(artifact_id)
            else:
                try:
                    self.store.verify_quarantine_bytes(
                        str(record["quarantine_storage_key"]),
                        artifact_id,
                        expected_byte_size=byte_sizes[artifact_id],
                    )
                except StagingNotFound:
                    # Once a PURGE batch is EXECUTING, a missing exact
                    # quarantine entry is the required absence proof.
                    purged.append(artifact_id)
                except Exception:
                    pass
        return byte_sizes, tuple(quarantined), tuple(purged)

    def _fail_gc_execution(
        self,
        row: Mapping[str, Any],
        records: Sequence[Mapping[str, Any]],
        error: Exception,
        *,
        apply_evidence: bool,
    ) -> None:
        """Close a normally failing EXECUTING batch as FAILED with a receipt.

        Process loss is intentionally represented by a BaseException and is
        left EXECUTING for the next startup reconciliation. Ordinary errors
        must not leave an unbounded retry loop with no durable outcome.
        """

        if apply_evidence:
            byte_sizes, quarantined, purged = self._gc_partial_evidence(row, records)
        else:
            # A plan/record validation failure is an admission failure, not
            # evidence that a missing byte was successfully moved.  Keep the
            # Catalog and quarantine rows untouched so a corrupt durable
            # binding cannot turn absence into a DELETED tombstone.
            byte_sizes, quarantined, purged = {}, (), ()
        if row["phase"] == "QUARANTINE":
            evidence_ids = quarantined
            receipt_result = "PARTIAL" if evidence_ids else "FAILED"
            reclaimed_bytes = 0
        else:
            evidence_ids = purged
            receipt_result = "PARTIAL" if evidence_ids else "FAILED"
            reclaimed_bytes = sum(byte_sizes.get(artifact_id, 0) for artifact_id in purged)
        exact_bytes = sum(byte_sizes.values())
        connection = self._connection()
        uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
        try:
            uow.begin()
            repository = SQLiteRepositoryRegistry(uow).artifact
            if apply_evidence and row["phase"] == "QUARANTINE":
                for artifact_id in quarantined:
                    record = next(
                        item for item in records if str(item["artifact_id"]) == artifact_id
                    )
                    connection.execute(
                        "UPDATE artifact SET state='QUARANTINED' WHERE artifact_id=? AND state='PUBLISHED'",
                        (artifact_id,),
                    )
                    connection.execute(
                        """
                        UPDATE artifact_quarantine SET state='QUARANTINED'
                        WHERE artifact_id=? AND gc_batch_id=? AND state='MOVING'
                        """,
                        (artifact_id, record["gc_batch_id"]),
                    )
                for record in records:
                    artifact_id = str(record["artifact_id"])
                    if record["state"] != "MOVING" or artifact_id in quarantined:
                        continue
                    try:
                        self.store.verify_quarantine_bytes(
                            str(record["quarantine_storage_key"]),
                            artifact_id,
                            expected_byte_size=byte_sizes[artifact_id],
                        )
                    except StagingNotFound:
                        # No destination bytes exist, so the uncommitted row
                        # cannot be resumed and must not strand a fake move.
                        connection.execute(
                            "DELETE FROM artifact_quarantine WHERE artifact_id=? AND gc_batch_id=? AND state='MOVING'",
                            (artifact_id, record["gc_batch_id"]),
                        )
            elif apply_evidence:
                for artifact_id in purged:
                    record = next(
                        item for item in records if str(item["artifact_id"]) == artifact_id
                    )
                    connection.execute(
                        "UPDATE artifact SET state='DELETED', deleted_at=? WHERE artifact_id=? AND state='QUARANTINED'",
                        (_wire_time(datetime.now(timezone.utc)), artifact_id),
                    )
                    connection.execute(
                        """
                        UPDATE artifact_quarantine SET state='PURGED'
                        WHERE artifact_id=? AND gc_batch_id=? AND state='QUARANTINED'
                        """,
                        (artifact_id, record["gc_batch_id"]),
                    )
            repository.transition_gc_batch(
                str(row["gc_batch_id"]),
                expected_state="EXECUTING",
                target_state="FAILED",
            )
            repository.create_gc_receipt(
                {
                    "receipt_id": _mint_id("agr_"),
                    "gc_batch_id": str(row["gc_batch_id"]),
                    "result": receipt_result,
                    "exact_artifact_ids_hash": str(row["exact_artifact_ids_hash"]),
                    "exact_bytes": exact_bytes,
                    "reclaimed_bytes": reclaimed_bytes,
                    "created_at": _wire_time(datetime.now(timezone.utc)),
                    "details_json": _canonical_text(
                        {
                            "error": str(error),
                            "evidence_applied": apply_evidence,
                            "evidence_artifact_ids": list(evidence_ids),
                            "record_states": {
                                str(item["artifact_id"]): str(item["state"])
                                for item in records
                            },
                        }
                    ),
                }
            )
            uow.commit()
        finally:
            if uow.active:
                uow.rollback()
            connection.close()

    @_namespace_locked
    def reconcile_gc(self, *, limit: int = 128) -> dict[str, Any]:
        """Finish only already-recorded GC moves; never invents a plan or confirmation."""

        if not 1 <= limit <= 1_000:
            raise ValueError("GC reconcile limit must be between 1 and 1000")
        restore_connection = self._connection(read_only=True)
        try:
            restore_rows = tuple(
                dict(row)
                for row in restore_connection.execute(
                    """
                    SELECT DISTINCT batch.*
                    FROM artifact_gc_batch AS batch
                    JOIN artifact_quarantine AS aq
                      ON aq.gc_batch_id=batch.gc_batch_id
                    JOIN artifact AS artifact
                      ON artifact.artifact_id=aq.artifact_id
                    WHERE batch.phase='QUARANTINE'
                      AND aq.state='RESTORED'
                      AND artifact.state='QUARANTINED'
                    ORDER BY batch.created_at,batch.gc_batch_id
                    LIMIT ?
                    """,
                    (limit,),
                )
            )
        finally:
            restore_connection.close()
        connection = self._connection(read_only=True)
        try:
            rows = tuple(
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM artifact_gc_batch WHERE state='EXECUTING' ORDER BY created_at,gc_batch_id LIMIT ?",
                    (limit,),
                )
            )
        finally:
            connection.close()
        completed = 0
        failed = 0
        restores_completed = 0
        restores_failed = 0
        for row in restore_rows:
            try:
                self.restore_quarantined_batch(
                    gc_batch_id=str(row["gc_batch_id"]),
                    now=datetime.now(timezone.utc),
                )
                restores_completed += 1
            except Exception as exc:
                restores_failed += 1
                try:
                    self._record_error(
                        intent_id=None,
                        artifact_id=None,
                        phase="QUARANTINE",
                        error_code="ARTIFACT_GC_RESTORE_RECONCILIATION_REQUIRED",
                        observed_state={
                            "gc_batch_id": row["gc_batch_id"],
                            "error": str(exc),
                        },
                    )
                except Exception:
                    pass
        for row in rows:
            records: tuple[dict[str, Any], ...] = ()
            apply_evidence = False
            try:
                records = (
                    self._gc_records(str(row["gc_batch_id"]))
                    if row["phase"] == "QUARANTINE"
                    else self._purge_records(row)
                )
                self._validate_gc_batch_before_reconcile(
                    row,
                    # EXECUTING is written only after the live execute path
                    # has passed the retention check.  Recovery resumes that
                    # already-admitted irreversible action; it must not
                    # reinterpret a simulated/monotonic clock as a new purge
                    # admission decision after process loss.
                    now=None,
                )
                if row["phase"] == "QUARANTINE":
                    byte_sizes = self._validated_gc_byte_sizes(records)
                    apply_evidence = True
                    moved: list[dict[str, Any]] = []
                    for record in records:
                        if record["state"] == "QUARANTINED":
                            self.store.verify_quarantine_bytes(
                                str(record["quarantine_storage_key"]),
                                str(record["artifact_id"]),
                                expected_byte_size=byte_sizes[str(record["artifact_id"])],
                            )
                            moved.append(record)
                            continue
                        if self.store.quarantine_published_bytes(
                            str(record["artifact_id"]),
                            str(row["gc_batch_id"]),
                            expected_byte_size=byte_sizes[str(record["artifact_id"])],
                        ) is not None:
                            moved.append(record)
                        else:
                            raise _PublishedBytesUnavailable(
                                f"GC quarantine bytes are unavailable: {record['artifact_id']}"
                            )
                    if len(moved) == len(records):
                        self._finish_quarantine_batch(
                            row,
                            records=moved,
                            state="COMPLETED",
                            receipt_result="QUARANTINED",
                            exact_bytes=sum(byte_sizes.values()),
                            details={"reconciled": True},
                            now=datetime.now(timezone.utc),
                            byte_sizes=byte_sizes,
                        )
                        completed += 1
                else:
                    # Resume a PURGE that lost the process before its Catalog
                    # boundary. A missing quarantine file is an absence proof;
                    # a valid file is still an admitted move that must be
                    # deleted now. Corrupt bytes raise and close the batch as
                    # FAILED instead of retrying forever.
                    byte_sizes = self._validated_gc_byte_sizes(records)
                    apply_evidence = True
                    purged: list[dict[str, Any]] = []
                    for record in records:
                        if record["state"] == "PURGED":
                            purged.append(record)
                            continue
                        try:
                            if not self.store.purge_quarantined_bytes(
                                str(record["artifact_id"]),
                                str(record["quarantine_storage_key"]),
                                expected_byte_size=byte_sizes[str(record["artifact_id"])],
                            ):
                                raise StagingNotFound("purge absence was not confirmed")
                        except StagingNotFound:
                            # The exact file is already absent; this is the
                            # required durable absence proof after process loss.
                            pass
                        purged.append(record)
                    if len(purged) == len(records):
                        self._write(
                            lambda repository: self._reconcile_purge_rows(
                                repository, row, purged, byte_sizes
                            )
                        )
                        completed += 1
            except Exception as exc:
                failed += 1
                try:
                    self._fail_gc_execution(
                        row,
                        records,
                        exc,
                        apply_evidence=apply_evidence,
                    )
                except Exception:
                    pass
                try:
                    self._record_error(
                        intent_id=None,
                        artifact_id=None,
                        phase="RECONCILIATION",
                        error_code="ARTIFACT_GC_RECONCILIATION_REQUIRED",
                        observed_state={"gc_batch_id": row["gc_batch_id"], "error": str(exc)},
                    )
                except Exception:
                    pass
        return {
            "gc_batches_seen": len(rows),
            "gc_batches_completed": completed,
            "gc_batches_failed": failed,
            "gc_restores_seen": len(restore_rows),
            "gc_restores_completed": restores_completed,
            "gc_restores_failed": restores_failed,
        }

    @staticmethod
    def _reconcile_purge_rows(
        repository,
        row: Mapping[str, Any],
        records: Sequence[Mapping[str, Any]],
        byte_sizes: Mapping[str, int],
    ):
        connection = repository.uow.connection
        now = _wire_time(datetime.now(timezone.utc))
        for record in records:
            connection.execute(
                "UPDATE artifact SET state='DELETED', deleted_at=? WHERE artifact_id=? AND state='QUARANTINED'",
                (now, record["artifact_id"]),
            )
            connection.execute(
                "UPDATE artifact_quarantine SET state='PURGED' WHERE artifact_id=? AND gc_batch_id=? AND state='QUARANTINED'",
                (record["artifact_id"], record["gc_batch_id"]),
            )
        repository.transition_gc_batch(
            str(row["gc_batch_id"]), expected_state="EXECUTING", target_state="COMPLETED", completed_at=now
        )
        return repository.create_gc_receipt(
            {
                "receipt_id": _mint_id("agr_"),
                "gc_batch_id": str(row["gc_batch_id"]),
                "result": "PURGED",
                "exact_artifact_ids_hash": str(row["exact_artifact_ids_hash"]),
                "exact_bytes": sum(byte_sizes.values()),
                "reclaimed_bytes": sum(byte_sizes[str(record["artifact_id"])] for record in records),
                "created_at": now,
                "details_json": _canonical_text({"reconciled": True}),
            }
        )


class SQLiteArtifactPublicationPort:
    """Persist one WS-C publication through the active WS-B PUBLISH transaction."""

    def __init__(self, unit_of_work: SQLiteUnitOfWork) -> None:
        if unit_of_work.mode is not TransactionMode.PUBLISH:
            raise ValueError("artifact publication requires a PUBLISH UnitOfWork")
        if not unit_of_work.active:
            raise RuntimeError("artifact publication requires an active UnitOfWork")
        self.unit_of_work = unit_of_work
        self.registry = SQLiteRepositoryRegistry(unit_of_work)

    def publish(
        self,
        publication: ArtifactPublication,
        *,
        promotion_intent_id: str | None = None,
    ) -> None:
        descriptor = publication.descriptor
        intent = None
        if promotion_intent_id is not None:
            intent = self.registry.artifact.get_promotion_intent(promotion_intent_id)
            if intent is None:
                raise ValueError("promotion intent does not exist")
            expected_sha256 = str(intent["expected_sha256"])
            expected_artifact_id = "art_sha256_" + expected_sha256
            expected_staging_key = f".staging/{intent['staging_token']}.stage"
            if (
                str(intent["artifact_id"]) != expected_artifact_id
                or descriptor.artifact_id != expected_artifact_id
                or descriptor.sha256 != expected_sha256
                or descriptor.byte_size != int(intent["expected_byte_size"])
                or str(intent["staging_key"]) != expected_staging_key
                or descriptor.storage_key != str(intent["final_storage_key"])
            ):
                raise ValueError("promotion intent content identity or storage key is inconsistent")
            if intent["artifact_id"] != descriptor.artifact_id:
                raise ValueError("promotion intent and Catalog Artifact identities differ")
            if intent["state"] not in {
                "FINAL_PRESENT",
                "CATALOG_COMMITTED",
                "CLEANUP_PENDING",
                "FINALIZED",
            }:
                raise ValueError("promotion intent is not at the Catalog commit boundary")
            persisted_descriptor = json.loads(str(intent["descriptor_json"]))
            if not isinstance(persisted_descriptor, Mapping) or _canonical_text(
                persisted_descriptor
            ) != str(intent["descriptor_json"]):
                raise ValueError("promotion intent descriptor JSON is not canonical")
            if _canonical_text(persisted_descriptor) != _canonical_text(_descriptor_wire(descriptor)):
                raise ValueError("Catalog publication descriptor is not authorized by the promotion intent")
            persisted_references = json.loads(str(intent["references_json"]))
            try:
                if not isinstance(persisted_references, list) or _canonical_text(
                    persisted_references
                ) != str(intent["references_json"]):
                    raise ValueError("promotion intent references JSON is not canonical")
                if any(not isinstance(value, Mapping) for value in persisted_references):
                    raise ValueError("promotion intent reference shape is invalid")
                reference_ids = {
                    str(value["artifact_reference_id"]) for value in persisted_references
                }
                if len(reference_ids) != len(persisted_references):
                    raise ValueError("promotion intent contains duplicate references")
                if len(_reference_semantic_signature(persisted_references)) != len(
                    persisted_references
                ):
                    raise ValueError("promotion intent contains duplicate owner bindings")
            except (KeyError, TypeError) as exc:
                raise ValueError("promotion intent reference shape is invalid") from exc
            requested_references = tuple(
                _reference_wire(reference) for reference in publication.active_references
            )
            if _reference_set_signature(persisted_references) != _reference_set_signature(
                requested_references
            ):
                raise ValueError("Catalog publication references are not authorized by the promotion intent")
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
            }
            if any(existing.get(key) != value for key, value in expected.items()):
                raise ValueError(
                    "existing published Artifact metadata conflicts with exact bytes"
                )
            if existing["state"] == "STAGED":
                self.registry.artifact.publish_verified(
                    descriptor.artifact_id,
                    sha256=descriptor.sha256,
                    published_at=_wire_time(descriptor.published_at),
                )
            elif existing["state"] != "PUBLISHED":
                raise ValueError("existing Artifact is not publishable")
        for reference in publication.active_references:
            self.registry.artifact.add_reference(
                _reference_wire(reference)
            )
        if promotion_intent_id is not None:
            assert intent is not None
            if intent["state"] == "FINAL_PRESENT":
                self.registry.artifact.transition_promotion_intent(
                    promotion_intent_id,
                    expected_state="FINAL_PRESENT",
                    expected_state_version=int(intent["state_version"]),
                    target_state="CATALOG_COMMITTED",
                    updated_at=_wire_time(datetime.now(timezone.utc)),
                )
