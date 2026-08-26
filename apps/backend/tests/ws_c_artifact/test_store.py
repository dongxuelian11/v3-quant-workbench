from __future__ import annotations

import hashlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from v3_backend.adapters.artifact_store import FileSystemArtifactStore
from v3_backend.domain.artifacts.exceptions import (
    ArtifactCollision,
    CapabilityUnavailable,
    IntegrityMismatch,
    FormatRejected,
)
from v3_backend.domain.artifacts.identity import artifact_id_for_bytes, storage_key_for_sha256


class FileSystemArtifactStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = FileSystemArtifactStore(self.root)

    def publish(self, payload: bytes, token: str | None = None):
        receipt = self.store.stage_bytes(payload) if token is None else None
        return self.store.publish(
            receipt.staging_token if receipt else token,
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            expected_byte_size=len(payload),
            media_type="text/plain",
            role="TEXT_REPORT",
            provenance_entity_id="prv_01H00000000000000000000000",
        )

    def test_atomic_publish_rehash_and_canonical_key(self) -> None:
        payload = b"durable bytes"
        result = self.publish(payload)
        self.assertFalse(result.deduplicated)
        self.assertEqual(result.descriptor.artifact_id, artifact_id_for_bytes(payload))
        self.assertEqual(self.store.read_bytes(result.descriptor.artifact_id), payload)
        final = self.root.joinpath(*result.storage_key.split("/"))
        self.assertTrue(final.is_file())
        self.assertFalse(any(self.store.staging_root.iterdir()))

    def test_concurrent_identical_publish_deduplicates(self) -> None:
        payload = b"same content" * 4096
        receipts = (self.store.stage_bytes(payload), self.store.stage_bytes(payload))

        def publish_token(token: str):
            return self.store.publish(
                token,
                expected_sha256=hashlib.sha256(payload).hexdigest(),
                expected_byte_size=len(payload),
                media_type="text/plain",
                role="TEXT_REPORT",
                provenance_entity_id="prv_01H00000000000000000000000",
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(pool.map(publish_token, (item.staging_token for item in receipts)))
        self.assertEqual(sum(result.deduplicated for result in results), 1)
        self.assertEqual({result.descriptor.artifact_id for result in results}, {artifact_id_for_bytes(payload)})
        self.assertEqual(self.store.read_bytes(results[0].descriptor.artifact_id), payload)

    def test_impossible_collision_is_rejected(self) -> None:
        payload = b"expected"
        receipt = self.store.stage_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        final = self.root.joinpath(*storage_key_for_sha256(digest).split("/"))
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_bytes(b"different")
        with self.assertRaises(ArtifactCollision):
            self.store.publish(
                receipt.staging_token,
                expected_sha256=digest,
                expected_byte_size=len(payload),
                media_type="text/plain",
                role="TEXT_REPORT",
                provenance_entity_id="prv_01H00000000000000000000000",
            )

    def test_content_namespace_rejects_non_directory_shard(self) -> None:
        digest = "aa" + "bb" + "0" * 60
        (self.store.content_root / "aa").write_bytes(b"not a directory")
        with self.assertRaises(IntegrityMismatch):
            self.store.final_path("art_sha256_" + digest)

    def test_quarantine_namespace_rejects_non_directory_shard(self) -> None:
        digest = "aa" + "bb" + "0" * 60
        (self.store.quarantine_root / "aa").write_bytes(b"not a directory")
        with self.assertRaises(IntegrityMismatch):
            self.store.quarantine_path("art_sha256_" + digest, "gcb_" + "0" * 26)

    def test_staged_tampering_and_size_mismatch_are_rejected(self) -> None:
        receipt = self.store.stage_bytes(b"abc")
        self.store._staging_path(receipt.staging_token).write_bytes(b"tampered")
        with self.assertRaises(IntegrityMismatch):
            self.store.publish(
                receipt.staging_token,
                expected_sha256=receipt.sha256,
                expected_byte_size=receipt.byte_size,
                media_type="text/plain",
                role="TEXT_REPORT",
                provenance_entity_id="prv_01H00000000000000000000000",
            )

    def test_interrupted_staging_is_recoverable_by_token(self) -> None:
        payload = b"resume after process interruption"
        receipt = self.store.stage_bytes(payload)
        restarted = FileSystemArtifactStore(self.root)
        recovered = restarted.recover_staging()
        self.assertEqual([(item.staging_token, item.sha256) for item in recovered], [(receipt.staging_token, receipt.sha256)])
        result = restarted.publish(
            receipt.staging_token,
            expected_sha256=receipt.sha256,
            expected_byte_size=receipt.byte_size,
            media_type="text/plain",
            role="TEXT_REPORT",
            provenance_entity_id="prv_01H00000000000000000000000",
        )
        self.assertEqual(restarted.read_bytes(result.descriptor.artifact_id), payload)

    def test_unadmitted_parquet_format_fails_closed_and_keeps_stage(self) -> None:
        receipt = self.store.stage_bytes(b"not parquet")
        with self.assertRaises(CapabilityUnavailable):
            self.store.publish(
                receipt.staging_token,
                expected_sha256=receipt.sha256,
                expected_byte_size=receipt.byte_size,
                media_type="application/vnd.apache.parquet",
                role="PARQUET_PARTITION",
                provenance_entity_id="prv_01H00000000000000000000000",
            )
        self.assertTrue(self.store._staging_path(receipt.staging_token).exists())

    def test_declared_media_bytes_are_validated_before_publication(self) -> None:
        invalid_text = self.store.stage_bytes(b"\xff")
        with self.assertRaises(FormatRejected):
            self.store.publish(
                invalid_text.staging_token,
                expected_sha256=invalid_text.sha256,
                expected_byte_size=invalid_text.byte_size,
                media_type="text/plain",
                role="TEXT_REPORT",
                provenance_entity_id="prv_01H00000000000000000000000",
            )
        noncanonical_json = self.store.stage_bytes(b'{"z": 1, "a": 2}')
        with self.assertRaises(FormatRejected):
            self.store.publish(
                noncanonical_json.staging_token,
                expected_sha256=noncanonical_json.sha256,
                expected_byte_size=noncanonical_json.byte_size,
                media_type="application/json",
                role="GC_PLAN",
                provenance_entity_id="prv_01H00000000000000000000000",
            )

    def test_large_payload_wire_boundary_is_artifact_ref(self) -> None:
        payload = b"x" * (2 * 1024 * 1024)
        result = self.publish(payload)
        reference = result.descriptor.to_artifact_ref()
        self.assertEqual(reference["byte_size"], len(payload))
        self.assertNotIn("bytes", reference)
        self.assertNotIn("path", reference)
        self.assertLess(len(str(reference)), 512)


if __name__ == "__main__":
    unittest.main()
