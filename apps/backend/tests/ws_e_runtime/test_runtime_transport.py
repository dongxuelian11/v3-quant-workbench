from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from v3_backend.contracts.registry import SERVICE_CONTRACTS
from v3_backend.runtime.composition_root import RuntimePorts, RuntimeSession
from v3_backend.runtime.event_publisher import EventPublisher
from v3_backend.runtime.framed_stdio import FrameDecoder, ProtocolViolation, encode_frame
from v3_backend.runtime.handshake import (
    Capability,
    create_hello,
    token_proof,
    verify_supervisor_accept,
)
from v3_backend.runtime.request_router import RequestRouter

REQUEST_ID = "01890f3c-7b5a-7000-8000-000000000001"
HEALTH_CONTROL_ID = "01890f3c-7b5a-7000-8000-000000000003"
PREPARE_CONTROL_ID = "01890f3c-7b5a-7000-8000-000000000004"
COMMIT_CONTROL_ID = "01890f3c-7b5a-7000-8000-000000000005"
PRODUCT_CONTROL_ID = "01890f3c-7b5a-7000-8000-000000000006"
ARTIFACT_CONTROL_ID = "01890f3c-7b5a-7000-8000-000000000007"
EXPORT_CONTROL_ID = "01890f3c-7b5a-7000-8000-000000000008"
PROJECT_ID = "prj_00000000000000000000000000"
REVISION_ID = "pcr_00000000000000000000000000"
TASK_ID = "tsk_00000000000000000000000000"
TOKEN = bytes(range(32))


def get_task_body(request_id: str = REQUEST_ID) -> dict[str, object]:
    return {
        "request_id": request_id,
        "project_id": PROJECT_ID,
        "project_context_revision_id": REVISION_ID,
        "expected_api_version": "1.0",
        "task_id": TASK_ID,
    }


def request(body: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "kind": "request",
        "request_id": REQUEST_ID,
        "operation_id": "TaskService.v1.getTask",
        "contract_version": "1.0.0",
        "project_id": PROJECT_ID,
        "project_context_revision_id": REVISION_ID,
        "body": body or get_task_body(),
    }


class FramingTests(unittest.TestCase):
    def test_fragmented_and_multiple_frames(self) -> None:
        first = encode_frame({"kind": "one", "value": "雪"})
        second = encode_frame({"kind": "two"})
        decoder = FrameDecoder()
        decoded: list[dict[str, object]] = []
        wire = first + second
        for index in range(0, len(wire), 3):
            decoded.extend(decoder.feed(wire[index : index + 3]))
        decoder.finish()
        self.assertEqual(decoded, [{"kind": "one", "value": "雪"}, {"kind": "two"}])

    def test_malformed_and_oversize_frames_fail_closed(self) -> None:
        with self.assertRaises(ProtocolViolation):
            FrameDecoder().feed(b"Content-Length: 2\r\nContent-Type: text/plain\r\n\r\n{}")
        with self.assertRaises(ProtocolViolation):
            FrameDecoder(max_frame_bytes=2).feed(encode_frame({"x": 1}))


class HandshakeTests(unittest.TestCase):
    def accept(self, nonce: str, protocol: str = "v3.local/1.0") -> dict[str, object]:
        return {
            "kind": "supervisor.accept",
            "token_proof": token_proof(TOKEN, nonce),
            "requested_protocol": protocol,
            "requested_asl_versions": {name: "1.0" for name in SERVICE_CONTRACTS},
            "desktop_version": "0.1.0",
            "project_id": PROJECT_ID,
            "project_context_revision_id": REVISION_ID,
            "last_project_event_sequence": 0,
        }

    def test_success_and_capability_enumeration(self) -> None:
        hello = create_hello(
            "backend-instance",
            42,
            "0.1.0",
            [Capability("TaskService", "UNAVAILABLE", "ASL_FACADE_NOT_BOUND")],
            nonce="ab" * 32,
        )
        accepted = verify_supervisor_accept(self.accept(hello["nonce"]), TOKEN, hello["nonce"])
        self.assertEqual(accepted.last_project_event_sequence, 0)
        self.assertEqual(hello["capabilities"][0]["code"], "TaskService")

    def test_incompatible_major_and_bad_proof_fail_closed(self) -> None:
        nonce = "cd" * 32
        with self.assertRaises(ProtocolViolation):
            verify_supervisor_accept(self.accept(nonce, "v3.local/2.0"), TOKEN, nonce)
        message = self.accept(nonce)
        message["token_proof"] = "0" * 64
        with self.assertRaises(ProtocolViolation):
            verify_supervisor_accept(message, TOKEN, nonce)


class RequestRouterTests(unittest.TestCase):
    def test_acc_c1_07_seen_response_cache_expires_by_owned_ttl(self) -> None:
        calls = 0
        now = [0.0]

        def handler(dto: dict[str, object]) -> dict[str, object]:
            nonlocal calls
            calls += 1
            return {"request_id": dto["request_id"], "truth_state": "UNAVAILABLE", "read_model": {}}

        router = RequestRouter(
            {"TaskService.v1.getTask": handler},
            clock=lambda: now[0],
            response_cache_ttl_seconds=5.0,
        )
        original = request()
        router.route(original)
        router.route(original)
        self.assertEqual(calls, 1)
        now[0] = 6.0
        router.route(original)
        self.assertEqual(calls, 2)
        self.assertEqual(router.retained_response_count, 1)

    def test_acc_c1_07_seen_response_cache_stays_bounded_after_4096_requests(self) -> None:
        def handler(dto: dict[str, object]) -> dict[str, object]:
            return {"request_id": dto["request_id"], "truth_state": "UNAVAILABLE", "read_model": {}}

        router = RequestRouter({"TaskService.v1.getTask": handler})
        for index in range(4097):
            request_id = f"01890f3c-7b5a-7000-8000-{index:012x}"
            wire = request(get_task_body(request_id))
            wire["request_id"] = request_id
            self.assertEqual(router.route(wire)["status"], "OK")

        self.assertEqual(router.retained_response_count, 4096)

    def test_acc_c1_06_expired_request_is_rejected_before_dispatch(self) -> None:
        calls: list[str] = []

        def handler(dto: dict[str, object]) -> dict[str, object]:
            calls.append(str(dto["task_id"]))
            return {"request_id": dto["request_id"], "truth_state": "UNAVAILABLE", "read_model": {}}

        expired = request()
        expired["deadline_at"] = "2000-01-01T00:00:00Z"
        response = RequestRouter({"TaskService.v1.getTask": handler}).route(expired)

        self.assertEqual(response["status"], "ERROR")
        self.assertEqual(response["error"]["code"], "RESOURCE_REJECTED")
        self.assertEqual(response["error"]["details"]["reason_code"], "DEADLINE_EXPIRED")
        self.assertEqual(calls, [], "an expired request must never reach the operation handler")

    def test_deadline_accepts_legacy_rfc3339_fractional_precision_beyond_python_microseconds(self) -> None:
        observed: list[object] = []

        def handler(dto: dict[str, object]) -> dict[str, object]:
            observed.append(dto)
            return {"request_id": dto["request_id"], "truth_state": "UNAVAILABLE", "read_model": {}}

        wire = request()
        wire["deadline_at"] = "2099-01-01T00:00:00.123456789Z"
        response = RequestRouter({"TaskService.v1.getTask": handler}).route(wire)

        self.assertEqual(response["status"], "OK")
        self.assertEqual(len(observed), 1)

    def test_operation_correlation_and_unknown_operation(self) -> None:
        calls: list[str] = []

        def handler(dto: dict[str, object]) -> dict[str, object]:
            calls.append(dto["task_id"])
            return {"request_id": dto["request_id"], "truth_state": "UNAVAILABLE", "read_model": {}}

        router = RequestRouter({"TaskService.v1.getTask": handler})
        response = router.route(request())
        self.assertEqual(response["status"], "OK")
        self.assertEqual(response["request_id"], REQUEST_ID)
        self.assertEqual(calls, [TASK_ID])
        unknown_request_id = "01890f3c-7b5a-7000-8000-000000000002"
        unknown = request(get_task_body(unknown_request_id))
        unknown["request_id"] = unknown_request_id
        unknown["operation_id"] = "TaskService.v1.unknown"
        error = router.route(unknown)
        self.assertEqual(error["status"], "ERROR")
        self.assertEqual(error["error"]["code"], "INVALID_ARGUMENT")

    def test_duplicate_same_request_replays_and_conflict_terminates(self) -> None:
        count = 0

        def handler(dto: dict[str, object]) -> dict[str, object]:
            nonlocal count
            count += 1
            return {"request_id": dto["request_id"], "truth_state": "UNAVAILABLE", "read_model": {}}

        router = RequestRouter({"TaskService.v1.getTask": handler})
        original = request()
        self.assertEqual(router.route(original), router.route(original))
        self.assertEqual(count, 1)
        conflicting = request({**get_task_body(), "task_id": "tsk_11111111111111111111111111"})
        with self.assertRaises(ProtocolViolation):
            router.route(conflicting)

    def test_mapped_handler_error_is_replayed_without_reexecution(self) -> None:
        calls = 0

        def handler(dto: dict[str, object]) -> dict[str, object]:
            nonlocal calls
            calls += 1
            raise RuntimeError("side effect outcome is now uncertain")

        router = RequestRouter({"TaskService.v1.getTask": handler})
        original = request()
        first = router.route(original)
        second = router.route(original)

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "ERROR")
        self.assertEqual(calls, 1)
        self.assertEqual(router.retained_response_count, 1)


class FakeReplay:
    def replay(self, after_sequence: int, limit: int) -> list[dict[str, object]]:
        events = [
            {
                "event_id": "evt-2",
                "project_id": PROJECT_ID,
                "project_sequence": 2,
                "event_type": "TASK_UPDATED",
                "occurred_at": "2026-08-09T00:00:00Z",
                "body": {"state": "RUNNING"},
            },
            {
                "event_id": "evt-3",
                "project_id": PROJECT_ID,
                "project_sequence": 3,
                "event_type": "TASK_UPDATED",
                "occurred_at": "2026-08-09T00:00:01Z",
                "body": {"state": "SUCCEEDED"},
            },
        ]
        return events[:limit] if after_sequence == 1 else []


class EventAndShutdownTests(unittest.TestCase):
    def test_event_replay_ack_and_gap_detection(self) -> None:
        publisher = EventPublisher(FakeReplay())
        publisher.initialize_cursor(1)
        events = publisher.replay(1, 1000)
        self.assertEqual([item["project_sequence"] for item in events], [2, 3])
        publisher.acknowledge(3)
        self.assertEqual(publisher.highest_acked, 3)
        with self.assertRaises(ProtocolViolation):
            publisher.accept_live({
                "event_id": "evt-5",
                "project_id": PROJECT_ID,
                "project_sequence": 5,
                "event_type": "TASK_UPDATED",
                "occurred_at": "2026-08-09T00:00:02Z",
                "body": {},
            })

    def test_runtime_health_echoes_closed_control_correlation(self) -> None:
        fixed_hello = create_hello("backend", 1, "0.1.0", [], nonce="de" * 32)
        accept = {
            "kind": "supervisor.accept",
            "token_proof": token_proof(TOKEN, fixed_hello["nonce"]),
            "requested_protocol": "v3.local/1.0",
            "requested_asl_versions": {name: "1.0" for name in SERVICE_CONTRACTS},
            "desktop_version": "0.1.0",
            "project_id": None,
            "project_context_revision_id": None,
            "last_project_event_sequence": 0,
        }
        health_request = {
            "kind": "runtime.health",
            "control_request_id": HEALTH_CONTROL_ID,
            "runtime_generation": 1,
            "deadline_at": "2026-08-23T00:00:30Z",
        }
        source = io.BytesIO(encode_frame(accept) + encode_frame(health_request))
        sink = io.BytesIO()
        session = RuntimeSession(
            RuntimePorts(),
            TOKEN,
            "0.1.0",
            backend_instance_id="backend",
        )

        with patch("v3_backend.runtime.composition_root.create_hello", return_value=fixed_hello):
            session.run(source, sink)

        decoded = FrameDecoder().feed(sink.getvalue())
        self.assertEqual([item["kind"] for item in decoded], [
            "backend.hello",
            "backend.ready",
            "runtime.health",
        ])
        self.assertEqual(decoded[2]["control_request_id"], HEALTH_CONTROL_ID)
        self.assertEqual(decoded[2]["runtime_generation"], 1)

    def test_product_entry_correlation_is_transport_owned(self) -> None:
        fixed_hello = create_hello("backend", 1, "0.1.0", [], nonce="ac" * 32)
        accept = {
            "kind": "supervisor.accept",
            "token_proof": token_proof(TOKEN, fixed_hello["nonce"]),
            "requested_protocol": "v3.local/1.0",
            "requested_asl_versions": {name: "1.0" for name in SERVICE_CONTRACTS},
            "desktop_version": "0.1.0",
            "project_id": None,
            "project_context_revision_id": None,
            "last_project_event_sequence": 0,
        }
        owner_messages: list[dict[str, object]] = []

        def product_entry(kind: str, message: object) -> dict[str, object]:
            owner_messages.append(dict(message))
            return {"kind": "productEntry.projectsListed", "projects": [], "has_more": False}

        request_message = {
            "kind": "productEntry.listProjects",
            "protocol_version": "v3.product-entry/1.0.0",
            "limit": 50,
            "after_project_id": None,
            "control_request_id": PRODUCT_CONTROL_ID,
            "runtime_generation": 1,
            "deadline_at": "2026-08-23T00:00:30Z",
        }
        source = io.BytesIO(encode_frame(accept) + encode_frame(request_message))
        sink = io.BytesIO()
        session = RuntimeSession(
            RuntimePorts(product_entry_control=product_entry),
            TOKEN,
            "0.1.0",
            backend_instance_id="backend",
        )

        with patch("v3_backend.runtime.composition_root.create_hello", return_value=fixed_hello):
            session.run(source, sink)

        decoded = FrameDecoder().feed(sink.getvalue())
        self.assertEqual(decoded[2]["kind"], "productEntry.projectsListed")
        self.assertEqual(decoded[2]["control_request_id"], PRODUCT_CONTROL_ID)
        self.assertEqual(decoded[2]["runtime_generation"], 1)
        self.assertEqual(owner_messages, [{
            "kind": "productEntry.listProjects",
            "protocol_version": "v3.product-entry/1.0.0",
            "limit": 50,
            "after_project_id": None,
        }])

    def test_artifact_stream_consume_emits_correlated_chunks_and_terminal(self) -> None:
        fixed_hello = create_hello("backend", 1, "0.1.0", [], nonce="bc" * 32)
        accept = {
            "kind": "supervisor.accept",
            "token_proof": token_proof(TOKEN, fixed_hello["nonce"]),
            "requested_protocol": "v3.local/1.0",
            "requested_asl_versions": {name: "1.0" for name in SERVICE_CONTRACTS},
            "desktop_version": "0.1.0",
            "project_id": PROJECT_ID,
            "project_context_revision_id": REVISION_ID,
            "last_project_event_sequence": 0,
        }
        owner_messages: list[dict[str, object]] = []

        def artifact_stream(kind: str, message: object):
            owner_messages.append(dict(message))
            yield {
                "kind": "artifactStream.chunk",
                "ticket_id": "stk_01ARZ3NDEKTSV4RRFFQ69G5FAX",
                "artifact_id": "art_sha256_" + "a" * 64,
                "offset": 0,
                "payload_base64": "eA==",
                "chunk_sha256": "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881",
            }
            yield {
                "kind": "artifactStream.complete",
                "ticket_id": "stk_01ARZ3NDEKTSV4RRFFQ69G5FAX",
                "artifact_id": "art_sha256_" + "a" * 64,
                "total_byte_count": 1,
                "artifact_sha256": "a" * 64,
                "range_start": 0,
                "range_end_exclusive": 1,
            }

        request_message = {
            "kind": "artifactStream.consume",
            "protocol_version": "v3.artifact-stream/1.0.0",
            "ticket_id": "stk_01ARZ3NDEKTSV4RRFFQ69G5FAX",
            "project_id": PROJECT_ID,
            "project_context_revision_id": REVISION_ID,
            "control_request_id": ARTIFACT_CONTROL_ID,
            "runtime_generation": 7,
            "deadline_at": "2026-08-24T12:00:00Z",
        }
        source = io.BytesIO(encode_frame(accept) + encode_frame(request_message))
        sink = io.BytesIO()
        session = RuntimeSession(
            RuntimePorts(artifact_stream_control=artifact_stream),
            TOKEN,
            "0.1.0",
            backend_instance_id="backend",
        )
        with patch("v3_backend.runtime.composition_root.create_hello", return_value=fixed_hello):
            session.run(source, sink)
        decoded = FrameDecoder().feed(sink.getvalue())
        self.assertEqual(
            [item["kind"] for item in decoded],
            ["backend.hello", "backend.ready", "artifactStream.chunk", "artifactStream.complete"],
        )
        for frame in decoded[2:]:
            self.assertEqual(frame["control_request_id"], ARTIFACT_CONTROL_ID)
            self.assertEqual(frame["runtime_generation"], 7)
        self.assertEqual(owner_messages, [{
            "kind": "artifactStream.consume",
            "protocol_version": "v3.artifact-stream/1.0.0",
            "ticket_id": "stk_01ARZ3NDEKTSV4RRFFQ69G5FAX",
            "project_id": PROJECT_ID,
            "project_context_revision_id": REVISION_ID,
            "runtime_generation": 7,
        }])

    def test_artifact_export_completion_receipt_is_closed_and_correlated(self) -> None:
        fixed_hello = create_hello("backend", 1, "0.1.0", [], nonce="bd" * 32)
        accept = {
            "kind": "supervisor.accept",
            "token_proof": token_proof(TOKEN, fixed_hello["nonce"]),
            "requested_protocol": "v3.local/1.0",
            "requested_asl_versions": {name: "1.0" for name in SERVICE_CONTRACTS},
            "desktop_version": "0.1.0",
            "project_id": PROJECT_ID,
            "project_context_revision_id": REVISION_ID,
            "last_project_event_sequence": 0,
        }
        owner_messages: list[tuple[str, dict[str, object]]] = []

        def artifact_export(kind: str, message: object) -> dict[str, object]:
            owner_messages.append((kind, dict(message)))
            return {
                "kind": "artifactExport.completed",
                "task_id": TASK_ID,
                "manifest_artifact_id": "art_sha256_" + "c" * 64,
            }

        request_message = {
            "kind": "artifactExport.complete",
            "protocol_version": "v3.artifact-export/1.0.0",
            "project_id": PROJECT_ID,
            "project_context_revision_id": REVISION_ID,
            "task_id": TASK_ID,
            "destination_token": "edc_01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "display_name": "result.json",
            "artifact_id": "art_sha256_" + "a" * 64,
            "sha256": "a" * 64,
            "byte_size": 1,
            "completed_at": "2026-08-24T12:00:00Z",
            "control_request_id": EXPORT_CONTROL_ID,
            "runtime_generation": 7,
            "deadline_at": "2026-08-24T12:00:30Z",
        }
        source = io.BytesIO(encode_frame(accept) + encode_frame(request_message))
        sink = io.BytesIO()
        session = RuntimeSession(
            RuntimePorts(artifact_export_control=artifact_export),
            TOKEN,
            "0.1.0",
            backend_instance_id="backend",
        )
        with patch("v3_backend.runtime.composition_root.create_hello", return_value=fixed_hello):
            session.run(source, sink)
        decoded = FrameDecoder().feed(sink.getvalue())
        self.assertEqual(
            [item["kind"] for item in decoded],
            ["backend.hello", "backend.ready", "artifactExport.completed"],
        )
        self.assertEqual(decoded[2]["control_request_id"], EXPORT_CONTROL_ID)
        self.assertEqual(decoded[2]["runtime_generation"], 7)
        expected_owner = dict(request_message)
        for field in ("control_request_id", "runtime_generation", "deadline_at"):
            expected_owner.pop(field)
        self.assertEqual(owner_messages, [("artifactExport.complete", expected_owner)])

    def test_runtime_graceful_shutdown_sequence(self) -> None:
        prepared: list[str | None] = []
        committed: list[bool] = []
        fixed_hello = create_hello("backend", 1, "0.1.0", [], nonce="ef" * 32)
        accept = {
            "kind": "supervisor.accept",
            "token_proof": token_proof(TOKEN, fixed_hello["nonce"]),
            "requested_protocol": "v3.local/1.0",
            "requested_asl_versions": {name: "1.0" for name in SERVICE_CONTRACTS},
            "desktop_version": "0.1.0",
            "project_id": None,
            "project_context_revision_id": None,
            "last_project_event_sequence": 0,
        }
        source = io.BytesIO(
            encode_frame(accept)
            + encode_frame({
                "kind": "runtime.prepareShutdown",
                "control_request_id": PREPARE_CONTROL_ID,
                "runtime_generation": 1,
                "deadline_at": "2026-08-09T00:00:00Z",
            })
            + encode_frame(request())
            + encode_frame({
                "kind": "runtime.commitShutdown",
                "control_request_id": COMMIT_CONTROL_ID,
                "runtime_generation": 1,
                "deadline_at": "2026-08-09T00:00:00Z",
            })
        )
        sink = io.BytesIO()
        session = RuntimeSession(
            RuntimePorts(
                prepare_shutdown=prepared.append,
                commit_shutdown=lambda: committed.append(True),
            ),
            TOKEN,
            "0.1.0",
            backend_instance_id="backend",
        )
        with patch("v3_backend.runtime.composition_root.create_hello", return_value=fixed_hello):
            session.run(source, sink)
        decoded = FrameDecoder().feed(sink.getvalue())
        self.assertEqual([item["kind"] for item in decoded], [
            "backend.hello",
            "backend.ready",
            "runtime.shutdownReady",
            "response",
            "runtime.shutdownCommitted",
        ])
        self.assertEqual(decoded[3]["status"], "ERROR")
        self.assertEqual(decoded[3]["error"]["details"]["reason_code"], "RUNTIME_DRAINING")
        self.assertEqual(decoded[2]["control_request_id"], PREPARE_CONTROL_ID)
        self.assertEqual(decoded[2]["runtime_generation"], 1)
        self.assertEqual(decoded[4]["control_request_id"], COMMIT_CONTROL_ID)
        self.assertEqual(decoded[4]["runtime_generation"], 1)
        self.assertEqual(prepared, ["2026-08-09T00:00:00Z"])
        self.assertEqual(committed, [True])


if __name__ == "__main__":
    unittest.main()
