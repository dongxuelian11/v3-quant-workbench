"""Canonical Dataset-to-Model research pipeline over A1/P1 actual bytes."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Mapping, Protocol

from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING, TruthAdmissionState
from v3_backend.domain.artifacts.model import ArtifactDescriptor
from v3_backend.domain.datasets import (
    DATASET_ARTIFACT_ROLE,
    DATASET_SCHEMA_FINGERPRINT,
    DATASET_SCHEMA_VERSION,
    FormalDatasetRepository,
    FormalDatasetVersion,
    SplitSpec,
    SplitSpecRepository,
)
from v3_backend.domain.payload_authority import (
    CanonicalPayloadResolver,
    PayloadResolutionReceipt,
    PayloadResolutionRequest,
)
from v3_backend.provenance.canonical_hash import canonical_artifact_id, canonical_sha256

from .model import DatasetSplitRole, FeatureColumn, ModelSample, SafeLinearModelArtifact, TrainingSpecVersion
from .runtime import IsolatedModelWorker, PredictionBundle, TrainedModelBundle, predict_model, train_model


MODEL_PIPELINE_SCHEMA_VERSION = "v3.model-research-pipeline/1.0.0"
MODEL_PIPELINE_SCHEMA_FINGERPRINT = "sch_sha256_" + canonical_sha256(
    {
        "schema_version": MODEL_PIPELINE_SCHEMA_VERSION,
        "source": "A1 FormalDatasetVersion plus P1 DATASET_SAMPLES bytes",
        "engine": "Track E deterministic model runtime",
        "artifacts": ["training", "safe_model", "model_version", "prediction"],
    }
)


class ModelPipelineStatus(StrEnum):
    DATASET_RESOLUTION_FAILED = "DATASET_RESOLUTION_FAILED"
    SAMPLE_MATERIALIZATION_FAILED = "SAMPLE_MATERIALIZATION_FAILED"
    TRAIN_FAILED = "TRAIN_FAILED"
    MODEL_PUBLICATION_FAILED = "MODEL_PUBLICATION_FAILED"
    PREDICT_FAILED = "PREDICT_FAILED"
    PREDICTION_PUBLICATION_FAILED = "PREDICTION_PUBLICATION_FAILED"
    SUCCESS = "SUCCESS"


class ModelPipelineArtifactPublisher(Protocol):
    def publish_record(
        self,
        payload: Mapping[str, object],
        *,
        provenance_entity_id: str,
        schema_fingerprint: str,
        semantic_fingerprint: str,
    ) -> ArtifactDescriptor: ...

    def publish_safe_model(
        self,
        artifact: SafeLinearModelArtifact,
        *,
        provenance_entity_id: str,
        schema_fingerprint: str,
        semantic_fingerprint: str,
    ) -> ArtifactDescriptor: ...


@dataclass(frozen=True, slots=True)
class ModelPipelineRequest:
    dataset_id: str
    target_semantics: str
    code_version: str
    environment_profile_id: str
    seed: int = 7
    alpha: float = 1.0
    fit_intercept: bool = True
    training_split: DatasetSplitRole = DatasetSplitRole.TRAIN
    prediction_split: DatasetSplitRole = DatasetSplitRole.TEST
    max_payload_bytes: int = 16 * 1024 * 1024
    proposed_state: TruthAdmissionState = PRE_ALPHA_CEILING

    def __post_init__(self) -> None:
        for value, label in (
            (self.dataset_id, "dataset_id"),
            (self.target_semantics, "target_semantics"),
            (self.code_version, "code_version"),
            (self.environment_profile_id, "environment_profile_id"),
        ):
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{label} must be non-empty without edge whitespace")
        if not self.dataset_id.startswith("fdsv_sha256_"):
            raise ValueError("runnable Model pipeline requires an A1 FormalDatasetVersion ID")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool) or self.seed < 0:
            raise ValueError("seed must be a non-negative integer")
        if isinstance(self.alpha, bool) or not isinstance(self.alpha, (int, float)) or not math.isfinite(self.alpha) or self.alpha < 0:
            raise ValueError("alpha must be a finite non-negative number")
        if not isinstance(self.fit_intercept, bool):
            raise TypeError("fit_intercept must be bool")
        if self.training_split is not DatasetSplitRole.TRAIN:
            raise ValueError("Model pipeline training_split is fixed to TRAIN")
        if self.prediction_split is not DatasetSplitRole.TEST:
            raise ValueError("Model pipeline prediction_split is fixed to TEST")
        if not isinstance(self.max_payload_bytes, int) or isinstance(self.max_payload_bytes, bool) or self.max_payload_bytes <= 0:
            raise ValueError("max_payload_bytes must be a positive integer")
        if not isinstance(self.proposed_state, TruthAdmissionState):
            raise TypeError("proposed_state must be typed")


@dataclass(frozen=True, slots=True)
class ResolvedModelDatasetVersion:
    """Track E compatibility projection derived only from one verified Formal Dataset."""

    dataset_version_id: str
    feature_set_version_id: str
    factor_evaluation_ids: tuple[str, ...]
    label_spec_id: str
    split_spec_id: str
    dataset_artifact_id: str
    truth_admission: TruthAdmissionState


@dataclass(frozen=True, slots=True)
class MaterializedModelDataset:
    owner: FormalDatasetVersion
    resolution_receipt: PayloadResolutionReceipt
    runtime_dataset: ResolvedModelDatasetVersion
    samples: tuple[ModelSample, ...]
    knowledge_cutoff: datetime
    ordinal_semantics: str = "STABLE_SPLIT_LOCAL_PROJECTION_RESEARCH_ONLY"
    timestamp_semantics: str = "DATASET_KNOWLEDGE_CUTOFF_PROXY_RESEARCH_ONLY"


@dataclass(frozen=True, slots=True)
class ModelPipelineResult:
    status: ModelPipelineStatus
    dataset_id: str
    dataset_artifact_id: str | None = None
    dataset_resolution_receipt_id: str | None = None
    sample_count: int = 0
    train_sample_count: int = 0
    validation_sample_count: int = 0
    prediction_sample_count: int = 0
    model_version_id: str | None = None
    model_artifact_id: str | None = None
    training_artifact_id: str | None = None
    model_version_artifact_id: str | None = None
    prediction_id: str | None = None
    prediction_artifact_id: str | None = None
    truth: str = "PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE"
    ordinal_semantics: str | None = None
    timestamp_semantics: str | None = None
    error: str | None = None

    def to_wire(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "dataset_id": self.dataset_id,
            "dataset_artifact_id": self.dataset_artifact_id,
            "dataset_resolution_receipt_id": self.dataset_resolution_receipt_id,
            "sample_count": self.sample_count,
            "train_sample_count": self.train_sample_count,
            "validation_sample_count": self.validation_sample_count,
            "prediction_sample_count": self.prediction_sample_count,
            "model_version_id": self.model_version_id,
            "model_artifact_id": self.model_artifact_id,
            "training_artifact_id": self.training_artifact_id,
            "model_version_artifact_id": self.model_version_artifact_id,
            "prediction_id": self.prediction_id,
            "prediction_artifact_id": self.prediction_artifact_id,
            "truth": self.truth,
            "ordinal_semantics": self.ordinal_semantics,
            "timestamp_semantics": self.timestamp_semantics,
            "error": self.error,
        }


def _strict_decimal(value: object, label: str) -> float:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a canonical decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{label} is not a decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{label} must be finite")
    if parsed == 0:
        canonical = "0"
    else:
        canonical = format(parsed.normalize(), "f")
        if "." in canonical:
            canonical = canonical.rstrip("0").rstrip(".")
    if canonical != value:
        raise ValueError(f"{label} must use canonical decimal encoding")
    return float(parsed)


def _parse_utc(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return parsed


def materialize_model_samples(
    *,
    owner: FormalDatasetVersion,
    payload: bytes,
    receipt: PayloadResolutionReceipt,
    split_spec: SplitSpec,
) -> MaterializedModelDataset:
    """Strictly decode P1-verified A1 Dataset bytes into deterministic ModelSample values."""

    if not isinstance(owner, FormalDatasetVersion):
        raise TypeError("materialization requires a persisted FormalDatasetVersion owner")
    if not isinstance(receipt, PayloadResolutionReceipt):
        raise TypeError("materialization requires a typed P1 Dataset receipt")
    if (
        receipt.context_identity != owner.dataset_version_id
        or receipt.artifact_id != owner.dataset_descriptor.artifact_id
    ):
        raise ValueError("P1 Dataset receipt does not bind the canonical Dataset owner/artifact")
    if split_spec.split_spec_id != owner.split_spec_id:
        raise ValueError("SplitSpec does not bind the canonical Dataset owner")
    try:
        root = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Dataset actual bytes must be UTF-8 JSON") from exc
    expected_root = {
        "schema_version", "schema_fingerprint", "snapshot_id", "universe_version_id",
        "universe_membership_identity", "knowledge_cutoff", "feature_materialization_ids",
        "feature_receipt_ids", "label_spec_id", "label_payload_id", "label_receipt_id",
        "split_spec_id", "feature_order", "samples",
    }
    if not isinstance(root, dict) or set(root) != expected_root:
        raise ValueError("Dataset actual bytes have an unrecognized root schema")
    exact = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "schema_fingerprint": DATASET_SCHEMA_FINGERPRINT,
        "snapshot_id": owner.snapshot_id,
        "universe_version_id": owner.universe_version_id,
        "universe_membership_identity": owner.universe_membership_identity,
        "feature_materialization_ids": list(owner.feature_materialization_ids),
        "feature_receipt_ids": [value.receipt_identity for value in owner.feature_receipts],
        "label_spec_id": owner.label_spec_id,
        "label_payload_id": owner.label_payload_id,
        "label_receipt_id": owner.label_receipt.receipt_identity,
        "split_spec_id": owner.split_spec_id,
        "feature_order": list(owner.feature_materialization_ids),
    }
    for key, value in exact.items():
        if root[key] != value:
            raise ValueError(f"Dataset actual bytes differ from canonical owner field {key}")
    raw_samples = root["samples"]
    if not isinstance(raw_samples, list) or len(raw_samples) != owner.sample_count:
        raise ValueError("Dataset sample count differs from canonical owner")
    knowledge_cutoff = _parse_utc(root["knowledge_cutoff"], "knowledge_cutoff")
    expected_row = {"sample_id", "instrument_id", "observation_id", "split", "features", "label"}
    rows: list[dict[str, object]] = []
    observed_ids: set[str] = set()
    observations_by_role: dict[str, set[str]] = {role.value: set() for role in DatasetSplitRole}
    for index, row in enumerate(raw_samples):
        if not isinstance(row, dict) or set(row) != expected_row:
            raise ValueError(f"Dataset sample[{index}] has an unrecognized schema")
        sample_id, instrument_id, observation_id, role = (
            row["sample_id"], row["instrument_id"], row["observation_id"], row["split"]
        )
        if not all(isinstance(value, str) and value for value in (sample_id, instrument_id, observation_id, role)):
            raise ValueError(f"Dataset sample[{index}] identities must be non-empty strings")
        expected_sample_id = "smp_sha256_" + canonical_sha256(
            {"instrument_id": instrument_id, "observation_id": observation_id, "label_spec_id": owner.label_spec_id}
        )
        if sample_id != expected_sample_id or sample_id in observed_ids:
            raise ValueError("Dataset sample identity is non-canonical or duplicated")
        if role not in observations_by_role:
            raise ValueError("Dataset sample split role is unsupported")
        features = row["features"]
        if not isinstance(features, list) or len(features) != len(owner.feature_materialization_ids):
            raise ValueError("Dataset sample feature count differs from canonical feature order")
        decoded_features = tuple(_strict_decimal(value, f"sample[{index}].feature") for value in features)
        decoded_label = _strict_decimal(row["label"], f"sample[{index}].label")
        rows.append({
            "sample_id": sample_id,
            "instrument_id": instrument_id,
            "observation_id": observation_id,
            "split": role,
            "features": decoded_features,
            "label": decoded_label,
        })
        observed_ids.add(sample_id)
        observations_by_role[role].add(observation_id)

    role_ranges = {
        DatasetSplitRole.TRAIN.value: (split_spec.train_start, split_spec.train_end),
        DatasetSplitRole.VALIDATION.value: (split_spec.validation_start, split_spec.validation_end),
        DatasetSplitRole.TEST.value: (split_spec.test_start, split_spec.test_end),
    }
    ordinal_by_role_observation: dict[tuple[str, str], int] = {}
    seen_observation_role: dict[str, str] = {}
    for role, observation_ids in observations_by_role.items():
        start, end = role_ranges[role]
        ordered = sorted(observation_ids)
        if len(ordered) > end - start + 1:
            raise ValueError("Dataset split contains more observation IDs than its SplitSpec range")
        for offset, observation_id in enumerate(ordered):
            other_role = seen_observation_role.setdefault(observation_id, role)
            if other_role != role:
                raise ValueError("one Dataset observation_id appears in multiple split roles")
            ordinal_by_role_observation[(role, observation_id)] = start + offset

    samples = tuple(
        ModelSample(
            sample_id=row["sample_id"],
            instrument_id=row["instrument_id"],
            observation_ordinal=ordinal_by_role_observation[(row["split"], row["observation_id"])],
            event_time=knowledge_cutoff,
            decision_time=knowledge_cutoff,
            features=row["features"],
            label=row["label"],
        )
        for row in rows
    )
    feature_projection_id = "mfs_sha256_" + canonical_sha256(
        {
            "formal_dataset_version_id": owner.dataset_version_id,
            "feature_materialization_ids": list(owner.feature_materialization_ids),
            "dataset_schema_fingerprint": owner.dataset_schema_fingerprint,
        }
    )
    runtime_dataset = ResolvedModelDatasetVersion(
        dataset_version_id=owner.dataset_version_id,
        feature_set_version_id=feature_projection_id,
        factor_evaluation_ids=owner.feature_materialization_ids,
        label_spec_id=owner.label_spec_id,
        split_spec_id=owner.split_spec_id,
        dataset_artifact_id=owner.dataset_descriptor.artifact_id,
        truth_admission=owner.truth_admission,
    )
    return MaterializedModelDataset(
        owner=owner,
        resolution_receipt=receipt,
        runtime_dataset=runtime_dataset,
        samples=samples,
        knowledge_cutoff=knowledge_cutoff,
    )


def _samples_for_split(
    materialized: MaterializedModelDataset,
    split_spec: SplitSpec,
    role: DatasetSplitRole,
) -> tuple[ModelSample, ...]:
    start, end = {
        DatasetSplitRole.TRAIN: (split_spec.train_start, split_spec.train_end),
        DatasetSplitRole.VALIDATION: (split_spec.validation_start, split_spec.validation_end),
        DatasetSplitRole.TEST: (split_spec.test_start, split_spec.test_end),
    }[role]
    return tuple(value for value in materialized.samples if start <= value.observation_ordinal <= end)


class CanonicalDatasetModelPipelineService:
    def __init__(
        self,
        *,
        datasets: FormalDatasetRepository,
        split_specs: SplitSpecRepository,
        payload_resolver: CanonicalPayloadResolver,
        worker: IsolatedModelWorker,
        artifact_publisher: ModelPipelineArtifactPublisher,
    ) -> None:
        self._datasets = datasets
        self._split_specs = split_specs
        self._resolver = payload_resolver
        self._worker = worker
        self._publisher = artifact_publisher

    def run(self, request: ModelPipelineRequest) -> ModelPipelineResult:
        try:
            owner = self._datasets.get_dataset(request.dataset_id)
            if owner is None:
                raise ValueError("canonical Dataset owner not found")
            resolution = self._resolver.resolve(
                PayloadResolutionRequest(
                    owner_namespace="v3.datasets",
                    owner_id=owner.dataset_version_id,
                    owner_version=owner.dataset_version_id,
                    payload_role=DATASET_ARTIFACT_ROLE,
                    context_identity=owner.dataset_version_id,
                    max_bytes=request.max_payload_bytes,
                )
            )
        except Exception as exc:
            return ModelPipelineResult(ModelPipelineStatus.DATASET_RESOLUTION_FAILED, request.dataset_id, error=str(exc))

        try:
            split_spec = self._split_specs.get_split_spec(owner.split_spec_id)
            if split_spec is None:
                raise ValueError("canonical Dataset SplitSpec owner not found")
            materialized = materialize_model_samples(
                owner=owner,
                payload=resolution.verified_payload.payload,
                receipt=resolution.receipt,
                split_spec=split_spec,
            )
            train_samples = _samples_for_split(materialized, split_spec, DatasetSplitRole.TRAIN)
            validation_samples = _samples_for_split(materialized, split_spec, DatasetSplitRole.VALIDATION)
            prediction_samples = _samples_for_split(materialized, split_spec, request.prediction_split)
            if not prediction_samples:
                raise ValueError("prediction split contains no materialized ModelSample rows")
        except Exception as exc:
            return ModelPipelineResult(
                ModelPipelineStatus.SAMPLE_MATERIALIZATION_FAILED,
                request.dataset_id,
                dataset_artifact_id=owner.dataset_descriptor.artifact_id,
                dataset_resolution_receipt_id=resolution.receipt.receipt_identity,
                error=str(exc),
            )

        try:
            runtime = self._worker.runtime
            training_spec = TrainingSpecVersion.create(
                dataset=materialized.runtime_dataset,
                feature_schema=tuple(FeatureColumn(value) for value in owner.feature_materialization_ids),
                seed=request.seed,
                environment_profile_id=request.environment_profile_id,
                dependency_runtime_fingerprint=runtime.fingerprint,
                alpha=request.alpha,
                fit_intercept=request.fit_intercept,
            )
            provenance_payload = {
                "schema_version": MODEL_PIPELINE_SCHEMA_VERSION,
                "kind": "MODEL_TRAINING_PROVENANCE",
                "dataset_version_id": owner.dataset_version_id,
                "dataset_artifact_id": owner.dataset_descriptor.artifact_id,
                "dataset_resolution_receipt_id": resolution.receipt.receipt_identity,
                "training_spec_version_id": training_spec.training_spec_version_id,
                "worker_runtime_fingerprint": runtime.fingerprint,
                "code_version": request.code_version,
                "truth": "PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE",
                "ordinal_semantics": materialized.ordinal_semantics,
                "timestamp_semantics": materialized.timestamp_semantics,
            }
            provenance_artifact_id = canonical_artifact_id(provenance_payload)
            trained = train_model(
                worker=self._worker,
                dataset=materialized.runtime_dataset,
                split_spec=split_spec,
                training_spec=training_spec,
                samples=train_samples + validation_samples,
                code_version=request.code_version,
                training_evidence_provenance_artifact_id=provenance_artifact_id,
                model_provenance_artifact_id=provenance_artifact_id,
                proposed_state=request.proposed_state,
            )
        except Exception as exc:
            return self._failure_after_materialization(ModelPipelineStatus.TRAIN_FAILED, request, materialized, split_spec, str(exc))

        try:
            provenance_descriptor = self._publisher.publish_record(
                provenance_payload,
                provenance_entity_id=resolution.receipt.receipt_identity,
                schema_fingerprint=MODEL_PIPELINE_SCHEMA_FINGERPRINT,
                semantic_fingerprint=training_spec.training_spec_version_id,
            )
            if provenance_descriptor.artifact_id != provenance_artifact_id:
                raise ValueError("training provenance publication identity drifted")
            safe_model_descriptor = self._publisher.publish_safe_model(
                trained.artifact,
                provenance_entity_id=trained.training_evidence.training_evidence_id,
                schema_fingerprint=training_spec.feature_schema_fingerprint,
                semantic_fingerprint=trained.model.model_version_id,
            )
            training_descriptor = self._publisher.publish_record(
                self._training_record(trained),
                provenance_entity_id=provenance_artifact_id,
                schema_fingerprint=MODEL_PIPELINE_SCHEMA_FINGERPRINT,
                semantic_fingerprint=trained.training_evidence.training_evidence_id,
            )
            model_version_descriptor = self._publisher.publish_record(
                self._model_record(trained),
                provenance_entity_id=provenance_artifact_id,
                schema_fingerprint=MODEL_PIPELINE_SCHEMA_FINGERPRINT,
                semantic_fingerprint=trained.model.model_version_id,
            )
        except Exception as exc:
            return self._failure_after_materialization(ModelPipelineStatus.MODEL_PUBLICATION_FAILED, request, materialized, split_spec, str(exc), trained=trained)

        try:
            prediction_provenance = {
                "schema_version": MODEL_PIPELINE_SCHEMA_VERSION,
                "kind": "MODEL_PREDICTION_PROVENANCE",
                "dataset_version_id": owner.dataset_version_id,
                "dataset_resolution_receipt_id": resolution.receipt.receipt_identity,
                "model_version_id": trained.model.model_version_id,
                "model_artifact_id": trained.artifact.artifact_id,
                "prediction_split": request.prediction_split.value,
                "target_semantics": request.target_semantics,
                "truth": "PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE",
            }
            prediction_provenance_id = canonical_artifact_id(prediction_provenance)
            predicted = predict_model(
                worker=self._worker,
                model=trained.model,
                model_artifact=trained.artifact,
                prediction_dataset=materialized.runtime_dataset,
                training_spec=training_spec,
                samples=prediction_samples,
                prediction_timestamp=materialized.knowledge_cutoff,
                target_semantics=request.target_semantics,
                provenance_artifact_id=prediction_provenance_id,
                proposed_state=request.proposed_state,
            )
        except Exception as exc:
            return self._failure_after_materialization(ModelPipelineStatus.PREDICT_FAILED, request, materialized, split_spec, str(exc), trained=trained, training_descriptor=training_descriptor, model_version_descriptor=model_version_descriptor)

        try:
            prediction_provenance_descriptor = self._publisher.publish_record(
                prediction_provenance,
                provenance_entity_id=trained.model.model_version_id,
                schema_fingerprint=MODEL_PIPELINE_SCHEMA_FINGERPRINT,
                semantic_fingerprint=predicted.request.model_prediction_request_id,
            )
            if prediction_provenance_descriptor.artifact_id != prediction_provenance_id:
                raise ValueError("prediction provenance publication identity drifted")
            prediction_descriptor = self._publisher.publish_record(
                self._prediction_record(predicted),
                provenance_entity_id=prediction_provenance_id,
                schema_fingerprint=MODEL_PIPELINE_SCHEMA_FINGERPRINT,
                semantic_fingerprint=predicted.prediction.prediction_artifact_id,
            )
        except Exception as exc:
            return self._failure_after_materialization(ModelPipelineStatus.PREDICTION_PUBLICATION_FAILED, request, materialized, split_spec, str(exc), trained=trained, predicted=predicted, training_descriptor=training_descriptor, model_version_descriptor=model_version_descriptor)

        return ModelPipelineResult(
            status=ModelPipelineStatus.SUCCESS,
            dataset_id=owner.dataset_version_id,
            dataset_artifact_id=owner.dataset_descriptor.artifact_id,
            dataset_resolution_receipt_id=resolution.receipt.receipt_identity,
            sample_count=len(materialized.samples),
            train_sample_count=len(train_samples),
            validation_sample_count=len(validation_samples),
            prediction_sample_count=len(prediction_samples),
            model_version_id=trained.model.model_version_id,
            model_artifact_id=safe_model_descriptor.artifact_id,
            training_artifact_id=training_descriptor.artifact_id,
            model_version_artifact_id=model_version_descriptor.artifact_id,
            prediction_id=predicted.prediction.prediction_artifact_id,
            prediction_artifact_id=prediction_descriptor.artifact_id,
            ordinal_semantics=materialized.ordinal_semantics,
            timestamp_semantics=materialized.timestamp_semantics,
        )

    @staticmethod
    def _training_record(trained: TrainedModelBundle) -> dict[str, object]:
        evidence = trained.training_evidence
        return {
            "schema_version": MODEL_PIPELINE_SCHEMA_VERSION,
            "kind": "MODEL_TRAINING_RESULT",
            "training_evidence_id": evidence.training_evidence_id,
            "model_training_request_id": evidence.model_training_request_id,
            "model_run_id": evidence.model_run_id,
            "dataset_version_id": evidence.dataset_version_id,
            "split_spec_id": evidence.split_spec_id,
            "train_sample_count": evidence.train_sample_count,
            "validation_sample_count": evidence.validation_sample_count,
            "train_rmse": evidence.train_rmse,
            "validation_rmse": evidence.validation_rmse,
            "seed": evidence.seed,
            "worker_runtime_fingerprint": evidence.worker_runtime_fingerprint,
            "provenance_artifact_id": evidence.provenance_artifact_id,
        }

    @staticmethod
    def _model_record(trained: TrainedModelBundle) -> dict[str, object]:
        model = trained.model
        return {
            "schema_version": MODEL_PIPELINE_SCHEMA_VERSION,
            "kind": "MODEL_VERSION",
            "model_version_id": model.model_version_id,
            "dataset_version_id": model.dataset_version_id,
            "model_run_id": model.model_run_id,
            "training_spec_version_id": model.training_spec_version_id,
            "model_training_request_id": model.model_training_request_id,
            "worker_training_candidate_digest": model.worker_training_candidate_digest,
            "model_artifact_id": model.model_artifact_id,
            "model_artifact_media_type": model.model_artifact_media_type,
            "feature_schema_fingerprint": model.feature_schema_fingerprint,
            "worker_runtime": model.worker_runtime.to_wire(),
            "seed": model.seed,
            "training_evidence_id": model.training_evidence_id,
            "provenance_artifact_id": model.provenance_artifact_id,
            "truth_admission": model.truth_admission.to_wire(),
        }

    @staticmethod
    def _prediction_record(predicted: PredictionBundle) -> dict[str, object]:
        prediction = predicted.prediction
        return {
            "schema_version": MODEL_PIPELINE_SCHEMA_VERSION,
            "kind": "MODEL_PREDICTION_RESULT",
            "prediction_artifact_id": prediction.prediction_artifact_id,
            "model_version_id": prediction.model_version_id,
            "model_artifact_id": prediction.model_artifact_id,
            "model_prediction_request_id": prediction.model_prediction_request_id,
            "prediction_dataset_version_id": prediction.prediction_dataset_version_id,
            "prediction_row_set_hash": prediction.prediction_row_set_hash,
            "feature_schema_fingerprint": prediction.feature_schema_fingerprint,
            "label_spec_id": prediction.label_spec_id,
            "prediction_timestamp": prediction.prediction_timestamp.isoformat(),
            "target_semantics": prediction.target_semantics,
            "values": [value.to_wire() for value in prediction.values],
            "missing_count": prediction.missing_count,
            "nonfinite_count": prediction.nonfinite_count,
            "worker_runtime_fingerprint": prediction.worker_runtime_fingerprint,
            "provenance_artifact_id": prediction.provenance_artifact_id,
            "truth_admission": prediction.truth_admission.to_wire(),
        }

    @staticmethod
    def _failure_after_materialization(
        status: ModelPipelineStatus,
        request: ModelPipelineRequest,
        materialized: MaterializedModelDataset,
        split_spec: SplitSpec,
        error: str,
        *,
        trained: TrainedModelBundle | None = None,
        predicted: PredictionBundle | None = None,
        training_descriptor: ArtifactDescriptor | None = None,
        model_version_descriptor: ArtifactDescriptor | None = None,
    ) -> ModelPipelineResult:
        return ModelPipelineResult(
            status=status,
            dataset_id=request.dataset_id,
            dataset_artifact_id=materialized.owner.dataset_descriptor.artifact_id,
            dataset_resolution_receipt_id=materialized.resolution_receipt.receipt_identity,
            sample_count=len(materialized.samples),
            train_sample_count=len(_samples_for_split(materialized, split_spec, DatasetSplitRole.TRAIN)),
            validation_sample_count=len(_samples_for_split(materialized, split_spec, DatasetSplitRole.VALIDATION)),
            prediction_sample_count=len(_samples_for_split(materialized, split_spec, request.prediction_split)),
            model_version_id=trained.model.model_version_id if trained else None,
            model_artifact_id=trained.artifact.artifact_id if trained else None,
            training_artifact_id=training_descriptor.artifact_id if training_descriptor else None,
            model_version_artifact_id=model_version_descriptor.artifact_id if model_version_descriptor else None,
            prediction_id=predicted.prediction.prediction_artifact_id if predicted else None,
            ordinal_semantics=materialized.ordinal_semantics,
            timestamp_semantics=materialized.timestamp_semantics,
            error=error,
        )


__all__ = [
    "CanonicalDatasetModelPipelineService",
    "MODEL_PIPELINE_SCHEMA_FINGERPRINT",
    "MODEL_PIPELINE_SCHEMA_VERSION",
    "MaterializedModelDataset",
    "ModelPipelineArtifactPublisher",
    "ModelPipelineRequest",
    "ModelPipelineResult",
    "ModelPipelineStatus",
    "ResolvedModelDatasetVersion",
    "materialize_model_samples",
]
