from __future__ import annotations

import unittest
from datetime import datetime, timezone

from v3_backend.domain.artifacts.identity import artifact_id_for_bytes, sha256_from_artifact_id
from v3_backend.domain.artifacts.model import ArtifactDescriptor, ArtifactReference
from v3_backend.domain.artifacts.publication import (
    ArtifactPublication,
    publish_to_catalog,
)


NOW = datetime(2026, 8, 9, tzinfo=timezone.utc)


class FakeCatalogPublishUnitOfWork:
    """Test-only fake; production repository ownership remains WS-B."""

    def __init__(self) -> None:
        self.publications: list[ArtifactPublication] = []

    def publish(self, publication: ArtifactPublication) -> None:
        self.publications.append(publication)


class PublicationBoundaryTests(unittest.TestCase):
    def descriptor(self) -> ArtifactDescriptor:
        artifact_id = artifact_id_for_bytes(b"large result")
        return ArtifactDescriptor(
            artifact_id=artifact_id,
            sha256=sha256_from_artifact_id(artifact_id),
            byte_size=12,
            media_type="text/plain",
            role="TEXT_REPORT",
            safe_format_id="utf8-text-v1",
            created_at=NOW,
            published_at=NOW,
            provenance_entity_id="prv_01H00000000000000000000000",
        )

    def test_publish_uow_requires_active_matching_reference(self) -> None:
        descriptor = self.descriptor()
        with self.assertRaises(ValueError):
            ArtifactPublication(descriptor, ())
        mismatched = ArtifactReference(
            reference_id="arf_00000000000000000000000000",
            owner_id="result",
            artifact_id=artifact_id_for_bytes(b"other"),
            role="TEXT_REPORT",
            created_at=NOW,
        )
        with self.assertRaises(ValueError):
            ArtifactPublication(descriptor, (mismatched,))

    def test_publish_delegates_one_atomic_catalog_boundary(self) -> None:
        descriptor = self.descriptor()
        reference = ArtifactReference(
            reference_id="arf_00000000000000000000000000",
            owner_id="result",
            artifact_id=descriptor.artifact_id,
            role="TEXT_REPORT",
            created_at=NOW,
        )
        publication = ArtifactPublication(descriptor, (reference,))
        fake = FakeCatalogPublishUnitOfWork()
        publish_to_catalog(fake, publication)
        self.assertEqual(fake.publications, [publication])


if __name__ == "__main__":
    unittest.main()
