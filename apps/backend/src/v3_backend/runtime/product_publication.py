"""Durable V1.1 publication/finality seam for Product research Backtests.

The filesystem and SQLite catalog are deliberately treated as two media.  A
durable PublicationIntent is created before bytes are published; catalog
ownership is recorded while the Result is still pending; only an exact-byte
reconciliation may finalize the Result and Task in one SQLite transaction.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Callable, Mapping

from v3_backend.domain.backtest_runtime import (
    BacktestRunResult,
    BacktestRunSpec,
    ResearchExecutionInputs,
)
from v3_backend.domain.result_analytics import (
    DeterministicResultAnalyticsEngine,
    ResultAnalyticsPolicyVersion,
    SourceResultBinding,
)
from v3_backend.domain.tasks.entities import AttemptState, RunState
from v3_backend.domain.tasks.events import PendingTaskEvent
from v3_backend.domain.tasks.state_machine import (
    TaskTransitionContext,
    transition_attempt,
    transition_run,
    transition_task,
)
from v3_backend.errors.exceptions import TruthPreconditionFailedError
from v3_backend.provenance.canonical_hash import canonical_json_bytes, canonical_sha256

from .product_runtime import (
    BACKTEST_RUN_RESULT_ROLE,
    BACKTEST_RUN_SPEC_ROLE,
    LEDGER_MANIFEST_ROLE,
    ProductRuntime,
    _TASK_EVENT_VERSION,
    mint_v3_id,
    wire_time,
)


EXECUTION_INPUTS_ROLE = "PRODUCT_RESEARCH_EXECUTION_INPUTS"
ASSUMPTION_RECEIPT_ROLE = "PRODUCT_RESEARCH_ASSUMPTION_RECEIPT"
RECONCILIATION_ROLE = "PRODUCT_RESEARCH_RESULT_RECONCILIATION"
ANALYTICS_ROLE = "PRODUCT_RESULT_ANALYTICS"
LINEAGE_ROLE = "PRODUCT_RESULT_LINEAGE"
READ_MODEL_ROLE = "PRODUCT_RESEARCH_BACKTEST_READ_MODEL"
SUMMARY_EXPORT_ROLE = "PRODUCT_RESULT_EXPORT_SUMMARY_JSON"
ORDERS_EXPORT_ROLE = "PRODUCT_RESULT_EXPORT_ORDERS_CSV"
FILLS_EXPORT_ROLE = "PRODUCT_RESULT_EXPORT_FILLS_CSV"
_INTENT_KIND = "PRODUCT_RESEARCH_BACKTEST_V1"
_ASSUMPTION_MODES = {"RESEARCH_APPROXIMATE", "STRICT_FAIL_CLOSED"}


@dataclass(frozen=True, slots=True)
class FinalizedBacktestPublication:
    result_id: str
    publication_intent_id: str
    read_model: dict[str, Any]


class ProductBacktestPublication:
    """Publish and atomically finalize one already-computed canonical Result."""

    def __init__(
        self,
        product: ProductRuntime,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self.product = product
        self._fault_injector = fault_injector

    def _fault(self, point: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(point)

    @staticmethod
    def _ledger_manifest(result: BacktestRunResult) -> dict[str, Any]:
        return {
            "schema_version": "v3.ledger-manifest/1.1.0-research",
            "backtest_result_id": result.result_id,
            "backtest_result_sha256": result.content_sha256,
            "run_spec_id": result.run_spec_id,
            "ledger_digests": {
                "cash_ledger": canonical_sha256(
                    [row.to_wire() for row in result.cash_ledger]
                ),
                "position_ledger": canonical_sha256(
                    [row.to_wire() for row in result.position_ledger]
                ),
                "orders": canonical_sha256([row.to_wire() for row in result.orders]),
                "fills": canonical_sha256([row.to_wire() for row in result.fills]),
                "holdings": canonical_sha256(
                    [row.to_wire() for row in result.holdings]
                ),
                "nav": canonical_sha256([row.to_wire() for row in result.nav]),
            },
        }

    @staticmethod
    def _summary_export_wire(
        result: Mapping[str, Any],
        analytics: Mapping[str, Any],
        *,
        engine_version: str,
    ) -> dict[str, Any]:
        """Build the bounded user export from verified Result/Analytics owners."""

        core = analytics["core_analytics"]
        return {
            "schema_version": "v3.product-result-summary-export/1.0.0",
            "source_backtest_result_id": result["result_id"],
            "source_backtest_result_sha256": result["content_sha256"],
            "source_analytics_id": analytics["analytics_id"],
            "source_analytics_sha256": analytics["content_sha256"],
            "run_spec_id": result["run_spec_id"],
            "engine_version": engine_version,
            "order_count": len(result["orders"]),
            "fill_count": len(result["fills"]),
            "diagnostic_count": len(result["diagnostics"]),
            "metrics": core["metrics"]
            | {"calmar": analytics["supplemental_metrics"]["calmar"]},
            "cost_summary": {
                "costs": core["costs"],
                "turnover": core["turnover"],
            },
            "benchmark_status": core["benchmark"]["status"],
            "truth": "NOT_FORMAL",
            "admission": "PRE_ALPHA",
        }

    @staticmethod
    def _csv_export_wire(
        *,
        result: Mapping[str, Any],
        kind: str,
    ) -> bytes:
        if kind == "orders":
            columns = (
                "source_backtest_result_id",
                "source_backtest_result_sha256",
                "order_id",
                "session_date",
                "instrument_id",
                "side",
                "requested_quantity",
                "raw_limit_price",
                "source_target_quantity_vector_id",
            )
            rows = list(result["orders"])
        elif kind == "fills":
            columns = (
                "source_backtest_result_id",
                "source_backtest_result_sha256",
                "fill_id",
                "order_id",
                "session_date",
                "instrument_id",
                "side",
                "quantity",
                "raw_price",
                "execution_price",
                "consideration",
                "commission",
                "stamp_duty",
                "transfer_fee",
                "exchange_fee",
                "total_fees",
                "participation_cap",
                "slippage_bps",
            )
            rows = []
            for item in result["fills"]:
                wire = dict(item)
                costs = wire.pop("costs")
                rows.append(
                    {
                        **wire,
                        "commission": costs["commission"],
                        "stamp_duty": costs["stamp_duty"],
                        "transfer_fee": costs["transfer_fee"],
                        "exchange_fee": costs["exchange_fee"],
                        "total_fees": costs["total"],
                    }
                )
        else:
            raise TruthPreconditionFailedError("unknown Product Result CSV export kind")
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\r\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **row,
                    "source_backtest_result_id": result["result_id"],
                    "source_backtest_result_sha256": result["content_sha256"],
                }
            )
        return output.getvalue().encode("utf-8")

    @staticmethod
    def _reconcile(
        *,
        spec: BacktestRunSpec,
        result: BacktestRunResult,
        result_payload: bytes,
        published_payload: bytes,
    ) -> dict[str, Any]:
        if result.run_spec_id != spec.run_spec_id:
            raise TruthPreconditionFailedError("Result/RunSpec identity mismatch")
        if published_payload != result_payload:
            raise TruthPreconditionFailedError("published Result bytes changed")
        rebuilt = BacktestRunResult.create(
            spec,
            result.target_quantity_vectors,
            result.orders,
            result.fills,
            result.diagnostics,
            result.cash_ledger,
            result.position_ledger,
            result.holdings,
            result.nav,
        )
        if rebuilt != result:
            raise TruthPreconditionFailedError("Result content identity changed")
        cash_sequences = [row.sequence for row in result.cash_ledger]
        position_sequences = [row.sequence for row in result.position_ledger]
        if cash_sequences != list(range(1, len(cash_sequences) + 1)):
            raise TruthPreconditionFailedError("cash ledger sequence is discontinuous")
        if position_sequences != list(range(1, len(position_sequences) + 1)):
            raise TruthPreconditionFailedError("position ledger sequence is discontinuous")

        orders = {row.order_id: row for row in result.orders}
        fills = {row.fill_id: row for row in result.fills}
        if len(orders) != len(result.orders) or len(fills) != len(result.fills):
            raise TruthPreconditionFailedError("Order/Fill identities are not unique")
        for fill in result.fills:
            order = orders.get(fill.order_id)
            if (
                order is None
                or order.instrument_id != fill.instrument_id
                or order.side is not fill.side
                or fill.quantity <= 0
                or fill.quantity > order.requested_quantity
            ):
                raise TruthPreconditionFailedError("Fill is not bound to its exact Order")
            execution_price = Decimal(fill.execution_price or fill.raw_price)
            if Decimal(fill.consideration) != execution_price * fill.quantity:
                raise TruthPreconditionFailedError("Fill consideration is inconsistent")

        cash = Decimal("0")
        for index, row in enumerate(result.cash_ledger):
            amount = Decimal(row.amount)
            cash = amount if index == 0 else cash + amount
            if cash != Decimal(row.balance_after):
                raise TruthPreconditionFailedError("cash ledger balance is inconsistent")
            if row.kind.value != "INITIAL_CASH" and row.reference_id not in fills:
                if row.kind.value != "CASH_DIVIDEND":
                    raise TruthPreconditionFailedError(
                        "cash ledger entry is not linked to a Fill"
                    )

        positions: dict[str, int] = {}
        for row in result.position_ledger:
            observed = positions.get(row.instrument_id, 0) + row.quantity_delta
            if observed != row.quantity_after or row.sellable_after > row.quantity_after:
                raise TruthPreconditionFailedError(
                    "position ledger balance is inconsistent"
                )
            positions[row.instrument_id] = observed

        for row in result.nav:
            if Decimal(row.nav) != Decimal(row.cash) + Decimal(row.holdings_value):
                raise TruthPreconditionFailedError("daily NAV is inconsistent")
        if result.nav and Decimal(result.nav[-1].cash) != cash:
            raise TruthPreconditionFailedError("terminal NAV cash differs from ledger")

        return {
            "schema_version": "v3.product-result-reconciliation/1.0.0",
            "backtest_result_id": result.result_id,
            "backtest_result_sha256": result.content_sha256,
            "run_spec_id": spec.run_spec_id,
            "checks": {
                "RESULT_BYTES": "PASS",
                "LEDGER_SEQUENCE": "PASS",
                "ORDER_FILL_LINK": "PASS",
                "CASH_BALANCE": "PASS",
                "POSITION_BALANCE": "PASS",
                "DAILY_NAV": "PASS",
            },
            "decision": "PASS",
        }

    @staticmethod
    def _decode_json_object(payload: bytes, label: str) -> dict[str, Any]:
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise TruthPreconditionFailedError(f"{label} bytes are invalid") from error
        if not isinstance(value, dict):
            raise TruthPreconditionFailedError(f"{label} must be a JSON object")
        if canonical_json_bytes(value) != payload:
            raise TruthPreconditionFailedError(f"{label} bytes are not canonical JSON")
        return value

    @staticmethod
    def _verify_wire_identity(
        value: Mapping[str, Any],
        *,
        artifact_type: str,
        identity_key: str,
        identity_prefix: str,
        implicit_payload: Mapping[str, Any] | None = None,
    ) -> None:
        if value.get("artifact_type") != artifact_type:
            raise TruthPreconditionFailedError(
                f"{artifact_type} artifact type drifted"
            )
        identity = value.get(identity_key)
        content_sha256 = value.get("content_sha256")
        if (
            not isinstance(identity, str)
            or not isinstance(content_sha256, str)
            or identity != identity_prefix + content_sha256
        ):
            raise TruthPreconditionFailedError(
                f"{artifact_type} content identity drifted"
            )
        payload = dict(value)
        payload.pop("artifact_type", None)
        payload.pop(identity_key, None)
        payload.pop("content_sha256", None)
        if implicit_payload is not None:
            for key, item in implicit_payload.items():
                if key in payload and payload[key] != item:
                    raise TruthPreconditionFailedError(
                        f"{artifact_type} implicit payload field drifted"
                    )
                payload[key] = item
        if canonical_sha256(payload) != content_sha256:
            raise TruthPreconditionFailedError(
                f"{artifact_type} payload hash drifted"
            )

    @classmethod
    def _reconcile_wire(
        cls,
        *,
        spec: Mapping[str, Any],
        result: Mapping[str, Any],
        result_payload: bytes,
    ) -> dict[str, Any]:
        cls._verify_wire_identity(
            spec,
            artifact_type="BacktestRunSpec",
            identity_key="run_spec_id",
            identity_prefix="btrs_sha256_",
        )
        cls._verify_wire_identity(
            result,
            artifact_type="BacktestRunResult",
            identity_key="result_id",
            identity_prefix="btrr_sha256_",
            # The frozen 1.0 Result wire omits this class-level field even
            # though it participates in the canonical domain identity.
            implicit_payload={"schema_version": BacktestRunResult.schema_version},
        )
        if result.get("run_spec_id") != spec.get("run_spec_id"):
            raise TruthPreconditionFailedError("Result/RunSpec identity mismatch")
        if canonical_json_bytes(dict(result)) != result_payload:
            raise TruthPreconditionFailedError("published Result bytes changed")

        cash_ledger = result.get("cash_ledger")
        position_ledger = result.get("position_ledger")
        orders_wire = result.get("orders")
        fills_wire = result.get("fills")
        nav = result.get("nav")
        if not all(
            isinstance(value, list)
            for value in (cash_ledger, position_ledger, orders_wire, fills_wire, nav)
        ):
            raise TruthPreconditionFailedError("Result ledger sections are invalid")
        if [row.get("sequence") for row in cash_ledger if isinstance(row, dict)] != list(
            range(1, len(cash_ledger) + 1)
        ):
            raise TruthPreconditionFailedError("cash ledger sequence is discontinuous")
        if [row.get("sequence") for row in position_ledger if isinstance(row, dict)] != list(
            range(1, len(position_ledger) + 1)
        ):
            raise TruthPreconditionFailedError(
                "position ledger sequence is discontinuous"
            )

        if not all(isinstance(row, dict) for row in orders_wire + fills_wire):
            raise TruthPreconditionFailedError("Order/Fill rows are invalid")
        orders = {row.get("order_id"): row for row in orders_wire}
        fills = {row.get("fill_id"): row for row in fills_wire}
        if (
            None in orders
            or None in fills
            or len(orders) != len(orders_wire)
            or len(fills) != len(fills_wire)
        ):
            raise TruthPreconditionFailedError("Order/Fill identities are not unique")
        for fill in fills_wire:
            order = orders.get(fill.get("order_id"))
            quantity = fill.get("quantity")
            if (
                order is None
                or order.get("instrument_id") != fill.get("instrument_id")
                or order.get("side") != fill.get("side")
                or not isinstance(quantity, int)
                or isinstance(quantity, bool)
                or quantity <= 0
                or not isinstance(order.get("requested_quantity"), int)
                or quantity > order["requested_quantity"]
            ):
                raise TruthPreconditionFailedError(
                    "Fill is not bound to its exact Order"
                )
            try:
                execution_price = Decimal(
                    str(fill.get("execution_price", fill.get("raw_price")))
                )
                consideration = Decimal(str(fill.get("consideration")))
            except Exception as error:
                raise TruthPreconditionFailedError(
                    "Fill monetary values are invalid"
                ) from error
            if consideration != execution_price * quantity:
                raise TruthPreconditionFailedError("Fill consideration is inconsistent")

        cash = Decimal("0")
        for index, row in enumerate(cash_ledger):
            if not isinstance(row, dict):
                raise TruthPreconditionFailedError("cash ledger row is invalid")
            try:
                amount = Decimal(str(row.get("amount")))
                balance_after = Decimal(str(row.get("balance_after")))
            except Exception as error:
                raise TruthPreconditionFailedError(
                    "cash ledger monetary value is invalid"
                ) from error
            cash = amount if index == 0 else cash + amount
            if cash != balance_after:
                raise TruthPreconditionFailedError("cash ledger balance is inconsistent")
            if row.get("kind") not in {"INITIAL_CASH", "CASH_DIVIDEND"} and row.get(
                "reference_id"
            ) not in fills:
                raise TruthPreconditionFailedError(
                    "cash ledger entry is not linked to a Fill"
                )

        positions: dict[str, int] = {}
        for row in position_ledger:
            if not isinstance(row, dict):
                raise TruthPreconditionFailedError("position ledger row is invalid")
            instrument_id = row.get("instrument_id")
            quantity_delta = row.get("quantity_delta")
            quantity_after = row.get("quantity_after")
            sellable_after = row.get("sellable_after")
            if (
                not isinstance(instrument_id, str)
                or not isinstance(quantity_delta, int)
                or not isinstance(quantity_after, int)
                or not isinstance(sellable_after, int)
            ):
                raise TruthPreconditionFailedError("position ledger values are invalid")
            observed = positions.get(instrument_id, 0) + quantity_delta
            if observed != quantity_after or sellable_after > quantity_after:
                raise TruthPreconditionFailedError(
                    "position ledger balance is inconsistent"
                )
            positions[instrument_id] = observed

        for row in nav:
            if not isinstance(row, dict):
                raise TruthPreconditionFailedError("daily NAV row is invalid")
            try:
                observed_nav = Decimal(str(row.get("nav")))
                expected_nav = Decimal(str(row.get("cash"))) + Decimal(
                    str(row.get("holdings_value"))
                )
            except Exception as error:
                raise TruthPreconditionFailedError("daily NAV value is invalid") from error
            if observed_nav != expected_nav:
                raise TruthPreconditionFailedError("daily NAV is inconsistent")
        if nav and Decimal(str(nav[-1].get("cash"))) != cash:
            raise TruthPreconditionFailedError("terminal NAV cash differs from ledger")

        return {
            "schema_version": "v3.product-result-reconciliation/1.0.0",
            "backtest_result_id": result["result_id"],
            "backtest_result_sha256": result["content_sha256"],
            "run_spec_id": spec["run_spec_id"],
            "checks": {
                "RESULT_BYTES": "PASS",
                "LEDGER_SEQUENCE": "PASS",
                "ORDER_FILL_LINK": "PASS",
                "CASH_BALANCE": "PASS",
                "POSITION_BALANCE": "PASS",
                "DAILY_NAV": "PASS",
            },
            "decision": "PASS",
        }

    def _load_recovery_artifact(
        self,
        staged: Mapping[str, Any],
        key: str,
        expected_role: str,
    ) -> tuple[str, bytes]:
        artifact_id = staged.get(key)
        artifact_ids = staged.get("artifact_ids")
        if (
            not isinstance(artifact_id, str)
            or not isinstance(artifact_ids, list)
            or artifact_id not in artifact_ids
        ):
            raise TruthPreconditionFailedError(
                f"PublicationIntent {key} binding is absent"
            )
        descriptor = self.product.require_published_artifact(artifact_id)
        if descriptor["semantic_role"] != expected_role:
            raise TruthPreconditionFailedError(
                f"PublicationIntent {key} role drifted"
            )
        return artifact_id, self.product.read_verified_bytes(artifact_id)

    def _require_active_reference(
        self, owner_id: str, role: str, artifact_id: str
    ) -> None:
        if not any(
            item["artifact_id"] == artifact_id
            for item in self.product.references(owner_id, role)
        ):
            raise TruthPreconditionFailedError(
                f"PublicationIntent {role} reference is not active"
            )

    @staticmethod
    def _verify_ledger_manifest(
        manifest: Mapping[str, Any], result: Mapping[str, Any]
    ) -> None:
        if (
            manifest.get("schema_version")
            != "v3.ledger-manifest/1.1.0-research"
            or manifest.get("backtest_result_id") != result.get("result_id")
            or manifest.get("backtest_result_sha256")
            != result.get("content_sha256")
            or manifest.get("run_spec_id") != result.get("run_spec_id")
        ):
            raise TruthPreconditionFailedError("ledger manifest identity drifted")
        digests = manifest.get("ledger_digests")
        if not isinstance(digests, dict):
            raise TruthPreconditionFailedError("ledger manifest digests are absent")
        expected = {
            "cash_ledger": canonical_sha256(result.get("cash_ledger")),
            "position_ledger": canonical_sha256(result.get("position_ledger")),
            "orders": canonical_sha256(result.get("orders")),
            "fills": canonical_sha256(result.get("fills")),
            "holdings": canonical_sha256(result.get("holdings")),
            "nav": canonical_sha256(result.get("nav")),
        }
        if digests != expected:
            raise TruthPreconditionFailedError("ledger manifest digest drifted")

    @staticmethod
    def _verify_analytics_wire(
        analytics: Mapping[str, Any], result: Mapping[str, Any]
    ) -> None:
        core = analytics.get("core_analytics")
        source = core.get("source_result") if isinstance(core, dict) else None
        if (
            analytics.get("artifact_type") != "ProductBacktestResultAnalytics"
            or analytics.get("schema_version")
            != "v3.backtest_result_analytics/1.1.0"
            or analytics.get("engine_version")
            != DeterministicResultAnalyticsEngine.product_engine_version
            or not isinstance(source, dict)
            or source.get("result_id") != result.get("result_id")
            or source.get("content_sha256") != result.get("content_sha256")
        ):
            raise TruthPreconditionFailedError("Result Analytics binding drifted")
        payload = {
            key: value
            for key, value in analytics.items()
            if key not in {"artifact_type", "analytics_id", "content_sha256"}
        }
        digest = canonical_sha256(payload)
        if (
            analytics.get("content_sha256") != digest
            or analytics.get("analytics_id") != "bra_sha256_" + digest
        ):
            raise TruthPreconditionFailedError("Result Analytics identity drifted")

    @staticmethod
    def _lineage_wire(
        *,
        project_id: str,
        project_context_revision_id: str,
        data: Mapping[str, Any],
        strategy: Mapping[str, Any],
        run_id: str,
        run_spec_artifact_id: str,
        result_id: str,
        result: BacktestRunResult,
        result_artifact_id: str,
        analytics_id: str,
        analytics_artifact_id: str,
    ) -> dict[str, Any]:
        payload = {
            "schema_version": "v3.product-result-lineage/1.0.0",
            "project_id": project_id,
            "project_context_revision_id": project_context_revision_id,
            "data": {
                "raw_capture_id": data["raw_capture_id"],
                "raw_artifact_id": data["artifact_ids"]["LOCAL_DATA_RAW_FILE"],
                "snapshot_id": data["snapshot_id"],
                "snapshot_manifest_artifact_id": data["artifact_ids"][
                    "DATA_TRUTH_SNAPSHOT_MANIFEST"
                ],
                "universe_version_id": data["universe_version_id"],
                "universe_membership_artifact_id": data["artifact_ids"][
                    "UNIVERSE_MEMBERSHIP"
                ],
            },
            "factors": {
                "entry": dict(strategy["entry_signal_ref"]),
                "exit": dict(strategy["exit_signal_ref"]),
            },
            "strategy": {
                "research_strategy_spec_id": strategy[
                    "research_strategy_spec_id"
                ],
                "research_strategy_spec_artifact_id": strategy[
                    "research_strategy_spec_artifact_id"
                ],
                "strategy_version_id": strategy["strategy_version_id"],
                "strategy_definition_version_id": strategy[
                    "strategy_definition_version_id"
                ],
                "strategy_definition_artifact_id": strategy[
                    "strategy_definition_artifact_id"
                ],
                "risk_policy_set_version_id": strategy["profile_refs"][
                    "risk_policy_set_version_id"
                ],
                "decision_chains": list(strategy["decision_chains"]),
            },
            "execution": {
                "run_id": run_id,
                "run_spec_id": result.run_spec_id,
                "run_spec_artifact_id": run_spec_artifact_id,
                "target_quantity_vectors": [
                    {
                        "target_quantity_vector_id": row.target_quantity_vector_id,
                        "source_weight_vector_id": row.source_weight_vector_id,
                        "session_date": row.session_date.isoformat(),
                    }
                    for row in result.target_quantity_vectors
                ],
                "orders": [
                    {
                        "order_id": row.order_id,
                        "source_target_quantity_vector_id": (
                            row.source_target_quantity_vector_id
                        ),
                        "instrument_id": row.instrument_id,
                        "session_date": row.session_date.isoformat(),
                    }
                    for row in result.orders
                ],
                "fills": [
                    {
                        "fill_id": row.fill_id,
                        "order_id": row.order_id,
                        "instrument_id": row.instrument_id,
                        "session_date": row.session_date.isoformat(),
                    }
                    for row in result.fills
                ],
            },
            "result": {
                "result_id": result_id,
                "backtest_result_id": result.result_id,
                "backtest_result_sha256": result.content_sha256,
                "result_artifact_id": result_artifact_id,
                "analytics_id": analytics_id,
                "analytics_artifact_id": analytics_artifact_id,
            },
            "truth": "NOT_FORMAL",
            "admission": "PRE_ALPHA",
        }
        digest = canonical_sha256(payload)
        return {
            "artifact_type": "ProductResultLineage",
            "result_lineage_id": "rln_sha256_" + digest,
            "content_sha256": digest,
            **payload,
        }

    @staticmethod
    def _verify_lineage_wire(
        lineage: Mapping[str, Any],
        *,
        project_id: str,
        result_id: str,
        result: Mapping[str, Any],
        analytics: Mapping[str, Any],
    ) -> None:
        payload = {
            key: value
            for key, value in lineage.items()
            if key not in {"artifact_type", "result_lineage_id", "content_sha256"}
        }
        digest = canonical_sha256(payload)
        result_binding = lineage.get("result")
        if (
            lineage.get("artifact_type") != "ProductResultLineage"
            or lineage.get("schema_version") != "v3.product-result-lineage/1.0.0"
            or lineage.get("content_sha256") != digest
            or lineage.get("result_lineage_id") != "rln_sha256_" + digest
            or lineage.get("project_id") != project_id
            or not isinstance(result_binding, dict)
            or result_binding.get("result_id") != result_id
            or result_binding.get("backtest_result_id") != result.get("result_id")
            or result_binding.get("backtest_result_sha256")
            != result.get("content_sha256")
            or result_binding.get("analytics_id") != analytics.get("analytics_id")
        ):
            raise TruthPreconditionFailedError("Product Result lineage binding drifted")

    @staticmethod
    def _recovered_read_model(
        *,
        intent: Mapping[str, Any],
        expected: Mapping[str, Any],
        staged: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        request_id = expected.get("request_id")
        required_text = {
            "project_id": intent.get("project_id"),
            "project_context_revision_id": staged.get(
                "project_context_revision_id"
            ),
            "research_backtest_request_id": request_id,
            "research_strategy_spec_id": staged.get("research_strategy_spec_id"),
            "snapshot_id": staged.get("snapshot_id"),
            "universe_version_id": staged.get("universe_version_id"),
            "run_id": intent.get("run_id"),
            "run_spec_id": staged.get("canonical_run_spec_id"),
            "run_spec_artifact_id": staged.get("run_spec_artifact_id"),
            "research_execution_inputs_artifact_id": staged.get(
                "research_execution_inputs_artifact_id"
            ),
            "result_id": staged.get("result_id"),
            "backtest_result_id": staged.get("backtest_result_id"),
            "result_artifact_id": staged.get("result_artifact_id"),
            "ledger_manifest_artifact_id": staged.get(
                "ledger_manifest_artifact_id"
            ),
            "assumption_receipt_artifact_id": staged.get(
                "assumption_receipt_artifact_id"
            ),
            "analytics_id": staged.get("analytics_id"),
            "analytics_artifact_id": staged.get("analytics_artifact_id"),
            "analytics_engine_version": staged.get("analytics_engine_version"),
            "summary_export_artifact_id": staged.get(
                "summary_export_artifact_id"
            ),
            "orders_export_artifact_id": staged.get(
                "orders_export_artifact_id"
            ),
            "fills_export_artifact_id": staged.get(
                "fills_export_artifact_id"
            ),
            "result_lineage_id": staged.get("result_lineage_id"),
            "lineage_artifact_id": staged.get("lineage_artifact_id"),
            "engine_version": staged.get("engine_version"),
            "first_effective_session_date": staged.get(
                "first_effective_session_date"
            ),
            "assumption_mode": staged.get("assumption_mode"),
            "publication_intent_id": intent.get("publication_intent_id"),
        }
        if any(not isinstance(value, str) or not value for value in required_text.values()):
            raise TruthPreconditionFailedError(
                "PublicationIntent recovery manifest is incomplete"
            )
        fills = result.get("fills")
        orders = result.get("orders")
        diagnostics = result.get("diagnostics")
        if not all(isinstance(value, list) for value in (fills, orders, diagnostics)):
            raise TruthPreconditionFailedError("Result summary sections are invalid")
        first_fill = None
        if fills:
            if not isinstance(fills[0], dict) or not isinstance(
                fills[0].get("session_date"), str
            ):
                raise TruthPreconditionFailedError("first Fill session is invalid")
            first_fill = fills[0]["session_date"]
        return {
            "schema_version": "v3.product-research-backtest-read-model/1.0.0",
            "maturity": "PRODUCT_CONNECTED",
            "truth": "NOT_FORMAL",
            "admission": "PRE_ALPHA",
            **required_text,
            "result_state": "VALID",
            "order_count": len(orders),
            "fill_count": len(fills),
            "diagnostic_count": len(diagnostics),
            "first_fill_session_date": first_fill,
        }

    def _recover_cataloged(self, intent: Mapping[str, Any]) -> None:
        try:
            expected = json.loads(str(intent["expected_outputs_json"]))
            staged = json.loads(str(intent["staged_manifest_json"]))
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise TruthPreconditionFailedError(
                "PublicationIntent recovery metadata is invalid"
            ) from error
        if not isinstance(expected, dict) or not isinstance(staged, dict):
            raise TruthPreconditionFailedError(
                "PublicationIntent recovery metadata is invalid"
            )

        run_spec_artifact_id, run_spec_payload = self._load_recovery_artifact(
            staged, "run_spec_artifact_id", BACKTEST_RUN_SPEC_ROLE
        )
        execution_artifact_id, execution_payload = self._load_recovery_artifact(
            staged, "research_execution_inputs_artifact_id", EXECUTION_INPUTS_ROLE
        )
        result_artifact_id, result_payload = self._load_recovery_artifact(
            staged, "result_artifact_id", BACKTEST_RUN_RESULT_ROLE
        )
        ledger_artifact_id, ledger_payload = self._load_recovery_artifact(
            staged, "ledger_manifest_artifact_id", LEDGER_MANIFEST_ROLE
        )
        assumption_artifact_id, assumption_payload = self._load_recovery_artifact(
            staged, "assumption_receipt_artifact_id", ASSUMPTION_RECEIPT_ROLE
        )
        analytics_artifact_id, analytics_payload = self._load_recovery_artifact(
            staged, "analytics_artifact_id", ANALYTICS_ROLE
        )
        summary_export_artifact_id, summary_export_payload = (
            self._load_recovery_artifact(
                staged, "summary_export_artifact_id", SUMMARY_EXPORT_ROLE
            )
        )
        orders_export_artifact_id, orders_export_payload = (
            self._load_recovery_artifact(
                staged, "orders_export_artifact_id", ORDERS_EXPORT_ROLE
            )
        )
        fills_export_artifact_id, fills_export_payload = (
            self._load_recovery_artifact(
                staged, "fills_export_artifact_id", FILLS_EXPORT_ROLE
            )
        )
        lineage_artifact_id, lineage_payload = self._load_recovery_artifact(
            staged, "lineage_artifact_id", LINEAGE_ROLE
        )
        spec_wire = self._decode_json_object(run_spec_payload, "BacktestRunSpec")
        result_wire = self._decode_json_object(result_payload, "BacktestRunResult")
        execution_wire = self._decode_json_object(
            execution_payload, "ResearchExecutionInputs"
        )
        ledger_wire = self._decode_json_object(ledger_payload, "LedgerManifest")
        assumption_wire = self._decode_json_object(
            assumption_payload, "AssumptionReceipt"
        )
        analytics_wire = self._decode_json_object(
            analytics_payload, "ProductBacktestResultAnalytics"
        )
        lineage_wire = self._decode_json_object(
            lineage_payload, "ProductResultLineage"
        )
        execution_profile = execution_wire.get("profile")
        assumption_mode = staged.get("assumption_mode")
        if (
            spec_wire.get("run_spec_id") != staged.get("canonical_run_spec_id")
            or result_wire.get("result_id") != staged.get("backtest_result_id")
            or execution_wire.get("schema_version")
            != "v3.research-execution-inputs/1.0.0"
            or not isinstance(execution_profile, dict)
            or assumption_mode not in _ASSUMPTION_MODES
            or execution_profile.get("assumption_mode") != assumption_mode
            or assumption_wire.get("schema_version")
            != "v3.research-assumption-receipt/1.0.0"
            or assumption_wire.get("research_backtest_request_id")
            != expected.get("request_id")
            or assumption_wire.get("assumption_mode") != assumption_mode
            or assumption_wire.get("research_execution_profile_id")
            != execution_profile.get("profile_id")
        ):
            raise TruthPreconditionFailedError(
                "PublicationIntent artifact relationship drifted"
            )
        self._verify_analytics_wire(analytics_wire, result_wire)
        if (
            analytics_wire.get("analytics_id") != staged.get("analytics_id")
            or analytics_wire.get("engine_version")
            != staged.get("analytics_engine_version")
        ):
            raise TruthPreconditionFailedError("Result Analytics recovery binding drifted")
        if (
            summary_export_payload
            != canonical_json_bytes(
                self._summary_export_wire(
                    result_wire,
                    analytics_wire,
                    engine_version=str(spec_wire["engine_version"]),
                )
            )
            or orders_export_payload
            != self._csv_export_wire(result=result_wire, kind="orders")
            or fills_export_payload
            != self._csv_export_wire(result=result_wire, kind="fills")
        ):
            raise TruthPreconditionFailedError(
                "Product Result export Artifact binding drifted"
            )
        self._verify_lineage_wire(
            lineage_wire,
            project_id=str(intent["project_id"]),
            result_id=str(staged.get("result_id")),
            result=result_wire,
            analytics=analytics_wire,
        )
        if lineage_wire.get("result_lineage_id") != staged.get("result_lineage_id"):
            raise TruthPreconditionFailedError("Result lineage recovery identity drifted")
        reconciliation = self._reconcile_wire(
            spec=spec_wire, result=result_wire, result_payload=result_payload
        )
        self._verify_ledger_manifest(ledger_wire, result_wire)

        run_id = str(intent["run_id"])
        result_id = str(staged.get("result_id"))
        for owner_id, role, artifact_id in (
            (run_id, BACKTEST_RUN_SPEC_ROLE, run_spec_artifact_id),
            (run_id, EXECUTION_INPUTS_ROLE, execution_artifact_id),
            (result_id, BACKTEST_RUN_RESULT_ROLE, result_artifact_id),
            (result_id, LEDGER_MANIFEST_ROLE, ledger_artifact_id),
            (result_id, ASSUMPTION_RECEIPT_ROLE, assumption_artifact_id),
            (result_id, ANALYTICS_ROLE, analytics_artifact_id),
            (result_id, SUMMARY_EXPORT_ROLE, summary_export_artifact_id),
            (result_id, ORDERS_EXPORT_ROLE, orders_export_artifact_id),
            (result_id, FILLS_EXPORT_ROLE, fills_export_artifact_id),
            (result_id, LINEAGE_ROLE, lineage_artifact_id),
        ):
            self._require_active_reference(owner_id, role, artifact_id)

        connection = self.product._connection(read_only=True)
        try:
            result_row = connection.execute(
                "SELECT state,project_id,backtest_run_id,ledger_manifest_artifact_id "
                "FROM result WHERE result_id=?",
                (result_id,),
            ).fetchone()
        finally:
            connection.close()
        if (
            result_row is None
            or str(result_row[0]) != "PENDING_RECONCILIATION"
            or str(result_row[1]) != intent["project_id"]
            or str(result_row[2]) != run_id
            or str(result_row[3]) != ledger_artifact_id
        ):
            raise TruthPreconditionFailedError("pending Result binding drifted")

        read_model = self._recovered_read_model(
            intent=intent, expected=expected, staged=staged, result=result_wire
        )
        request_id = str(expected["request_id"])
        secondary = self.product.execution._publish_artifact_batch(
            payloads=(
                (
                    "prv_product_reconciliation_" + result_id,
                    canonical_json_bytes(reconciliation),
                    RECONCILIATION_ROLE,
                    "v3.product-result-reconciliation/1.0.0",
                ),
                (
                    "prv_product_backtest_read_model_" + request_id,
                    canonical_json_bytes(read_model),
                    READ_MODEL_ROLE,
                    "v3.product-research-backtest-read-model/1.0.0",
                ),
            ),
            references=(
                (result_id, RECONCILIATION_ROLE, 0),
                (str(intent["project_id"]), READ_MODEL_ROLE, 1),
            ),
        )
        reconciliation_artifact, read_model_artifact = (
            item.descriptor for item in secondary
        )
        with self.product.task_persistence.begin() as unit:
            handles = SimpleNamespace(
                task=unit.require_task(str(intent["task_id"])),
                run=unit.require_run(run_id),
                attempt=unit.require_attempt(str(intent["attempt_id"])),
            )
            unit.commit()
        self._finalize_catalog(
            handles=handles,
            result_id=result_id,
            publication_intent_id=str(intent["publication_intent_id"]),
            reconciliation_artifact_id=reconciliation_artifact.artifact_id,
            outputs=(
                (BACKTEST_RUN_SPEC_ROLE, 0, run_spec_artifact_id),
                (EXECUTION_INPUTS_ROLE, 0, execution_artifact_id),
                (BACKTEST_RUN_RESULT_ROLE, 0, result_artifact_id),
                (LEDGER_MANIFEST_ROLE, 0, ledger_artifact_id),
                (ASSUMPTION_RECEIPT_ROLE, 0, assumption_artifact_id),
                (ANALYTICS_ROLE, 0, analytics_artifact_id),
                (SUMMARY_EXPORT_ROLE, 0, summary_export_artifact_id),
                (ORDERS_EXPORT_ROLE, 0, orders_export_artifact_id),
                (FILLS_EXPORT_ROLE, 0, fills_export_artifact_id),
                (LINEAGE_ROLE, 0, lineage_artifact_id),
                (RECONCILIATION_ROLE, 0, reconciliation_artifact.artifact_id),
                (READ_MODEL_ROLE, 0, read_model_artifact.artifact_id),
            ),
        )

    def _publish_failure_reconciliation(
        self, intent: Mapping[str, Any], error: Exception
    ) -> str | None:
        try:
            staged = json.loads(str(intent["staged_manifest_json"]))
        except (KeyError, TypeError, json.JSONDecodeError):
            return None
        if not isinstance(staged, dict):
            return None
        result_id = staged.get("result_id")
        if not isinstance(result_id, str) or not result_id.startswith("res_"):
            return None
        connection = self.product._connection(read_only=True)
        try:
            result_exists = connection.execute(
                "SELECT 1 FROM result WHERE result_id=? AND state='PENDING_RECONCILIATION'",
                (result_id,),
            ).fetchone()
        finally:
            connection.close()
        if result_exists is None:
            return None
        payload = canonical_json_bytes(
            {
                "schema_version": "v3.product-result-reconciliation/1.0.0",
                "publication_intent_id": str(intent["publication_intent_id"]),
                "result_id": result_id,
                "decision": "FAIL",
                "reason_code": "RESIDUAL_VALIDATION_FAILED",
                "failure_class": type(error).__name__,
                "checks": {"RECOVERY_RECONCILIATION": "FAIL"},
            }
        )
        published = self.product.execution._publish_artifact_batch(
            payloads=(
                (
                    "prv_product_reconciliation_failure_" + result_id,
                    payload,
                    RECONCILIATION_ROLE,
                    "v3.product-result-reconciliation/1.0.0",
                ),
            ),
            references=((result_id, RECONCILIATION_ROLE, 0),),
        )
        return published[0].descriptor.artifact_id

    def _fail_pending_intent(
        self,
        intent: Mapping[str, Any],
        *,
        reason_code: str,
        reconciliation_artifact_id: str | None = None,
    ) -> None:
        """End an unrecoverable publication without permitting false success."""

        now = wire_time(datetime.now(timezone.utc))
        with self.product.task_persistence.begin() as unit:
            task_id = str(intent["task_id"])
            run_id = str(intent["run_id"])
            attempt_id = str(intent["attempt_id"])
            task = unit.require_task(task_id)
            if task.state.value == "SUCCEEDED":
                raise TruthPreconditionFailedError(
                    "Task succeeded before PublicationIntent finality"
                )
            unit.connection.execute(
                "UPDATE result SET state='INVALID',invalid_reason_code=?,"
                "reconciliation_artifact_id=COALESCE(?,reconciliation_artifact_id),"
                "finalized_at=? "
                "WHERE backtest_run_id=? AND state='PENDING_RECONCILIATION'",
                (reason_code, reconciliation_artifact_id, now, run_id),
            )
            unit.connection.execute(
                "UPDATE task_attempt SET state='FAILED',error_code=?,finished_at=? "
                "WHERE attempt_id=? AND state NOT IN "
                "('SUCCEEDED','FAILED','CANCELLED','LOST')",
                (reason_code, now, attempt_id),
            )
            unit.connection.execute(
                "UPDATE run SET state='TERMINAL',terminal_at=? "
                "WHERE run_id=? AND state IN ('SEALED','ACTIVE')",
                (now, run_id),
            )
            task_changed = unit.connection.execute(
                "UPDATE task SET state='FAILED',state_version=state_version+1,"
                " updated_at=?,terminal_at=? WHERE task_id=? AND state NOT IN "
                "('SUCCEEDED','FAILED','CANCELLED','PARTIAL')",
                (now, now, task_id),
            )
            intent_changed = unit.connection.execute(
                "UPDATE publication_intent SET state='FAILED',last_error_code=?,"
                "updated_at=?,finalized_at=?,state_version=state_version+1 "
                "WHERE publication_intent_id=? AND state NOT IN ('FINALIZED','FAILED')",
                (
                    reason_code,
                    now,
                    now,
                    str(intent["publication_intent_id"]),
                ),
            )
            if intent_changed.rowcount != 1:
                raise TruthPreconditionFailedError(
                    "PublicationIntent failure state drifted"
                )
            if task_changed.rowcount == 1:
                unit.append_event(
                    PendingTaskEvent(
                        event_id=mint_v3_id("tev_"),
                        event_version=_TASK_EVENT_VERSION,
                        project_id=str(intent["project_id"]),
                        task_id=task_id,
                        event_type="TASK_FAILED",
                        occurred_at=datetime.now(timezone.utc),
                        payload={
                            "error_type": "PublicationRecoveryFailure",
                            "error_category": "RESIDUAL_VALIDATION_FAILED",
                            "reason_code": reason_code,
                        },
                        run_id=run_id,
                        attempt_id=attempt_id,
                    )
                )
            unit.connection.execute(
                "UPDATE worker_lease SET state='REVOKED',released_at=? "
                "WHERE attempt_id=? AND state IN ('GRANTED','RENEWED','EXPIRED')",
                (now, attempt_id),
            )
            self.product.execution._stop_worker_for_attempt(unit, attempt_id, now)
            unit.commit()

    def recover_pending(self) -> dict[str, int]:
        """Recover durable Product Backtest publications before worker-loss fencing."""

        connection = self.product._connection(read_only=True)
        try:
            rows = connection.execute(
                "SELECT * FROM publication_intent WHERE intent_kind=? "
                "AND state NOT IN ('FINALIZED','FAILED') "
                "ORDER BY created_at,publication_intent_id",
                (_INTENT_KIND,),
            ).fetchall()
        finally:
            connection.close()
        summary = {
            "publication_intents_seen": len(rows),
            "publication_finalized": 0,
            "publication_failed": 0,
        }
        for row in rows:
            intent = dict(row)
            if str(intent["state"]) not in {"CATALOG_COMMITTED", "RECONCILING"}:
                self._fail_pending_intent(
                    intent, reason_code="PUBLICATION_RECOVERY_INCOMPLETE"
                )
                summary["publication_failed"] += 1
                continue
            try:
                self._recover_cataloged(intent)
            except Exception as error:
                try:
                    failure_reconciliation_artifact_id = (
                        self._publish_failure_reconciliation(intent, error)
                    )
                except Exception:
                    failure_reconciliation_artifact_id = None
                self._fail_pending_intent(
                    intent,
                    reason_code="RESIDUAL_VALIDATION_FAILED",
                    reconciliation_artifact_id=failure_reconciliation_artifact_id,
                )
                summary["publication_failed"] += 1
            else:
                summary["publication_finalized"] += 1
        return summary

    def finalize(
        self,
        *,
        project_id: str,
        handles: Any,
        request_id: str,
        strategy: Mapping[str, Any],
        spec: BacktestRunSpec,
        execution_inputs: ResearchExecutionInputs,
        result: BacktestRunResult,
        assumption_receipt: Mapping[str, Any],
        first_effective_session_date: str,
    ) -> FinalizedBacktestPublication:
        receipt = dict(assumption_receipt)
        expected_receipt_keys = {
            "schema_version",
            "research_backtest_request_id",
            "assumption_mode",
            "market_state_derivation",
            "corporate_actions",
            "snapshot_id",
            "snapshot_sha256",
            "research_execution_profile_id",
            "truth",
            "admission",
        }
        expected_derivation = (
            "VERIFIED_CANONICAL_EXPLICIT_STATUS_FIELDS"
            if execution_inputs.profile.assumption_mode == "STRICT_FAIL_CLOSED"
            else "VERIFIED_BAR_PRESENT_AND_VOLUME_POSITIVE"
        )
        expected_corporate_actions = (
            "ADMITTED_PRE_ALPHA_ACTIONS_IN_RESOLVED_RANGE"
            if any(session.corporate_actions for session in spec.sessions)
            else "NO_ADMITTED_ACTIONS_IN_RESOLVED_RANGE"
        )
        if (
            set(receipt) != expected_receipt_keys
            or receipt.get("schema_version")
            != "v3.research-assumption-receipt/1.0.0"
            or receipt.get("research_backtest_request_id") != request_id
            or receipt.get("assumption_mode")
            != execution_inputs.profile.assumption_mode
            or receipt.get("assumption_mode") not in _ASSUMPTION_MODES
            or receipt.get("market_state_derivation") != expected_derivation
            or receipt.get("corporate_actions")
            != expected_corporate_actions
            or receipt.get("snapshot_id")
            != execution_inputs.market_data_source_id
            or receipt.get("snapshot_sha256")
            != execution_inputs.market_data_content_sha256
            or receipt.get("research_execution_profile_id")
            != execution_inputs.profile.profile_id
            or receipt.get("truth") != "NOT_FORMAL"
            or receipt.get("admission") != "PRE_ALPHA"
        ):
            raise TruthPreconditionFailedError(
                "AssumptionReceipt does not match verified execution inputs"
            )
        result_id = mint_v3_id("res_")
        publication_intent_id = mint_v3_id("pub_")
        now = wire_time(datetime.now(timezone.utc))
        analytics = DeterministicResultAnalyticsEngine().analyze_product_v1_1(
            result,
            SourceResultBinding(result.result_id, result.content_sha256),
            ResultAnalyticsPolicyVersion.a_share_daily_research_v0(),
        )
        expected_outputs = {
            "request_id": request_id,
            "result_id": result_id,
            "roles": [
                BACKTEST_RUN_SPEC_ROLE,
                EXECUTION_INPUTS_ROLE,
                BACKTEST_RUN_RESULT_ROLE,
                LEDGER_MANIFEST_ROLE,
                ASSUMPTION_RECEIPT_ROLE,
                ANALYTICS_ROLE,
                SUMMARY_EXPORT_ROLE,
                ORDERS_EXPORT_ROLE,
                FILLS_EXPORT_ROLE,
                LINEAGE_ROLE,
                RECONCILIATION_ROLE,
                READ_MODEL_ROLE,
            ],
        }
        self._fault("BEFORE_INTENT_COMMIT")
        with self.product.task_persistence.begin() as unit:
            unit.connection.execute(
                """
                INSERT INTO publication_intent(
                  publication_intent_id,project_id,task_id,run_id,attempt_id,
                  intent_kind,state,expected_outputs_json,staged_manifest_json,
                  created_at,updated_at,state_version
                ) VALUES(?,?,?,?,?,?, 'STAGED', ?,NULL,?,?,0)
                """,
                (
                    publication_intent_id,
                    project_id,
                    handles.task.task_id,
                    handles.run.run_id,
                    handles.attempt.attempt_id,
                    _INTENT_KIND,
                    json.dumps(expected_outputs, separators=(",", ":"), sort_keys=True),
                    now,
                    now,
                ),
            )
            unit.commit()
        self._fault("AFTER_INTENT_STAGED")

        run_spec_payload = canonical_json_bytes(spec.to_wire())
        execution_payload = canonical_json_bytes(execution_inputs.to_wire())
        result_payload = canonical_json_bytes(result.to_wire())
        manifest_payload = canonical_json_bytes(self._ledger_manifest(result))
        assumption_payload = canonical_json_bytes(receipt)
        result_wire = result.to_wire()
        analytics_wire = analytics.to_wire()
        analytics_payload = canonical_json_bytes(analytics_wire)
        summary_export_payload = canonical_json_bytes(
            self._summary_export_wire(
                result_wire, analytics_wire, engine_version=spec.engine_version
            )
        )
        orders_export_payload = self._csv_export_wire(
            result=result_wire, kind="orders"
        )
        fills_export_payload = self._csv_export_wire(
            result=result_wire, kind="fills"
        )
        published_primary = self.product.execution._publish_artifact_batch(
            payloads=(
                ("prv_product_run_spec_" + request_id, run_spec_payload, BACKTEST_RUN_SPEC_ROLE, spec.schema_version),
                ("prv_product_execution_inputs_" + request_id, execution_payload, EXECUTION_INPUTS_ROLE, "v3.research-execution-inputs/1.0.0"),
                ("prv_product_result_" + result.result_id, result_payload, BACKTEST_RUN_RESULT_ROLE, result.schema_version),
                ("prv_product_ledger_" + result.result_id, manifest_payload, LEDGER_MANIFEST_ROLE, "v3.ledger-manifest/1.1.0-research"),
                ("prv_product_assumptions_" + request_id, assumption_payload, ASSUMPTION_RECEIPT_ROLE, "v3.research-assumption-receipt/1.0.0"),
                ("prv_product_analytics_" + analytics.analytics_id, analytics_payload, ANALYTICS_ROLE, analytics.schema_version),
                ("prv_product_summary_export_" + result.result_id, summary_export_payload, SUMMARY_EXPORT_ROLE, "v3.product-result-summary-export/1.0.0"),
                ("prv_product_orders_export_" + result.result_id, orders_export_payload, ORDERS_EXPORT_ROLE, "v3.product-result-orders-export/1.0.0", "text/csv"),
                ("prv_product_fills_export_" + result.result_id, fills_export_payload, FILLS_EXPORT_ROLE, "v3.product-result-fills-export/1.0.0", "text/csv"),
            ),
            references=(
                (handles.run.run_id, BACKTEST_RUN_SPEC_ROLE, 0),
                (handles.run.run_id, EXECUTION_INPUTS_ROLE, 1),
                (result_id, BACKTEST_RUN_RESULT_ROLE, 2),
                (result_id, LEDGER_MANIFEST_ROLE, 3),
                (result_id, ASSUMPTION_RECEIPT_ROLE, 4),
                (result_id, ANALYTICS_ROLE, 5),
                (result_id, SUMMARY_EXPORT_ROLE, 6),
                (result_id, ORDERS_EXPORT_ROLE, 7),
                (result_id, FILLS_EXPORT_ROLE, 8),
            ),
        )
        (
            run_spec_artifact,
            execution_artifact,
            result_artifact,
            ledger_artifact,
            assumption_artifact,
            analytics_artifact,
            summary_export_artifact,
            orders_export_artifact,
            fills_export_artifact,
        ) = (item.descriptor for item in published_primary)
        from .product_data import ProductDataService

        data = ProductDataService(self.product).get_local_dataset(
            project_id=project_id,
            project_context_revision_id=strategy["project_context_revision_id"],
            snapshot_id=strategy["snapshot_id"],
        )
        lineage_wire = self._lineage_wire(
            project_id=project_id,
            project_context_revision_id=strategy["project_context_revision_id"],
            data=data,
            strategy=strategy,
            run_id=handles.run.run_id,
            run_spec_artifact_id=run_spec_artifact.artifact_id,
            result_id=result_id,
            result=result,
            result_artifact_id=result_artifact.artifact_id,
            analytics_id=analytics.analytics_id,
            analytics_artifact_id=analytics_artifact.artifact_id,
        )
        lineage_publication = self.product.execution._publish_artifact_batch(
            payloads=((
                "prv_product_lineage_" + str(lineage_wire["result_lineage_id"]),
                canonical_json_bytes(lineage_wire),
                LINEAGE_ROLE,
                "v3.product-result-lineage/1.0.0",
            ),),
            references=((result_id, LINEAGE_ROLE, 0),),
        )[0]
        lineage_artifact = lineage_publication.descriptor
        published = (*published_primary, lineage_publication)
        self._fault("AFTER_INITIAL_ARTIFACTS_PUBLISHED")

        strategy_version_id = str(strategy["strategy_version_id"])
        catalog_run_spec_id = mint_v3_id("brs_")
        run_spec_projection = {
            "schema_version": "v3.product-research-backtest-run-spec-projection/1.0.0",
            "canonical_run_spec_id": spec.run_spec_id,
            "canonical_run_spec_artifact_id": run_spec_artifact.artifact_id,
            "research_execution_inputs_artifact_id": execution_artifact.artifact_id,
        }
        lineage_hash = canonical_sha256(
            {
                "project_id": project_id,
                "run_id": handles.run.run_id,
                "request_id": request_id,
                "run_spec_id": spec.run_spec_id,
                "result_id": result.result_id,
                "result_artifact_id": result_artifact.artifact_id,
                "ledger_manifest_artifact_id": ledger_artifact.artifact_id,
                "analytics_id": analytics.analytics_id,
                "analytics_artifact_id": analytics_artifact.artifact_id,
                "result_lineage_id": lineage_wire["result_lineage_id"],
                "lineage_artifact_id": lineage_artifact.artifact_id,
            }
        )
        with self.product.task_persistence.begin() as unit:
            unit.connection.execute(
                """
                INSERT OR IGNORE INTO backtest_run_spec(
                  backtest_run_spec_id,experiment_id,strategy_version_id,
                  dataset_version_id,universe_version_id,portfolio_version_id,
                  risk_model_version_id,optimization_solution_id,snapshot_id,
                  execution_adapter_version_id,rules_profile_id,fee_profile_id,
                  environment_profile_id,run_spec_json,canonical_hash,published_at
                ) VALUES(?,NULL,?,NULL,?,NULL,NULL,NULL,?,?,?,?,?,?,?,?)
                """,
                (
                    catalog_run_spec_id,
                    strategy_version_id,
                    str(strategy["universe_version_id"]),
                    str(strategy["snapshot_id"]),
                    spec.engine_version,
                    spec.rule_profile.profile_id,
                    spec.cost_policy.policy_id,
                    spec.runtime_identity.environment_fingerprint,
                    json.dumps(run_spec_projection, separators=(",", ":"), sort_keys=True),
                    spec.content_sha256,
                    now,
                ),
            )
            persisted = unit.connection.execute(
                "SELECT backtest_run_spec_id FROM backtest_run_spec WHERE canonical_hash=?",
                (spec.content_sha256,),
            ).fetchone()
            if persisted is None:
                raise TruthPreconditionFailedError("BacktestRunSpec catalog publication failed")
            unit.registry.result.publish_result(
                {
                    "result_id": result_id,
                    "project_id": project_id,
                    "backtest_run_id": handles.run.run_id,
                    "ledger_manifest_artifact_id": ledger_artifact.artifact_id,
                    "reconciliation_artifact_id": None,
                    "state": "PENDING_RECONCILIATION",
                    "invalid_reason_code": None,
                    "lineage_hash": lineage_hash,
                    "created_at": now,
                }
            )
            updated = unit.connection.execute(
                """
                UPDATE publication_intent
                SET state='CATALOG_COMMITTED',staged_manifest_json=?,updated_at=?,
                    state_version=state_version+1
                WHERE publication_intent_id=? AND state='STAGED'
                """,
                (
                    json.dumps(
                        {
                            "artifact_ids": [item.descriptor.artifact_id for item in published],
                            "canonical_run_spec_id": spec.run_spec_id,
                            "catalog_run_spec_id": str(persisted[0]),
                            "project_context_revision_id": str(strategy["project_context_revision_id"]),
                            "research_strategy_spec_id": str(strategy["research_strategy_spec_id"]),
                            "snapshot_id": str(strategy["snapshot_id"]),
                            "universe_version_id": str(strategy["universe_version_id"]),
                            "result_id": result_id,
                            "backtest_result_id": result.result_id,
                            "run_id": handles.run.run_id,
                            "engine_version": spec.engine_version,
                            "first_effective_session_date": first_effective_session_date,
                            "assumption_mode": execution_inputs.profile.assumption_mode,
                            "run_spec_artifact_id": run_spec_artifact.artifact_id,
                            "research_execution_inputs_artifact_id": execution_artifact.artifact_id,
                            "result_artifact_id": result_artifact.artifact_id,
                            "ledger_manifest_artifact_id": ledger_artifact.artifact_id,
                            "assumption_receipt_artifact_id": assumption_artifact.artifact_id,
                            "analytics_id": analytics.analytics_id,
                            "analytics_artifact_id": analytics_artifact.artifact_id,
                            "analytics_engine_version": analytics.engine_version,
                            "summary_export_artifact_id": summary_export_artifact.artifact_id,
                            "orders_export_artifact_id": orders_export_artifact.artifact_id,
                            "fills_export_artifact_id": fills_export_artifact.artifact_id,
                            "result_lineage_id": lineage_wire["result_lineage_id"],
                            "lineage_artifact_id": lineage_artifact.artifact_id,
                        },
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    now,
                    publication_intent_id,
                ),
            )
            if updated.rowcount != 1:
                raise TruthPreconditionFailedError("PublicationIntent state drifted")
            unit.commit()
        self._fault("AFTER_CATALOG_COMMITTED")

        self.product.execution._record_progress(
            handles.task,
            handles.run,
            handles.attempt,
            phase="RECONCILING",
            completed_units=3,
            total_units=4,
            work_unit="RESULT_RECONCILIATION",
        )

        reconciliation = self._reconcile(
            spec=spec,
            result=result,
            result_payload=result_payload,
            published_payload=self.product.read_verified_bytes(result_artifact.artifact_id),
        )
        reconciliation_payload = canonical_json_bytes(reconciliation)
        first_fill = result.fills[0].session_date.isoformat() if result.fills else None
        read_model = {
            "schema_version": "v3.product-research-backtest-read-model/1.0.0",
            "maturity": "PRODUCT_CONNECTED",
            "truth": "NOT_FORMAL",
            "admission": "PRE_ALPHA",
            "project_id": project_id,
            "project_context_revision_id": str(
                strategy["project_context_revision_id"]
            ),
            "research_backtest_request_id": request_id,
            "research_strategy_spec_id": str(strategy["research_strategy_spec_id"]),
            "snapshot_id": str(strategy["snapshot_id"]),
            "universe_version_id": str(strategy["universe_version_id"]),
            "run_id": handles.run.run_id,
            "run_spec_id": spec.run_spec_id,
            "run_spec_artifact_id": run_spec_artifact.artifact_id,
            "research_execution_inputs_artifact_id": execution_artifact.artifact_id,
            "result_id": result_id,
            "backtest_result_id": result.result_id,
            "result_artifact_id": result_artifact.artifact_id,
            "ledger_manifest_artifact_id": ledger_artifact.artifact_id,
            "assumption_receipt_artifact_id": assumption_artifact.artifact_id,
            "analytics_id": analytics.analytics_id,
            "analytics_artifact_id": analytics_artifact.artifact_id,
            "analytics_engine_version": analytics.engine_version,
            "summary_export_artifact_id": summary_export_artifact.artifact_id,
            "orders_export_artifact_id": orders_export_artifact.artifact_id,
            "fills_export_artifact_id": fills_export_artifact.artifact_id,
            "result_lineage_id": lineage_wire["result_lineage_id"],
            "lineage_artifact_id": lineage_artifact.artifact_id,
            "result_state": "VALID",
            "engine_version": spec.engine_version,
            "order_count": len(result.orders),
            "fill_count": len(result.fills),
            "diagnostic_count": len(result.diagnostics),
            "first_fill_session_date": first_fill,
            "first_effective_session_date": first_effective_session_date,
            "assumption_mode": execution_inputs.profile.assumption_mode,
            "publication_intent_id": publication_intent_id,
        }
        secondary = self.product.execution._publish_artifact_batch(
            payloads=(
                ("prv_product_reconciliation_" + result_id, reconciliation_payload, RECONCILIATION_ROLE, "v3.product-result-reconciliation/1.0.0"),
                ("prv_product_backtest_read_model_" + request_id, canonical_json_bytes(read_model), READ_MODEL_ROLE, "v3.product-research-backtest-read-model/1.0.0"),
            ),
            references=(
                (result_id, RECONCILIATION_ROLE, 0),
                (project_id, READ_MODEL_ROLE, 1),
            ),
        )
        reconciliation_artifact, read_model_artifact = (
            item.descriptor for item in secondary
        )
        self._fault("AFTER_RECONCILIATION_PUBLISHED")

        self._fault("BEFORE_FINALIZE_TRANSACTION")

        self._finalize_catalog(
            handles=handles,
            result_id=result_id,
            publication_intent_id=publication_intent_id,
            reconciliation_artifact_id=reconciliation_artifact.artifact_id,
            outputs=(
                (BACKTEST_RUN_SPEC_ROLE, 0, run_spec_artifact.artifact_id),
                (EXECUTION_INPUTS_ROLE, 0, execution_artifact.artifact_id),
                (BACKTEST_RUN_RESULT_ROLE, 0, result_artifact.artifact_id),
                (LEDGER_MANIFEST_ROLE, 0, ledger_artifact.artifact_id),
                (ASSUMPTION_RECEIPT_ROLE, 0, assumption_artifact.artifact_id),
                (ANALYTICS_ROLE, 0, analytics_artifact.artifact_id),
                (SUMMARY_EXPORT_ROLE, 0, summary_export_artifact.artifact_id),
                (ORDERS_EXPORT_ROLE, 0, orders_export_artifact.artifact_id),
                (FILLS_EXPORT_ROLE, 0, fills_export_artifact.artifact_id),
                (LINEAGE_ROLE, 0, lineage_artifact.artifact_id),
                (RECONCILIATION_ROLE, 0, reconciliation_artifact.artifact_id),
                (READ_MODEL_ROLE, 0, read_model_artifact.artifact_id),
            ),
        )
        return FinalizedBacktestPublication(
            result_id, publication_intent_id, dict(read_model)
        )

    def _finalize_catalog(
        self,
        *,
        handles: Any,
        result_id: str,
        publication_intent_id: str,
        reconciliation_artifact_id: str,
        outputs: tuple[tuple[str, int, str], ...],
    ) -> None:
        finalized_at = wire_time(datetime.now(timezone.utc))
        with self.product.task_persistence.begin() as unit:
            current_task = unit.require_task(handles.task.task_id)
            current_run = unit.require_run(handles.run.run_id)
            current_attempt = unit.require_attempt(handles.attempt.attempt_id)
            changed = unit.connection.execute(
                """
                UPDATE publication_intent
                SET state='RECONCILING',updated_at=?,state_version=state_version+1
                WHERE publication_intent_id=? AND state='CATALOG_COMMITTED'
                """,
                (finalized_at, publication_intent_id),
            )
            if changed.rowcount != 1:
                raise TruthPreconditionFailedError("PublicationIntent is not reconcilable")
            unit.registry.result.record_reconciliation(
                result_id,
                reconciliation_artifact_id=reconciliation_artifact_id,
                reconciliation_passed=True,
                state="VALID",
                finalized_at=finalized_at,
            )
            self._fault("DURING_FINALIZE_TRANSACTION")
            for role, ordinal, artifact_id in outputs:
                unit.connection.execute(
                    """
                    INSERT INTO task_output(task_id,output_role,ordinal,artifact_id,created_at)
                    VALUES(?,?,?,?,?)
                    """,
                    (current_task.task_id, role, ordinal, artifact_id, finalized_at),
                )
            current_attempt.state = transition_attempt(
                current_attempt.state, "ATTEMPT_SUCCEEDED"
            )
            if current_attempt.state is not AttemptState.SUCCEEDED:
                raise TruthPreconditionFailedError("Attempt did not reach SUCCEEDED")
            unit.save_attempt(
                current_attempt, expected_version=current_attempt.state_version
            )
            if current_run.state is not RunState.TERMINAL:
                current_run.state = transition_run(
                    current_run.state,
                    "TASK_TERMINAL_NO_ACTIVE_ATTEMPT",
                    no_active_attempt=True,
                )
                unit.save_run(
                    current_run, expected_version=current_run.state_version
                )
            elif current_attempt.ordinal <= 1:
                raise TruthPreconditionFailedError(
                    "only a retry Attempt may finalize against a terminal immutable Run"
                )
            current_task.state = transition_task(
                current_task.state,
                "ALL_REQUIRED_ARTIFACTS_PUBLISHED",
                TaskTransitionContext(
                    successful_attempt=True, publication_committed=True
                ),
            )
            unit.save_task(current_task, expected_version=current_task.state_version)
            finalized = unit.connection.execute(
                """
                UPDATE publication_intent
                SET state='FINALIZED',updated_at=?,finalized_at=?,state_version=state_version+1
                WHERE publication_intent_id=? AND state='RECONCILING'
                """,
                (finalized_at, finalized_at, publication_intent_id),
            )
            if finalized.rowcount != 1:
                raise TruthPreconditionFailedError("PublicationIntent did not finalize")
            unit.append_event(
                PendingTaskEvent(
                    event_id=mint_v3_id("tev_"),
                    event_version=_TASK_EVENT_VERSION,
                    project_id=current_task.project_id,
                    task_id=current_task.task_id,
                    event_type="TASK_SUCCEEDED",
                    occurred_at=datetime.now(timezone.utc),
                    payload={"result_id": result_id, "result_state": "VALID"},
                    run_id=current_run.run_id,
                    attempt_id=current_attempt.attempt_id,
                )
            )
            unit.connection.execute(
                """
                UPDATE worker_lease SET state='RELEASED', released_at=?
                WHERE attempt_id=? AND state IN ('GRANTED','RENEWED')
                """,
                (finalized_at, current_attempt.attempt_id),
            )
            self.product.execution._stop_worker_for_attempt(
                unit, current_attempt.attempt_id, finalized_at
            )
            unit.commit()


__all__ = [
    "ASSUMPTION_RECEIPT_ROLE",
    "EXECUTION_INPUTS_ROLE",
    "FinalizedBacktestPublication",
    "ProductBacktestPublication",
    "READ_MODEL_ROLE",
    "RECONCILIATION_ROLE",
]
