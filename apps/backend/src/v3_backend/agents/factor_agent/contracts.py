from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from v3_backend.agents.contracts import (
    AgentProvenance,
    PermissionDecision,
    PermissionLevel,
    ProposalBoundary,
    StrictAgentModel,
)


class FactorAgentError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


FactorText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=16384)]
FactorShortText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)]


class FactorToolEffect(StrEnum):
    READ = "READ"
    DRAFT = "DRAFT"


class FactorToolDescriptor(StrictAgentModel):
    name: FactorShortText
    required_permission: PermissionLevel
    effect: FactorToolEffect
    agent_callable: Literal[True] = True


FACTOR_AGENT_TOOL_CATALOG = (
    FactorToolDescriptor(name="factor_catalog_search", required_permission=PermissionLevel.L0_READ, effect=FactorToolEffect.READ),
    FactorToolDescriptor(name="factor_catalog_read", required_permission=PermissionLevel.L0_READ, effect=FactorToolEffect.READ),
    FactorToolDescriptor(name="factor_evidence_explain", required_permission=PermissionLevel.L0_READ, effect=FactorToolEffect.READ),
    FactorToolDescriptor(name="factor_draft_natural_language", required_permission=PermissionLevel.L1_DRAFT, effect=FactorToolEffect.DRAFT),
    FactorToolDescriptor(name="factor_tdx_preview", required_permission=PermissionLevel.L1_DRAFT, effect=FactorToolEffect.DRAFT),
    FactorToolDescriptor(name="factor_import_action_draft", required_permission=PermissionLevel.L1_DRAFT, effect=FactorToolEffect.DRAFT),
    FactorToolDescriptor(name="factor_evaluate_action_draft", required_permission=PermissionLevel.L1_DRAFT, effect=FactorToolEffect.DRAFT),
)


class FactorDraftPayload(StrictAgentModel):
    draft_kind: Literal["TDX", "V3_FACTOR_IR"]
    draft_payload: FactorText
    rationale: FactorText
    expected_inputs: tuple[FactorShortText, ...] = Field(min_length=1, max_length=64)
    expected_output: Literal["FLOAT_SERIES", "BOOLEAN_SERIES"]
    unsupported_assumptions: tuple[FactorText, ...] = Field(default=(), max_length=64)
    arbitrary_python: Literal[None] = None
    execution_requested: Literal[False] = False
    review_or_promotion_requested: Literal[False] = False

    @field_validator("expected_inputs", "unsupported_assumptions", mode="before")
    @classmethod
    def accept_json_arrays(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def forbid_python_and_eval(self) -> FactorDraftPayload:
        normalized = self.draft_payload.casefold()
        if self.draft_kind == "TDX" and any(token in normalized for token in ("import ", "exec(", "eval(", "__")):
            raise ValueError("arbitrary Python/eval is not a factor draft")
        return self


class FactorDraftResponse(ProposalBoundary):
    proposal_type: Literal["FACTOR_DRAFT_PROPOSAL"] = "FACTOR_DRAFT_PROPOSAL"
    payload: FactorDraftPayload


class FactorDraftProvenance(AgentProvenance):
    instruction_version: Literal["round5-p-factor-draft/1.0.0"] = "round5-p-factor-draft/1.0.0"


def require_factor_l1(decision: PermissionDecision) -> None:
    if not decision.allowed or decision.normalized is not PermissionLevel.L1_DRAFT:
        raise FactorAgentError("FACTOR_AGENT_L1_REQUIRED", decision.reason)
