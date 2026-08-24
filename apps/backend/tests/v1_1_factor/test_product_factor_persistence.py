from __future__ import annotations

import csv
import io
import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from v3_backend.adapters.local_data import LocalDataImportIntentV1, LocalDataImportLimits
from v3_backend.runtime.product_data import ProductDataService
from v3_backend.runtime.product_entry import create_project
from v3_backend.runtime.product_factor import ProductFactorStudyService
from v3_backend.runtime.product_runtime import ProductRuntime, connect_catalog
from v3_backend.errors.exceptions import NotFoundError

from .test_factor_panel import GOLDEN_FORMULA, _panel_csv


class ProductFactorPersistenceTests(unittest.TestCase):
    def test_csv_and_parquet_produce_identical_snapshot_and_factor_outputs(self) -> None:
        csv_bytes = _panel_csv()
        rows = tuple(csv.DictReader(io.StringIO(csv_bytes.decode("utf-8"))))
        parquet = io.BytesIO()
        pq.write_table(
            pa.table({name: [row[name] for row in rows] for name in rows[0]}),
            parquet,
            row_group_size=17,
        )

        with tempfile.TemporaryDirectory(prefix="v3-v1-1-factor-format-equivalence-") as directory:
            product = ProductRuntime(Path(directory))
            project = create_project(
                product,
                display_name="Factor format equivalence",
                notes=None,
                idempotency_key="create-factor-format-equivalence",
            )
            data = ProductDataService(product)
            csv_import = data.import_local_dataset(
                project_id=project["project_id"],
                project_context_revision_id=project["project_context_revision_id"],
                display_name="factor-panel.csv",
                source=io.BytesIO(csv_bytes),
                intent=LocalDataImportIntentV1(
                    media_type="text/csv",
                    volume_unit="SHARES",
                    amount_unit="CNY",
                    timezone="Asia/Shanghai",
                    adjustment="UNADJUSTED",
                ),
            )
            factor = ProductFactorStudyService(product)
            csv_study = factor.run_factor_study(
                project_id=project["project_id"],
                project_context_revision_id=csv_import["project_context_revision_id"],
                formula_source=GOLDEN_FORMULA,
                analysis_output_name="MJ",
            )

            parquet_import = data.import_local_dataset(
                project_id=project["project_id"],
                project_context_revision_id=csv_import["project_context_revision_id"],
                display_name="factor-panel.parquet",
                source=io.BytesIO(parquet.getvalue()),
                intent=LocalDataImportIntentV1(
                    media_type="application/vnd.apache.parquet",
                    volume_unit="SHARES",
                    amount_unit="CNY",
                    timezone="Asia/Shanghai",
                    adjustment="UNADJUSTED",
                ),
            )
            parquet_study = factor.run_factor_study(
                project_id=project["project_id"],
                project_context_revision_id=parquet_import["project_context_revision_id"],
                formula_source=GOLDEN_FORMULA,
                analysis_output_name="MJ",
            )

            self.assertEqual(csv_import["normalized_payload_hash"], parquet_import["normalized_payload_hash"])
            self.assertEqual(csv_import["snapshot_id"], parquet_import["snapshot_id"])
            self.assertEqual(csv_import["universe_version_id"], parquet_import["universe_version_id"])
            self.assertEqual(
                csv_study["formula_document_version_id"],
                parquet_study["formula_document_version_id"],
            )
            self.assertEqual(csv_study["outputs"], parquet_study["outputs"])
            self.assertEqual(
                csv_study["analysis"]["factor_analysis_result_id"],
                parquet_study["analysis"]["factor_analysis_result_id"],
            )
            self.assertEqual(csv_study["visual_preview"], parquet_study["visual_preview"])

    def test_real_formula_factor_materialization_and_analysis_persist_across_restart(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-factor-") as directory:
            root = Path(directory)
            product = ProductRuntime(root)
            project = create_project(
                product,
                display_name="Persistent factor study",
                notes=None,
                idempotency_key="create-persistent-factor-study",
            )
            imported = ProductDataService(product).import_local_dataset(
                project_id=project["project_id"],
                project_context_revision_id=project["project_context_revision_id"],
                display_name="factor-panel.csv",
                source=io.BytesIO(_panel_csv()),
                intent=LocalDataImportIntentV1(
                    media_type="text/csv",
                    volume_unit="SHARES",
                    amount_unit="CNY",
                    timezone="Asia/Shanghai",
                    adjustment="UNADJUSTED",
                ),
                limits=LocalDataImportLimits(max_partition_bytes=6_000),
            )
            service = ProductFactorStudyService(product)
            study = service.run_factor_study(
                project_id=project["project_id"],
                project_context_revision_id=imported["project_context_revision_id"],
                formula_source=GOLDEN_FORMULA,
                analysis_output_name="MJ",
            )

            self.assertEqual(study["truth"], "NOT_FORMAL")
            self.assertEqual(study["admission"], "PRE_ALPHA")
            self.assertEqual(study["snapshot_id"], imported["snapshot_id"])
            self.assertEqual(study["universe_version_id"], imported["universe_version_id"])
            self.assertTrue(study["formula_document_version_id"].startswith("fdoc_sha256_"))
            self.assertEqual(
                tuple(study["outputs"]),
                ("MJ", "MA5", "MA20", "MA60", "GOLDEN_CROSS", "DEATH_CROSS"),
            )
            self.assertTrue(
                all(item["factor_definition_version_id"].startswith("fdv_sha256_") for item in study["outputs"].values())
            )
            self.assertTrue(
                all(item["materialization_id"].startswith("fmt_sha256_") for item in study["outputs"].values())
            )
            self.assertEqual(
                study["analysis"]["aggregate"]["ic_mean"]["status"],
                "INSUFFICIENT_SAMPLE",
            )
            self.assertEqual(
                study["analysis"]["aggregate"]["ic_mean"]["reason"],
                "CROSS_SECTION_REQUIRES_AT_LEAST_20_INSTRUMENTS",
            )
            self.assertTrue(study["visual_preview"])
            self.assertTrue(
                any(row["GOLDEN_CROSS"] is True for row in study["visual_preview"])
            )

            connection = connect_catalog(product.database_path, read_only=True)
            try:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM factor_definition WHERE project_id=?",
                        (project["project_id"],),
                    ).fetchone()[0],
                    6,
                )
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM factor_version").fetchone()[0], 6)
                roles = {
                    str(row[0])
                    for row in connection.execute(
                        """
                        SELECT DISTINCT a.semantic_role FROM artifact AS a
                        JOIN artifact_reference AS r ON r.artifact_id=a.artifact_id
                        WHERE r.owner_type='Project' AND r.owner_id=? AND r.state='ACTIVE'
                        """,
                        (project["project_id"],),
                    ).fetchall()
                }
                self.assertTrue(
                    {
                        "FACTOR_FORMULA_DOCUMENT",
                        "FACTOR_DEFINITION",
                        "FACTOR_MATERIALIZATION",
                        "FACTOR_ANALYSIS",
                        "PRODUCT_FACTOR_STUDY_READ_MODEL",
                    }
                    <= roles
                )
            finally:
                connection.close()

            reopened_service = ProductFactorStudyService(ProductRuntime(root))
            with self.assertRaises(NotFoundError):
                reopened_service.get_latest_factor_study(
                    project_id=project["project_id"],
                    project_context_revision_id=project["project_context_revision_id"],
                    snapshot_id=imported["snapshot_id"],
                )
            reopened = reopened_service.get_latest_factor_study(
                project_id=project["project_id"],
                project_context_revision_id=imported["project_context_revision_id"],
                snapshot_id=imported["snapshot_id"],
            )
            self.assertEqual(reopened, study)


if __name__ == "__main__":
    unittest.main()
