"""Clean-start Product Runtime research smoke at the provider boundary.

The only synthetic input in this smoke is a provider response returned by the
injected provider loader.  Product Entry receives only closed provider/source
refs and date/symbol intent; observations are constructed inside the backend
after the adapter has emitted and the runtime has verified canonical raw bytes.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "backend" / "src"))

from v3_backend.adapters.market_data.akshare import AkshareAShareEodAdapter  # noqa: E402
from v3_backend.contracts.product_entry import SubmitResearchRequestV1, SubmitResearchResponseV1  # noqa: E402
from v3_backend.runtime.product_entry import create_project  # noqa: E402
from v3_backend.runtime.product_facades import build_product_facades  # noqa: E402
from v3_backend.runtime.product_runtime import ProductRuntime  # noqa: E402


class _Frame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def to_dict(self, *, orient: str) -> list[dict[str, object]]:
        if orient != "records":
            raise RuntimeError("provider adapter requested a non-record response")
        return list(self.rows)


class _Provider:
    __version__ = "1.18.84"

    def stock_zh_a_hist(self, **_request: object) -> _Frame:
        return _Frame(
            [
                {"股票代码": "000001", "日期": "2026-01-06", "开盘": "10.00", "最高": "11.00", "最低": "9.50", "收盘": "10.50", "成交量": "1000", "成交额": "10500"},
                {"股票代码": "000001", "日期": "2026-01-07", "开盘": "10.50", "最高": "11.50", "最低": "10.00", "收盘": "11.00", "成交量": "1200", "成交额": "13200"},
            ]
        )


def _provider_factory(config):
    return AkshareAShareEodAdapter(
        connector_version_id=config.connector_version_id,
        loader=lambda: _Provider(),
        clock=lambda: datetime(2026, 1, 8, 8, 0, tzinfo=timezone.utc),
    )


def _handler(product: ProductRuntime, operation_id: str):
    for facade in build_product_facades(product):
        callback = facade.handlers().get(operation_id)
        if callback is not None:
            return callback
    raise RuntimeError(f"missing Product Runtime handler: {operation_id}")


def _request(project_id: str, revision_id: str) -> dict[str, object]:
    return {
        "request_id": str(uuid.uuid4()),
        "project_id": project_id,
        "project_context_revision_id": revision_id,
        "expected_api_version": "1.0",
        "idempotency_key": "clean-start-product-research-001",
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


def _submit_research(product: ProductRuntime, project: dict[str, object]):
    request = _request(project["project_id"], project["project_context_revision_id"])
    validated_request = SubmitResearchRequestV1.from_mapping(request)
    submit = _handler(product, "ProductEntryService.v1.submitResearch")
    response = submit(validated_request.to_wire())
    validated_response = SubmitResearchResponseV1.from_mapping(response)
    model = validated_response["read_model"]
    task = product.task_persistence.read_task(model["task_id"])
    if task.state.value != "SUCCEEDED":
        raise RuntimeError(f"research Task did not finish successfully: {task.state.value}")
    return request, validated_response, model


def _read_result_artifact(product: ProductRuntime, project: dict[str, object], model: dict[str, object]):
    task_request = {
        "request_id": str(uuid.uuid4()),
        "project_id": project["project_id"],
        "project_context_revision_id": project["project_context_revision_id"],
        "expected_api_version": "1.0",
        "task_id": model["task_id"],
    }
    task_read = _handler(product, "TaskService.v1.getTask")(task_request)["read_model"]
    result_id = task_read["result_id"]
    if not isinstance(result_id, str) or not result_id:
        raise RuntimeError("research Task has no canonical Result relation")
    result_read = _handler(product, "ResultService.v1.getResult")(
        {
            "request_id": str(uuid.uuid4()),
            "project_id": project["project_id"],
            "project_context_revision_id": project["project_context_revision_id"],
            "expected_api_version": "1.0",
            "result_id": result_id,
            "section": "summary",
            "page": {},
        }
    )["read_model"]
    artifact_id = result_read["result_artifact"]["artifact_id"]
    artifact_read = _handler(product, "ArtifactService.v1.getArtifactDescriptor")(
        {
            "request_id": str(uuid.uuid4()),
            "project_id": project["project_id"],
            "project_context_revision_id": project["project_context_revision_id"],
            "expected_api_version": "1.0",
            "artifact_id": artifact_id,
        }
    )["read_model"]
    return result_id, artifact_id, artifact_read


def _assert_replay(storage_root: Path, request: dict[str, object], model: dict[str, object]) -> None:
    reopened = ProductRuntime(storage_root, research_provider_factory=_provider_factory)
    replay = _handler(reopened, "ProductEntryService.v1.submitResearch")(request)
    replay_model = replay["read_model"]
    if replay_model["task_id"] != model["task_id"] or replay_model["run_id"] != model["run_id"]:
        raise RuntimeError("restart/reopen idempotency did not resolve the original Task/Run")
    if "event_cursor" in replay_model:
        raise RuntimeError("idempotent restart replay unexpectedly minted a new event cursor")


def run(storage_root: Path) -> None:
    product = ProductRuntime(storage_root, research_provider_factory=_provider_factory)
    project = create_project(
        product,
        display_name="clean-start Product Research",
        notes=None,
        idempotency_key="clean-start-product-research-project-001",
    )
    request, validated_response, model = _submit_research(product, project)
    result_id, artifact_id, artifact_read = _read_result_artifact(product, project, model)
    _assert_replay(storage_root, request, model)

    print(json.dumps({
        "status": "PASS",
        "project_id": project["project_id"],
        "project_context_revision_id": project["project_context_revision_id"],
        "task_id": model["task_id"],
        "run_id": model["run_id"],
        "result_id": result_id,
        "result_artifact_id": artifact_id,
        "artifact_sha256": artifact_read["sha256"],
        "truth_state": validated_response["truth_state"],
        "maturity": model["maturity"],
        "research_classification": model["research_classification"],
        "reopened_replay": True,
    }, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: product_research_smoke_python.py <storage-root>")
    run(Path(sys.argv[1]).resolve())
