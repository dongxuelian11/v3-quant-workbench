"""Thin ASL facades over the B3 product runtime composition.

Each facade maps one frozen service contract onto durable product stores and
accepted canonical owners.  Facades never compute financial truth: every
numeric value they return originates from a canonical owner record or a
content-addressed artifact published by the canonical execution path.
"""

from __future__ import annotations

import json
import base64
import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from collections.abc import Iterator
from typing import Any, Mapping

from v3_backend.adapters.sqlite.connection import connect_catalog
from v3_backend.adapters.sqlite.repositories import SQLiteRepositoryRegistry
from v3_backend.adapters.sqlite.unit_of_work import SQLiteUnitOfWork
from v3_backend.domain.tasks.events import PendingTaskEvent
from v3_backend.errors.exceptions import (
    CapabilityUnavailableError,
    ConflictError,
    IdempotencyConflictError,
    InvalidArgumentError,
    NotFoundError,
    ResourceRejectedError,
    SessionProjectBindingConflictError,
    TruthPreconditionFailedError,
)
from v3_backend.provenance.canonical_hash import canonical_sha256
from v3_backend.repositories.unit_of_work import TransactionMode

from .product_runtime import (
    ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
    BUILD_MANIFEST_ID,
    DEFAULT_RETENTION_PROFILE,
    FORMAL_BACKTEST_UNAVAILABLE_REASON,
    MAX_EXPERIMENT_CELLS,
    ProductResearchSubmission,
    RUN_RESULT_REFERENCE_ROLE,
    ProductRuntime,
    _canonical_request_hash,
    mint_v3_id,
    wire_time,
)

_TRUTH_FORMAL = "FORMAL"
_CANONICAL_SESSION_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)


def _session_row_id_for_value(session_id: str) -> str:
    digest = canonical_sha256({"session_id": session_id})
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    value = int(digest, 16)
    chars = "".join(
        alphabet[(value >> (5 * shift)) & 0x1F] for shift in range(25, -1, -1)
    )
    return "ses_" + chars


def _session_row_id(session_id: str) -> str:
    """Deterministic canonical row identity for a contract-format session UUID.

    The frozen DTO carries `format: uuid` session identities while the durable
    catalog primary key requires the `ses_` identity pattern; the mapping is a
    pure, deterministic derivation so the same UUID always resolves the same
    durable session row across backend restarts.
    """
    # The wire contract admits only lowercase canonical UUIDs.  Keep the
    # durable mapping explicit so a legacy row can be claimed without minting
    # a second project-visible session identity.
    return _session_row_id_for_value(session_id.lower())


def _session_row_candidates(session_id: str) -> tuple[str, ...]:
    """Return the one durable identity admitted by the lowercase UUID contract."""

    return (_session_row_id(session_id),)


def _require_canonical_session_uuid(session_id: str) -> str:
    if _CANONICAL_SESSION_UUID.fullmatch(session_id) is None:
        raise InvalidArgumentError(
            "session UUID must use lowercase canonical hyphenated form"
        )
    return session_id


def _session_rows(
    connection: Any,
    row_ids: tuple[str, ...],
    canonical_session_uuid: str,
) -> tuple[Any, ...]:
    placeholders = ",".join("?" for _ in row_ids)
    return tuple(
        connection.execute(
            f"""
            SELECT * FROM desktop_session
            WHERE session_id IN ({placeholders})
               OR canonical_session_uuid=?
            """,
            (*row_ids, canonical_session_uuid),
        ).fetchall()
    )


def _unresolved_legacy_session_projects(connection: Any) -> frozenset[str]:
    return frozenset(
        str(row["project_id"])
        for row in connection.execute(
            """
            SELECT DISTINCT project_id
            FROM desktop_session
            WHERE canonical_session_uuid IS NULL
            """
        ).fetchall()
    )


def _first_session_row_id(
    row_ids: tuple[str, ...], rows: tuple[Any, ...], canonical_session_uuid: str
) -> str:
    for row in rows:
        if str(row["canonical_session_uuid"] or "") == canonical_session_uuid:
            return str(row["session_id"])
    for row_id in row_ids:
        if any(str(row["session_id"]) == row_id for row in rows):
            return row_id
    return row_ids[0]


_ACCEPTED_STATE = "QUEUED"
CONTEXT_ALLOW_LIST = ("notes", "benchmark_universe_version_id")
STREAM_TICKET_TTL_SECONDS = 300
MAX_STREAM_TICKETS = 4096
STREAM_CHUNK_MAX_BYTES = 256 * 1024
PRODUCT_FACTOR_HOME_PROJECTION_LIMIT = 256
PRODUCT_FACTOR_HOME_PROJECTION = "TAIL_ASCENDING_MAX_256"


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
        _require_canonical_session_uuid(session_id)
        self.product.require_project(project_id)
        current = self.product.current_revision(project_id)
        if current["project_context_revision_id"] != project_context_revision_id:
            raise TruthPreconditionFailedError(
                "openProject requires the current (non-superseded) project context revision"
            )
        now = wire_time(datetime.now(timezone.utc))
        row_ids = _session_row_candidates(session_id)
        canonical_session_uuid = session_id.lower()

        # Fast domain preflight before taking a write lock. The guarded read is
        # repeated inside BEGIN IMMEDIATE below to close the concurrency race.
        existing_connection = self.product._connection(read_only=True)
        try:
            existing_rows = _session_rows(
                existing_connection, row_ids, canonical_session_uuid
            )
            unresolved_legacy_projects = _unresolved_legacy_session_projects(
                existing_connection
            )
        finally:
            existing_connection.close()
        if any(str(row["project_id"]) != project_id for row in existing_rows):
            raise SessionProjectBindingConflictError(
                "session UUID is already bound to a different project"
            )
        if any(
            legacy_project != project_id
            for legacy_project in unresolved_legacy_projects
        ):
            raise SessionProjectBindingConflictError(
                "legacy session identity in another project requires explicit revalidation"
            )
        connection = self.product._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            locked_project = connection.execute(
                "SELECT state FROM project WHERE project_id=?",
                (project_id,),
            ).fetchone()
            if locked_project is None:
                raise NotFoundError(f"unknown project: {project_id}")
            if str(locked_project["state"]) != "ACTIVE":
                raise ConflictError(f"project is not ACTIVE: {project_id}")
            locked_current = connection.execute(
                """
                SELECT project_context_revision_id
                FROM project_context_revision
                WHERE project_id=?
                ORDER BY revision_no DESC
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
            if locked_current is None:
                raise NotFoundError(f"project has no context revision: {project_id}")
            if (
                str(locked_current["project_context_revision_id"])
                != project_context_revision_id
            ):
                raise TruthPreconditionFailedError(
                    "openProject requires the current (non-superseded) project context revision"
                )
            locked_existing_rows = _session_rows(
                connection, row_ids, canonical_session_uuid
            )
            if any(
                str(row["project_id"]) != project_id
                for row in locked_existing_rows
            ):
                raise SessionProjectBindingConflictError(
                    "session UUID is already bound to a different project"
                )
            unresolved_legacy_projects = _unresolved_legacy_session_projects(
                connection
            )
            if any(
                legacy_project != project_id
                for legacy_project in unresolved_legacy_projects
            ):
                raise SessionProjectBindingConflictError(
                    "legacy session identity in another project requires explicit revalidation"
                )
            row_id = _first_session_row_id(
                row_ids, locked_existing_rows, canonical_session_uuid
            )
            connection.execute(
                """
                INSERT INTO desktop_session(
                    session_id, project_id, project_context_revision_id, state,
                    opened_at, row_version, canonical_session_uuid
                ) VALUES(?,?,?,'OPEN',?,0,?)
                ON CONFLICT(session_id) DO UPDATE SET
                    project_context_revision_id=excluded.project_context_revision_id,
                    state='OPEN', closed_at=NULL, opened_at=excluded.opened_at,
                    row_version=desktop_session.row_version+1,
                    canonical_session_uuid=excluded.canonical_session_uuid
                """,
                (
                    row_id,
                    project_id,
                    project_context_revision_id,
                    now,
                    canonical_session_uuid,
                ),
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
        _require_canonical_session_uuid(session_id)
        self.product.require_project_context_ownership(project_id, project_context_revision_id)
        current = self.product.current_revision(project_id)
        if str(current["project_context_revision_id"]) != project_context_revision_id:
            raise TruthPreconditionFailedError(
                "restoreSession requires the current (non-superseded) project context revision"
            )
        row_ids = _session_row_candidates(session_id)
        canonical_session_uuid = session_id.lower()
        connection = self.product._connection(read_only=True)
        try:
            session_rows = _session_rows(connection, row_ids, canonical_session_uuid)
            unresolved_legacy_projects = _unresolved_legacy_session_projects(
                connection
            )
        finally:
            connection.close()
        if any(str(row["project_id"]) != project_id for row in session_rows):
            raise SessionProjectBindingConflictError(
                "session UUID is already bound to a different project"
            )
        if any(
            legacy_project != project_id
            for legacy_project in unresolved_legacy_projects
        ):
            raise SessionProjectBindingConflictError(
                "legacy session identity in another project requires explicit revalidation"
            )
        session = None
        selected_row_id = _first_session_row_id(
            row_ids, session_rows, canonical_session_uuid
        )
        for row in session_rows:
            if str(row["session_id"]) == selected_row_id:
                session = row
                break
        if session is None:
            raise NotFoundError(f"unknown desktop session: {session_id}")
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
            "reason_code": None,
        }
    reason_code: str | None = None
    if attempt.state.value == "FAILED":
        connection = product._connection(read_only=True)
        try:
            failure_event = connection.execute(
                """
                SELECT payload_json
                FROM task_event
                WHERE task_id=? AND run_id=? AND attempt_id=? AND event_type='TASK_FAILED'
                ORDER BY project_sequence DESC
                LIMIT 1
                """,
                (task_id, run_id, attempt.attempt_id),
            ).fetchone()
        finally:
            connection.close()
        if failure_event is not None:
            try:
                failure_payload = json.loads(str(failure_event["payload_json"]))
            except json.JSONDecodeError as error:
                raise TruthPreconditionFailedError(
                    "Task failure event payload is not valid JSON"
                ) from error
            candidate = failure_payload.get("reason_code") if isinstance(failure_payload, dict) else None
            if candidate is not None:
                if not isinstance(candidate, str) or not 1 <= len(candidate) <= 128:
                    raise TruthPreconditionFailedError(
                        "Task failure event reason_code must be a bounded non-empty string"
                    )
                reason_code = candidate
    return {
        "attempt_id": attempt.attempt_id,
        "ordinal": attempt.ordinal,
        "state": attempt.state.value,
        "error_category": attempt.terminal_error_category,
        "reason_code": reason_code,
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
        task_output_rows = connection.execute(
            """
            SELECT output_role, artifact_id
            FROM task_output
            WHERE task_id=?
            ORDER BY output_role, ordinal
            """,
            (task_id,),
        ).fetchall()
        terminal_event = connection.execute(
            """
            SELECT payload_json
            FROM task_event
            WHERE task_id=? AND run_id=? AND event_type='TASK_SUCCEEDED'
            ORDER BY project_sequence DESC
            LIMIT 1
            """,
            (task_id, task.active_run_id),
        ).fetchone()
    finally:
        connection.close()

    def add_output(role: str, value: str) -> None:
        current = outputs.get(role)
        if current is not None and current != value:
            raise TruthPreconditionFailedError(
                f"Task output role {role!r} has conflicting durable values"
            )
        outputs[role] = value

    for output in task_output_rows:
        add_output(str(output["output_role"]), str(output["artifact_id"]))
    if terminal_event is not None:
        try:
            terminal_payload = json.loads(str(terminal_event["payload_json"]))
        except json.JSONDecodeError as error:
            raise TruthPreconditionFailedError(
                "Task success event payload is not valid JSON"
            ) from error
        if not isinstance(terminal_payload, dict):
            raise TruthPreconditionFailedError(
                "Task success event payload must be an object"
            )
        if "outputs" in terminal_payload:
            terminal_outputs = terminal_payload["outputs"]
            if not isinstance(terminal_outputs, dict):
                raise TruthPreconditionFailedError(
                    "Task success event outputs must be an object when present"
                )
            for role, value in terminal_outputs.items():
                if (
                    not isinstance(role, str)
                    or role == ""
                    or not isinstance(value, str)
                    or value == ""
                ):
                    raise TruthPreconditionFailedError(
                        "Task success event outputs must map non-empty string roles "
                        "to non-empty string values"
                    )
                add_output(role, value)
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
        allowed = {"service", "state", "cursor"}
        unknown = set(filter_wire) - allowed
        if unknown:
            raise InvalidArgumentError(f"task filter fields unsupported: {sorted(unknown)}")
        service = filter_wire.get("service")
        state = filter_wire.get("state")
        cursor = filter_wire.get("cursor")
        cursor_created_at: str | None = None
        cursor_task_id: str | None = None
        if cursor is not None:
            if not isinstance(cursor, str) or not 1 <= len(cursor) <= 2048:
                raise InvalidArgumentError("task cursor must be a bounded opaque string")
            try:
                padding = "=" * (-len(cursor) % 4)
                decoded = json.loads(base64.urlsafe_b64decode(cursor + padding).decode("utf-8"))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise InvalidArgumentError("task cursor is malformed") from exc
            expected_keys = {"v", "project_id", "service", "state", "created_at", "task_id", "sort"}
            if not isinstance(decoded, dict) or set(decoded) != expected_keys:
                raise InvalidArgumentError("task cursor shape is invalid")
            if (
                decoded["v"] != 1
                or decoded["project_id"] != project_id
                or decoded["service"] != service
                or decoded["state"] != state
                or decoded["sort"] != "created_at_desc_task_id_asc"
                or not isinstance(decoded["created_at"], str)
                or not isinstance(decoded["task_id"], str)
            ):
                raise InvalidArgumentError("task cursor does not match the current project/filter/sort scope")
            cursor_created_at = decoded["created_at"]
            cursor_task_id = decoded["task_id"]
        sql = (
            "SELECT task_id, created_at FROM task WHERE project_id=? "
            + ("AND service_name=? " if service else "")
            + ("AND state=? " if state else "")
            + (
                "AND (created_at < ? OR (created_at = ? AND task_id > ?)) "
                if cursor_created_at is not None
                else ""
            )
            + "ORDER BY created_at DESC, task_id LIMIT ?"
        )
        params: list[Any] = [project_id]
        if service:
            params.append(str(service))
        if state:
            params.append(str(state))
        if cursor_created_at is not None:
            params.extend((cursor_created_at, cursor_created_at, cursor_task_id))
        params.append(page_size + 1)
        connection = self.product._connection(read_only=True)
        try:
            rows = connection.execute(sql, params).fetchall()
        finally:
            connection.close()
        truncated = len(rows) > page_size
        page_rows = rows[:page_size]
        items = [_task_read_model(self.product, str(row["task_id"])) for row in page_rows]
        next_cursor = None
        if truncated:
            last = page_rows[-1]
            cursor_wire = {
                "v": 1,
                "project_id": project_id,
                "service": service,
                "state": state,
                "created_at": str(last["created_at"]),
                "task_id": str(last["task_id"]),
                "sort": "created_at_desc_task_id_asc",
            }
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(cursor_wire, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
            ).decode("ascii").rstrip("=")
        return _response(
            request,
            {
                "read_model_version": "v3.task-page/1.0",
                "items": items,
                "page_size": page_size,
                "truncated": truncated,
                "has_more": truncated,
                "next_cursor": next_cursor,
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
                SELECT task_event_id, project_id, task_id, project_sequence, event_type,
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
                "task_id": str(row["task_id"]),
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
        self.product.cancel_research_task(
            task_id,
            project_id=str(request["project_id"]),
            expected_state_version=int(request["expected_state_version"]),
            reason=str(request["reason"]),
        )
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

    def __init__(
        self,
        product: ProductRuntime,
        *,
        clock=None,
        ticket_limit: int = MAX_STREAM_TICKETS,
        runtime_generation: int | None = None,
    ) -> None:
        if not 1 <= ticket_limit <= MAX_STREAM_TICKETS:
            raise ValueError(
                f"ticket_limit must be between 1 and {MAX_STREAM_TICKETS}"
            )
        self.product = product
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._ticket_limit = ticket_limit
        if runtime_generation is not None and (
            isinstance(runtime_generation, bool)
            or not isinstance(runtime_generation, int)
            or runtime_generation < 1
        ):
            raise ValueError("runtime_generation must be a positive integer or null")
        self._runtime_generation = runtime_generation
        self._tickets: dict[str, dict[str, Any]] = {}

    @property
    def retained_ticket_count(self) -> int:
        return len(self._tickets)

    def _prune_expired_tickets(self, now: datetime) -> None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Artifact stream ticket clock must be timezone-aware")
        for ticket_id, ticket in tuple(self._tickets.items()):
            if ticket["expires_at"] <= now:
                del self._tickets[ticket_id]

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
                            created_at=published_at,
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
        row = self.product.require_project_reachable_artifact(
            str(request["project_id"]), str(request["artifact_id"])
        )
        return _response(request, _artifact_descriptor_read_model(row))

    def open_artifact_stream(self, request: Mapping[str, Any]) -> dict[str, Any]:
        artifact_id = str(request["artifact_id"])
        descriptor = self.product.require_project_reachable_artifact(
            str(request["project_id"]), artifact_id
        )
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
            if range_end_exclusive > int(descriptor["byte_size"]):
                raise InvalidArgumentError("stream byte range exceeds artifact size")
        now = self._clock()
        self._prune_expired_tickets(now)
        if len(self._tickets) >= self._ticket_limit:
            raise ResourceRejectedError(
                "Artifact stream ticket capacity is exhausted",
                details={
                    "reason_code": "STREAM_TICKET_CAPACITY_EXCEEDED",
                    "max_tickets": self._ticket_limit,
                },
            )
        ticket_id = mint_v3_id("stk_")
        expires_at = now + timedelta(seconds=STREAM_TICKET_TTL_SECONDS)
        self._tickets[ticket_id] = {
            "artifact_id": artifact_id,
            "project_id": str(request["project_id"]),
            "expires_at": expires_at,
            "range_start": range_start,
            "range_end_exclusive": range_end_exclusive,
            "runtime_generation": self._runtime_generation,
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

    def consume_artifact_stream(
        self,
        *,
        ticket_id: str,
        project_id: str,
        project_context_revision_id: str,
        runtime_generation: int,
    ) -> Iterator[dict[str, Any]]:
        """Consume one ticket exactly once and lazily emit verified chunks."""

        if (
            isinstance(runtime_generation, bool)
            or not isinstance(runtime_generation, int)
            or runtime_generation < 1
        ):
            raise InvalidArgumentError("runtime_generation must be a positive integer")
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Artifact stream ticket clock must be timezone-aware")
        ticket = self._tickets.get(ticket_id)
        if ticket is None:
            raise TruthPreconditionFailedError(
                "Artifact stream ticket is not available",
                details={"reason_code": "STREAM_TICKET_NOT_AVAILABLE"},
            )
        if ticket["expires_at"] <= now:
            del self._tickets[ticket_id]
            self._prune_expired_tickets(now)
            raise TruthPreconditionFailedError(
                "Artifact stream ticket has expired",
                details={"reason_code": "STREAM_TICKET_EXPIRED"},
            )
        self._prune_expired_tickets(now)
        if str(ticket["project_id"]) != project_id:
            raise TruthPreconditionFailedError(
                "Artifact stream ticket belongs to another project",
                details={"reason_code": "STREAM_TICKET_PROJECT_MISMATCH"},
            )
        self.product.require_project_context_ownership(
            project_id, project_context_revision_id
        )
        bound_generation = ticket["runtime_generation"]
        if bound_generation is not None and bound_generation != runtime_generation:
            raise TruthPreconditionFailedError(
                "Artifact stream ticket belongs to another runtime generation",
                details={"reason_code": "STREAM_TICKET_GENERATION_MISMATCH"},
            )
        ticket["runtime_generation"] = runtime_generation
        artifact_id = str(ticket["artifact_id"])
        descriptor = self.product.require_project_reachable_artifact(
            project_id, artifact_id
        )
        range_start = (
            0 if ticket["range_start"] is None else int(ticket["range_start"])
        )
        range_end_exclusive = (
            int(descriptor["byte_size"])
            if ticket["range_end_exclusive"] is None
            else int(ticket["range_end_exclusive"])
        )
        # Consumption starts only after every reusable scope/generation check;
        # any byte or integrity failure after this point burns the ticket.
        del self._tickets[ticket_id]
        with self.product.artifact_store.open_verified(
            artifact_id,
            expected_sha256=str(descriptor["sha256"]),
            expected_byte_size=int(descriptor["byte_size"]),
        ) as handle:
            handle.seek(range_start)
            offset = range_start
            remaining = range_end_exclusive - range_start
            while remaining > 0:
                chunk = handle.read(min(STREAM_CHUNK_MAX_BYTES, remaining))
                if not chunk:
                    raise TruthPreconditionFailedError(
                        "Artifact stream ended before the admitted range",
                        details={"reason_code": "ARTIFACT_STREAM_TRUNCATED"},
                    )
                remaining -= len(chunk)
                yield {
                    "kind": "artifactStream.chunk",
                    "ticket_id": ticket_id,
                    "artifact_id": artifact_id,
                    "offset": offset,
                    "payload_base64": base64.b64encode(chunk).decode("ascii"),
                    "chunk_sha256": hashlib.sha256(chunk).hexdigest(),
                }
                offset += len(chunk)
        yield {
            "kind": "artifactStream.complete",
            "ticket_id": ticket_id,
            "artifact_id": artifact_id,
            "total_byte_count": range_end_exclusive - range_start,
            "artifact_sha256": str(descriptor["sha256"]),
            "range_start": range_start,
            "range_end_exclusive": range_end_exclusive,
        }

    def handle_stream_control(
        self, kind: str, message: Mapping[str, Any]
    ) -> Iterator[dict[str, Any]]:
        if kind != "artifactStream.consume":
            raise InvalidArgumentError("unknown artifact-stream control kind")
        if message.get("protocol_version") != "v3.artifact-stream/1.0.0":
            raise InvalidArgumentError("unsupported artifact-stream protocol version")
        return self.consume_artifact_stream(
            ticket_id=str(message["ticket_id"]),
            project_id=str(message["project_id"]),
            project_context_revision_id=str(
                message["project_context_revision_id"]
            ),
            runtime_generation=message["runtime_generation"],
        )

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

    def handle_export_control(
        self, kind: str, message: Mapping[str, Any]
    ) -> dict[str, Any]:
        if message.get("protocol_version") != "v3.artifact-export/1.0.0":
            raise InvalidArgumentError("unsupported artifact-export protocol version")
        common = {
            "project_id": str(message["project_id"]),
            "project_context_revision_id": str(
                message["project_context_revision_id"]
            ),
            "task_id": str(message["task_id"]),
            "destination_token": str(message["destination_token"]),
        }
        if kind == "artifactExport.complete":
            return self.product.execution.complete_artifact_export(
                **common,
                display_name=str(message["display_name"]),
                artifact_id=str(message["artifact_id"]),
                sha256=str(message["sha256"]),
                byte_size=message["byte_size"],
                completed_at=str(message["completed_at"]),
            )
        if kind == "artifactExport.fail":
            return self.product.execution.fail_artifact_export(
                **common,
                reason_code=str(message["reason_code"]),
            )
        raise InvalidArgumentError("unknown artifact-export control kind")

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


class UnavailableBacktestFacade:
    """Wire-compatible production denial for the unclosed formal contract.

    The frozen operations remain DTO-validated, but normal product composition
    must not execute the legacy synchronous/checkpoint-promising implementation.
    The additive ProductEntry research backtest is the V1.1 product path.
    """

    def handlers(self) -> dict[str, Any]:
        return {
            "BacktestService.v1.submitBacktest": self._unavailable,
            "BacktestService.v1.createExperiment": self._unavailable,
            "BacktestService.v1.getExperiment": self._unavailable,
            "BacktestService.v1.expandExperiment": self._unavailable,
        }

    @staticmethod
    def _unavailable(_request: Mapping[str, Any]) -> dict[str, Any]:
        raise CapabilityUnavailableError(
            "formal BacktestService execution contract is not closed",
            details={"reason_code": FORMAL_BACKTEST_UNAVAILABLE_REASON},
        )


class ResultFacade:
    SERVICE = "ResultService"

    def __init__(self, product: ProductRuntime) -> None:
        self.product = product

    def handlers(self) -> dict[str, Any]:
        return {
            "ResultService.v1.reconcileLedger": self.reconcile_ledger,
            "ResultService.v1.finalizeResult": self.finalize_result,
            "ResultService.v1.getResult": self.get_result,
            "ResultService.v1.compareResults": self.compare_results,
        }

    def reconcile_ledger(self, request: Mapping[str, Any]) -> dict[str, Any]:
        from .product_results import ResultReconcileSubmission
        from .request_router import current_request_deadline_at

        outcome = self.product.results.submit_reconcile(
            ResultReconcileSubmission(
                project_id=str(request["project_id"]),
                project_context_revision_id=str(
                    request["project_context_revision_id"]
                ),
                backtest_run_id=str(request["backtest_run_id"]),
                ledger_manifest_artifact_id=str(
                    request["ledger_manifest_artifact_id"]
                ),
                reconciliation_profile_id=str(
                    request["reconciliation_profile_id"]
                ),
                idempotency_key=str(request["idempotency_key"]),
                execution_deadline_at=current_request_deadline_at(),
            )
        )
        return _accepted(
            request,
            str(outcome["task_id"]),
            str(outcome["run_id"]),
            outcome.get("event_cursor"),
        )

    def finalize_result(self, request: Mapping[str, Any]) -> dict[str, Any]:
        from .product_results import ResultFinalizeSubmission
        from .request_router import current_request_deadline_at

        analytics_spec = request.get("analytics_spec")
        if not isinstance(analytics_spec, Mapping):
            raise InvalidArgumentError("analytics_spec must be an object")
        outcome = self.product.results.submit_finalize(
            ResultFinalizeSubmission(
                project_id=str(request["project_id"]),
                project_context_revision_id=str(
                    request["project_context_revision_id"]
                ),
                backtest_run_id=str(request["backtest_run_id"]),
                reconciliation_artifact_id=str(
                    request["reconciliation_artifact_id"]
                ),
                analytics_spec=analytics_spec,
                idempotency_key=str(request["idempotency_key"]),
                execution_deadline_at=current_request_deadline_at(),
            )
        )
        return _accepted(
            request,
            str(outcome["task_id"]),
            str(outcome["run_id"]),
            outcome.get("event_cursor"),
        )

    def get_result(self, request: Mapping[str, Any]) -> dict[str, Any]:
        page = request.get("page")
        if not isinstance(page, Mapping):
            raise InvalidArgumentError("page must be an object")
        result_id = str(request["result_id"])
        result = self.product.require_result(result_id)
        if str(result["project_id"]) != str(request["project_id"]):
            raise TruthPreconditionFailedError(
                "result belongs to a different project"
            )
        connection = self.product._connection(read_only=True)
        try:
            product_intent_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM publication_intent "
                    "WHERE project_id=? AND run_id=?",
                    (
                        str(result["project_id"]),
                        str(result["backtest_run_id"]),
                    ),
                ).fetchone()[0]
            )
        finally:
            connection.close()
        if product_intent_count == 0:
            return self._legacy_summary(request, result)
        read_model = self.product.results.get_result(
            project_id=str(request["project_id"]),
            project_context_revision_id=str(
                request["project_context_revision_id"]
            ),
            result_id=result_id,
            section=str(request["section"]),
            page=page,
        )
        return {
            "request_id": request["request_id"],
            # The bounded Product projection is usable, but the frozen service
            # remains incomplete because comparison and checkpoint/resume
            # promises are not closed.
            "truth_state": "UNAVAILABLE",
            "read_model": read_model,
        }

    def _legacy_summary(
        self, request: Mapping[str, Any], result: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Preserve internal V1.0 read compatibility without Product promotion."""
        if str(request["section"]) != "summary":
            raise InvalidArgumentError(
                "legacy Result projection supports only the summary section"
            )
        connection = self.product._connection(read_only=True)
        try:
            run_row = connection.execute(
                "SELECT code_version FROM run WHERE run_id=?",
                (str(result["backtest_run_id"]),),
            ).fetchone()
        finally:
            connection.close()
        result_artifact = None
        references = self.product.references(
            str(result["backtest_run_id"]), RUN_RESULT_REFERENCE_ROLE
        )
        if references:
            artifact_id = str(references[0]["artifact_id"])
            artifact_row = self.product.require_published_artifact(artifact_id)
            result_artifact = _artifact_descriptor_read_model(artifact_row)
        return _response(
            request,
            {
                "read_model_version": "v3.result/1.0",
                "result_id": str(result["result_id"]),
                "project_id": str(result["project_id"]),
                "backtest_run_id": str(result["backtest_run_id"]),
                "code_version": (
                    None if run_row is None else str(run_row["code_version"])
                ),
                "build_manifest_id": BUILD_MANIFEST_ID,
                "state": str(result["state"]),
                "ledger_manifest_artifact_id": str(
                    result["ledger_manifest_artifact_id"]
                ),
                "reconciliation_artifact_id": (
                    None
                    if result["reconciliation_artifact_id"] is None
                    else str(result["reconciliation_artifact_id"])
                ),
                "result_artifact": result_artifact,
                "lineage_hash": str(result["lineage_hash"]),
                "created_at": str(result["created_at"]),
                "finalized_at": (
                    None
                    if result.get("finalized_at") is None
                    else str(result["finalized_at"])
                ),
            },
        )

    @staticmethod
    def compare_results(_request: Mapping[str, Any]) -> dict[str, Any]:
        raise CapabilityUnavailableError(
            "Result comparison is not available in V1.1",
            details={"reason_code": "RESULT_COMPARISON_NOT_AVAILABLE"},
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
            "ProductEntryService.v1.submitResearch": self.submit_research,
            "ProductEntryService.v1.importLocalDataset": self.import_local_dataset,
            "ProductEntryService.v1.submitFactorStudy": self.submit_factor_study,
            "ProductEntryService.v1.previewResearchStrategy": self.preview_research_strategy,
            "ProductEntryService.v1.publishResearchStrategy": self.publish_research_strategy,
            "ProductEntryService.v1.previewResearchBacktest": self.preview_research_backtest,
            "ProductEntryService.v1.submitResearchBacktest": self.submit_research_backtest,
            "ProductEntryService.v1.getProjectHome": self.get_project_home,
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

    def submit_research(self, request: Mapping[str, Any]) -> dict[str, Any]:
        from .request_router import current_request_deadline_at

        outcome = self.product.execution.submit_research(
            ProductResearchSubmission(
                project_id=str(request["project_id"]),
                project_context_revision_id=str(request["project_context_revision_id"]),
                research_profile_id=str(request["research_profile_id"]),
                strategy_profile_id=str(request["strategy_profile_id"]),
                source=request["source"],
                idempotency_key=str(request["idempotency_key"]),
                execution_deadline_at=current_request_deadline_at(),
            )
        )
        return {
            "request_id": request["request_id"],
            "truth_state": "DEMO",
            "read_model": {
                "read_model_version": "v3.product-entry-research/1.0",
                **outcome,
            },
        }

    def import_local_dataset(self, request: Mapping[str, Any]) -> dict[str, Any]:
        from .product_data import ProductLocalDataSubmission
        from .request_router import current_request_deadline_at

        outcome = self.product.data.submit(
            ProductLocalDataSubmission(
                project_id=str(request["project_id"]),
                project_context_revision_id=str(
                    request["project_context_revision_id"]
                ),
                source=request["source"],
                idempotency_key=str(request["idempotency_key"]),
                execution_deadline_at=current_request_deadline_at(),
            )
        )
        return {
            "request_id": request["request_id"],
            "truth_state": "NOT_FORMAL",
            "read_model": {
                "read_model_version": "v3.product-entry-local-data/1.1",
                **outcome,
            },
        }

    def get_project_home(self, request: Mapping[str, Any]) -> dict[str, Any]:
        from .product_data import ProductDataService
        from .product_backtest import ProductResearchBacktestService
        from .product_factor import ProductFactorStudyService
        from .product_strategy import ProductStrategyService

        project_id = str(request["project_id"])
        supplied_revision_id = str(request["project_context_revision_id"])
        current = self.product.current_revision(project_id)
        current_revision_id = str(current["project_context_revision_id"])
        if current_revision_id != supplied_revision_id:
            raise TruthPreconditionFailedError(
                "getProjectHome requires the current project context revision"
            )
        read_model: dict[str, Any] = {
            "read_model_version": "v3.project-home/1.1",
            "project_id": project_id,
            "project_context_revision_id": current_revision_id,
            "maturity": "PRODUCT_CONNECTED",
            "truth": "NOT_FORMAL",
            "admission": "PRE_ALPHA",
            "local_import_state": "AVAILABLE",
            "data_state": "EMPTY",
            "data_unavailable_reason": "NO_SNAPSHOT",
            "factor_state": "EMPTY",
            "factor_unavailable_reason": "NO_SNAPSHOT",
            "strategy_authoring_profile": ProductStrategyService.bounded_authoring_profile(),
            "backtest_policy_coverage": ProductResearchBacktestService.bounded_policy_coverage(),
            "strategy_state": "EMPTY",
            "strategy_unavailable_reason": "NO_FACTOR_STUDY",
            "backtest_state": "EMPTY",
            "backtest_unavailable_reason": "NO_RESEARCH_STRATEGY",
        }
        snapshot_id = current.get("snapshot_id")
        if snapshot_id is not None:
            try:
                data = ProductDataService(self.product).get_local_dataset(
                    project_id=project_id,
                    project_context_revision_id=current_revision_id,
                    snapshot_id=str(snapshot_id),
                )
            except NotFoundError:
                read_model.update(
                    data_state="UNAVAILABLE",
                    data_unavailable_reason="DATA_READ_MODEL_NOT_AVAILABLE",
                )
            except TruthPreconditionFailedError:
                read_model.update(
                    data_state="UNAVAILABLE",
                    data_unavailable_reason="DATA_READ_MODEL_NOT_AVAILABLE",
                )
            else:
                raw_artifact_id = data["artifact_ids"]["LOCAL_DATA_RAW_FILE"]
                read_model.update(
                    data_state="AVAILABLE",
                    data_unavailable_reason="NONE",
                    data={
                        key: data[key]
                        for key in (
                            "schema_version",
                            "project_id",
                            "project_context_revision_id",
                            "display_name",
                            "truth",
                            "admission",
                            "source_type",
                            "pit_state",
                            "media_type",
                            "row_count",
                            "instrument_count",
                            "date_coverage_start",
                            "date_coverage_end",
                            "partition_count",
                            "universe_role",
                            "quality_status",
                            "validation_profile_id",
                            "capability_reasons",
                            "volume_unit",
                            "amount_unit",
                            "adjustment",
                            "raw_capture_id",
                            "raw_content_hash",
                            "snapshot_id",
                            "normalized_payload_hash",
                            "universe_version_id",
                            "imported_at",
                        )
                    }
                    | {"raw_artifact_id": raw_artifact_id},
                )
            try:
                study = ProductFactorStudyService(self.product).get_latest_factor_study(
                    project_id=project_id,
                    project_context_revision_id=current_revision_id,
                    snapshot_id=str(snapshot_id),
                )
            except NotFoundError:
                read_model.update(
                    factor_state="EMPTY",
                    factor_unavailable_reason="NO_FACTOR_STUDY",
                )
            except TruthPreconditionFailedError:
                read_model.update(
                    factor_state="UNAVAILABLE",
                    factor_unavailable_reason="FACTOR_READ_MODEL_NOT_AVAILABLE",
                )
            else:
                output_names = tuple(study["outputs"])
                visual_preview = tuple(study["visual_preview"])
                daily_results = tuple(study["analysis"]["daily_results"])
                projected_visual_preview = visual_preview[
                    -PRODUCT_FACTOR_HOME_PROJECTION_LIMIT:
                ]
                projected_daily_results = daily_results[
                    -PRODUCT_FACTOR_HOME_PROJECTION_LIMIT:
                ]
                read_model.update(
                    factor_state="AVAILABLE",
                    factor_unavailable_reason="NONE",
                    factor={
                        "schema_version": "v3.project-factor-summary/1.1.0",
                        "truth": study["truth"],
                        "admission": study["admission"],
                        "project_id": study["project_id"],
                        "project_context_revision_id": study[
                            "project_context_revision_id"
                        ],
                        "snapshot_id": study["snapshot_id"],
                        "universe_version_id": study["universe_version_id"],
                        "source_manifest_artifact_id": study[
                            "source_manifest_artifact_id"
                        ],
                        "source_manifest_sha256": study["source_manifest_sha256"],
                        "formula_document_version_id": study[
                            "formula_document_version_id"
                        ],
                        "formula_document_artifact_id": study[
                            "formula_document_artifact_id"
                        ],
                        "analysis_output_name": study["analysis_output_name"],
                        "analysis_artifact_id": study["analysis_artifact_id"],
                        "outputs": tuple(
                            {"name": name, **study["outputs"][name]}
                            for name in output_names
                        ),
                        "visual_preview_total_rows": len(visual_preview),
                        "visual_preview_projection": PRODUCT_FACTOR_HOME_PROJECTION,
                        "visual_preview": tuple(
                            {
                                "session_date": row["session_date"],
                                "instrument_id": row["instrument_id"],
                                "open": row["open"],
                                "high": row["high"],
                                "low": row["low"],
                                "close": row["close"],
                                "volume_shares": row["volume_shares"],
                                "amount_cny": row["amount_cny"],
                                "series": tuple(
                                    {"name": name, "value": row[name]}
                                    for name in output_names
                                ),
                            }
                            for row in projected_visual_preview
                        ),
                        "analysis": {
                            "factor_analysis_result_id": study["analysis"][
                                "factor_analysis_result_id"
                            ],
                            "spec": study["analysis"]["spec"],
                            "aggregate": study["analysis"]["aggregate"],
                            "daily_result_count": len(daily_results),
                            "daily_results_projection": PRODUCT_FACTOR_HOME_PROJECTION,
                            "daily_results": tuple(
                                {
                                    **{
                                        key: value
                                        for key, value in item.items()
                                        if key != "excluded_reason_counts"
                                    },
                                    "excluded_reason_counts": tuple(
                                        {"reason": pair[0], "count": pair[1]}
                                        for pair in item["excluded_reason_counts"]
                                    ),
                                }
                                for item in projected_daily_results
                            ),
                        },
                    },
                )
                try:
                    strategy = ProductStrategyService(self.product).get_latest_strategy(
                        project_id=project_id,
                        project_context_revision_id=current_revision_id,
                    )
                except NotFoundError:
                    read_model.update(
                        strategy_state="EMPTY",
                        strategy_unavailable_reason="NO_RESEARCH_STRATEGY",
                    )
                except TruthPreconditionFailedError:
                    read_model.update(
                        strategy_state="UNAVAILABLE",
                        strategy_unavailable_reason="STRATEGY_READ_MODEL_NOT_AVAILABLE",
                    )
                else:
                    read_model.update(
                        strategy_state="AVAILABLE",
                        strategy_unavailable_reason="NONE",
                        strategy={
                            "schema_version": "v3.project-strategy-summary/1.0.0",
                            "truth": strategy["truth"],
                            "admission": strategy["admission"],
                            "project_id": strategy["project_id"],
                            "project_context_revision_id": strategy[
                                "project_context_revision_id"
                            ],
                            "snapshot_id": strategy["snapshot_id"],
                            "universe_version_id": strategy["universe_version_id"],
                            "research_strategy_spec_id": strategy[
                                "research_strategy_spec_id"
                            ],
                            "strategy_version_id": strategy["strategy_version_id"],
                            "entry_signal_factor_version_id": strategy[
                                "entry_signal_ref"
                            ]["factor_definition_version_id"],
                            "exit_signal_factor_version_id": strategy[
                                "exit_signal_ref"
                            ]["factor_definition_version_id"],
                            "profile_refs": strategy["profile_refs"],
                            "transition_count": strategy["transition_count"],
                            "decision_chain_count": strategy["decision_chain_count"],
                        },
                    )
                    try:
                        backtest = ProductResearchBacktestService(
                            self.product
                        ).get_latest_backtest(
                            project_id=project_id,
                            project_context_revision_id=current_revision_id,
                        )
                    except NotFoundError:
                        read_model.update(
                            backtest_state="EMPTY",
                            backtest_unavailable_reason="NO_VALID_BACKTEST",
                        )
                    except TruthPreconditionFailedError:
                        read_model.update(
                            backtest_state="UNAVAILABLE",
                            backtest_unavailable_reason="BACKTEST_READ_MODEL_NOT_AVAILABLE",
                        )
                    else:
                        read_model.update(
                            backtest_state="AVAILABLE",
                            backtest_unavailable_reason="NONE",
                            backtest={
                                "schema_version": "v3.project-backtest-summary/1.0.0",
                                **{
                                    key: backtest[key]
                                    for key in (
                                        "maturity",
                                        "truth",
                                        "admission",
                                        "project_id",
                                        "project_context_revision_id",
                                        "research_backtest_request_id",
                                        "research_strategy_spec_id",
                                        "snapshot_id",
                                        "universe_version_id",
                                        "run_id",
                                        "run_spec_id",
                                        "result_id",
                                        "backtest_result_id",
                                        "result_artifact_id",
                                        "analytics_id",
                                        "analytics_artifact_id",
                                        "summary_export_artifact_id",
                                        "orders_export_artifact_id",
                                        "fills_export_artifact_id",
                                        "result_lineage_id",
                                        "lineage_artifact_id",
                                        "result_state",
                                        "engine_version",
                                        "order_count",
                                        "fill_count",
                                        "diagnostic_count",
                                        "first_fill_session_date",
                                        "first_effective_session_date",
                                        "assumption_mode",
                                    )
                                },
                            },
                        )
        return {
            "request_id": request["request_id"],
            "truth_state": "NOT_FORMAL",
            "read_model": read_model,
        }

    def submit_factor_study(self, request: Mapping[str, Any]) -> dict[str, Any]:
        from .product_factor import ProductFactorStudySubmission
        from .request_router import current_request_deadline_at

        outcome = self.product.factor.submit(
            ProductFactorStudySubmission(
                project_id=str(request["project_id"]),
                project_context_revision_id=str(
                    request["project_context_revision_id"]
                ),
                formula_source=str(request["formula_source"]),
                analysis_output_name=str(request["analysis_output_name"]),
                idempotency_key=str(request["idempotency_key"]),
                execution_deadline_at=current_request_deadline_at(),
            )
        )
        return {
            "request_id": request["request_id"],
            "truth_state": "NOT_FORMAL",
            "read_model": {
                "read_model_version": "v3.product-entry-factor-study/1.1",
                **outcome,
            },
        }

    def publish_research_strategy(self, request: Mapping[str, Any]) -> dict[str, Any]:
        from .product_strategy import ProductStrategySubmission
        from .request_router import current_request_deadline_at

        text_keys = (
            "project_id",
            "project_context_revision_id",
            "universe_version_id",
            "entry_signal_factor_version_id",
            "exit_signal_factor_version_id",
            "position_sizing",
            "gross_exposure",
            "rebalance",
            "cost_policy_version_id",
            "execution_policy_version_id",
            "risk_policy_set_version_id",
            "initial_cash",
            "assumption_profile_id",
            "idempotency_key",
        )
        values: dict[str, str] = {}
        for key in text_keys:
            value = request.get(key)
            if not isinstance(value, str):
                raise InvalidArgumentError(f"{key} must be text")
            values[key] = value
        max_positions = request.get("max_positions")
        if not isinstance(max_positions, int) or isinstance(max_positions, bool):
            raise InvalidArgumentError("max_positions must be an integer")
        outcome = self.product.strategy.submit(
            ProductStrategySubmission(
                project_id=values["project_id"],
                project_context_revision_id=values["project_context_revision_id"],
                universe_version_id=values["universe_version_id"],
                entry_signal_factor_version_id=values[
                    "entry_signal_factor_version_id"
                ],
                exit_signal_factor_version_id=values[
                    "exit_signal_factor_version_id"
                ],
                position_sizing=values["position_sizing"],
                max_positions=max_positions,
                gross_exposure=values["gross_exposure"],
                rebalance=values["rebalance"],
                cost_policy_version_id=values["cost_policy_version_id"],
                execution_policy_version_id=values[
                    "execution_policy_version_id"
                ],
                risk_policy_set_version_id=values["risk_policy_set_version_id"],
                initial_cash=values["initial_cash"],
                assumption_profile_id=values["assumption_profile_id"],
                idempotency_key=values["idempotency_key"],
                execution_deadline_at=current_request_deadline_at(),
            )
        )
        return {
            "request_id": request["request_id"],
            "truth_state": "NOT_FORMAL",
            "read_model": {
                "read_model_version": "v3.product-entry-research-strategy/1.1",
                **outcome,
            },
        }

    def preview_research_strategy(self, request: Mapping[str, Any]) -> dict[str, Any]:
        from .product_strategy import ProductStrategySubmission

        text_keys = (
            "project_id",
            "project_context_revision_id",
            "universe_version_id",
            "entry_signal_factor_version_id",
            "exit_signal_factor_version_id",
            "position_sizing",
            "gross_exposure",
            "rebalance",
            "cost_policy_version_id",
            "execution_policy_version_id",
            "risk_policy_set_version_id",
            "initial_cash",
            "assumption_profile_id",
        )
        values: dict[str, str] = {}
        for key in text_keys:
            value = request.get(key)
            if not isinstance(value, str):
                raise InvalidArgumentError(f"{key} must be text")
            values[key] = value
        max_positions = request.get("max_positions")
        if not isinstance(max_positions, int) or isinstance(max_positions, bool):
            raise InvalidArgumentError("max_positions must be an integer")
        preview = self.product.strategy.preview(
            ProductStrategySubmission(
                project_id=values["project_id"],
                project_context_revision_id=values["project_context_revision_id"],
                universe_version_id=values["universe_version_id"],
                entry_signal_factor_version_id=values["entry_signal_factor_version_id"],
                exit_signal_factor_version_id=values["exit_signal_factor_version_id"],
                position_sizing=values["position_sizing"],
                max_positions=max_positions,
                gross_exposure=values["gross_exposure"],
                rebalance=values["rebalance"],
                cost_policy_version_id=values["cost_policy_version_id"],
                execution_policy_version_id=values["execution_policy_version_id"],
                risk_policy_set_version_id=values["risk_policy_set_version_id"],
                initial_cash=values["initial_cash"],
                assumption_profile_id=values["assumption_profile_id"],
                idempotency_key="preview:" + str(request["request_id"]),
            )
        )
        return {
            "request_id": request["request_id"],
            "truth_state": "NOT_FORMAL",
            "read_model": preview,
        }

    def submit_research_backtest(self, request: Mapping[str, Any]) -> dict[str, Any]:
        from .product_backtest import ProductResearchBacktestSubmission
        from .request_router import current_request_deadline_at

        text_keys = (
            "project_id",
            "project_context_revision_id",
            "research_strategy_spec_id",
            "session_start",
            "session_end",
            "slippage_bps",
            "daily_volume_participation_rate",
            "idempotency_key",
        )
        values: dict[str, str] = {}
        for key in text_keys:
            value = request.get(key)
            if not isinstance(value, str):
                raise InvalidArgumentError(f"{key} must be text")
            values[key] = value
        try:
            session_start = date.fromisoformat(values["session_start"])
            session_end = date.fromisoformat(values["session_end"])
        except ValueError as error:
            raise InvalidArgumentError(
                "session_start and session_end must be ISO calendar dates"
            ) from error
        if (
            session_start.isoformat() != values["session_start"]
            or session_end.isoformat() != values["session_end"]
        ):
            raise InvalidArgumentError(
                "session_start and session_end must be canonical ISO dates"
            )
        outcome = self.product.backtest.submit(
            ProductResearchBacktestSubmission(
                project_id=values["project_id"],
                project_context_revision_id=values[
                    "project_context_revision_id"
                ],
                research_strategy_spec_id=values["research_strategy_spec_id"],
                session_start=session_start,
                session_end=session_end,
                slippage_bps=values["slippage_bps"],
                daily_volume_participation_rate=values[
                    "daily_volume_participation_rate"
                ],
                idempotency_key=values["idempotency_key"],
                execution_deadline_at=current_request_deadline_at(),
            )
        )
        return {
            "request_id": request["request_id"],
            "truth_state": "NOT_FORMAL",
            "read_model": {
                "read_model_version": "v3.product-entry-research-backtest/1.1",
                **outcome,
            },
        }

    def preview_research_backtest(self, request: Mapping[str, Any]) -> dict[str, Any]:
        from .product_backtest import ProductResearchBacktestSubmission

        text_keys = (
            "project_id",
            "project_context_revision_id",
            "research_strategy_spec_id",
            "session_start",
            "session_end",
            "slippage_bps",
            "daily_volume_participation_rate",
        )
        values: dict[str, str] = {}
        for key in text_keys:
            value = request.get(key)
            if not isinstance(value, str):
                raise InvalidArgumentError(f"{key} must be text")
            values[key] = value
        try:
            session_start = date.fromisoformat(values["session_start"])
            session_end = date.fromisoformat(values["session_end"])
        except ValueError as error:
            raise InvalidArgumentError(
                "session_start and session_end must be ISO calendar dates"
            ) from error
        if (
            session_start.isoformat() != values["session_start"]
            or session_end.isoformat() != values["session_end"]
        ):
            raise InvalidArgumentError(
                "session_start and session_end must be canonical ISO dates"
            )
        preview = self.product.backtest.preview(
            ProductResearchBacktestSubmission(
                project_id=values["project_id"],
                project_context_revision_id=values[
                    "project_context_revision_id"
                ],
                research_strategy_spec_id=values["research_strategy_spec_id"],
                session_start=session_start,
                session_end=session_end,
                slippage_bps=values["slippage_bps"],
                daily_volume_participation_rate=values[
                    "daily_volume_participation_rate"
                ],
                idempotency_key="preview:" + str(request["request_id"]),
            )
        )
        return {
            "request_id": request["request_id"],
            "truth_state": "NOT_FORMAL",
            "read_model": preview,
        }


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
        UnavailableBacktestFacade(),
        ResultFacade(product),
        ProductEntryFacade(product),
    )


__all__ = [
    "ArtifactFacade",
    "BacktestFacade",
    "UnavailableBacktestFacade",
    "ProductEntryFacade",
    "ProjectSessionFacade",
    "ResultFacade",
    "TaskFacade",
    "build_product_facades",
]
