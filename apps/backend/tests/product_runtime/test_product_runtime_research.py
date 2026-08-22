from __future__ import annotations

import tempfile
import uuid
import unittest
from datetime import datetime, timezone
from pathlib import Path

from v3_backend.adapters.market_data.akshare import AkshareAShareEodAdapter
from v3_backend.contracts.common.dto import ContractValidationError
from v3_backend.contracts.product_entry import (
    SubmitResearchRequestV1,
    SubmitResearchResponseV1,
)
from v3_backend.runtime.product_entry import create_project
from v3_backend.runtime.product_facades import build_product_facades
from v3_backend.runtime.product_research import _ensure_provider_admission
from v3_backend.runtime.product_runtime import ProductRuntime


class _Frame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def to_dict(self, *, orient: str) -> list[dict[str, object]]:
        if orient != "records":
            raise AssertionError("the provider adapter must request records orientation")
        return list(self._rows)


class _FakeAkshare:
    __version__ = "1.18.84"

    def stock_zh_a_hist(self, **request: object) -> _Frame:
        del request
        return _Frame(
            [
                {
                    "股票代码": "000001",
                    "日期": "2026-01-06",
                    "开盘": "10.00",
                    "最高": "11.00",
                    "最低": "9.50",
                    "收盘": "10.50",
                    "成交量": "1000",
                    "成交额": "10500",
                },
                {
                    "股票代码": "000001",
                    "日期": "2026-01-07",
                    "开盘": "10.50",
                    "最高": "11.50",
                    "最低": "10.00",
                    "收盘": "11.00",
                    "成交量": "1200",
                    "成交额": "13200",
                },
            ]
        )


def _provider_factory(_config):
    return AkshareAShareEodAdapter(
        connector_version_id="cov_akshare_eod_research_v1",
        loader=lambda: _FakeAkshare(),
        clock=lambda: datetime(2026, 1, 8, 8, 0, tzinfo=timezone.utc),
    )


def _facade_handler(product: ProductRuntime, operation_id: str):
    for facade in build_product_facades(product):
        handler = facade.handlers().get(operation_id)
        if handler is not None:
            return handler
    raise AssertionError(f"missing handler: {operation_id}")


def _request(project_id: str, revision_id: str, *, key: str = "research-1") -> dict[str, object]:
    return {
        "request_id": str(uuid.uuid4()),
        "project_id": project_id,
        "project_context_revision_id": revision_id,
        "expected_api_version": "1.0",
        "idempotency_key": key,
        "research_profile_id": "RESEARCH_FREE_DATA_V1",
        "strategy_profile_id": "RESEARCH_CLOSE_RANK_TOP1_V1",
        "source": {
            "provider_id": "pvd_akshare_eastmoney_a_share_eod_v1",
            "connector_version_id": "cov_akshare_eod_research_v1",
            "logical_dataset": "CN_A_SHARE_EOD",
            "frequency": "P1D",
            "symbol": "000001",
            "start_date": "20260106",
            "end_date": "20260107",
        },
    }


class ProductRuntimeResearchTests(unittest.TestCase):
    def test_closed_entry_and_clean_start_restart_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-product-research-") as directory:
            root = Path(directory)
            product = ProductRuntime(root, research_provider_factory=_provider_factory)
            project = create_project(
                product,
                display_name="Product research smoke",
                notes=None,
                idempotency_key="create-research-project",
            )
            request = _request(project["project_id"], project["project_context_revision_id"])
            dto = SubmitResearchRequestV1.from_mapping(request)
            handler = _facade_handler(product, "ProductEntryService.v1.submitResearch")
            response = handler(dto.to_wire())
            validated = SubmitResearchResponseV1.from_mapping(response)
            read_model = validated["read_model"]

            self.assertEqual(validated["truth_state"], "DEMO")
            self.assertEqual(read_model["accepted_state"], "QUEUED")
            self.assertEqual(read_model["maturity"], "PRODUCT_CONNECTED_CANDIDATE")
            self.assertEqual(read_model["truth_admission"], {"truth": "NOT_FORMAL", "admission": "PRE_ALPHA"})
            self.assertEqual(read_model["research_classification"], ["RESEARCH_ONLY", "APPROXIMATE"])

            task = product.task_persistence.read_task(read_model["task_id"])
            self.assertEqual(task.operation_id, "ProductEntryService.v1.submitResearch")
            self.assertEqual(task.active_run_id, read_model["run_id"])
            task_connection = product._connection(read_only=True)
            try:
                task_row = task_connection.execute(
                    "SELECT state FROM task WHERE task_id=?", (task.task_id,)
                ).fetchone()
            finally:
                task_connection.close()
            self.assertEqual(task_row["state"], "SUCCEEDED")
            result_connection = product._connection(read_only=True)
            try:
                result_row = result_connection.execute(
                    "SELECT result_id FROM result WHERE backtest_run_id=?", (task.active_run_id,)
                ).fetchone()
            finally:
                result_connection.close()
            self.assertIsNotNone(result_row)

            restarted = ProductRuntime(root, research_provider_factory=_provider_factory)
            replay_request = _request(
                project["project_id"], project["project_context_revision_id"], key="research-1"
            )
            replay = _facade_handler(restarted, "ProductEntryService.v1.submitResearch")
            replay_response = replay(replay_request)
            replay_model = replay_response["read_model"]
            self.assertEqual(replay_model["task_id"], read_model["task_id"])
            self.assertEqual(replay_model["run_id"], read_model["run_id"])
            self.assertNotIn("event_cursor", replay_model)

    def test_repeated_provider_admission_reuses_append_only_descriptor(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-product-provider-admission-") as directory:
            product = ProductRuntime(Path(directory), research_provider_factory=_provider_factory)
            project = create_project(
                product,
                display_name="Provider admission retry",
                notes=None,
                idempotency_key="create-provider-admission-project",
            )
            adapter = _provider_factory(None)
            first_registry, first_config = _ensure_provider_admission(
                product,
                project_id=project["project_id"],
                adapter=adapter,
            )
            second_registry, second_config = _ensure_provider_admission(
                product,
                project_id=project["project_id"],
                adapter=adapter,
            )
            self.assertEqual(first_config, second_config)
            self.assertIsNot(first_registry, second_registry)

    def test_caller_numeric_truth_is_rejected_by_closed_contract(self) -> None:
        request = _request("prj_01ARZ3NDEKTSV4RRFFQ69G5FB", "pcr_01ARZ3NDEKTSV4RRFFQ69G5FB")
        request["observations"] = []
        with self.assertRaises(ContractValidationError):
            SubmitResearchRequestV1.from_mapping(request)


if __name__ == "__main__":
    unittest.main()
