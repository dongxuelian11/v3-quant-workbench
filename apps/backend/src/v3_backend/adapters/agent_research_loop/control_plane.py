from __future__ import annotations

from v3_backend.control_plane.persistence import TaskPersistencePort
from v3_backend.domain.agent_research_loop.model import (
    PersistedExecutionObservation,
    ResearchActionDraft,
    ResearchLoopContractError,
)
from v3_backend.domain.tasks.entities import AttemptState, RunState, TaskState


class ResearchExecutionEvidenceResolver:
    """Re-reads Control Plane persistence; never trusts caller-owned entities."""

    def __init__(self, persistence: TaskPersistencePort) -> None:
        self._persistence = persistence

    def resolve_execution(
        self,
        *,
        action: ResearchActionDraft,
        task_id: str,
        run_id: str,
        attempt_id: str,
    ) -> PersistedExecutionObservation:
        try:
            with self._persistence.begin() as unit:
                try:
                    task = unit.require_task(task_id)
                except KeyError as error:
                    raise ResearchLoopContractError(
                        "CONTROL_PLANE_PERSISTENCE_TASK_NOT_FOUND", task_id
                    ) from error
                try:
                    run = unit.require_run(run_id)
                except KeyError as error:
                    raise ResearchLoopContractError(
                        "CONTROL_PLANE_PERSISTENCE_RUN_NOT_FOUND", run_id
                    ) from error
                try:
                    attempt = unit.require_attempt(attempt_id)
                except KeyError as error:
                    raise ResearchLoopContractError(
                        "CONTROL_PLANE_PERSISTENCE_ATTEMPT_NOT_FOUND", attempt_id
                    ) from error
        except ResearchLoopContractError:
            raise
        except Exception as error:
            raise ResearchLoopContractError(
                "CONTROL_PLANE_PERSISTENCE_READ_FAILED", type(error).__name__
            ) from error

        if task.task_id != task_id or run.run_id != run_id or attempt.attempt_id != attempt_id:
            raise ResearchLoopContractError(
                "CONTROL_PLANE_PERSISTENCE_IDENTITY_MISMATCH", action.action_draft_id
            )
        if task.active_run_id != run.run_id or run.task_id != task.task_id:
            raise ResearchLoopContractError(
                "OWNER_EXECUTION_BINDING_MISMATCH", action.action_draft_id
            )
        if attempt.task_id != task.task_id or attempt.run_id != run.run_id:
            raise ResearchLoopContractError(
                "OWNER_EXECUTION_BINDING_MISMATCH", action.action_draft_id
            )
        if task.state is not TaskState.SUCCEEDED:
            raise ResearchLoopContractError("OWNER_TASK_NOT_SUCCEEDED", task.task_id)
        if run.state is not RunState.TERMINAL:
            raise ResearchLoopContractError("OWNER_RUN_NOT_TERMINAL", run.run_id)
        if attempt.state is not AttemptState.SUCCEEDED:
            raise ResearchLoopContractError("OWNER_ATTEMPT_NOT_SUCCEEDED", attempt.attempt_id)
        if task.operation_id != action.requested_capability:
            raise ResearchLoopContractError(
                "RESEARCH_ACTION_CAPABILITY_MISMATCH", action.action_draft_id
            )

        # operation_id equality and a persisted input hash are necessary observations,
        # but the current owner contract does not bind either value to action_draft_id.
        return PersistedExecutionObservation._from_persistence_read(
            action=action,
            task_id=task.task_id,
            run_id=run.run_id,
            attempt_id=attempt.attempt_id,
            operation_id=task.operation_id,
            normalized_input_hash=run.identity.normalized_input_hash,
        )
