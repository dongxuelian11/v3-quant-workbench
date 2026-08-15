from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from v3_backend.contracts.registry import SERVICE_CONTRACTS
from v3_backend.runtime.composition_root import RuntimePorts, RuntimeSession
from v3_backend.runtime.event_publisher import EventPublisher
from v3_backend.runtime.framed_stdio import FrameDecoder, ProtocolViolation, encode_frame
from v3_backend.runtime.handshake import create_hello, token_proof

PROJECT_ID = "prj_00000000000000000000000000"
REVISION_ID = "pcr_00000000000000000000000000"
TOKEN = bytes(range(32))


def event(sequence: int) -> dict[str, object]:
    return {
        "event_id": f"evt-{sequence}",
        "project_id": PROJECT_ID,
        "project_sequence": sequence,
        "event_type": "TASK_UPDATED",
        "occurred_at": "2026-08-09T00:00:00Z",
        "body": {"state": "RUNNING"},
    }


class FixedWatermarkSource:
    """Durable source with `count` contiguous events and a fixed high watermark."""

    def __init__(self, count: int) -> None:
        self.count = count

    def replay(self, after_sequence: int, limit: int):
        end = min(self.count, after_sequence + limit)
        return [event(sequence) for sequence in range(after_sequence + 1, end + 1)]

    def high_watermark(self) -> int:
        return self.count


class GappedSource:
    def replay(self, after_sequence: int, limit: int):
        return [event(3)] if after_sequence == 0 else []

    def high_watermark(self) -> int:
        return 3


def run_session(source, frames) -> list[dict[str, object]]:
    fixed_hello = create_hello("backend", 1, "0.1.0", [], nonce="ab" * 32)
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
    session = RuntimeSession(
        RuntimePorts(event_replay=source),
        TOKEN,
        "0.1.0",
        backend_instance_id="backend",
    )
    data = io.BytesIO(encode_frame(accept) + b"".join(encode_frame(frame) for frame in frames))
    sink = io.BytesIO()
    with patch("v3_backend.runtime.composition_root.create_hello", return_value=fixed_hello):
        session.run(data, sink)
    return FrameDecoder().feed(sink.getvalue())


def replay_frame(after_sequence: int, limit: int = 1000) -> dict[str, object]:
    return {"kind": "events.replay", "after_sequence": after_sequence, "limit": limit}


class ReplayPaginationTests(unittest.TestCase):
    def complete_frames(self, decoded: list[dict[str, object]]) -> list[dict[str, object]]:
        return [frame for frame in decoded if frame["kind"] == "events.replayComplete"]

    def event_frames(self, decoded: list[dict[str, object]]) -> list[dict[str, object]]:
        return [frame for frame in decoded if frame["kind"] == "event"]

    def test_999_events_complete_in_one_page_with_has_more_false(self) -> None:
        decoded = run_session(FixedWatermarkSource(999), [replay_frame(0)])
        self.assertEqual([item["project_sequence"] for item in self.event_frames(decoded)], list(range(1, 1000)))
        self.assertEqual(self.complete_frames(decoded), [{
            "kind": "events.replayComplete",
            "last_sequence": 999,
            "next_after_sequence": 999,
            "high_watermark": 999,
            "has_more": False,
        }])

    def test_1000_events_fill_one_page_exactly(self) -> None:
        decoded = run_session(FixedWatermarkSource(1000), [replay_frame(0)])
        self.assertEqual(len(self.event_frames(decoded)), 1000)
        self.assertEqual(self.complete_frames(decoded), [{
            "kind": "events.replayComplete",
            "last_sequence": 1000,
            "next_after_sequence": 1000,
            "high_watermark": 1000,
            "has_more": False,
        }])

    def test_1001_events_span_two_pages(self) -> None:
        decoded = run_session(FixedWatermarkSource(1001), [replay_frame(0), replay_frame(1000)])
        self.assertEqual([item["project_sequence"] for item in self.event_frames(decoded)], list(range(1, 1002)))
        self.assertEqual(self.complete_frames(decoded), [
            {"kind": "events.replayComplete", "last_sequence": 1000, "next_after_sequence": 1000, "high_watermark": 1001, "has_more": True},
            {"kind": "events.replayComplete", "last_sequence": 1001, "next_after_sequence": 1001, "high_watermark": 1001, "has_more": False},
        ])

    def test_2501_events_span_three_pages_with_stable_high_watermark(self) -> None:
        decoded = run_session(FixedWatermarkSource(2501), [replay_frame(0), replay_frame(1000), replay_frame(2000)])
        self.assertEqual(len(self.event_frames(decoded)), 2501)
        self.assertEqual([item["project_sequence"] for item in self.event_frames(decoded)], list(range(1, 2502)))
        completes = self.complete_frames(decoded)
        self.assertEqual([item["last_sequence"] for item in completes], [1000, 2000, 2501])
        self.assertEqual([item["high_watermark"] for item in completes], [2501, 2501, 2501])
        self.assertEqual([item["has_more"] for item in completes], [True, True, False])

    def test_empty_page_at_watermark_reports_has_more_false(self) -> None:
        decoded = run_session(FixedWatermarkSource(2501), [replay_frame(2501)])
        self.assertEqual(self.event_frames(decoded), [])
        self.assertEqual(self.complete_frames(decoded), [{
            "kind": "events.replayComplete",
            "last_sequence": 2501,
            "next_after_sequence": 2501,
            "high_watermark": 2501,
            "has_more": False,
        }])

    def test_sequence_gap_in_durable_source_fails_closed(self) -> None:
        with self.assertRaises(ProtocolViolation):
            run_session(GappedSource(), [replay_frame(0)])

    def test_publisher_high_watermark_without_source_is_zero(self) -> None:
        self.assertEqual(EventPublisher().high_watermark(), 0)

    def test_negative_watermark_fails_closed(self) -> None:
        class NegativeWatermarkSource(FixedWatermarkSource):
            def high_watermark(self) -> int:
                return -1

        with self.assertRaises(ProtocolViolation):
            run_session(NegativeWatermarkSource(1), [replay_frame(0)])


if __name__ == "__main__":
    unittest.main()
