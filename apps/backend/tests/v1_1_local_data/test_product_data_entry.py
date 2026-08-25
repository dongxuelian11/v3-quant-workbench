from __future__ import annotations

import time
import tempfile
import unittest
from pathlib import Path

from v3_backend.contracts.common.dto import ContractValidationError
from v3_backend.contracts.registry import OPERATIONS
from v3_backend.domain.tasks.entities import TASK_TERMINAL_STATES
from v3_backend.runtime.product_data import ProductDataService, _schema_fingerprint
from v3_backend.runtime.product_entry import create_project
from v3_backend.runtime.product_facades import build_product_facades
from v3_backend.runtime.product_runtime import ProductRuntime, mint_uuid7
from v3_backend.runtime.product_workers import ProductResearchWorkerConfig
from v3_backend.runtime.request_router import RequestRouter

from .test_local_data_import import CSV_SHARES


_OPERATION = "ProductEntryService.v1.importLocalDataset"


def _facade_handlers(product: ProductRuntime):
    return {
        operation_id: handler
        for facade in build_product_facades(product)
        for operation_id, handler in facade.handlers().items()
    }


def _publish_local_source(product: ProductRuntime, project_id: str):
    staging = product.artifact_store.stage_bytes(CSV_SHARES)
    return product.execution._publish_staged_artifact(
        staging=staging,
        provenance_entity_id="prv_product_data_local_transfer_" + staging.sha256,
        role="LOCAL_DATA_RAW_FILE",
        media_type="text/csv",
        schema_fingerprint=_schema_fingerprint("local-user-source-v1"),
        references=((project_id, "LOCAL_DATA_RAW_FILE"),),
    ).descriptor


def _request(project: dict[str, str], descriptor) -> tuple[str, dict[str, object]]:
    request_id = mint_uuid7()
    body = {
        "request_id": request_id,
        "project_id": project["project_id"],
        "project_context_revision_id": project["project_context_revision_id"],
        "expected_api_version": "1.1",
        "idempotency_key": "import-local-dataset-1",
        "source": {
            "artifact_id": descriptor.artifact_id,
            "sha256": descriptor.sha256,
            "byte_size": descriptor.byte_size,
            "media_type": descriptor.media_type,
            "display_name": "golden.csv",
            "volume_unit": "SHARES",
            "amount_unit": "CNY",
            "timezone": "Asia/Shanghai",
            "adjustment": "UNADJUSTED",
        },
    }
    return request_id, body


class ProductDataEntryContractTests(unittest.TestCase):
    def test_import_local_dataset_is_additive_closed_v1_1_contract(self) -> None:
        operation = OPERATIONS.get(_OPERATION)
        self.assertIsNotNone(operation)
        assert operation is not None
        self.assertEqual(operation.version, "1.1.0")
        self.assertEqual(
            OPERATIONS["ProductEntryService.v1.submitResearch"].version,
            "1.0.0",
        )

        source_properties = operation.request_type.SCHEMA["properties"]["source"][
            "properties"
        ]
        self.assertEqual(
            set(source_properties),
            {
                "artifact_id",
                "sha256",
                "byte_size",
                "media_type",
                "display_name",
                "volume_unit",
                "amount_unit",
                "timezone",
                "adjustment",
            },
        )
        self.assertTrue(
            {"path", "raw_path", "capability_token", "payload_base64", "rows", "bars"}
            .isdisjoint(source_properties)
        )

        source = {
            "artifact_id": "art_sha256_" + "a" * 64,
            "sha256": "a" * 64,
            "byte_size": 128,
            "media_type": "text/csv",
            "display_name": "golden.csv",
            "volume_unit": "SHARES",
            "amount_unit": "CNY",
            "timezone": "Asia/Shanghai",
            "adjustment": "UNADJUSTED",
        }
        request = {
            "request_id": "018f47f2-9b02-7cc0-8ee6-1b82e3d62c01",
            "project_id": "prj_01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "project_context_revision_id": "pcr_01ARZ3NDEKTSV4RRFFQ69G5FAW",
            "expected_api_version": "1.1",
            "idempotency_key": "local-import-contract",
            "source": source,
        }
        operation.validate_request(request)
        for forbidden in ("raw_path", "payload_base64", "bars"):
            with self.subTest(forbidden=forbidden), self.assertRaises(
                ContractValidationError
            ):
                operation.validate_request(
                    {**request, "source": {**source, forbidden: "not-authority"}}
                )
        with self.assertRaises(ContractValidationError):
            operation.validate_request({**request, "expected_api_version": "1.0"})

        operation.validate_response(
            {
                "request_id": request["request_id"],
                "truth_state": "NOT_FORMAL",
                "read_model": {
                    "read_model_version": "v3.product-entry-local-data/1.1",
                    "task_id": "tsk_01ARZ3NDEKTSV4RRFFQ69G5FAX",
                    "run_id": "run_01ARZ3NDEKTSV4RRFFQ69G5FAY",
                    "accepted_state": "QUEUED",
                    "maturity": "PRODUCT_CONNECTED",
                    "truth": "NOT_FORMAL",
                    "admission": "PRE_ALPHA",
                    "checkpoint_resume": "UNAVAILABLE",
                    "retry": "NEW_ATTEMPT_SAME_RUN_FROM_START",
                    "source_artifact_id": source["artifact_id"],
                },
            }
        )

    def test_router_durably_accepts_before_isolated_import_work(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-data-entry-") as directory:
            product = ProductRuntime(
                Path(directory),
                research_worker_config=ProductResearchWorkerConfig(
                    start_delay_seconds=0.75,
                ),
            )
            project = create_project(
                product,
                display_name="Queued local import",
                notes=None,
                idempotency_key="create-queued-local-import",
            )
            descriptor = _publish_local_source(product, project["project_id"])
            request_id, body = _request(project, descriptor)
            router = RequestRouter(_facade_handlers(product))
            started = time.monotonic()
            response = router.route(
                {
                    "kind": "request",
                    "request_id": request_id,
                    "operation_id": _OPERATION,
                    "contract_version": "1.1",
                    "project_id": project["project_id"],
                    "project_context_revision_id": project[
                        "project_context_revision_id"
                    ],
                    "body": body,
                }
            )
            elapsed = time.monotonic() - started
            try:
                self.assertEqual(response["status"], "OK", response)
                read_model = response["body"]["read_model"]
                self.assertLess(elapsed, 2.0)
                self.assertEqual(read_model["accepted_state"], "QUEUED")
                self.assertEqual(read_model["maturity"], "PRODUCT_CONNECTED")
                self.assertEqual(read_model["truth"], "NOT_FORMAL")
                self.assertEqual(read_model["admission"], "PRE_ALPHA")
                self.assertEqual(read_model["source_artifact_id"], descriptor.artifact_id)

                task = product.task_persistence.read_task(read_model["task_id"])
                self.assertEqual(task.operation_id, _OPERATION)
                connection = product._connection(read_only=True)
                try:
                    self.assertEqual(
                        connection.execute("SELECT COUNT(*) FROM data_snapshot").fetchone()[0],
                        0,
                        "the durable Task must exist before import work publishes a Snapshot",
                    )
                finally:
                    connection.close()

                deadline = time.monotonic() + 15.0
                while time.monotonic() < deadline:
                    task = product.task_persistence.read_task(read_model["task_id"])
                    if task.state in TASK_TERMINAL_STATES:
                        break
                    time.sleep(0.05)
                self.assertEqual(task.state.value, "SUCCEEDED")
                current = product.current_revision(project["project_id"])
                task_request_id = mint_uuid7()
                task_response = router.route(
                    {
                        "kind": "request",
                        "request_id": task_request_id,
                        "operation_id": "TaskService.v1.getTask",
                        "contract_version": "1.0",
                        "project_id": project["project_id"],
                        "project_context_revision_id": current[
                            "project_context_revision_id"
                        ],
                        "body": {
                            "request_id": task_request_id,
                            "project_id": project["project_id"],
                            "project_context_revision_id": current[
                                "project_context_revision_id"
                            ],
                            "expected_api_version": "1.0",
                            "task_id": read_model["task_id"],
                        },
                    }
                )
                self.assertEqual(task_response["status"], "OK", task_response)
                terminal_outputs = task_response["body"]["read_model"]["outputs"]
                self.assertEqual(
                    terminal_outputs["project_context_revision_id"],
                    current["project_context_revision_id"],
                )
                self.assertEqual(
                    terminal_outputs["snapshot_id"], current["snapshot_id"]
                )
                self.assertEqual(
                    terminal_outputs["universe_version_id"],
                    current["universe_version_id"],
                )
                self.assertEqual(
                    terminal_outputs["raw_artifact_id"], descriptor.artifact_id
                )
                restored = ProductDataService(product).get_local_dataset(
                    project_id=project["project_id"],
                    project_context_revision_id=str(
                        current["project_context_revision_id"]
                    ),
                    snapshot_id=str(current["snapshot_id"]),
                )
                self.assertEqual(restored["raw_content_hash"], descriptor.sha256)
                self.assertEqual(
                    restored["artifact_ids"]["LOCAL_DATA_RAW_FILE"],
                    descriptor.artifact_id,
                )

                home_request_id = mint_uuid7()
                home = router.route(
                    {
                        "kind": "request",
                        "request_id": home_request_id,
                        "operation_id": "ProductEntryService.v1.getProjectHome",
                        "contract_version": "1.1",
                        "project_id": project["project_id"],
                        "project_context_revision_id": current[
                            "project_context_revision_id"
                        ],
                        "body": {
                            "request_id": home_request_id,
                            "project_id": project["project_id"],
                            "project_context_revision_id": current[
                                "project_context_revision_id"
                            ],
                            "expected_api_version": "1.1",
                        },
                    }
                )
                self.assertEqual(home["status"], "OK", home)
                home_model = home["body"]["read_model"]
                self.assertEqual(home_model["read_model_version"], "v3.project-home/1.1")
                self.assertEqual(home_model["project_id"], project["project_id"])
                self.assertEqual(
                    home_model["project_context_revision_id"],
                    current["project_context_revision_id"],
                )
                self.assertEqual(home_model["local_import_state"], "AVAILABLE")
                self.assertEqual(home_model["data_state"], "AVAILABLE")
                self.assertEqual(home_model["data"]["snapshot_id"], current["snapshot_id"])
                self.assertEqual(home_model["data"]["raw_content_hash"], descriptor.sha256)
                self.assertEqual(home_model["data"]["date_coverage_start"], "2026-01-05")
                self.assertEqual(home_model["data"]["date_coverage_end"], "2026-01-05")
                self.assertEqual(home_model["data"]["quality_status"], "PASS")
                self.assertEqual(home_model["data"]["universe_role"], "USER_DEFINED_STATIC")

                replay_request_id = mint_uuid7()
                replay = router.route(
                    {
                        "kind": "request",
                        "request_id": replay_request_id,
                        "operation_id": _OPERATION,
                        "contract_version": "1.1",
                        "project_id": project["project_id"],
                        "project_context_revision_id": project[
                            "project_context_revision_id"
                        ],
                        "body": {**body, "request_id": replay_request_id},
                    }
                )
                self.assertEqual(replay["status"], "OK", replay)
                self.assertEqual(
                    replay["body"]["read_model"]["task_id"],
                    read_model["task_id"],
                )
            finally:
                product.research_workers.shutdown_all()

    def test_cross_project_source_ref_fails_before_task_acceptance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-data-scope-") as directory:
            product = ProductRuntime(
                Path(directory),
                research_worker_config=ProductResearchWorkerConfig(),
            )
            first = create_project(
                product,
                display_name="Source owner",
                notes=None,
                idempotency_key="create-source-owner",
            )
            second = create_project(
                product,
                display_name="Wrong target",
                notes=None,
                idempotency_key="create-wrong-target",
            )
            descriptor = _publish_local_source(product, first["project_id"])
            request_id, body = _request(second, descriptor)
            try:
                response = RequestRouter(_facade_handlers(product)).route(
                    {
                        "kind": "request",
                        "request_id": request_id,
                        "operation_id": _OPERATION,
                        "contract_version": "1.1",
                        "project_id": second["project_id"],
                        "project_context_revision_id": second[
                            "project_context_revision_id"
                        ],
                        "body": body,
                    }
                )
                self.assertEqual(response["status"], "ERROR", response)
                self.assertEqual(
                    response["error"]["code"],
                    "TRUTH_PRECONDITION_FAILED",
                )
                connection = product._connection(read_only=True)
                try:
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM task").fetchone()[0], 0)
                    self.assertEqual(
                        connection.execute("SELECT COUNT(*) FROM data_snapshot").fetchone()[0],
                        0,
                    )
                finally:
                    connection.close()
            finally:
                product.research_workers.shutdown_all()

    def test_tampered_source_bytes_fail_in_worker_without_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-product-data-tamper-") as directory:
            product = ProductRuntime(
                Path(directory),
                research_worker_config=ProductResearchWorkerConfig(),
            )
            project = create_project(
                product,
                display_name="Tampered source",
                notes=None,
                idempotency_key="create-tampered-source",
            )
            descriptor = _publish_local_source(product, project["project_id"])
            artifact_path = product.artifact_root.joinpath(
                *descriptor.storage_key.split("/")
            )
            artifact_path.write_bytes(b"X" + CSV_SHARES[1:])
            request_id, body = _request(project, descriptor)
            try:
                response = RequestRouter(_facade_handlers(product)).route(
                    {
                        "kind": "request",
                        "request_id": request_id,
                        "operation_id": _OPERATION,
                        "contract_version": "1.1",
                        "project_id": project["project_id"],
                        "project_context_revision_id": project[
                            "project_context_revision_id"
                        ],
                        "body": body,
                    }
                )
                self.assertEqual(response["status"], "OK", response)
                task_id = response["body"]["read_model"]["task_id"]
                deadline = time.monotonic() + 15.0
                while time.monotonic() < deadline:
                    task = product.task_persistence.read_task(task_id)
                    if task.state in TASK_TERMINAL_STATES:
                        break
                    time.sleep(0.05)
                self.assertEqual(task.state.value, "FAILED")
                connection = product._connection(read_only=True)
                try:
                    self.assertEqual(
                        connection.execute("SELECT COUNT(*) FROM data_snapshot").fetchone()[0],
                        0,
                    )
                finally:
                    connection.close()
            finally:
                product.research_workers.shutdown_all()


if __name__ == "__main__":
    unittest.main()
