from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol

from v3_backend.domain.tasks.entities import (
    ATTEMPT_TERMINAL_STATES,
    Run,
    RunIdentity,
    RunState,
    Task,
    TaskAttempt,
    TaskState,
)
from v3_backend.domain.tasks.events import PendingTaskEvent
from v3_backend.domain.tasks.retry_policy import ErrorCategory, RetryPolicy
from v3_backend.domain.tasks.state_machine import (
    TaskTransitionContext,
    transition_attempt,
    transition_run,
    transition_task,
)

from .checkpoint_manager import CheckpointManager
from .event_log import DurableEventLog
from .persistence import TaskUnitOfWork


class IdentityAllocator(Protocol):
    def new(self, object_type: str) -> str: ...


class NewRunRequired(ValueError):
    pass


class RetryRejected(ValueError):
    pass


def _wire_time(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Task control timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


class TaskSupervisor:
    def __init__(
        self,
        event_log: DurableEventLog,
        identities: IdentityAllocator,
        checkpoints: CheckpointManager,
        retry_policy: RetryPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.event_log = event_log
        self.identities = identities
        self.checkpoints = checkpoints
        self.retry_policy = retry_policy or RetryPolicy()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _event(
        self,
        event_type: str,
        task: Task,
        *,
        run_id: str | None = None,
        attempt_id: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> PendingTaskEvent:
        return PendingTaskEvent(
            event_id=self.identities.new("TaskEvent"),
            event_version="1.0.0",
            project_id=task.project_id,
            task_id=task.task_id,
            run_id=run_id,
            attempt_id=attempt_id,
            event_type=event_type,
            occurred_at=self.clock(),
            payload=payload or {},
        )

    def accept(
        self,
        project_id: str,
        operation_id: str,
        identity: RunIdentity,
        *,
        is_batch: bool = False,
        child_task_ids: tuple[str, ...] = (),
    ) -> tuple[Task, Run, TaskAttempt]:
        task_id = self.identities.new("Task")
        run_id = self.identities.new("Run")
        attempt_id = self.identities.new("TaskAttempt")
        task = Task(task_id, project_id, operation_id, run_id, is_batch=is_batch, child_task_ids=child_task_ids)
        run = Run(run_id, task_id, identity)
        attempt = TaskAttempt(attempt_id, task_id, run_id, 1)

        def mutation(unit: TaskUnitOfWork) -> None:
            unit.add_task(task)
            unit.add_run(run)
            unit.add_attempt(attempt)
            for event_type, event_attempt in (
                ("TASK_ACCEPTED", None),
                ("RUN_SEALED", None),
                ("ATTEMPT_CREATED", attempt.attempt_id),
            ):
                unit.append_event(
                    self._event(
                        event_type,
                        task,
                        run_id=run.run_id,
                        attempt_id=event_attempt,
                        payload={"state": "QUEUED" if event_attempt else "SEALED"},
                    )
                )

        self.event_log.transact(mutation)
        return task, run, attempt

    @staticmethod
    def require_unchanged_run(run: Run, proposed: RunIdentity) -> None:
        if run.identity != proposed:
            raise NewRunRequired("input change requires a new Run")

    @staticmethod
    def _link_attempt_predecessor(
        unit: TaskUnitOfWork,
        *,
        attempt_id: str,
        predecessor_attempt_id: str,
    ) -> None:
        """Persist retry/resume lineage in the SQLite owner UoW.

        ``TaskAttempt`` is intentionally frozen for the PR03 schema change,
        so the relational lineage column is written by the existing SQLite
        Task owner immediately after the aggregate insert.  The in-memory
        test adapter has no relational sidecar and therefore needs no extra
        mutation.
        """

        connection = getattr(unit, "connection", None)
        if connection is None:
            return
        cursor = connection.execute(
            """
            UPDATE task_attempt
            SET retry_of_attempt_id=?
            WHERE attempt_id=? AND retry_of_attempt_id IS NULL
            """,
            (predecessor_attempt_id, attempt_id),
        )
        if cursor.rowcount != 1:
            raise RetryRejected("new Attempt lineage could not be persisted")

    def retry(
        self,
        task_id: str,
        failed_attempt_id: str,
        proposed_identity: RunIdentity,
        category: ErrorCategory,
    ) -> TaskAttempt:
        def mutation(unit: TaskUnitOfWork) -> TaskAttempt:
            task = unit.require_task(task_id)
            run = unit.require_run(task.active_run_id)
            failed = unit.require_attempt(failed_attempt_id)
            if failed.run_id != run.run_id or failed.state not in ATTEMPT_TERMINAL_STATES:
                raise RetryRejected("failed_attempt_id is not terminal in the active Run")
            if failed.terminal_error_category != category.value:
                raise RetryRejected("retry category must match the persisted terminal error")
            self.require_unchanged_run(run, proposed_identity)
            attempts = unit.attempts_for_run(run.run_id)
            if not attempts or attempts[-1].attempt_id != failed_attempt_id:
                raise RetryRejected("only the latest Attempt may be retried")
            decision = self.retry_policy.decide(category, len(attempts))
            if not decision.allowed:
                raise RetryRejected(decision.reason)
            expected = task.state_version
            task.state = transition_task(
                task.state,
                "RETRY_SCHEDULED",
                TaskTransitionContext(retry_epoch=True, is_batch=task.is_batch),
            )
            task.execution_epoch += 1
            unit.save_task(task, expected)
            attempt = TaskAttempt(
                self.identities.new("TaskAttempt"), task.task_id, run.run_id, len(attempts) + 1
            )
            unit.add_attempt(attempt)
            self._link_attempt_predecessor(
                unit,
                attempt_id=attempt.attempt_id,
                predecessor_attempt_id=failed_attempt_id,
            )
            unit.append_event(
                self._event(
                    "ATTEMPT_CREATED",
                    task,
                    run_id=run.run_id,
                    attempt_id=attempt.attempt_id,
                    payload={"retry_of": failed_attempt_id, "delay_seconds": decision.delay_seconds},
                )
            )
            return attempt

        return self.event_log.transact(mutation)

    def resume(
        self,
        task_id: str,
        checkpoint_artifact_id: str,
        proposed_identity: RunIdentity,
        compatibility_hash: str,
    ) -> TaskAttempt:
        def mutation(unit: TaskUnitOfWork) -> TaskAttempt:
            task = unit.require_task(task_id)
            run = unit.require_run(task.active_run_id)
            self.require_unchanged_run(run, proposed_identity)
            checkpoint = self.checkpoints.validate_resume(checkpoint_artifact_id, run, compatibility_hash)
            attempts = unit.attempts_for_run(run.run_id)
            expected = task.state_version
            task.state = transition_task(
                task.state, "RESUME_SCHEDULED", TaskTransitionContext(retry_epoch=True)
            )
            task.execution_epoch += 1
            unit.save_task(task, expected)
            attempt = TaskAttempt(
                self.identities.new("TaskAttempt"),
                task.task_id,
                run.run_id,
                len(attempts) + 1,
                resume_checkpoint_artifact_id=checkpoint.artifact_id,
            )
            unit.add_attempt(attempt)
            predecessors = {item.attempt_id for item in attempts}
            if checkpoint.created_by_attempt_id not in predecessors:
                raise RetryRejected("checkpoint predecessor is outside the active Run")
            self._link_attempt_predecessor(
                unit,
                attempt_id=attempt.attempt_id,
                predecessor_attempt_id=checkpoint.created_by_attempt_id,
            )
            unit.append_event(
                self._event(
                    "ATTEMPT_CREATED",
                    task,
                    run_id=run.run_id,
                    attempt_id=attempt.attempt_id,
                    payload={"resume_checkpoint_artifact_id": checkpoint.artifact_id},
                )
            )
            return attempt

        return self.event_log.transact(mutation)

    def request_cancel(self, task_id: str, signal_worker: Callable[[str], None]) -> None:
        def mutation(unit: TaskUnitOfWork) -> str:
            task = unit.require_task(task_id)
            expected = task.state_version
            task.state = transition_task(task.state, "CANCEL_REQUESTED", TaskTransitionContext())
            unit.save_task(task, expected)
            unit.append_event(self._event("CANCEL_REQUESTED", task, run_id=task.active_run_id))
            attempts = unit.attempts_for_run(task.active_run_id)
            active = [item for item in attempts if item.state not in ATTEMPT_TERMINAL_STATES]
            return active[-1].attempt_id if active else ""

        attempt_id = self.event_log.transact(mutation)
        if attempt_id:
            signal_worker(attempt_id)

    def transition_attempt(self, attempt_id: str, event: str, *, error_category: str | None = None) -> TaskAttempt:
        def mutation(unit: TaskUnitOfWork) -> TaskAttempt:
            attempt = unit.require_attempt(attempt_id)
            task = unit.require_task(attempt.task_id)
            expected = attempt.state_version
            attempt.state = transition_attempt(attempt.state, event)
            if error_category:
                attempt.terminal_error_category = error_category
            unit.save_attempt(attempt, expected)
            unit.append_event(
                self._event(
                    "ATTEMPT_TERMINAL" if attempt.state in ATTEMPT_TERMINAL_STATES else "ATTEMPT_STATE_CHANGED",
                    task,
                    run_id=attempt.run_id,
                    attempt_id=attempt.attempt_id,
                    payload={"state": attempt.state.value, "error_category": error_category},
                )
            )
            return attempt

        return self.event_log.transact(mutation)

    def fail_attempt_before_start(
        self,
        attempt_id: str,
        *,
        error_category: str,
        error_message: str,
        reason_code: str | None = None,
    ) -> TaskAttempt:
        """Atomically close a pre-ACK Attempt and its still-queued Task.

        A worker can exist after ``WORKER_DISPATCHED`` but before the Task has
        entered RUNNING. A failure in that interval must not leave a queued
        Task with a failed Attempt, nor permit a later ACK to open the domain.
        This path is deliberately separate from generic worker-loss handling:
        a pre-start enforcement failure is a terminal admission result.
        """

        def mutation(unit: TaskUnitOfWork) -> TaskAttempt:
            attempt = unit.require_attempt(attempt_id)
            task = unit.require_task(attempt.task_id)
            run = unit.require_run(attempt.run_id)
            if attempt.state in ATTEMPT_TERMINAL_STATES:
                return attempt

            expected_attempt = attempt.state_version
            attempt.state = transition_attempt(attempt.state, "ATTEMPT_FAILED")
            attempt.terminal_error_category = error_category
            unit.save_attempt(attempt, expected_attempt)

            if task.state not in {
                TaskState.SUCCEEDED,
                TaskState.FAILED,
                TaskState.CANCELLED,
                TaskState.PARTIAL,
            }:
                expected_task = task.state_version
                task.state = transition_task(
                    task.state,
                    "ATTEMPT_FAILED_NO_RETRY",
                    TaskTransitionContext(error_persisted=True),
                )
                unit.save_task(task, expected_task)

            if run.state is not RunState.TERMINAL:
                expected_run = run.state_version
                run.state = transition_run(
                    run.state,
                    "TASK_TERMINAL_NO_ACTIVE_ATTEMPT",
                    no_active_attempt=True,
                )
                unit.save_run(run, expected_run)

            # The supplemental PR03 queue owner follows the same terminal
            # decision as the Task aggregate.  Without this write a failed
            # pre-ACK dispatch could leave DISPATCHED control truth pointing
            # at a Task that is already durably FAILED.
            connection = getattr(unit, "connection", None)
            if connection is not None and connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_dispatch_control'"
            ).fetchone() is not None:
                connection.execute(
                    """
                    UPDATE task_dispatch_control
                    SET state='TERMINAL',hold_reason=NULL,
                        user_confirmed_at=NULL,state_version=state_version+1,
                        updated_at=?
                    WHERE task_id=? AND state<>'TERMINAL'
                    """,
                    (_wire_time(self.clock()), task.task_id),
                )

            payload: dict[str, object] = {
                "state": attempt.state.value,
                "error_category": error_category,
                "error_message": error_message[:2048],
            }
            if reason_code is not None:
                payload["reason_code"] = reason_code
            unit.append_event(
                self._event(
                    "ATTEMPT_TERMINAL",
                    task,
                    run_id=attempt.run_id,
                    attempt_id=attempt.attempt_id,
                    payload=payload,
                )
            )
            unit.append_event(
                self._event(
                    "TASK_FAILED",
                    task,
                    run_id=run.run_id,
                    attempt_id=attempt.attempt_id,
                    payload=payload,
                )
            )
            unit.append_event(
                self._event(
                    "RUN_TERMINAL",
                    task,
                    run_id=run.run_id,
                    attempt_id=attempt.attempt_id,
                    payload={"state": run.state.value, "reason_code": reason_code},
                )
            )
            return attempt

        return self.event_log.transact(mutation)

    def assign_lease(self, attempt_id: str, lease_id: str) -> TaskAttempt:
        def mutation(unit: TaskUnitOfWork) -> TaskAttempt:
            attempt = unit.require_attempt(attempt_id)
            task = unit.require_task(attempt.task_id)
            expected = attempt.state_version
            attempt.state = transition_attempt(attempt.state, "LEASE_GRANTED")
            attempt.lease_id = lease_id
            unit.save_attempt(attempt, expected)
            unit.append_event(
                self._event(
                    "LEASE_GRANTED",
                    task,
                    run_id=attempt.run_id,
                    attempt_id=attempt.attempt_id,
                    payload={"lease_id": lease_id},
                )
            )
            return attempt

        return self.event_log.transact(mutation)

    def mark_task_started_for_attempt(self, attempt_id: str) -> Task:
        def mutation(unit: TaskUnitOfWork) -> Task:
            attempt = unit.require_attempt(attempt_id)
            task = unit.require_task(attempt.task_id)
            expected = task.state_version
            task.state = transition_task(
                task.state,
                "ATTEMPT_STARTED",
                TaskTransitionContext(active_lease_persisted=True),
            )
            unit.save_task(task, expected)
            run = unit.require_run(attempt.run_id)
            if run.state.value == "SEALED":
                run_expected = run.state_version
                run.state = transition_run(run.state, "ATTEMPT_ACTIVATED")
                unit.save_run(run, run_expected)
            unit.append_event(
                self._event(
                    "ATTEMPT_STARTED",
                    task,
                    run_id=attempt.run_id,
                    attempt_id=attempt.attempt_id,
                    payload={"state": task.state.value},
                )
            )
            return task

        return self.event_log.transact(mutation)

    def finalize_run(self, task_id: str) -> Run:
        def mutation(unit: TaskUnitOfWork) -> Run:
            task = unit.require_task(task_id)
            if task.state not in {TaskState.SUCCEEDED, TaskState.FAILED, TaskState.CANCELLED, TaskState.PARTIAL}:
                raise ValueError("Task must be terminal before Run finalization")
            run = unit.require_run(task.active_run_id)
            if any(item.state not in ATTEMPT_TERMINAL_STATES for item in unit.attempts_for_run(run.run_id)):
                raise ValueError("active Attempt prevents Run finalization")
            expected = run.state_version
            run.state = transition_run(
                run.state, "TASK_TERMINAL_NO_ACTIVE_ATTEMPT", no_active_attempt=True
            )
            unit.save_run(run, expected)
            unit.append_event(
                self._event("RUN_TERMINAL", task, run_id=run.run_id, payload={"state": run.state.value})
            )
            return run

        return self.event_log.transact(mutation)

    def transition_task(self, task_id: str, event: str, context: TaskTransitionContext) -> Task:
        def mutation(unit: TaskUnitOfWork) -> Task:
            task = unit.require_task(task_id)
            expected = task.state_version
            task.state = transition_task(task.state, event, context)
            unit.save_task(task, expected)
            unit.append_event(
                self._event(
                    "TASK_TERMINAL" if task.state in {TaskState.SUCCEEDED, TaskState.FAILED, TaskState.CANCELLED, TaskState.PARTIAL} else "TASK_STATE_CHANGED",
                    task,
                    run_id=task.active_run_id,
                    payload={"state": task.state.value},
                )
            )
            return task

        return self.event_log.transact(mutation)

    def derive_batch_terminal(self, task_id: str) -> Task:
        def mutation(unit: TaskUnitOfWork) -> Task:
            task = unit.require_task(task_id)
            if not task.is_batch or not task.child_task_ids:
                raise ValueError("batch parent with children required")
            children = tuple(unit.require_task(child_id) for child_id in task.child_task_ids)
            terminal = {TaskState.SUCCEEDED, TaskState.FAILED, TaskState.CANCELLED, TaskState.PARTIAL}
            if any(child.state not in terminal for child in children):
                raise ValueError("batch parent is derived only after all children are terminal")
            if all(child.state is TaskState.SUCCEEDED for child in children):
                event = "CHILDREN_ALL_SUCCEEDED"
                context = TaskTransitionContext(is_batch=True)
            elif any(child.state is TaskState.SUCCEEDED for child in children):
                event = "CHILDREN_TERMINAL_MIXED"
                context = TaskTransitionContext(is_batch=True)
            else:
                event = "ATTEMPT_FAILED_NO_RETRY"
                context = TaskTransitionContext(is_batch=True, error_persisted=True)
            expected = task.state_version
            task.state = transition_task(task.state, event, context)
            unit.save_task(task, expected)
            unit.append_event(
                self._event(
                    "TASK_TERMINAL",
                    task,
                    run_id=task.active_run_id,
                    payload={"state": task.state.value, "derived_from_children": True},
                )
            )
            return task

        return self.event_log.transact(mutation)

    def retry_failed_batch_children(
        self,
        parent_task_id: str,
        proposed_identities: dict[str, RunIdentity],
        category: ErrorCategory,
    ) -> tuple[TaskAttempt, ...]:
        created: list[TaskAttempt] = []
        persistence = self.event_log.persistence
        parent = persistence.read_task(parent_task_id)
        if not parent.is_batch or parent.state is not TaskState.PARTIAL:
            raise RetryRejected("failed-child retry requires a PARTIAL batch parent")
        for child_id in parent.child_task_ids:
            child = persistence.read_task(child_id)
            if child.state is not TaskState.FAILED:
                continue
            failed = persistence.latest_attempt(child_id)
            created.append(self.retry(child_id, failed.attempt_id, proposed_identities[child_id], category))
        if created:
            self.transition_task(
                parent_task_id,
                "RETRY_SCHEDULED",
                TaskTransitionContext(retry_epoch=True, is_batch=True),
            )
        return tuple(created)
