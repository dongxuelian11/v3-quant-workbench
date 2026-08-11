from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


NonEmptyText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=4096)]
ShortText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)]
Sha256Text = Annotated[str, StringConstraints(strict=True, pattern=r"[0-9a-f]{64}")]


class StrictAgentModel(BaseModel):
    """Closed, immutable wire model with deterministic serialization."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def to_deterministic_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def deterministic_sha256(self) -> str:
        return hashlib.sha256(self.to_deterministic_json().encode("utf-8")).hexdigest()


class PermissionLevel(str, Enum):
    L0_READ = "L0_READ"
    L1_DRAFT = "L1_DRAFT"
    L2_EXECUTE = "L2_EXECUTE"
    L3_PUBLISH = "L3_PUBLISH"


class PermissionDecision(StrictAgentModel):
    requested: ShortText
    normalized: PermissionLevel | None
    allowed: bool
    reason: ShortText

    @model_validator(mode="after")
    def enforce_v0_boundary(self) -> PermissionDecision:
        allowed_levels = {PermissionLevel.L0_READ, PermissionLevel.L1_DRAFT}
        if self.allowed != (self.normalized in allowed_levels):
            raise ValueError("permission decision exceeds the Track D V0 boundary")
        return self


class AgentKind(str, Enum):
    RESEARCH = "RESEARCH"
    DATA = "DATA"
    REVIEWER = "REVIEWER"


class AgentProvenance(StrictAgentModel):
    agent_kind: AgentKind
    sdk_name: Literal["pydantic-ai"] = "pydantic-ai"
    sdk_version: ShortText
    model_name: ShortText
    provider_name: ShortText
    prompt_version: ShortText
    instruction_version: ShortText
    input_sha256: Sha256Text


class ProposalBoundary(StrictAgentModel):
    authority_status: Literal["NON_CANONICAL"] = "NON_CANONICAL"
    lifecycle_state: Literal["DRAFT"] = "DRAFT"
    canonical_identity: Literal[None] = None
    admission_decision: Literal[None] = None
    publish_authority: Literal[False] = False
    permission_decision: PermissionDecision
    provenance: AgentProvenance

    @model_validator(mode="after")
    def require_draft_permission(self) -> ProposalBoundary:
        if not self.permission_decision.allowed:
            raise ValueError("a denied permission cannot produce a draft")
        if self.permission_decision.normalized is not PermissionLevel.L1_DRAFT:
            raise ValueError("agent proposals require L1_DRAFT")
        return self


class AlphaMiningRequestIntent(StrictAgentModel):
    hypothesis: NonEmptyText
    research_objective: NonEmptyText
    universe_intent: NonEmptyText
    factor_intents: tuple[NonEmptyText, ...] = Field(min_length=1, max_length=32)
    dataset_intents: tuple[NonEmptyText, ...] = Field(min_length=1, max_length=32)
    experiment_intent: NonEmptyText
    worker_triggered: Literal[False] = False

    @field_validator("factor_intents", "dataset_intents", mode="before")
    @classmethod
    def accept_json_arrays(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ResearchPayload(StrictAgentModel):
    alpha_mining_request: AlphaMiningRequestIntent
    assumptions: tuple[NonEmptyText, ...] = Field(default=(), max_length=64)
    open_questions: tuple[NonEmptyText, ...] = Field(default=(), max_length=64)

    @field_validator("assumptions", "open_questions", mode="before")
    @classmethod
    def accept_json_arrays(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ResearchDraft(ProposalBoundary):
    proposal_type: Literal["RESEARCH_DRAFT"] = "RESEARCH_DRAFT"
    payload: ResearchPayload


class FindingSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKING_EVIDENCE = "BLOCKING_EVIDENCE"


class DataFindingKind(str, Enum):
    PIT_AVAILABLE_TIME = "PIT_AVAILABLE_TIME"
    REVISION = "REVISION"
    MISSINGNESS = "MISSINGNESS"
    PROVIDER_PROVENANCE = "PROVIDER_PROVENANCE"
    HISTORICAL_UNIVERSE = "HISTORICAL_UNIVERSE"
    SURVIVORSHIP = "SURVIVORSHIP"
    TRUTH_ADMISSION_CEILING_WARNING = "TRUTH_ADMISSION_CEILING_WARNING"


class DataFinding(StrictAgentModel):
    kind: DataFindingKind
    severity: FindingSeverity
    summary: NonEmptyText
    evidence: tuple[NonEmptyText, ...] = Field(min_length=1, max_length=64)

    @field_validator("kind", mode="before")
    @classmethod
    def accept_exact_kind_string(cls, value: object) -> object:
        return DataFindingKind(value) if isinstance(value, str) else value

    @field_validator("severity", mode="before")
    @classmethod
    def accept_exact_severity_string(cls, value: object) -> object:
        return FindingSeverity(value) if isinstance(value, str) else value

    @field_validator("evidence", mode="before")
    @classmethod
    def accept_json_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class DataFindingsPayload(StrictAgentModel):
    findings: tuple[DataFinding, ...] = Field(min_length=1, max_length=128)

    @field_validator("findings", mode="before")
    @classmethod
    def accept_json_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class DataReviewDraft(ProposalBoundary):
    proposal_type: Literal["DATA_REVIEW_FINDINGS"] = "DATA_REVIEW_FINDINGS"
    reviewed_input_sha256: Sha256Text
    payload: DataFindingsPayload


class ReviewerFindingKind(str, Enum):
    LOOK_AHEAD = "LOOK_AHEAD"
    LEAKAGE = "LEAKAGE"
    OVERFITTING_RISK = "OVERFITTING_RISK"
    MULTIPLE_TESTING_RISK = "MULTIPLE_TESTING_RISK"
    SAMPLE_INSUFFICIENCY = "SAMPLE_INSUFFICIENCY"
    TURNOVER_COST_SENSITIVITY = "TURNOVER_COST_SENSITIVITY"
    REGIME_DEPENDENCY = "REGIME_DEPENDENCY"
    ROBUSTNESS_CONCERN = "ROBUSTNESS_CONCERN"


class ReviewerFinding(StrictAgentModel):
    kind: ReviewerFindingKind
    severity: FindingSeverity
    summary: NonEmptyText
    evidence: tuple[NonEmptyText, ...] = Field(min_length=1, max_length=64)

    @field_validator("kind", mode="before")
    @classmethod
    def accept_exact_kind_string(cls, value: object) -> object:
        return ReviewerFindingKind(value) if isinstance(value, str) else value

    @field_validator("severity", mode="before")
    @classmethod
    def accept_exact_severity_string(cls, value: object) -> object:
        return FindingSeverity(value) if isinstance(value, str) else value

    @field_validator("evidence", mode="before")
    @classmethod
    def accept_json_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ReviewerFindingsPayload(StrictAgentModel):
    findings: tuple[ReviewerFinding, ...] = Field(min_length=1, max_length=128)

    @field_validator("findings", mode="before")
    @classmethod
    def accept_json_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ReviewerReviewDraft(ProposalBoundary):
    proposal_type: Literal["REVIEWER_FINDINGS"] = "REVIEWER_FINDINGS"
    reviewed_proposal_sha256: Sha256Text
    payload: ReviewerFindingsPayload


def deterministic_json(value: Any) -> str:
    """Serialize a JSON-compatible value without permitting NaN or key-order drift."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
