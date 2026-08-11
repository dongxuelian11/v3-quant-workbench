from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from v3_backend.agents.contracts import (
    NonEmptyText,
    ProposalBoundary,
    ResearchPayload,
    Sha256Text,
    ShortText,
    StrictAgentModel,
)
from v3_backend.agents.contracts import FindingSeverity as AgentFindingSeverity
from v3_backend.contracts.common.truth_admission import (
    AdmissionState,
    TruthAdmissionState,
    TruthState,
)
from v3_backend.domain.data_truth import PitEvidenceState
from v3_backend.domain.experiments import EvidenceStatus, ExperimentAttemptState


ObjectId = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)]
ReasonCode = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)]


class TruthAdmissionEvidence(StrictAgentModel):
    canonical_truth_state: TruthState
    canonical_admission_state: AdmissionState

    @classmethod
    def from_state(cls, state: TruthAdmissionState) -> TruthAdmissionEvidence:
        if not isinstance(state, TruthAdmissionState):
            raise TypeError("truth evidence requires exact TruthAdmissionState")
        return cls(
            canonical_truth_state=state.truth,
            canonical_admission_state=state.admission,
        )


class EvidenceObjectKind(StrEnum):
    SNAPSHOT = "SNAPSHOT"
    DATASET = "DATASET"
    EXPERIMENT_RUN = "EXPERIMENT_RUN"
    REWARD_VECTOR = "REWARD_VECTOR"
    REVIEWER_EVIDENCE = "REVIEWER_EVIDENCE"
    PROVENANCE = "PROVENANCE"


class MissingEvidence(StrictAgentModel):
    status: Literal["MISSING"] = "MISSING"
    object_kind: EvidenceObjectKind
    requested_object_id: ObjectId
    warning_code: Literal["REQUESTED_EVIDENCE_NOT_FOUND"] = "REQUESTED_EVIDENCE_NOT_FOUND"


class SnapshotEvidence(StrictAgentModel):
    status: Literal["FOUND"] = "FOUND"
    snapshot_id: ObjectId
    normalization_version: ShortText
    truth_ceiling: TruthAdmissionEvidence
    pit_evidence: PitEvidenceState
    revision_evidence: PitEvidenceState
    reason_codes: tuple[ReasonCode, ...] = Field(max_length=64)
    raw_capture_ids: tuple[ObjectId, ...] = Field(max_length=64)
    acquisition_ids: tuple[ObjectId, ...] = Field(max_length=64)
    research_universe_input_id: ObjectId
    instrument_count: int = Field(ge=0)
    sample_instrument_ids: tuple[ObjectId, ...] = Field(max_length=64)
    instruments_truncated: bool
    record_count: int = Field(ge=0)
    missing_value_count: int = Field(ge=0)
    provenance_refs: tuple[ObjectId, ...] = Field(max_length=128)
    response_truncated: bool


class DatasetSplitEvidence(StrictAgentModel):
    split_spec_id: ObjectId
    train_start: int
    train_end: int
    validation_start: int
    validation_end: int
    test_start: int
    test_end: int
    purge_observations: int = Field(ge=0)
    embargo_observations: int = Field(ge=0)


class DatasetEvidence(StrictAgentModel):
    status: Literal["FOUND"] = "FOUND"
    dataset_version_id: ObjectId
    snapshot_id: ObjectId
    universe_version_id: ObjectId
    knowledge_cutoff: ShortText
    feature_set_version_id: ObjectId
    factor_evaluation_count: int = Field(ge=0)
    factor_evaluation_ids: tuple[ObjectId, ...] = Field(max_length=64)
    factor_evaluations_truncated: bool
    label_spec_id: ObjectId
    split: DatasetSplitEvidence
    truth_admission: TruthAdmissionEvidence
    provenance_refs: tuple[ObjectId, ...] = Field(max_length=128)
    response_truncated: bool


class ExperimentAttemptEvidence(StrictAgentModel):
    experiment_attempt_id: ObjectId
    ordinal: int = Field(ge=1)
    state: ExperimentAttemptState
    started_at: ShortText
    ended_at: ShortText
    evidence_artifact_ids: tuple[ObjectId, ...] = Field(max_length=64)
    result_artifact_id: ObjectId | None
    error_code: ShortText | None


class ExperimentEvidence(StrictAgentModel):
    status: Literal["FOUND"] = "FOUND"
    experiment_version_id: ObjectId
    logical_name: ShortText
    objective: NonEmptyText
    protocol_version: ShortText
    experiment_run_id: ObjectId
    dataset_version_id: ObjectId
    factor_evaluation_id: ObjectId
    code_version: ShortText
    environment_fingerprint: ShortText
    input_artifact_ids: tuple[ObjectId, ...] = Field(max_length=64)
    attempt_count: int = Field(ge=0)
    attempts: tuple[ExperimentAttemptEvidence, ...] = Field(max_length=64)
    attempts_truncated: bool
    truth_admission: TruthAdmissionEvidence
    provenance_refs: tuple[ObjectId, ...] = Field(max_length=128)
    response_truncated: bool


class RewardVectorEvidence(StrictAgentModel):
    status: Literal["FOUND"] = "FOUND"
    reward_vector_id: ObjectId
    experiment_run_id: ObjectId
    experiment_attempt_id: ObjectId
    reviewer_evidence_id: ObjectId
    coverage: float
    ic: float
    rank_ic: float
    lower_quantile_return: float
    upper_quantile_return: float
    quantile_spread: float
    turnover: float
    complexity: int = Field(ge=1)
    truth_admission: TruthAdmissionEvidence
    provenance_refs: tuple[ObjectId, ...] = Field(max_length=128)
    response_truncated: bool


class ReviewerEvidenceView(StrictAgentModel):
    status: Literal["FOUND"] = "FOUND"
    reviewer_evidence_id: ObjectId
    lookahead: EvidenceStatus
    leakage: EvidenceStatus
    split: EvidenceStatus
    sample_coverage: EvidenceStatus
    missingness: EvidenceStatus
    turnover: EvidenceStatus
    complexity: EvidenceStatus
    multiple_testing_robustness: EvidenceStatus
    finding_ids: tuple[ObjectId, ...] = Field(max_length=128)
    truth_ceiling: TruthAdmissionEvidence
    provenance_refs: tuple[ObjectId, ...] = Field(max_length=128)
    response_truncated: bool


class ProvenanceEvidence(StrictAgentModel):
    status: Literal["FOUND"] = "FOUND"
    object_id: ObjectId
    provenance_refs: tuple[ObjectId, ...] = Field(min_length=1, max_length=128)
    response_truncated: bool


class EvidenceToolCall(StrictAgentModel):
    tool_name: ShortText
    requested_object_id: ObjectId
    lookup_status: Literal["FOUND", "MISSING"]
    response_sha256: Sha256Text
    evidence_object_ids: tuple[ObjectId, ...] = Field(min_length=1, max_length=128)
    provenance_refs: tuple[ObjectId, ...] = Field(max_length=128)


class AgentEvidenceTrace(StrictAgentModel):
    input_object_ids: tuple[ObjectId, ...] = Field(min_length=1, max_length=64)
    input_sha256: Sha256Text
    tool_calls: tuple[EvidenceToolCall, ...] = Field(min_length=1, max_length=32)
    evidence_refs: tuple[ObjectId, ...] = Field(max_length=256)
    missing_evidence_ids: tuple[ObjectId, ...] = Field(max_length=64)

    @model_validator(mode="after")
    def require_trace_consistency(self) -> AgentEvidenceTrace:
        evidenced_ids = {
            object_id
            for item in self.tool_calls
            for object_id in item.evidence_object_ids
        }
        if not set(self.input_object_ids).issubset(
            evidenced_ids | set(self.missing_evidence_ids)
        ):
            raise ValueError("every exact input object must have a trusted tool receipt")
        observed_missing = tuple(
            sorted(
                {
                    *(
                        item.requested_object_id
                        for item in self.tool_calls
                        if item.lookup_status == "MISSING"
                    ),
                    *(
                        value
                        for value in self.input_object_ids
                        if value not in evidenced_ids
                    ),
                }
            )
        )
        if observed_missing != self.missing_evidence_ids:
            raise ValueError("missing evidence IDs must be derived from tool receipts")
        return self


class ResearchEvidenceDraft(ProposalBoundary):
    proposal_type: Literal["RESEARCH_EVIDENCE_DRAFT"] = "RESEARCH_EVIDENCE_DRAFT"
    evidence_trace: AgentEvidenceTrace
    cited_evidence_object_ids: tuple[ObjectId, ...] = Field(min_length=1, max_length=64)
    payload: ResearchPayload

    @model_validator(mode="after")
    def citations_are_system_trace(self) -> ResearchEvidenceDraft:
        if self.cited_evidence_object_ids != self.evidence_trace.input_object_ids:
            raise ValueError("research citations must be exact system-owned evidence inputs")
        return self


class DataEvidenceFindingKind(StrEnum):
    PIT_AVAILABLE_TIME = "PIT_AVAILABLE_TIME"
    REVISION = "REVISION"
    PROVIDER_PROVENANCE = "PROVIDER_PROVENANCE"
    MISSINGNESS = "MISSINGNESS"
    HISTORICAL_UNIVERSE = "HISTORICAL_UNIVERSE"
    SURVIVORSHIP = "SURVIVORSHIP"
    TRUTH_ADMISSION_CEILING = "TRUTH_ADMISSION_CEILING"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"


class DataFindingNarrative(StrictAgentModel):
    kind: DataEvidenceFindingKind
    severity: AgentFindingSeverity
    finding: NonEmptyText
    reason: NonEmptyText
    recommended_next_check: NonEmptyText
    pit_pass_claimed: Literal[False] = False

    @field_validator("kind", mode="before")
    @classmethod
    def accept_exact_kind_string(cls, value: object) -> object:
        return DataEvidenceFindingKind(value) if isinstance(value, str) else value

    @field_validator("severity", mode="before")
    @classmethod
    def accept_exact_severity_string(cls, value: object) -> object:
        return AgentFindingSeverity(value) if isinstance(value, str) else value


class DataFindingNarrativePayload(StrictAgentModel):
    findings: tuple[DataFindingNarrative, ...] = Field(min_length=1, max_length=128)

    @field_validator("findings", mode="before")
    @classmethod
    def accept_json_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class DataEvidenceFinding(DataFindingNarrative):
    evidence_object_ids: tuple[ObjectId, ...] = Field(min_length=1, max_length=64)


class DataEvidenceFindingsPayload(StrictAgentModel):
    findings: tuple[DataEvidenceFinding, ...] = Field(min_length=1, max_length=128)


class DataEvidenceReviewDraft(ProposalBoundary):
    proposal_type: Literal["DATA_EVIDENCE_FINDINGS"] = "DATA_EVIDENCE_FINDINGS"
    evidence_trace: AgentEvidenceTrace
    reviewed_input_sha256: Sha256Text
    payload: DataEvidenceFindingsPayload

    @model_validator(mode="after")
    def reviewed_hash_is_system_trace(self) -> DataEvidenceReviewDraft:
        if self.reviewed_input_sha256 != self.evidence_trace.input_sha256:
            raise ValueError("reviewed input hash must come from the system evidence trace")
        expected = self.evidence_trace.input_object_ids
        if any(item.evidence_object_ids != expected for item in self.payload.findings):
            raise ValueError("data finding citations must be system-owned")
        return self


class ReviewerEvidenceFindingKind(StrEnum):
    LOOK_AHEAD = "LOOK_AHEAD"
    LEAKAGE = "LEAKAGE"
    SPLIT_PURGE_EMBARGO = "SPLIT_PURGE_EMBARGO"
    OVERFITTING_RISK = "OVERFITTING_RISK"
    MULTIPLE_TESTING_RISK = "MULTIPLE_TESTING_RISK"
    SAMPLE_INSUFFICIENCY = "SAMPLE_INSUFFICIENCY"
    TURNOVER = "TURNOVER"
    REGIME_ROBUSTNESS = "REGIME_ROBUSTNESS"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"


class ReviewerFindingNarrative(StrictAgentModel):
    kind: ReviewerEvidenceFindingKind
    severity: AgentFindingSeverity
    finding: NonEmptyText
    reason: NonEmptyText
    recommended_next_check: NonEmptyText

    @field_validator("kind", mode="before")
    @classmethod
    def accept_exact_kind_string(cls, value: object) -> object:
        return ReviewerEvidenceFindingKind(value) if isinstance(value, str) else value

    @field_validator("severity", mode="before")
    @classmethod
    def accept_exact_severity_string(cls, value: object) -> object:
        return AgentFindingSeverity(value) if isinstance(value, str) else value


class ReviewerFindingNarrativePayload(StrictAgentModel):
    findings: tuple[ReviewerFindingNarrative, ...] = Field(min_length=1, max_length=128)

    @field_validator("findings", mode="before")
    @classmethod
    def accept_json_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ReviewerEvidenceFinding(ReviewerFindingNarrative):
    evidence_object_ids: tuple[ObjectId, ...] = Field(min_length=1, max_length=64)


class ReviewerEvidenceFindingsPayload(StrictAgentModel):
    findings: tuple[ReviewerEvidenceFinding, ...] = Field(min_length=1, max_length=128)


class ReviewerEvidenceReviewDraft(ProposalBoundary):
    proposal_type: Literal["REVIEWER_EVIDENCE_FINDINGS"] = "REVIEWER_EVIDENCE_FINDINGS"
    evidence_trace: AgentEvidenceTrace
    reviewed_evidence_sha256: Sha256Text
    payload: ReviewerEvidenceFindingsPayload

    @model_validator(mode="after")
    def reviewed_hash_is_system_trace(self) -> ReviewerEvidenceReviewDraft:
        if self.reviewed_evidence_sha256 != self.evidence_trace.input_sha256:
            raise ValueError("reviewed evidence hash must come from the system evidence trace")
        expected = self.evidence_trace.input_object_ids
        if any(item.evidence_object_ids != expected for item in self.payload.findings):
            raise ValueError("reviewer finding citations must be system-owned")
        return self


SnapshotLookup = SnapshotEvidence | MissingEvidence
DatasetLookup = DatasetEvidence | MissingEvidence
ExperimentLookup = ExperimentEvidence | MissingEvidence
RewardVectorLookup = RewardVectorEvidence | MissingEvidence
ReviewerEvidenceLookup = ReviewerEvidenceView | MissingEvidence
ProvenanceLookup = ProvenanceEvidence | MissingEvidence


__all__ = [
    "AgentEvidenceTrace",
    "DataEvidenceFinding",
    "DataEvidenceFindingKind",
    "DataEvidenceFindingsPayload",
    "DataEvidenceReviewDraft",
    "DataFindingNarrative",
    "DataFindingNarrativePayload",
    "DatasetEvidence",
    "DatasetLookup",
    "DatasetSplitEvidence",
    "EvidenceObjectKind",
    "EvidenceToolCall",
    "ExperimentAttemptEvidence",
    "ExperimentEvidence",
    "ExperimentLookup",
    "MissingEvidence",
    "ProvenanceEvidence",
    "ProvenanceLookup",
    "ResearchEvidenceDraft",
    "ReviewerEvidenceFinding",
    "ReviewerEvidenceFindingKind",
    "ReviewerEvidenceFindingsPayload",
    "ReviewerEvidenceLookup",
    "ReviewerEvidenceReviewDraft",
    "ReviewerEvidenceView",
    "ReviewerFindingNarrative",
    "ReviewerFindingNarrativePayload",
    "RewardVectorEvidence",
    "RewardVectorLookup",
    "SnapshotEvidence",
    "SnapshotLookup",
    "TruthAdmissionEvidence",
]
