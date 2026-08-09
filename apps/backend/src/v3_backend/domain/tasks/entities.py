from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from v3_backend.contracts.common.ids import validate_v3_id


class TaskState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PAUSE_REQUESTED = "PAUSE_REQUESTED"
    PAUSED = "PAUSED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PARTIAL = "PARTIAL"


class RunState(StrEnum):
    SEALED = "SEALED"
    ACTIVE = "ACTIVE"
    TERMINAL = "TERMINAL"


class AttemptState(StrEnum):
    QUEUED = "QUEUED"
    LEASED = "LEASED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    CHECKPOINTING = "CHECKPOINTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    LOST = "LOST"


TASK_TERMINAL_STATES = frozenset(
    {TaskState.SUCCEEDED, TaskState.FAILED, TaskState.CANCELLED, TaskState.PARTIAL}
)
ATTEMPT_TERMINAL_STATES = frozenset(
    {AttemptState.SUCCEEDED, AttemptState.FAILED, AttemptState.CANCELLED, AttemptState.LOST}
)


@dataclass(frozen=True)
class RunIdentity:
    project_context_revision_id: str
    normalized_input_hash: str
    code_version: str
    environment_profile: str
    service_contract_version: str

    def __post_init__(self) -> None:
        validate_v3_id(self.project_context_revision_id, "ProjectContextRevision")
        if len(self.normalized_input_hash) != 64 or any(
            ch not in "0123456789abcdef" for ch in self.normalized_input_hash
        ):
            raise ValueError("normalized_input_hash must be lowercase SHA-256")
        for name in ("code_version", "environment_profile", "service_contract_version"):
            if not getattr(self, name):
                raise ValueError(f"{name} must not be empty")


@dataclass
class Task:
    task_id: str
    project_id: str
    operation_id: str
    active_run_id: str
    state: TaskState = TaskState.QUEUED
    state_version: int = 0
    execution_epoch: int = 0
    is_batch: bool = False
    child_task_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_v3_id(self.task_id, "Task")
        validate_v3_id(self.project_id, "Project")
        validate_v3_id(self.active_run_id, "Run")
        if not self.operation_id:
            raise ValueError("operation_id must not be empty")
        if self.child_task_ids and not self.is_batch:
            raise ValueError("only batch tasks may own child tasks")
        for child_id in self.child_task_ids:
            validate_v3_id(child_id, "Task")


@dataclass
class Run:
    run_id: str
    task_id: str
    identity: RunIdentity
    state: RunState = RunState.SEALED
    state_version: int = 0

    def __post_init__(self) -> None:
        validate_v3_id(self.run_id, "Run")
        validate_v3_id(self.task_id, "Task")


@dataclass
class TaskAttempt:
    attempt_id: str
    task_id: str
    run_id: str
    ordinal: int
    state: AttemptState = AttemptState.QUEUED
    state_version: int = 0
    lease_id: str | None = None
    resume_checkpoint_artifact_id: str | None = None
    terminal_error_category: str | None = None

    def __post_init__(self) -> None:
        validate_v3_id(self.attempt_id, "TaskAttempt")
        validate_v3_id(self.task_id, "Task")
        validate_v3_id(self.run_id, "Run")
        if self.ordinal < 1:
            raise ValueError("attempt ordinal starts at one")
        if self.lease_id is not None:
            validate_v3_id(self.lease_id, "WorkerLease")
        if self.resume_checkpoint_artifact_id is not None:
            validate_v3_id(self.resume_checkpoint_artifact_id, "Artifact")


@dataclass(frozen=True)
class CheckpointMetadata:
    artifact_id: str
    run_id: str
    input_hash: str
    code_version: str
    environment_profile: str
    compatibility_hash: str
    created_by_attempt_id: str
    bounded_metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_v3_id(self.artifact_id, "Artifact")
        validate_v3_id(self.run_id, "Run")
        validate_v3_id(self.created_by_attempt_id, "TaskAttempt")
        for value in (self.input_hash, self.compatibility_hash):
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise ValueError("checkpoint hashes must be lowercase SHA-256")
        if len(self.bounded_metadata) > 32:
            raise ValueError("checkpoint metadata is not bounded")
