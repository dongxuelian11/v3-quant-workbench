from __future__ import annotations

import unittest
import hashlib
import tempfile
from pathlib import Path

from v3_backend.adapters.parquet import (
    LogicalField,
    LogicalSchema,
    ParquetDatasetManifest,
    ParquetPartition,
)
from v3_backend.adapters.artifact_store import FileSystemArtifactStore
from v3_backend.domain.artifacts.identity import artifact_id_for_bytes


def schema(*, nullable_price: bool = False, reverse: bool = False) -> LogicalSchema:
    fields = (
        LogicalField("instrument_id", "utf8", False),
        LogicalField("session_date", "date", False),
        LogicalField("close", "decimal", nullable_price, decimal_scale=4),
        LogicalField("available_time", "timestamp_utc", False),
    )
    if reverse:
        fields = tuple(reversed(fields))
    return LogicalSchema(
        fields=fields,
        primary_key=("instrument_id", "session_date"),
        sort_keys=("session_date", "instrument_id"),
        calendar="XSHG_XSHE_DAILY",
        timezone="Asia/Shanghai",
        null_policy="EXPLICIT_BITMAP_NO_IMPLICIT_FILL",
    )


def partition(path: str, payload: bytes, fingerprint: str, *, byte_size: int | None = None) -> ParquetPartition:
    return ParquetPartition(
        logical_path=path,
        artifact_id=artifact_id_for_bytes(payload),
        byte_size=len(payload) if byte_size is None else byte_size,
        row_count=2,
        schema_fingerprint=fingerprint,
        partition_values=(("year", 2026),),
        min_effective_time="2026-01-02",
        max_effective_time="2026-01-05",
        max_available_time="2026-01-05T09:00:00Z",
    )


def manifest(parts: tuple[ParquetPartition, ...], logical_schema: LogicalSchema | None = None):
    value = logical_schema or schema()
    return ParquetDatasetManifest(
        logical_schema=value,
        partitions=parts,
        producer_version="v3-test-producer/1",
        environment_profile_id="env_profile_test_v1",
        writer_settings=(("compression", "zstd"), ("row_group_rows", 65536), ("utc_timestamps", True)),
    )


class CanonicalManifestTests(unittest.TestCase):
    def test_partition_input_order_does_not_change_identity(self) -> None:
        logical = schema()
        a = partition("year=2026/part-000.parquet", b"a", logical.fingerprint)
        b = partition("year=2026/part-001.parquet", b"b", logical.fingerprint)
        first = manifest((a, b), logical)
        second = manifest((b, a), logical)
        self.assertEqual(first.artifact_id, second.artifact_id)
        self.assertEqual(first.canonical_bytes, second.canonical_bytes)
        self.assertEqual(tuple(item.logical_path for item in second.partitions), (a.logical_path, b.logical_path))

    def test_schema_fingerprint_is_sensitive_to_nullability_and_column_order(self) -> None:
        base = schema()
        self.assertNotEqual(base.fingerprint, schema(nullable_price=True).fingerprint)
        self.assertNotEqual(base.fingerprint, schema(reverse=True).fingerprint)

    def test_byte_identity_is_not_semantic_equality(self) -> None:
        logical = schema()
        one = manifest((partition("year=2026/p.parquet", b"physical-one", logical.fingerprint),), logical)
        two = manifest(
            (partition("year=2026/p.parquet", b"physical-two", logical.fingerprint, byte_size=999),),
            logical,
        )
        self.assertEqual(one.semantic_fingerprint, two.semantic_fingerprint)
        self.assertNotEqual(one.artifact_id, two.artifact_id)
        self.assertNotEqual(one.canonical_bytes, two.canonical_bytes)

    def test_manifest_is_compact_canonical_json(self) -> None:
        logical = schema()
        value = manifest((partition("year=2026/p.parquet", b"bytes", logical.fingerprint),), logical)
        self.assertTrue(value.canonical_bytes.startswith(b'{"environment_profile_id"'))
        self.assertNotIn(b"\n", value.canonical_bytes)
        self.assertNotIn(b": ", value.canonical_bytes)
        self.assertEqual(value.artifact_id, artifact_id_for_bytes(value.canonical_bytes))

    def test_canonical_manifest_publishes_with_manifest_identity(self) -> None:
        logical = schema()
        value = manifest((partition("year=2026/p.parquet", b"bytes", logical.fingerprint),), logical)
        with tempfile.TemporaryDirectory() as temp:
            store = FileSystemArtifactStore(Path(temp))
            staged = store.stage_bytes(value.canonical_bytes)
            result = store.publish(
                staged.staging_token,
                expected_sha256=hashlib.sha256(value.canonical_bytes).hexdigest(),
                expected_byte_size=len(value.canonical_bytes),
                media_type="application/json",
                role="PARQUET_DATASET_MANIFEST",
                schema_fingerprint=value.schema_fingerprint,
                semantic_fingerprint=value.semantic_fingerprint,
                provenance_entity_id="prv_01H00000000000000000000000",
            )
            self.assertEqual(result.descriptor.artifact_id, value.artifact_id)
            self.assertEqual(result.descriptor.schema_fingerprint, value.schema_fingerprint)
            self.assertEqual(result.descriptor.semantic_fingerprint, value.semantic_fingerprint)
            self.assertEqual(store.read_bytes(value.artifact_id), value.canonical_bytes)

    def test_partition_schema_mismatch_and_unsafe_path_rejected(self) -> None:
        logical = schema()
        with self.assertRaises(ValueError):
            manifest((partition("part.parquet", b"x", "0" * 64),), logical)
        with self.assertRaises(ValueError):
            partition("../escape.parquet", b"x", logical.fingerprint)

    def test_floating_partition_identity_is_rejected(self) -> None:
        logical = schema()
        with self.assertRaises(ValueError):
            ParquetPartition(
                logical_path="part.parquet",
                artifact_id=artifact_id_for_bytes(b"x"),
                byte_size=1,
                row_count=1,
                schema_fingerprint=logical.fingerprint,
                partition_values=(("ratio", 1.5),),  # type: ignore[arg-type]
                min_effective_time="2026-01-02",
                max_effective_time="2026-01-02",
                max_available_time="2026-01-02T09:00:00Z",
            ).canonical_value(include_byte_identity=True)


if __name__ == "__main__":
    unittest.main()
