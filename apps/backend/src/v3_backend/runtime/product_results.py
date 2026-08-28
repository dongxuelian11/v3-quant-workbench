"""Bounded ResultService projections over the Product Backtest publication owner.

The Product Backtest saga remains the only owner that creates and finalizes a
Result.  These handlers create durable verification Tasks, re-resolve the
already-finalized publication, and reuse its exact reconciliation/analytics
Artifacts.  They never create a second Result or PublicationIntent.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from v3_backend.errors.exceptions import (
    CapabilityUnavailableError,
    ConflictError,
    InvalidArgumentError,
    NotFoundError,
    TruthPreconditionFailedError,
)
from v3_backend.provenance.canonical_hash import canonical_sha256

from .product_publication import (
    ANALYTICS_ROLE,
    LINEAGE_ROLE,
    RECONCILIATION_ROLE,
)
from .product_runtime import (
    ProductRuntime,
    _accept_outcome_json,
    _canonical_request_hash,
    classify_execution_error,
)


RESULT_RECONCILE_OPERATION = "ResultService.v1.reconcileLedger"
RESULT_FINALIZE_OPERATION = "ResultService.v1.finalizeResult"
RESULT_RECONCILIATION_PROFILE = "v3.product-result-reconciliation/1.0.0"
_CONTEXT_SCHEMA = "v3.product-result-verification-context/1.0.0"
_MAX_CONTROL_ARTIFACT_BYTES = 16 * 1024 * 1024
_RESULT_SECTIONS = frozenset(
    {
        "summary",
        "analytics",
        "orders",
        "fills",
        "positions",
        "diagnostics",
        "lineage",
    }
)


@dataclass(frozen=True, slots=True)
class ResultReconcileSubmission:
    project_id: str
    project_context_revision_id: str
    backtest_run_id: str
    ledger_manifest_artifact_id: str
    reconciliation_profile_id: str
    idempotency_key: str
    execution_deadline_at: str | None = None


@dataclass(frozen=True, slots=True)
class ResultFinalizeSubmission:
    project_id: str
    project_context_revision_id: str
    backtest_run_id: str
    reconciliation_artifact_id: str
    analytics_spec: Mapping[str, Any]
    idempotency_key: str
    execution_deadline_at: str | None = None


@dataclass(frozen=True, slots=True)
class _PreparedResultVerification:
    operation_id: str
    work_kind: str
    resource_class: str
    project_id: str
    project_context_revision_id: str
    backtest_run_id: str
    semantic: dict[str, Any]
    request_hash: str
    scope: str
    execution_deadline_at: str | None


@dataclass(frozen=True, slots=True)
class _ResultTaskHandles:
    task: Any
    run: Any
    attempt: Any


@dataclass(frozen=True, slots=True)
class _VerifiedPublication:
    result: dict[str, Any]
    intent: dict[str, Any]
    expected: dict[str, Any]
    staged: dict[str, Any]
    read_model: dict[str, Any]


class ProductResultService:
    """Read and verify V1.1 Result truth without minting another owner."""

    def __init__(self, product: ProductRuntime) -> None:
        self.product = product

    @staticmethod
    def _required_text(value: object, name: str) -> str:
        if not isinstance(value, str) or not value or value != value.strip():
            raise InvalidArgumentError(f"{name} must be non-empty text")
        return value

    def _verified_publication(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        backtest_run_id: str,
    ) -> _VerifiedPublication:
        self.product.require_project_context_ownership(
            project_id, project_context_revision_id
        )
        current = self.product.current_revision(project_id)
        if (
            str(current["project_context_revision_id"])
            != project_context_revision_id
        ):
            raise ConflictError(
                "Result verification requires the current project context revision"
            )
        connection = self.product._connection(read_only=True)
        try:
            result_rows = connection.execute(
                """
                SELECT * FROM result
                WHERE project_id=? AND backtest_run_id=?
                ORDER BY created_at,result_id
                """,
                (project_id, backtest_run_id),
            ).fetchall()
            intent_rows = connection.execute(
                """
                SELECT * FROM publication_intent
                WHERE project_id=? AND run_id=?
                ORDER BY created_at,publication_intent_id
                """,
                (project_id, backtest_run_id),
            ).fetchall()
        finally:
            connection.close()
        if len(result_rows) != 1:
            raise NotFoundError(
                "Result verification requires exactly one Product Result"
            )
        if len(intent_rows) != 1:
            raise TruthPreconditionFailedError(
                "Result verification requires exactly one Product publication intent"
            )
        result = dict(result_rows[0])
        intent = dict(intent_rows[0])
        if result.get("state") != "VALID" or intent.get("state") != "FINALIZED":
            raise TruthPreconditionFailedError(
                "Result verification requires FINALIZED publication and VALID Result"
            )
        try:
            expected = json.loads(str(intent["expected_outputs_json"]))
            staged = json.loads(str(intent["staged_manifest_json"]))
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise TruthPreconditionFailedError(
                "Product publication metadata is invalid"
            ) from error
        if not isinstance(expected, dict) or not isinstance(staged, dict):
            raise TruthPreconditionFailedError(
                "Product publication metadata is invalid"
            )
        request_id = expected.get("request_id")
        if (
            not isinstance(request_id, str)
            or staged.get("result_id") != result.get("result_id")
            or staged.get("run_id") != backtest_run_id
            or staged.get("project_context_revision_id")
            != project_context_revision_id
            or staged.get("ledger_manifest_artifact_id")
            != result.get("ledger_manifest_artifact_id")
        ):
            raise TruthPreconditionFailedError(
                "Product publication owner bindings drifted"
            )
        read_model = self.product.backtest.get_backtest(
            project_id=project_id,
            project_context_revision_id=project_context_revision_id,
            research_backtest_request_id=request_id,
        )
        if (
            read_model.get("result_id") != result.get("result_id")
            or read_model.get("run_id") != backtest_run_id
            or read_model.get("result_state") != "VALID"
            or read_model.get("publication_intent_id")
            != intent.get("publication_intent_id")
        ):
            raise TruthPreconditionFailedError(
                "Product Result readback does not match its finality owner"
            )
        reconciliation_artifact_id = result.get("reconciliation_artifact_id")
        if not isinstance(reconciliation_artifact_id, str):
            raise TruthPreconditionFailedError(
                "VALID Result lacks reconciliation evidence"
            )
        self.product.require_project_reachable_artifact(
            project_id, reconciliation_artifact_id
        )
        return _VerifiedPublication(result, intent, expected, staged, read_model)

    def _prepare(
        self,
        *,
        operation_id: str,
        work_kind: str,
        resource_class: str,
        project_id: str,
        project_context_revision_id: str,
        backtest_run_id: str,
        idempotency_key: str,
        semantic_tail: Mapping[str, Any],
        execution_deadline_at: str | None,
    ) -> _PreparedResultVerification:
        for value, name in (
            (project_id, "project_id"),
            (project_context_revision_id, "project_context_revision_id"),
            (backtest_run_id, "backtest_run_id"),
            (idempotency_key, "idempotency_key"),
        ):
            self._required_text(value, name)
        semantic = {
            "project_id": project_id,
            "project_context_revision_id": project_context_revision_id,
            "backtest_run_id": backtest_run_id,
            **dict(semantic_tail),
        }
        request_hash = _canonical_request_hash(operation_id, semantic)
        return _PreparedResultVerification(
            operation_id=operation_id,
            work_kind=work_kind,
            resource_class=resource_class,
            project_id=project_id,
            project_context_revision_id=project_context_revision_id,
            backtest_run_id=backtest_run_id,
            semantic=semantic,
            request_hash=request_hash,
            scope=self.product.idempotency.scope_key(
                operation_id, project_id, idempotency_key
            ),
            execution_deadline_at=execution_deadline_at,
        )

    def _accept_request(
        self, request: _PreparedResultVerification
    ) -> _ResultTaskHandles:
        context_artifact_id = self.product.execution._persist_context_artifact(
            {
                "schema_version": _CONTEXT_SCHEMA,
                "context_kind": request.work_kind,
                **request.semantic,
                "truth": "NOT_FORMAL",
                "admission": "PRE_ALPHA",
                "execution_state": "QUEUED_FOR_EXISTING_RESULT_VERIFICATION",
            },
            provenance="prv_product_result_verify_" + request.request_hash,
            deadline_at=request.execution_deadline_at,
        )
        return _ResultTaskHandles(
            *self.product.execution._create_task(
                operation_id=request.operation_id,
                project_id=request.project_id,
                project_context_revision_id=request.project_context_revision_id,
                normalized_input_hash=canonical_sha256(request.semantic),
                context_artifact_id=context_artifact_id,
                canonical_input={
                    "semantic_request": dict(request.semantic),
                    "request_hash": request.request_hash,
                    "scope": request.scope,
                },
                idempotency=(
                    request.scope,
                    request.request_hash,
                    _accept_outcome_json,
                ),
                execution_deadline_at=request.execution_deadline_at,
                inline_worker=False,
                service_contract_version="1.0.0",
            )
        )

    def _submit(self, request: _PreparedResultVerification) -> dict[str, Any]:
        workers = getattr(self.product, "product_workers", None)
        if workers is None:
            raise CapabilityUnavailableError(
                "isolated Product worker is unavailable for Result verification",
                details={"reason_code": "PRODUCT_WORKER_NOT_AVAILABLE"},
            )
        reservation = workers.reserve_capacity()
        handles: _ResultTaskHandles | None = None
        try:
            handles = self._accept_request(request)
            workers.start(
                request,
                handles,
                reservation_token=reservation,
                operation_id=request.operation_id,
                work_kind=request.work_kind,
                resource_class=request.resource_class,
            )
        except Exception as error:
            workers.release_capacity(reservation)
            if handles is not None and not getattr(
                error, "defer_task_finalization", False
            ):
                self.product.execution._finish_failure(
                    handles.task,
                    handles.run,
                    handles.attempt,
                    error=error,
                    category=classify_execution_error(error),
                )
            raise
        return self._accepted_outcome(
            request,
            task_id=handles.task.task_id,
            run_id=handles.run.run_id,
            operation_receipt_id=self.product.execution.operation_receipt_id_for_task(
                handles.task.task_id
            ),
            event_cursor=self.product.latest_event_sequence(request.project_id),
        )

    def _existing_outcome(
        self, request: _PreparedResultVerification
    ) -> dict[str, Any] | None:
        existing = self.product.idempotency.lookup(
            self.product, request.scope, request.request_hash
        )
        if existing is None:
            return None
        task_id = str(existing["task_id"])
        return self._accepted_outcome(
            request,
            task_id=task_id,
            run_id=str(existing["run_id"]),
            operation_receipt_id=self.product.execution.operation_receipt_id_for_task(task_id),
        )

    @staticmethod
    def _accepted_outcome(
        request: _PreparedResultVerification,
        *,
        task_id: str,
        run_id: str,
        operation_receipt_id: str | None = None,
        event_cursor: int | None = None,
    ) -> dict[str, Any]:
        outcome: dict[str, Any] = {
            "task_id": task_id,
            "run_id": run_id,
            "accepted_state": "QUEUED",
        }
        if operation_receipt_id is not None:
            outcome["operation_receipt_id"] = operation_receipt_id
        if event_cursor is not None:
            outcome["event_cursor"] = event_cursor
        return outcome

    def submit_reconcile(
        self, submission: ResultReconcileSubmission
    ) -> dict[str, Any]:
        request = self._prepare(
            operation_id=RESULT_RECONCILE_OPERATION,
            work_kind="RESULT_RECONCILE_VERIFY",
            resource_class="PRODUCT_RESULT_RECONCILE_CPU",
            project_id=submission.project_id,
            project_context_revision_id=submission.project_context_revision_id,
            backtest_run_id=submission.backtest_run_id,
            idempotency_key=submission.idempotency_key,
            semantic_tail={
                "ledger_manifest_artifact_id": submission.ledger_manifest_artifact_id,
                "reconciliation_profile_id": submission.reconciliation_profile_id,
            },
            execution_deadline_at=submission.execution_deadline_at,
        )
        existing = self._existing_outcome(request)
        if existing is not None:
            return existing
        if submission.reconciliation_profile_id != RESULT_RECONCILIATION_PROFILE:
            raise CapabilityUnavailableError(
                "Result reconciliation profile is not product-admitted",
                details={"reason_code": "RESULT_RECONCILIATION_PROFILE_NOT_AVAILABLE"},
            )
        verified = self._verified_publication(
            project_id=submission.project_id,
            project_context_revision_id=submission.project_context_revision_id,
            backtest_run_id=submission.backtest_run_id,
        )
        if (
            verified.result.get("ledger_manifest_artifact_id")
            != submission.ledger_manifest_artifact_id
        ):
            raise TruthPreconditionFailedError(
                "ledger manifest does not match the finalized Product Result"
            )
        return self._submit(request)

    def submit_finalize(
        self, submission: ResultFinalizeSubmission
    ) -> dict[str, Any]:
        analytics_spec = dict(submission.analytics_spec)
        request = self._prepare(
            operation_id=RESULT_FINALIZE_OPERATION,
            work_kind="RESULT_FINALIZE_VERIFY",
            resource_class="PRODUCT_RESULT_FINALIZE_CPU",
            project_id=submission.project_id,
            project_context_revision_id=submission.project_context_revision_id,
            backtest_run_id=submission.backtest_run_id,
            idempotency_key=submission.idempotency_key,
            semantic_tail={
                "reconciliation_artifact_id": submission.reconciliation_artifact_id,
                "analytics_spec": analytics_spec,
            },
            execution_deadline_at=submission.execution_deadline_at,
        )
        existing = self._existing_outcome(request)
        if existing is not None:
            return existing
        if set(analytics_spec) != {
            "analytics_policy_id",
            "analytics_policy_content_sha256",
        } or any(not isinstance(value, str) or not value for value in analytics_spec.values()):
            raise InvalidArgumentError(
                "analytics_spec must bind the exact Product analytics policy ID/hash"
            )
        verified = self._verified_publication(
            project_id=submission.project_id,
            project_context_revision_id=submission.project_context_revision_id,
            backtest_run_id=submission.backtest_run_id,
        )
        if (
            verified.result.get("reconciliation_artifact_id")
            != submission.reconciliation_artifact_id
        ):
            raise TruthPreconditionFailedError(
                "reconciliation Artifact does not match the finalized Product Result"
            )
        analytics = self._read_json_artifact(
            submission.project_id,
            str(verified.read_model["analytics_artifact_id"]),
            "Product Result Analytics",
        )
        core = analytics.get("core_analytics")
        policy = core.get("analytics_policy") if isinstance(core, dict) else None
        if not isinstance(policy, dict) or analytics_spec != {
            "analytics_policy_id": policy.get("policy_id"),
            "analytics_policy_content_sha256": policy.get("content_sha256"),
        }:
            raise TruthPreconditionFailedError(
                "analytics_spec does not match the finalized Product analytics owner"
            )
        return self._submit(request)

    def execute_reconcile_accepted(
        self,
        request: _PreparedResultVerification,
        handles: _ResultTaskHandles,
    ) -> None:
        self._execute_verification(
            request,
            handles,
            output_role=RECONCILIATION_ROLE,
            output_artifact_key="reconciliation_artifact_id",
        )

    def execute_finalize_accepted(
        self,
        request: _PreparedResultVerification,
        handles: _ResultTaskHandles,
    ) -> None:
        self._execute_verification(
            request,
            handles,
            output_role=ANALYTICS_ROLE,
            output_artifact_key="analytics_artifact_id",
        )

    def _execute_verification(
        self,
        request: _PreparedResultVerification,
        handles: _ResultTaskHandles,
        *,
        output_role: str,
        output_artifact_key: str,
    ) -> None:
        try:
            verified = self._verified_publication(
                project_id=request.project_id,
                project_context_revision_id=request.project_context_revision_id,
                backtest_run_id=request.backtest_run_id,
            )
            self._verify_queued_request(request, verified)
            if output_artifact_key == "reconciliation_artifact_id":
                artifact_id = str(verified.result[output_artifact_key])
            else:
                artifact_id = str(verified.read_model[output_artifact_key])
            self.product.require_project_reachable_artifact(
                request.project_id, artifact_id
            )
            self.product.execution._finish_success(
                handles.task,
                handles.run,
                handles.attempt,
                outputs={
                    "verified_result_id": str(verified.result["result_id"]),
                    "verified_source_run_id": request.backtest_run_id,
                    "reused_artifact_id": artifact_id,
                },
                artifact_outputs=((output_role, 0, artifact_id),),
            )
        except Exception as error:
            self.product.execution._finish_failure(
                handles.task,
                handles.run,
                handles.attempt,
                error=error,
                category=classify_execution_error(error),
            )
            raise

    def _verify_queued_request(
        self,
        request: _PreparedResultVerification,
        verified: _VerifiedPublication,
    ) -> None:
        common = {
            "project_id": request.project_id,
            "project_context_revision_id": request.project_context_revision_id,
            "backtest_run_id": request.backtest_run_id,
        }
        if request.operation_id == RESULT_RECONCILE_OPERATION:
            expected = {
                **common,
                "ledger_manifest_artifact_id": verified.result.get(
                    "ledger_manifest_artifact_id"
                ),
                "reconciliation_profile_id": RESULT_RECONCILIATION_PROFILE,
            }
        elif request.operation_id == RESULT_FINALIZE_OPERATION:
            analytics = self._read_json_artifact(
                request.project_id,
                str(verified.read_model["analytics_artifact_id"]),
                "Product Result Analytics",
            )
            core = analytics.get("core_analytics")
            policy = core.get("analytics_policy") if isinstance(core, dict) else None
            if not isinstance(policy, dict):
                raise TruthPreconditionFailedError(
                    "Product Result analytics policy binding is absent"
                )
            expected = {
                **common,
                "reconciliation_artifact_id": verified.result.get(
                    "reconciliation_artifact_id"
                ),
                "analytics_spec": {
                    "analytics_policy_id": policy.get("policy_id"),
                    "analytics_policy_content_sha256": policy.get(
                        "content_sha256"
                    ),
                },
            }
        else:
            raise TruthPreconditionFailedError(
                "queued Result verification operation is not admitted"
            )
        if request.semantic != expected:
            raise TruthPreconditionFailedError(
                "queued Result verification inputs drifted from canonical owners"
            )

    def _read_json_artifact(
        self, project_id: str, artifact_id: str, label: str
    ) -> dict[str, Any]:
        descriptor = self.product.require_project_reachable_artifact(
            project_id, artifact_id
        )
        if int(descriptor["byte_size"]) > _MAX_CONTROL_ARTIFACT_BYTES:
            raise TruthPreconditionFailedError(f"{label} exceeds its control bound")
        try:
            value = json.loads(
                self.product.read_verified_bytes(artifact_id).decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError, OSError, ValueError) as error:
            raise TruthPreconditionFailedError(f"{label} bytes are invalid") from error
        if not isinstance(value, dict):
            raise TruthPreconditionFailedError(f"{label} payload is not an object")
        return value

    @staticmethod
    def _stream_ref(
        descriptor: Mapping[str, Any], *, json_pointer: str
    ) -> dict[str, Any]:
        return {
            "artifact_id": str(descriptor["artifact_id"]),
            "sha256": str(descriptor["sha256"]),
            "byte_size": int(descriptor["byte_size"]),
            "media_type": str(descriptor["media_type"]),
            "semantic_role": str(descriptor["semantic_role"]),
            "json_pointer": json_pointer,
        }

    @staticmethod
    def _stream_page_metadata(page: Mapping[str, Any]) -> dict[str, Any]:
        if any(key not in {"cursor", "limit"} for key in page):
            raise InvalidArgumentError("Result page must use cursor/limit only")
        cursor = page.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise InvalidArgumentError("Result page cursor must be text or null")
        if cursor:
            raise CapabilityUnavailableError(
                "row-cursor pagination is not available for Result Artifact streams",
                details={"reason_code": "RESULT_ROW_CURSOR_NOT_AVAILABLE"},
            )
        limit = page.get("limit")
        if limit is not None and (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise InvalidArgumentError("Result page limit must be between 1 and 100")
        return {
            "delivery_mode": "FULL_ARTIFACT_STREAM",
            "row_pagination_applied": False,
            "requested_limit": limit,
            "cursor": None,
            "next_cursor": None,
        }

    def get_result(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        result_id: str,
        section: str,
        page: Mapping[str, Any],
    ) -> dict[str, Any]:
        if section not in _RESULT_SECTIONS:
            raise InvalidArgumentError("Result section is not admitted")
        if not isinstance(page, Mapping):
            raise InvalidArgumentError("Result page must be an object")
        page_metadata = self._stream_page_metadata(page)
        result = self.product.require_result(result_id)
        if str(result["project_id"]) != project_id:
            raise TruthPreconditionFailedError(
                "Result belongs to a different project"
            )
        verified = self._verified_publication(
            project_id=project_id,
            project_context_revision_id=project_context_revision_id,
            backtest_run_id=str(result["backtest_run_id"]),
        )
        if str(verified.result["result_id"]) != result_id:
            raise TruthPreconditionFailedError(
                "Result identity does not match the verified Product publication"
            )
        source = verified.read_model
        result_artifact_id = str(source["result_artifact_id"])
        analytics_artifact_id = str(source["analytics_artifact_id"])
        lineage_artifact_id = str(source["lineage_artifact_id"])
        result_descriptor = self.product.require_project_reachable_artifact(
            project_id, result_artifact_id
        )
        analytics_descriptor = self.product.require_project_reachable_artifact(
            project_id, analytics_artifact_id
        )
        lineage_descriptor = self.product.require_project_reachable_artifact(
            project_id, lineage_artifact_id
        )
        common: dict[str, Any] = {
            "read_model_version": "v3.product-result/1.1",
            "project_id": project_id,
            "project_context_revision_id": project_context_revision_id,
            "result_id": result_id,
            "source_run_id": str(result["backtest_run_id"]),
            "result_state": "VALID",
            "truth": "NOT_FORMAL",
            "admission": "PRE_ALPHA",
            "section": section,
        }
        if section == "summary":
            common.update(
                {
                    "backtest_result_id": source["backtest_result_id"],
                    "engine_version": source["engine_version"],
                    "order_count": source["order_count"],
                    "fill_count": source["fill_count"],
                    "diagnostic_count": source["diagnostic_count"],
                    "assumption_mode": source["assumption_mode"],
                    "result_artifact": self._stream_ref(
                        result_descriptor, json_pointer=""
                    ),
                    "analytics_artifact": self._stream_ref(
                        analytics_descriptor, json_pointer=""
                    ),
                    "lineage_artifact": self._stream_ref(
                        lineage_descriptor, json_pointer=""
                    ),
                }
            )
            return common
        if section == "analytics":
            analytics = self._read_json_artifact(
                project_id, analytics_artifact_id, "Product Result Analytics"
            )
            core = analytics.get("core_analytics")
            common.update(
                {
                    "analytics_id": analytics.get("analytics_id"),
                    "analytics_engine_version": analytics.get("engine_version"),
                    "metrics": core.get("metrics") if isinstance(core, dict) else None,
                    "supplemental_metrics": analytics.get("supplemental_metrics"),
                    "concentration": analytics.get("concentration"),
                    "table_summary": analytics.get("table_summary"),
                    "benchmark": core.get("benchmark") if isinstance(core, dict) else None,
                    "stream_ref": self._stream_ref(
                        analytics_descriptor, json_pointer=""
                    ),
                }
            )
            return common
        if section == "lineage":
            common.update(
                {
                    "result_lineage_id": source["result_lineage_id"],
                    "stream_ref": self._stream_ref(
                        lineage_descriptor, json_pointer=""
                    ),
                }
            )
            return common
        pointer = {
            "orders": "/orders",
            "fills": "/fills",
            "positions": "/holdings",
            "diagnostics": "/diagnostics",
        }[section]
        row_count = {
            "orders": int(source["order_count"]),
            "fills": int(source["fill_count"]),
            "diagnostics": int(source["diagnostic_count"]),
        }.get(section)
        if section == "positions":
            result_wire = self._read_json_artifact(
                project_id, result_artifact_id, "Product Backtest Result"
            )
            holdings = result_wire.get("holdings")
            if not isinstance(holdings, list):
                raise TruthPreconditionFailedError(
                    "Product Backtest positions are invalid"
                )
            row_count = len(holdings)
        common.update(
            {
                "row_count": row_count,
                "page": page_metadata,
                "stream_ref": self._stream_ref(
                    result_descriptor, json_pointer=pointer
                ),
            }
        )
        return common


__all__ = [
    "ProductResultService",
    "RESULT_FINALIZE_OPERATION",
    "RESULT_RECONCILE_OPERATION",
    "RESULT_RECONCILIATION_PROFILE",
    "ResultFinalizeSubmission",
    "ResultReconcileSubmission",
]
