from __future__ import annotations

import hashlib
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

from v3_backend.domain.artifacts.identity import (
    artifact_id_for_bytes,
    artifact_id_from_sha256,
    sha256_from_artifact_id,
    storage_key_for_artifact_id,
)
from v3_backend.domain.artifacts.model import (
    ArtifactDescriptor,
    ArtifactReference,
    StreamTicketDescriptor,
    ensure_descriptor_immutable,
)
from v3_backend.domain.artifacts.exceptions import DescriptorConflict, InvalidArtifactIdentity


NOW = datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc)


def descriptor(payload: bytes = b"abc", *, role: str = "TEXT_REPORT") -> ArtifactDescriptor:
    digest = hashlib.sha256(payload).hexdigest()
    return ArtifactDescriptor(
        artifact_id=artifact_id_from_sha256(digest),
        sha256=digest,
        byte_size=len(payload),
        media_type="text/plain",
        role=role,
        safe_format_id="utf8-text-v1",
        schema_fingerprint=None,
        created_at=NOW,
        published_at=NOW,
        provenance_entity_id="prv_01H00000000000000000000000",
    )


class IdentityKnownAnswerTests(unittest.TestCase):
    def test_empty_and_abc_known_answers(self) -> None:
        self.assertEqual(
            artifact_id_for_bytes(b""),
            "art_sha256_e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )
        self.assertEqual(
            artifact_id_for_bytes(b"abc"),
            "art_sha256_ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )

    def test_storage_key_known_answer(self) -> None:
        artifact_id = artifact_id_for_bytes(b"abc")
        self.assertEqual(
            storage_key_for_artifact_id(artifact_id),
            "sha256/ba/78/ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )
        self.assertEqual(sha256_from_artifact_id(artifact_id), hashlib.sha256(b"abc").hexdigest())

    def test_noncanonical_identity_rejected(self) -> None:
        with self.assertRaises(InvalidArtifactIdentity):
            sha256_from_artifact_id("art_sha256_" + "A" * 64)


class ImmutableModelTests(unittest.TestCase):
    def test_descriptor_is_frozen_and_has_no_raw_path(self) -> None:
        value = descriptor()
        with self.assertRaises(FrozenInstanceError):
            value.role = "OTHER"  # type: ignore[misc]
        wire = value.to_wire()
        ref = value.to_artifact_ref()
        self.assertNotIn("path", wire)
        self.assertNotIn("storage_key", wire)
        self.assertNotIn("payload", ref)
        self.assertEqual(ref["artifact_id"], artifact_id_for_bytes(b"abc"))

    def test_conflicting_descriptor_rewrite_rejected(self) -> None:
        existing = descriptor(role="TEXT_REPORT")
        changed = descriptor(role="OTHER")
        with self.assertRaises(DescriptorConflict):
            ensure_descriptor_immutable(existing, changed)

    def test_active_reference_and_ticket_are_scoped(self) -> None:
        value = descriptor()
        reference = ArtifactReference(
            reference_id="arf_00000000000000000000000000",
            owner_id="prj_00000000000000000000000000",
            artifact_id=value.artifact_id,
            role=value.role,
            created_at=NOW,
        )
        self.assertEqual(reference.state, "ACTIVE")
        ticket = StreamTicketDescriptor(
            ticket_id="opaque-ticket",
            artifact_id=value.artifact_id,
            project_id="prj_00000000000000000000000000",
            session_id="ses_01890f3a-6e93-7cc0-8000-000000000000",
            expires_at=NOW + timedelta(minutes=5),
            range_start=0,
            range_end_exclusive=3,
        )
        self.assertEqual(ticket.to_access_wire()["mode"], "STREAM_TICKET")
        self.assertNotIn("path", ticket.to_access_wire())


if __name__ == "__main__":
    unittest.main()
