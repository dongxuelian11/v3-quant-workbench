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
from .request_router import OperationHandler, RequestRouter


@dataclass(frozen=True)
class RuntimePorts:
    operation_handlers: Mapping[str, OperationHandler] = field(default_factory=dict)
    capabilities: Sequence[Capability] = field(default_factory=tuple)
    event_replay: DurableEventReplayPort | None = None
    startup_reconcile: Callable[[AcceptedSupervisor], None] = lambda _accepted: None
    prepare_shutdown: Callable[[str | None], None] = lambda _deadline: None
    commit_shutdown: Callable[[], None] = lambda: None


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
        self.health = RuntimeHealth(self.backend_instance_id)

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
        write_frame(sink, {"kind": "events.replayComplete", "last_sequence": last})

    def _prepare_shutdown(self, message: Mapping[str, Any], sink: BinaryIO) -> None:
        if set(message) != {"kind", "deadline_at"}:
            raise ProtocolViolation("runtime.prepareShutdown fields do not match the closed wire shape")
        deadline = message["deadline_at"]
        if deadline is not None and not isinstance(deadline, str):
            raise ProtocolViolation("shutdown deadline must be a string or null")
        self.health.accepting_requests = False
        self.ports.prepare_shutdown(deadline)
        write_frame(sink, {"kind": "runtime.shutdownReady", "deadline_at": deadline})


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
