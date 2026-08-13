from __future__ import annotations

from datetime import datetime

from v3_backend.contracts.common.truth_admission import TruthAdmissionState
from v3_backend.domain.datasets import DatasetVersion, SplitSpec
from v3_backend.domain.models import (
    IsolatedModelWorker,
    ModelSample,
    ModelVersion,
    PredictionBundle,
    SafeLinearModelArtifact,
    TrainedModelBundle,
    TrainingSpecVersion,
    predict_model,
    train_model,
)

from .contracts import ModelAgentDraft, ModelDraftKind, UserConfirmation


class ModelDraftApplicationError(ValueError):
    pass


def _confirmed(draft: ModelAgentDraft, confirmation: UserConfirmation, expected: ModelDraftKind) -> None:
    if draft.draft_kind is not expected:
        raise ModelDraftApplicationError("confirmation action does not match draft kind")
    if confirmation.action != expected.value:
        raise ModelDraftApplicationError("confirmation action does not match application command")
    if confirmation.draft_sha256 != draft.deterministic_sha256:
        raise ModelDraftApplicationError("user confirmation must bind the exact draft hash")
    if confirmation.agent_issued:
        raise ModelDraftApplicationError("Agent-issued confirmation is forbidden")


def apply_confirmed_model_train(
    *, draft: ModelAgentDraft, confirmation: UserConfirmation,
    worker: IsolatedModelWorker, dataset: DatasetVersion, split_spec: SplitSpec,
    training_spec: TrainingSpecVersion, samples: tuple[ModelSample, ...], code_version: str,
    training_evidence_provenance_artifact_id: str, model_provenance_artifact_id: str,
    proposed_state: TruthAdmissionState,
) -> TrainedModelBundle:
    _confirmed(draft, confirmation, ModelDraftKind.MODEL_TRAIN)
    payload = draft.payload
    if payload.action != "MODEL_TRAIN":
        raise ModelDraftApplicationError("typed train payload required")
    if dataset.dataset_version_id != payload.context.dataset_version_id:
        raise ModelDraftApplicationError("application DatasetVersion mismatch")
    if split_spec.split_spec_id != payload.context.split_spec_id:
        raise ModelDraftApplicationError("application SplitSpec mismatch")
    if training_spec.training_spec_version_id != payload.training_spec_version_id:
        raise ModelDraftApplicationError("application TrainingSpecVersion mismatch")
    if worker.runtime.fingerprint != payload.dependency_runtime_fingerprint:
        raise ModelDraftApplicationError("application worker runtime mismatch")
    return train_model(worker=worker, dataset=dataset, split_spec=split_spec, training_spec=training_spec, samples=samples, code_version=code_version, training_evidence_provenance_artifact_id=training_evidence_provenance_artifact_id, model_provenance_artifact_id=model_provenance_artifact_id, proposed_state=proposed_state)


def apply_confirmed_model_predict(
    *, draft: ModelAgentDraft, confirmation: UserConfirmation,
    worker: IsolatedModelWorker, model: ModelVersion, model_artifact: SafeLinearModelArtifact,
    prediction_dataset: DatasetVersion, training_spec: TrainingSpecVersion,
    samples: tuple[ModelSample, ...], prediction_timestamp: datetime,
    provenance_artifact_id: str, proposed_state: TruthAdmissionState,
) -> PredictionBundle:
    _confirmed(draft, confirmation, ModelDraftKind.MODEL_PREDICT)
    payload = draft.payload
    if payload.action != "MODEL_PREDICT":
        raise ModelDraftApplicationError("typed prediction payload required")
    if model.model_version_id != payload.model_version_id or model_artifact.artifact_id != payload.model_artifact_id:
        raise ModelDraftApplicationError("application ModelVersion/Artifact mismatch")
    if prediction_dataset.dataset_version_id != payload.prediction_context.dataset_version_id:
        raise ModelDraftApplicationError("application prediction DatasetVersion mismatch")
    if training_spec.training_spec_version_id != payload.training_spec_version_id:
        raise ModelDraftApplicationError("application TrainingSpecVersion mismatch")
    return predict_model(worker=worker, model=model, model_artifact=model_artifact, prediction_dataset=prediction_dataset, training_spec=training_spec, samples=samples, prediction_timestamp=prediction_timestamp, target_semantics=payload.target_semantics, provenance_artifact_id=provenance_artifact_id, proposed_state=proposed_state)


__all__ = ["ModelDraftApplicationError", "apply_confirmed_model_predict", "apply_confirmed_model_train"]
