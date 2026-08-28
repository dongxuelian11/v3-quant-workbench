from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from v3_backend.control_plane.execution_control import (
    ExecutionControlContext,
    ExecutionControlError,
    OPERATION_RECEIPT_REQUIRED,
    PROGRESS_STALLED,
    json_fingerprint,
)


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 27, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


class _Cancellation:
    def __init__(self) -> None:
        self.cancelled = False

    def is_cancelled(self) -> bool:
        return self.cancelled


class _Progress:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def record_progress(self, **kwargs):
        self.records.append(kwargs)
        return kwargs

    def latest_progress(self, attempt_id: str):
        return None


class _Checkpoint:
    def __init__(self) -> None:
        self.calls = 0

    def request_checkpoint(self, *, reason: str, deadline_at: str) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("checkpoint port unavailable")


class _Receipt:
    def __init__(self) -> None:
        self.operation_receipt_id = "opr_control"
        self.correlation_id = "corr-control"
        self.deadline_at = "2026-08-27T00:10:00Z"
        self.runtime_generation_id = "rgen_control"
        self.state = "ACCEPTED"
        self.attempt_id = "att_control"


class _ReceiptStore:
    def __init__(self) -> None:
        self.value = _Receipt()

    def receipt(self, operation_receipt_id: str) -> _Receipt:
        return self.value

    def transition_receipt(self, operation_receipt_id: str, *, expected_state: str, new_state: str, **kwargs):
        if self.value.state != expected_state:
            raise RuntimeError("receipt state changed")
        self.value.state = new_state
        return self.value


class ExecutionControlTests(unittest.TestCase):
    def _context(
        self,
        deadline: str,
        *,
        clock: _Clock | None = None,
        progress_stall_seconds: object | None = None,
    ) -> ExecutionControlContext:
        return ExecutionControlContext(
            "corr-control",
            "opr_control",
            deadline,
            _Cancellation(),
            _Progress(),
            _Checkpoint(),
            None,
            "rgen_control",
            attempt_id="att_control",
            receipt_persistence=_ReceiptStore(),
            clock=clock,
            progress_stall_seconds=progress_stall_seconds,  # type: ignore[arg-type]
        )

    def test_deadline_wire_shape_is_canonical_and_bounded(self) -> None:
        for value in (
            "2026-08-27T00:00:00Z",
            "2026-08-27T00:00:00.123456Z",
            # RFC3339 permits arbitrary fractional-second precision.  Python
            # compares the parsed instant at microsecond precision while the
            # original wire value remains available for propagation.
            "2026-08-27T00:00:00.1234567Z",
        ):
            self._context(value)
        for value in (
            "2026-08-27T00:00:00+00:00",
            "2026-08-27T00:00:00",
        ):
            with self.assertRaises(ValueError):
                self._context(value)

    def test_progress_stall_window_requires_a_positive_integer(self) -> None:
        for value in (True, 0, -1, 1.5, "1"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self._context("2026-08-27T00:10:00Z", progress_stall_seconds=value)

    def test_progress_persistence_requires_an_attempt_binding_at_construction(self) -> None:
        with self.assertRaisesRegex(ValueError, "attempt_id is required"):
            ExecutionControlContext(
                "corr-control",
                "opr_control",
                "2026-08-27T00:10:00Z",
                _Cancellation(),
                _Progress(),
                None,
                None,
                "rgen_control",
            )

    def test_repeated_identical_progress_does_not_reset_stall_window(self) -> None:
        clock = _Clock()
        checkpoint = _Checkpoint()
        checkpoint.calls = 1
        progress = _Progress()
        context = ExecutionControlContext(
            "corr-control",
            "opr_control",
            "2026-08-27T00:10:00Z",
            _Cancellation(),
            progress,
            checkpoint,
            None,
            "rgen_control",
            attempt_id="att_control",
            receipt_persistence=_ReceiptStore(),
            clock=clock,
            progress_stall_seconds=1,
        )

        context.safe_point("COMPUTING", 1, 2, {"rows": 1})
        clock.now += timedelta(seconds=0.5)
        context.safe_point("COMPUTING", 1, 2, {"rows": 1})
        clock.now += timedelta(seconds=0.6)

        with self.assertRaises(ExecutionControlError) as raised:
            context.safe_point("COMPUTING", 1, 2, {"rows": 1})
        self.assertEqual(raised.exception.code, PROGRESS_STALLED)
        self.assertEqual(checkpoint.calls, 2)
        self.assertEqual(len(progress.records), 2)

    def test_failed_checkpoint_request_does_not_mask_later_stall_retry(self) -> None:
        clock = _Clock()
        context = ExecutionControlContext(
            "corr-control",
            "opr_control",
            "2026-08-27T00:10:00Z",
            _Cancellation(),
            progress := _Progress(),
            checkpoint := _Checkpoint(),
            None,
            "rgen_control",
            attempt_id="att_control",
            receipt_persistence=_ReceiptStore(),
            clock=clock,
            progress_stall_seconds=1,
        )
        context.safe_point("COMPUTING", 1, 2, {"rows": 1})
        clock.now += timedelta(seconds=2)
        with self.assertRaisesRegex(RuntimeError, "checkpoint port unavailable"):
            context.safe_point("COMPUTING", 1, 2, {"rows": 1})
        with self.assertRaises(ExecutionControlError) as raised:
            context.safe_point("COMPUTING", 1, 2, {"rows": 1})
        self.assertEqual(raised.exception.code, PROGRESS_STALLED)
        self.assertEqual(checkpoint.calls, 2)
        self.assertEqual(len(progress.records), 1)

    def test_commit_receipt_owns_finality_after_cancel(self) -> None:
        cancellation = _Cancellation()
        receipts = _ReceiptStore()
        outcome = {"accepted": True}
        context = ExecutionControlContext(
            "corr-control",
            "opr_control",
            "2026-08-27T00:10:00Z",
            cancellation,
            _Progress(),
            None,
            None,
            "rgen_control",
            attempt_id="att_control",
            receipt_persistence=receipts,
            clock=_Clock(),
        )
        context.before_irreversible_commit("CATALOG_COMMIT", json_fingerprint(outcome))
        context.mark_committed(outcome)
        cancellation.cancelled = True
        with self.assertRaises(ExecutionControlError) as raised:
            context.before_irreversible_commit("CATALOG_COMMIT", json_fingerprint(outcome))
        self.assertEqual(raised.exception.code, OPERATION_RECEIPT_REQUIRED)
        self.assertEqual(receipts.value.state, "COMMITTED")

    def test_expected_commit_hash_binds_the_durable_commit_receipt(self) -> None:
        receipts = _ReceiptStore()
        context = ExecutionControlContext(
            "corr-control",
            "opr_control",
            "2026-08-27T00:10:00Z",
            _Cancellation(),
            _Progress(),
            None,
            None,
            "rgen_control",
            attempt_id="att_control",
            receipt_persistence=receipts,
            clock=_Clock(),
        )
        context.before_irreversible_commit("CATALOG_COMMIT", "a" * 64)
        with self.assertRaises(ExecutionControlError) as raised:
            context.mark_committed({"accepted": True})
        self.assertEqual(raised.exception.code, OPERATION_RECEIPT_REQUIRED)
        self.assertEqual(receipts.value.state, "ACCEPTED")

    def test_commit_rejects_non_strict_outcomes_before_receipt_transition(self) -> None:
        receipts = _ReceiptStore()
        context = ExecutionControlContext(
            "corr-control",
            "opr_control",
            "2026-08-27T00:10:00Z",
            _Cancellation(),
            _Progress(),
            None,
            None,
            "rgen_control",
            attempt_id="att_control",
            receipt_persistence=receipts,
            clock=_Clock(),
        )
        for outcome in ({1: "coerced"}, {"value": float("nan")}):
            with self.subTest(outcome=outcome), self.assertRaises(ValueError):
                context.mark_committed(outcome)  # type: ignore[arg-type]
            self.assertEqual(receipts.value.state, "ACCEPTED")

    def test_commit_rejects_noncanonical_artifact_identity_before_receipt_transition(self) -> None:
        receipts = _ReceiptStore()
        context = ExecutionControlContext(
            "corr-control",
            "opr_control",
            "2026-08-27T00:10:00Z",
            _Cancellation(),
            _Progress(),
            None,
            None,
            "rgen_control",
            attempt_id="att_control",
            receipt_persistence=receipts,
            clock=_Clock(),
        )
        with self.assertRaises(ValueError):
            context.mark_committed("artifact-not-canonical")
        self.assertEqual(receipts.value.state, "ACCEPTED")

    def test_commit_marker_cannot_bypass_pre_commit_gate(self) -> None:
        receipts = _ReceiptStore()
        context = ExecutionControlContext(
            "corr-control",
            "opr_control",
            "2026-08-27T00:10:00Z",
            _Cancellation(),
            _Progress(),
            None,
            None,
            "rgen_control",
            attempt_id="att_control",
            receipt_persistence=receipts,
            clock=_Clock(),
        )
        with self.assertRaises(ExecutionControlError) as raised:
            context.mark_committed({"accepted": True})
        self.assertEqual(raised.exception.code, OPERATION_RECEIPT_REQUIRED)
        self.assertEqual(receipts.value.state, "ACCEPTED")

    def test_commit_rejects_receipt_without_exact_attempt_binding(self) -> None:
        receipts = _ReceiptStore()
        receipts.value.attempt_id = None
        context = ExecutionControlContext(
            "corr-control",
            "opr_control",
            "2026-08-27T00:10:00Z",
            _Cancellation(),
            _Progress(),
            None,
            None,
            "rgen_control",
            attempt_id="att_control",
            receipt_persistence=receipts,
            clock=_Clock(),
        )
        with self.assertRaises(ExecutionControlError) as raised:
            context.before_irreversible_commit("CATALOG_COMMIT", "a" * 64)
        self.assertEqual(raised.exception.code, OPERATION_RECEIPT_REQUIRED)
        self.assertEqual(receipts.value.state, "ACCEPTED")

    def test_commit_rejects_receipt_without_generation_binding(self) -> None:
        receipts = _ReceiptStore()
        receipts.value.runtime_generation_id = None
        context = ExecutionControlContext(
            "corr-control",
            "opr_control",
            "2026-08-27T00:10:00Z",
            _Cancellation(),
            _Progress(),
            None,
            None,
            "rgen_control",
            attempt_id="att_control",
            receipt_persistence=receipts,
            clock=_Clock(),
        )
        with self.assertRaises(ExecutionControlError) as raised:
            context.before_irreversible_commit("CATALOG_COMMIT", "a" * 64)
        self.assertEqual(raised.exception.code, "RUNTIME_GENERATION_MISMATCH")
        self.assertEqual(receipts.value.state, "ACCEPTED")


if __name__ == "__main__":
    unittest.main()
