from __future__ import annotations

import unittest

try:
    from .helpers import SRC  # noqa: F401
except ImportError:
    from helpers import SRC  # type: ignore[no-redef]  # noqa: F401

from v3_backend.domain.tasks.entities import AttemptState, RunState, TaskState
from v3_backend.domain.tasks.retry_policy import ErrorCategory, RetryPolicy
from v3_backend.domain.tasks.state_machine import (
    ATTEMPT_TRANSITIONS,
    RUN_TRANSITIONS,
    TASK_TRANSITIONS,
    ImpossibleTransition,
    TaskTransitionContext,
    transition_attempt,
    transition_run,
    transition_task,
)


class TaskStateMachineTests(unittest.TestCase):
    def test_full_task_transition_matrix(self) -> None:
        events = sorted({event for _, event in TASK_TRANSITIONS})
        permissive = TaskTransitionContext(
            supports_checkpoint=True,
            active_lease_persisted=True,
            successful_attempt=True,
            publication_committed=True,
            error_persisted=True,
            cleanup_complete=True,
            is_batch=True,
            retry_epoch=True,
        )
        for state in TaskState:
            for event in events:
                key = (state, event)
                with self.subTest(state=state, event=event):
                    if key in TASK_TRANSITIONS:
                        self.assertEqual(transition_task(state, event, permissive), TASK_TRANSITIONS[key])
                    else:
                        with self.assertRaises(ImpossibleTransition):
                            transition_task(state, event, permissive)

    def test_task_guards_fail_closed(self) -> None:
        guarded = (
            (TaskState.QUEUED, "ATTEMPT_STARTED"),
            (TaskState.RUNNING, "PAUSE_REQUESTED"),
            (TaskState.RUNNING, "ALL_REQUIRED_ARTIFACTS_PUBLISHED"),
            (TaskState.RUNNING, "ATTEMPT_FAILED_NO_RETRY"),
            (TaskState.CANCEL_REQUESTED, "WORKER_CANCELLED_OR_TERMINATED"),
            (TaskState.RUNNING, "CHILDREN_TERMINAL_MIXED"),
            (TaskState.FAILED, "RETRY_SCHEDULED"),
        )
        for state, event in guarded:
            with self.subTest(state=state, event=event), self.assertRaises(ImpossibleTransition):
                transition_task(state, event, TaskTransitionContext())

    def test_full_attempt_transition_matrix_and_terminal_immutability(self) -> None:
        events = sorted({event for _, event in ATTEMPT_TRANSITIONS})
        for state in AttemptState:
            for event in events:
                key = (state, event)
                with self.subTest(state=state, event=event):
                    if key in ATTEMPT_TRANSITIONS:
                        self.assertEqual(transition_attempt(state, event), ATTEMPT_TRANSITIONS[key])
                    else:
                        with self.assertRaises(ImpossibleTransition):
                            transition_attempt(state, event)

    def test_run_matrix_and_terminal_guard(self) -> None:
        self.assertEqual(transition_run(RunState.SEALED, "ATTEMPT_ACTIVATED"), RunState.ACTIVE)
        self.assertEqual(
            transition_run(RunState.ACTIVE, "TASK_TERMINAL_NO_ACTIVE_ATTEMPT", no_active_attempt=True),
            RunState.TERMINAL,
        )
        with self.assertRaises(ImpossibleTransition):
            transition_run(RunState.ACTIVE, "TASK_TERMINAL_NO_ACTIVE_ATTEMPT")
        with self.assertRaises(ImpossibleTransition):
            transition_run(RunState.TERMINAL, "ATTEMPT_ACTIVATED")

    def test_retry_policy_categories_and_exponential_delay(self) -> None:
        policy = RetryPolicy(base_delay_seconds=2, max_delay_seconds=20, max_attempts=4)
        self.assertEqual(policy.decide(ErrorCategory.TRANSIENT_IO, 1).delay_seconds, 2)
        self.assertEqual(policy.decide(ErrorCategory.WORKER_LOST, 3).delay_seconds, 8)
        self.assertFalse(policy.decide(ErrorCategory.TRUTH_PIT_FAILURE, 1).allowed)
        self.assertFalse(policy.decide(ErrorCategory.TRANSIENT_IO, 4).allowed)


if __name__ == "__main__":
    unittest.main()
