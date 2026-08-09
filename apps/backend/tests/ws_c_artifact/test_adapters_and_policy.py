from __future__ import annotations

import dataclasses
import unittest

from v3_backend.adapters.duckdb import (
    DatasetFilter,
    DatasetQuery,
    UnavailableDuckDbAdapter,
    duckdb_adapter_without_admission,
)
from v3_backend.adapters.parquet import UnavailableParquetAdapter, parquet_adapter_without_admission
from v3_backend.domain.artifacts.exceptions import CapabilityUnavailable, FormatRejected
from v3_backend.domain.artifacts.identity import artifact_id_for_bytes
from v3_backend.domain.artifacts.policy import ADMITTED, REJECTED, UNAVAILABLE, SafeFormatPolicy


class AdmissionBoundaryTests(unittest.TestCase):
    def test_safe_format_policy_is_closed_and_role_specific(self) -> None:
        policy = SafeFormatPolicy.baseline()
        self.assertEqual(policy.decide("PARQUET_DATASET_MANIFEST", "application/json").outcome, ADMITTED)
        self.assertEqual(policy.decide("PARQUET_PARTITION", "application/vnd.apache.parquet").outcome, UNAVAILABLE)
        self.assertEqual(policy.decide("MODEL", "application/python-pickle").outcome, REJECTED)
        self.assertEqual(policy.decide("UNKNOWN", "application/json").outcome, REJECTED)
        with self.assertRaises(FormatRejected):
            policy.require_publishable("MODEL", "application/python-pickle")

    def test_unadmitted_parquet_is_explicitly_unavailable(self) -> None:
        adapter = parquet_adapter_without_admission()
        self.assertIsInstance(adapter, UnavailableParquetAdapter)
        self.assertEqual(adapter.capability_state, "UNAVAILABLE")
        with self.assertRaises(CapabilityUnavailable):
            adapter.inspect_schema(artifact_id_for_bytes(b"not parquet"))
        with self.assertRaises(CapabilityUnavailable):
            adapter.write_partition(None)  # type: ignore[arg-type]

    def test_unadmitted_duckdb_is_read_only_and_unavailable(self) -> None:
        adapter = duckdb_adapter_without_admission()
        self.assertIsInstance(adapter, UnavailableDuckDbAdapter)
        self.assertEqual(adapter.capability_state, "UNAVAILABLE")
        self.assertTrue(adapter.read_only)
        request = DatasetQuery(
            manifest_artifact_id=artifact_id_for_bytes(b"manifest"),
            columns=("instrument_id", "close"),
            filters=(DatasetFilter("session_date", "GE", ("2026-01-01",)),),
            limit=100,
        )
        with self.assertRaises(CapabilityUnavailable):
            adapter.query_dataset(request)

    def test_duckdb_api_exposes_no_raw_sql_or_write_surface(self) -> None:
        adapter = UnavailableDuckDbAdapter()
        for forbidden in ("execute", "execute_sql", "sql", "write", "insert", "create_table"):
            self.assertFalse(hasattr(adapter, forbidden), forbidden)
        field_names = {field.name for field in dataclasses.fields(DatasetQuery)}
        self.assertNotIn("sql", field_names)
        self.assertNotIn("path", field_names)
        with self.assertRaises(TypeError):
            DatasetQuery(  # type: ignore[call-arg]
                manifest_artifact_id=artifact_id_for_bytes(b"manifest"),
                columns=("close",),
                sql="DROP TABLE catalog",
            )

    def test_typed_query_rejects_identifier_injection_and_unbounded_limit(self) -> None:
        with self.assertRaises(ValueError):
            DatasetQuery(
                manifest_artifact_id=artifact_id_for_bytes(b"manifest"),
                columns=("close; DROP TABLE x",),
            )
        with self.assertRaises(ValueError):
            DatasetQuery(
                manifest_artifact_id=artifact_id_for_bytes(b"manifest"),
                columns=("close",),
                limit=1_000_000,
            )


if __name__ == "__main__":
    unittest.main()
