from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from v3_backend.adapters.artifact_store import FileSystemArtifactStore
from v3_backend.adapters.sqlite.artifact_publication import (
    ArtifactPublicationCoordinator,
    SQLiteArtifactPublicationPort,
)
from v3_backend.adapters.sqlite.connection import connect_catalog
from v3_backend.adapters.sqlite.repositories import SQLiteRepositoryRegistry
from v3_backend.adapters.sqlite.unit_of_work import SQLiteUnitOfWork
from v3_backend.domain.artifacts.exceptions import (
    ArtifactError,
    ArtifactCollision,
    GarbageCollectionSafetyError,
)
from v3_backend.domain.artifacts.model import ArtifactReference
from v3_backend.domain.artifacts.publication import ArtifactPublication
from v3_backend.domain.artifacts.reachability import (
    GarbageCollectionItem,
    GarbageCollectionPlan,
    ReachabilityGraph,
)
from v3_backend.errors.exceptions import ConflictError
from v3_backend.migrations import apply_migrations
from v3_backend.repositories.unit_of_work import TransactionMode


NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


class _NoopPublishCallbacks:
    def verify_staged(self) -> None:
        return None

    def publish_staged(self) -> None:
        return None

    def compensate_unreferenced_staging(self) -> None:
        return None

    def notify_committed(self) -> None:
        return None


class ArtifactLifecycleIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "catalog.sqlite3"
        self.store = FileSystemArtifactStore(self.root / "artifacts")
        apply_migrations(self.database, application_version="artifact-lifecycle-tests")
        self.coordinator = ArtifactPublicationCoordinator(self.database, self.store)
        self.project_id = "prj_" + "A" * 26
        self._reference_number = 0

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _reference(self, artifact_id: str, role: str) -> ArtifactReference:
        self._reference_number += 1
        return ArtifactReference(
            reference_id="arf_" + f"{self._reference_number:026d}",
            owner_id=self.project_id,
            artifact_id=artifact_id,
            role=role,
            created_at=NOW,
            state="ACTIVE",
            released_at=None,
        )

    def _prepare(
        self,
        payload: bytes,
        *,
        role: str = "TEXT_REPORT",
        media_type: str = "text/plain",
        published_at: datetime = NOW,
        reference_role: str | None = None,
        schema_fingerprint: str = "v3.test.artifact-lifecycle/1.0",
    ):
        stage = self.store.stage_bytes(payload)
        reference = self._reference(
            "art_sha256_" + stage.sha256,
            reference_role or role,
        )
        prepared = self.coordinator.prepare(
            stage,
            media_type=media_type,
            role=role,
            provenance_entity_id="prv_artifact_lifecycle_test",
            schema_fingerprint=schema_fingerprint,
            semantic_fingerprint=stage.sha256,
            published_at=published_at,
            active_references=(reference,),
        )
        return stage, prepared, (reference,)

    def _promote_and_catalog_commit(
        self,
        stage,
        prepared,
        references: tuple[ArtifactReference, ...],
        *,
        role: str = "TEXT_REPORT",
        media_type: str = "text/plain",
        published_at: datetime = NOW,
        finalize: bool = True,
        schema_fingerprint: str = "v3.test.artifact-lifecycle/1.0",
    ):
        result = self.coordinator.promote(
            prepared,
            media_type=media_type,
            role=role,
            provenance_entity_id="prv_artifact_lifecycle_test",
            schema_fingerprint=schema_fingerprint,
            semantic_fingerprint=stage.sha256,
            published_at=published_at,
        )
        connection = connect_catalog(self.database)
        uow = SQLiteUnitOfWork(
            connection,
            TransactionMode.PUBLISH,
            publish_callbacks=_NoopPublishCallbacks(),
        )
        try:
            uow.begin()
            SQLiteArtifactPublicationPort(uow).publish(
                ArtifactPublication(result.descriptor, references),
                promotion_intent_id=prepared.promotion_intent_id,
            )
            uow.commit()
        finally:
            if uow.active:
                uow.rollback()
            connection.close()
        if finalize:
            self.coordinator.finalize(prepared)
        return result

    def _read_one(self, sql: str, params: tuple[object, ...] = ()) -> sqlite3.Row | None:
        connection = connect_catalog(self.database, read_only=True)
        try:
            return connection.execute(sql, params).fetchone()
        finally:
            connection.close()

    def _release_reference(self, reference_id: str) -> None:
        connection = connect_catalog(self.database)
        try:
            connection.execute(
                "UPDATE artifact_reference SET state='RELEASED', released_at=? WHERE artifact_reference_id=?",
                (NOW.isoformat().replace("+00:00", "Z"), reference_id),
            )
            connection.commit()
        finally:
            connection.close()

    def _record_gc_plan(
        self,
        *,
        candidate,
        phase: str,
        created_at: datetime,
        reachability_fingerprint: str,
    ):
        plan = GarbageCollectionPlan(
            created_at=created_at,
            grace_period_seconds=7 * 24 * 60 * 60,
            reachability_fingerprint=reachability_fingerprint,
            items=(
                GarbageCollectionItem(
                    artifact_id=candidate.descriptor.artifact_id,
                    byte_size=candidate.descriptor.byte_size,
                    published_at=candidate.descriptor.published_at,
                    storage_key=candidate.descriptor.storage_key,
                ),
            ),
            phase=phase,
        )
        publication = self._publish_gc_plan(plan, created_at=created_at)
        batch = self.coordinator.record_gc_batch(
            phase=phase,
            scope_owner_id=self.project_id,
            plan_artifact_id=publication.descriptor.artifact_id,
            plan=plan,
        )
        return plan, batch

    def _publish_gc_plan(self, plan: GarbageCollectionPlan, *, created_at: datetime):
        stage, prepared, references = self._prepare(
            plan.canonical_bytes(),
            role="GC_PLAN",
            media_type="application/json",
            published_at=created_at,
            reference_role="GC_PLAN",
            schema_fingerprint="urn:v3:artifact-gc-plan:1.0.0",
        )
        publication = self._promote_and_catalog_commit(
            stage,
            prepared,
            references,
            role="GC_PLAN",
            media_type="application/json",
            published_at=created_at,
            schema_fingerprint="urn:v3:artifact-gc-plan:1.0.0",
        )
        self.assertEqual(publication.descriptor.artifact_id, plan.plan_artifact_id)
        return publication

    def _make_released_candidate(self, payload: bytes = b"GC candidate"):
        stage, prepared, references = self._prepare(
            payload,
            published_at=NOW - timedelta(days=30),
        )
        result = self._promote_and_catalog_commit(
            stage,
            prepared,
            references,
            published_at=NOW - timedelta(days=30),
        )
        self._release_reference(references[0].reference_id)
        return result

    def test_reconcile_recovers_wrong_final_from_verified_stage_without_overwrite(self) -> None:
        payload = b"recover from the retained stage"
        stage, prepared, references = self._prepare(payload)
        result = self.coordinator.promote(
            prepared,
            media_type="text/plain",
            role="TEXT_REPORT",
            provenance_entity_id="prv_artifact_lifecycle_test",
            schema_fingerprint="v3.test.artifact-lifecycle/1.0",
            semantic_fingerprint=stage.sha256,
            published_at=NOW,
        )
        final = self.store.final_path(result.descriptor.artifact_id)
        final.write_bytes(b"wrong final bytes")

        summary = self.coordinator.reconcile()

        self.assertEqual(summary["promotion_finalized"], 1)
        self.assertEqual(self.store.verify_final_bytes(result.descriptor.artifact_id), (stage.sha256, len(payload)))
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact WHERE artifact_id=?",
                (result.descriptor.artifact_id,),
            )[0],
            "PUBLISHED",
        )
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact_promotion_intent WHERE promotion_intent_id=?",
                (prepared.promotion_intent_id,),
            )[0],
            "FINALIZED",
        )
        self.assertFalse(self.store.staging_path(stage.staging_token).exists())
        self.assertTrue(tuple((self.store.quarantine_root / "conflicts").glob("*.bytes")))

    def test_reconcile_marks_unrecoverable_published_bytes_and_blocks_catalog_completion(self) -> None:
        stage, prepared, references = self._prepare(b"bytes that will disappear")
        result = self._promote_and_catalog_commit(
            stage, prepared, references, finalize=False
        )
        self.store.final_path(result.descriptor.artifact_id).unlink()
        self.store.staging_path(stage.staging_token).unlink()

        summary = self.coordinator.reconcile()

        self.assertEqual(summary["promotion_bytes_unavailable"], 1)
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact_promotion_intent WHERE promotion_intent_id=?",
                (prepared.promotion_intent_id,),
            )[0],
            "FAILED",
        )
        self.assertEqual(
            self._read_one(
                """
                SELECT error_code FROM artifact_storage_error
                WHERE promotion_intent_id=? ORDER BY created_at DESC LIMIT 1
                """,
                (prepared.promotion_intent_id,),
            )[0],
            "PUBLISHED_BYTES_UNAVAILABLE",
        )

    def test_orphan_stage_and_final_are_isolated_without_auto_publish(self) -> None:
        orphan_stage = self.store.stage_bytes(b"untracked stage")
        orphan_final_stage = self.store.stage_bytes(b"untracked final")
        orphan_final = self.store.publish(
            orphan_final_stage.staging_token,
            expected_sha256=orphan_final_stage.sha256,
            expected_byte_size=orphan_final_stage.byte_size,
            media_type="text/plain",
            role="TEXT_REPORT",
            provenance_entity_id="prv_artifact_lifecycle_test",
        )

        summary = self.coordinator.reconcile()

        self.assertEqual(summary["orphan_stages_quarantined"], 1)
        self.assertEqual(summary["orphan_final_bytes_isolated"], 1)
        self.assertFalse(self.store.staging_path(orphan_stage.staging_token).exists())
        self.assertFalse(self.store.final_path(orphan_final.descriptor.artifact_id).exists())
        self.assertIsNone(
            self._read_one(
                "SELECT artifact_id FROM artifact WHERE artifact_id=?",
                (orphan_final.descriptor.artifact_id,),
            )
        )

    def test_intent_reentry_retains_stage_until_catalog_commit_and_then_finalizes(self) -> None:
        stage, prepared, references = self._prepare(b"idempotent lifecycle")
        first = self.coordinator.promote(
            prepared,
            media_type="text/plain",
            role="TEXT_REPORT",
            provenance_entity_id="prv_artifact_lifecycle_test",
            schema_fingerprint="v3.test.artifact-lifecycle/1.0",
            semantic_fingerprint=stage.sha256,
            published_at=NOW,
        )
        second = self.coordinator.promote(
            prepared,
            media_type="text/plain",
            role="TEXT_REPORT",
            provenance_entity_id="prv_artifact_lifecycle_test",
            schema_fingerprint="v3.test.artifact-lifecycle/1.0",
            semantic_fingerprint=stage.sha256,
            published_at=NOW,
        )
        self.assertEqual(first.descriptor.artifact_id, second.descriptor.artifact_id)
        self.assertTrue(self.store.staging_path(stage.staging_token).exists())
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact_promotion_intent WHERE promotion_intent_id=?",
                (prepared.promotion_intent_id,),
            )[0],
            "FINAL_PRESENT",
        )
        self._promote_and_catalog_commit(stage, prepared, references)
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact_promotion_intent WHERE promotion_intent_id=?",
                (prepared.promotion_intent_id,),
            )[0],
            "FINALIZED",
        )
        self.assertFalse(self.store.staging_path(stage.staging_token).exists())

    def test_prepare_reentry_reuses_persisted_reference_identity(self) -> None:
        stage, prepared, references = self._prepare(b"re-entry reference identity")
        replacement_reference = self._reference(
            "art_sha256_" + stage.sha256,
            references[0].role,
        )

        retried = self.coordinator.prepare(
            stage,
            media_type="text/plain",
            role="TEXT_REPORT",
            provenance_entity_id="prv_artifact_lifecycle_test",
            schema_fingerprint="v3.test.artifact-lifecycle/1.0",
            semantic_fingerprint=stage.sha256,
            published_at=NOW + timedelta(days=1),
            active_references=(replacement_reference,),
        )

        self.assertEqual(retried.promotion_intent_id, prepared.promotion_intent_id)
        self.assertEqual(
            tuple(item.reference_id for item in retried.active_references),
            tuple(item.reference_id for item in references),
        )
        self._promote_and_catalog_commit(stage, retried, retried.active_references)
        self.assertEqual(
            self._read_one(
                "SELECT COUNT(*) FROM artifact_reference WHERE artifact_id=?",
                ("art_sha256_" + stage.sha256,),
            )[0],
            1,
        )

    def test_prepare_rejects_a_reference_to_a_different_artifact_before_intent(self) -> None:
        stage = self.store.stage_bytes(b"reference must target this stage")
        mismatched = self._reference("art_sha256_" + "0" * 64, "TEXT_REPORT")

        with self.assertRaises(ArtifactCollision):
            self.coordinator.prepare(
                stage,
                media_type="text/plain",
                role="TEXT_REPORT",
                provenance_entity_id="prv_artifact_lifecycle_test",
                schema_fingerprint="v3.test.artifact-lifecycle/1.0",
                semantic_fingerprint=stage.sha256,
                published_at=NOW,
                active_references=(mismatched,),
            )

        self.assertIsNone(
            self._read_one(
                "SELECT promotion_intent_id FROM artifact_promotion_intent WHERE staging_token=?",
                (stage.staging_token,),
            )
        )
        self.assertTrue(self.store.staging_path(stage.staging_token).exists())

    def test_prepare_rejects_duplicate_owner_bindings_before_intent(self) -> None:
        stage = self.store.stage_bytes(b"duplicate owner binding")
        artifact_id = "art_sha256_" + stage.sha256
        first = self._reference(artifact_id, "TEXT_REPORT")
        second = self._reference(artifact_id, "TEXT_REPORT")

        with self.assertRaises(ArtifactCollision):
            self.coordinator.prepare(
                stage,
                media_type="text/plain",
                role="TEXT_REPORT",
                provenance_entity_id="prv_artifact_lifecycle_test",
                schema_fingerprint="v3.test.artifact-lifecycle/1.0",
                semantic_fingerprint=stage.sha256,
                published_at=NOW,
                active_references=(first, second),
            )

        self.assertIsNone(
            self._read_one(
                "SELECT promotion_intent_id FROM artifact_promotion_intent WHERE staging_token=?",
                (stage.staging_token,),
            )
        )
        self.assertTrue(self.store.staging_path(stage.staging_token).exists())

    def test_promote_rejects_a_prepared_object_bound_to_another_stage(self) -> None:
        stage, prepared, _ = self._prepare(b"prepared object binding")
        alternate_stage = self.store.stage_bytes(b"prepared object binding")

        with self.assertRaises(ArtifactCollision):
            self.coordinator.promote(
                replace(prepared, staging=alternate_stage),
                media_type="text/plain",
                role="TEXT_REPORT",
                provenance_entity_id="prv_artifact_lifecycle_test",
                schema_fingerprint="v3.test.artifact-lifecycle/1.0",
                semantic_fingerprint=stage.sha256,
                published_at=NOW,
            )

        self.assertTrue(self.store.staging_path(stage.staging_token).exists())
        self.assertTrue(self.store.staging_path(alternate_stage.staging_token).exists())

    def test_reconcile_cursor_ignores_terminal_failed_intents(self) -> None:
        for index in range(3):
            stage, prepared, _ = self._prepare(f"failed cursor {index}".encode("ascii"))
            connection = connect_catalog(self.database)
            try:
                connection.execute(
                    "UPDATE artifact_promotion_intent SET state='FAILED', state_version=2 WHERE promotion_intent_id=?",
                    (prepared.promotion_intent_id,),
                )
                connection.commit()
            finally:
                connection.close()

        stage, prepared, references = self._prepare(b"open cursor item")
        summary = self.coordinator.reconcile(limit=1)

        self.assertEqual(summary["promotion_intents_seen"], 1)
        self.assertEqual(summary["promotion_finalized"], 1)
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact_promotion_intent WHERE promotion_intent_id=?",
                (prepared.promotion_intent_id,),
            )[0],
            "FINALIZED",
        )
        self.assertFalse(self.store.staging_path(stage.staging_token).exists())

    def test_finalize_recovers_a_missing_final_from_the_retained_stage(self) -> None:
        stage, prepared, references = self._prepare(
            b"finalize recovers retained stage"
        )
        result = self._promote_and_catalog_commit(
            stage, prepared, references, finalize=False
        )
        self.store.final_path(result.descriptor.artifact_id).unlink()

        finalized = self.coordinator.finalize(prepared)

        self.assertEqual(finalized["state"], "FINALIZED")
        self.assertEqual(
            self.store.verify_final_bytes(
                result.descriptor.artifact_id,
                expected_byte_size=len(b"finalize recovers retained stage"),
            ),
            (stage.sha256, len(b"finalize recovers retained stage")),
        )
        self.assertFalse(self.store.staging_path(stage.staging_token).exists())

    def test_reconcile_scans_finalized_catalog_rows_for_missing_bytes(self) -> None:
        stage, prepared, references = self._prepare(b"finalized integrity sweep")
        result = self._promote_and_catalog_commit(stage, prepared, references)
        self.store.final_path(result.descriptor.artifact_id).unlink()

        summary = self.coordinator.reconcile()

        self.assertEqual(summary["published_artifacts_seen"], 1)
        self.assertEqual(summary["published_artifacts_unavailable"], 1)
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact_promotion_intent WHERE promotion_intent_id=?",
                (prepared.promotion_intent_id,),
            )[0],
            "FINALIZED",
        )
        self.assertEqual(
            self._read_one(
                "SELECT error_code FROM artifact_storage_error WHERE artifact_id=? ORDER BY created_at DESC LIMIT 1",
                (result.descriptor.artifact_id,),
            )[0],
            "PUBLISHED_BYTES_UNAVAILABLE",
        )

    def test_reconcile_isolates_a_nonregular_finalized_entry(self) -> None:
        stage, prepared, references = self._prepare(b"nonregular finalized entry")
        result = self._promote_and_catalog_commit(stage, prepared, references)
        final = self.store.final_path(result.descriptor.artifact_id)
        final.unlink()
        final.mkdir()
        (final / "untrusted-child").write_bytes(b"do not follow")

        summary = self.coordinator.reconcile()

        self.assertEqual(summary["published_artifacts_unavailable"], 1)
        self.assertFalse(final.exists())
        self.assertTrue(
            tuple((self.store.quarantine_root / "conflicts").glob("*.entry"))
        )

    def test_deduplicated_promotion_does_not_rewrite_durable_descriptor(self) -> None:
        first_stage, first_prepared, first_references = self._prepare(
            b"descriptor must remain immutable"
        )
        first = self._promote_and_catalog_commit(
            first_stage, first_prepared, first_references, published_at=NOW
        )
        final = self.store.final_path(first.descriptor.artifact_id)
        old_mtime = (NOW - timedelta(days=1)).timestamp()
        import os

        os.utime(final, (old_mtime, old_mtime))

        second_stage, second_prepared, _ = self._prepare(
            b"descriptor must remain immutable",
            published_at=NOW + timedelta(days=365),
        )
        before = self._read_one(
            "SELECT descriptor_json FROM artifact_promotion_intent WHERE promotion_intent_id=?",
            (second_prepared.promotion_intent_id,),
        )[0]
        result = self.coordinator.promote(
            second_prepared,
            media_type="text/plain",
            role="TEXT_REPORT",
            provenance_entity_id="prv_artifact_lifecycle_test",
            schema_fingerprint="v3.test.artifact-lifecycle/1.0",
            semantic_fingerprint=second_stage.sha256,
            published_at=NOW + timedelta(days=365),
        )
        after = self._read_one(
            "SELECT descriptor_json FROM artifact_promotion_intent WHERE promotion_intent_id=?",
            (second_prepared.promotion_intent_id,),
        )[0]
        self.assertEqual(result.descriptor.artifact_id, first.descriptor.artifact_id)
        self.assertEqual(after, before)

    def test_failed_intent_does_not_touch_unknown_final_bytes(self) -> None:
        stage, prepared, _ = self._prepare(b"failed intent is inert")
        final = self.store.final_path("art_sha256_" + stage.sha256)
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_bytes(b"unknown bytes that must remain reviewable")
        connection = connect_catalog(self.database)
        try:
            connection.execute(
                "UPDATE artifact_promotion_intent SET state='FAILED', state_version=2 WHERE promotion_intent_id=?",
                (prepared.promotion_intent_id,),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(ArtifactError):
            self.coordinator.promote(
                prepared,
                media_type="text/plain",
                role="TEXT_REPORT",
                provenance_entity_id="prv_artifact_lifecycle_test",
                schema_fingerprint="v3.test.artifact-lifecycle/1.0",
                semantic_fingerprint=stage.sha256,
                published_at=NOW,
            )
        self.assertEqual(final.read_bytes(), b"unknown bytes that must remain reviewable")
        self.assertTrue(self.store.staging_path(stage.staging_token).exists())

    def test_malformed_orphan_stage_entry_is_quarantined_instead_of_skipped(self) -> None:
        malformed = self.store.staging_root / "not-a-publish-token.stage"
        malformed.write_bytes(b"untrusted stage entry")

        summary = self.coordinator.reconcile()

        self.assertEqual(summary["orphan_stages_seen"], 1)
        self.assertEqual(summary["orphan_stages_quarantined"], 1)
        self.assertFalse(malformed.exists())
        self.assertTrue(
            tuple((self.store.quarantine_root / "orphans").glob("invalid-*.stage"))
        )
        error = self._read_one(
            """
            SELECT artifact_id, error_code FROM artifact_storage_error
            WHERE error_code='ARTIFACT_ORPHAN_STAGE_QUARANTINED'
            ORDER BY created_at DESC LIMIT 1
            """
        )
        self.assertIsNone(error[0])
        self.assertEqual(error[1], "ARTIFACT_ORPHAN_STAGE_QUARANTINED")

    def test_unexpected_staging_namespace_entry_is_quarantined_instead_of_skipped(self) -> None:
        unexpected = self.store.staging_root / "unexpected-directory"
        unexpected.mkdir()
        (unexpected / "payload").write_bytes(b"untrusted namespace entry")

        summary = self.coordinator.reconcile()

        self.assertEqual(summary["orphan_stages_seen"], 1)
        self.assertEqual(summary["orphan_stages_quarantined"], 1)
        self.assertFalse(unexpected.exists())
        quarantined = tuple((self.store.quarantine_root / "orphans").glob("invalid-*.entry"))
        self.assertEqual(len(quarantined), 1)
        self.assertTrue(quarantined[0].is_dir())

    def test_gc_fails_closed_on_unexpected_staging_namespace_entry(self) -> None:
        unexpected = self.store.staging_root / "unexpected-entry"
        unexpected.write_bytes(b"untrusted namespace entry")

        with self.assertRaises(GarbageCollectionSafetyError):
            self.coordinator.current_gc_guard()

        self.assertTrue(unexpected.exists())

    def test_legacy_repository_delete_entry_is_fail_closed(self) -> None:
        connection = connect_catalog(self.database)
        uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
        try:
            uow.begin()
            with self.assertRaisesRegex(ConflictError, "direct Artifact deletion is disabled"):
                SQLiteRepositoryRegistry(uow).artifact.mark_deleted(
                    "art_sha256_" + "0" * 64,
                    deleted_at=NOW.isoformat().replace("+00:00", "Z"),
                    confirmed_gc_plan_artifact_id="art_sha256_" + "1" * 64,
                )
        finally:
            if uow.active:
                uow.rollback()
            connection.close()

    def test_gc_batch_admission_rejects_catalog_byte_size_drift(self) -> None:
        candidate = self._make_released_candidate(b"GC byte-size drift")
        plan = GarbageCollectionPlan(
            created_at=NOW,
            grace_period_seconds=7 * 24 * 60 * 60,
            reachability_fingerprint=ReachabilityGraph((self.project_id,), ()).fingerprint(),
            items=(
                GarbageCollectionItem(
                    artifact_id=candidate.descriptor.artifact_id,
                    byte_size=candidate.descriptor.byte_size,
                    published_at=candidate.descriptor.published_at,
                    storage_key=candidate.descriptor.storage_key,
                ),
            ),
        )
        publication = self._publish_gc_plan(plan, created_at=NOW)
        connection = connect_catalog(self.database)
        try:
            connection.execute(
                "UPDATE artifact SET byte_size=byte_size+1 WHERE artifact_id=?",
                (candidate.descriptor.artifact_id,),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(GarbageCollectionSafetyError):
            self.coordinator.record_gc_batch(
                phase="QUARANTINE",
                scope_owner_id=self.project_id,
                plan_artifact_id=publication.descriptor.artifact_id,
                plan=plan,
            )
        self.assertIsNone(
            self._read_one(
                "SELECT gc_batch_id FROM artifact_gc_batch WHERE plan_artifact_id=?",
                (publication.descriptor.artifact_id,),
            )
        )

    def test_gc_batch_admission_rejects_plan_publication_timestamp_drift(self) -> None:
        candidate = self._make_released_candidate(b"GC publication-time drift")
        plan = GarbageCollectionPlan(
            created_at=NOW,
            grace_period_seconds=7 * 24 * 60 * 60,
            reachability_fingerprint=ReachabilityGraph((self.project_id,), ()).fingerprint(),
            items=(
                GarbageCollectionItem(
                    artifact_id=candidate.descriptor.artifact_id,
                    byte_size=candidate.descriptor.byte_size,
                    published_at=candidate.descriptor.published_at + timedelta(seconds=1),
                    storage_key=candidate.descriptor.storage_key,
                ),
            ),
        )
        publication = self._publish_gc_plan(plan, created_at=NOW)

        with self.assertRaises(GarbageCollectionSafetyError):
            self.coordinator.record_gc_batch(
                phase="QUARANTINE",
                scope_owner_id=self.project_id,
                plan_artifact_id=publication.descriptor.artifact_id,
                plan=plan,
            )
        self.assertIsNone(
            self._read_one(
                "SELECT gc_batch_id FROM artifact_gc_batch WHERE plan_artifact_id=?",
                (publication.descriptor.artifact_id,),
            )
        )

    def test_gc_confirmation_rechecks_plan_and_catalog_metadata(self) -> None:
        candidate = self._make_released_candidate(b"GC confirmation metadata drift")
        plan, batch = self._record_gc_plan(
            candidate=candidate,
            phase="QUARANTINE",
            created_at=NOW,
            reachability_fingerprint=ReachabilityGraph((self.project_id,), ()).fingerprint(),
        )
        connection = connect_catalog(self.database)
        try:
            connection.execute(
                "UPDATE artifact SET byte_size=byte_size+1 WHERE artifact_id=?",
                (candidate.descriptor.artifact_id,),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(GarbageCollectionSafetyError):
            self.coordinator.confirm_gc_batch(
                gc_batch_id=batch["gc_batch_id"],
                plan_artifact_id=plan.plan_artifact_id,
                exact_ids_hash=plan.exact_artifact_ids_hash,
                confirmation_nonce="metadata-confirm",
                now=NOW + timedelta(minutes=1),
            )
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact_gc_batch WHERE gc_batch_id=?",
                (batch["gc_batch_id"],),
            )[0],
            "PLANNED",
        )

    def test_gc_execution_rechecks_catalog_metadata_after_confirmation(self) -> None:
        candidate = self._make_released_candidate(b"GC execution metadata drift")
        plan, batch = self._record_gc_plan(
            candidate=candidate,
            phase="QUARANTINE",
            created_at=NOW,
            reachability_fingerprint=ReachabilityGraph((self.project_id,), ()).fingerprint(),
        )
        self.coordinator.confirm_gc_batch(
            gc_batch_id=batch["gc_batch_id"],
            plan_artifact_id=plan.plan_artifact_id,
            exact_ids_hash=plan.exact_artifact_ids_hash,
            confirmation_nonce="metadata-execute-confirm",
            now=NOW + timedelta(minutes=1),
        )
        connection = connect_catalog(self.database)
        try:
            connection.execute(
                "UPDATE artifact SET storage_key=? WHERE artifact_id=?",
                ("tampered/storage-key", candidate.descriptor.artifact_id),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(GarbageCollectionSafetyError):
            self.coordinator.execute_quarantine(
                gc_batch_id=batch["gc_batch_id"], now=NOW + timedelta(minutes=2)
            )
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact_gc_batch WHERE gc_batch_id=?",
                (batch["gc_batch_id"],),
            )[0],
            "CONFIRMED",
        )
        self.assertTrue(self.store.final_path(candidate.descriptor.artifact_id).exists())

    def test_gc_execution_freezes_artifact_and_quarantine_metadata(self) -> None:
        candidate = self._make_released_candidate(b"GC execution metadata barrier")
        plan, batch = self._record_gc_plan(
            candidate=candidate,
            phase="QUARANTINE",
            created_at=NOW,
            reachability_fingerprint=ReachabilityGraph((self.project_id,), ()).fingerprint(),
        )
        self.coordinator.confirm_gc_batch(
            gc_batch_id=batch["gc_batch_id"],
            plan_artifact_id=plan.plan_artifact_id,
            exact_ids_hash=plan.exact_artifact_ids_hash,
            confirmation_nonce="metadata-barrier-confirm",
            now=NOW + timedelta(minutes=1),
        )
        records = self.coordinator._prepare_quarantine_records(
            batch, NOW + timedelta(minutes=2)
        )
        self.assertEqual(len(records), 1)
        connection = connect_catalog(self.database)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE artifact SET byte_size=byte_size+1 WHERE artifact_id=?",
                    (candidate.descriptor.artifact_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE artifact_quarantine SET original_storage_key=? "
                    "WHERE artifact_id=? AND gc_batch_id=?",
                    (
                        "tampered/original-key",
                        candidate.descriptor.artifact_id,
                        batch["gc_batch_id"],
                    ),
                )
        finally:
            connection.close()

    def test_catalog_commit_rejects_references_not_authorized_by_intent(self) -> None:
        stage, prepared, references = self._prepare(b"intent reference authority")
        result = self.coordinator.promote(
            prepared,
            media_type="text/plain",
            role="TEXT_REPORT",
            provenance_entity_id="prv_artifact_lifecycle_test",
            schema_fingerprint="v3.test.artifact-lifecycle/1.0",
            semantic_fingerprint=stage.sha256,
            published_at=NOW,
        )
        tampered = ArtifactReference(
            reference_id="arf_" + f"99{self._reference_number:024d}",
            owner_id=self.project_id,
            artifact_id=result.descriptor.artifact_id,
            role="UNAUTHORIZED_REFERENCE",
            created_at=NOW,
            state="ACTIVE",
        )
        connection = connect_catalog(self.database)
        uow = SQLiteUnitOfWork(
            connection,
            TransactionMode.PUBLISH,
            publish_callbacks=_NoopPublishCallbacks(),
        )
        try:
            uow.begin()
            with self.assertRaises(ValueError):
                SQLiteArtifactPublicationPort(uow).publish(
                    ArtifactPublication(result.descriptor, (tampered,)),
                    promotion_intent_id=prepared.promotion_intent_id,
                )
        finally:
            if uow.active:
                uow.rollback()
            connection.close()
        self.assertIsNone(
            self._read_one(
                "SELECT artifact_id FROM artifact WHERE artifact_id=?",
                (result.descriptor.artifact_id,),
            )
        )
        self.assertTrue(self.store.staging_path(stage.staging_token).exists())

    def test_catalog_commit_rejects_noncanonical_intent_descriptor_json(self) -> None:
        stage, prepared, references = self._prepare(b"noncanonical intent descriptor")
        result = self.coordinator.promote(
            prepared,
            media_type="text/plain",
            role="TEXT_REPORT",
            provenance_entity_id="prv_artifact_lifecycle_test",
            schema_fingerprint="v3.test.artifact-lifecycle/1.0",
            semantic_fingerprint=stage.sha256,
            published_at=NOW,
        )
        descriptor_row = self._read_one(
            "SELECT descriptor_json FROM artifact_promotion_intent WHERE promotion_intent_id=?",
            (prepared.promotion_intent_id,),
        )
        noncanonical = json.dumps(json.loads(descriptor_row[0]), ensure_ascii=False)
        self.assertNotEqual(noncanonical, descriptor_row[0])
        connection = connect_catalog(self.database)
        try:
            connection.execute(
                "UPDATE artifact_promotion_intent SET descriptor_json=? WHERE promotion_intent_id=?",
                (noncanonical, prepared.promotion_intent_id),
            )
            connection.commit()
        finally:
            connection.close()

        connection = connect_catalog(self.database)
        uow = SQLiteUnitOfWork(
            connection,
            TransactionMode.PUBLISH,
            publish_callbacks=_NoopPublishCallbacks(),
        )
        try:
            uow.begin()
            with self.assertRaises(ValueError):
                SQLiteArtifactPublicationPort(uow).publish(
                    ArtifactPublication(result.descriptor, references),
                    promotion_intent_id=prepared.promotion_intent_id,
                )
        finally:
            if uow.active:
                uow.rollback()
            connection.close()
        self.assertIsNone(
            self._read_one(
                "SELECT artifact_id FROM artifact WHERE artifact_id=?",
                (result.descriptor.artifact_id,),
            )
        )

    def test_reconcile_rejects_intent_safe_format_not_allowed_by_store_policy(self) -> None:
        stage, prepared, _ = self._prepare(b"safe format policy authority")
        intent_row = self._read_one(
            "SELECT descriptor_json FROM artifact_promotion_intent WHERE promotion_intent_id=?",
            (prepared.promotion_intent_id,),
        )
        descriptor = json.loads(intent_row[0])
        descriptor["safe_format_id"] = "canonical-finite-json-v1"
        connection = connect_catalog(self.database)
        try:
            connection.execute(
                "UPDATE artifact_promotion_intent SET descriptor_json=? WHERE promotion_intent_id=?",
                (
                    json.dumps(descriptor, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    prepared.promotion_intent_id,
                ),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(ArtifactCollision):
            self.coordinator.promote(
                prepared,
                media_type="text/plain",
                role="TEXT_REPORT",
                provenance_entity_id="prv_artifact_lifecycle_test",
                schema_fingerprint="v3.test.artifact-lifecycle/1.0",
                semantic_fingerprint=stage.sha256,
                published_at=NOW,
            )
        self.assertTrue(self.store.staging_path(stage.staging_token).exists())

    def test_wrong_final_collision_never_overwrites_admitted_unknown_bytes(self) -> None:
        stage, prepared, _ = self._prepare(b"admitted payload")
        final = self.store.final_path("art_sha256_" + stage.sha256)
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_bytes(b"unknown bytes")

        with self.assertRaises(ArtifactCollision):
            self.coordinator.promote(
                prepared,
                media_type="text/plain",
                role="TEXT_REPORT",
                provenance_entity_id="prv_artifact_lifecycle_test",
                schema_fingerprint="v3.test.artifact-lifecycle/1.0",
                semantic_fingerprint=stage.sha256,
                published_at=NOW,
            )

        self.assertEqual(final.read_bytes(), b"unknown bytes")
        self.assertTrue(self.store.staging_path(stage.staging_token).exists())

    def test_catalog_commit_then_cleanup_failure_is_reconciled_without_republishing(self) -> None:
        stage, prepared, references = self._prepare(b"cleanup can be retried")
        result = self._promote_and_catalog_commit(
            stage, prepared, references, finalize=False
        )
        with patch.object(
            self.store,
            "cleanup_staging",
            side_effect=OSError("simulated cleanup I/O failure"),
        ):
            pending = self.coordinator.finalize(prepared)
        self.assertEqual(pending["state"], "CLEANUP_PENDING")
        self.assertTrue(self.store.staging_path(stage.staging_token).exists())
        summary = self.coordinator.reconcile()
        self.assertEqual(summary["promotion_finalized"], 1)
        self.assertEqual(
            self._read_one(
                "SELECT COUNT(*) FROM artifact WHERE artifact_id=?",
                (result.descriptor.artifact_id,),
            )[0],
            1,
        )
        self.assertFalse(self.store.staging_path(stage.staging_token).exists())

    def test_quarantine_and_purge_reconcile_after_process_loss_between_bytes_and_catalog(self) -> None:
        candidate = self._make_released_candidate(b"recoverable gc bytes")
        graph = ReachabilityGraph((self.project_id,), ())
        plan, batch = self._record_gc_plan(
            candidate=candidate,
            phase="QUARANTINE",
            created_at=NOW,
            reachability_fingerprint=graph.fingerprint(),
        )
        self.coordinator.confirm_gc_batch(
            gc_batch_id=batch["gc_batch_id"],
            plan_artifact_id=plan.plan_artifact_id,
            exact_ids_hash=plan.exact_artifact_ids_hash,
            confirmation_nonce="gc-crash-confirm",
            now=NOW + timedelta(minutes=1),
        )
        original_quarantine = self.store.quarantine_published_bytes

        def move_then_crash(*args, **kwargs):
            value = original_quarantine(*args, **kwargs)
            raise KeyboardInterrupt("simulated process loss after quarantine move")

        with patch.object(self.store, "quarantine_published_bytes", side_effect=move_then_crash):
            with self.assertRaises(KeyboardInterrupt):
                self.coordinator.execute_quarantine(
                    gc_batch_id=batch["gc_batch_id"], now=NOW + timedelta(minutes=2)
                )
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact_gc_batch WHERE gc_batch_id=?",
                (batch["gc_batch_id"],),
            )[0],
            "EXECUTING",
        )
        restarted_summary = self.coordinator.reconcile_gc()
        self.assertEqual(restarted_summary["gc_batches_completed"], 1)
        self.assertFalse(self.store.final_path(candidate.descriptor.artifact_id).exists())

        # A separate PURGE batch is constructed from the retained quarantine
        # row; the same process-loss boundary must resolve to one tombstone.
        purge_time = NOW + timedelta(days=30, minutes=3)
        fingerprint, _, _, _, _ = self.coordinator._current_gc_snapshot(self.project_id)
        purge_plan, purge_batch = self._record_gc_plan(
            candidate=candidate,
            phase="PURGE",
            created_at=purge_time,
            reachability_fingerprint=fingerprint,
        )
        self.coordinator.confirm_gc_batch(
            gc_batch_id=purge_batch["gc_batch_id"],
            plan_artifact_id=purge_plan.plan_artifact_id,
            exact_ids_hash=purge_plan.exact_artifact_ids_hash,
            confirmation_nonce="purge-crash-confirm",
            now=purge_time + timedelta(minutes=1),
        )
        original_purge = self.store.purge_quarantined_bytes

        def purge_then_crash(*args, **kwargs):
            value = original_purge(*args, **kwargs)
            raise KeyboardInterrupt("simulated process loss after purge move")

        with patch.object(self.store, "purge_quarantined_bytes", side_effect=purge_then_crash):
            with self.assertRaises(KeyboardInterrupt):
                self.coordinator.execute_purge(
                    gc_batch_id=purge_batch["gc_batch_id"],
                    now=purge_time + timedelta(minutes=2),
                )
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact_gc_batch WHERE gc_batch_id=?",
                (purge_batch["gc_batch_id"],),
            )[0],
            "EXECUTING",
        )
        self.assertEqual(self.coordinator.reconcile_gc()["gc_batches_completed"], 1)
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact WHERE artifact_id=?",
                (candidate.descriptor.artifact_id,),
            )[0],
            "DELETED",
        )
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact_quarantine WHERE artifact_id=? AND state='PURGED'",
                (candidate.descriptor.artifact_id,),
            )[0],
            "PURGED",
        )

    def test_gc_confirmation_is_invalidated_by_new_reference_and_quarantine_has_receipt(self) -> None:
        candidate = self._make_released_candidate()
        graph = ReachabilityGraph((self.project_id,), ())
        plan, batch = self._record_gc_plan(
            candidate=candidate,
            phase="QUARANTINE",
            created_at=NOW,
            reachability_fingerprint=graph.fingerprint(),
        )
        confirmed = self.coordinator.confirm_gc_batch(
            gc_batch_id=batch["gc_batch_id"],
            plan_artifact_id=plan.plan_artifact_id,
            exact_ids_hash=plan.exact_artifact_ids_hash,
            confirmation_nonce="nonce-1",
            now=NOW + timedelta(minutes=1),
        )
        self.assertEqual(confirmed["state"], "CONFIRMED")

        connection = connect_catalog(self.database)
        try:
            connection.execute(
                """
                INSERT INTO artifact_reference(
                    artifact_reference_id,owner_type,owner_id,role,artifact_id,state,created_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    "arf_" + f"{99:026d}",
                    "Project",
                    self.project_id,
                    "NEW_OWNER_REFERENCE",
                    candidate.descriptor.artifact_id,
                    "ACTIVE",
                    NOW.isoformat().replace("+00:00", "Z"),
                ),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(GarbageCollectionSafetyError):
            self.coordinator.execute_quarantine(
                gc_batch_id=batch["gc_batch_id"], now=NOW + timedelta(minutes=2)
            )
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact_gc_batch WHERE gc_batch_id=?",
                (batch["gc_batch_id"],),
            )[0],
            "STALE",
        )

    def test_gc_execution_barrier_blocks_new_reference_and_promotion_intent(self) -> None:
        candidate = self._make_released_candidate(b"GC execution barrier")
        plan, batch = self._record_gc_plan(
            candidate=candidate,
            phase="QUARANTINE",
            created_at=NOW,
            reachability_fingerprint=ReachabilityGraph((self.project_id,), ()).fingerprint(),
        )
        self.coordinator.confirm_gc_batch(
            gc_batch_id=batch["gc_batch_id"],
            plan_artifact_id=plan.plan_artifact_id,
            exact_ids_hash=plan.exact_artifact_ids_hash,
            confirmation_nonce="barrier-confirm",
            now=NOW + timedelta(minutes=1),
        )
        self.coordinator._prepare_quarantine_records(batch, NOW + timedelta(minutes=2))
        candidate_id = candidate.descriptor.artifact_id
        connection = connect_catalog(self.database)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO artifact_reference(
                        artifact_reference_id,owner_type,owner_id,role,artifact_id,state,created_at
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        "arf_" + "Z" * 26,
                        "Project",
                        self.project_id,
                        "LATE_REFERENCE",
                        candidate_id,
                        "ACTIVE",
                        NOW.isoformat().replace("+00:00", "Z"),
                    ),
                )
        finally:
            connection.close()

        staged = self.store.stage_bytes(b"attempted concurrent publication")
        connection = connect_catalog(self.database)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO artifact_promotion_intent(
                        promotion_intent_id,artifact_id,expected_sha256,expected_byte_size,
                        staging_token,staging_key,final_storage_key,state,state_version,
                        descriptor_json,references_json,created_at,updated_at,finalized_at,
                        last_error_code,last_error_detail_artifact_id
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        "api_" + "B" * 26,
                        candidate_id,
                        candidate.descriptor.sha256,
                        candidate.descriptor.byte_size,
                        staged.staging_token,
                        f".staging/{staged.staging_token}.stage",
                        candidate.descriptor.storage_key,
                        "STAGED_SYNCED",
                        1,
                        "{}",
                        "[]",
                        NOW.isoformat().replace("+00:00", "Z"),
                        NOW.isoformat().replace("+00:00", "Z"),
                        None,
                        None,
                        None,
                    ),
                )
        finally:
            connection.close()

    def test_gc_reconcile_closes_normal_storage_failure_with_failed_receipt(self) -> None:
        candidate = self._make_released_candidate(b"unavailable gc bytes")
        plan, batch = self._record_gc_plan(
            candidate=candidate,
            phase="QUARANTINE",
            created_at=NOW,
            reachability_fingerprint=ReachabilityGraph((self.project_id,), ()).fingerprint(),
        )
        self.coordinator.confirm_gc_batch(
            gc_batch_id=batch["gc_batch_id"],
            plan_artifact_id=plan.plan_artifact_id,
            exact_ids_hash=plan.exact_artifact_ids_hash,
            confirmation_nonce="reconcile-failure-confirm",
            now=NOW + timedelta(minutes=1),
        )
        self.coordinator._prepare_quarantine_records(batch, NOW + timedelta(minutes=2))
        self.store.final_path(candidate.descriptor.artifact_id).unlink()

        summary = self.coordinator.reconcile_gc()

        self.assertEqual(summary["gc_batches_seen"], 1)
        self.assertEqual(summary["gc_batches_completed"], 0)
        self.assertEqual(summary["gc_batches_failed"], 1)
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact_gc_batch WHERE gc_batch_id=?",
                (batch["gc_batch_id"],),
            )[0],
            "FAILED",
        )
        self.assertEqual(
            self._read_one(
                "SELECT result FROM artifact_gc_receipt WHERE gc_batch_id=? ORDER BY created_at DESC LIMIT 1",
                (batch["gc_batch_id"],),
            )[0],
            "FAILED",
        )

    def test_gc_reconcile_does_not_commit_corrupt_quarantined_bytes(self) -> None:
        candidate = self._make_released_candidate(b"corrupt quarantine evidence")
        plan, batch = self._record_gc_plan(
            candidate=candidate,
            phase="QUARANTINE",
            created_at=NOW,
            reachability_fingerprint=ReachabilityGraph((self.project_id,), ()).fingerprint(),
        )
        self.coordinator.confirm_gc_batch(
            gc_batch_id=batch["gc_batch_id"],
            plan_artifact_id=plan.plan_artifact_id,
            exact_ids_hash=plan.exact_artifact_ids_hash,
            confirmation_nonce="corrupt-quarantine-confirm",
            now=NOW + timedelta(minutes=1),
        )
        records = self.coordinator._prepare_quarantine_records(batch, NOW + timedelta(minutes=2))
        record = records[0]
        self.store.quarantine_published_bytes(
            candidate.descriptor.artifact_id,
            batch["gc_batch_id"],
            expected_byte_size=candidate.descriptor.byte_size,
        )
        connection = connect_catalog(self.database)
        try:
            connection.execute(
                "UPDATE artifact SET state='QUARANTINED' WHERE artifact_id=?",
                (candidate.descriptor.artifact_id,),
            )
            connection.execute(
                "UPDATE artifact_quarantine SET state='QUARANTINED' WHERE artifact_id=? AND gc_batch_id=?",
                (candidate.descriptor.artifact_id, batch["gc_batch_id"]),
            )
            connection.commit()
        finally:
            connection.close()
        quarantine_path, _ = self.store.quarantine_path(
            candidate.descriptor.artifact_id, batch["gc_batch_id"]
        )
        quarantine_path.write_bytes(b"corrupt evidence")

        summary = self.coordinator.reconcile_gc()

        self.assertEqual(summary["gc_batches_failed"], 1)
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact_gc_batch WHERE gc_batch_id=?",
                (batch["gc_batch_id"],),
            )[0],
            "FAILED",
        )
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact WHERE artifact_id=?",
                (candidate.descriptor.artifact_id,),
            )[0],
            "QUARANTINED",
        )
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact_quarantine WHERE artifact_id=? AND gc_batch_id=?",
                (candidate.descriptor.artifact_id, batch["gc_batch_id"]),
            )[0],
            "QUARANTINED",
        )

    def test_gc_reconcile_does_not_apply_purge_evidence_when_plan_validation_fails(self) -> None:
        candidate = self._make_released_candidate(b"purge validation must fail closed")
        graph = ReachabilityGraph((self.project_id,), ())
        quarantine_plan, quarantine_batch = self._record_gc_plan(
            candidate=candidate,
            phase="QUARANTINE",
            created_at=NOW,
            reachability_fingerprint=graph.fingerprint(),
        )
        self.coordinator.confirm_gc_batch(
            gc_batch_id=quarantine_batch["gc_batch_id"],
            plan_artifact_id=quarantine_plan.plan_artifact_id,
            exact_ids_hash=quarantine_plan.exact_artifact_ids_hash,
            confirmation_nonce="purge-validation-quarantine-confirm",
            now=NOW + timedelta(minutes=1),
        )
        self.coordinator.execute_quarantine(
            gc_batch_id=quarantine_batch["gc_batch_id"], now=NOW + timedelta(minutes=2)
        )

        purge_time = NOW + timedelta(days=30, minutes=3)
        fingerprint, _, _, _, _ = self.coordinator._current_gc_snapshot(self.project_id)
        purge_plan, purge_batch = self._record_gc_plan(
            candidate=candidate,
            phase="PURGE",
            created_at=purge_time,
            reachability_fingerprint=fingerprint,
        )
        self.coordinator.confirm_gc_batch(
            gc_batch_id=purge_batch["gc_batch_id"],
            plan_artifact_id=purge_plan.plan_artifact_id,
            exact_ids_hash=purge_plan.exact_artifact_ids_hash,
            confirmation_nonce="purge-validation-confirm",
            now=purge_time + timedelta(minutes=1),
        )
        self.coordinator._set_gc_state(
            purge_batch["gc_batch_id"],
            expected_state="CONFIRMED",
            target_state="EXECUTING",
            now=purge_time + timedelta(minutes=2),
        )
        quarantine_path, _ = self.store.quarantine_path(
            candidate.descriptor.artifact_id, quarantine_batch["gc_batch_id"]
        )
        quarantine_path.unlink()
        self.store.final_path(purge_plan.plan_artifact_id).write_bytes(b"tampered plan")

        summary = self.coordinator.reconcile_gc()

        self.assertEqual(summary["gc_batches_failed"], 1)
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact_gc_batch WHERE gc_batch_id=?",
                (purge_batch["gc_batch_id"],),
            )[0],
            "FAILED",
        )
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact WHERE artifact_id=?",
                (candidate.descriptor.artifact_id,),
            )[0],
            "QUARANTINED",
        )
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact_quarantine WHERE artifact_id=? AND gc_batch_id=?",
                (candidate.descriptor.artifact_id, quarantine_batch["gc_batch_id"]),
            )[0],
            "QUARANTINED",
        )

    def test_gc_quarantine_restore_and_second_purge_plan_are_distinct_confirmed_steps(self) -> None:
        candidate = self._make_released_candidate(b"quarantine then purge")
        initial_graph = ReachabilityGraph((self.project_id,), ())
        quarantine_plan, quarantine_batch = self._record_gc_plan(
            candidate=candidate,
            phase="QUARANTINE",
            created_at=NOW,
            reachability_fingerprint=initial_graph.fingerprint(),
        )
        self.coordinator.confirm_gc_batch(
            gc_batch_id=quarantine_batch["gc_batch_id"],
            plan_artifact_id=quarantine_plan.plan_artifact_id,
            exact_ids_hash=quarantine_plan.exact_artifact_ids_hash,
            confirmation_nonce="quarantine-confirm",
            now=NOW + timedelta(minutes=1),
        )
        quarantine_receipt = self.coordinator.execute_quarantine(
            gc_batch_id=quarantine_batch["gc_batch_id"], now=NOW + timedelta(minutes=2)
        )
        self.assertEqual(quarantine_receipt["result"], "QUARANTINED")
        self.assertEqual(
            self.coordinator.execute_quarantine(
                gc_batch_id=quarantine_batch["gc_batch_id"], now=NOW + timedelta(minutes=3)
            )["receipt_id"],
            quarantine_receipt["receipt_id"],
        )
        self.assertFalse(self.store.final_path(candidate.descriptor.artifact_id).exists())

        restored = self.coordinator.restore_quarantined_batch(
            gc_batch_id=quarantine_batch["gc_batch_id"], now=NOW + timedelta(minutes=3)
        )
        self.assertEqual(restored["result"], "RESTORED")
        self.assertTrue(self.store.final_path(candidate.descriptor.artifact_id).exists())
        restored_again = self.coordinator.restore_quarantined_batch(
            gc_batch_id=quarantine_batch["gc_batch_id"], now=NOW + timedelta(minutes=4)
        )
        self.assertEqual(restored_again["receipt_id"], restored["receipt_id"])
        self.assertEqual(
            self._read_one(
                "SELECT COUNT(*) FROM artifact_gc_receipt WHERE gc_batch_id=? AND result='RESTORED'",
                (quarantine_batch["gc_batch_id"],),
            )[0],
            1,
        )

        # Recreate the quarantine batch so the purge test cannot accidentally
        # reuse a restore receipt or the first confirmation.
        second_candidate = self._make_released_candidate(b"purge without restore")
        second_fingerprint, _, _, _, _ = self.coordinator._current_gc_snapshot(self.project_id)
        second_plan, second_batch = self._record_gc_plan(
            candidate=second_candidate,
            phase="QUARANTINE",
            created_at=NOW,
            reachability_fingerprint=second_fingerprint,
        )
        self.coordinator.confirm_gc_batch(
            gc_batch_id=second_batch["gc_batch_id"],
            plan_artifact_id=second_plan.plan_artifact_id,
            exact_ids_hash=second_plan.exact_artifact_ids_hash,
            confirmation_nonce="second-quarantine-confirm",
            now=NOW + timedelta(minutes=1),
        )
        self.coordinator.execute_quarantine(
            gc_batch_id=second_batch["gc_batch_id"], now=NOW + timedelta(minutes=2)
        )

        current_fingerprint, _, _, _, _ = self.coordinator._current_gc_snapshot(self.project_id)
        purge_time = NOW + timedelta(days=30, minutes=3)
        purge_plan, purge_batch = self._record_gc_plan(
            candidate=second_candidate,
            phase="PURGE",
            created_at=purge_time,
            reachability_fingerprint=current_fingerprint,
        )
        # The generated plan is new and is confirmed independently from the
        # quarantine batch; attempting purge before this confirmation is not
        # part of the allowed path.
        self.coordinator.confirm_gc_batch(
            gc_batch_id=purge_batch["gc_batch_id"],
            plan_artifact_id=purge_plan.plan_artifact_id,
            exact_ids_hash=purge_plan.exact_artifact_ids_hash,
            confirmation_nonce="purge-confirm",
            now=purge_time + timedelta(minutes=1),
        )
        receipt = self.coordinator.execute_purge(
            gc_batch_id=purge_batch["gc_batch_id"], now=purge_time + timedelta(minutes=2)
        )
        self.assertEqual(receipt["result"], "PURGED")
        self.assertEqual(
            self.coordinator.execute_purge(
                gc_batch_id=purge_batch["gc_batch_id"], now=purge_time + timedelta(minutes=3)
            )["receipt_id"],
            receipt["receipt_id"],
        )
        self.assertEqual(receipt["exact_bytes"], len(b"purge without restore"))
        self.assertEqual(receipt["reclaimed_bytes"], len(b"purge without restore"))
        self.assertFalse(
            self.store.quarantine_path(
                second_candidate.descriptor.artifact_id, second_batch["gc_batch_id"]
            )[0].exists()
        )
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact WHERE artifact_id=?",
                (second_candidate.descriptor.artifact_id,),
            )[0],
            "DELETED",
        )
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact_quarantine WHERE artifact_id=? AND state='PURGED'",
                (second_candidate.descriptor.artifact_id,),
            )[0],
            "PURGED",
        )

    def test_reconcile_recovers_promoting_remnant_without_retained_stage(self) -> None:
        payload = b"recover atomic promoting remnant"
        stage, prepared, references = self._prepare(payload)
        final = self.store.final_path("art_sha256_" + stage.sha256)
        final.parent.mkdir(parents=True, exist_ok=True)
        promoting = final.with_name(
            final.name + ".promoting." + prepared.promotion_intent_id
        )
        promoting.write_bytes(payload)
        stage_path = self.store.staging_path(stage.staging_token)
        stage_path.unlink()

        summary = self.coordinator.reconcile()

        self.assertEqual(summary["promotion_finalized"], 1)
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact_promotion_intent WHERE promotion_intent_id=?",
                (prepared.promotion_intent_id,),
            )[0],
            "FINALIZED",
        )
        self.assertEqual(
            self.store.verify_final_bytes("art_sha256_" + stage.sha256),
            (stage.sha256, len(payload)),
        )
        self.assertFalse(promoting.exists())
        self.assertFalse(stage_path.exists())

    def test_reconcile_isolates_promoting_remnant_without_matching_intent(self) -> None:
        payload = b"unadmitted promoting remnant"
        stage = self.store.stage_bytes(payload)
        final = self.store.final_path("art_sha256_" + stage.sha256)
        final.parent.mkdir(parents=True, exist_ok=True)
        promoting = final.with_name(final.name + ".promoting.api_" + "X" * 26)
        promoting.write_bytes(payload)
        stage_path = self.store.staging_path(stage.staging_token)
        stage_path.unlink()

        summary = self.coordinator.reconcile()

        self.assertEqual(summary["orphan_promoting_bytes_seen"], 1)
        self.assertEqual(summary["orphan_promoting_bytes_isolated"], 1)
        self.assertFalse(promoting.exists())
        self.assertTrue(
            tuple((self.store.quarantine_root / "conflicts").glob("*.entry"))
        )

    def test_restore_reconciles_after_durable_restore_intent_process_loss(self) -> None:
        candidate = self._make_released_candidate(b"restore crash boundary")
        plan, batch = self._record_gc_plan(
            candidate=candidate,
            phase="QUARANTINE",
            created_at=NOW,
            reachability_fingerprint=ReachabilityGraph((self.project_id,), ()).fingerprint(),
        )
        self.coordinator.confirm_gc_batch(
            gc_batch_id=batch["gc_batch_id"],
            plan_artifact_id=plan.plan_artifact_id,
            exact_ids_hash=plan.exact_artifact_ids_hash,
            confirmation_nonce="restore-crash-confirm",
            now=NOW + timedelta(minutes=1),
        )
        self.coordinator.execute_quarantine(
            gc_batch_id=batch["gc_batch_id"], now=NOW + timedelta(minutes=2)
        )
        original_restore = self.store.restore_quarantined_bytes

        def restore_then_crash(*args, **kwargs):
            value = original_restore(*args, **kwargs)
            raise KeyboardInterrupt("simulated process loss after restore move")

        with patch.object(
            self.store,
            "restore_quarantined_bytes",
            side_effect=restore_then_crash,
        ):
            with self.assertRaises(KeyboardInterrupt):
                self.coordinator.restore_quarantined_batch(
                    gc_batch_id=batch["gc_batch_id"], now=NOW + timedelta(minutes=3)
                )

        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact_quarantine WHERE artifact_id=? AND gc_batch_id=?",
                (candidate.descriptor.artifact_id, batch["gc_batch_id"]),
            )[0],
            "RESTORED",
        )
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact WHERE artifact_id=?",
                (candidate.descriptor.artifact_id,),
            )[0],
            "QUARANTINED",
        )
        generic_summary = self.coordinator.reconcile()
        self.assertEqual(generic_summary["orphan_final_bytes_isolated"], 0)
        self.assertTrue(self.store.final_path(candidate.descriptor.artifact_id).exists())
        summary = self.coordinator.reconcile_gc()

        self.assertEqual(summary["gc_restores_completed"], 1)
        self.assertTrue(self.store.final_path(candidate.descriptor.artifact_id).exists())
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact WHERE artifact_id=?",
                (candidate.descriptor.artifact_id,),
            )[0],
            "PUBLISHED",
        )

    def test_restore_rejects_completed_batch_with_incomplete_exact_records(self) -> None:
        candidate = self._make_released_candidate(b"restore exact-set binding")
        plan, batch = self._record_gc_plan(
            candidate=candidate,
            phase="QUARANTINE",
            created_at=NOW,
            reachability_fingerprint=ReachabilityGraph((self.project_id,), ()).fingerprint(),
        )
        self.coordinator.confirm_gc_batch(
            gc_batch_id=batch["gc_batch_id"],
            plan_artifact_id=plan.plan_artifact_id,
            exact_ids_hash=plan.exact_artifact_ids_hash,
            confirmation_nonce="restore-exact-record-confirm",
            now=NOW + timedelta(minutes=1),
        )
        self.coordinator.execute_quarantine(
            gc_batch_id=batch["gc_batch_id"], now=NOW + timedelta(minutes=2)
        )
        connection = connect_catalog(self.database)
        try:
            connection.execute(
                "DELETE FROM artifact_quarantine WHERE artifact_id=? AND gc_batch_id=?",
                (candidate.descriptor.artifact_id, batch["gc_batch_id"]),
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(GarbageCollectionSafetyError):
            self.coordinator.restore_quarantined_batch(
                gc_batch_id=batch["gc_batch_id"], now=NOW + timedelta(minutes=3)
            )

    def test_restore_stales_unstarted_overlapping_purge_batch(self) -> None:
        candidate = self._make_released_candidate(b"restore invalidates purge")
        plan, quarantine_batch = self._record_gc_plan(
            candidate=candidate,
            phase="QUARANTINE",
            created_at=NOW,
            reachability_fingerprint=ReachabilityGraph((self.project_id,), ()).fingerprint(),
        )
        self.coordinator.confirm_gc_batch(
            gc_batch_id=quarantine_batch["gc_batch_id"],
            plan_artifact_id=plan.plan_artifact_id,
            exact_ids_hash=plan.exact_artifact_ids_hash,
            confirmation_nonce="restore-stale-quarantine",
            now=NOW + timedelta(minutes=1),
        )
        self.coordinator.execute_quarantine(
            gc_batch_id=quarantine_batch["gc_batch_id"], now=NOW + timedelta(minutes=2)
        )

        current_fingerprint, _, _, _, _ = self.coordinator._current_gc_snapshot(
            self.project_id,
            exclude_artifact_ids=frozenset(),
        )
        purge_plan, purge_batch = self._record_gc_plan(
            candidate=candidate,
            phase="PURGE",
            created_at=NOW + timedelta(days=30),
            reachability_fingerprint=current_fingerprint,
        )
        self.coordinator.confirm_gc_batch(
            gc_batch_id=purge_batch["gc_batch_id"],
            plan_artifact_id=purge_plan.plan_artifact_id,
            exact_ids_hash=purge_plan.exact_artifact_ids_hash,
            confirmation_nonce="restore-stale-purge",
            now=NOW + timedelta(days=30, minutes=5),
        )

        receipt = self.coordinator.restore_quarantined_batch(
            gc_batch_id=quarantine_batch["gc_batch_id"],
            now=NOW + timedelta(days=30, minutes=6),
        )

        self.assertEqual(receipt["result"], "RESTORED")
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact_gc_batch WHERE gc_batch_id=?",
                (purge_batch["gc_batch_id"],),
            )[0],
            "STALE",
        )
        self.assertEqual(
            self._read_one(
                "SELECT state FROM artifact WHERE artifact_id=?",
                (candidate.descriptor.artifact_id,),
            )[0],
            "PUBLISHED",
        )


if __name__ == "__main__":
    unittest.main()
