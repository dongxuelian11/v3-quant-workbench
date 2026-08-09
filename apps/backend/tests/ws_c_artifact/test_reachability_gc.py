from __future__ import annotations

import hashlib
import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone

from v3_backend.domain.artifacts.exceptions import GarbageCollectionSafetyError
from v3_backend.domain.artifacts.identity import artifact_id_for_bytes, artifact_id_from_sha256
from v3_backend.domain.artifacts.model import ArtifactDescriptor, ArtifactReference
from v3_backend.domain.artifacts.reachability import (
    GarbageCollectionConfirmation,
    ReachabilityGraph,
    execute_confirmed_garbage_collection,
    plan_garbage_collection,
)
from v3_backend.adapters.artifact_store import FileSystemArtifactStore


NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def descriptor(payload: bytes, published_at: datetime) -> ArtifactDescriptor:
    digest = hashlib.sha256(payload).hexdigest()
    return ArtifactDescriptor(
        artifact_id=artifact_id_from_sha256(digest),
        sha256=digest,
        byte_size=len(payload),
        media_type="text/plain",
        role="TEXT_REPORT",
        safe_format_id="utf8-text-v1",
        created_at=published_at,
        published_at=published_at,
        provenance_entity_id="prv_01H00000000000000000000000",
    )


def reference(owner_id: str, artifact_id: str, suffix: str = "0") -> ArtifactReference:
    return ArtifactReference(
        reference_id="arf_" + suffix * 26,
        owner_id=owner_id,
        artifact_id=artifact_id,
        role="TEXT_REPORT",
        created_at=NOW - timedelta(days=10),
    )


class FakeDeletionPort:
    def __init__(self, available: set[str], fail: set[str] | None = None) -> None:
        self.available = available
        self.fail = fail or set()
        self.deleted: list[str] = []

    def delete_published_bytes(self, artifact_id: str) -> bool:
        if artifact_id in self.fail:
            return False
        self.available.discard(artifact_id)
        self.deleted.append(artifact_id)
        return artifact_id not in self.available


class ReachabilityAndGarbageCollectionTests(unittest.TestCase):
    def test_reachability_closure_follows_artifact_dependencies(self) -> None:
        manifest = artifact_id_for_bytes(b"manifest")
        partition = artifact_id_for_bytes(b"partition")
        statistics = artifact_id_for_bytes(b"statistics")
        graph = ReachabilityGraph(
            roots=("prj_root",),
            references=(reference("prj_root", manifest),),
            dependencies=((manifest, partition), (partition, statistics)),
        )
        self.assertEqual(graph.reachable_artifacts(), frozenset({manifest, partition, statistics}))

    def test_referenced_artifact_cannot_be_planned_for_deletion(self) -> None:
        kept = descriptor(b"kept", NOW - timedelta(days=30))
        orphan = descriptor(b"orphan", NOW - timedelta(days=30))
        graph = ReachabilityGraph(("project",), (reference("project", kept.artifact_id),))
        plan = plan_garbage_collection(
            (kept, orphan), graph, now=NOW, grace_period=timedelta(days=7)
        )
        self.assertEqual(tuple(item.artifact_id for item in plan.items), (orphan.artifact_id,))
        self.assertEqual(plan.exact_byte_size, orphan.byte_size)

    def test_grace_period_excludes_recent_orphans(self) -> None:
        recent = descriptor(b"recent", NOW - timedelta(hours=1))
        graph = ReachabilityGraph(("project",), ())
        plan = plan_garbage_collection((recent,), graph, now=NOW, grace_period=timedelta(days=1))
        self.assertEqual(plan.items, ())

    def test_gc_plan_is_a_canonical_content_addressed_artifact(self) -> None:
        orphan = descriptor(b"orphan", NOW - timedelta(days=30))
        graph = ReachabilityGraph(("project",), ())
        first = plan_garbage_collection((orphan,), graph, now=NOW, grace_period=timedelta(days=7))
        second = plan_garbage_collection((orphan,), graph, now=NOW, grace_period=timedelta(days=7))
        self.assertEqual(first.canonical_bytes(), second.canonical_bytes())
        self.assertEqual(first.plan_artifact_id, artifact_id_for_bytes(first.canonical_bytes()))

    def test_exact_confirmation_deletes_and_then_tombstones(self) -> None:
        orphan = descriptor(b"orphan", NOW - timedelta(days=30))
        graph = ReachabilityGraph(("project",), ())
        plan = plan_garbage_collection((orphan,), graph, now=NOW, grace_period=timedelta(days=7))
        confirmation = GarbageCollectionConfirmation(
            plan_artifact_id=plan.plan_artifact_id,
            artifact_ids=(orphan.artifact_id,),
            confirmed_at=NOW + timedelta(minutes=1),
        )
        deletion = FakeDeletionPort({orphan.artifact_id})
        tombstones = execute_confirmed_garbage_collection(
            plan, confirmation, graph, deletion, deleted_at=NOW + timedelta(minutes=2)
        )
        self.assertEqual(deletion.deleted, [orphan.artifact_id])
        self.assertEqual(tuple(item.artifact_id for item in tombstones), (orphan.artifact_id,))

    def test_confirmation_mismatch_and_new_reference_fail_closed(self) -> None:
        orphan = descriptor(b"orphan", NOW - timedelta(days=30))
        initial = ReachabilityGraph(("project",), ())
        plan = plan_garbage_collection((orphan,), initial, now=NOW, grace_period=timedelta(days=7))
        wrong = GarbageCollectionConfirmation(
            plan_artifact_id=artifact_id_for_bytes(b"wrong plan"),
            artifact_ids=(orphan.artifact_id,),
            confirmed_at=NOW + timedelta(minutes=1),
        )
        deletion = FakeDeletionPort({orphan.artifact_id})
        with self.assertRaises(GarbageCollectionSafetyError):
            execute_confirmed_garbage_collection(plan, wrong, initial, deletion, deleted_at=NOW)
        current = ReachabilityGraph(("project",), (reference("project", orphan.artifact_id),))
        exact = GarbageCollectionConfirmation(
            plan_artifact_id=plan.plan_artifact_id,
            artifact_ids=(orphan.artifact_id,),
            confirmed_at=NOW + timedelta(minutes=1),
        )
        with self.assertRaises(GarbageCollectionSafetyError):
            execute_confirmed_garbage_collection(plan, exact, current, deletion, deleted_at=NOW)
        self.assertEqual(deletion.deleted, [])

    def test_failed_delete_creates_no_tombstone(self) -> None:
        orphan = descriptor(b"orphan", NOW - timedelta(days=30))
        graph = ReachabilityGraph(("project",), ())
        plan = plan_garbage_collection((orphan,), graph, now=NOW, grace_period=timedelta(days=7))
        confirmation = GarbageCollectionConfirmation(
            plan.plan_artifact_id,
            (orphan.artifact_id,),
            NOW + timedelta(minutes=1),
        )
        with self.assertRaises(GarbageCollectionSafetyError):
            execute_confirmed_garbage_collection(
                plan,
                confirmation,
                graph,
                FakeDeletionPort({orphan.artifact_id}, {orphan.artifact_id}),
                deleted_at=NOW,
            )

    def test_confirmed_gc_deletes_exact_filesystem_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = FileSystemArtifactStore(Path(temp))
            payload = b"delete only after confirmation"
            staged = store.stage_bytes(payload)
            published = store.publish(
                staged.staging_token,
                expected_sha256=staged.sha256,
                expected_byte_size=staged.byte_size,
                media_type="text/plain",
                role="TEXT_REPORT",
                provenance_entity_id="prv_01H00000000000000000000000",
                published_at=NOW - timedelta(days=30),
            )
            graph = ReachabilityGraph(("project",), ())
            plan = plan_garbage_collection(
                (published.descriptor,), graph, now=NOW, grace_period=timedelta(days=7)
            )
            confirmation = GarbageCollectionConfirmation(
                plan.plan_artifact_id,
                (published.descriptor.artifact_id,),
                NOW + timedelta(minutes=1),
            )
            tombstones = execute_confirmed_garbage_collection(
                plan, confirmation, graph, store, deleted_at=NOW + timedelta(minutes=2)
            )
            self.assertEqual(len(tombstones), 1)
            self.assertTrue(store.delete_published_bytes(published.descriptor.artifact_id))


if __name__ == "__main__":
    unittest.main()
