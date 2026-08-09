"""Canonical byte identity and storage-key derivation."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from .exceptions import InvalidArtifactIdentity


ARTIFACT_ID_PREFIX = "art_sha256_"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def validate_sha256(value: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise InvalidArtifactIdentity("SHA-256 must be 64 lowercase hexadecimal characters")
    return value


def artifact_id_from_sha256(digest: str) -> str:
    return ARTIFACT_ID_PREFIX + validate_sha256(digest)


def sha256_from_artifact_id(artifact_id: str) -> str:
    if not isinstance(artifact_id, str) or not artifact_id.startswith(ARTIFACT_ID_PREFIX):
        raise InvalidArtifactIdentity("artifact ID must start with art_sha256_")
    digest = artifact_id[len(ARTIFACT_ID_PREFIX) :]
    validate_sha256(digest)
    if artifact_id != ARTIFACT_ID_PREFIX + digest:
        raise InvalidArtifactIdentity("artifact ID is not canonical")
    return digest


def artifact_id_for_bytes(payload: bytes) -> str:
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    return artifact_id_from_sha256(hashlib.sha256(payload).hexdigest())


def hash_chunks(chunks: Iterable[bytes]) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_size = 0
    for chunk in chunks:
        if not isinstance(chunk, bytes):
            raise TypeError("hash chunks must be bytes")
        digest.update(chunk)
        byte_size += len(chunk)
    return digest.hexdigest(), byte_size


def storage_key_for_sha256(digest: str) -> str:
    digest = validate_sha256(digest)
    return f"sha256/{digest[:2]}/{digest[2:4]}/{digest}"


def storage_key_for_artifact_id(artifact_id: str) -> str:
    return storage_key_for_sha256(sha256_from_artifact_id(artifact_id))
