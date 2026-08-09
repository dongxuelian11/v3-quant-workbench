from __future__ import annotations

import unittest

try:
    from .helpers import PROJECT_ID, make_supervisor, run_identity
except ImportError:
    from helpers import PROJECT_ID, make_supervisor, run_identity  # type: ignore[no-redef]

from v3_backend.control_plane.checkpoint_manager import CheckpointIncompatible
from v3_backend.control_plane.event_replay import EventReplay
from v3_backend.control_plane.task_supervisor import NewRunRequired
from v3_backend.domain.tasks.entities import CheckpointMetadata, RunState, TaskState
from v3_backend.domain.tasks.retry_policy import ErrorCategory
from v3_backend.domain.tasks.state_machine import TaskTransitionContext


class TaskSupervisorTests(unittest.TestCase):
    def test_accept_is_durable_before_notify_and_replay_is_monotonic(self) -> None:
        supervisor, persistence, publisher, _, _ = make_supervisor()
        task, run, attempt = supervisor.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        self.assertEqual(persistence.trace[:7], [
            "aggregate_mutated", "aggregate_mutated", "aggregate_mutated",
            "event_appended", "event_appended", "event_appended", "commit",
        ])
        self.assertEqual(persistence.trace[7:], ["notify", "notify", "notify"])
        self.assertEqual([event.project_sequence for event in publisher.events], [1, 2, 3])
        replay = EventReplay(persistence).after(PROJECT_ID, 1)
        self.assertEqual([event.project_sequence for event in replay], [2, 3])
        self.assertEqual((task.active_run_id, run.run_id, attempt.run_id), (run.run_id,) * 3)

    def test_retry_creates_new_attempt_and_changed_input_requires_new_run(self) -> None:
        supervisor, persistence, _, _, _ = make_supervisor()
        task, run, first = supervisor.accept(PROJECT_ID, "BacktestService.v1.run", run_identity())
        supervisor.transition_task(task.task_id, "ATTEMPT_STARTED", TaskTransitionContext(active_lease_persisted=True))
        supervisor.transition_attempt(first.attempt_id, "ATTEMPT_FAILED", error_category="TRANSIENT_IO")
        supervisor.transition_task(task.task_id, "ATTEMPT_FAILED_NO_RETRY", TaskTransitionContext(error_persisted=True))
        second = supervisor.retry(task.task_id, first.attempt_id, run.identity, ErrorCategory.TRANSIENT_IO)
        self.assertNotEqual(first.attempt_id, second.attempt_id)
        self.assertEqual(second.run_id, first.run_id)
        self.assertEqual(second.ordinal, 2)
        self.assertEqual(persistence.tasks[task.task_id].execution_epoch, 1)
        with self.assertRaises(NewRunRequired):
            supervisor.retry(task.task_id, first.attempt_id, run_identity("b" * 64), ErrorCategory.TRANSIENT_IO)

    def test_checkpoint_resume_requires_exact_compatibility_and_new_attempt(self) -> None:
        supervisor, persistence, _, _, checkpoints = make_supervisor()
        task, run, first = supervisor.accept(PROJECT_ID, "StudyService.v1.run", run_identity())
        supervisor.transition_task(task.task_id, "PAUSE_REQUESTED", TaskTransitionContext(supports_checkpoint=True))
        supervisor.transition_task(task.task_id, "CHECKPOINT_PUBLISHED", TaskTransitionContext())
        checkpoint = CheckpointMetadata(
            artifact_id="art_sha256_" + "c" * 64,
            run_id=run.run_id,
            input_hash=run.identity.normalized_input_hash,
            code_version=run.identity.code_version,
            environment_profile=run.identity.environment_profile,
            compatibility_hash="d" * 64,
            created_by_attempt_id=first.attempt_id,
        )
        checkpoints.publish(checkpoint)
        resumed = supervisor.resume(task.task_id, checkpoint.artifact_id, run.identity, "d" * 64)
        self.assertNotEqual(resumed.attempt_id, first.attempt_id)
        self.assertEqual(resumed.resume_checkpoint_artifact_id, checkpoint.artifact_id)
        self.assertEqual(persistence.tasks[task.task_id].state, TaskState.QUEUED)
        with self.assertRaises(CheckpointIncompatible):
            checkpoints.validate_resume(checkpoint.artifact_id, run, "e" * 64)

    def test_cancel_is_persisted_and_notified_before_worker_signal(self) -> None:
        supervisor, persistence, _, _, _ = make_supervisor()
        task, _, attempt = supervisor.accept(PROJECT_ID, "DatasetService.v1.materialize", run_identity())
        supervisor.request_cancel(task.task_id, lambda attempt_id: persistence.trace.append("signal"))
        last_commit = max(i for i, value in enumerate(persistence.trace) if value == "commit")
        last_notify = max(i for i, value in enumerate(persistence.trace) if value == "notify")
        signal = persistence.trace.index("signal")
        self.assertLess(last_commit, last_notify)
        self.assertLess(last_notify, signal)
        self.assertEqual(persistence.tasks[task.task_id].state, TaskState.CANCEL_REQUESTED)
        supervisor.transition_attempt(attempt.attempt_id, "ATTEMPT_CANCELLED")
        cancelled = supervisor.transition_task(
            task.task_id,
            "WORKER_CANCELLED_OR_TERMINATED",
            TaskTransitionContext(cleanup_complete=True),
        )
        self.assertEqual(cancelled.state, TaskState.CANCELLED)

    def test_run_becomes_active_then_terminal_only_after_attempt_and_task_terminal(self) -> None:
        supervisor, persistence, _, _, _ = make_supervisor()
        task, run, attempt = supervisor.accept(PROJECT_ID, "ModelService.v1.train", run_identity())
        for event in ("LEASE_GRANTED", "WORKER_DISPATCHED", "WORKER_ACKNOWLEDGED"):
            supervisor.transition_attempt(attempt.attempt_id, event)
        supervisor.mark_task_started_for_attempt(attempt.attempt_id)
        self.assertEqual(persistence.runs[run.run_id].state, RunState.ACTIVE)
        with self.assertRaises(ValueError):
            supervisor.finalize_run(task.task_id)
        supervisor.transition_attempt(attempt.attempt_id, "ATTEMPT_SUCCEEDED")
        supervisor.transition_task(
            task.task_id,
            "ALL_REQUIRED_ARTIFACTS_PUBLISHED",
            TaskTransitionContext(successful_attempt=True, publication_committed=True),
        )
        finalized = supervisor.finalize_run(task.task_id)
        self.assertEqual(finalized.state, RunState.TERMINAL)

    def test_batch_partial_is_derived_and_only_failed_child_is_retried(self) -> None:
        supervisor, persistence, _, _, _ = make_supervisor()
        ok_task, ok_run, ok_attempt = supervisor.accept(PROJECT_ID, "BacktestService.v1.child", run_identity())
        bad_task, bad_run, bad_attempt = supervisor.accept(PROJECT_ID, "BacktestService.v1.child", run_identity())
        parent, _, _ = supervisor.accept(
            PROJECT_ID,
            "BacktestService.v1.batch",
            run_identity(),
            is_batch=True,
            child_task_ids=(ok_task.task_id, bad_task.task_id),
        )
        for item in (ok_task, bad_task, parent):
            supervisor.transition_task(item.task_id, "ATTEMPT_STARTED", TaskTransitionContext(active_lease_persisted=True))
        for event in ("LEASE_GRANTED", "WORKER_DISPATCHED", "WORKER_ACKNOWLEDGED", "ATTEMPT_SUCCEEDED"):
            supervisor.transition_attempt(ok_attempt.attempt_id, event)
        supervisor.transition_task(
            ok_task.task_id,
            "ALL_REQUIRED_ARTIFACTS_PUBLISHED",
            TaskTransitionContext(successful_attempt=True, publication_committed=True),
        )
        supervisor.transition_attempt(bad_attempt.attempt_id, "ATTEMPT_FAILED", error_category="TRANSIENT_IO")
        supervisor.transition_task(
            bad_task.task_id, "ATTEMPT_FAILED_NO_RETRY", TaskTransitionContext(error_persisted=True)
        )
        derived = supervisor.derive_batch_terminal(parent.task_id)
        self.assertEqual(derived.state, TaskState.PARTIAL)
        created = supervisor.retry_failed_batch_children(
            parent.task_id,
            {ok_task.task_id: ok_run.identity, bad_task.task_id: bad_run.identity},
            ErrorCategory.TRANSIENT_IO,
        )
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].task_id, bad_task.task_id)
        self.assertEqual(len([a for a in persistence.attempts.values() if a.task_id == ok_task.task_id]), 1)
        self.assertEqual(persistence.tasks[parent.task_id].state, TaskState.QUEUED)


if __name__ == "__main__":
    unittest.main()
