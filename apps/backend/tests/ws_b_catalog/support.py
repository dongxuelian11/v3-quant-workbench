from __future__ import annotations

import tempfile
import unittest
import hashlib
from pathlib import Path

from v3_backend.adapters.sqlite.connection import connect_catalog
from v3_backend.adapters.sqlite.repositories import SQLiteRepositoryRegistry
from v3_backend.adapters.sqlite.unit_of_work import SQLiteUnitOfWork
from v3_backend.migrations import apply_migrations


NOW = "2026-08-09T00:00:00.000000Z"


class CatalogTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database_path = self.root / "catalog.sqlite3"
        apply_migrations(self.database_path, application_version="ws-b-tests")
        self.connection = connect_catalog(self.database_path)

    def tearDown(self) -> None:
        self.connection.close()
        self.temporary.cleanup()

    def registry(self, unit_of_work: SQLiteUnitOfWork) -> SQLiteRepositoryRegistry:
        return SQLiteRepositoryRegistry(unit_of_work)

    def add_project(self, registry: SQLiteRepositoryRegistry, project_id: str = "prj_test") -> dict:
        return registry.project.add_new(
            {
                "project_id": project_id,
                "display_name": "Test Project",
                "created_at": NOW,
                "state": "ACTIVE",
            }
        )

    def append_context(
        self,
        registry: SQLiteRepositoryRegistry,
        *,
        project_id: str = "prj_test",
        revision_id: str = "pcr_test_1",
        base_revision_id: str | None = None,
    ) -> dict:
        return registry.project.append_revision(
            {
                "project_context_revision_id": revision_id,
                "project_id": project_id,
                "context_json": {"project_id": project_id},
                "canonical_hash": hashlib.sha256(revision_id.encode("utf-8")).hexdigest(),
                "created_by": "test",
                "created_at": NOW,
            },
            base_revision_id=base_revision_id,
        )

    def publish_artifact(
        self, registry: SQLiteRepositoryRegistry, digest: str = "a" * 64
    ) -> dict:
        artifact_id = "art_sha256_" + digest
        registry.artifact.declare_staged(
            {
                "artifact_id": artifact_id,
                "sha256": digest,
                "byte_size": 12,
                "media_type": "application/octet-stream",
                "semantic_role": "TEST_EVIDENCE",
                "storage_key": digest,
                "state": "STAGED",
                "created_at": NOW,
            }
        )
        return registry.artifact.publish_verified(artifact_id, sha256=digest, published_at=NOW)
