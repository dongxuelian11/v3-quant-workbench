"""Formal identity-only canonical Risk application publication service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Protocol

from v3_backend.domain.weights import RuntimeIdentity, TargetWeightVector

from .model import RiskPolicySetVersion
from .runtime import apply_risk


class RiskApplicationAuthorityError(RuntimeError):
    """A canonical owner, context, or publication boundary rejected the request."""


_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class CanonicalRiskApplicationRequest:
    """Untrusted identity-level intent; it deliberately contains no numeric payload."""

    project_id: str
    project_context_revision_id: str
    source_target_weight_vector_id: str
    risk_policy_set_version_id: str
    runtime_identity: RuntimeIdentity
    context_identity: str

    def __post_init__(self) -> None:
        if not isinstance(self.project_id, str) or not self.project_id.startswith("prj_"):
            raise RiskApplicationAuthorityError("project_id is not canonical")
        if (
            not isinstance(self.project_context_revision_id, str)
            or not self.project_context_revision_id.startswith("pcr_")
        ):
            raise RiskApplicationAuthorityError(
                "project_context_revision_id is not canonical"
            )
        if not self.source_target_weight_vector_id.startswith("twv_sha256_"):
            raise RiskApplicationAuthorityError("source target identity is not canonical")
        if not self.risk_policy_set_version_id.startswith("rpsv_sha256_"):
            raise RiskApplicationAuthorityError("risk policy-set identity is not canonical")
        if not isinstance(self.runtime_identity, RuntimeIdentity):
            raise TypeError("runtime_identity must be RuntimeIdentity")
        if not isinstance(self.context_identity, str) or _SHA256.fullmatch(self.context_identity) is None:
            raise RiskApplicationAuthorityError("context_identity must be an exact SHA-256")


@dataclass(frozen=True, slots=True)
class CanonicalRiskApplicationPublication:
    source_target_weight_vector_id: str
    risk_policy_set_version_id: str
    risk_application_receipt_id: str
    risk_adjusted_weight_vector_id: str
    receipt_artifact_id: str
    adjusted_artifact_id: str
    context_identity: str
    truth_state: str
    admission_state: str


class CanonicalRiskApplicationOwnerPort(Protocol):
    def require_target_weight(
        self,
        target_weight_vector_id: str,
        *,
        project_id: str,
        project_context_revision_id: str,
        context_identity: str,
    ) -> TargetWeightVector: ...

    def require_risk_policy_set(
        self,
        risk_policy_set_version_id: str,
        *,
        project_id: str,
        project_context_revision_id: str,
        context_identity: str,
        runtime_identity: RuntimeIdentity,
    ) -> RiskPolicySetVersion: ...

    def persist_recomputed_application(
        self,
        request: CanonicalRiskApplicationRequest,
        *,
        expected_receipt_id: str,
        expected_adjusted_id: str,
        published_at: datetime,
    ) -> CanonicalRiskApplicationPublication:
        """Re-resolve and recompute before persisting; callers cannot submit result objects."""


class CanonicalRiskApplicationService:
    """The only formal Risk application mint; input is exact owner intent only."""

    service_version = "v3.canonical-risk-application-service/1.0.0"

    def __init__(self, owner: CanonicalRiskApplicationOwnerPort) -> None:
        self._owner = owner

    def apply_and_publish(
        self,
        request: CanonicalRiskApplicationRequest,
        *,
        published_at: datetime,
    ) -> CanonicalRiskApplicationPublication:
        if not isinstance(request, CanonicalRiskApplicationRequest):
            raise TypeError(
                "formal Risk publication requires CanonicalRiskApplicationRequest"
            )
        if published_at.tzinfo is None or published_at.utcoffset() is None:
            raise RiskApplicationAuthorityError("published_at must be timezone-aware")

        source_target = self._owner.require_target_weight(
            request.source_target_weight_vector_id,
            project_id=request.project_id,
            project_context_revision_id=request.project_context_revision_id,
            context_identity=request.context_identity,
        )
        policy_set = self._owner.require_risk_policy_set(
            request.risk_policy_set_version_id,
            project_id=request.project_id,
            project_context_revision_id=request.project_context_revision_id,
            context_identity=request.context_identity,
            runtime_identity=request.runtime_identity,
        )
        runtime_keys = {
            (policy.code_version, policy.runtime_profile_id)
            for policy in policy_set.policies
        }
        expected_runtime = (
            request.runtime_identity.code_version,
            request.runtime_identity.runtime_profile_id,
        )
        if runtime_keys != {expected_runtime}:
            raise RiskApplicationAuthorityError(
                "request runtime identity does not match canonical policy owner"
            )
        required_state = {
            requirement.input_key
            for policy in policy_set.policies
            for requirement in policy.required_state_inputs
        }
        if required_state:
            raise RiskApplicationAuthorityError(
                "canonical RiskStateInput owner is unavailable for required keys: "
                + ",".join(sorted(required_state))
            )

        result = apply_risk(
            source_target=source_target,
            policy_set=policy_set,
            runtime_identity=request.runtime_identity,
            state_inputs=(),
        )
        return self._owner.persist_recomputed_application(
            request,
            expected_receipt_id=result.application_receipt.risk_application_receipt_id,
            expected_adjusted_id=result.adjusted_weights.risk_adjusted_weight_vector_id,
            published_at=published_at,
        )


__all__ = [
    "CanonicalRiskApplicationOwnerPort",
    "CanonicalRiskApplicationPublication",
    "CanonicalRiskApplicationRequest",
    "CanonicalRiskApplicationService",
    "RiskApplicationAuthorityError",
]
