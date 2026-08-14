"""Same-volume, content-addressed filesystem publication adapter."""

from __future__ import annotations

import hashlib
import codecs
import json
import os
import re
import secrets
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO

from v3_backend.domain.artifacts.exceptions import (
    ArtifactCollision,
    IntegrityMismatch,
    FormatRejected,
    StagingNotFound,
)
from v3_backend.domain.artifacts.identity import (
    artifact_id_from_sha256,
    sha256_from_artifact_id,
    storage_key_for_sha256,
    validate_sha256,
)
from v3_backend.domain.artifacts.model import ArtifactDescriptor
from v3_backend.domain.artifacts.policy import SafeFormatPolicy
from v3_backend.provenance.canonical_hash import canonical_json_bytes


_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{32,128}")
_CHUNK_SIZE = 1024 * 1024
_MAX_CANONICAL_JSON_BYTES = 16 * 1024 * 1024


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _fsync_directory(path: Path) -> None:
    """Flush directory metadata where the host exposes directory handles."""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        if os.name == "nt":
            return
        raise
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
            byte_size += len(chunk)
    return digest.hexdigest(), byte_size


def _require_regular_file(path: Path, label: str) -> None:
    mode = path.lstat().st_mode
    if not stat.S_ISREG(mode):
        raise IntegrityMismatch(f"{label} must be a regular file")


def _validate_safe_payload(path: Path, safe_format_id: str | None) -> None:
    if safe_format_id == "utf8-text-v1":
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        try:
            with path.open("rb") as handle:
                while chunk := handle.read(_CHUNK_SIZE):
                    decoder.decode(chunk, final=False)
                decoder.decode(b"", final=True)
        except UnicodeDecodeError as exc:
            raise FormatRejected("declared UTF-8 text contains invalid bytes") from exc
        return
    if safe_format_id == "canonical-json-v1":
        if path.stat().st_size > _MAX_CANONICAL_JSON_BYTES:
            raise FormatRejected("canonical JSON control artifacts must remain small")
        try:
            payload = path.read_bytes()
            text = payload.decode("utf-8")

            def closed_object(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError(f"duplicate JSON key: {key}")
                    result[key] = value
                return result

            parsed = json.loads(
                text,
                object_pairs_hook=closed_object,
                parse_float=lambda value: (_ for _ in ()).throw(ValueError("floats are forbidden")),
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError("non-finite values are forbidden")),
            )
            canonical = json.dumps(
                parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise FormatRejected("invalid canonical JSON control artifact") from exc
        if canonical != payload:
            raise FormatRejected("JSON bytes are not in canonical form")
        return
    if safe_format_id == "canonical-finite-json-v1":
        if path.stat().st_size > _MAX_CANONICAL_JSON_BYTES:
            raise FormatRejected("canonical JSON control artifacts must remain small")
        try:
            payload = path.read_bytes()
            text = payload.decode("utf-8")

            def closed_finite_object(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError(f"duplicate JSON key: {key}")
                    result[key] = value
                return result

            parsed = json.loads(
                text,
                object_pairs_hook=closed_finite_object,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError("non-finite values are forbidden")
                ),
            )

            canonical = canonical_json_bytes(parsed)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise FormatRejected("invalid canonical finite JSON artifact") from exc
        if canonical != payload:
            raise FormatRejected("JSON bytes are not in canonical form")
        return
    if safe_format_id is None:
        raise FormatRejected("publishable payload lacks an admitted safe-format validator")
    raise FormatRejected(f"unknown safe-format validator: {safe_format_id}")


@dataclass(frozen=True, slots=True)
class StagingReceipt:
    staging_token: str
    sha256: str
    byte_size: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PublicationResult:
    descriptor: ArtifactDescriptor
    deduplicated: bool
    storage_key: str


class FileSystemArtifactStore:
    """Durable bytes only. Catalog descriptors/references remain behind the UoW port."""

    def __init__(self, root: Path | str, policy: SafeFormatPolicy | None = None) -> None:
        self.root = Path(root).resolve()
        self.staging_root = self.root / ".staging"
        self.content_root = self.root / "sha256"
        self.policy = policy or SafeFormatPolicy.baseline()
        self.staging_root.mkdir(parents=True, exist_ok=True)
        self.content_root.mkdir(parents=True, exist_ok=True)
        if self.staging_root.stat().st_dev != self.content_root.stat().st_dev:
            raise OSError("staging and content roots must be on the same volume")

    def _staging_path(self, token: str) -> Path:
        if not isinstance(token, str) or _TOKEN_RE.fullmatch(token) is None:
            raise StagingNotFound("invalid staging token")
        return self.staging_root / f"{token}.stage"

    def _final_path(self, digest: str) -> Path:
        key = storage_key_for_sha256(digest)
        return self.root.joinpath(*key.split("/"))

    def stage_bytes(self, payload: bytes) -> StagingReceipt:
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        from io import BytesIO

        return self.stage_stream(BytesIO(payload))

    def stage_stream(self, stream: BinaryIO, *, max_bytes: int | None = None) -> StagingReceipt:
        if max_bytes is not None and (not isinstance(max_bytes, int) or max_bytes < 0):
            raise ValueError("max_bytes must be a non-negative integer")
        token = secrets.token_urlsafe(32)
        path = self._staging_path(token)
        digest = hashlib.sha256()
        byte_size = 0
        created_at = _utc_now()
        try:
            with path.open("xb") as handle:
                while True:
                    chunk = stream.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    if not isinstance(chunk, bytes):
                        raise TypeError("binary staging stream must return bytes")
                    byte_size += len(chunk)
                    if max_bytes is not None and byte_size > max_bytes:
                        raise IntegrityMismatch("staged payload exceeds max_bytes")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_directory(self.staging_root)
        except BaseException:
            try:
                path.unlink(missing_ok=True)
            finally:
                raise
        return StagingReceipt(token, digest.hexdigest(), byte_size, created_at)

    def recover_staging(self) -> tuple[StagingReceipt, ...]:
        recovered: list[StagingReceipt] = []
        for path in sorted(self.staging_root.glob("*.stage"), key=lambda value: value.name):
            _require_regular_file(path, "staging entry")
            token = path.name[: -len(".stage")]
            if _TOKEN_RE.fullmatch(token) is None:
                continue
            digest, byte_size = _hash_file(path)
            created_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            recovered.append(StagingReceipt(token, digest, byte_size, created_at))
        return tuple(recovered)

    def discard_staging(
        self,
        staging_token: str,
        *,
        not_newer_than: datetime,
        now: datetime | None = None,
    ) -> bool:
        """Explicitly discard an interrupted stage only after an age cutoff."""

        if not_newer_than.tzinfo is None or not_newer_than.utcoffset() is None:
            raise ValueError("not_newer_than must be timezone-aware")
        path = self._staging_path(staging_token)
        if not path.exists():
            return False
        _require_regular_file(path, "staging entry")
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        observed_now = now or _utc_now()
        if observed_now.tzinfo is None or observed_now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if modified > not_newer_than or modified > observed_now:
            return False
        path.unlink()
        _fsync_directory(self.staging_root)
        return True

    def publish(
        self,
        staging_token: str,
        *,
        expected_sha256: str,
        expected_byte_size: int,
        media_type: str,
        role: str,
        provenance_entity_id: str,
        schema_fingerprint: str | None = None,
        semantic_fingerprint: str | None = None,
        published_at: datetime | None = None,
    ) -> PublicationResult:
        validate_sha256(expected_sha256)
        if not isinstance(expected_byte_size, int) or isinstance(expected_byte_size, bool) or expected_byte_size < 0:
            raise ValueError("expected_byte_size must be a non-negative integer")
        decision = self.policy.require_publishable(role, media_type)
        stage = self._staging_path(staging_token)
        if not stage.exists():
            raise StagingNotFound("staging token does not identify staged bytes")
        _require_regular_file(stage, "staging entry")

        actual_sha256, actual_size = _hash_file(stage)
        if actual_sha256 != expected_sha256:
            raise IntegrityMismatch(
                f"staged SHA-256 mismatch: expected {expected_sha256}, observed {actual_sha256}"
            )
        if actual_size != expected_byte_size:
            raise IntegrityMismatch(
                f"staged byte-size mismatch: expected {expected_byte_size}, observed {actual_size}"
            )
        _validate_safe_payload(stage, decision.safe_format_id)

        final = self._final_path(actual_sha256)
        final.parent.mkdir(parents=True, exist_ok=True)
        deduplicated = False
        try:
            os.link(stage, final)
            # The linked inode/file record was already flushed through the writable
            # staging handle. Windows rejects fsync on a read-only Python handle.
            _fsync_directory(final.parent)
        except FileExistsError:
            _require_regular_file(final, "published artifact")
            existing_sha256, existing_size = _hash_file(final)
            if existing_sha256 != actual_sha256 or existing_size != actual_size:
                raise ArtifactCollision("content-addressed key contains different bytes")
            deduplicated = True

        stage.unlink()
        _fsync_directory(self.staging_root)
        observed_published_at = published_at or _utc_now()
        if observed_published_at.tzinfo is None or observed_published_at.utcoffset() is None:
            raise ValueError("published_at must be timezone-aware")
        created_at = datetime.fromtimestamp(final.stat().st_mtime, timezone.utc)
        if created_at > observed_published_at:
            created_at = observed_published_at
        descriptor = ArtifactDescriptor(
            artifact_id=artifact_id_from_sha256(actual_sha256),
            sha256=actual_sha256,
            byte_size=actual_size,
            media_type=media_type,
            role=role,
            safe_format_id=decision.safe_format_id,
            schema_fingerprint=schema_fingerprint,
            semantic_fingerprint=semantic_fingerprint,
            created_at=created_at,
            published_at=observed_published_at,
            provenance_entity_id=provenance_entity_id,
        )
        return PublicationResult(descriptor, deduplicated, storage_key_for_sha256(actual_sha256))

    def read_bytes(self, artifact_id: str, *, max_bytes: int | None = None) -> bytes:
        digest = sha256_from_artifact_id(artifact_id)
        path = self._final_path(digest)
        _require_regular_file(path, "published artifact")
        if max_bytes is not None and path.stat().st_size > max_bytes:
            raise IntegrityMismatch("artifact exceeds read bound")
        observed_digest, _ = _hash_file(path)
        if observed_digest != digest:
            raise IntegrityMismatch("published bytes no longer match artifact identity")
        return path.read_bytes()

    def delete_published_bytes(self, artifact_id: str) -> bool:
        digest = sha256_from_artifact_id(artifact_id)
        path = self._final_path(digest)
        if not path.exists():
            return True
        _require_regular_file(path, "published artifact")
        observed_digest, _ = _hash_file(path)
        if observed_digest != digest:
            raise ArtifactCollision("refusing to delete bytes that do not match the artifact ID")
        path.unlink()
        _fsync_directory(path.parent)
        return not path.exists()
