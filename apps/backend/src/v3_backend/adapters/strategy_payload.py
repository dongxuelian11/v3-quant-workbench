"""Resolve Strategy score bindings from canonical Catalog publications."""

from __future__ import annotations

from v3_backend.adapters.sqlite.repositories import SQLiteRepositoryRegistry
from v3_backend.domain.payload_authority import (
    CanonicalPayloadBinding,
    PayloadResolutionRequest,
)
from v3_backend.domain.strategies.binding import StrategyEvaluationBindingVersion
from v3_backend.repositories.unit_of_work import TransactionMode


STRATEGY_OWNER_BINDING_VERSION = "v3.strategy-catalog-owner-binding/1.0.0"


class StrategyPayloadBindingError(ValueError):
    """The Strategy owner cannot establish the requested canonical binding."""


class StrategyPayloadBindingResolver:
    """Resolve immutable owner/Artifact publication state from the shared Catalog."""

    def __init__(
        self,
        *,
        binding: StrategyEvaluationBindingVersion,
        repositories: SQLiteRepositoryRegistry,
    ) -> None:
        if not isinstance(binding, StrategyEvaluationBindingVersion):
            raise TypeError("binding must be StrategyEvaluationBindingVersion")
        if not isinstance(repositories, SQLiteRepositoryRegistry):
            raise TypeError("repositories must be SQLiteRepositoryRegistry")
        unit = repositories.artifact.uow
        if not unit.active or unit.mode is not TransactionMode.READ_ONLY:
            raise StrategyPayloadBindingError(
                "Strategy owner resolution requires an active READ_ONLY canonical Catalog"
            )
        self._binding = binding
        self._repositories = repositories

    def resolve(
        self, request: PayloadResolutionRequest
    ) -> CanonicalPayloadBinding | None:
        if not isinstance(request, PayloadResolutionRequest):
            raise TypeError("Strategy payload resolution requires PayloadResolutionRequest")
        owner_matches = tuple(
            value
            for value in self._binding.canonical_owner_references
            if (
                value.owner_namespace,
                value.owner_id,
                value.owner_version,
                value.payload_role,
            )
            == (
                request.owner_namespace,
                request.owner_id,
                request.owner_version,
                request.payload_role,
            )
        )
        if len(owner_matches) != 1:
            return None
        intent = owner_matches[0]
        bound_matches = tuple(
            value for value in self._binding.input_references
            if value.source_id == intent.owner_id
        )
        if len(bound_matches) != 1:
            raise StrategyPayloadBindingError(
                "canonical owner must back exactly one Strategy input reference"
            )
        bound = bound_matches[0]
        if (
            bound.artifact_kind != intent.artifact_type
            or bound.artifact_id != intent.artifact_id
            or bound.content_sha256 != intent.content_sha256
        ):
            raise StrategyPayloadBindingError(
                "canonical owner intent does not match the exact Strategy input reference"
            )
        if intent.owner_namespace != "PREDICTION_SIGNAL_VERSION":
            return None
        publication = self._repositories.model.table("prediction_signal_version").get(
            intent.owner_id
        )
        if publication is None or publication["state"] != "PUBLISHED":
            return None
        model = self._repositories.model.table("model_version").get(
            publication["model_version_id"]
        )
        if model is None or model["state"] != "PUBLISHED":
            return None
        dataset = self._repositories.dataset.table("dataset_version").get(
            publication["dataset_version_id"]
        )
        if dataset is None or dataset["state"] != "PUBLISHED":
            return None
        snapshot = self._repositories.snapshot.table("data_snapshot").get(
            dataset["snapshot_id"]
        )
        if snapshot is None or snapshot["state"] != "PUBLISHED":
            return None
        universe = self._repositories.universe.table("universe_version").get(
            dataset["universe_version_id"]
        )
        if universe is None or universe["state"] != "PUBLISHED":
            return None
        membership_artifact = self._repositories.artifact.table("artifact").get(
            universe["membership_artifact_id"]
        )
        if membership_artifact is None or membership_artifact["state"] != "PUBLISHED":
            return None
        if (
            publication["prediction_signal_version_id"] != intent.owner_id
            or publication["content_hash"] != intent.owner_version
            or publication["dataset_version_id"] != self._binding.dataset_version_id
            or model["model_version_id"] != publication["model_version_id"]
            or model["dataset_version_id"] != self._binding.dataset_version_id
            or dataset["dataset_version_id"] != self._binding.dataset_version_id
            or dataset["snapshot_id"] != self._binding.snapshot.snapshot_id
            or dataset["universe_version_id"]
            != self._binding.universe.universe_version_id
            or snapshot["snapshot_id"] != self._binding.snapshot.snapshot_id
            or snapshot["content_hash"] != self._binding.snapshot.content_sha256
            or universe["universe_version_id"]
            != self._binding.universe.universe_version_id
            or universe["snapshot_id"] != self._binding.snapshot.snapshot_id
            or universe["membership_artifact_id"]
            != self._binding.universe.membership_artifact_id
            or membership_artifact["artifact_id"]
            != self._binding.universe.membership_artifact_id
            or membership_artifact["sha256"]
            != self._binding.universe.membership_sha256
            or publication["signal_artifact_id"] != intent.artifact_id
            or publication["content_hash"] != intent.content_sha256
        ):
            raise StrategyPayloadBindingError(
                "canonical PredictionSignalVersion publication does not match requested owner/version/context/artifact"
            )
        artifact = self._repositories.artifact.table("artifact").get(
            publication["signal_artifact_id"]
        )
        if artifact is None or artifact["state"] != "PUBLISHED":
            return None
        if (
            artifact["artifact_id"] != bound.artifact_id
            or artifact["sha256"] != bound.content_sha256
            or artifact["semantic_role"] != intent.payload_role
        ):
            raise StrategyPayloadBindingError(
                "canonical owner publication Artifact metadata does not match Strategy binding"
            )
        return CanonicalPayloadBinding(
            owner_namespace=intent.owner_namespace,
            owner_id=str(publication["prediction_signal_version_id"]),
            owner_version=str(publication["content_hash"]),
            payload_role=intent.payload_role,
            artifact_id=str(artifact["artifact_id"]),
            expected_sha256=str(artifact["sha256"]),
            expected_byte_size=int(artifact["byte_size"]),
            context_identity=request.context_identity,
            binding_version=STRATEGY_OWNER_BINDING_VERSION,
            schema_fingerprint=(None if artifact["schema_fingerprint"] is None else str(artifact["schema_fingerprint"])),
            provenance_reference_id=str(publication["prediction_signal_version_id"]),
        )


__all__ = (
    "STRATEGY_OWNER_BINDING_VERSION",
    "StrategyPayloadBindingError",
    "StrategyPayloadBindingResolver",
)
