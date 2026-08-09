from __future__ import annotations

from typing import Protocol

from v3_backend.domain.tasks.entities import CheckpointMetadata, Run


class CheckpointIncompatible(ValueError):
    pass


class CheckpointPort(Protocol):
    def save(self, checkpoint: CheckpointMetadata) -> None: ...
    def require(self, artifact_id: str) -> CheckpointMetadata: ...


class InMemoryCheckpointPort:
    def __init__(self) -> None:
        self.items: dict[str, CheckpointMetadata] = {}

    def save(self, checkpoint: CheckpointMetadata) -> None:
        if checkpoint.artifact_id in self.items and self.items[checkpoint.artifact_id] != checkpoint:
            raise ValueError("checkpoint artifact metadata is immutable")
        self.items[checkpoint.artifact_id] = checkpoint

    def require(self, artifact_id: str) -> CheckpointMetadata:
        try:
            return self.items[artifact_id]
        except KeyError as exc:
            raise KeyError(f"checkpoint not found: {artifact_id}") from exc


class CheckpointManager:
    def __init__(self, port: CheckpointPort) -> None:
        self.port = port

    def publish(self, checkpoint: CheckpointMetadata) -> None:
        self.port.save(checkpoint)

    def validate_resume(
        self, artifact_id: str, run: Run, compatibility_hash: str
    ) -> CheckpointMetadata:
        checkpoint = self.port.require(artifact_id)
        expected = (
            checkpoint.run_id == run.run_id,
            checkpoint.input_hash == run.identity.normalized_input_hash,
            checkpoint.code_version == run.identity.code_version,
            checkpoint.environment_profile == run.identity.environment_profile,
            checkpoint.compatibility_hash == compatibility_hash,
        )
        if not all(expected):
            raise CheckpointIncompatible("CHECKPOINT_INCOMPATIBLE")
        return checkpoint
