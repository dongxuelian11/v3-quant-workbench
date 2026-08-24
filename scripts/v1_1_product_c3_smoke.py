"""V1.1 canonical Strategy -> Backtest -> VALID Result restart smoke."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from v3_backend.adapters.local_data import LocalDataImportIntentV1
from v3_backend.domain.tasks.entities import TASK_TERMINAL_STATES
from v3_backend.runtime.product_backtest import ProductResearchBacktestService
from v3_backend.runtime.product_data import ProductDataService
from v3_backend.runtime.product_entry import create_project
from v3_backend.runtime.product_facades import ProductEntryFacade
from v3_backend.runtime.product_factor import ProductFactorStudyService
from v3_backend.runtime.product_runtime import ProductRuntime, mint_uuid7
from v3_backend.runtime.product_strategy import ProductStrategyService, ResearchStrategySpecV1
from v3_backend.runtime.product_workers import ProductResearchWorkerConfig


FIRST_SESSION = date(2026, 7, 6)
FORMULA = """MJ:=AMOUNT/VOL/100;
MA5:=MA(MJ,5);
MA20:=MA(MJ,20);
MA60:=MA(MJ,60);
GOLDEN_CROSS:CROSS(MA20,MA60) AND MA5>MA20;
DEATH_CROSS:CROSS(MA60,MA20) AND MA5<MA20;
"""


def panel_csv() -> bytes:
    rows = ["symbol,date,open,high,low,close,volume,amount"]
    for offset in range(70):
        session = FIRST_SESSION + timedelta(days=offset)
        for symbol, price in (
            ("600519", 100 if offset < 60 else 200),
            ("000001", 300 if offset < 60 else 150),
        ):
            volume = 10_000
            rows.append(
                f"{symbol},{session.isoformat()},{price},{price},{price},{price},"
                f"{volume},{price * volume}"
            )
    return ("\n".join(rows) + "\n").encode("utf-8")


def require_terminal(product: ProductRuntime, task_id: str) -> object:
    deadline = time.monotonic() + 30.0
    task = product.task_persistence.read_task(task_id)
    while task.state not in TASK_TERMINAL_STATES and time.monotonic() < deadline:
        time.sleep(0.05)
        task = product.task_persistence.read_task(task_id)
    if task.state.value != "SUCCEEDED":
        raise RuntimeError(f"Product research Backtest Task did not succeed: {task.state.value}")
    return task


def exact_artifact_evidence(product: ProductRuntime, artifact_id: str) -> dict[str, object]:
    payload = product.read_verified_bytes(artifact_id)
    digest = hashlib.sha256(payload).hexdigest()
    if artifact_id != f"art_sha256_{digest}":
        raise RuntimeError(f"Artifact identity drifted: {artifact_id}")
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"Artifact root is not an object: {artifact_id}")
    return {
        "artifact_id": artifact_id,
        "byte_size": len(payload),
        "sha256": digest,
        "artifact_type": value.get("artifact_type"),
    }


def main(storage: Path, mode: str) -> None:
    if mode not in {"backtest", "result"}:
        raise RuntimeError("C3 smoke mode must be backtest or result")
    product = ProductRuntime(storage)
    project = create_project(
        product,
        display_name="V1.1 C3 smoke",
        notes=None,
        idempotency_key="v1-1-c3-smoke-project",
    )
    imported = ProductDataService(product).import_local_dataset(
        project_id=project["project_id"],
        project_context_revision_id=project["project_context_revision_id"],
        display_name="c3-smoke.csv",
        source=io.BytesIO(panel_csv()),
        intent=LocalDataImportIntentV1(
            media_type="text/csv",
            volume_unit="SHARES",
            amount_unit="CNY",
            timezone="Asia/Shanghai",
            adjustment="UNADJUSTED",
        ),
    )
    study = ProductFactorStudyService(product).run_factor_study(
        project_id=project["project_id"],
        project_context_revision_id=imported["project_context_revision_id"],
        formula_source=FORMULA,
        analysis_output_name="MJ",
    )
    strategy_service = ProductStrategyService(product)
    profile = strategy_service.bounded_profile_ids()
    strategy_spec = ResearchStrategySpecV1.create(
        universe_version_id=str(imported["universe_version_id"]),
        entry_signal_factor_version_id=str(study["outputs"]["GOLDEN_CROSS"]["factor_definition_version_id"]),
        exit_signal_factor_version_id=str(study["outputs"]["DEATH_CROSS"]["factor_definition_version_id"]),
        position_sizing="EQUAL_WEIGHT_ACTIVE_SIGNALS",
        max_positions=2,
        gross_exposure="1",
        rebalance="NEXT_OPEN_AFTER_SIGNAL",
        cost_policy_version_id=profile["cost_policy_version_id"],
        execution_policy_version_id=profile["execution_policy_version_id"],
        risk_policy_set_version_id=profile["risk_policy_set_version_id"],
        initial_cash="1000000",
        assumption_profile_id=profile["assumption_profile_id"],
    )
    strategy = strategy_service.publish_strategy(
        project_id=project["project_id"],
        project_context_revision_id=imported["project_context_revision_id"],
        spec=strategy_spec,
    )

    runtime = ProductRuntime(storage, research_worker_config=ProductResearchWorkerConfig())
    request_id = mint_uuid7()
    accepted_response = ProductEntryFacade(runtime).handlers()[
        "ProductEntryService.v1.submitResearchBacktest"
    ](
        {
            "request_id": request_id,
            "project_id": project["project_id"],
            "project_context_revision_id": imported["project_context_revision_id"],
            "research_strategy_spec_id": strategy["research_strategy_spec_id"],
            "session_start": FIRST_SESSION.isoformat(),
            "session_end": (FIRST_SESSION + timedelta(days=69)).isoformat(),
            "slippage_bps": "10",
            "daily_volume_participation_rate": "0.1",
            "idempotency_key": "v1-1-c3-smoke-backtest",
        }
    )
    accepted = accepted_response["read_model"]
    if accepted["accepted_state"] != "QUEUED":
        raise RuntimeError("Backtest ProductEntry command was not durably queued")
    try:
        task = require_terminal(runtime, str(accepted["task_id"]))
    finally:
        runtime.research_workers.shutdown_all()

    restarted = ProductRuntime(storage)
    restored = ProductResearchBacktestService(restarted).get_latest_backtest(
        project_id=project["project_id"],
        project_context_revision_id=imported["project_context_revision_id"],
    )
    home_response = ProductEntryFacade(restarted).get_project_home(
        {
            "request_id": mint_uuid7(),
            "project_id": project["project_id"],
            "project_context_revision_id": imported["project_context_revision_id"],
        }
    )
    home = home_response["read_model"]
    if (
        restored["result_state"] != "VALID"
        or home["backtest_state"] != "AVAILABLE"
        or home["backtest"]["result_id"] != restored["result_id"]
        or restored["research_strategy_spec_id"] != strategy["research_strategy_spec_id"]
        or task.operation_id != "ProductEntryService.v1.submitResearchBacktest"
    ):
        raise RuntimeError("canonical Backtest/Result restart readback drifted")

    result_artifact = exact_artifact_evidence(restarted, str(restored["result_artifact_id"]))
    analytics_artifact = exact_artifact_evidence(restarted, str(restored["analytics_artifact_id"]))
    lineage_artifact = exact_artifact_evidence(restarted, str(restored["lineage_artifact_id"]))
    if mode == "result" and (
        result_artifact["artifact_type"] != "BacktestRunResult"
        or analytics_artifact["artifact_type"] != "ProductBacktestResultAnalytics"
        or lineage_artifact["artifact_type"] != "ProductResultLineage"
    ):
        raise RuntimeError("Result smoke artifact semantics drifted")

    print(
        json.dumps(
            {
                "status": "PASS",
                "mode": mode,
                "truth": restored["truth"],
                "admission": restored["admission"],
                "maturity": restored["maturity"],
                "task_id": accepted["task_id"],
                "run_id": restored["run_id"],
                "research_strategy_spec_id": restored["research_strategy_spec_id"],
                "research_backtest_request_id": restored["research_backtest_request_id"],
                "result_id": restored["result_id"],
                "backtest_result_id": restored["backtest_result_id"],
                "result_state": restored["result_state"],
                "order_count": restored["order_count"],
                "fill_count": restored["fill_count"],
                "result_artifact": result_artifact,
                "analytics_artifact": analytics_artifact,
                "lineage_artifact": lineage_artifact,
                "restart_readback": "PASS",
                "recomputed_on_restart": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve(), sys.argv[2])
