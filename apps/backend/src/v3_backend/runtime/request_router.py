"""Frozen-operation request routing into injected ASL facade callables."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from v3_backend.contracts.registry import OPERATIONS
from v3_backend.errors.codes import ErrorCode
from v3_backend.errors import ResourceRejectedError
from v3_backend.errors.mapping import ErrorEnvelopeV1, map_exception

from .framed_stdio import ProtocolViolation

OperationHandler = Callable[[Mapping[str, Any]], Mapping[str, Any]]
MAX_RETAINED_RESPONSES = 4096
DEFAULT_RESPONSE_CACHE_TTL_SECONDS = 300.0
MAX_RESPONSE_CACHE_TTL_SECONDS = 3600.0
_REQUEST_DEADLINE_AT: ContextVar[str | None] = ContextVar(
    "v3_request_deadline_at", default=None
)


def current_request_deadline_at() -> str | None:
    """Return the deadline owned by the active transport invocation, if any."""
    return _REQUEST_DEADLINE_AT.get()


@dataclass(frozen=True)
class RequestEnvelope:
    request_id: str
    operation_id: str
    contract_version: str
    project_id: str
    project_context_revision_id: str
    body: Mapping[str, Any]
    idempotency_key: str | None = None
    deadline_at: str | None = None

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> "RequestEnvelope":
        required = {
            "kind",
            "request_id",
            "operation_id",
            "contract_version",
            "project_id",
            "project_context_revision_id",
            "body",
        }
        allowed = required | {"idempotency_key", "deadline_at"}
        if set(value) - allowed or required - set(value):
            raise ValueError("request envelope fields do not match the closed wire shape")
        if value["kind"] != "request":
            raise ValueError("request envelope kind must be request")
        request_id = value["request_id"]
        try:
            parsed_id = uuid.UUID(request_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("request_id must be a canonical UUID") from exc
        if str(parsed_id) != request_id.lower() or parsed_id.version != 7:
            raise ValueError("request_id must be a canonical UUIDv7")
        body = value["body"]
        if not isinstance(body, Mapping):
            raise ValueError("request body must be an object")
        deadline = value.get("deadline_at")
        if deadline is not None:
            if not isinstance(deadline, str) or not deadline.endswith("Z"):
                raise ValueError("deadline_at must be RFC3339 UTC")
            datetime.fromisoformat(deadline[:-1] + "+00:00")
        for name in ("operation_id", "contract_version", "project_id", "project_context_revision_id"):
            if not isinstance(value[name], str) or not value[name]:
                raise ValueError(f"{name} must be a non-empty string")
        key = value.get("idempotency_key")
        if key is not None and (not isinstance(key, str) or not key):
            raise ValueError("idempotency_key must be a non-empty string")
        return cls(
            request_id=request_id,
            operation_id=value["operation_id"],
            contract_version=value["contract_version"],
            project_id=value["project_id"],
            project_context_revision_id=value["project_context_revision_id"],
            body=dict(body),
            idempotency_key=key,
            deadline_at=deadline,
        )


class RequestRouter:
    """Validates transport envelopes and dispatches only frozen operation IDs."""

    def __init__(
        self,
        handlers: Mapping[str, OperationHandler],
        *,
        response_cache_limit: int = MAX_RETAINED_RESPONSES,
        response_cache_ttl_seconds: float = DEFAULT_RESPONSE_CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        unknown = sorted(set(handlers) - set(OPERATIONS))
        if unknown:
            raise ValueError("handlers contain non-frozen operation IDs: " + ", ".join(unknown))
        if not 1 <= response_cache_limit <= MAX_RETAINED_RESPONSES:
            raise ValueError(
                f"response_cache_limit must be between 1 and {MAX_RETAINED_RESPONSES}"
            )
        if not 0 < response_cache_ttl_seconds <= MAX_RESPONSE_CACHE_TTL_SECONDS:
            raise ValueError(
                "response_cache_ttl_seconds must be greater than zero and no more than "
                f"{MAX_RESPONSE_CACHE_TTL_SECONDS}"
            )
        self._handlers = dict(handlers)
        self._response_cache_limit = response_cache_limit
        self._response_cache_ttl_seconds = float(response_cache_ttl_seconds)
        self._clock = clock
        self._seen: OrderedDict[
            str, tuple[str, dict[str, Any], float]
        ] = OrderedDict()

    @property
    def bound_operation_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))

    @property
    def retained_response_count(self) -> int:
        return len(self._seen)

    def route(self, wire: Mapping[str, Any]) -> dict[str, Any]:
        request_id = wire.get("request_id") if isinstance(wire, Mapping) else None
        operation_id = wire.get("operation_id") if isinstance(wire, Mapping) else None
        try:
            envelope = RequestEnvelope.from_wire(wire)
            fingerprint = self._fingerprint(wire)
            now = self._clock()
            self._prune_expired(now)
            prior = self._seen.get(envelope.request_id)
            if prior is not None:
                if prior[0] != fingerprint:
                    raise ProtocolViolation("duplicate request_id has conflicting content")
                self._seen[envelope.request_id] = (
                    prior[0],
                    prior[1],
                    now + self._response_cache_ttl_seconds,
                )
                self._seen.move_to_end(envelope.request_id)
                return dict(prior[1])
            response = self._dispatch(envelope)
            self._seen[envelope.request_id] = (
                fingerprint,
                response,
                now + self._response_cache_ttl_seconds,
            )
            while len(self._seen) > self._response_cache_limit:
                self._seen.popitem(last=False)
            return dict(response)
        except ProtocolViolation:
            raise
        except Exception as exc:
            error = map_exception(exc)
            if operation_id is not None or request_id is not None:
                error = ErrorEnvelopeV1(
                    code=error.code,
                    message=error.message,
                    retryable=error.retryable,
                    details=error.details,
                    correlation_id=request_id if isinstance(request_id, str) else None,
                    operation_id=operation_id if isinstance(operation_id, str) else None,
                )
            return {
                "kind": "response",
                "request_id": request_id if isinstance(request_id, str) else "00000000-0000-7000-8000-000000000000",
                "status": "ERROR",
                "error": error.to_wire(),
            }

    def _prune_expired(self, now: float) -> None:
        while self._seen:
            request_id, cached = next(iter(self._seen.items()))
            if cached[2] > now:
                return
            del self._seen[request_id]

    def _dispatch(self, envelope: RequestEnvelope) -> dict[str, Any]:
        if envelope.deadline_at is not None:
            deadline = datetime.fromisoformat(envelope.deadline_at[:-1] + "+00:00")
            if deadline <= datetime.now(timezone.utc):
                raise ResourceRejectedError(
                    "request deadline expired before dispatch",
                    details={"reason_code": "DEADLINE_EXPIRED"},
                )
        operation = OPERATIONS.get(envelope.operation_id)
        if operation is None:
            raise ValueError(f"unknown frozen operation ID: {envelope.operation_id}")
        requested_major_minor = ".".join(envelope.contract_version.split(".")[:2])
        offered_major_minor = ".".join(operation.version.split(".")[:2])
        if requested_major_minor != offered_major_minor:
            return self._error_response(
                envelope,
                ErrorEnvelopeV1(
                    code=ErrorCode.VERSION_MISMATCH,
                    message="contract version is incompatible with frozen operation",
                    details={"requested": envelope.contract_version, "offered": operation.version},
                    operation_id=envelope.operation_id,
                    correlation_id=envelope.request_id,
                ),
            )
        body = dict(envelope.body)
        for field, expected in (
            ("request_id", envelope.request_id),
            ("project_id", envelope.project_id),
            ("project_context_revision_id", envelope.project_context_revision_id),
        ):
            if body.get(field) != expected:
                raise ValueError(f"body {field} must match the transport envelope")
        request_dto = operation.validate_request(body)
        handler = self._handlers.get(envelope.operation_id)
        if handler is None:
            return self._error_response(
                envelope,
                ErrorEnvelopeV1(
                    code=ErrorCode.CAPABILITY_UNAVAILABLE,
                    message="operation has no admitted ASL facade binding",
                    details={"reason_code": "ASL_FACADE_NOT_BOUND"},
                    operation_id=envelope.operation_id,
                    correlation_id=envelope.request_id,
                ),
            )
        deadline_token = _REQUEST_DEADLINE_AT.set(envelope.deadline_at)
        try:
            response_body = handler(request_dto)
        finally:
            _REQUEST_DEADLINE_AT.reset(deadline_token)
        validated = operation.validate_response(response_body)
        return {
            "kind": "response",
            "request_id": envelope.request_id,
            "status": "OK",
            "body": validated.to_wire(),
        }

    @staticmethod
    def _error_response(envelope: RequestEnvelope, error: ErrorEnvelopeV1) -> dict[str, Any]:
        return {
            "kind": "response",
            "request_id": envelope.request_id,
            "status": "ERROR",
            "error": error.to_wire(),
        }

    @staticmethod
    def _fingerprint(wire: Mapping[str, Any]) -> str:
        encoded = json.dumps(dict(wire), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
