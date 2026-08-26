"""Same-volume, content-addressed filesystem publication adapter."""

from __future__ import annotations

import hashlib
import codecs
import json
import os
import re
import secrets
import stat
import shutil
from contextlib import contextmanager
from threading import RLock
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO

from v3_backend.domain.artifacts.exceptions import (
    ArtifactCollision,
    ArtifactScanLimitExceeded,
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
_PROMOTION_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")
_PROMOTING_ENTRY_RE = re.compile(
    r"(?P<sha256>[0-9a-f]{64})\.promoting\.(?P<intent>[A-Za-z0-9_-]{1,128})"
)
_CHUNK_SIZE = 1024 * 1024
_MAX_CANONICAL_JSON_BYTES = 16 * 1024 * 1024
_MAX_BOUNDED_SCAN_ENTRIES = 10_000


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


def _is_reparse_entry(entry: os.stat_result) -> bool:
    return stat.S_ISLNK(entry.st_mode) or bool(
        getattr(entry, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _require_regular_file(path: Path, label: str) -> None:
    entry = path.lstat()
    if _is_reparse_entry(entry) or not stat.S_ISREG(entry.st_mode):
        raise IntegrityMismatch(f"{label} must be a regular file")


def _entry_exists(path: Path) -> bool:
    """Check directory entry existence without following a symlink."""

    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _assert_directory_entry(path: Path, label: str) -> None:
    """Reject symlinked/non-directory namespace components without following them."""

    entry = path.lstat()
    if _is_reparse_entry(entry) or not stat.S_ISDIR(entry.st_mode):
        raise IntegrityMismatch(f"{label} must be a real directory")


def _assert_safe_parent_chain(base: Path, path: Path, label: str) -> None:
    """Reject an existing symlink/non-directory in a store-owned parent chain."""

    try:
        relative = path.relative_to(base)
    except ValueError as exc:
        raise IntegrityMismatch(f"{label} escapes the store-owned root") from exc
    _assert_directory_entry(base, label)
    current = base
    for part in relative.parts[:-1]:
        current /= part
        try:
            _assert_directory_entry(current, f"{label} parent")
        except FileNotFoundError:
            # A missing component and everything below it will be created by
            # _ensure_directory_chain under the namespace lock.  There cannot
            # be a deeper existing component once a parent is absent.
            break


def _ensure_directory_chain(base: Path, path: Path, label: str) -> None:
    """Create a store-owned directory chain without following symlinks."""

    try:
        relative = path.relative_to(base)
    except ValueError as exc:
        raise IntegrityMismatch(f"{label} escapes the store-owned root") from exc
    _assert_directory_entry(base, label)
    current = base
    for part in relative.parts:
        current /= part
        try:
            _assert_directory_entry(current, f"{label} component")
        except FileNotFoundError:
            try:
                current.mkdir()
            except FileExistsError:
                # Re-check the entry rather than accepting a concurrent
                # replacement with an unsafe type.
                pass
            _assert_directory_entry(current, f"{label} component")


def _validate_canonical_finite_json(path: Path) -> None:
    if path.stat().st_size > _MAX_CANONICAL_JSON_BYTES:
        raise FormatRejected("canonical JSON control artifacts must remain small")
    try:
        payload = path.read_bytes()
        text = payload.decode("utf-8")

        def closed_finite_object(pairs):
            parsed_object = {}
            for key, value in pairs:
                if key in parsed_object:
                    raise ValueError(f"duplicate JSON key: {key}")
                parsed_object[key] = value
            return parsed_object

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


def _validate_flat_parquet(path: Path) -> None:
    """Re-open admitted Parquet bytes at the final publication boundary."""

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise FormatRejected("the admitted PyArrow runtime is unavailable") from exc
    try:
        parquet = pq.ParquetFile(path)
        if parquet.metadata.num_columns <= 0:
            raise FormatRejected("Parquet must contain at least one column")
        for field in parquet.schema_arrow:
            if (
                pa.types.is_nested(field.type)
                or isinstance(field.type, pa.ExtensionType)
                or pa.types.is_dictionary(field.type)
                or pa.types.is_binary(field.type)
                or pa.types.is_large_binary(field.type)
            ):
                raise FormatRejected("Parquet publication accepts flat primitive columns only")
    except FormatRejected:
        raise
    except Exception as exc:
        raise FormatRejected("invalid Parquet artifact") from exc


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
        _validate_canonical_finite_json(path)
        return
    if safe_format_id == "flat-parquet-v1":
        _validate_flat_parquet(path)
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


class BoundedStagingWriter:
    """One exclusive incremental Artifact staging lease.

    The writer owns the open handle and the running content identity, so a
    framed transport can stage bounded chunks without assembling the source
    in memory or reopening a caller-controlled path.
    """

    def __init__(
        self,
        *,
        path: Path,
        staging_root: Path,
        staging_token: str,
        max_bytes: int,
        created_at: datetime,
        promotion_lock: RLock,
    ) -> None:
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
            raise ValueError("max_bytes must be a positive integer")
        self._path = path
        self._staging_root = staging_root
        self._staging_token = staging_token
        self._max_bytes = max_bytes
        self._created_at = created_at
        self._promotion_lock = promotion_lock
        self._digest = hashlib.sha256()
        self._byte_size = 0
        # Hold the store namespace lease for the complete incremental write.
        # A GC snapshot must never observe a partial stage and then delete the
        # final bytes that the writer is about to publish.
        self._promotion_lock.acquire()
        try:
            self._handle = path.open("xb")
        except BaseException:
            self._promotion_lock.release()
            raise
        self._lock_held = True
        self._closed = False

    def _release_namespace_lock(self) -> None:
        if self._lock_held:
            self._lock_held = False
            self._promotion_lock.release()

    @property
    def byte_size(self) -> int:
        return self._byte_size

    def write(self, payload: bytes) -> int:
        if self._closed:
            raise ValueError("staging writer is closed")
        if not isinstance(payload, bytes) or not payload:
            raise TypeError("staging chunk must be non-empty bytes")
        observed = self._byte_size + len(payload)
        if observed > self._max_bytes:
            raise IntegrityMismatch("staged payload exceeds max_bytes")
        self._handle.write(payload)
        self._digest.update(payload)
        self._byte_size = observed
        return observed

    def finish(self) -> StagingReceipt:
        if self._closed:
            raise ValueError("staging writer is closed")
        try:
            self._handle.flush()
            os.fsync(self._handle.fileno())
            self._handle.close()
            self._closed = True
            _fsync_directory(self._staging_root)
            return StagingReceipt(
                self._staging_token,
                self._digest.hexdigest(),
                self._byte_size,
                self._created_at,
            )
        finally:
            self._release_namespace_lock()

    def abort(self) -> None:
        try:
            if not self._closed:
                self._handle.close()
                self._closed = True
            with self._promotion_lock:
                self._path.unlink(missing_ok=True)
                _fsync_directory(self._staging_root)
        finally:
            self._release_namespace_lock()


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
        self.quarantine_root = self.root / ".quarantine"
        self.content_root = self.root / "sha256"
        self.policy = policy or SafeFormatPolicy.baseline()
        self._promotion_lock = RLock()
        self.staging_root.mkdir(parents=True, exist_ok=True)
        self.quarantine_root.mkdir(parents=True, exist_ok=True)
        self.content_root.mkdir(parents=True, exist_ok=True)
        _assert_directory_entry(self.staging_root, "staging root")
        _assert_directory_entry(self.quarantine_root, "quarantine root")
        _assert_directory_entry(self.content_root, "content root")
        if len({
            self.staging_root.stat().st_dev,
            self.content_root.stat().st_dev,
            self.quarantine_root.stat().st_dev,
        }) != 1:
            raise OSError("staging and content roots must be on the same volume")

    @contextmanager
    def namespace_lock(self):
        """Serialize stage, promotion, quarantine and purge namespace changes.

        The lock is process-local; durable Catalog barriers remain responsible
        for cross-process admission. Callers hold this lock across a complete
        GC byte move so a same-process stage writer cannot enter mid-flight.
        """

        with self._promotion_lock:
            yield

    def _staging_path(self, token: str) -> Path:
        if not isinstance(token, str) or _TOKEN_RE.fullmatch(token) is None:
            raise StagingNotFound("invalid staging token")
        return self.staging_root / f"{token}.stage"

    def staging_path(self, token: str) -> Path:
        """Return the canonical store-owned stage path for a valid token."""

        return self._staging_path(token)

    def _final_path(self, digest: str) -> Path:
        key = storage_key_for_sha256(digest)
        path = self.root.joinpath(*key.split("/"))
        _assert_safe_parent_chain(self.content_root, path, "content path")
        return path

    def final_path(self, artifact_id: str) -> Path:
        return self._final_path(sha256_from_artifact_id(artifact_id))

    def _quarantine_path(self, storage_key: str) -> Path:
        if (
            not isinstance(storage_key, str)
            or not storage_key.startswith(".quarantine/")
            or "\\" in storage_key
            or any(part in {"", ".", ".."} for part in storage_key.split("/"))
            or any(
                re.fullmatch(r"[A-Za-z0-9_.-]+", part) is None
                for part in storage_key.split("/")
            )
        ):
            raise IntegrityMismatch("quarantine storage key is not canonical")
        path = self.root.joinpath(*storage_key.split("/"))
        if not path.is_relative_to(self.root):
            raise IntegrityMismatch("quarantine storage key escapes the artifact root")
        _assert_safe_parent_chain(self.quarantine_root, path, "quarantine path")
        return path

    def quarantine_path(self, artifact_id: str, gc_batch_id: str) -> tuple[Path, str]:
        digest = sha256_from_artifact_id(artifact_id)
        if not isinstance(gc_batch_id, str) or _PROMOTION_ID_RE.fullmatch(gc_batch_id) is None:
            raise ValueError("gc_batch_id is not a safe storage identity")
        relative = f".quarantine/{digest[:2]}/{digest}.{gc_batch_id}.bytes"
        return self._quarantine_path(relative), relative

    def stage_bytes(self, payload: bytes) -> StagingReceipt:
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        from io import BytesIO

        return self.stage_stream(BytesIO(payload))

    def begin_staging(self, *, max_bytes: int) -> BoundedStagingWriter:
        """Open an exclusive bounded writer for correlated chunk transport."""

        token = secrets.token_urlsafe(32)
        return BoundedStagingWriter(
            path=self._staging_path(token),
            staging_root=self.staging_root,
            staging_token=token,
            max_bytes=max_bytes,
            created_at=_utc_now(),
            promotion_lock=self._promotion_lock,
        )

    def stage_stream(self, stream: BinaryIO, *, max_bytes: int | None = None) -> StagingReceipt:
        if max_bytes is not None and (
            not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 0
        ):
            raise ValueError("max_bytes must be a non-negative integer")
        token = secrets.token_urlsafe(32)
        path = self._staging_path(token)
        digest = hashlib.sha256()
        byte_size = 0
        created_at = _utc_now()
        with self._promotion_lock:
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

    def open_staged(self, staging_token: str) -> BinaryIO:
        """Open immutable staged bytes for validation before publication."""

        with self._promotion_lock:
            path = self._staging_path(staging_token)
            if not _entry_exists(path):
                raise StagingNotFound("staging token does not identify staged bytes")
            _require_regular_file(path, "staging entry")
            return path.open("rb")

    def staging_receipt(self, staging_token: str) -> StagingReceipt:
        """Read one exact stage without scanning the whole staging namespace."""

        with self._promotion_lock:
            path = self._staging_path(staging_token)
            if not _entry_exists(path):
                raise StagingNotFound("staging token does not identify staged bytes")
            _require_regular_file(path, "staging entry")
            digest, byte_size = _hash_file(path)
            created_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            return StagingReceipt(staging_token, digest, byte_size, created_at)

    def iter_staging_entries(
        self,
        *,
        limit: int | None = 256,
        after_entry_name: str | None = None,
    ) -> tuple[str, ...]:
        """Return bounded stage entry names, including malformed entries.

        Recovery must not silently omit a namespace entry merely because its
        filename is not a valid staging token.  Names are returned separately
        from receipts so the coordinator can quarantine malformed or
        non-regular entries without treating them as publication evidence.
        """

        if limit is not None and not 1 <= limit <= 10_000:
            raise ValueError("staging scan limit must be between 1 and 10000")
        if after_entry_name is not None and (
            not isinstance(after_entry_name, str)
            or not after_entry_name
            or "/" in after_entry_name
            or "\\" in after_entry_name
            or after_entry_name in {".", ".."}
        ):
            raise ValueError("staging scan cursor is invalid")
        names: list[str] = []
        with self._promotion_lock:
            with os.scandir(self.staging_root) as entries:
                for entry in entries:
                    names.append(entry.name)
                    if len(names) > _MAX_BOUNDED_SCAN_ENTRIES:
                        raise ArtifactScanLimitExceeded(
                            "staging scan exceeded the bounded limit"
                        )
        ordered = sorted(names)
        if after_entry_name is not None:
            ordered = [name for name in ordered if name > after_entry_name]
        if limit is not None:
            ordered = ordered[:limit]
        return tuple(ordered)

    def recover_staging(
        self,
        *,
        limit: int | None = None,
        after_token: str | None = None,
    ) -> tuple[StagingReceipt, ...]:
        if limit is not None and not 1 <= limit <= 10_000:
            raise ValueError("staging scan limit must be between 1 and 10000")
        if after_token is not None and _TOKEN_RE.fullmatch(after_token) is None:
            raise ValueError("staging scan cursor is invalid")
        entry_names = self.iter_staging_entries(
            limit=limit,
            after_entry_name=None if after_token is None else after_token + ".stage",
        )
        recovered: list[StagingReceipt] = []
        for entry_name in entry_names:
            if not entry_name.endswith(".stage"):
                continue
            token = entry_name[: -len(".stage")]
            if _TOKEN_RE.fullmatch(token) is None:
                continue
            recovered.append(self.staging_receipt(token))
        return tuple(recovered)

    def quarantine_orphan_stage_entry(self, entry_name: str) -> str:
        """Quarantine one untracked stage entry without trusting its name/type."""

        if (
            not isinstance(entry_name, str)
            or not entry_name
            or "/" in entry_name
            or "\\" in entry_name
            or "\x00" in entry_name
            or entry_name in {".", ".."}
        ):
            raise ValueError("staging entry name is not safe")
        source = self.staging_root / entry_name
        is_stage_entry = entry_name.endswith(".stage")
        token = entry_name[: -len(".stage")] if is_stage_entry else ""
        destination_name = (
            entry_name
            if is_stage_entry and _TOKEN_RE.fullmatch(token) is not None
            else "invalid-"
            + hashlib.sha256(entry_name.encode("utf-8")).hexdigest()
            + (".stage" if is_stage_entry else ".entry")
        )
        destination = self.quarantine_root / "orphans" / destination_name
        with self._promotion_lock:
            _ensure_directory_chain(
                self.quarantine_root, destination.parent, "orphan quarantine path"
            )
            if not _entry_exists(source):
                return destination.relative_to(self.root).as_posix()
            if _entry_exists(destination):
                raise ArtifactCollision("orphan staging quarantine key collision")
            # os.replace moves a symlink or other non-regular entry itself;
            # it never follows untrusted stage contents during quarantine.
            os.replace(source, destination)
            _fsync_directory(self.staging_root)
            _fsync_directory(destination.parent)
        return destination.relative_to(self.root).as_posix()

    def quarantine_orphan_stage(self, staging_token: str) -> str:
        """Move an untracked stage out of the publish namespace without trusting it."""
        if _TOKEN_RE.fullmatch(staging_token) is None:
            raise StagingNotFound("invalid staging token")
        return self.quarantine_orphan_stage_entry(staging_token + ".stage")

    def iter_final_artifact_ids(
        self,
        *,
        limit: int = 256,
        after_artifact_id: str | None = None,
    ) -> tuple[str, ...]:
        """Return a bounded scan of canonical content files for orphan detection."""

        if not 1 <= limit <= 10_000:
            raise ValueError("final artifact scan limit must be between 1 and 10000")
        if after_artifact_id is not None:
            sha256_from_artifact_id(after_artifact_id)
        found: list[str] = []
        with self._promotion_lock:
            paths: list[Path] = []
            for path in self.content_root.rglob("*"):
                paths.append(path)
                if limit is not None and len(paths) > _MAX_BOUNDED_SCAN_ENTRIES:
                    raise ArtifactScanLimitExceeded(
                        "final artifact scan exceeded the bounded limit"
                    )
            for path in sorted(paths, key=lambda value: value.as_posix()):
                if len(found) >= limit:
                    break
                try:
                    path.lstat()
                except FileNotFoundError:
                    continue
                if re.fullmatch(r"[0-9a-f]{64}", path.name) is None:
                    continue
                relative = path.relative_to(self.content_root).parts
                if (
                    len(relative) != 3
                    or relative[0] != path.name[:2]
                    or relative[1] != path.name[2:4]
                    or relative[2] != path.name
                ):
                    continue
                artifact_id = artifact_id_from_sha256(path.name)
                if after_artifact_id is not None and artifact_id <= after_artifact_id:
                    continue
                found.append(artifact_id)
        return tuple(found)

    def iter_promoting_entries(
        self,
        *,
        limit: int = 256,
        after_entry_name: str | None = None,
    ) -> tuple[str, ...]:
        """Return bounded atomic-promotion remnants for restart reconciliation."""

        if not 1 <= limit <= 10_000:
            raise ValueError("promotion scan limit must be between 1 and 10000")
        if after_entry_name is not None and (
            not isinstance(after_entry_name, str)
            or not after_entry_name
            or "/" in after_entry_name
            or "\\" in after_entry_name
            or after_entry_name in {".", ".."}
        ):
            raise ValueError("promotion scan cursor is invalid")
        with self._promotion_lock:
            found: list[str] = []
            for path in self.content_root.rglob("*"):
                if _PROMOTING_ENTRY_RE.fullmatch(path.name) is None:
                    continue
                try:
                    path.lstat()
                except FileNotFoundError:
                    continue
                relative = path.relative_to(self.content_root).parts
                if (
                    len(relative) != 3
                    or relative[0] != path.name[:2]
                    or relative[1] != path.name[2:4]
                    or relative[2] != path.name
                ):
                    continue
                found.append(path.name)
                if len(found) > _MAX_BOUNDED_SCAN_ENTRIES:
                    raise ArtifactScanLimitExceeded(
                        "promotion scan exceeded the bounded limit"
                    )
            ordered = sorted(set(found))
            if after_entry_name is not None:
                ordered = [name for name in ordered if name > after_entry_name]
            return tuple(ordered[:limit])

    def _promoting_path(self, entry_name: str) -> tuple[Path, str, str]:
        match = _PROMOTING_ENTRY_RE.fullmatch(entry_name)
        if match is None:
            raise IntegrityMismatch("promotion entry name is not canonical")
        digest = match.group("sha256")
        intent_id = match.group("intent")
        final = self._final_path(digest)
        return final.with_name(entry_name), digest, intent_id

    def promoting_entry_identity(self, entry_name: str) -> tuple[str, str]:
        """Return the byte identity and intent encoded by one safe entry name."""

        _, digest, intent_id = self._promoting_path(entry_name)
        return artifact_id_from_sha256(digest), intent_id

    def verify_promoting_entry(self, entry_name: str) -> tuple[str, int]:
        """Verify one promoting remnant without changing either namespace."""

        with self._promotion_lock:
            promoting, digest, _ = self._promoting_path(entry_name)
            if not _entry_exists(promoting):
                raise StagingNotFound("promoting artifact is missing")
            _require_regular_file(promoting, "promoting artifact")
            observed = _hash_file(promoting)
            if observed[0] != digest:
                raise ArtifactCollision("promoting bytes do not match their content identity")
            return observed

    def recover_promoting_entry(self, entry_name: str) -> bool:
        """Complete one verified promoting rename, including a dedup cleanup."""

        with self._promotion_lock:
            promoting, digest, _ = self._promoting_path(entry_name)
            final = self._final_path(digest)
            if not _entry_exists(promoting):
                return False
            _require_regular_file(promoting, "promoting artifact")
            observed = _hash_file(promoting)
            if observed[0] != digest:
                raise ArtifactCollision("promoting bytes do not match their content identity")
            _ensure_directory_chain(self.content_root, final.parent, "content path")
            if _entry_exists(final):
                _require_regular_file(final, "published artifact")
                if _hash_file(final) != observed:
                    raise ArtifactCollision("final and promoting bytes conflict")
                promoting.unlink()
                _fsync_directory(final.parent)
            else:
                os.replace(promoting, final)
                _fsync_directory(final.parent)
            return self.verify_final_bytes(
                artifact_id_from_sha256(digest), expected_byte_size=observed[1]
            ) == (digest, observed[1])

    def isolate_promoting_entry(self, entry_name: str, *, reason: str) -> str | None:
        """Isolate an unadmitted promoting entry without following its type."""

        with self._promotion_lock:
            source, digest, intent_id = self._promoting_path(entry_name)
            if not _entry_exists(source):
                return None
            safe_reason = re.sub(r"[^A-Za-z0-9_-]+", "_", reason)[:48] or "unknown"
            destination = self.quarantine_root / "conflicts" / (
                f"{digest}.promoting.{intent_id}.{safe_reason}.entry"
            )
            _ensure_directory_chain(
                self.quarantine_root, destination.parent, "promotion quarantine path"
            )
            if _entry_exists(destination):
                raise ArtifactCollision("promotion quarantine key collision")
            os.replace(source, destination)
            _fsync_directory(source.parent)
            _fsync_directory(destination.parent)
            return destination.relative_to(self.root).as_posix()

    def isolate_final_bytes(self, artifact_id: str, *, reason: str) -> str | None:
        """Move an untrusted canonical-path entry to app-owned quarantine.

        The entry may be a regular file, symlink, or directory created by a
        fault/attacker.  Isolation must move the directory entry itself and
        must never follow an untrusted type while trying to preserve evidence.
        """

        with self._promotion_lock:
            source = self.final_path(artifact_id)
            if not _entry_exists(source):
                return None
            try:
                source_entry = source.lstat()
            except FileNotFoundError:
                return None
            mode = source_entry.st_mode
            source_is_regular = stat.S_ISREG(mode) and not _is_reparse_entry(source_entry)
            if source_is_regular:
                observed_digest, _ = _hash_file(source)
                suffix = ".bytes"
            else:
                observed_digest = "nonregular-" + hashlib.sha256(
                    str(mode).encode("ascii")
                ).hexdigest()[:16]
                suffix = ".entry"
            safe_reason = re.sub(r"[^A-Za-z0-9_-]+", "_", reason)[:64] or "unknown"
            destination = self.quarantine_root / "conflicts" / (
                f"{sha256_from_artifact_id(artifact_id)}.{observed_digest}.{safe_reason}{suffix}"
            )
            _ensure_directory_chain(
                self.quarantine_root, destination.parent, "conflict quarantine path"
            )
            if _entry_exists(destination):
                destination_entry = destination.lstat()
                if (
                    source_is_regular
                    and stat.S_ISREG(destination_entry.st_mode)
                    and not _is_reparse_entry(destination_entry)
                ):
                    if _hash_file(destination) != _hash_file(source):
                        raise ArtifactCollision("conflict quarantine key collision")
                    source.unlink()
                else:
                    raise ArtifactCollision("conflict quarantine key collision")
            else:
                os.replace(source, destination)
            _fsync_directory(source.parent)
            _fsync_directory(destination.parent)
            return destination.relative_to(self.root).as_posix()

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
        with self._promotion_lock:
            path = self._staging_path(staging_token)
            if not _entry_exists(path):
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

    def _validated_stage(
        self,
        staging_token: str,
        *,
        expected_sha256: str,
        expected_byte_size: int,
        media_type: str,
        role: str,
    ) -> tuple[Path, str, int, str]:
        validate_sha256(expected_sha256)
        if not isinstance(expected_byte_size, int) or isinstance(expected_byte_size, bool) or expected_byte_size < 0:
            raise ValueError("expected_byte_size must be a non-negative integer")
        decision = self.policy.require_publishable(role, media_type)
        stage = self._staging_path(staging_token)
        if not _entry_exists(stage):
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
        return stage, actual_sha256, actual_size, decision.safe_format_id

    def verify_staged(
        self,
        staging_token: str,
        *,
        expected_sha256: str,
        expected_byte_size: int,
        media_type: str,
        role: str,
    ) -> tuple[str, int]:
        """Re-read and validate a stage without changing the final namespace."""

        with self._promotion_lock:
            _, actual_sha256, actual_size, _ = self._validated_stage(
                staging_token,
                expected_sha256=expected_sha256,
                expected_byte_size=expected_byte_size,
                media_type=media_type,
                role=role,
            )
            return actual_sha256, actual_size

    def _descriptor_for_final(
        self,
        final: Path,
        *,
        sha256: str,
        byte_size: int,
        media_type: str,
        role: str,
        provenance_entity_id: str,
        safe_format_id: str,
        schema_fingerprint: str | None,
        semantic_fingerprint: str | None,
        published_at: datetime,
    ) -> ArtifactDescriptor:
        if published_at.tzinfo is None or published_at.utcoffset() is None:
            raise ValueError("published_at must be timezone-aware")
        created_at = datetime.fromtimestamp(final.stat().st_mtime, timezone.utc)
        if created_at > published_at:
            created_at = published_at
        return ArtifactDescriptor(
            artifact_id=artifact_id_from_sha256(sha256),
            sha256=sha256,
            byte_size=byte_size,
            media_type=media_type,
            role=role,
            safe_format_id=safe_format_id,
            schema_fingerprint=schema_fingerprint,
            semantic_fingerprint=semantic_fingerprint,
            created_at=created_at,
            published_at=published_at,
            provenance_entity_id=provenance_entity_id,
        )

    def promote_staged(
        self,
        staging_token: str,
        *,
        promotion_intent_id: str,
        expected_sha256: str,
        expected_byte_size: int,
        media_type: str,
        role: str,
        provenance_entity_id: str,
        schema_fingerprint: str | None = None,
        semantic_fingerprint: str | None = None,
        published_at: datetime | None = None,
    ) -> PublicationResult:
        """Promote exact staged bytes while retaining the stage for Catalog recovery.

        This method deliberately stops before Catalog publication.  The caller
        must persist the promotion intent first and must delete the stage only
        after the Catalog transaction commits.
        """

        if not isinstance(promotion_intent_id, str) or _PROMOTION_ID_RE.fullmatch(promotion_intent_id) is None:
            raise ValueError("promotion_intent_id is not a safe storage identity")
        with self._promotion_lock:
            # Keep validation and the final namespace mutation in the same
            # lease. Otherwise cleanup/quarantine can remove the stage after
            # validation but before the promoting copy is made.
            stage, actual_sha256, actual_size, safe_format_id = self._validated_stage(
                staging_token,
                expected_sha256=expected_sha256,
                expected_byte_size=expected_byte_size,
                media_type=media_type,
                role=role,
            )
            final = self._final_path(actual_sha256)
            _ensure_directory_chain(self.content_root, final.parent, "content path")
            promoting = final.with_name(final.name + ".promoting." + promotion_intent_id)
            deduplicated = False
            if _entry_exists(final):
                _require_regular_file(final, "published artifact")
                existing_sha256, existing_size = _hash_file(final)
                if existing_sha256 != actual_sha256 or existing_size != actual_size:
                    raise ArtifactCollision("content-addressed key contains different bytes")
                deduplicated = True
                if _entry_exists(promoting):
                    _require_regular_file(promoting, "promoting artifact")
                    if _hash_file(promoting) != (actual_sha256, actual_size):
                        raise ArtifactCollision("promoting key contains different bytes")
                    promoting.unlink()
                    _fsync_directory(final.parent)
            else:
                if _entry_exists(promoting):
                    _require_regular_file(promoting, "promoting artifact")
                    if _hash_file(promoting) != (actual_sha256, actual_size):
                        raise ArtifactCollision("promoting key contains different bytes")
                else:
                    # The retained stage is an independent recovery source.
                    # A hardlink would make an in-place final corruption also
                    # corrupt the stage inode, defeating the reconcile matrix.
                    shutil.copyfile(stage, promoting)
                    with promoting.open("r+b") as handle:
                        handle.flush()
                        os.fsync(handle.fileno())
                    _fsync_directory(final.parent)
                    if _hash_file(promoting) != (actual_sha256, actual_size):
                        raise IntegrityMismatch("promoting bytes changed before atomic rename")
                os.replace(promoting, final)
                _fsync_directory(final.parent)

            final_sha256, final_size = _hash_file(final)
            if (final_sha256, final_size) != (actual_sha256, actual_size):
                raise IntegrityMismatch("final bytes failed post-promotion identity verification")
            observed_published_at = published_at or _utc_now()
            descriptor = self._descriptor_for_final(
                final,
                sha256=actual_sha256,
                byte_size=actual_size,
                media_type=media_type,
                role=role,
                provenance_entity_id=provenance_entity_id,
                safe_format_id=safe_format_id,
                schema_fingerprint=schema_fingerprint,
                semantic_fingerprint=semantic_fingerprint,
                published_at=observed_published_at,
            )
        return PublicationResult(descriptor, deduplicated, storage_key_for_sha256(actual_sha256))

    def cleanup_staging(self, staging_token: str) -> bool:
        """Delete one stage after Catalog commit; the operation is idempotent."""

        with self._promotion_lock:
            path = self._staging_path(staging_token)
            if not _entry_exists(path):
                return True
            _require_regular_file(path, "staging entry")
            path.unlink()
            _fsync_directory(self.staging_root)
            return not _entry_exists(path)

    def verify_final_bytes(
        self, artifact_id: str, *, expected_byte_size: int | None = None
    ) -> tuple[str, int]:
        with self._promotion_lock:
            digest = sha256_from_artifact_id(artifact_id)
            path = self._final_path(digest)
            try:
                _require_regular_file(path, "published artifact")
            except FileNotFoundError:
                raise StagingNotFound("published artifact bytes are missing")
            observed = _hash_file(path)
            if observed[0] != digest:
                raise ArtifactCollision("published bytes do not match the Artifact ID")
            if expected_byte_size is not None and observed[1] != expected_byte_size:
                raise IntegrityMismatch("published byte size does not match the Catalog")
            return observed

    def quarantine_published_bytes(
        self,
        artifact_id: str,
        gc_batch_id: str,
        *,
        expected_byte_size: int | None = None,
    ) -> str | None:
        """Atomically move exact final bytes into the app-owned quarantine."""

        with self._promotion_lock:
            source = self.final_path(artifact_id)
            destination, storage_key = self.quarantine_path(artifact_id, gc_batch_id)
            _ensure_directory_chain(self.quarantine_root, destination.parent, "quarantine path")
            if _entry_exists(destination):
                _require_regular_file(destination, "quarantined artifact")
                self.verify_quarantine_bytes(storage_key, artifact_id, expected_byte_size=expected_byte_size)
                if _entry_exists(source):
                    _require_regular_file(source, "published artifact")
                    if _hash_file(source) != _hash_file(destination):
                        raise ArtifactCollision("final and quarantine bytes conflict")
                    source.unlink()
                    _fsync_directory(source.parent)
                return storage_key
            if not _entry_exists(source):
                return None
            _require_regular_file(source, "published artifact")
            observed = _hash_file(source)
            if observed[0] != sha256_from_artifact_id(artifact_id):
                raise ArtifactCollision("refusing to quarantine bytes with a mismatched Artifact ID")
            if expected_byte_size is not None and observed[1] != expected_byte_size:
                raise IntegrityMismatch("published byte size does not match the Catalog")
            os.replace(source, destination)
            _fsync_directory(source.parent)
            _fsync_directory(destination.parent)
            self.verify_quarantine_bytes(storage_key, artifact_id, expected_byte_size=expected_byte_size)
            return storage_key

    def verify_quarantine_bytes(
        self,
        storage_key: str,
        artifact_id: str,
        *,
        expected_byte_size: int | None = None,
    ) -> tuple[str, int]:
        with self._promotion_lock:
            path = self._quarantine_path(storage_key)
            if not _entry_exists(path):
                raise StagingNotFound("quarantined Artifact bytes are missing")
            _require_regular_file(path, "quarantined artifact")
            observed = _hash_file(path)
            if observed[0] != sha256_from_artifact_id(artifact_id):
                raise ArtifactCollision("quarantined bytes do not match the Artifact ID")
            if expected_byte_size is not None and observed[1] != expected_byte_size:
                raise IntegrityMismatch("quarantined byte size does not match the Catalog")
            return observed

    def restore_quarantined_bytes(
        self,
        artifact_id: str,
        storage_key: str,
        *,
        expected_byte_size: int | None = None,
    ) -> bool:
        with self._promotion_lock:
            source = self._quarantine_path(storage_key)
            destination = self.final_path(artifact_id)
            _ensure_directory_chain(self.content_root, destination.parent, "content path")
            if not _entry_exists(source):
                if not _entry_exists(destination):
                    raise StagingNotFound("quarantined Artifact bytes are missing")
                self.verify_final_bytes(artifact_id, expected_byte_size=expected_byte_size)
                return True
            self.verify_quarantine_bytes(storage_key, artifact_id, expected_byte_size=expected_byte_size)
            if _entry_exists(destination):
                self.verify_final_bytes(artifact_id, expected_byte_size=expected_byte_size)
                source.unlink()
                _fsync_directory(source.parent)
                return True
            os.replace(source, destination)
            _fsync_directory(source.parent)
            _fsync_directory(destination.parent)
            self.verify_final_bytes(artifact_id, expected_byte_size=expected_byte_size)
            return True

    def purge_quarantined_bytes(
        self,
        artifact_id: str,
        storage_key: str,
        *,
        expected_byte_size: int | None = None,
    ) -> bool:
        with self._promotion_lock:
            self.verify_quarantine_bytes(storage_key, artifact_id, expected_byte_size=expected_byte_size)
            path = self._quarantine_path(storage_key)
            path.unlink()
            _fsync_directory(path.parent)
            return not _entry_exists(path)

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
        result = self.promote_staged(
            staging_token,
            promotion_intent_id="legacy_" + staging_token,
            expected_sha256=expected_sha256,
            expected_byte_size=expected_byte_size,
            media_type=media_type,
            role=role,
            provenance_entity_id=provenance_entity_id,
            schema_fingerprint=schema_fingerprint,
            semantic_fingerprint=semantic_fingerprint,
            published_at=published_at,
        )
        self.cleanup_staging(staging_token)
        return result

    def read_bytes(self, artifact_id: str, *, max_bytes: int | None = None) -> bytes:
        with self.open_verified(artifact_id, max_bytes=max_bytes) as handle:
            return handle.read()

    def open_verified(
        self,
        artifact_id: str,
        *,
        expected_sha256: str | None = None,
        expected_byte_size: int | None = None,
        max_bytes: int | None = None,
    ) -> BinaryIO:
        """Open one verified immutable payload without loading it into memory.

        Hashing and the returned stream use the same open file handle, avoiding a
        path re-open boundary between verification and the consumer read.
        """

        digest = sha256_from_artifact_id(artifact_id)
        if expected_sha256 is not None:
            validate_sha256(expected_sha256)
            if expected_sha256 != digest:
                raise IntegrityMismatch("declared SHA-256 does not match artifact identity")
        if expected_byte_size is not None and (
            not isinstance(expected_byte_size, int)
            or isinstance(expected_byte_size, bool)
            or expected_byte_size < 0
        ):
            raise ValueError("expected_byte_size must be a non-negative integer")
        if max_bytes is not None and (
            not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 0
        ):
            raise ValueError("max_bytes must be a non-negative integer")

        # Keep admission, open, and hashing under the same namespace lease.
        # Otherwise a concurrent promotion/quarantine could replace the path
        # after lstat but before the consumer receives the verified handle.
        with self._promotion_lock:
            path = self._final_path(digest)
            try:
                # lstat is intentional: a symlink/reparse entry is not an admitted
                # content-addressed file even when its target hashes correctly.
                _require_regular_file(path, "published artifact")
                handle = path.open("rb")
            except FileNotFoundError as exc:
                raise StagingNotFound("published artifact bytes are missing") from exc
            try:
                mode = os.fstat(handle.fileno()).st_mode
                if not stat.S_ISREG(mode):
                    raise IntegrityMismatch("published artifact must be a regular file")
                observed = hashlib.sha256()
                byte_size = 0
                while chunk := handle.read(_CHUNK_SIZE):
                    observed.update(chunk)
                    byte_size += len(chunk)
                    if max_bytes is not None and byte_size > max_bytes:
                        raise IntegrityMismatch("artifact exceeds read bound")
                if observed.hexdigest() != digest:
                    raise IntegrityMismatch("published bytes no longer match artifact identity")
                if expected_byte_size is not None and byte_size != expected_byte_size:
                    raise IntegrityMismatch("declared byte size does not match artifact bytes")
                handle.seek(0)
                return handle
            except BaseException:
                handle.close()
                raise

    def delete_published_bytes(self, artifact_id: str) -> bool:
        digest = sha256_from_artifact_id(artifact_id)
        path = self._final_path(digest)
        if not _entry_exists(path):
            return True
        _require_regular_file(path, "published artifact")
        observed_digest, _ = _hash_file(path)
        if observed_digest != digest:
            raise ArtifactCollision("refusing to delete bytes that do not match the artifact ID")
        path.unlink()
        _fsync_directory(path.parent)
        return not _entry_exists(path)
