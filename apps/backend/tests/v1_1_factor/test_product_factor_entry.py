from __future__ import annotations

import io
import tempfile
import time
import unittest
from pathlib import Path

from v3_backend.adapters.local_data import LocalDataImportIntentV1, LocalDataImportLimits
from v3_backend.contracts.registry import OPERATIONS
from v3_backend.domain.tasks.entities import TASK_TERMINAL_STATES
from v3_backend.runtime.product_data import ProductDataService
from v3_backend.runtime.product_entry import create_project
from v3_backend.runtime.product_facades import build_product_facades
from v3_backend.runtime.product_factor import ProductFactorStudyService
from v3_backend.runtime.product_runtime import ProductRuntime, mint_uuid7
from v3_backend.runtime.product_workers import ProductResearchWorkerConfig
from v3_backend.runtime.request_router import RequestRouter

from .test_factor_panel import GOLDEN_FORMULA, _panel_csv


_OPERATION = "ProductEntryService.v1.submitFactorStudy"


def _handlers(product: ProductRuntime):
    return {
        operation_id: handler
        for facade in build_product_facades(product)
        for operation_id, handler in facade.handlers().items()
    }


class ProductFactorEntryTests(unittest.TestCase):
    def _runtime_with_data(self, root: Path):
        product = ProductRuntime(
            root,
            research_worker_config=ProductResearchWorkerConfig(start_delay_seconds=0.75),
        )
        project = create_project(
            product,
            display_name="Queued factor study",
            notes=None,
            idempotency_key="create-queued-factor-study",
        )
        imported = ProductDataService(product).import_local_dataset(
            project_id=project["project_id"],
            project_context_revision_id=project["project_context_revision_id"],
            display_name="panel.csv",
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
        return product, project, imported

    def test_contract_is_additive_closed_and_preserves_v1_prefix(self) -> None:
        operation = OPERATIONS.get(_OPERATION)
        self.assertIsNotNone(operation)
        assert operation is not None
        self.assertEqual(operation.version, "1.1.0")
        product_operations = tuple(
            operation_id
            for operation_id in OPERATIONS
            if operation_id.startswith("ProductEntryService.")
        )
        self.assertEqual(
            product_operations[:3],
            (
                "ProductEntryService.v1.listBacktestRunSpecs",
                "ProductEntryService.v1.importResearchPackage",
                "ProductEntryService.v1.submitResearch",
            ),
        )
        properties = operation.request_type.SCHEMA["properties"]
        self.assertEqual(
            set(properties),
            {
                "request_id",
                "project_id",
                "project_context_revision_id",
                "expected_api_version",
                "idempotency_key",
                "formula_source",
                "analysis_output_name",
            },
        )
        self.assertTrue(
            {"bars", "factor_values", "snapshot_id", "universe_version_id", "artifact_id"}
            .isdisjoint(properties)
        )

    def test_router_accepts_durable_task_before_factor_work_and_recovers_result(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-factor-entry-") as directory:
            product, project, imported = self._runtime_with_data(Path(directory))
            request_id = mint_uuid7()
            body = {
                "request_id": request_id,
                "project_id": project["project_id"],
                "project_context_revision_id": imported["project_context_revision_id"],
                "expected_api_version": "1.1",
                "idempotency_key": "golden-factor-study-1",
                "formula_source": GOLDEN_FORMULA,
                "analysis_output_name": "MJ",
            }
            router = RequestRouter(_handlers(product))
            started = time.monotonic()
            response = router.route(
                {
                    "kind": "request",
                    "request_id": request_id,
                    "operation_id": _OPERATION,
                    "contract_version": "1.1",
                    "project_id": project["project_id"],
                    "project_context_revision_id": imported[
                        "project_context_revision_id"
                    ],
                    "body": body,
                }
            )
            elapsed = time.monotonic() - started
            try:
                self.assertEqual(response["status"], "OK", response)
                accepted = response["body"]["read_model"]
                self.assertLess(elapsed, 2.0)
                self.assertEqual(accepted["accepted_state"], "QUEUED")
                self.assertEqual(accepted["truth"], "NOT_FORMAL")
                self.assertEqual(accepted["admission"], "PRE_ALPHA")
                task = product.task_persistence.read_task(accepted["task_id"])
                self.assertEqual(task.operation_id, _OPERATION)
                connection = product._connection(read_only=True)
                try:
                    self.assertEqual(
                        connection.execute("SELECT COUNT(*) FROM factor_version").fetchone()[0],
                        0,
                        "durable Task must exist before Factor publication starts",
                    )
                finally:
                    connection.close()

                deadline = time.monotonic() + 15.0
                while time.monotonic() < deadline:
                    task = product.task_persistence.read_task(accepted["task_id"])
                    if task.state in TASK_TERMINAL_STATES:
                        break
                    time.sleep(0.05)
                self.assertEqual(task.state.value, "SUCCEEDED")
                restored = ProductFactorStudyService(product).get_latest_factor_study(
                    project_id=project["project_id"],
                    project_context_revision_id=imported["project_context_revision_id"],
                    snapshot_id=imported["snapshot_id"],
                )
                self.assertEqual(restored["formula_document_version_id"], accepted["formula_document_version_id"])
                self.assertTrue(
                    any(row["GOLDEN_CROSS"] is True for row in restored["visual_preview"])
                )
                home_request_id = mint_uuid7()
                home = router.route(
                    {
                        "kind": "request",
                        "request_id": home_request_id,
                        "operation_id": "ProductEntryService.v1.getProjectHome",
                        "contract_version": "1.1",
                        "project_id": project["project_id"],
                        "project_context_revision_id": imported[
                            "project_context_revision_id"
                        ],
                        "body": {
                            "request_id": home_request_id,
                            "project_id": project["project_id"],
                            "project_context_revision_id": imported[
                                "project_context_revision_id"
                            ],
                            "expected_api_version": "1.1",
                        },
                    }
                )
                self.assertEqual(home["status"], "OK", home)
                home_model = home["body"]["read_model"]
                self.assertEqual(home_model["factor_state"], "AVAILABLE")
                self.assertEqual(home_model["factor_unavailable_reason"], "NONE")
                self.assertEqual(
                    home_model["factor"]["formula_document_version_id"],
                    accepted["formula_document_version_id"],
                )
                self.assertTrue(
                    any(
                        next(
                            item["value"]
                            for item in row["series"]
                            if item["name"] == "GOLDEN_CROSS"
                        )
                        is True
                        for row in home_model["factor"]["visual_preview"]
                    )
                )
                connection = product._connection()
                try:
                    connection.execute(
                        """
                        UPDATE artifact_reference SET state='RELEASED'
                        WHERE owner_type='Project' AND owner_id=? AND role='FACTOR_ANALYSIS'
                          AND artifact_id=? AND state='ACTIVE'
                        """,
                        (project["project_id"], restored["analysis_artifact_id"]),
                    )
                    connection.commit()
                finally:
                    connection.close()
                unavailable_request_id = mint_uuid7()
                unavailable = router.route(
                    {
                        "kind": "request",
                        "request_id": unavailable_request_id,
                        "operation_id": "ProductEntryService.v1.getProjectHome",
                        "contract_version": "1.1",
                        "project_id": project["project_id"],
                        "project_context_revision_id": imported[
                            "project_context_revision_id"
                        ],
                        "body": {
                            "request_id": unavailable_request_id,
                            "project_id": project["project_id"],
                            "project_context_revision_id": imported[
                                "project_context_revision_id"
                            ],
                            "expected_api_version": "1.1",
                        },
                    }
                )
                self.assertEqual(unavailable["status"], "OK", unavailable)
                unavailable_home = unavailable["body"]["read_model"]
                self.assertEqual(unavailable_home["data_state"], "AVAILABLE")
                self.assertEqual(unavailable_home["factor_state"], "UNAVAILABLE")
                self.assertEqual(
                    unavailable_home["factor_unavailable_reason"],
                    "FACTOR_READ_MODEL_NOT_AVAILABLE",
                )
                self.assertNotIn("factor", unavailable_home)
            finally:
                product.research_workers.shutdown_all()


if __name__ == "__main__":
    unittest.main()
