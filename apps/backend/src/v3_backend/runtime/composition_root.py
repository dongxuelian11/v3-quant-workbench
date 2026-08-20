"""Composition seam for transport-only runtime sessions."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
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
                if set(message) != {"kind"}:
                    raise ProtocolViolation("runtime.health request has unknown fields")
                write_frame(sink, self.health.snapshot())
            elif str(message.get("kind", "")).startswith("productEntry."):
                self._handle_product_entry(message, sink)
            elif message.get("kind") == "runtime.prepareShutdown":
                self._prepare_shutdown(message, sink)
            elif message.get("kind") == "runtime.commitShutdown":
                if set(message) != {"kind"} or self.health.accepting_requests:
                    raise ProtocolViolation("runtime.commitShutdown requires a prepared runtime")
                self.ports.commit_shutdown()
                write_frame(sink, {"kind": "runtime.shutdownCommitted"})
                return
            else:
                raise ProtocolViolation("unknown runtime control frame")

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
        if set(message) != {"kind", "deadline_at"}:
            raise ProtocolViolation("runtime.prepareShutdown fields do not match the closed wire shape")
        deadline = message["deadline_at"]
        if deadline is not None and not isinstance(deadline, str):
            raise ProtocolViolation("shutdown deadline must be a string or null")
        self.health.accepting_requests = False
        truth = self.ports.prepare_shutdown(deadline)
        response: dict[str, Any] = {
            "kind": "runtime.shutdownReady",
            "deadline_at": deadline,
            "execution_mode": "SYNCHRONOUS_IN_PROCESS",
            "active_task_policy": "DRAIN_BEFORE_SHUTDOWN",
            "checkpoint_resume": "UNAVAILABLE",
        }
        if isinstance(truth, Mapping):
            response.update(dict(truth))
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
        if not self.health.accepting_requests:
            write_frame(
                sink,
                {
                    "kind": "productEntry.error",
                    "code": "RESOURCE_REJECTED",
                    "message": "runtime is draining and rejects new commands",
                    "retryable": False,
                },
            )
            return
        kind = str(message["kind"])
        try:
            write_frame(sink, self.ports.product_entry_control(kind, message))
        except Exception as exc:
            error = map_exception(exc)
            write_frame(
                sink,
                {
                    "kind": "productEntry.error",
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
