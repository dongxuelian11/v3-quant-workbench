from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from v3_backend.adapters.local_data import (
    LocalDataImportError,
    LocalDataImportIntentV1,
    LocalDataImportLimits,
)
from v3_backend.errors.exceptions import TruthPreconditionFailedError
from v3_backend.runtime.product_data import ProductDataService
from v3_backend.runtime.product_entry import create_project
from v3_backend.runtime.product_runtime import ProductRuntime, connect_catalog

from .test_local_data_import import CSV_SHARES


class ProductDataPersistenceTests(unittest.TestCase):
    @staticmethod
    def _csv_intent() -> LocalDataImportIntentV1:
        return LocalDataImportIntentV1(
            media_type="text/csv",
            volume_unit="SHARES",
            amount_unit="CNY",
            timezone="Asia/Shanghai",
            adjustment="UNADJUSTED",
        )

    def test_local_import_publishes_exact_project_scoped_owner_chain_and_reopens(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-data-") as directory:
            root = Path(directory)
            product = ProductRuntime(root)
            project = create_project(
                product,
                display_name="Local data persistence",
                notes=None,
                idempotency_key="create-local-data-persistence",
            )
            service = ProductDataService(product)
            imported = service.import_local_dataset(
                project_id=project["project_id"],
                project_context_revision_id=project["project_context_revision_id"],
                display_name="golden.csv",
                source=io.BytesIO(CSV_SHARES),
                intent=self._csv_intent(),
            )

            self.assertEqual(imported["truth"], "NOT_FORMAL")
            self.assertEqual(imported["admission"], "PRE_ALPHA")
            self.assertEqual(imported["source_type"], "LOCAL_USER_SUPPLIED")
            self.assertEqual(imported["pit_state"], "PIT_UNPROVABLE")
            self.assertEqual(imported["row_count"], 2)
            self.assertEqual(imported["instrument_count"], 2)
            self.assertEqual(imported["date_coverage_start"], "2026-01-05")
            self.assertEqual(imported["date_coverage_end"], "2026-01-05")
            self.assertTrue(imported["raw_capture_id"].startswith("raw_sha256_"))
            self.assertTrue(imported["snapshot_id"].startswith("snp_sha256_"))
            self.assertTrue(imported["universe_version_id"].startswith("unv_sha256_"))

            connection = connect_catalog(product.database_path, read_only=True)
            try:
                artifact_rows = connection.execute(
                    """
                    SELECT a.semantic_role,a.artifact_id,a.sha256,a.state,a.media_type
                    FROM artifact AS a
                    JOIN artifact_reference AS r ON r.artifact_id=a.artifact_id
                    WHERE r.owner_id=? AND r.state='ACTIVE'
                    ORDER BY a.semantic_role
                    """,
                    (project["project_id"],),
                ).fetchall()
                roles = {str(row[0]) for row in artifact_rows}
                self.assertTrue(
                    {
                        "LOCAL_DATA_RAW_FILE",
                        "LOCAL_DATA_SCHEMA_MAPPING",
                        "LOCAL_DATA_NORMALIZATION_RECEIPT",
                        "DATA_TRUTH_SNAPSHOT_PARTITION",
                        "DATA_TRUTH_SNAPSHOT_MANIFEST",
                        "UNIVERSE_MEMBERSHIP",
                    }
                    <= roles
                )
                by_role = {str(row[0]): row for row in artifact_rows}
                raw_artifact = by_role["LOCAL_DATA_RAW_FILE"]
                self.assertEqual(str(raw_artifact[4]), "text/csv")
                self.assertEqual(
                    product.read_verified_bytes(str(raw_artifact[1])),
                    CSV_SHARES,
                )
                partition_artifact = by_role["DATA_TRUTH_SNAPSHOT_PARTITION"]
                self.assertEqual(str(partition_artifact[4]), "application/json")
                manifest_artifact = by_role["DATA_TRUTH_SNAPSHOT_MANIFEST"]
                self.assertEqual(str(manifest_artifact[2]), imported["normalized_payload_hash"])
                snapshot = connection.execute(
                    "SELECT state,content_hash,truth_profile_id FROM data_snapshot WHERE snapshot_id=?",
                    (imported["snapshot_id"],),
                ).fetchone()
                self.assertEqual(tuple(snapshot), ("PUBLISHED", imported["normalized_payload_hash"], "PRE_ALPHA_LOCAL_USER_SUPPLIED"))
                validations = connection.execute(
                    """
                    SELECT check_code,state,severity,report_artifact_id
                    FROM snapshot_validation WHERE snapshot_id=? ORDER BY check_code
                    """,
                    (imported["snapshot_id"],),
                ).fetchall()
                self.assertEqual(len(validations), 7)
                self.assertTrue(all(tuple(row[1:3]) == ("PASS", "BLOCKING") for row in validations))
                self.assertTrue(all(str(row[3]) == str(manifest_artifact[1]) for row in validations))
                raw = connection.execute(
                    "SELECT state,content_hash FROM raw_capture WHERE raw_capture_id=?",
                    (imported["raw_capture_id"],),
                ).fetchone()
                self.assertEqual(tuple(raw), ("ACCEPTED", imported["raw_content_hash"]))
                local_capability = connection.execute(
                    "SELECT admitted_truth_state FROM connector_capability WHERE connector_version_id='cov_local_data_import_v1'"
                ).fetchone()
                self.assertIsNone(local_capability)
                universe = connection.execute(
                    """
                    SELECT d.project_id,d.definition_json,u.snapshot_id,u.state
                    FROM universe_version AS u
                    JOIN universe_definition AS d
                      ON d.universe_definition_id=u.universe_definition_id
                    WHERE u.universe_version_id=?
                    """,
                    (imported["universe_version_id"],),
                ).fetchone()
                self.assertEqual(str(universe[0]), project["project_id"])
                self.assertIn('"role":"USER_DEFINED_STATIC"', str(universe[1]))
                self.assertEqual(tuple(universe[2:]), (imported["snapshot_id"], "PUBLISHED"))
                context = connection.execute(
                    """
                    SELECT project_id,snapshot_id,universe_version_id
                    FROM project_context_revision
                    WHERE project_context_revision_id=?
                    """,
                    (imported["project_context_revision_id"],),
                ).fetchone()
                self.assertEqual(
                    tuple(context),
                    (
                        project["project_id"],
                        imported["snapshot_id"],
                        imported["universe_version_id"],
                    ),
                )
            finally:
                connection.close()

            reopened = ProductDataService(ProductRuntime(root)).get_local_dataset(
                project_id=project["project_id"],
                project_context_revision_id=imported["project_context_revision_id"],
                snapshot_id=imported["snapshot_id"],
            )
            self.assertEqual(reopened, imported)

            connection = connect_catalog(product.database_path)
            try:
                connection.execute(
                    """
                    UPDATE artifact_reference
                    SET state='RELEASED',released_at='2026-08-24T00:00:00+00:00'
                    WHERE owner_type='Project' AND owner_id=? AND role=? AND artifact_id=?
                    """,
                    (
                        project["project_id"],
                        "LOCAL_DATA_RAW_FILE",
                        imported["artifact_ids"]["LOCAL_DATA_RAW_FILE"],
                    ),
                )
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(
                TruthPreconditionFailedError,
                "not exactly project-reachable",
            ):
                ProductDataService(ProductRuntime(root)).get_local_dataset(
                    project_id=project["project_id"],
                    project_context_revision_id=imported[
                        "project_context_revision_id"
                    ],
                    snapshot_id=imported["snapshot_id"],
                )

    def test_csv_and_parquet_share_snapshot_semantics_but_retain_distinct_raw_bytes(self) -> None:
        table = pa.table(
            {
                "symbol": ["600519", "000001"],
                "date": ["2026-01-05", "2026-01-05"],
                "open": ["1400", "10"],
                "high": ["1420", "10.5"],
                "low": ["1395", "9.8"],
                "close": ["1410", "10.2"],
                "volume": ["10000", "20000"],
                "amount": ["14100000", "204000"],
            }
        )
        parquet = io.BytesIO()
        pq.write_table(table, parquet, row_group_size=1)
        parquet_bytes = parquet.getvalue()

        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-data-equivalence-") as directory:
            product = ProductRuntime(Path(directory))
            csv_project = create_project(
                product,
                display_name="CSV project",
                notes=None,
                idempotency_key="create-csv-project",
            )
            service = ProductDataService(product)
            csv_import = service.import_local_dataset(
                project_id=csv_project["project_id"],
                project_context_revision_id=csv_project["project_context_revision_id"],
                display_name="golden.csv",
                source=io.BytesIO(CSV_SHARES),
                intent=self._csv_intent(),
            )
            parquet_import = service.import_local_dataset(
                project_id=csv_project["project_id"],
                project_context_revision_id=csv_import["project_context_revision_id"],
                display_name="golden.parquet",
                source=io.BytesIO(parquet_bytes),
                intent=LocalDataImportIntentV1(
                    media_type="application/vnd.apache.parquet",
                    volume_unit="SHARES",
                    amount_unit="CNY",
                    timezone="Asia/Shanghai",
                    adjustment="UNADJUSTED",
                ),
            )

            self.assertEqual(csv_import["snapshot_id"], parquet_import["snapshot_id"])
            self.assertEqual(
                csv_import["normalized_payload_hash"],
                parquet_import["normalized_payload_hash"],
            )
            self.assertNotEqual(csv_import["raw_content_hash"], parquet_import["raw_content_hash"])
            connection = connect_catalog(product.database_path, read_only=True)
            try:
                source_count = connection.execute(
                    "SELECT COUNT(*) FROM snapshot_raw_capture WHERE snapshot_id=?",
                    (csv_import["snapshot_id"],),
                ).fetchone()[0]
                self.assertEqual(
                    int(source_count),
                    1,
                    "published Snapshot source membership must remain immutable",
                )
                raw = connection.execute(
                    "SELECT artifact_id,media_type FROM artifact WHERE artifact_id=?",
                    (parquet_import["artifact_ids"]["LOCAL_DATA_RAW_FILE"],),
                ).fetchone()
                self.assertEqual(str(raw[1]), "application/vnd.apache.parquet")
                self.assertEqual(product.read_verified_bytes(str(raw[0])), parquet_bytes)
            finally:
                connection.close()
            self.assertEqual(
                ProductDataService(ProductRuntime(Path(directory))).get_local_dataset(
                    project_id=csv_project["project_id"],
                    project_context_revision_id=parquet_import[
                        "project_context_revision_id"
                    ],
                    snapshot_id=parquet_import["snapshot_id"],
                ),
                parquet_import,
            )

    def test_large_normalized_data_uses_bounded_canonical_partitions_and_manifest(self) -> None:
        rows = [
            "symbol,date,open,high,low,close,volume,amount",
            *(
                f"{600000 + index:06d},2026-01-05,10,11,9,10.5,100,1050"
                for index in range(40)
            ),
        ]
        payload = ("\n".join(rows) + "\n").encode("utf-8")
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-data-chunked-") as directory:
            product = ProductRuntime(Path(directory))
            project = create_project(
                product,
                display_name="Chunked local data",
                notes=None,
                idempotency_key="create-chunked-local-data",
            )
            imported = ProductDataService(product).import_local_dataset(
                project_id=project["project_id"],
                project_context_revision_id=project["project_context_revision_id"],
                display_name="chunked.csv",
                source=io.BytesIO(payload),
                intent=self._csv_intent(),
                limits=LocalDataImportLimits(max_partition_bytes=1024),
            )
            connection = connect_catalog(product.database_path, read_only=True)
            try:
                partitions = connection.execute(
                    """
                    SELECT partition_key,parquet_artifact_id,row_count
                    FROM snapshot_partition WHERE snapshot_id=? ORDER BY partition_key
                    """,
                    (imported["snapshot_id"],),
                ).fetchall()
                manifest = connection.execute(
                    """
                    SELECT s.manifest_artifact_id,a.sha256
                    FROM data_snapshot AS s JOIN artifact AS a
                      ON a.artifact_id=s.manifest_artifact_id
                    WHERE s.snapshot_id=?
                    """,
                    (imported["snapshot_id"],),
                ).fetchone()
                self.assertGreater(len(partitions), 1)
                self.assertEqual(sum(int(row[2]) for row in partitions), 40)
                self.assertEqual([str(row[0]) for row in partitions], sorted(str(row[0]) for row in partitions))
                self.assertEqual(str(manifest[1]), imported["normalized_payload_hash"])
                for partition in partitions:
                    descriptor = product.require_published_artifact(str(partition[1]))
                    self.assertLessEqual(int(descriptor["byte_size"]), 1024)
                    self.assertEqual(descriptor["semantic_role"], "DATA_TRUTH_SNAPSHOT_PARTITION")
            finally:
                connection.close()

    def test_invalid_or_cross_project_import_fails_before_canonical_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-data-reject-") as directory:
            product = ProductRuntime(Path(directory))
            first = create_project(
                product,
                display_name="First",
                notes=None,
                idempotency_key="create-first-reject-project",
            )
            second = create_project(
                product,
                display_name="Second",
                notes=None,
                idempotency_key="create-second-reject-project",
            )
            service = ProductDataService(product)
            with self.assertRaises(TruthPreconditionFailedError):
                service.import_local_dataset(
                    project_id=first["project_id"],
                    project_context_revision_id=second["project_context_revision_id"],
                    display_name="wrong-scope.csv",
                    source=io.BytesIO(CSV_SHARES),
                    intent=self._csv_intent(),
                )
            invalid = CSV_SHARES.replace(b"1400,1420,1395,1410", b"1400,1390,1395,1410")
            with self.assertRaisesRegex(LocalDataImportError, "OHLC"):
                service.import_local_dataset(
                    project_id=first["project_id"],
                    project_context_revision_id=first["project_context_revision_id"],
                    display_name="invalid.csv",
                    source=io.BytesIO(invalid),
                    intent=self._csv_intent(),
                )

            connection = connect_catalog(product.database_path, read_only=True)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM artifact").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM raw_capture").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM data_snapshot").fetchone()[0], 0)
            finally:
                connection.close()
            self.assertEqual(tuple(product.artifact_store.recover_staging()), ())


if __name__ == "__main__":
    unittest.main()
