from __future__ import annotations

from typing import NoReturn

from .contracts import (
    ModelAgentDraft,
    ModelDraftKind,
    ModelPredictExecutionSpec,
    ModelTrainExecutionSpec,
    UserConfirmationClaim,
)


class ModelDraftApplicationError(ValueError):
    pass


USER_EXECUTION_AUTHORITY_NOT_AVAILABLE = "USER_EXECUTION_AUTHORITY_NOT_AVAILABLE"
EXECUTION_SPEC_BINDING_MISMATCH = "EXECUTION_SPEC_BINDING_MISMATCH"


def _deny_production_execution() -> NoReturn:
    raise ModelDraftApplicationError(
        f"{USER_EXECUTION_AUTHORITY_NOT_AVAILABLE}: no canonical shared user-action authority exists; production Model Agent execution is NOT_AVAILABLE/NOT_RUN"
    )


def verify_model_train_execution_binding(*, draft: ModelAgentDraft, execution_spec: ModelTrainExecutionSpec) -> ModelTrainExecutionSpec:
    try:
        spec = ModelTrainExecutionSpec.model_validate(execution_spec.model_dump(mode="python"))
    except Exception as exc:
        raise ModelDraftApplicationError(f"{EXECUTION_SPEC_BINDING_MISMATCH}: invalid MODEL_TRAIN execution spec") from exc
    if draft.draft_kind is not ModelDraftKind.MODEL_TRAIN or draft.payload.action != "MODEL_TRAIN":
        raise ModelDraftApplicationError(f"{EXECUTION_SPEC_BINDING_MISMATCH}: typed MODEL_TRAIN draft required")
    payload = draft.payload
    if (payload.execution_spec_id != spec.execution_spec_id or payload.execution_spec_sha256 != spec.content_sha256 or payload.context != spec.context or payload.training_spec_version_id != spec.training_spec_version_id or payload.dependency_runtime_fingerprint != spec.worker_runtime_fingerprint):
        raise ModelDraftApplicationError(f"{EXECUTION_SPEC_BINDING_MISMATCH}: draft does not bind exact MODEL_TRAIN execution spec")
    return spec


def verify_model_predict_execution_binding(*, draft: ModelAgentDraft, execution_spec: ModelPredictExecutionSpec) -> ModelPredictExecutionSpec:
    try:
        spec = ModelPredictExecutionSpec.model_validate(execution_spec.model_dump(mode="python"))
    except Exception as exc:
        raise ModelDraftApplicationError(f"{EXECUTION_SPEC_BINDING_MISMATCH}: invalid MODEL_PREDICT execution spec") from exc
    if draft.draft_kind is not ModelDraftKind.MODEL_PREDICT or draft.payload.action != "MODEL_PREDICT":
        raise ModelDraftApplicationError(f"{EXECUTION_SPEC_BINDING_MISMATCH}: typed MODEL_PREDICT draft required")
    payload = draft.payload
    if (payload.execution_spec_id != spec.execution_spec_id or payload.execution_spec_sha256 != spec.content_sha256 or payload.prediction_context != spec.prediction_context or payload.model_version_id != spec.model_version_id or payload.model_artifact_id != spec.model_artifact_id or payload.training_spec_version_id != spec.training_spec_version_id or payload.target_semantics != spec.target_semantics):
        raise ModelDraftApplicationError(f"{EXECUTION_SPEC_BINDING_MISMATCH}: draft does not bind exact MODEL_PREDICT execution spec")
    return spec


def apply_confirmed_model_train(
    *, draft: ModelAgentDraft, confirmation: UserConfirmationClaim,
    execution_spec: ModelTrainExecutionSpec,
) -> NoReturn:
    verify_model_train_execution_binding(draft=draft, execution_spec=execution_spec)
    _deny_production_execution()


def apply_confirmed_model_predict(
    *, draft: ModelAgentDraft, confirmation: UserConfirmationClaim,
    execution_spec: ModelPredictExecutionSpec,
) -> NoReturn:
    verify_model_predict_execution_binding(draft=draft, execution_spec=execution_spec)
    _deny_production_execution()


__all__ = ["EXECUTION_SPEC_BINDING_MISMATCH", "ModelDraftApplicationError", "USER_EXECUTION_AUTHORITY_NOT_AVAILABLE", "apply_confirmed_model_predict", "apply_confirmed_model_train", "verify_model_predict_execution_binding", "verify_model_train_execution_binding"]
