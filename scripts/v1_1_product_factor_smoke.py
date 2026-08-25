"""V1.1 durable ProductEntry Factor execution and restart smoke."""

from __future__ import annotations

import io
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from v3_backend.adapters.local_data import LocalDataImportIntentV1
from v3_backend.domain.tasks.entities import TASK_TERMINAL_STATES
from v3_backend.runtime.product_data import ProductDataService
from v3_backend.runtime.product_entry import create_project
from v3_backend.runtime.product_facades import build_product_facades
from v3_backend.runtime.product_factor import ProductFactorStudyService
from v3_backend.runtime.product_runtime import ProductRuntime, mint_uuid7
from v3_backend.runtime.product_workers import ProductResearchWorkerConfig
from v3_backend.runtime.request_router import RequestRouter


FORMULA = """MJ:=AMOUNT/VOL/100;
MA5:=MA(MJ,5);
MA20:=MA(MJ,20);
MA60:=MA(MJ,60);
GOLDEN_CROSS:CROSS(MA20,MA60) AND MA5>MA20;
DEATH_CROSS:CROSS(MA60,MA20) AND MA5<MA20;
"""


def panel_csv() -> bytes:
    rows = ["symbol,date,open,high,low,close,volume,amount"]
    first = date(2025, 1, 1)
    for offset in range(70):
        session = first + timedelta(days=offset)
        for symbol, price in (("600519", 100 if offset < 60 else 200),):
            volume = 10_000
            rows.append(
                f"{symbol},{session.isoformat()},{price},{price},{price},{price},{volume},{price * volume}"
            )
    return ("\n".join(rows) + "\n").encode("utf-8")


def handlers(product: ProductRuntime):
    return {
        operation_id: callback
        for facade in build_product_facades(product)
        for operation_id, callback in facade.handlers().items()
    }


def main(storage: Path) -> None:
    product = ProductRuntime(
        storage,
        research_worker_config=ProductResearchWorkerConfig(),
    )
    project = create_project(
        product,
        display_name="V1.1 Factor smoke",
        notes=None,
        idempotency_key="v1-1-factor-smoke-project",
    )
    imported = ProductDataService(product).import_local_dataset(
        project_id=project["project_id"],
        project_context_revision_id=project["project_context_revision_id"],
        display_name="factor-smoke.csv",
        source=io.BytesIO(panel_csv()),
        intent=LocalDataImportIntentV1(
            media_type="text/csv",
            volume_unit="SHARES",
            amount_unit="CNY",
            timezone="Asia/Shanghai",
            adjustment="UNADJUSTED",
        ),
    )
    request_id = mint_uuid7()
    body = {
        "request_id": request_id,
        "project_id": project["project_id"],
        "project_context_revision_id": imported["project_context_revision_id"],
        "expected_api_version": "1.1",
        "idempotency_key": "v1-1-factor-smoke-study",
        "formula_source": FORMULA,
        "analysis_output_name": "MJ",
    }
    response = RequestRouter(handlers(product)).route(
        {
            "kind": "request",
            "request_id": request_id,
            "operation_id": "ProductEntryService.v1.submitFactorStudy",
            "contract_version": "1.1",
            "project_id": project["project_id"],
            "project_context_revision_id": imported["project_context_revision_id"],
            "body": body,
        }
    )
    if response["status"] != "OK":
        raise RuntimeError(f"Factor ProductEntry acceptance failed: {response}")
    accepted = response["body"]["read_model"]
    if accepted["accepted_state"] != "QUEUED":
        raise RuntimeError("Factor command was not durably queued")
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            task = product.task_persistence.read_task(accepted["task_id"])
            if task.state in TASK_TERMINAL_STATES:
                break
            time.sleep(0.05)
        if task.state.value != "SUCCEEDED":
            raise RuntimeError(f"Factor Task did not succeed: {task.state.value}")
    finally:
        product.research_workers.shutdown_all()

    reopened_runtime = ProductRuntime(storage)
    restored = ProductFactorStudyService(reopened_runtime).get_latest_factor_study(
        project_id=project["project_id"],
        project_context_revision_id=imported["project_context_revision_id"],
        snapshot_id=imported["snapshot_id"],
    )
    if (
        restored["formula_document_version_id"]
        != accepted["formula_document_version_id"]
        or not any(row["GOLDEN_CROSS"] is True for row in restored["visual_preview"])
        or restored["analysis"]["aggregate"]["ic_mean"]["status"]
        != "INSUFFICIENT_SAMPLE"
    ):
        raise RuntimeError("canonical Factor restart readback drifted")
    print(
        json.dumps(
            {
                "status": "PASS",
                "truth": restored["truth"],
                "admission": restored["admission"],
                "task_id": accepted["task_id"],
                "run_id": accepted["run_id"],
                "snapshot_id": restored["snapshot_id"],
                "universe_version_id": restored["universe_version_id"],
                "formula_document_version_id": restored["formula_document_version_id"],
                "factor_analysis_result_id": restored["analysis"]["factor_analysis_result_id"],
                "output_names": list(restored["outputs"]),
                "single_symbol_truth": restored["analysis"]["aggregate"]["ic_mean"]["status"],
                "restart_readback": "PASS",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
