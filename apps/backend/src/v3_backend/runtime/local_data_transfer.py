"""Correlated, bounded native-file transfer into the canonical Artifact owner."""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, TYPE_CHECKING

from v3_backend.adapters.artifact_store import BoundedStagingWriter
from v3_backend.errors.exceptions import (
    ConflictError,
    InvalidArgumentError,
    NotFoundError,
    ResourceRejectedError,
    TruthPreconditionFailedError,
)
from v3_backend.provenance.canonical_hash import canonical_sha256

if TYPE_CHECKING:
    from .product_runtime import ProductRuntime


LOCAL_DATA_TRANSFER_PROTOCOL = "v3.local-data-transfer/1.0.0"
LOCAL_DATA_RAW_ROLE = "LOCAL_DATA_RAW_FILE"
MAX_LOCAL_DATA_BYTES = 256 * 1024 * 1024
MAX_LOCAL_DATA_CHUNK_BYTES = 256 * 1024
MAX_ACTIVE_TRANSFERS = 4
TRANSFER_TTL = timedelta(minutes=10)
_TRANSFER_ID_PREFIX = "ldt_"
_MEDIA_TYPES = frozenset({"text/csv", "application/vnd.apache.parquet"})


@dataclass(slots=True)
class _ActiveTransfer:
    transfer_id: str
    project_id: str
    project_context_revision_id: str
    display_name: str
    media_type: str
    expected_byte_size: int
    writer: BoundedStagingWriter
    expires_at: datetime


def _bounded_text(value: object, name: str, *, maximum: int = 255) -> str:
    if not isinstance(value, str):
        raise InvalidArgumentError(f"{name} must be a string")
    text = value.strip()
    if not text or len(text) > maximum:
        raise InvalidArgumentError(f"{name} must be a bounded non-empty string")
    return text


def _require_int(value: object, name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum or value > maximum:
        raise InvalidArgumentError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


def _require_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise InvalidArgumentError(f"{name} must be lowercase SHA-256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise InvalidArgumentError(f"{name} must be lowercase SHA-256") from exc
    if value != value.lower():
        raise InvalidArgumentError(f"{name} must be lowercase SHA-256")
    return value


class ProductLocalDataTransferService:
    """Own live staging handles; callers receive only correlated receipts."""

    def __init__(self, product: ProductRuntime) -> None:
        self._product = product
        self._active: dict[str, _ActiveTransfer] = {}
        self._lock = RLock()

    def handle(self, kind: str, message: Mapping[str, Any]) -> dict[str, Any]:
        if message.get("protocol_version") != LOCAL_DATA_TRANSFER_PROTOCOL:
            raise InvalidArgumentError("unsupported local-data transfer protocol_version")
        if kind == "localData.beginTransfer":
            return self._begin(message)
        if kind == "localData.appendChunk":
            return self._append(message)
        if kind == "localData.finishTransfer":
            return self._finish(message)
        if kind == "localData.abortTransfer":
            return self._abort(message)
        raise InvalidArgumentError("unknown local-data transfer control kind")

    def _sweep_expired_locked(self, now: datetime) -> None:
        expired = [key for key, item in self._active.items() if item.expires_at <= now]
        for key in expired:
            item = self._active.pop(key)
            item.writer.abort()

    def _begin(self, message: Mapping[str, Any]) -> dict[str, Any]:
        expected = {
            "kind", "protocol_version", "project_id", "project_context_revision_id",
            "display_name", "media_type", "expected_byte_size",
        }
        if set(message) != expected:
            raise InvalidArgumentError("localData.beginTransfer fields do not match the closed shape")
        project_id = _bounded_text(message["project_id"], "project_id", maximum=200)
        context_id = _bounded_text(
            message["project_context_revision_id"],
            "project_context_revision_id",
            maximum=200,
        )
        self._product.require_project_context_ownership(project_id, context_id)
        if self._product.current_revision(project_id)["project_context_revision_id"] != context_id:
            raise ConflictError("local-data transfer requires the current project context revision")
        display_name = _bounded_text(message["display_name"], "display_name")
        if Path(display_name).name != display_name:
            raise InvalidArgumentError("display_name must be a flat filename")
        media_type = _bounded_text(message["media_type"], "media_type", maximum=100)
        if media_type not in _MEDIA_TYPES:
            raise InvalidArgumentError("local-data media_type is not admitted")
        expected_size = _require_int(
            message["expected_byte_size"],
            "expected_byte_size",
            minimum=1,
            maximum=MAX_LOCAL_DATA_BYTES,
        )
        now = datetime.now(timezone.utc)
        with self._lock:
            self._sweep_expired_locked(now)
            if len(self._active) >= MAX_ACTIVE_TRANSFERS:
                raise ResourceRejectedError(
                    "local-data transfer capacity is exhausted",
                    details={"limit": MAX_ACTIVE_TRANSFERS, "observed": len(self._active)},
                )
            from .product_runtime import mint_v3_id

            transfer_id = mint_v3_id(_TRANSFER_ID_PREFIX)
            writer = self._product.artifact_store.begin_staging(max_bytes=expected_size)
            self._active[transfer_id] = _ActiveTransfer(
                transfer_id=transfer_id,
                project_id=project_id,
                project_context_revision_id=context_id,
                display_name=display_name,
                media_type=media_type,
                expected_byte_size=expected_size,
                writer=writer,
                expires_at=now + TRANSFER_TTL,
            )
        return {
            "kind": "localData.transferReady",
            "transfer_id": transfer_id,
            "next_offset": 0,
            "max_chunk_bytes": MAX_LOCAL_DATA_CHUNK_BYTES,
        }

    def _require_active_locked(self, transfer_id: object) -> _ActiveTransfer:
        identity = _bounded_text(transfer_id, "transfer_id", maximum=200)
        active = self._active.get(identity)
        if active is None:
            raise NotFoundError("local-data transfer is not active")
        return active

    def _append(self, message: Mapping[str, Any]) -> dict[str, Any]:
        expected = {
            "kind", "protocol_version", "transfer_id", "offset",
            "payload_base64", "chunk_sha256",
        }
        if set(message) != expected:
            raise InvalidArgumentError("localData.appendChunk fields do not match the closed shape")
        payload_base64 = _bounded_text(
            message["payload_base64"], "payload_base64", maximum=400_000
        )
        try:
            payload = base64.b64decode(payload_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise InvalidArgumentError("payload_base64 must be canonical base64") from exc
        if base64.b64encode(payload).decode("ascii") != payload_base64:
            raise InvalidArgumentError("payload_base64 must be canonical base64")
        if not payload or len(payload) > MAX_LOCAL_DATA_CHUNK_BYTES:
            raise InvalidArgumentError("local-data chunk byte size is outside the admitted bound")
        expected_chunk_hash = _require_sha256(message["chunk_sha256"], "chunk_sha256")
        if hashlib.sha256(payload).hexdigest() != expected_chunk_hash:
            raise TruthPreconditionFailedError("local-data chunk SHA-256 mismatch")
        with self._lock:
            now = datetime.now(timezone.utc)
            self._sweep_expired_locked(now)
            active = self._require_active_locked(message["transfer_id"])
            offset = _require_int(
                message["offset"], "offset", minimum=0, maximum=active.expected_byte_size
            )
            if offset != active.writer.byte_size:
                raise ConflictError("local-data chunk offset does not match the staged byte count")
            next_offset = active.writer.write(payload)
            active.expires_at = now + TRANSFER_TTL
        return {
            "kind": "localData.chunkAccepted",
            "transfer_id": active.transfer_id,
            "next_offset": next_offset,
        }

    def _finish(self, message: Mapping[str, Any]) -> dict[str, Any]:
        expected = {
            "kind", "protocol_version", "transfer_id",
            "expected_sha256", "expected_byte_size",
        }
        if set(message) != expected:
            raise InvalidArgumentError("localData.finishTransfer fields do not match the closed shape")
        expected_hash = _require_sha256(message["expected_sha256"], "expected_sha256")
        with self._lock:
            self._sweep_expired_locked(datetime.now(timezone.utc))
            active = self._require_active_locked(message["transfer_id"])
            expected_size = _require_int(
                message["expected_byte_size"],
                "expected_byte_size",
                minimum=1,
                maximum=MAX_LOCAL_DATA_BYTES,
            )
            if expected_size != active.expected_byte_size:
                raise TruthPreconditionFailedError("local-data final byte size changed from beginTransfer")
            self._active.pop(active.transfer_id)
        try:
            staging = active.writer.finish()
            if staging.byte_size != expected_size or staging.sha256 != expected_hash:
                raise TruthPreconditionFailedError("local-data final source identity mismatch")
            self._product.require_project_context_ownership(
                active.project_id, active.project_context_revision_id
            )
            if (
                self._product.current_revision(active.project_id)[
                    "project_context_revision_id"
                ]
                != active.project_context_revision_id
            ):
                raise ConflictError(
                    "project context changed before local-data source publication"
                )
            publication = self._product.execution._publish_staged_artifact(
                staging=staging,
                provenance_entity_id="prv_local_data_transfer_" + staging.sha256,
                role=LOCAL_DATA_RAW_ROLE,
                media_type=active.media_type,
                schema_fingerprint=canonical_sha256({"schema": "local-user-source-v1"}),
                references=((active.project_id, LOCAL_DATA_RAW_ROLE),),
            )
        except Exception:
            active.writer.abort()
            raise
        descriptor = publication.descriptor
        return {
            "kind": "localData.sourcePublished",
            "transfer_id": active.transfer_id,
            "source": {
                "artifact_id": descriptor.artifact_id,
                "sha256": descriptor.sha256,
                "byte_size": descriptor.byte_size,
                "media_type": descriptor.media_type,
                "display_name": active.display_name,
            },
        }

    def _abort(self, message: Mapping[str, Any]) -> dict[str, Any]:
        expected = {"kind", "protocol_version", "transfer_id"}
        if set(message) != expected:
            raise InvalidArgumentError("localData.abortTransfer fields do not match the closed shape")
        with self._lock:
            self._sweep_expired_locked(datetime.now(timezone.utc))
            transfer_id = _bounded_text(message["transfer_id"], "transfer_id", maximum=200)
            active = self._active.pop(transfer_id, None)
        if active is not None:
            active.writer.abort()
        return {"kind": "localData.transferAborted", "transfer_id": transfer_id}

    def close(self) -> None:
        with self._lock:
            active = tuple(self._active.values())
            self._active.clear()
        for item in active:
            item.writer.abort()


__all__ = [
    "LOCAL_DATA_TRANSFER_PROTOCOL",
    "MAX_ACTIVE_TRANSFERS",
    "MAX_LOCAL_DATA_BYTES",
    "MAX_LOCAL_DATA_CHUNK_BYTES",
    "ProductLocalDataTransferService",
]
