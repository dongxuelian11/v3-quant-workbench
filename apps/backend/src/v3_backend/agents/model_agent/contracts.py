from __future__ import annotations

from enum import StrEnum
from datetime import datetime
import hashlib
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from v3_backend.agents.contracts import ProposalBoundary, StrictAgentModel, deterministic_json


ExactId = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)]
EvidenceStatusText = Literal["AVAILABLE", "NOT_AVAILABLE", "NOT_RUN"]


class ModelDraftKind(StrEnum):
    MODEL_TRAIN = "MODEL_TRAIN"
    MODEL_PREDICT = "MODEL_PREDICT"
    RESULT_COMPARE = "RESULT_COMPARE"
    REVIEW_RUN = "REVIEW_RUN"


class ModelResearchContext(StrictAgentModel):
    dataset_version_id: ExactId
    feature_set_version_id: ExactId
    factor_evaluation_ids: tuple[ExactId, ...] = Field(min_length=1)
    factor_definition_version_ids: tuple[ExactId, ...] = Field(min_length=1)
    feature_materialization_ids: tuple[ExactId, ...] = Field(min_length=1)
    label_spec_id: ExactId
    label_name: ExactId
    label_source_field: ExactId
    horizon_observations: int = Field(ge=1)
    split_spec_id: ExactId
    train_range: tuple[int, int]
    validation_range: tuple[int, int]
    test_range: tuple[int, int]
    purge_observations: int = Field(ge=0)
    embargo_observations: int = Field(ge=0)
    snapshot_id: ExactId
    universe_version_id: ExactId
    knowledge_cutoff: ExactId
    truth_state: ExactId
    admission_state: ExactId
    dataset_artifact_id: ExactId
    provenance_artifact_id: ExactId

    @field_validator("factor_evaluation_ids", "factor_definition_version_ids", "feature_materialization_ids", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def exact_feature_membership(self) -> "ModelResearchContext":
        if not (len(self.factor_evaluation_ids) == len(self.factor_definition_version_ids) == len(self.feature_materialization_ids)):
            raise ValueError("feature definitions and materializations must be exact-bound")
        return self


class ModelSampleExecutionInput(StrictAgentModel):
    sample_id: ExactId
    instrument_id: ExactId
    observation_ordinal: int = Field(ge=0)
    event_time: datetime
    decision_time: datetime
    features: tuple[float, ...] = Field(min_length=1)
    label: float | None = None

    @field_validator("features", mode="before")
    @classmethod
    def feature_arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("event_time", "decision_time")
    @classmethod
    def aware_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("execution sample timestamps must be timezone-aware")
        return value


class ModelTrainExecutionSpec(StrictAgentModel):
    action: Literal["MODEL_TRAIN"] = "MODEL_TRAIN"
    execution_spec_id: ExactId
    content_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    context: ModelResearchContext
    training_spec_version_id: ExactId
    training_spec_content_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    feature_schema_fingerprint: ExactId
    worker_runtime_fingerprint: ExactId
    worker_runtime_content_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    samples: tuple[ModelSampleExecutionInput, ...] = Field(min_length=1)
    code_version: ExactId
    training_evidence_provenance_artifact_id: ExactId
    model_provenance_artifact_id: ExactId
    proposed_truth_state: ExactId
    proposed_admission_state: ExactId

    @field_validator("samples", mode="before")
    @classmethod
    def sample_arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def verify_content_identity(self) -> "ModelTrainExecutionSpec":
        payload = self.model_dump(mode="json", exclude={"execution_spec_id", "content_sha256"})
        digest = hashlib.sha256(deterministic_json(payload).encode("utf-8")).hexdigest()
        if self.content_sha256 != digest or self.execution_spec_id != "mtes_sha256_" + digest:
            raise ValueError("MODEL_TRAIN execution spec identity/content mismatch")
        return self


class ModelPredictExecutionSpec(StrictAgentModel):
    action: Literal["MODEL_PREDICT"] = "MODEL_PREDICT"
    execution_spec_id: ExactId
    content_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    model_version_id: ExactId
    model_artifact_id: ExactId
    model_artifact_content_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    model_training_request_id: ExactId
    training_spec_version_id: ExactId
    training_spec_content_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    prediction_context: ModelResearchContext
    worker_runtime_fingerprint: ExactId
    worker_runtime_content_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    samples: tuple[ModelSampleExecutionInput, ...] = Field(min_length=1)
    prediction_timestamp: datetime
    target_semantics: ExactId
    provenance_artifact_id: ExactId
    proposed_truth_state: ExactId
    proposed_admission_state: ExactId

    @field_validator("samples", mode="before")
    @classmethod
    def prediction_sample_arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("prediction_timestamp")
    @classmethod
    def aware_prediction_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("prediction timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def verify_content_identity(self) -> "ModelPredictExecutionSpec":
        payload = self.model_dump(mode="json", exclude={"execution_spec_id", "content_sha256"})
        digest = hashlib.sha256(deterministic_json(payload).encode("utf-8")).hexdigest()
        if self.content_sha256 != digest or self.execution_spec_id != "mpes_sha256_" + digest:
            raise ValueError("MODEL_PREDICT execution spec identity/content mismatch")
        return self


class ModelResearchProposal(StrictAgentModel):
    research_goal: str
    agent_rationale: str | None = None
    exact_context: ModelResearchContext
    action_drafts: tuple["ModelAgentDraft", ...] = Field(min_length=1, max_length=16)
    next_action_proposals: tuple[str, ...] = ()
    authority_status: Literal["NON_CANONICAL"] = "NON_CANONICAL"
    lifecycle_state: Literal["DRAFT"] = "DRAFT"
    agent_execution_allowed: Literal[False] = False

    @field_validator("action_drafts", "next_action_proposals", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def bind_every_action_to_context(self) -> "ModelResearchProposal":
        for draft in self.action_drafts:
            payload = draft.payload
            context = getattr(payload, "context", None) or getattr(payload, "prediction_context", None)
            if context is not None and context.dataset_version_id != self.exact_context.dataset_version_id:
                raise ValueError("proposal action must bind the exact DatasetVersion")
        return self


class ModelProposalNarrative(StrictAgentModel):
    rationale: str
    next_action_proposals: tuple[str, ...] = Field(default=(), max_length=16)
    evidence_claims: tuple[str, ...] = Field(default=(), max_length=32)

    @field_validator("next_action_proposals", "evidence_claims", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class TrainDraftPayload(StrictAgentModel):
    action: Literal["MODEL_TRAIN"] = "MODEL_TRAIN"
    context: ModelResearchContext
    training_spec_version_id: ExactId
    model_family: ExactId
    parameters: tuple[tuple[ExactId, bool | int | float | str], ...]
    seed: int = Field(ge=0)
    resource_profile: ExactId
    dependency_runtime_fingerprint: ExactId
    execution_spec_id: ExactId
    execution_spec_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    requested_metrics: tuple[ExactId, ...] = Field(min_length=1)
    expected_output_kind: Literal["MODEL_VERSION"] = "MODEL_VERSION"
    evidence_refs: tuple[ExactId, ...] = Field(min_length=1)
    canonical_user_execution_authority: Literal["NOT_AVAILABLE"] = "NOT_AVAILABLE"
    production_execution_state: Literal["NOT_RUN"] = "NOT_RUN"
    agent_execution_allowed: Literal[False] = False

    @field_validator("parameters", "requested_metrics", "evidence_refs", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(tuple(item) if isinstance(item, list) else item for item in value) if isinstance(value, list) else value


class PredictDraftPayload(StrictAgentModel):
    action: Literal["MODEL_PREDICT"] = "MODEL_PREDICT"
    model_version_id: ExactId
    model_artifact_id: ExactId
    training_dataset_version_id: ExactId
    prediction_context: ModelResearchContext
    training_spec_version_id: ExactId
    target_semantics: ExactId
    execution_spec_id: ExactId
    execution_spec_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    expected_output_kind: Literal["PREDICTION_SET"] = "PREDICTION_SET"
    evidence_refs: tuple[ExactId, ...] = Field(min_length=1)
    canonical_user_execution_authority: Literal["NOT_AVAILABLE"] = "NOT_AVAILABLE"
    production_execution_state: Literal["NOT_RUN"] = "NOT_RUN"
    agent_execution_allowed: Literal[False] = False

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class CompareDraftPayload(StrictAgentModel):
    action: Literal["RESULT_COMPARE"] = "RESULT_COMPARE"
    left_evidence_id: ExactId
    right_evidence_id: ExactId
    objective_metric: ExactId | None = None
    objective_split_role: ExactId | None = None
    objective_direction: Literal["MINIMIZE", "MAXIMIZE"] | None = None
    evidence_refs: tuple[ExactId, ...] = Field(min_length=2)
    agent_execution_allowed: Literal[False] = False

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def complete_objective(self) -> "CompareDraftPayload":
        flags = (self.objective_metric is None, self.objective_split_role is None, self.objective_direction is None)
        if len(set(flags)) != 1:
            raise ValueError("comparison draft objective requires metric, split role and direction")
        return self


class ReviewDraftPayload(StrictAgentModel):
    action: Literal["REVIEW_RUN"] = "REVIEW_RUN"
    target_refs: tuple[ExactId, ...] = Field(min_length=1)
    evidence_refs: tuple[ExactId, ...] = Field(min_length=1)
    requested_rule_set_id: ExactId
    agent_execution_allowed: Literal[False] = False

    @field_validator("target_refs", "evidence_refs", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ModelAgentDraft(ProposalBoundary):
    proposal_type: Literal["MODEL_AGENT_DRAFT"] = "MODEL_AGENT_DRAFT"
    draft_kind: ModelDraftKind
    payload: TrainDraftPayload | PredictDraftPayload | CompareDraftPayload | ReviewDraftPayload = Field(discriminator="action")


class MetricEvidence(StrictAgentModel):
    name: ExactId
    split_role: ExactId
    status: EvidenceStatusText
    value: float | None = None
    evidence_ref: ExactId | None = None

    @model_validator(mode="after")
    def require_exact_available_evidence(self) -> "MetricEvidence":
        if self.status == "AVAILABLE" and (self.value is None or self.evidence_ref is None):
            raise ValueError("available metric requires value and exact evidence ref")
        if self.status != "AVAILABLE" and (self.value is not None or self.evidence_ref is not None):
            raise ValueError("missing/not-run metric cannot carry a value or evidence ref")
        return self


class ModelEvidenceView(StrictAgentModel):
    model_version_id: ExactId
    model_family: ExactId
    training_spec_version_id: ExactId
    model_run_id: ExactId
    model_training_request_id: ExactId
    training_evidence_id: ExactId
    dataset_version_id: ExactId
    feature_set_version_id: ExactId
    factor_evaluation_ids: tuple[ExactId, ...]
    label_spec_id: ExactId
    horizon_observations: int = Field(ge=1)
    split_spec_id: ExactId
    train_range: tuple[int, int]
    validation_range: tuple[int, int]
    test_range: tuple[int, int]
    purge_observations: int = Field(ge=0)
    embargo_observations: int = Field(ge=0)
    universe_version_id: ExactId
    snapshot_id: ExactId
    knowledge_cutoff: ExactId
    dataset_artifact_id: ExactId
    dataset_provenance_artifact_id: ExactId
    seed: int = Field(ge=0)
    parameters: tuple[tuple[ExactId, bool | int | float | str], ...]
    worker_runtime_fingerprint: ExactId
    model_artifact_id: ExactId
    provenance_artifact_id: ExactId
    prediction_artifact_id: ExactId | None = None
    model_prediction_request_id: ExactId | None = None
    target_semantics: ExactId | None = None
    evaluation_policy_id: ExactId
    benchmark_id: ExactId | None = None
    experiment_refs: tuple[ExactId, ...] = ()
    reviewer_refs: tuple[ExactId, ...] = ()
    metrics: tuple[MetricEvidence, ...] = ()

    @field_validator("factor_evaluation_ids", "parameters", "experiment_refs", "reviewer_refs", "metrics", mode="before")
    @classmethod
    def arrays_to_tuples(cls, value: object) -> object:
        return tuple(tuple(item) if isinstance(item, list) else item for item in value) if isinstance(value, list) else value


class ModelEvidenceResolutionRequest(StrictAgentModel):
    model_version_id: ExactId
    dataset_version_id: ExactId
    training_spec_version_id: ExactId
    model_artifact_id: ExactId
    training_evidence_id: ExactId
    prediction_artifact_id: ExactId | None = None
    model_evaluation_evidence_id: ExactId | None = None
    experiment_version_id: ExactId
    experiment_run_id: ExactId
    experiment_attempt_id: ExactId
    result_artifact_id: ExactId
    reviewer_report_ids: tuple[ExactId, ...] = Field(min_length=1)
    evaluation_policy_id: ExactId
    benchmark_id: ExactId | None = None

    @field_validator("reviewer_report_ids", mode="before")
    @classmethod
    def reviewer_arrays_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ComparisonStatus(StrEnum):
    COMPARABLE = "COMPARABLE"
    INCOMPARABLE_CONTEXT = "INCOMPARABLE_CONTEXT"


class MetricDelta(StrictAgentModel):
    name: ExactId
    split_role: ExactId
    status: EvidenceStatusText
    left_value: float | None = None
    right_value: float | None = None
    delta_right_minus_left: float | None = None

    @model_validator(mode="after")
    def bind_values_to_status(self) -> "MetricDelta":
        values = (self.left_value, self.right_value, self.delta_right_minus_left)
        if self.status == "AVAILABLE" and any(value is None for value in values):
            raise ValueError("available metric delta requires both values and delta")
        if self.status != "AVAILABLE" and any(value is not None for value in values):
            raise ValueError("missing/not-run metric delta cannot carry values")
        return self


class ModelComparison(StrictAgentModel):
    status: ComparisonStatus
    left_model_version_id: ExactId
    right_model_version_id: ExactId
    context_mismatches: tuple[ExactId, ...] = ()
    metric_deltas: tuple[MetricDelta, ...] = ()
    objective_metric: ExactId | None = None
    objective_split_role: ExactId | None = None
    objective_direction: Literal["MINIMIZE", "MAXIMIZE"] | None = None
    ranking: Literal["LEFT", "RIGHT", "TIE"] | None = None

    @model_validator(mode="after")
    def prohibit_incomparable_ranking(self) -> "ModelComparison":
        if self.status is ComparisonStatus.INCOMPARABLE_CONTEXT and (self.metric_deltas or self.ranking):
            raise ValueError("incomparable contexts cannot be ranked")
        if self.ranking is not None and self.objective_metric is None:
            raise ValueError("ranking requires an explicit objective metric")
        if self.ranking is not None and self.objective_direction is None:
            raise ValueError("ranking requires an explicit objective direction")
        return self


class EvidenceExplanation(StrictAgentModel):
    status: Literal["EVIDENCE_BOUND", "EVIDENCE_MISSING"]
    summary: str
    changed_specs: tuple[str, ...] = ()
    metric_statements: tuple[str, ...] = ()
    reviewer_statements: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    next_action_proposals: tuple[str, ...] = ()
    cited_evidence_refs: tuple[ExactId, ...] = ()
    invented_feature_importance: Literal[False] = False
    invented_shap: Literal[False] = False
    invented_ic: Literal[False] = False
    invented_attribution: Literal[False] = False
    invented_robustness: Literal[False] = False
    invented_causality: Literal[False] = False


class UserConfirmationClaim(StrictAgentModel):
    confirmation_type: Literal["UNTRUSTED_USER_CONFIRMATION_CLAIM"] = "UNTRUSTED_USER_CONFIRMATION_CLAIM"
    action: Literal["MODEL_TRAIN", "MODEL_PREDICT"]
    draft_sha256: str = Field(pattern=r"[0-9a-f]{64}")
    confirmed_by: ExactId
    confirmed_at: datetime
    agent_issued: Literal[False] = False
    authority_status: Literal["UNTRUSTED_CALLER_ASSERTED"] = "UNTRUSTED_CALLER_ASSERTED"

    @field_validator("confirmed_at")
    @classmethod
    def timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("user confirmation timestamp must be timezone-aware")
        return value


# Compatibility name only: this object is explicitly not an execution authority.
UserConfirmation = UserConfirmationClaim
