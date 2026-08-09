from __future__ import annotations

from dataclasses import dataclass

from .entities import (
    ATTEMPT_TERMINAL_STATES,
    TASK_TERMINAL_STATES,
    AttemptState,
    RunState,
    TaskState,
)


class ImpossibleTransition(ValueError):
    pass


@dataclass(frozen=True)
class TaskTransitionContext:
    supports_checkpoint: bool = False
    active_lease_persisted: bool = False
    successful_attempt: bool = False
    publication_committed: bool = False
    error_persisted: bool = False
    cleanup_complete: bool = False
    is_batch: bool = False
    retry_epoch: bool = False


TASK_TRANSITIONS: dict[tuple[TaskState, str], TaskState] = {
    (TaskState.QUEUED, "ATTEMPT_STARTED"): TaskState.RUNNING,
    (TaskState.QUEUED, "PAUSE_REQUESTED"): TaskState.PAUSE_REQUESTED,
    (TaskState.RUNNING, "PAUSE_REQUESTED"): TaskState.PAUSE_REQUESTED,
    (TaskState.PAUSE_REQUESTED, "CHECKPOINT_PUBLISHED"): TaskState.PAUSED,
    (TaskState.QUEUED, "CANCEL_REQUESTED"): TaskState.CANCEL_REQUESTED,
    (TaskState.RUNNING, "CANCEL_REQUESTED"): TaskState.CANCEL_REQUESTED,
    (TaskState.PAUSE_REQUESTED, "CANCEL_REQUESTED"): TaskState.CANCEL_REQUESTED,
    (TaskState.PAUSED, "CANCEL_REQUESTED"): TaskState.CANCEL_REQUESTED,
    (TaskState.RUNNING, "ALL_REQUIRED_ARTIFACTS_PUBLISHED"): TaskState.SUCCEEDED,
    (TaskState.RUNNING, "ATTEMPT_FAILED_NO_RETRY"): TaskState.FAILED,
    (TaskState.CANCEL_REQUESTED, "WORKER_CANCELLED_OR_TERMINATED"): TaskState.CANCELLED,
    (TaskState.RUNNING, "CHILDREN_TERMINAL_MIXED"): TaskState.PARTIAL,
    (TaskState.RUNNING, "CHILDREN_ALL_SUCCEEDED"): TaskState.SUCCEEDED,
    (TaskState.FAILED, "RETRY_SCHEDULED"): TaskState.QUEUED,
    (TaskState.PARTIAL, "RETRY_SCHEDULED"): TaskState.QUEUED,
    (TaskState.PAUSED, "RESUME_SCHEDULED"): TaskState.QUEUED,
}


def transition_task(
    state: TaskState, event: str, context: TaskTransitionContext
) -> TaskState:
    try:
        target = TASK_TRANSITIONS[(state, event)]
    except KeyError as exc:
        raise ImpossibleTransition(f"Task {state} cannot handle {event}") from exc

    if event == "ATTEMPT_STARTED" and not context.active_lease_persisted:
        raise ImpossibleTransition("ATTEMPT_STARTED requires a persisted active lease")
    if event == "PAUSE_REQUESTED" and not context.supports_checkpoint:
        raise ImpossibleTransition("operation does not support checkpoint/pause")
    if event == "ALL_REQUIRED_ARTIFACTS_PUBLISHED" and not (
        context.successful_attempt and context.publication_committed
    ):
        raise ImpossibleTransition("success requires successful Attempt and committed publication")
    if event == "ATTEMPT_FAILED_NO_RETRY" and not context.error_persisted:
        raise ImpossibleTransition("failure requires a persisted error")
    if event == "WORKER_CANCELLED_OR_TERMINATED" and not context.cleanup_complete:
        raise ImpossibleTransition("cancellation requires completed cleanup")
    if event.startswith("CHILDREN_") and not context.is_batch:
        raise ImpossibleTransition("child aggregation is batch-only")
    if event in {"RETRY_SCHEDULED", "RESUME_SCHEDULED"} and not context.retry_epoch:
        raise ImpossibleTransition("terminal/restart transitions require a new execution epoch")
    return target


ATTEMPT_TRANSITIONS: dict[tuple[AttemptState, str], AttemptState] = {
    (AttemptState.QUEUED, "LEASE_GRANTED"): AttemptState.LEASED,
    (AttemptState.LEASED, "WORKER_DISPATCHED"): AttemptState.STARTING,
    (AttemptState.STARTING, "WORKER_ACKNOWLEDGED"): AttemptState.RUNNING,
    (AttemptState.RUNNING, "CHECKPOINT_REQUESTED"): AttemptState.CHECKPOINTING,
    (AttemptState.CHECKPOINTING, "CHECKPOINT_PUBLISHED"): AttemptState.RUNNING,
}
for _source in (
    AttemptState.QUEUED,
    AttemptState.LEASED,
    AttemptState.STARTING,
    AttemptState.RUNNING,
    AttemptState.CHECKPOINTING,
):
    ATTEMPT_TRANSITIONS[(_source, "ATTEMPT_FAILED")] = AttemptState.FAILED
    ATTEMPT_TRANSITIONS[(_source, "ATTEMPT_CANCELLED")] = AttemptState.CANCELLED
    ATTEMPT_TRANSITIONS[(_source, "WORKER_LOST")] = AttemptState.LOST
ATTEMPT_TRANSITIONS[(AttemptState.RUNNING, "ATTEMPT_SUCCEEDED")] = AttemptState.SUCCEEDED


def transition_attempt(state: AttemptState, event: str) -> AttemptState:
    if state in ATTEMPT_TERMINAL_STATES:
        raise ImpossibleTransition(f"terminal Attempt {state} cannot transition")
    try:
        return ATTEMPT_TRANSITIONS[(state, event)]
    except KeyError as exc:
        raise ImpossibleTransition(f"Attempt {state} cannot handle {event}") from exc


RUN_TRANSITIONS = {
    (RunState.SEALED, "ATTEMPT_ACTIVATED"): RunState.ACTIVE,
    (RunState.ACTIVE, "TASK_TERMINAL_NO_ACTIVE_ATTEMPT"): RunState.TERMINAL,
}


def transition_run(state: RunState, event: str, *, no_active_attempt: bool = False) -> RunState:
    try:
        target = RUN_TRANSITIONS[(state, event)]
    except KeyError as exc:
        raise ImpossibleTransition(f"Run {state} cannot handle {event}") from exc
    if target is RunState.TERMINAL and not no_active_attempt:
        raise ImpossibleTransition("Run terminal requires no active Attempt")
    return target


def task_is_terminal(state: TaskState) -> bool:
    return state in TASK_TERMINAL_STATES
