"""Thin ASL facades over the B3 product runtime composition.

Each facade maps one frozen service contract onto durable product stores and
accepted canonical owners.  Facades never compute financial truth: every
numeric value they return originates from a canonical owner record or a
content-addressed artifact published by the canonical execution path.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from v3_backend.adapters.sqlite.connection import connect_catalog
from v3_backend.adapters.sqlite.repositories import SQLiteRepositoryRegistry
from v3_backend.adapters.sqlite.unit_of_work import SQLiteUnitOfWork
from v3_backend.domain.tasks.entities import TaskState
from v3_backend.domain.tasks.events import PendingTaskEvent
from v3_backend.domain.tasks.state_machine import (
    TaskTransitionContext,
    transition_attempt,
    transition_task,
)
from v3_backend.errors.exceptions import (
    ConflictError,
    IdempotencyConflictError,
    InvalidArgumentError,
    NotFoundError,
    TruthPreconditionFailedError,
)
from v3_backend.provenance.canonical_hash import canonical_sha256
from v3_backend.repositories.unit_of_work import TransactionMode

from .product_runtime import (
    ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
    BUILD_MANIFEST_ID,
    DEFAULT_RETENTION_PROFILE,
    MAX_EXPERIMENT_CELLS,
    RUN_RESULT_REFERENCE_ROLE,
    ProductRuntime,
    _canonical_request_hash,
    mint_v3_id,
    wire_time,
)

_TRUTH_FORMAL = "FORMAL"


def _session_row_id(session_id: str) -> str:
    """Deterministic catalog row identity for a contract-format session UUID.

    The frozen DTO carries `format: uuid` session identities while the durable
    catalog primary key requires the `ses_` identity pattern; the mapping is a
    pure, deterministic derivation so the same UUID always resolves the same
    durable session row across backend restarts.
    """
    digest = canonical_sha256({"session_id": session_id})
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    value = int(digest, 16)
    chars = "".join(alphabet[(value >> (5 * shift)) & 0x1F] for shift in range(25, -1, -1))
    return "ses_" + chars
_ACCEPTED_STATE = "QUEUED"
CONTEXT_ALLOW_LIST = ("notes", "benchmark_universe_version_id")
STREAM_TICKET_TTL_SECONDS = 300


def _response(request: Mapping[str, Any], read_model: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "request_id": request["request_id"],
        "truth_state": _TRUTH_FORMAL,
        "read_model": dict(read_model),
    }


def _accepted(
    request: Mapping[str, Any], task_id: str, run_id: str, event_cursor: int | None
) -> dict[str, Any]:
    wire: dict[str, Any] = {
        "request_id": request["request_id"],
        "task_id": task_id,
        "run_id": run_id,
        "accepted_state": _ACCEPTED_STATE,
    }
    if event_cursor is not None and event_cursor >= 1:
        wire["event_cursor"] = event_cursor
    return wire


def _project_context_read_model(product: ProductRuntime, revision: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "read_model_version": "v3.project-context/1.0",
        "project_id": str(revision["project_id"]),
        "project_context_revision_id": str(revision["project_context_revision_id"]),
        "revision_no": int(revision["revision_no"]),
        "parent_revision_id": (
            None if revision["parent_revision_id"] is None else str(revision["parent_revision_id"])
        ),
        "canonical_hash": str(revision["canonical_hash"]),
        "context": json.loads(str(revision["context_json"])),
        "created_at": str(revision["created_at"]),
        "created_by": str(revision["created_by"]),
        "capabilities": [item.to_wire() for item in product.capabilities()],
    }


def _session_restore_read_model(
    product: ProductRuntime, session: Mapping[str, Any]
) -> dict[str, Any]:
    current = product.current_revision(str(session["project_id"]))
    return {
        "read_model_version": "v3.session-restore/1.0",
        "session_row_id": str(session["session_id"]),
        "project_id": str(session["project_id"]),
        "project_context_revision_id": current["project_context_revision_id"],
        "state": str(session["state"]),
        "active_lab": None if session["active_lab"] is None else str(session["active_lab"]),
        "layout_artifact_id": (
            None if session["layout_artifact_id"] is None else str(session["layout_artifact_id"])
        ),
        "opened_at": str(session["opened_at"]),
        "closed_at": None if session["closed_at"] is None else str(session["closed_at"]),
        "context": _project_context_read_model(product, current),
    }


class ProjectSessionFacade:
    SERVICE = "ProjectSessionService"

    def __init__(self, product: ProductRuntime) -> None:
        self.product = product

    def handlers(self) -> dict[str, Any]:
        return {
            "ProjectSessionService.v1.openProject": self.open_project,
            "ProjectSessionService.v1.getProjectContext": self.get_project_context,
            "ProjectSessionService.v1.reviseProjectContext": self.revise_project_context,
            "ProjectSessionService.v1.restoreSession": self.restore_session,
        }

    def open_project(self, request: Mapping[str, Any]) -> dict[str, Any]:
        project_id = str(request["project_id"])
        project_context_revision_id = str(request["project_context_revision_id"])
        session_id = str(request["session_id"])
        project = self.product.require_project(project_id)
        current = self.product.current_revision(project_id)
        if current["project_context_revision_id"] != project_context_revision_id:
            raise TruthPreconditionFailedError(
                "openProject requires the current (non-superseded) project context revision"
            )
        now = wire_time(datetime.now(timezone.utc))
        row_id = _session_row_id(session_id)
        connection = self.product._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO desktop_session(
                    session_id, project_id, project_context_revision_id, state, opened_at, row_version
                ) VALUES(?,?,?,'OPEN',?,0)
                ON CONFLICT(session_id) DO UPDATE SET
                    project_context_revision_id=excluded.project_context_revision_id,
                    state='OPEN', closed_at=NULL, opened_at=excluded.opened_at
                """,
                (row_id, project_id, project_context_revision_id, now),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return _response(request, _project_context_read_model(self.product, current))

    def get_project_context(self, request: Mapping[str, Any]) -> dict[str, Any]:
        revision = self.product.require_project_context_ownership(
            str(request["project_id"]), str(request["project_context_revision_id"])
        )
        return _response(request, _project_context_read_model(self.product, revision))

    def revise_project_context(self, request: Mapping[str, Any]) -> dict[str, Any]:
        project_id = str(request["project_id"])
        base_revision_id = str(request["base_revision_id"])
        patch = dict(request["patch"])
        idempotency_key = str(request["idempotency_key"])
        unknown = set(patch) - {"context_fields"}
        if unknown or not isinstance(patch.get("context_fields"), Mapping):
            raise InvalidArgumentError("patch must contain only allow-listed context_fields")
        fields = dict(patch["context_fields"])
        unknown_fields = set(fields) - set(CONTEXT_ALLOW_LIST)
        if unknown_fields:
            raise InvalidArgumentError(
                f"context fields outside the product allow-list: {sorted(unknown_fields)}"
            )
        for value in fields.values():
            if not isinstance(value, str) or len(value) > 2048:
                raise InvalidArgumentError("context field values must be bounded strings")
        operation_id = "ProjectSessionService.v1.reviseProjectContext"
        semantic = {
            "project_id": project_id,
            "base_revision_id": base_revision_id,
            "patch": patch,
        }
        scope = self.product.idempotency.scope_key(operation_id, project_id, idempotency_key)
        request_hash = _canonical_request_hash(operation_id, semantic)
        existing = self.product.idempotency.lookup(self.product, scope, request_hash)
        if existing is not None:
            revision = self.product.require_context_revision(str(existing["project_context_revision_id"]))
            return _response(request, _project_context_read_model(self.product, revision))
        current = self.product.current_revision(project_id)
        if current["project_context_revision_id"] != base_revision_id:
            raise ConflictError("ProjectContext base revision is stale")
        current_context = json.loads(str(current["context_json"]))
        merged = dict(current_context)
        merged.setdefault("context_fields", {})
        merged["context_fields"] = {**merged["context_fields"], **fields}
        canonical_context = json.dumps(merged, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        new_revision_id = mint_v3_id("pcr_")
        now = wire_time(datetime.now(timezone.utc))
        connection = connect_catalog(self.product.database_path)
        uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
        try:
            uow.begin()
            registry = SQLiteRepositoryRegistry(uow)
            registry.project.append_revision(
                {
                    "project_context_revision_id": new_revision_id,
                    "project_id": project_id,
                    "context_json": canonical_context,
                    "canonical_hash": canonical_sha256(canonical_context),
                    "created_by": "product-runtime",
                    "created_at": now,
                },
                base_revision_id=base_revision_id,
            )
            registry.task.record_idempotency(
                {
                    "scope_key": scope,
                    "operation_id": operation_id,
                    "project_id": project_id,
                    "canonical_request_hash": request_hash,
                    "outcome_kind": "RESPONSE",
                    "outcome_json": json.dumps(
                        {"project_context_revision_id": new_revision_id},
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    "created_at": now,
                    "expires_at": None,
                }
            )
            uow.commit()
        finally:
            if uow.active:
                uow.rollback()
            connection.close()
        revision = self.product.require_context_revision(new_revision_id)
        return _response(request, _project_context_read_model(self.product, revision))

    def restore_session(self, request: Mapping[str, Any]) -> dict[str, Any]:
        project_id = str(request["project_id"])
        project_context_revision_id = str(request["project_context_revision_id"])
        session_id = str(request["session_id"])
        self.product.require_project_context_ownership(project_id, project_context_revision_id)
        session = self.product.session_row(_session_row_id(session_id))
        if session is None:
            raise NotFoundError(f"unknown desktop session: {session_id}")
        if str(session["project_id"]) != project_id:
            raise TruthPreconditionFailedError("session belongs to a different project")
        read_model = _session_restore_read_model(self.product, session)
        read_model["session_id"] = session_id
        return _response(request, read_model)


def _attempt_read_model(product: ProductRuntime, task_id: str, run_id: str) -> dict[str, Any]:
    try:
        attempt = product.task_persistence.latest_attempt(task_id)
    except KeyError:
        return {
            "attempt_id": None,
            "ordinal": 0,
            "state": "QUEUED",
            "error_category": None,
        }
    return {
        "attempt_id": attempt.attempt_id,
        "ordinal": attempt.ordinal,
        "state": attempt.state.value,
        "error_category": attempt.terminal_error_category,
    }


def _task_read_model(product: ProductRuntime, task_id: str) -> dict[str, Any]:
    task = product.task_persistence.read_task(task_id)
    outputs: dict[str, str] = {}
    for reference in product.references(task.active_run_id):
        outputs[str(reference["role"])] = str(reference["artifact_id"])
    connection = product._connection(read_only=True)
    try:
        row = connection.execute(
            """
            SELECT t.created_at, t.updated_at, t.terminal_at,
                   result.result_id AS result_id
            FROM task t
            LEFT JOIN run r ON r.run_id=? AND r.task_id=t.task_id
            LEFT JOIN result
              ON result.backtest_run_id=r.run_id
             AND result.project_id=t.project_id
            WHERE t.task_id=? AND t.project_id=?
            """,
            (task.active_run_id, task_id, task.project_id),
        ).fetchone()
    finally:
        connection.close()
    return {
        "read_model_version": "v3.task/1.0",
        "task_id": task.task_id,
        "project_id": task.project_id,
        "operation_id": task.operation_id,
        "state": task.state.value,
        "state_version": task.state_version,
        "run_id": task.active_run_id,
        "result_id": None if row["result_id"] is None else str(row["result_id"]),
        "attempt": _attempt_read_model(product, task_id, task.active_run_id),
        "outputs": outputs,
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "terminal_at": None if row["terminal_at"] is None else str(row["terminal_at"]),
    }


class TaskFacade:
    SERVICE = "TaskService"

    def __init__(self, product: ProductRuntime) -> None:
        self.product = product

    def handlers(self) -> dict[str, Any]:
        return {
            "TaskService.v1.getTask": self.get_task,
            "TaskService.v1.listTasks": self.list_tasks,
            "TaskService.v1.getEvents": self.get_events,
            "TaskService.v1.cancelTask": self.cancel_task,
            "TaskService.v1.retryTask": self.retry_task,
        }

    def get_task(self, request: Mapping[str, Any]) -> dict[str, Any]:
        task_id = str(request["task_id"])
        task = self.product.task_persistence.read_task(task_id)
        if task.project_id != str(request["project_id"]):
            raise TruthPreconditionFailedError("task belongs to a different project")
        return _response(request, _task_read_model(self.product, task_id))

    def list_tasks(self, request: Mapping[str, Any]) -> dict[str, Any]:
        project_id = str(request["project_id"])
        filter_wire = dict(request["filter"])
        page_size = int(request["page_size"])
        allowed = {"service", "state"}
        unknown = set(filter_wire) - allowed
        if unknown:
            raise InvalidArgumentError(f"task filter fields unsupported: {sorted(unknown)}")
        sql = (
            "SELECT task_id FROM task WHERE project_id=? "
            + ("AND service_name=? " if filter_wire.get("service") else "")
            + ("AND state=? " if filter_wire.get("state") else "")
            + "ORDER BY created_at DESC, task_id LIMIT ?"
        )
        params: list[Any] = [project_id]
        if filter_wire.get("service"):
            params.append(str(filter_wire["service"]))
        if filter_wire.get("state"):
            params.append(str(filter_wire["state"]))
        params.append(page_size + 1)
        connection = self.product._connection(read_only=True)
        try:
            rows = connection.execute(sql, params).fetchall()
        finally:
            connection.close()
        truncated = len(rows) > page_size
        items = [
            _task_read_model(self.product, str(row["task_id"])) for row in rows[:page_size]
        ]
        return _response(
            request,
            {
                "read_model_version": "v3.task-page/1.0",
                "items": items,
                "page_size": page_size,
                "truncated": truncated,
            },
        )

    def get_events(self, request: Mapping[str, Any]) -> dict[str, Any]:
        project_id = str(request["project_id"])
        after_sequence = int(request["after_sequence"])
        limit = int(request["limit"])
        connection = self.product._connection(read_only=True)
        try:
            rows = connection.execute(
                """
                SELECT task_event_id, project_id, project_sequence, event_type,
                       occurred_at, payload_json
                FROM task_event
                WHERE project_id=? AND project_sequence>? AND project_sequence<=?
                ORDER BY project_sequence
                """,
                (project_id, after_sequence, after_sequence + limit),
            ).fetchall()
            watermark = int(
                connection.execute(
                    "SELECT COALESCE(MAX(project_sequence),0) FROM task_event WHERE project_id=?",
                    (project_id,),
                ).fetchone()[0]
            )
        finally:
            connection.close()
        items = [
            {
                "event_id": str(row["task_event_id"]),
                "project_sequence": int(row["project_sequence"]),
                "event_type": str(row["event_type"]),
                "occurred_at": str(row["occurred_at"]),
                "body": json.loads(str(row["payload_json"])),
            }
            for row in rows
        ]
        return _response(
            request,
            {
                "read_model_version": "v3.task-event-page/1.0",
                "items": items,
                "after_sequence": after_sequence,
                "high_watermark": watermark,
                "has_more": bool(items) and int(items[-1]["project_sequence"]) < watermark,
            },
        )

    def cancel_task(self, request: Mapping[str, Any]) -> dict[str, Any]:
        task_id = str(request["task_id"])
        expected_state_version = int(request["expected_state_version"])
        reason = str(request["reason"])
        task = self.product.task_persistence.read_task(task_id)
        if task.project_id != str(request["project_id"]):
            raise TruthPreconditionFailedError("task belongs to a different project")
        if task.state in {TaskState.SUCCEEDED, TaskState.FAILED, TaskState.CANCELLED, TaskState.PARTIAL}:
            raise ConflictError("terminal Task cannot be cancelled")
        if task.state_version != expected_state_version:
            raise ConflictError("Task state version is stale")
        with self.product.task_persistence.begin() as unit:
            current_task = unit.require_task(task_id)
            current_task.state = transition_task(
                current_task.state,
                "CANCEL_REQUESTED",
                TaskTransitionContext(),
            )
            unit.save_task(current_task, expected_version=current_task.state_version)
            current_attempt = unit.require_attempt(_latest_attempt_id(unit, task_id))
            current_attempt.state = transition_attempt(current_attempt.state, "ATTEMPT_CANCELLED")
            unit.save_attempt(current_attempt, expected_version=current_attempt.state_version)
            current_task.state = transition_task(
                current_task.state,
                "WORKER_CANCELLED_OR_TERMINATED",
                TaskTransitionContext(cleanup_complete=True),
            )
            unit.save_task(current_task, expected_version=current_task.state_version)
            unit.append_event(
                PendingTaskEvent(
                    event_id=mint_v3_id("tev_"),
                    event_version="1.0.0",
                    project_id=current_task.project_id,
                    task_id=task_id,
                    event_type="TASK_CANCELLED",
                    occurred_at=datetime.now(timezone.utc),
                    payload={"reason": reason},
                    run_id=current_task.active_run_id,
                    attempt_id=current_attempt.attempt_id,
                )
            )
            unit.commit()
        return _response(request, _task_read_model(self.product, task_id))

    def retry_task(self, request: Mapping[str, Any]) -> dict[str, Any]:
        task_id = str(request["task_id"])
        failed_attempt_id = str(request["failed_attempt_id"])
        expected_state_version = int(request["expected_state_version"])
        task = self.product.task_persistence.read_task(task_id)
        if task.project_id != str(request["project_id"]):
            raise TruthPreconditionFailedError("task belongs to a different project")
        self.product.execution.retry_failed_task(
            task_id=task_id,
            failed_attempt_id=failed_attempt_id,
            expected_state_version=expected_state_version,
        )
        return _response(request, _task_read_model(self.product, task_id))

def _latest_attempt_id(unit: Any, task_id: str) -> str:
    row = unit.connection.execute(
        """
        SELECT attempt_id FROM task_attempt
        JOIN run USING(run_id)
        WHERE task_id=? ORDER BY attempt_no DESC LIMIT 1
        """,
        (task_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"no Attempt for Task: {task_id}")
    return str(row[0])


def _artifact_descriptor_read_model(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "read_model_version": "v3.artifact-descriptor/1.0",
        "artifact_id": str(row["artifact_id"]),
        "sha256": str(row["sha256"]),
        "byte_size": int(row["byte_size"]),
        "media_type": str(row["media_type"]),
        "role": str(row["semantic_role"]),
        "state": str(row["state"]),
        "created_at": str(row["created_at"]),
        "published_at": None if row["published_at"] is None else str(row["published_at"]),
    }


class ArtifactFacade:
    SERVICE = "ArtifactService"

    def __init__(self, product: ProductRuntime) -> None:
        self.product = product
        self._tickets: dict[str, dict[str, Any]] = {}

    def handlers(self) -> dict[str, Any]:
        return {
            "ArtifactService.v1.publishArtifact": self.publish_artifact,
            "ArtifactService.v1.getArtifactDescriptor": self.get_artifact_descriptor,
            "ArtifactService.v1.openArtifactStream": self.open_artifact_stream,
            "ArtifactService.v1.exportArtifact": self.export_artifact,
            "ArtifactService.v1.planGarbageCollection": self.plan_garbage_collection,
        }

    def publish_artifact(self, request: Mapping[str, Any]) -> dict[str, Any]:
        staging_token = str(request["staging_token"])
        declared_media_type = str(request["declared_media_type"])
        declared_role = str(request["declared_role"])
        expected_sha256 = str(request["expected_sha256"])
        idempotency_key = str(request["idempotency_key"])
        project_id = str(request["project_id"])
        self.product.require_project_context_ownership(
            project_id, str(request["project_context_revision_id"])
        )
        operation_id = "ArtifactService.v1.publishArtifact"
        semantic = {
            "project_id": project_id,
            "staging_token": staging_token,
            "declared_media_type": declared_media_type,
            "declared_role": declared_role,
            "expected_sha256": expected_sha256,
        }
        scope = self.product.idempotency.scope_key(operation_id, project_id, idempotency_key)
        request_hash = _canonical_request_hash(operation_id, semantic)
        existing = self.product.idempotency.lookup(self.product, scope, request_hash)
        if existing is not None:
            row = self.product.require_published_artifact(str(existing["artifact_id"]))
            return _response(request, _artifact_descriptor_read_model(row))
        receipt = None
        for candidate in self.product.artifact_store.recover_staging():
            if candidate.staging_token == staging_token:
                receipt = candidate
                break
        if receipt is None:
            raise NotFoundError("staging token is unknown to the product artifact store")
        if receipt.sha256 != expected_sha256:
            raise IdempotencyConflictError("declared SHA-256 does not match the staged bytes")
        self.product.artifact_store.policy.require_publishable(declared_role, declared_media_type)
        from v3_backend.adapters.sqlite.artifact_publication import SQLiteArtifactPublicationPort
        from v3_backend.domain.artifacts.model import ArtifactReference
        from v3_backend.domain.artifacts.publication import ArtifactPublication

        published_at = datetime.now(timezone.utc)
        publication_result = self.product.artifact_store.publish(
            staging_token,
            expected_sha256=expected_sha256,
            expected_byte_size=receipt.byte_size,
            media_type=declared_media_type,
            role=declared_role,
            provenance_entity_id="prv_product_caller_publication",
            published_at=published_at,
        )
        connection = connect_catalog(self.product.database_path)
        uow = SQLiteUnitOfWork(
            connection,
            TransactionMode.PUBLISH,
            publish_callbacks=_NoopPublishCallbacksFacade(),
        )
        try:
            uow.begin()
            port = SQLiteArtifactPublicationPort(uow)
            port.publish(
                ArtifactPublication(
                    descriptor=publication_result.descriptor,
                    active_references=(
                        ArtifactReference(
                            reference_id=mint_v3_id("arf_"),
                            owner_id=project_id,
                            artifact_id=publication_result.descriptor.artifact_id,
                            role=declared_role,
                            created_at=wire_time(published_at),
                            state="ACTIVE",
                        ),
                    ),
                )
            )
            SQLiteRepositoryRegistry(uow).task.record_idempotency(
                {
                    "scope_key": scope,
                    "operation_id": operation_id,
                    "project_id": project_id,
                    "canonical_request_hash": request_hash,
                    "outcome_kind": "RESPONSE",
                    "outcome_json": json.dumps(
                        {"artifact_id": publication_result.descriptor.artifact_id},
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    "created_at": wire_time(published_at),
                    "expires_at": None,
                }
            )
            uow.commit()
        finally:
            if uow.active:
                uow.rollback()
            connection.close()
        row = self.product.require_published_artifact(publication_result.descriptor.artifact_id)
        return _response(request, _artifact_descriptor_read_model(row))

    def get_artifact_descriptor(self, request: Mapping[str, Any]) -> dict[str, Any]:
        row = self.product.require_published_artifact(str(request["artifact_id"]))
        return _response(request, _artifact_descriptor_read_model(row))

    def open_artifact_stream(self, request: Mapping[str, Any]) -> dict[str, Any]:
        artifact_id = str(request["artifact_id"])
        self.product.require_published_artifact(artifact_id)
        range_wire = request.get("range")
        range_start = None
        range_end_exclusive = None
        if range_wire is not None:
            unknown = set(range_wire) - {"start", "end_exclusive"}
            if unknown or not isinstance(range_wire.get("start"), int) or not isinstance(
                range_wire.get("end_exclusive"), int
            ):
                raise InvalidArgumentError("stream range must provide integer start/end_exclusive")
            range_start = int(range_wire["start"])
            range_end_exclusive = int(range_wire["end_exclusive"])
            if range_start < 0 or range_end_exclusive <= range_start:
                raise InvalidArgumentError("invalid stream byte range")
        ticket_id = mint_v3_id("stk_")
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=STREAM_TICKET_TTL_SECONDS)
        self._tickets[ticket_id] = {
            "artifact_id": artifact_id,
            "project_id": str(request["project_id"]),
            "expires_at": expires_at,
            "range_start": range_start,
            "range_end_exclusive": range_end_exclusive,
        }
        read_model: dict[str, Any] = {
            "read_model_version": "v3.artifact-stream-ticket/1.0",
            "mode": "STREAM_TICKET",
            "ticket_id": ticket_id,
            "artifact_id": artifact_id,
            "project_id": str(request["project_id"]),
            "expires_at": wire_time(expires_at),
            "range_start": range_start,
            "range_end_exclusive": range_end_exclusive,
        }
        return _response(request, read_model)

    def export_artifact(self, request: Mapping[str, Any]) -> dict[str, Any]:
        outcome = self.product.execution.export_artifacts(
            project_id=str(request["project_id"]),
            project_context_revision_id=str(request["project_context_revision_id"]),
            artifact_ids=tuple(str(item) for item in request["artifact_ids"]),
            export_profile_id=str(request["export_profile_id"]),
            destination_token=str(request["destination_token"]),
            idempotency_key=str(request["idempotency_key"]),
        )
        return _accepted(request, outcome.task_id, outcome.run_id, outcome.event_cursor)

    def plan_garbage_collection(self, request: Mapping[str, Any]) -> dict[str, Any]:
        retention_profile_id = str(request["retention_profile_id"])
        if retention_profile_id != DEFAULT_RETENTION_PROFILE:
            raise InvalidArgumentError(
                f"unknown retention profile: {retention_profile_id}"
            )
        connection = self.product._connection(read_only=True)
        try:
            reachable = {
                str(row["artifact_id"])
                for row in connection.execute(
                    "SELECT DISTINCT artifact_id FROM artifact_reference WHERE state='ACTIVE'"
                ).fetchall()
            }
            candidates = [
                {
                    "artifact_id": str(row["artifact_id"]),
                    "sha256": str(row["sha256"]),
                    "byte_size": int(row["byte_size"]),
                    "reason": "UNREACHABLE",
                }
                for row in connection.execute(
                    "SELECT artifact_id, sha256, byte_size FROM artifact WHERE state='PUBLISHED'"
                ).fetchall()
                if str(row["artifact_id"]) not in reachable
            ]
        finally:
            connection.close()
        return _response(
            request,
            {
                "read_model_version": "v3.garbage-collection-plan/1.0",
                "plan_id": mint_v3_id("gcp_"),
                "retention_profile_id": retention_profile_id,
                "generated_at": wire_time(datetime.now(timezone.utc)),
                "reachable_artifact_count": len(reachable),
                "candidates": candidates,
                "requires_confirmation": True,
            },
        )


class _NoopPublishCallbacksFacade:
    def verify_staged(self) -> None:
        return None

    def publish_staged(self) -> None:
        return None

    def compensate_unreferenced_staging(self) -> None:
        return None

    def notify_committed(self) -> None:
        return None


class BacktestFacade:
    SERVICE = "BacktestService"

    def __init__(self, product: ProductRuntime) -> None:
        self.product = product

    def handlers(self) -> dict[str, Any]:
        return {
            "BacktestService.v1.submitBacktest": self.submit_backtest,
            "BacktestService.v1.createExperiment": self.create_experiment,
            "BacktestService.v1.getExperiment": self.get_experiment,
            "BacktestService.v1.expandExperiment": self.expand_experiment,
        }

    def submit_backtest(self, request: Mapping[str, Any]) -> dict[str, Any]:
        outcome = self.product.execution.submit_backtest(
            project_id=str(request["project_id"]),
            project_context_revision_id=str(request["project_context_revision_id"]),
            run_spec_id=str(request["run_spec_id"]),
            execution_adapter_version_id=str(request["execution_adapter_version_id"]),
            idempotency_key=str(request["idempotency_key"]),
        )
        return _accepted(request, outcome.task_id, outcome.run_id, outcome.event_cursor)

    def create_experiment(self, request: Mapping[str, Any]) -> dict[str, Any]:
        project_id = str(request["project_id"])
        project_context_revision_id = str(request["project_context_revision_id"])
        self.product.require_project_context_ownership(project_id, project_context_revision_id)
        experiment_spec = dict(request["experiment_spec"])
        idempotency_key = str(request["idempotency_key"])
        allowed = {"axes", "cells"}
        unknown = set(experiment_spec) - allowed
        if unknown or "cells" not in experiment_spec:
            raise InvalidArgumentError("experiment_spec must declare axes and cells")
        cells = list(experiment_spec["cells"])
        if not cells or len(cells) > MAX_EXPERIMENT_CELLS:
            raise InvalidArgumentError(f"experiment matrix must have 1..{MAX_EXPERIMENT_CELLS} cells")
        for cell in cells:
            if set(cell) != {"run_spec_id", "execution_adapter_version_id"}:
                raise InvalidArgumentError("experiment cell must pin run_spec_id and execution_adapter_version_id")
            if str(cell["execution_adapter_version_id"]) != ADMITTED_EXECUTION_ADAPTER_VERSION_ID:
                raise TruthPreconditionFailedError("cell execution adapter is not admitted")
            self._require_run_spec(project_id, str(cell["run_spec_id"]))
        operation_id = "BacktestService.v1.createExperiment"
        semantic = {
            "project_id": project_id,
            "project_context_revision_id": project_context_revision_id,
            "experiment_spec": experiment_spec,
        }
        scope = self.product.idempotency.scope_key(operation_id, project_id, idempotency_key)
        request_hash = _canonical_request_hash(operation_id, semantic)
        existing = self.product.idempotency.lookup(self.product, scope, request_hash)
        if existing is not None:
            row = self.product.require_experiment(str(existing["experiment_id"]))
            return _response(request, self._experiment_read_model(row))
        experiment_id = mint_v3_id("exp_")
        canonical_spec = json.dumps(experiment_spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        now = wire_time(datetime.now(timezone.utc))
        connection = connect_catalog(self.product.database_path)
        uow = SQLiteUnitOfWork(connection, TransactionMode.WRITE_CONTROL)
        try:
            uow.begin()
            registry = SQLiteRepositoryRegistry(uow)
            registry.backtest.table("experiment").add_new(
                {
                    "experiment_id": experiment_id,
                    "project_id": project_id,
                    "experiment_spec_json": canonical_spec,
                    "canonical_hash": canonical_sha256(canonical_spec),
                    "state": "DRAFT",
                    "expansion_manifest_artifact_id": None,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            registry.task.record_idempotency(
                {
                    "scope_key": scope,
                    "operation_id": operation_id,
                    "project_id": project_id,
                    "canonical_request_hash": request_hash,
                    "outcome_kind": "RESPONSE",
                    "outcome_json": json.dumps(
                        {"experiment_id": experiment_id}, separators=(",", ":"), sort_keys=True
                    ),
                    "created_at": now,
                    "expires_at": None,
                }
            )
            uow.commit()
        finally:
            if uow.active:
                uow.rollback()
            connection.close()
        row = self.product.require_experiment(experiment_id)
        return _response(request, self._experiment_read_model(row))

    def _require_run_spec(self, project_id: str, run_spec_id: str) -> None:
        rows = self.product.spec_codec.resolve_reference(
            project_id, "RESEARCH_RUN_SPEC"
        )
        for row in rows:
            payload = self.product.read_verified_bytes(row["artifact_id"])
            if json.loads(payload.decode("utf-8")).get("run_spec_id") == run_spec_id:
                return
        raise NotFoundError(f"no durable run spec for project: {run_spec_id}")

    def _experiment_read_model(self, row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "read_model_version": "v3.experiment/1.0",
            "experiment_id": str(row["experiment_id"]),
            "project_id": str(row["project_id"]),
            "state": str(row["state"]),
            "canonical_hash": str(row["canonical_hash"]),
            "spec": json.loads(str(row["experiment_spec_json"])),
            "expansion_manifest_artifact_id": (
                None if row["expansion_manifest_artifact_id"] is None
                else str(row["expansion_manifest_artifact_id"])
            ),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def get_experiment(self, request: Mapping[str, Any]) -> dict[str, Any]:
        row = self.product.require_experiment(str(request["experiment_id"]))
        if str(row["project_id"]) != str(request["project_id"]):
            raise TruthPreconditionFailedError("experiment belongs to a different project")
        return _response(request, self._experiment_read_model(row))

    def expand_experiment(self, request: Mapping[str, Any]) -> dict[str, Any]:
        outcome = self.product.execution.expand_experiment(
            project_id=str(request["project_id"]),
            project_context_revision_id=str(request["project_context_revision_id"]),
            experiment_id=str(request["experiment_id"]),
            idempotency_key=str(request["idempotency_key"]),
        )
        return _accepted(request, outcome.task_id, outcome.run_id, outcome.event_cursor)


class ResultFacade:
    SERVICE = "ResultService"

    def __init__(self, product: ProductRuntime) -> None:
        self.product = product

    def handlers(self) -> dict[str, Any]:
        return {
            "ResultService.v1.getResult": self.get_result,
        }

    def get_result(self, request: Mapping[str, Any]) -> dict[str, Any]:
        result_id = str(request["result_id"])
        section = str(request["section"])
        if section != "summary":
            raise InvalidArgumentError("only the summary section is product-available")
        row = self.product.require_result(result_id)
        if str(row["project_id"]) != str(request["project_id"]):
            raise TruthPreconditionFailedError("result belongs to a different project")
        result_artifact = None
        connection = self.product._connection(read_only=True)
        try:
            run_row = connection.execute(
                "SELECT code_version FROM run WHERE run_id=?",
                (str(row["backtest_run_id"]),),
            ).fetchone()
        finally:
            connection.close()
        references = self.product.references(
            str(row["backtest_run_id"]), RUN_RESULT_REFERENCE_ROLE
        )
        if references:
            artifact_id = str(references[0]["artifact_id"])
            artifact_row = self.product.require_published_artifact(artifact_id)
            result_artifact = _artifact_descriptor_read_model(artifact_row)
        return _response(
            request,
            {
                "read_model_version": "v3.result/1.0",
                "result_id": result_id,
                "project_id": str(row["project_id"]),
                "backtest_run_id": str(row["backtest_run_id"]),
                "code_version": None if run_row is None else str(run_row["code_version"]),
                "build_manifest_id": BUILD_MANIFEST_ID,
                "state": str(row["state"]),
                "ledger_manifest_artifact_id": str(row["ledger_manifest_artifact_id"]),
                "reconciliation_artifact_id": (
                    None if row["reconciliation_artifact_id"] is None
                    else str(row["reconciliation_artifact_id"])
                ),
                "result_artifact": result_artifact,
                "lineage_hash": str(row["lineage_hash"]),
                "created_at": str(row["created_at"]),
                "finalized_at": (
                    None if row.get("finalized_at") is None else str(row["finalized_at"])
                ),
            },
        )


class ProductEntryFacade:
    """Product Entry ASL operations over the canonical project/run-spec owners.

    createProject / listProjects intentionally live OUTSIDE this ASL facade as
    narrow projectless control frames; every ASL operation here remains fully
    project-bound.
    """

    SERVICE = "ProductEntryService"

    def __init__(self, product: ProductRuntime) -> None:
        self.product = product

    def handlers(self) -> dict[str, Any]:
        return {
            "ProductEntryService.v1.listBacktestRunSpecs": self.list_backtest_run_specs,
            "ProductEntryService.v1.importResearchPackage": self.import_research_package,
        }

    def list_backtest_run_specs(self, request: Mapping[str, Any]) -> dict[str, Any]:
        page = request.get("page") or {}
        listing = _product_entry().list_backtest_run_specs(
            self.product,
            project_id=str(request["project_id"]),
            project_context_revision_id=str(request["project_context_revision_id"]),
            limit=int(page.get("limit", 50)),
            after_artifact_id=page.get("after_artifact_id"),
        )
        return _response(
            request,
            {
                "read_model_version": "v3.product-entry/1.0",
                "specs": listing["specs"],
                "has_more": listing["has_more"],
                "next_after_artifact_id": listing["next_after_artifact_id"],
            },
        )

    def import_research_package(self, request: Mapping[str, Any]) -> dict[str, Any]:
        outcome = _product_entry().import_research_package(
            self.product,
            project_id=str(request["project_id"]),
            project_context_revision_id=str(request["project_context_revision_id"]),
            manifest_wire=request["manifest"],
            files_wire=request["files"],
            idempotency_key=str(request["idempotency_key"]),
        )
        return _response(
            request,
            {"read_model_version": "v3.product-entry/1.0", **outcome},
        )


def _product_entry():
    from .product_entry import (
        import_research_package as _import,
        list_backtest_run_specs as _list,
    )

    return _PRODUCT_ENTRY_API(import_research_package=_import, list_backtest_run_specs=_list)


class _PRODUCT_ENTRY_API:
    def __init__(self, *, import_research_package, list_backtest_run_specs) -> None:
        self.import_research_package = import_research_package
        self.list_backtest_run_specs = list_backtest_run_specs


def build_product_facades(product: ProductRuntime) -> tuple[Any, ...]:
    return (
        ProjectSessionFacade(product),
        TaskFacade(product),
        ArtifactFacade(product),
        BacktestFacade(product),
        ResultFacade(product),
        ProductEntryFacade(product),
    )


__all__ = [
    "ArtifactFacade",
    "BacktestFacade",
    "ProductEntryFacade",
    "ProjectSessionFacade",
    "ResultFacade",
    "TaskFacade",
    "build_product_facades",
]
