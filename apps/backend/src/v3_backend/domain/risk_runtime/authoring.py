"""Trusted RiskPolicy definition authoring and canonical owner publication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, TypeAlias

from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
from v3_backend.domain.weights import RuntimeIdentity

from .model import (
    RiskModelRequirement,
    RiskPolicyDefinition,
    RiskPolicySetVersion,
    RiskStateRequirement,
)


RISK_POLICY_OWNER_NAMESPACE = "v3.risk.policy-set-version"
RISK_POLICY_PAYLOAD_ROLE = "RISK_POLICY_SET"
RISK_POLICY_SERIALIZATION_VERSION = "v3.riskpolicy-set.canonical-json/1.0.0"


class RiskPolicyOwnerAuthorityError(RuntimeError):
    """The trusted RiskPolicy authoring/publication boundary rejected the request."""


@dataclass(frozen=True, slots=True)
class PassThroughPolicyInput:
    policy_version: str = "1.0.0"


@dataclass(frozen=True, slots=True)
class MaxSingleNamePolicyInput:
    max_weight: str
    required_state_inputs: tuple[RiskStateRequirement, ...] = ()
    policy_version: str = "1.0.0"


@dataclass(frozen=True, slots=True)
class GrossNetExposureValidatePolicyInput:
    max_gross: str
    min_net: str
    max_net: str
    required_state_inputs: tuple[RiskStateRequirement, ...] = ()
    policy_version: str = "1.0.0"


RiskPolicyDefinitionInput: TypeAlias = (
    PassThroughPolicyInput
    | MaxSingleNamePolicyInput
    | GrossNetExposureValidatePolicyInput
)


@dataclass(frozen=True, slots=True)
class RiskPolicySetOwnerPublication:
    risk_policy_set_version_id: str
    content_sha256: str
    project_id: str
    project_context_revision_id: str
    context_identity: str
    artifact_id: str
    artifact_sha256: str
    byte_size: int
    schema_version: str
    serialization_version: str
    risk_model_requirement: str
    canonical_truth_state: str
    canonical_admission_state: str
    published_at: datetime


@dataclass(frozen=True, slots=True)
class CanonicalRiskPolicySetResult:
    policy_set: RiskPolicySetVersion
    publication: RiskPolicySetOwnerPublication


class TrustedRiskPolicyOwnerPort(Protocol):
    def _publish_authored_policy_set(
        self,
        policy_set: RiskPolicySetVersion,
        *,
        project_id: str,
        project_context_revision_id: str,
        runtime_identity: RuntimeIdentity,
        authoring_service_version: str,
        published_at: datetime,
    ) -> RiskPolicySetOwnerPublication:
        """Internal sink invoked only after trusted authoring and validation."""


class CanonicalRiskPolicyAuthoringService:
    """Build and publish policy sets from definition-level input only.

    A caller-created ``RiskPolicyDefinition`` or ``RiskPolicySetVersion`` is not an
    accepted input. Existing constructors remain the sole policy semantic validators.
    """

    service_version = "v3.canonical-riskpolicy-authoring-service/1.0.0"

    def __init__(self, owner: TrustedRiskPolicyOwnerPort) -> None:
        self._owner = owner

    def author_and_publish(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        definitions: tuple[RiskPolicyDefinitionInput, ...],
        runtime_identity: RuntimeIdentity,
        published_at: datetime,
    ) -> CanonicalRiskPolicySetResult:
        if not isinstance(runtime_identity, RuntimeIdentity):
            raise TypeError("runtime_identity must be RuntimeIdentity")
        if not isinstance(published_at, datetime) or published_at.tzinfo is None:
            raise RiskPolicyOwnerAuthorityError("published_at must be timezone-aware")
        if not isinstance(definitions, tuple) or not definitions:
            raise RiskPolicyOwnerAuthorityError("ordered policy definitions are required")

        policies: list[RiskPolicyDefinition] = []
        for definition in definitions:
            if not isinstance(
                definition,
                (
                    PassThroughPolicyInput,
                    MaxSingleNamePolicyInput,
                    GrossNetExposureValidatePolicyInput,
                ),
            ):
                raise TypeError(
                    "definitions must use the closed RiskPolicy definition input types"
                )
            common = {
                "code_version": runtime_identity.code_version,
                "runtime_profile_id": runtime_identity.runtime_profile_id,
                "policy_version": definition.policy_version,
                "truth_admission": PRE_ALPHA_CEILING,
            }
            if isinstance(definition, PassThroughPolicyInput):
                policies.append(RiskPolicyDefinition.pass_through(**common))
            elif isinstance(definition, MaxSingleNamePolicyInput):
                policies.append(
                    RiskPolicyDefinition.max_single_name(
                        max_weight=definition.max_weight,
                        required_state_inputs=definition.required_state_inputs,
                        **common,
                    )
                )
            elif isinstance(definition, GrossNetExposureValidatePolicyInput):
                policies.append(
                    RiskPolicyDefinition.gross_net_exposure_validate(
                        max_gross=definition.max_gross,
                        min_net=definition.min_net,
                        max_net=definition.max_net,
                        required_state_inputs=definition.required_state_inputs,
                        **common,
                    )
                )

        policy_set = RiskPolicySetVersion.create(tuple(policies))
        if any(
            policy.risk_model_requirement is not RiskModelRequirement.NOT_REQUIRED
            for policy in policy_set.policies
        ):
            raise RiskPolicyOwnerAuthorityError("RiskModel is NOT_REQUIRED for Risk V0")
        publication = self._owner._publish_authored_policy_set(
            policy_set,
            project_id=project_id,
            project_context_revision_id=project_context_revision_id,
            runtime_identity=runtime_identity,
            authoring_service_version=self.service_version,
            published_at=published_at,
        )
        return CanonicalRiskPolicySetResult(policy_set, publication)


__all__ = [
    "CanonicalRiskPolicyAuthoringService",
    "CanonicalRiskPolicySetResult",
    "GrossNetExposureValidatePolicyInput",
    "MaxSingleNamePolicyInput",
    "PassThroughPolicyInput",
    "RISK_POLICY_OWNER_NAMESPACE",
    "RISK_POLICY_PAYLOAD_ROLE",
    "RISK_POLICY_SERIALIZATION_VERSION",
    "RiskPolicyDefinitionInput",
    "RiskPolicyOwnerAuthorityError",
    "RiskPolicySetOwnerPublication",
    "TrustedRiskPolicyOwnerPort",
]
