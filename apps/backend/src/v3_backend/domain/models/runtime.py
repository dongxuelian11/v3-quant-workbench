from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from v3_backend.contracts.common.truth_admission import TruthAdmissionState
from v3_backend.domain.datasets import DatasetVersion, SplitSpec

from .model import (
    ModelEvaluationEvidence,
    ModelRun,
    ModelSample,
    ModelTrainingBinding,
    ModelVersion,
    PredictionArtifact,
    PredictionDatasetView,
    SafeLinearModelArtifact,
    TrainingDatasetView,
    TrainingEvidence,
    TrainingSpecVersion,
    WorkerPredictionCandidate,
    WorkerRuntimeFingerprint,
    WorkerTrainingCandidate,
)


class IsolatedModelWorker(Protocol):
    @property
    def runtime(self) -> WorkerRuntimeFingerprint: ...

    def train(
        self, training_spec: TrainingSpecVersion, view: TrainingDatasetView
    ) -> WorkerTrainingCandidate: ...

    def predict(
        self,
        training_spec: TrainingSpecVersion,
        artifact: SafeLinearModelArtifact,
        view: PredictionDatasetView,
    ) -> WorkerPredictionCandidate: ...


@dataclass(frozen=True, slots=True)
class TrainedModelBundle:
    view: TrainingDatasetView
    binding: ModelTrainingBinding
    run: ModelRun
    candidate: WorkerTrainingCandidate
    training_evidence: TrainingEvidence
    artifact: SafeLinearModelArtifact
    model: ModelVersion


@dataclass(frozen=True, slots=True)
class PredictionBundle:
    view: PredictionDatasetView
    candidate: WorkerPredictionCandidate
    prediction: PredictionArtifact


def train_model(
    *,
    worker: IsolatedModelWorker,
    dataset: DatasetVersion,
    split_spec: SplitSpec,
    training_spec: TrainingSpecVersion,
    samples: tuple[ModelSample, ...],
    code_version: str,
    training_evidence_provenance_artifact_id: str,
    model_provenance_artifact_id: str,
    proposed_state: TruthAdmissionState,
) -> TrainedModelBundle:
    view = TrainingDatasetView.create(
        dataset=dataset,
        split_spec=split_spec,
        training_spec=training_spec,
        samples=samples,
    )
    binding = ModelTrainingBinding.create(
        dataset=dataset,
        training_spec=training_spec,
        code_version=code_version,
        worker_runtime=worker.runtime,
        proposed_state=proposed_state,
    )
    run = ModelRun.create(binding, view)
    candidate = worker.train(training_spec, view)
    evidence = TrainingEvidence.create(
        run=run,
        view=view,
        candidate=candidate,
        provenance_artifact_id=training_evidence_provenance_artifact_id,
    )
    artifact = SafeLinearModelArtifact.create(training_spec, candidate)
    model = ModelVersion.create(
        dataset=dataset,
        run=run,
        training_spec=training_spec,
        artifact=artifact,
        training_evidence=evidence,
        provenance_artifact_id=model_provenance_artifact_id,
        proposed_state=proposed_state,
    )
    return TrainedModelBundle(
        view=view,
        binding=binding,
        run=run,
        candidate=candidate,
        training_evidence=evidence,
        artifact=artifact,
        model=model,
    )


def predict_model(
    *,
    worker: IsolatedModelWorker,
    model: ModelVersion,
    model_artifact: SafeLinearModelArtifact,
    prediction_dataset: DatasetVersion,
    training_spec: TrainingSpecVersion,
    samples: tuple[ModelSample, ...],
    prediction_timestamp: datetime,
    target_semantics: str,
    provenance_artifact_id: str,
    proposed_state: TruthAdmissionState,
) -> PredictionBundle:
    if worker.runtime != model.worker_runtime:
        raise ValueError("prediction worker must exactly match ModelVersion runtime")
    if model_artifact.artifact_id != model.model_artifact_id:
        raise ValueError("prediction must load the exact ModelVersion Artifact")
    view = PredictionDatasetView.create(
        dataset=prediction_dataset,
        model=model,
        training_spec=training_spec,
        samples=samples,
    )
    candidate = worker.predict(training_spec, model_artifact, view)
    prediction = PredictionArtifact.create(
        model=model,
        dataset=prediction_dataset,
        training_spec=training_spec,
        view=view,
        candidate=candidate,
        prediction_timestamp=prediction_timestamp,
        target_semantics=target_semantics,
        provenance_artifact_id=provenance_artifact_id,
        proposed_state=proposed_state,
    )
    return PredictionBundle(view=view, candidate=candidate, prediction=prediction)


def evaluate_prediction(
    *,
    model_bundle: TrainedModelBundle,
    prediction_bundle: PredictionBundle,
    dataset: DatasetVersion,
    split_spec: SplitSpec,
    provenance_artifact_id: str,
) -> ModelEvaluationEvidence:
    return ModelEvaluationEvidence.create(
        model=model_bundle.model,
        dataset=dataset,
        training_evidence=model_bundle.training_evidence,
        prediction=prediction_bundle.prediction,
        prediction_view=prediction_bundle.view,
        split_spec=split_spec,
        provenance_artifact_id=provenance_artifact_id,
    )


__all__ = [
    "IsolatedModelWorker",
    "PredictionBundle",
    "TrainedModelBundle",
    "evaluate_prediction",
    "predict_model",
    "train_model",
]
