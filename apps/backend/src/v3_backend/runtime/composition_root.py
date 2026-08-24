"""Composition seam for transport-only runtime sessions."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, BinaryIO

from v3_backend.contracts.registry import SERVICE_CONTRACTS
from v3_backend.errors.codes import ErrorCode
from v3_backend.errors.mapping import ErrorEnvelopeV1

from .event_publisher import DurableEventReplayPort, EventPublisher
from .framed_stdio import ProtocolViolation, read_frames, write_frame
from .handshake import (
    AcceptedSupervisor,
    Capability,
    create_hello,
    create_ready,
    verify_supervisor_accept,
)
from .health import RuntimeHealth
from .build_manifest import BUILD_MANIFEST
from .request_router import OperationHandler, RequestRouter


@dataclass(frozen=True)
class RuntimePorts:
    operation_handlers: Mapping[str, OperationHandler] = field(default_factory=dict)
    capabilities: Sequence[Capability] = field(default_factory=tuple)
    event_replay: DurableEventReplayPort | None = None
    startup_reconcile: Callable[[AcceptedSupervisor], None] = lambda _accepted: None
    prepare_shutdown: Callable[[str | None], Mapping[str, Any] | None] = lambda _deadline: None
    commit_shutdown: Callable[[], None] = lambda: None
    # Narrow, versioned projectless Product Entry bootstrap seam.  None keeps
    # productEntry.* control frames fail-closed (unknown control frame).
    product_entry_control: Callable[[str, Mapping[str, Any]], dict[str, Any]] | None = None


class RuntimeSession:
    """One authenticated supervisor session over framed binary streams."""

    def __init__(
        self,
        ports: RuntimePorts,
        supervisor_token: bytes,
        backend_version: str,
        backend_instance_id: str | None = None,
    ) -> None:
        self.ports = ports
        self.supervisor_token = supervisor_token
        self.backend_version = backend_version
        self.backend_instance_id = backend_instance_id or str(uuid.uuid4())
        self.router = RequestRouter(ports.operation_handlers)
        self.events = EventPublisher(ports.event_replay)
        self.health = RuntimeHealth(
            self.backend_instance_id,
            backend_version=self.backend_version,
            build_manifest=BUILD_MANIFEST.health_wire(),
        )

    def run(self, source: BinaryIO, sink: BinaryIO) -> None:
        messages = iter(read_frames(source))
        hello = create_hello(
            self.backend_instance_id,
            os.getpid(),
            self.backend_version,
            self.ports.capabilities,
        )
        write_frame(sink, hello)
        try:
            accepted = verify_supervisor_accept(next(messages), self.supervisor_token, hello["nonce"])
        except StopIteration as exc:
            raise ProtocolViolation("transport closed before supervisor.accept") from exc
        self.ports.startup_reconcile(accepted)
        self.events.initialize_cursor(accepted.last_project_event_sequence)
        write_frame(sink, create_ready(self.backend_instance_id))
        for message in messages:
            if message.get("kind") == "request":
                if not self.health.accepting_requests:
                    request_id = message.get("request_id")
                    operation_id = message.get("operation_id")
                    error = ErrorEnvelopeV1(
                        code=ErrorCode.RESOURCE_REJECTED,
                        message="runtime is draining and rejects new commands",
                        details={"reason_code": "RUNTIME_DRAINING"},
                        correlation_id=request_id if isinstance(request_id, str) else None,
                        operation_id=operation_id if isinstance(operation_id, str) else None,
                    )
                    write_frame(sink, {
                        "kind": "response",
                        "request_id": request_id if isinstance(request_id, str) else "00000000-0000-7000-8000-000000000000",
                        "status": "ERROR",
                        "error": error.to_wire(),
                    })
                else:
                    write_frame(sink, self.router.route(message))
            elif message.get("kind") == "events.replay":
                self._handle_replay(message, sink)
            elif message.get("kind") == "events.ack":
                if set(message) != {"kind", "project_sequence"}:
                    raise ProtocolViolation("events.ack fields do not match the closed wire shape")
                self.events.acknowledge(message["project_sequence"])
            elif message.get("kind") == "runtime.health":
                control_request_id, runtime_generation = self._control_correlation(message)
                write_frame(
                    sink,
                    self.health.snapshot(
                        control_request_id=control_request_id,
                        runtime_generation=runtime_generation,
                    ),
                )
            elif str(message.get("kind", "")).startswith("productEntry."):
                self._handle_product_entry(message, sink)
            elif message.get("kind") == "runtime.prepareShutdown":
                self._prepare_shutdown(message, sink)
            elif message.get("kind") == "runtime.commitShutdown":
                control_request_id, runtime_generation = self._control_correlation(message)
                if self.health.accepting_requests:
                    raise ProtocolViolation("runtime.commitShutdown requires a prepared runtime")
                self.ports.commit_shutdown()
                write_frame(sink, {
                    "kind": "runtime.shutdownCommitted",
                    "control_request_id": control_request_id,
                    "runtime_generation": runtime_generation,
                })
                return
            else:
                raise ProtocolViolation("unknown runtime control frame")

    @staticmethod
    def _control_correlation(
        message: Mapping[str, Any],
        payload_fields: set[str] | frozenset[str] = frozenset(),
    ) -> tuple[str, int]:
        required = {"kind", "control_request_id", "runtime_generation", "deadline_at"}
        if set(message) != required | set(payload_fields):
            raise ProtocolViolation("control request fields do not match the closed wire shape")

        control_request_id = message["control_request_id"]
        try:
            parsed_id = uuid.UUID(control_request_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ProtocolViolation("control_request_id must be a canonical UUIDv7") from exc
        if (
            not isinstance(control_request_id, str)
            or str(parsed_id) != control_request_id.lower()
            or parsed_id.version != 7
        ):
            raise ProtocolViolation("control_request_id must be a canonical UUIDv7")

        runtime_generation = message["runtime_generation"]
        if (
            isinstance(runtime_generation, bool)
            or not isinstance(runtime_generation, int)
            or runtime_generation < 1
            or runtime_generation > 9_007_199_254_740_991
        ):
            raise ProtocolViolation("runtime_generation must be a positive safe integer")

        deadline = message["deadline_at"]
        if deadline is not None:
            if not isinstance(deadline, str) or not deadline.endswith("Z"):
                raise ProtocolViolation("deadline_at must be RFC3339 UTC or null")
            try:
                datetime.fromisoformat(deadline[:-1] + "+00:00")
            except ValueError as exc:
                raise ProtocolViolation("deadline_at must be RFC3339 UTC or null") from exc

        return control_request_id, runtime_generation

    def _handle_replay(self, message: Mapping[str, Any], sink: BinaryIO) -> None:
        if set(message) != {"kind", "after_sequence", "limit"}:
            raise ProtocolViolation("events.replay fields do not match the closed wire shape")
        events = self.events.replay(message["after_sequence"], message["limit"])
        for event in events:
            write_frame(sink, event)
        last = events[-1]["project_sequence"] if events else message["after_sequence"]
        watermark = self.events.high_watermark()
        write_frame(sink, {
            "kind": "events.replayComplete",
            "last_sequence": last,
            "next_after_sequence": last,
            "high_watermark": watermark,
            "has_more": last < watermark,
        })

    def _prepare_shutdown(self, message: Mapping[str, Any], sink: BinaryIO) -> None:
        control_request_id, runtime_generation = self._control_correlation(message)
        deadline = message["deadline_at"]
        self.health.accepting_requests = False
        truth = self.ports.prepare_shutdown(deadline)
        response: dict[str, Any] = dict(truth) if isinstance(truth, Mapping) else {}
        response.update({
            "kind": "runtime.shutdownReady",
            "control_request_id": control_request_id,
            "runtime_generation": runtime_generation,
            "deadline_at": deadline,
        })
        response.setdefault("execution_mode", "SYNCHRONOUS_IN_PROCESS")
        response.setdefault("active_task_policy", "DRAIN_BEFORE_SHUTDOWN")
        response.setdefault("checkpoint_resume", "UNAVAILABLE")
        write_frame(sink, response)

    def _handle_product_entry(self, message: Mapping[str, Any], sink: BinaryIO) -> None:
        """Projectless Product Entry bootstrap control protocol.

        A closed, versioned control seam (like runtime.health/shutdown) used
        only for createProject/listProjects before any canonical project
        exists.  Every ASL operation stays project-bound; this seam never
        becomes a generic request bypass.
        """
        from v3_backend.errors.mapping import map_exception

        if self.ports.product_entry_control is None:
            raise ProtocolViolation("product entry control frames are not bound in this runtime")
        kind = str(message["kind"])
        payload_fields = {
            "productEntry.createProject": {"protocol_version", "display_name", "idempotency_key", "notes"},
            "productEntry.listProjects": {"protocol_version", "limit", "after_project_id"},
        }.get(kind)
        if payload_fields is None:
            raise ProtocolViolation("unknown product entry control frame")
        control_request_id, runtime_generation = self._control_correlation(message, payload_fields)
        owner_message = {
            key: value
            for key, value in message.items()
            if key not in {"control_request_id", "runtime_generation", "deadline_at"}
        }
        if not self.health.accepting_requests:
            write_frame(
                sink,
                {
                    "kind": "productEntry.error",
                    "control_request_id": control_request_id,
                    "runtime_generation": runtime_generation,
                    "code": "RESOURCE_REJECTED",
                    "message": "runtime is draining and rejects new commands",
                    "retryable": False,
                },
            )
            return
        try:
            response = dict(self.ports.product_entry_control(kind, owner_message))
            response.update({
                "control_request_id": control_request_id,
                "runtime_generation": runtime_generation,
            })
            write_frame(sink, response)
        except Exception as exc:
            error = map_exception(exc)
            write_frame(
                sink,
                {
                    "kind": "productEntry.error",
                    "control_request_id": control_request_id,
                    "runtime_generation": runtime_generation,
                    "code": error.code.value,
                    "message": error.message,
                    "retryable": error.retryable,
                },
            )


def default_capabilities() -> tuple[Capability, ...]:
    return tuple(
        Capability(code=service, truth_state="UNAVAILABLE", reason_code="ASL_FACADE_NOT_BOUND")
        for service in sorted(SERVICE_CONTRACTS)
    )


def build_runtime(
    supervisor_token: bytes,
    backend_version: str,
    ports: RuntimePorts | None = None,
) -> RuntimeSession:
    selected = ports or RuntimePorts(capabilities=default_capabilities())
    return RuntimeSession(selected, supervisor_token, backend_version)
