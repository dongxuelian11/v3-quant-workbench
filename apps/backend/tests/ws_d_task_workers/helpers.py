from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "apps" / "backend" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from v3_backend.control_plane.checkpoint_manager import CheckpointManager, InMemoryCheckpointPort
from v3_backend.control_plane.event_log import CollectingPublisher, DurableEventLog
from v3_backend.control_plane.persistence import InMemoryTaskPersistence
from v3_backend.control_plane.task_supervisor import TaskSupervisor
from v3_backend.domain.tasks.entities import RunIdentity


PREFIXES = {
    "Task": "tsk_",
    "Run": "run_",
    "TaskAttempt": "att_",
    "TaskEvent": "tev_",
    "WorkerLease": "lea_",
}


class DeterministicIdentities:
    def __init__(self) -> None:
        self.value = 0

    def new(self, object_type: str) -> str:
        self.value += 1
        return PREFIXES[object_type] + str(self.value).zfill(26)


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 9, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


def run_identity(input_hash: str = "a" * 64) -> RunIdentity:
    return RunIdentity(
        project_context_revision_id="pcr_" + "0" * 26,
        normalized_input_hash=input_hash,
        code_version="git:seed",
        environment_profile="cpu-formal-v1",
        service_contract_version="1.0.0",
    )


def make_supervisor(clock: MutableClock | None = None):
    persistence = InMemoryTaskPersistence(clock)
    publisher = CollectingPublisher()
    identities = DeterministicIdentities()
    checkpoints = CheckpointManager(InMemoryCheckpointPort())
    supervisor = TaskSupervisor(
        DurableEventLog(persistence, publisher),
        identities,
        checkpoints,
        clock=clock,
    )
    return supervisor, persistence, publisher, identities, checkpoints


PROJECT_ID = "prj_" + "0" * 26
